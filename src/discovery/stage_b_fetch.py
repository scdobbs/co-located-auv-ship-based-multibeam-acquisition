"""Phase 2 Stage B — raw-LR fetch of the A.6 cleaned plan.

45 cruises (12 subset to intersecting swath files + 33 whole), swath + per-file
``.fnv`` only (NO ``.fbt``), to ``$DATA_ROOT/raw_lr/<cruise>/``. Idempotent,
byte-exact (HEAD Content-Length), content-verified (gzip -t / file), bounded
retries. No gridding, no manifest writes, no OAK writes.

Run modes:
  python -m src.discovery.stage_b_fetch --plan-only   # B0 only (no network)
  python -m src.discovery.stage_b_fetch               # B0..B4 (Slurm; network)
"""

from __future__ import annotations

import csv
import gzip
import json
import logging
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.ops import unary_union

from src.discovery.stage_a5_subset import (
    iter_cruise_files, parse_fnv_track, NAVCACHE, GEOPORTAL, DIRLIST,
)
from src.discovery.raw_lr_dryrun import data_dir_from_iso, resolve_data_dir
from src.discovery.stage_a6_common import REPO

log = logging.getLogger("stage_b")
TODAY = date.today().isoformat()
# Fixed campaign date — inputs (fetch list, A.5 footprints) are dated 2026-06-22
# regardless of when a recovery re-run happens (the calendar may have rolled).
STAGE_DATE = "2026-06-22"

DATA_ROOT = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
RAW_LR = DATA_ROOT / "raw_lr"
FETCH_LIST = REPO / f"reports/stage_b_fetch_list_{STAGE_DATE}.csv"
A5_FP = REPO / f"reports/discovery/stage_a5_hr_footprints_{STAGE_DATE}.gpkg"
STORAGE_RECORD = REPO / "reports/gate1_storage_setup_20260622.md"
PLAN_CSV = REPO / f"reports/discovery/stage_b_file_plan_{STAGE_DATE}.csv"
LOG_CSV = REPO / "reports/discovery/stage_b_fetch_log.csv"
REPORT = REPO / f"reports/stage_b_fetch_report_{TODAY}.md"
STATE = REPO / "reports/discovery/staging_state_20260605.json"

_HEADERS = {"User-Agent": "auv-ship-acq/0.2 (Sherlock; phase2 stage-B fetch; "
                          "stephencoledobbs@gmail.com)"}
_WORKERS = 6
_RETRIES = 3
_THROTTLE = 0.1


@dataclass
class FilePlan:
    cruise: str
    filename: str
    url: str
    advertised: int
    kind: str          # swath | nav


# --------------------------------------------------------------------------- #
# B0 — per-file plan (no network; cached listings + nav + A.5 footprints)
# --------------------------------------------------------------------------- #
def _subset_keys(cruise: str, live_hr: list[str], a5_fp: gpd.GeoDataFrame,
                 swath, nav) -> set[str]:
    """Reproduce the A.5 intersection: keys of swath files whose nav track
    crosses the live-HR buffered footprint union (or whose nav is missing —
    over-include at the margin)."""
    sub = a5_fp[(a5_fp.cruise == cruise) & (a5_fp.hr_id.isin(live_hr))]
    if sub.empty:
        return {s.key for s in swath}     # safety: keep all if no footprint
    fp_union = unary_union(list(sub.geometry))
    cdir = NAVCACHE / cruise
    keep = set()
    for s in swath:
        nr = nav.get(s.key)
        track = None
        if nr is not None and (cdir / nr.name).exists():
            track = parse_fnv_track(cdir / nr.name)
        if track is None or track.intersects(fp_union):
            keep.add(s.key)
    return keep


def _dedup_encoding(swath):
    """Honor 'one encoding per cruise': if a cruise carries BOTH a pure-vendor
    encoding (.all/.gsf[.gz]) and an MB-System encoding (.mbNN[.gz]), keep the
    larger-total group (matches the Stage-A fetch_estimate dedup)."""
    import re
    vendor, mbsys = [], []
    for s in swath:
        n = s.name.lower()
        if re.search(r"\.mb\d+(\.gz)?$", n):
            mbsys.append(s)
        elif re.search(r"\.(all|gsf)(\.gz)?$", n):
            vendor.append(s)
        else:
            mbsys.append(s)            # default unknown swath into one bucket
    if vendor and mbsys and any(re.search(r"\.mb\d+(\.gz)?$", s.name.lower()) for s in mbsys):
        vb = sum(s.bytes for s in vendor); mb = sum(s.bytes for s in mbsys)
        return vendor if vb >= mb else mbsys
    return swath


def build_plan() -> tuple[list[FilePlan], list[dict]]:
    """Returns (plan, escalated). `escalated` = cruises that could not be
    planned (no recognised swath data) — flagged, never silently dropped."""
    fl = pd.read_csv(FETCH_LIST)
    kept = fl[fl.fetch_mode != "DROP"]
    a5_fp = gpd.read_file(A5_FP)
    plan: list[FilePlan] = []
    escalated: list[dict] = []
    for _, r in kept.iterrows():
        cruise, mode = r["cruise"], r["fetch_mode"]
        iso = data_dir_from_iso(cruise, GEOPORTAL)
        url, _ = resolve_data_dir(iso, DIRLIST) if iso else (None, "")
        if not url:
            escalated.append({"cruise": cruise, "reason": "data dir unresolved"})
            continue
        recs = iter_cruise_files(url, DIRLIST)
        swath = [x for x in recs if x.kind == "swath"]
        nav = {x.key: x for x in recs if x.kind == "nav"}
        if not swath:
            # Legacy SeaBeam-classic formats the classifier doesn't recognise
            # (date-named .SBM.*/.dNNN/.rc00…), or genuinely no soundings.
            import collections
            exts = collections.Counter(
                x.name.split(".", 1)[1] if "." in x.name else "noext"
                for x in recs if x.kind != "nav")
            escalated.append({"cruise": cruise,
                              "reason": "no recognised swath data (legacy format)",
                              "exts": dict(exts.most_common(5))})
            continue
        if mode == "subset":
            live = [h for h in str(r["live_HR"]).split(";") if h]
            keys = _subset_keys(cruise, live, a5_fp, swath, nav)
            chosen = [s for s in swath if s.key in keys]
        else:
            chosen = _dedup_encoding(swath)
        for s in chosen:
            plan.append(FilePlan(cruise, s.name, s.url, s.bytes, "swath"))
            nr = nav.get(s.key)
            if nr is not None:
                plan.append(FilePlan(cruise, nr.name, nr.url, nr.bytes, "nav"))
    return plan, escalated


def write_plan(plan: list[FilePlan], escalated: list[dict]) -> None:
    PLAN_CSV.parent.mkdir(parents=True, exist_ok=True)
    with PLAN_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cruise", "filename", "url", "advertised", "kind"])
        for p in plan:
            w.writerow([p.cruise, p.filename, p.url, p.advertised, p.kind])
    swath = [p for p in plan if p.kind == "swath"]
    gb = sum(p.advertised for p in swath) / 1024**3
    by_cruise = len({p.cruise for p in plan})
    log.info("PLAN: %d cruises, %d files (%d swath + %d nav), ~%.1f GB swath",
             by_cruise, len(plan), len(swath), len(plan) - len(swath), gb)
    print(f"PLAN: {by_cruise} cruises | {len(plan)} files "
          f"({len(swath)} swath + {len(plan)-len(swath)} nav) | ~{gb:.1f} GB swath "
          f"(advertised)\nwrote {PLAN_CSV}")
    if escalated:
        print(f"ESCALATED (not fetched): {len(escalated)} cruises -> "
              f"{[e['cruise'] for e in escalated]}")


# --------------------------------------------------------------------------- #
# B1 — fetch (HEAD + idempotent GET)
# --------------------------------------------------------------------------- #
def _head_len(url: str, sess: requests.Session) -> tuple[int | None, str, int]:
    """Return (content_length|None, status_token, attempts). status_token is the
    last HTTP code (e.g. '200','404','503') or 'timeout'/'conn_err' — the
    transient-vs-systematic evidence R2 needs."""
    status = "no_attempt"
    for attempt in range(_RETRIES):
        try:
            r = sess.head(url, headers=_HEADERS, timeout=60, allow_redirects=True)
            status = str(r.status_code)
            if r.status_code == 200 and "Content-Length" in r.headers:
                return int(r.headers["Content-Length"]), status, attempt + 1
            if r.status_code >= 500:
                time.sleep(2 ** attempt); continue
            return None, status, attempt + 1          # 4xx etc — don't retry
        except requests.Timeout:
            status = "timeout"; time.sleep(2 ** attempt)
        except Exception:
            status = "conn_err"; time.sleep(2 ** attempt)
    return None, status, _RETRIES


def _fetch_one(p: FilePlan, sess: requests.Session) -> dict:
    out_dir = RAW_LR / p.cruise
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / p.filename
    clen, http_status, head_attempts = _head_len(p.url, sess)
    rec = {"cruise": p.cruise, "filename": p.filename, "url": p.url,
           "advertised": p.advertised, "head_content_length": clen,
           "received": "", "kind": p.kind, "status": "",
           "http_status": http_status, "attempts": head_attempts}
    if out.exists():
        sz = out.stat().st_size
        rec["received"] = sz
        if clen is not None and sz == clen:
            rec["status"] = "skip_present"; return rec
        if clen is not None and sz != clen:
            rec["status"] = "size_mismatch_existing"; return rec
        # clen unknown but file present & non-trivial — treat as present
        if clen is None and sz > 0:
            rec["status"] = "skip_present"; return rec
    if clen is None:
        rec["status"] = "failed"; return rec
    for attempt in range(_RETRIES):
        rec["attempts"] = head_attempts + attempt + 1
        try:
            with sess.get(p.url, headers=_HEADERS, timeout=300, stream=True) as r:
                rec["http_status"] = str(r.status_code)
                if r.status_code >= 500:
                    time.sleep(2 ** attempt); continue
                if r.status_code != 200:
                    rec["status"] = "failed"; return rec
                tmp = out.with_suffix(out.suffix + ".part")
                n = 0
                with tmp.open("wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        fh.write(chunk); n += len(chunk)
            if n == clen:
                tmp.rename(out)
                rec["received"] = n; rec["status"] = "fetched"
                time.sleep(_THROTTLE); return rec
            rec["received"] = n
            tmp.unlink(missing_ok=True)
            time.sleep(2 ** attempt)
        except requests.Timeout:
            rec["http_status"] = "timeout"; time.sleep(2 ** attempt)
        except Exception:
            rec["http_status"] = "conn_err"; time.sleep(2 ** attempt)
    rec["received"] = rec.get("received") or 0
    rec["status"] = "failed"
    return rec


def fetch_all(plan: list[FilePlan]) -> list[dict]:
    sessions = [requests.Session() for _ in range(_WORKERS)]
    results: list[dict] = []
    def job(i_p):
        i, p = i_p
        return _fetch_one(p, sessions[i % _WORKERS])
    with ThreadPoolExecutor(max_workers=_WORKERS) as ex:
        for k, rec in enumerate(ex.map(job, enumerate(plan)), 1):
            results.append(rec)
            if k % 200 == 0:
                log.info("  fetched %d/%d", k, len(plan))
    for s in sessions:
        s.close()
    return results


# --------------------------------------------------------------------------- #
# B2 — integrity
# --------------------------------------------------------------------------- #
def verify_content(path: Path) -> tuple[bool, str]:
    """(ok, reason). gzip -t for .gz; else 'file' must not look like an error page."""
    if path.name.endswith(".gz"):
        rc = subprocess.run(["gzip", "-t", str(path)], capture_output=True)
        return (rc.returncode == 0, "gzip_ok" if rc.returncode == 0
                else "gzip_test_failed")
    # uncompressed swath / nav
    rc = subprocess.run(["file", "-b", str(path)], capture_output=True, text=True)
    desc = (rc.stdout or "").strip().lower()
    if "html" in desc:
        return False, f"looks_like_html: {desc[:40]}"
    if path.suffix.lower() not in (".fnv",) and ("ascii text" in desc and path.stat().st_size < 4096):
        return False, f"tiny_ascii_suspect: {desc[:40]}"
    return True, desc[:40]


def integrity_pass(results: list[dict], verify_skip_present: bool = True) -> list[dict]:
    """Content-verify fetched files. On a recovery re-run pass
    verify_skip_present=False to skip re-checking the already-validated
    skip_present corpus (saves re-reading ~130 GB)."""
    check = ("fetched", "skip_present") if verify_skip_present else ("fetched",)
    for rec in results:
        if rec["status"] not in check:
            rec["integrity"] = "n/a" if rec["status"] != "skip_present" else "prior_verified"
            continue
        path = RAW_LR / rec["cruise"] / rec["filename"]
        if not path.exists():
            rec["integrity"] = "missing"; rec["status"] = "failed"; continue
        # byte-exact (already enforced on fetch; re-affirm for skip_present)
        clen = rec.get("head_content_length")
        if clen is not None and path.stat().st_size != clen:
            rec["integrity"] = "size_mismatch"; rec["status"] = "corrupt_content"; continue
        ok, reason = verify_content(path)
        rec["integrity"] = reason
        if not ok:
            rec["status"] = "corrupt_content"
    return results


# --------------------------------------------------------------------------- #
# B3/B4 — accounting, report, state
# --------------------------------------------------------------------------- #
def write_log(results: list[dict]) -> None:
    LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    cols = ["cruise", "filename", "url", "advertised", "head_content_length",
            "received", "kind", "status", "integrity"]
    with LOG_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            w.writerow({c: r.get(c, "") for c in cols})


def accounting(plan, results, escalated) -> dict:
    from collections import Counter, defaultdict
    planned = len(plan)
    status_counts = Counter(r["status"] for r in results)
    per_cruise = defaultdict(lambda: Counter())
    bytes_recv = defaultdict(int)
    for r in results:
        per_cruise[r["cruise"]][r["status"]] += 1
        if isinstance(r.get("received"), int):
            bytes_recv[r["cruise"]] += r["received"]
    cruises = sorted({p.cruise for p in plan})
    cruise_status = {}
    for c in cruises:
        cc = per_cruise[c]
        bad = cc["failed"] + cc["size_mismatch_existing"] + cc["corrupt_content"]
        cruise_status[c] = "complete" if bad == 0 else "incomplete_for_grid"
    total_recv = sum(bytes_recv.values())
    for e in escalated:                      # escalated cruises carried in status map
        cruise_status[e["cruise"]] = "needs_format_review"
    return {
        "planned_files": planned,
        "status_counts": dict(status_counts),
        "identity_ok": sum(status_counts.values()) == planned,
        "total_received_gb": round(total_recv / 1024**3, 2),
        "n_complete": sum(v == "complete" for v in cruise_status.values()),
        "n_incomplete": sum(v == "incomplete_for_grid" for v in cruise_status.values()),
        "n_escalated": len(escalated),
        "incomplete_cruises": [c for c, v in cruise_status.items() if v == "incomplete_for_grid"],
        "escalated": escalated,
        "cruise_status": cruise_status,
        "bytes_recv_by_cruise": {c: bytes_recv[c] for c in cruises},
        "per_cruise_counts": {c: dict(per_cruise[c]) for c in cruises},
    }


def update_state(acct: dict) -> None:
    st = json.loads(STATE.read_text())
    st["stage_b_fetch"] = {
        "generated": TODAY,
        "cruise_status": acct["cruise_status"],
        "total_received_gb": acct["total_received_gb"],
        "n_complete": acct["n_complete"],
        "n_incomplete": acct["n_incomplete"],
        "incomplete_cruises": acct["incomplete_cruises"],
    }
    STATE.write_text(json.dumps(st, indent=2))


def write_report(plan, acct, escalated) -> None:
    sc = acct["status_counts"]
    lines = [
        f"# Phase 2 — Stage B raw-LR fetch report ({TODAY})", "",
        "Fetched the A.6 cleaned plan to `$DATA_ROOT/raw_lr/`. "
        "Swath + per-file `.fnv` only; **no `.fbt`**; one encoding per cruise; "
        "no gridding; manifest untouched; no OAK writes.", "",
        "## Completeness (B3)", "",
        f"- Cleaned fetch list: **45 cruises** = "
        f"**{45 - acct['n_escalated']} planned + fetched** + "
        f"**{acct['n_escalated']} escalated `needs_format_review`** (below).",
        f"- Planned files: **{acct['planned_files']}**",
        f"- Status identity holds: **{acct['identity_ok']}** "
        f"(Σ status == planned)",
        f"- Status counts: {sc}",
        f"- Cruises `complete`: **{acct['n_complete']}**; "
        f"`incomplete_for_grid`: **{acct['n_incomplete']}**; "
        f"`needs_format_review`: **{acct['n_escalated']}**",
        f"- Total received: **{acct['total_received_gb']} GB** "
        f"(plan ≈ 131 GB; autoindex rounding ~1 %)", "",
    ]
    if escalated:
        lines += ["## ⚠️ needs_format_review (NOT fetched — legacy formats)", "",
                  "Legacy SeaBeam-classic cruises (1983–1991) whose date-named "
                  "data files are not recognised by the swath classifier; "
                  "`RP11SU81` carries only `.gps`/`.gps.inf` (no soundings). "
                  "Budgeted at ≈0 GB in the plan. Recommend assessment rule on "
                  "each (likely exclude — coarse legacy + format ambiguity) "
                  "before Stage C.", ""]
        for e in escalated:
            lines.append(f"- `{e['cruise']}`: {e['reason']}"
                         + (f" — exts {e.get('exts')}" if e.get("exts") else ""))
        lines.append("")
    if acct["incomplete_cruises"]:
        lines += ["## ⚠️ incomplete_for_grid (held from Stage C)", ""]
        for c in acct["incomplete_cruises"]:
            lines.append(f"- `{c}`: {acct['per_cruise_counts'][c]}")
        lines.append("")
    lines += ["## Per-cruise received bytes", "",
              "| cruise | GB | status |", "|---|---|---|"]
    for c in sorted(acct["bytes_recv_by_cruise"]):
        gb = acct["bytes_recv_by_cruise"][c] / 1024**3
        lines.append(f"| {c} | {gb:.2f} | {acct['cruise_status'][c]} |")
    lines += ["", "## Notes", "",
              "- MB-System not available as a Sherlock module; B2 content "
              "sanity used `gzip -t` (.gz) and `file` (uncompressed). Flag for "
              "Stage C, which needs MB-System for gridding.",
              "- Only `complete` cruises advance to Stage C; "
              "`incomplete_for_grid` wait for assessment.", ""]
    REPORT.write_text("\n".join(lines))
    print(f"wrote {REPORT}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    plan_only = "--plan-only" in sys.argv
    if not STORAGE_RECORD.exists():
        log.error("storage-setup record %s absent — STOP, do not fetch", STORAGE_RECORD)
        sys.exit(2)
    log.info("B0: building per-file plan")
    plan, escalated = build_plan()
    write_plan(plan, escalated)
    if plan_only:
        return
    log.info("B1: fetching %d files (%d workers)", len(plan), _WORKERS)
    results = fetch_all(plan)
    log.info("B2: integrity verification")
    results = integrity_pass(results)
    write_log(results)
    log.info("B3/B4: accounting + report + state")
    acct = accounting(plan, results, escalated)
    update_state(acct)
    write_report(plan, acct, escalated)
    print(f"\nStage B done: {acct['n_complete']}/45 complete, "
          f"{acct['total_received_gb']} GB, "
          f"incomplete={acct['incomplete_cruises']}, "
          f"escalated={[e['cruise'] for e in escalated]}")


if __name__ == "__main__":
    main()

