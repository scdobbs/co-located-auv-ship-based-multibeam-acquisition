"""ACQ-R08 report assembler: funnel tables, candidate tables, Pool C table, per-pool summaries, prior exposure, the
network-request-type list and the must-hold checks → REPORT_ACQ-R08_<date>.md (+ candidate tables as .md / .csv)."""
from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from src.acq_r08 import common as K
from src.acq_r01 import common as C

log = logging.getLogger("acq_r08.report")
CAND_COLS = ["pool", "source", "hr_id", "doi", "title", "platform", "hr_res_m", "lr_cruise", "lr_sonar", "lr_year", "lr_est_m", "lr_est_method",
             "cells_across_est", "ratio_est", "band_feasible", "overlap_km2_est", "tiles_est", "depth_min_m", "depth_max_m", "setting", "basin",
             "releasable", "license", "size_est_gb", "nearest_corpus_ref", "nearest_corpus_km", "within_50km", "status", "status_reason", "prior_exposure", "pool_c_rescreen"]
SHORT_COLS = ["source", "hr_id", "title", "hr_res_m", "lr_cruise", "lr_sonar", "lr_est_m", "cells_across_est", "ratio_est", "tiles_est", "depth_min_m", "depth_max_m",
              "setting", "basin", "releasable", "size_est_gb", "nearest_corpus_km", "status_reason"]
OUT_COLS = ["source", "hr_id", "title", "hr_res_m", "lr_cruise", "lr_est_m", "cells_across_est", "ratio_est", "tiles_est", "nearest_corpus_km", "status_reason"]
POOLB_COLS = ["hr_id", "title", "year", "hr_res_m", "bag_files", "lr_cruise", "lr_platform", "lr_sonar", "lr_year", "overlap_km2_est", "tiles_est",
              "depth_needed_for_band_m", "hssd_depth_band_m", "plausible_under_hssd", "nos_vessel", "nearest_corpus_ref", "nearest_corpus_km", "status_reason"]
POOLC_COLS = ["run", "hr_id", "lr", "title", "reason", "still_applies", "why", "now_in_manifest_v2_1"]


def _load(p: Path) -> pd.DataFrame:
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_csv(p, low_memory=False)
    for c in ("excluded_by", "exclusion_detail", "status", "status_reason", "not_eligible_reason", "lr_cruise"):
        if c in d.columns:
            d[c] = d[c].fillna("").astype(str).str.replace(r"\.0$", "", regex=True)
    return d


def must_hold(a: pd.DataFrame, b: pd.DataFrame, netkinds: Counter, guard: dict) -> dict:
    checks = {}
    checks["1_no_bathymetry_opened"] = {"guard_installed": guard.get("installed"), "raster_open_attempts_refused": guard.get("raster_open_refused"),
                                        "data_url_requests_refused": guard.get("data_url_refused"), "network_request_kinds": dict(netkinds),
                                        "non_metadata_kinds_present": [k for k in netkinds if not k.startswith(("catalog API", "footprint query", "ISO / JSON record", "file listing", "DOI resolver"))]}
    for name, d in (("pool_a", a), ("pool_b", b)):
        if d.empty:
            continue
        el = d[d.pool_eligible.astype(bool)]
        ex = el[el.excluded_by.astype(str).str.len() > 0]
        checks[f"2_every_excluded_has_reason_{name}"] = {"excluded": int(len(ex)), "with_reason": int(ex.exclusion_detail.astype(str).str.len().gt(0).sum()),
                                                        "not_eligible": int((~d.pool_eligible.astype(bool)).sum()),
                                                        "not_eligible_with_reason": int(d[~d.pool_eligible.astype(bool)].not_eligible_reason.astype(str).str.len().gt(0).sum())}
        ir = el[(el.excluded_by.astype(str) == "") & (el.status == "in range")]
        checks[f"3_in_range_have_named_cruise_{name}"] = {"in_range": int(len(ir)), "with_lr_cruise": int(ir.lr_cruise.astype(str).str.len().gt(0).sum()),
                                                         "with_raw_swath": int(ir.lr_raw_available.fillna(False).astype(bool).sum()) if "lr_raw_available" in ir else None}
    checks["4_no_designation"] = {"designation_files_written": False, "seed_used": None, "split_written": False}
    return checks


def main(argv=None):
    logging.basicConfig(level=logging.INFO)
    a = _load(K.OUT / "pool_a" / "hr_records.csv"); b = _load(K.OUT / "pool_b" / "nos_records.csv"); c = _load(K.OUT / "pool_c" / "pool_c_table.csv")
    fa = json.loads((K.OUT / "pool_a" / "funnel.json").read_text()) if (K.OUT / "pool_a" / "funnel.json").exists() else {}
    fb = json.loads((K.OUT / "pool_b" / "funnel.json").read_text()) if (K.OUT / "pool_b" / "funnel.json").exists() else {}
    fc = json.loads((K.OUT / "pool_c" / "summary.json").read_text()) if (K.OUT / "pool_c" / "summary.json").exists() else {}
    notes = json.loads((K.OUT / "exclusion_set_notes.json").read_text()) if (K.OUT / "exclusion_set_notes.json").exists() else {}
    netkinds = Counter(); nreq = 0
    if K.NET_LOG.exists():
        for line in K.NET_LOG.read_text().splitlines():
            try:
                netkinds[json.loads(line)["kind"]] += 1; nreq += 1
            except Exception:
                pass
    guard = {}
    for p in (K.OUT / "guard_state_pool_b.json", K.OUT / "guard_state_pool_a.json"):
        if p.exists():
            guard = json.loads(p.read_text()); break
    mh = must_hold(a, b, netkinds, guard); K.write_json(K.OUT / "must_hold_checks.json", mh)

    # ---- candidate tables
    ca = a[a.pool_eligible.astype(bool) & (a.excluded_by.astype(str) == "")].copy() if not a.empty else pd.DataFrame()
    ca_in = ca[ca.status.isin(["in range", "uncertain"])].sort_values(["status", "tiles_est"], ascending=[True, False]) if not ca.empty else ca
    ca_out = ca[ca.status == "outside range"].sort_values("tiles_est", ascending=False) if not ca.empty else ca
    cb = b[b.pool_eligible.astype(bool) & (b.excluded_by.astype(str) == "")].copy() if not b.empty else pd.DataFrame()
    cb_in = cb[cb.status.isin(["in range", "uncertain"])].sort_values("tiles_est", ascending=False) if not cb.empty else cb
    cb_out = cb[cb.status == "outside range"] if not cb.empty else cb
    for df, name in ((ca_in, "candidates_pool_a_in_range_and_uncertain"), (ca_out, "candidates_pool_a_outside_range"),
                     (cb_in, "candidates_pool_b_in_range_and_uncertain"), (cb_out, "candidates_pool_b_outside_range")):
        if not df.empty:
            cols = [x for x in (CAND_COLS if name.startswith("candidates_pool_a") else POOLB_COLS + ["status"]) if x in df.columns]
            df[cols].to_csv(K.OUT / f"{name}.csv", index=False)
            (K.OUT / f"{name}.md").write_text("\n".join([f"# {name} ({len(df)} rows)", ""] + K.md_table(df, cols, 90)))
    if not c.empty:
        (K.OUT / "pool_c_table.md").write_text("\n".join([f"# Pool C — previously rejected pairs ({len(c)} rows)", ""] + K.md_table(c, POOLC_COLS, 110)))

    L = []
    L += [f"# REPORT ACQ-R08 — metadata-only inventory of candidate pairs for a second blind test", "",
          f"**Directive:** `ACQ-R08_directive_second_blind_test_candidates_2026-10-12.md` (acquisition repo, CPU only). **Run:** {K.STAMP}, Slurm job(s) listed in `run_jobs.json`; login-node work limited to git, hashing and this assembly.",
          f"**Code:** `src/acq_r08/` (`common` installs the lockbox guard and a blindness guard: raster opens and data/image URLs are refused process-wide; every request is logged), `pool_a.py`, `pool_b.py`, `pool_c.py`, `report.py`, `preserve.py`; `src/discovery/mgds.py` gained an optional `platform_type` (default unchanged). Metadata cache: `$GROUP_SCRATCH/auv_ship_colocated_bathy/discovery_cache/acq_r08_{K.STAMP}/`.",
          "**Evidence:** `guard_selftest.json`, `must_hold_checks.json`, `network_log.jsonl`, `exclusion_set_notes.json`, `exclusion_footprints.gpkg`, `pool_a/`, `pool_b/`, `pool_c/`, the candidate tables (`candidates_pool_*.csv/.md`, `pool_c_table.csv/.md`).",
          "**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.", "", "## 1. Bottom line", ""]
    L.append("<<BULLETS>>")
    L += ["", "## 2. Funnel (per pool and source)", ""]
    if fa:
        srcs = [s for s in fa if not s.startswith("_") and s != "TOTAL"] + ["TOTAL"]
        hdr = ["source", "records found", "not a grid / non-bathy", "excl. §1.1 identity/overlap", "excl. §1.2 < 10 km", "excl. §1.3 Cal DIG", "excl. §1.4 compilation LR", "excl. §1.5 same cruise", "screened §3", "in range", "outside range", "uncertain", "flagged ≤ 50 km"]
        L += ["**Pool A (near-bottom vehicle grids)**", "", "| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)]
        for s in srcs:
            f = fa[s]
            L.append(f"| {s} | {f['records_found']} | {f['not_a_grid_or_non_bathy']} | {f['excluded_rule_1']} | {f['excluded_rule_2']} | {f['excluded_rule_3']} | {f['excluded_rule_4']} | {f['excluded_rule_5']} | {f['screened_under_s3']} | {f['in_range']} | {f['outside_range']} | {f['uncertain']} | {f.get('within_50km_flagged', '')} |")
        L += ["", f"Outside range by failed condition (Pool A total): `{json.dumps(fa['TOTAL']['outside_by_condition'])}`; uncertain by field: `{json.dumps(fa['TOTAL']['uncertain_by_field'])}`.",
              f"Harvest: {json.dumps(fa.get('_harvest', {}))}.", ""]
    if fb:
        L += ["**Pool B (NOS BAG ≤ 4 m + independent NCEI multibeam cruise)**", "", "| item | n |", "|---|---|"]
        for k, v in fb.items():
            if k in ("not_eligible_breakdown", "generated", "elapsed_s"):
                continue
            L.append(f"| {k} | {v} |")
        L += ["", f"Not eligible breakdown: `{json.dumps(fb.get('not_eligible_breakdown', {}))}`.", ""]
    if fc:
        L += ["**Pool C (previously rejected)**", "", f"Rows {fc.get('rows')} ({fc.get('distinct_hr')} distinct HR): by run `{json.dumps(fc.get('by_run'))}`; reason still applies `{json.dumps(fc.get('still_applies'))}`; re-screened under §3 (retired ratio gate): {len(fc.get('rescreen_ids', []))} → see the Pool A tables (column `pool_c_rescreen`).", ""]
    L += ["## 3. Candidate table — in range and uncertain (Pool A, then Pool B; `tiles_est` descending within status)", ""]
    if not ca_in.empty:
        L += [f"**Pool A — {int((ca_in.status == 'in range').sum())} in range, {int((ca_in.status == 'uncertain').sum())} uncertain** (all §3 fields in `candidates_pool_a_in_range_and_uncertain.csv`):", ""]
        L += K.md_table(ca_in.assign(status_reason=ca_in.status.str.upper() + ": " + ca_in.status_reason.fillna("")), SHORT_COLS, 80)
    else:
        L.append("Pool A: no in-range or uncertain candidate.")
    L.append("")
    if not cb_in.empty:
        n_show = 40
        L += [f"**Pool B — {int((cb_in.status == 'in range').sum())} in range, {int((cb_in.status == 'uncertain').sum())} uncertain**; every row is uncertain for the same reason (depth is not in any NOS catalog record → `lr_est_m` needs download). Top {min(n_show, len(cb_in))} by `tiles_est` (bbox upper bound); full table `candidates_pool_b_in_range_and_uncertain.csv`:", ""]
        L += K.md_table(cb_in.head(n_show), POOLB_COLS, 60)
    else:
        L.append("Pool B: no in-range or uncertain candidate.")
    L += ["", "## 4. Outside range (failed condition)", ""]
    if not ca_out.empty:
        L += [f"Pool A ({len(ca_out)} rows; full table `candidates_pool_a_outside_range.csv`):", ""] + K.md_table(ca_out, OUT_COLS, 80)
    if not cb_out.empty:
        L += ["", f"Pool B: {len(cb_out)} rows (all: no independent NCEI multibeam cruise over the survey, or tiles below 300); `candidates_pool_b_outside_range.csv`."]
    L += ["", "## 5. Pool C — previously rejected pairs", "", f"Full table: `pool_c_table.md` / `.csv` ({len(c)} rows). Rows whose reason no longer applies (re-screened in Pool A):", ""]
    if not c.empty:
        L += K.md_table(c[c.still_applies == "no"], POOLC_COLS, 90)
        L += ["", "Reason categories and whether they still apply:", ""]
        cats = c.groupby(["still_applies", "why"]).size().reset_index(name="n").sort_values("n", ascending=False)
        L += K.md_table(cats, ["still_applies", "why", "n"], 140)
    L.append("<<SUMMARY>>")
    L.append("<<EXPOSURE>>")
    L += ["", "## 8. Must hold (§4)", "", "```", json.dumps(mh, indent=1), "```", "",
          f"Network requests: {nreq} in total, by kind: " + "; ".join(f"{k} ×{v}" for k, v in netkinds.most_common()) + ".", ""]
    L.append("<<HOLDS>>")
    L += ["", "## 10. Not pursued", "", "- Legacy GMRT versions as LR partners; simulating old-sonar noise; re-screening Cal DIG or the Amundsen pairs (directive §8).",
          "- Any HEAD/GET on a data file to confirm access or type (a data request; refused by the guard).",
          "- Any depth lookup for Pool B outside the catalog record (GEBCO or any grid is bathymetry and may not be read).", ""]
    (K.OUT / f"REPORT_ACQ-R08_{K.STAMP}.draft.md").write_text("\n".join(L))
    print("draft written; placeholders <<BULLETS>> <<SUMMARY>> <<EXPOSURE>> <<HOLDS>> to be filled from the results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
