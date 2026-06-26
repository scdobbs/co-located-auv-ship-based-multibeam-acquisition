"""Phase 2 Stage B-recovery (Track R) — idempotent re-run of the fetch plan.

R0 clears the AR26 bad partial; R1 re-runs the plan (skip_present for the
18,339 good files, retry the 106 failed) with HTTP-status instrumentation;
R2 emits failed-file detail with a transient-vs-systematic verdict; R3
re-evaluates cruise completeness + the watch-cruise overlap recovery; R4 runs
the legacy-7 HR-dependency diagnostic.

Does NOT overwrite the original `stage_b_fetch_report` (append-only). Writes
recovery-specific artifacts; the narrative recovery report is written
separately. No gridding, no manifest/OAK writes.
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

from src.discovery.stage_b_fetch import (
    build_plan, fetch_all, integrity_pass, RAW_LR, LOG_CSV, STATE, REPO,
    STAGE_DATE,
)
from src.discovery.stage_a6_common import THIN_OVERLAP

log = logging.getLogger("stage_b_recovery")
FETCH_LIST = REPO / f"reports/stage_b_fetch_list_{STAGE_DATE}.csv"
DETAIL_CSV = REPO / "reports/discovery/stage_b_failed_files_detail.csv"
RECOVERY_JSON = REPO / f"reports/discovery/stage_b_recovery_{STAGE_DATE}.json"

LEGACY7 = ["AII8L11", "EW9914", "RC2901", "PASC04WT", "PASC02WT",
           "RP11SU81", "TUNE04WT"]
AR26_BAD = ("AR26", "9999.all.mb58.gz")     # R0 sanctioned deletion


# --------------------------------------------------------------------------- #
def r0_clear_ar26() -> dict:
    """Delete the AR26 bad partial (sanctioned). On disk it is ~11 MB while the
    server's HEAD said 1275 B (recorded in the prior fetch log) — a clear bad
    partial, not validated data. The R1 re-run re-fetches it with the correct
    URL and verifies byte-exact + integrity."""
    cruise, fname = AR26_BAD
    path = RAW_LR / cruise / fname
    info = {"file": str(path), "existed": path.exists(),
            "prior_log_head_content_length": 1275}
    if path.exists():
        info["on_disk_bytes"] = path.stat().st_size
        path.unlink()
        info["deleted"] = True
        log.warning("R0: deleted AR26 bad partial %s (%d bytes on disk vs 1275 advertised)",
                    fname, info["on_disk_bytes"])
    return info


def r2_detail_and_verdict(results: list[dict]) -> tuple[list[dict], dict]:
    """Write failed-file detail; classify each cruise's residual failures."""
    still = [r for r in results if r["status"] in ("failed", "size_mismatch_existing")]
    DETAIL_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ["cruise", "filename", "url", "http_status", "head_content_length",
            "received", "attempts"]
    with DETAIL_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in still:
            w.writerow({c: r.get(c, "") for c in cols})
    # per-cruise verdict
    by_cruise = defaultdict(list)
    for r in still:
        by_cruise[r["cruise"]].append(r)
    verdict = {}
    for c, rs in by_cruise.items():
        codes = Counter(str(r.get("http_status")) for r in rs)
        n404 = sum(v for k, v in codes.items() if k.startswith("4"))
        if n404 == len(rs) and len(rs) > 0:
            verdict[c] = {"verdict": "systematic_needs_path_fix", "codes": dict(codes)}
        else:
            verdict[c] = {"verdict": "transient_residual", "codes": dict(codes)}
    return still, verdict


def r3_cruise_status(plan, results, residual_verdict) -> dict:
    """Recompute complete vs incomplete; report flips and watch-cruise overlap."""
    planned_by_cruise = defaultdict(int)
    for p in plan:
        planned_by_cruise[p.cruise] += 1
    status_by_cruise = defaultdict(Counter)
    for r in results:
        status_by_cruise[r["cruise"]][r["status"]] += 1
    cruise_status = {}
    for c in planned_by_cruise:
        cc = status_by_cruise[c]
        bad = cc["failed"] + cc["size_mismatch_existing"] + cc["corrupt_content"]
        cruise_status[c] = "complete" if bad == 0 else "incomplete_for_grid"
    # watch cruises: recovered fraction of overlap (= all planned, since subset)
    watch = {}
    for c in sorted(THIN_OVERLAP):
        tot = planned_by_cruise.get(c, 0)
        good = status_by_cruise[c]["fetched"] + status_by_cruise[c]["skip_present"]
        watch[c] = {
            "overlap_files_total": tot,
            "overlap_files_recovered": good,
            "fraction_recovered": round(good / tot, 3) if tot else None,
            "status": cruise_status.get(c),
            "exclude_candidate": cruise_status.get(c) == "incomplete_for_grid",
        }
    return {"cruise_status": cruise_status, "watch": watch}


def r4_legacy_dependency() -> dict:
    fl = pd.read_csv(FETCH_LIST)
    live = {}
    for _, r in fl[fl.fetch_mode != "DROP"].iterrows():
        live[r["cruise"]] = [h for h in str(r.get("live_HR", "")).split(";") if h]
    # HR -> cruises that serve it (across the kept plan)
    hr_to_cruises = defaultdict(list)
    for c, hrs in live.items():
        for h in hrs:
            hr_to_cruises[h].append(c)
    out = {}
    for c in LEGACY7:
        hrs = live.get(c, [])
        rows = []
        for h in hrs:
            others = [x for x in hr_to_cruises[h] if x != c]
            rows.append({"hr_id": h, "also_served_by": others,
                         "sole_dependency": len(others) == 0})
        out[c] = {"live_HR": hrs, "hr_detail": rows,
                  "note": "RP11SU81 carries only .gps (no soundings) -> hard exclude"
                          if c == "RP11SU81" else ""}
    return out


def merge_log(results: list[dict]) -> None:
    """Update stage_b_fetch_log.csv: prior rows overridden by this run's rows
    (same cruise/filename), so skip_present + recovered statuses are current."""
    prior = pd.read_csv(LOG_CSV) if LOG_CSV.exists() else pd.DataFrame()
    new = pd.DataFrame(results)
    if not prior.empty:
        key = ["cruise", "filename"]
        prior = prior.set_index(key)
        new_idx = new.set_index(key)
        prior = prior[~prior.index.isin(new_idx.index)]
        merged = pd.concat([prior.reset_index(), new], ignore_index=True)
    else:
        merged = new
    merged.to_csv(LOG_CSV, index=False)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log.info("R0: clear AR26 partial")
    r0 = r0_clear_ar26()
    log.info("R1: build plan + idempotent re-run")
    plan, escalated = build_plan()
    results = fetch_all(plan)
    results = integrity_pass(results, verify_skip_present=False)
    merge_log(results)
    log.info("R2: failed-file detail + verdict")
    still, residual_verdict = r2_detail_and_verdict(results)
    log.info("R3: cruise status + watch overlap")
    r3 = r3_cruise_status(plan, results, residual_verdict)
    log.info("R4: legacy-7 HR dependency")
    r4 = r4_legacy_dependency()

    status_counts = Counter(r["status"] for r in results)
    cs = r3["cruise_status"]
    summary = {
        "generated": STAGE_DATE,
        "r0_ar26": r0,
        "status_counts": dict(status_counts),
        "n_complete": sum(v == "complete" for v in cs.values()),
        "n_incomplete": sum(v == "incomplete_for_grid" for v in cs.values()),
        "incomplete_cruises": sorted(c for c, v in cs.items() if v == "incomplete_for_grid"),
        "residual_failed_files": len(still),
        "residual_verdict": residual_verdict,
        "watch_cruises": r3["watch"],
        "legacy7_dependency": r4,
        "escalated_legacy": [e["cruise"] for e in escalated],
    }
    RECOVERY_JSON.write_text(json.dumps(summary, indent=2, default=str))

    # update staging_state
    st = json.loads(STATE.read_text())
    st["stage_b_recovery"] = {
        "generated": STAGE_DATE,
        "n_complete": summary["n_complete"],
        "n_incomplete": summary["n_incomplete"],
        "incomplete_cruises": summary["incomplete_cruises"],
        "residual_failed_files": summary["residual_failed_files"],
        "cruise_status": cs,
    }
    STATE.write_text(json.dumps(st, indent=2))

    print("\n=========== STAGE B RECOVERY SUMMARY ===========")
    print(f"status counts        : {dict(status_counts)}")
    print(f"complete / incomplete: {summary['n_complete']} / {summary['n_incomplete']}")
    print(f"residual failed files: {len(still)}")
    print(f"incomplete cruises   : {summary['incomplete_cruises']}")
    for c, v in r3["watch"].items():
        print(f"  watch {c}: {v['overlap_files_recovered']}/{v['overlap_files_total']} "
              f"overlap recovered, exclude_candidate={v['exclude_candidate']}")
    print(f"residual verdicts    : { {c: v['verdict'] for c, v in residual_verdict.items()} }")
    print(f"wrote {RECOVERY_JSON}\nwrote {DETAIL_CSV}")


if __name__ == "__main__":
    main()
