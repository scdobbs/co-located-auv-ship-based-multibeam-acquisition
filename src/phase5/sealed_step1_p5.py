"""ACQ-R09 §2 — Phase 5 step 1: the entry script that acquires and harmonizes the eight pre-registered sites.

Per site (spec §3.1-3.3; rulings S1-S3 of 2026-10-13), in this order:
  1. HR selection (src/phase5/hr_select.py): the site's sealed directory, companion filter, resolution group, repeat-survey
     rule, footprint of the kept grids; every grid kept / dropped / skipped is recorded with its reason;
  2. ship swath (phase5 mode only): fetch plan by the development planner (fetch_plan.plan_ncei) and the unchanged fetcher
     (fetch_swath.main --plan-csv) into OAK raw_lr_swath/<cruise>/; then a count preflight (disk == fetch manifest);
  3. ship grid by the development gridder (grid_lr: grid_region, prepare, footprint_depth, mbgrid -A2 -G3 -F1 -C0 -M);
  4. harmonize, masked rigid co-registration, validity masks, 256-tiles and qa_pass (harmonize_new main, unchanged calls);
  5. C2a lr_native and the C2c sweep (stage_c2c_recalibrate.sweep, calibration thresholds), giving k;
  6. contract-v2.1 products if the site has a k (build_products_v2_1.build, unchanged) and ship_products_usable by the
     frozen Phase 4 rule C1;
  7. eligibility, spec §3.3 items 1-3: coreg_pass, k_recoverable, cells_across, hr_res_in_range, eligible, eligibility_reason;
  8. one supplement row: the 64 columns, names and arrow types of the Phase 4 supplement plus the six eligibility columns
     (asserted in code), written to the mode's supplement path; the run record to the mode's record directory.
A data-tied failure (no kept grid, unreadable format, no overlap ...) makes the site "not testable" with its reason and
the run continues; anything else (container start, network, missing swath, write error) stops the run, which can be run
again: finished sites (site_record.json present, every listed file at its sha256) are re-used, not recomputed, and a
stopped run does not count as a completed one.  A site's outputs are built in harmonized/.staging/<pair>/ and moved to
harmonized/<pair>/ only when complete.

Modes (differ only in MODES below: site list, sealed root + allow-list, output root, fetch, supplement / record paths).
  --mode rehearsal --run-tag <tag> [--site-list <csv>] [--sites ...] [--freeze-record <json>]
       development pairs on the mock layout (scratch), no network, no sign-off.
  --mode phase5 --signoff <file> --prereg-sha256 <hex> [--freeze-record <json>]
       the eight sites of inputs/phase5_sites.csv; locks 1-4 before the allowance:
       1 sign-off holds the v3 sha256; 2 freeze record matches every file and every loaded module; 3 site list = the
       eight sites exactly (no other site, no other list); 4 no supplement and no complete phase5 run record exist.
Usage: python -m src.phase5.sealed_step1_p5 --mode rehearsal --run-tag r09
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from src.acq_r01 import common as C
from src.acq_r01.discovery_rerun import basin
from src.phase4 import guard_selftest as G4
from src.phase4 import sealed_step1 as S4
from src.phase5 import common_p5 as P
from src.phase5 import guard_p5 as GP
from src.phase5 import hr_select as HS
from src.phase5 import chain_p5 as CH

log = logging.getLogger("acq_r09.step1")
MODE_CHOICES = ("rehearsal", "phase5")
MODES = {
    "rehearsal": {"site_list": P.MOCK_SITE_LIST, "site_list_fixed": False, "sealed_root": P.MOCK_ROOT, "out_root": P.REHEARSAL_OUT, "fetch": False,
                  "supplement": P.REHEARSAL_DIR / "supplement_rehearsal.parquet", "record_dir": P.REHEARSAL_DIR, "designation": "rehearsal (development data)",
                  "allow_reason": "ACQ-R09 rehearsal (mock root, development data)"},
    "phase5": {"site_list": P.SITE_LIST, "site_list_fixed": True, "sealed_root": C.SEALED_CANDIDATES_V3, "out_root": C.OAK / "phase5", "fetch": True,
               "supplement": P.SUPPLEMENT_PHASE5, "record_dir": P.PHASE5_DIR, "designation": "phase5_sealed",
               "allow_reason": "ACQ-R09 phase5 locks passed: sign-off, freeze record, site list, single run"},
}
ELIG_COLS = ("coreg_pass", "k_recoverable", "cells_across", "hr_res_in_range", "eligible", "eligibility_reason")
RECORD_FILES = ("site_record.json", "sweep_record.json", "hr_selection.json", "grid_record.json")

Refusal = S4.Refusal
StopRun = CH.StopRun


# --------------------------------------------------------------------------- #
# locks (phase5 mode)
# --------------------------------------------------------------------------- #
def lock_signoff(signoff, prereg_sha256) -> dict:
    if not signoff or not prereg_sha256:
        raise Refusal("LOCK 1 sign-off: --signoff and --prereg-sha256 are required in phase5 mode")
    h = str(prereg_sha256).strip().lower()
    if len(h) != 64 or any(ch not in "0123456789abcdef" for ch in h):
        raise Refusal(f"LOCK 1 sign-off: --prereg-sha256 is not a sha256 hex digest: {prereg_sha256!r}")
    p = Path(signoff)
    if not p.exists():
        raise Refusal(f"LOCK 1 sign-off: {p} does not exist")
    if h not in p.read_text(errors="replace").lower():
        raise Refusal(f"LOCK 1 sign-off: {p} does not hold the pre-registration v3 sha256 {h}")
    return {"signoff": str(p), "prereg_sha256": h, "signoff_sha256": P.sha256_file(p)}


def lock_freeze_record(freeze_record) -> dict:
    p = Path(freeze_record)
    if not p.exists():
        raise Refusal(f"LOCK 2 freeze record: {p} does not exist")
    rec = json.loads(p.read_text())
    files = rec.get("files") or {}
    for need in (P.ENTRY_REL, P.SITE_LIST_REL):
        if need not in files:
            raise Refusal(f"LOCK 2 freeze record: {p} has no entry for {need}")
    bad = []
    for rel, sha in files.items():
        fp = C.REPO / rel
        got = P.sha256_file(fp) if fp.exists() else "MISSING"
        if got != sha:
            bad.append((rel, sha[:12], got[:12]))
    if bad:
        raise Refusal(f"LOCK 2 freeze record: {len(bad)} file(s) differ from {p.name}: {bad[:5]}")
    loaded = P.loaded_repo_files()
    extra = sorted(set(loaded) - set(files))
    if extra:
        raise Refusal(f"LOCK 2 freeze record: loaded repo modules not in {p.name}: {extra}")
    return {"freeze_record": str(p), "freeze_record_sha256": P.sha256_file(p), "n_files": len(files), "n_loaded_checked": len(loaded)}


def lock_site_list(a, sites: list, requested: list) -> dict:
    if a.site_list and Path(a.site_list).resolve() != P.SITE_LIST.resolve():
        raise Refusal(f"LOCK 3 site list: phase5 mode reads {P.SITE_LIST_REL} only; got --site-list {a.site_list}")
    ids = [s["hr_id"] for s in sites]
    if sorted(requested) != sorted(ids) or len(requested) != len(ids):
        raise Refusal(f"LOCK 3 site list: the run must cover exactly the {len(ids)} sites of {P.SITE_LIST_REL}; got {sorted(requested)}")
    not_sealed = [i for i in ids if i not in C.SEALED_CANDIDATE_IDS]
    if not_sealed:
        raise Refusal(f"LOCK 3 site list: {not_sealed} are not sealed ACQ-R08b candidates")
    if a.run_tag:
        raise Refusal(f"LOCK 3 site list: --run-tag is not accepted in phase5 mode (outputs go to the fixed phase5 root); got {a.run_tag!r}")
    return {"site_list": str(P.SITE_LIST), "site_list_sha256": P.sha256_file(P.SITE_LIST), "sites": ids}


def lock_single_run(cfg) -> dict:
    sp = Path(cfg["supplement"])
    if sp.exists():
        raise Refusal(f"LOCK 4 single run: {sp} already exists (sha256 {P.sha256_file(sp)}); there is one completed run")
    done = []
    for f in sorted(glob.glob(str(Path(cfg["record_dir"]) / "step1_run_phase5_*.json"))):
        try:
            r = json.loads(Path(f).read_text())
        except Exception:
            continue
        if r.get("status") == "complete" and r.get("mode") == "phase5":
            done.append(f)
    if done:
        raise Refusal(f"LOCK 4 single run: a complete phase5 run record exists: {done}")
    return {"supplement": str(sp), "complete_records_found": 0}


def enforce_phase5_locks(a, cfg, sites, requested) -> dict:
    """Order: sign-off, freeze record, site list, single run.  Any failure raises Refusal before any sealed read."""
    rec = {"lock1_signoff": lock_signoff(a.signoff, a.prereg_sha256)}
    rec["lock2_freeze_record"] = lock_freeze_record(a.freeze_record or P.FREEZE_RECORD)
    rec["lock3_site_list"] = lock_site_list(a, sites, requested)
    rec["lock4_single_run"] = lock_single_run(cfg)
    return rec


# --------------------------------------------------------------------------- #
# per site
# --------------------------------------------------------------------------- #
def _chmod_tree(d: Path, fmode=0o444):
    for p in Path(d).rglob("*"):
        if p.is_file():
            p.chmod(fmode)


def _unlock_tree(d: Path):
    for p in Path(d).rglob("*"):
        try:
            p.chmod(0o755 if p.is_dir() else 0o644)
        except OSError:
            pass


def file_hashes(d: Path) -> dict:
    return {str(p.relative_to(d)): P.sha256_file(p) for p in sorted(Path(d).rglob("*")) if p.is_file() and p.name != "site_record.json"}


def reuse_site(final: Path) -> dict:
    """A finished site of an earlier (stopped) run: every listed file at its recorded sha256, else stop."""
    rec = json.loads((final / "site_record.json").read_text())
    bad = [k for k, v in (rec.get("files") or {}).items() if not (final / k).exists() or P.sha256_file(final / k) != v]
    if bad:
        raise StopRun(f"{final.name}: a finished site's files differ from its site_record.json: {bad[:5]}")
    rec["reused"] = {"from": str(final / "site_record.json"), "sha256": P.sha256_file(final / "site_record.json"), "n_files_verified": len(rec.get("files") or {})}
    return rec


def run_site(site: dict, cfg: dict, out_root: Path, work_root: Path, a, ledger: list) -> dict:
    t0 = time.time()
    pid = site["pair_id"]
    final = out_root / "harmonized" / pid
    if (final / "site_record.json").exists():
        rec = reuse_site(final)
        ledger.append({"pair_id": pid, "item": "site", "status": "re-used", "reason": f"{rec['reused']['n_files_verified']} files verified"})
        return rec
    if final.exists():
        raise StopRun(f"{pid}: {final} exists without site_record.json; not overwritten")
    staging = out_root / "harmonized" / ".staging" / pid
    gridded = out_root / "raw_lr_gridded" / pid
    work = work_root / pid
    for d in (staging, work):
        if d.exists():
            _unlock_tree(d); shutil.rmtree(d)
    staging.mkdir(parents=True); work.mkdir(parents=True)
    site_dir = Path(cfg["sealed_root"]) / site["token"]
    rec = {"pair_id": pid, "site_name": site["site_name"], "hr_id": site["hr_id"], "lr_cruise": site["ship_cruise"], "sonar": site["sonar"],
           "ship_year": site["year"], "unit": site["unit"], "designation": cfg["designation"], "mode": cfg["mode"], "site_dir": str(site_dir),
           "path": f"harmonized/{pid}", "out_root": str(out_root), "host": P.hostname(), "cpu_model": P.cpu_model(), "started": P.utc_now()}
    fail = None
    try:
        if not site_dir.is_dir():
            raise StopRun(f"{pid}: sealed directory {site_dir} is missing")
        sel = HS.select(site, site_dir, work / "hr")
        rec["hr_selection"] = sel["record"]
        ledger.append({"pair_id": pid, "item": "hr_selection", "status": f"{len(sel['kept_raw'])} kept", "reason": f"group {sel['record']['resolution_group'].get('chosen')}"})
        if not sel["kept_raw"]:
            raise CH.SiteFail("no HR grid kept by the §3.2 rules: " + str(sel["record"]["resolution_group"].get("reason", "")))
        c = sel["footprint"].centroid; rec["footprint_centroid"] = [round(c.x, 4), round(c.y, 4)]
        if cfg["fetch"]:
            plan_csv, summ = CH.fetch_plan(site, sel["footprint"], cfg["record_dir"])
            rec["fetch_plan"] = summ
            rec["fetch"] = CH.fetch(site, plan_csv, cfg["record_dir"])
            ledger.append({"pair_id": pid, "item": "fetch", "status": "complete", "reason": f"{rec['fetch']['n_ok']} of {rec['fetch']['n_planned']} files"})
        rec["swath"] = CH.swath_preflight(site)
        rec["grid"] = CH.grid_ship(site, sel["footprint"], gridded, work / "grid")
        ledger.append({"pair_id": pid, "item": "grid", "status": "built", "reason": f"cell {rec['grid']['cell_m']} m, {rec['grid']['region_choice'][:60]}"})
        rec["harmonize"] = CH.harmonize(site, sel["kept_raw"], gridded, staging, work / "harm")
        ledger.append({"pair_id": pid, "item": "harmonize", "status": "qa pass" if rec["harmonize"]["qa_pass"] else "qa fail", "reason": json.dumps(rec["harmonize"]["qa_components"])})
        rec["c2a"] = CH.c2a(site, staging)
        rec["sweep"] = CH.sweep(site, staging, rec["c2a"]["lr_native_unrounded_m"])
        k = rec["sweep"].get("max_recoverable_k")
        ledger.append({"pair_id": pid, "item": "sweep", "status": rec["sweep"].get("status"), "reason": f"k={k}"})
        if k is not None:
            rec["products"] = CH.products(site, staging, Path(rec["swath"]["cruise_dir"]), a.nproc, a.batch_files, work / "products")
            ledger.append({"pair_id": pid, "item": "products", "status": "built" if rec["products"]["available"] else "unavailable", "reason": f"flags {rec['products'].get('flags')}"})
        else:
            rec["products"] = None
            ledger.append({"pair_id": pid, "item": "products", "status": "not built", "reason": "no k (rule C3)"})
    except CH.SiteFail as e:
        fail = str(e); rec["site_fail"] = fail
        ledger.append({"pair_id": pid, "item": "site", "status": "not testable", "reason": fail[:200]})
    rec["usable"], rec["usable_reason"] = S4.usable_rule(rec.get("products"))
    rec["eligibility"] = CH.eligibility(rec.get("harmonize"), rec.get("c2a"), rec.get("sweep"), fail)
    rec["wall_s"] = round(time.time() - t0, 1); rec["finished"] = P.utc_now()
    # records (no depth statistic, amplitude or residual may appear in them)
    hits = P.forbidden_keys({k: v for k, v in rec.items()})
    if hits:
        raise StopRun(f"{pid}: forbidden keys in the site record: {hits[:8]}")
    P.write_json(staging / "hr_selection.json", rec.get("hr_selection") or {}, mode=0o644)
    P.write_json(staging / "grid_record.json", rec.get("grid") or {}, mode=0o644)
    P.write_json(staging / "sweep_record.json", rec.get("sweep") or {}, mode=0o644)
    rec["files"] = file_hashes(staging)
    P.write_json(staging / "site_record.json", rec, mode=0o644)
    _chmod_tree(staging)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.rename(staging, final)
    shutil.rmtree(work, ignore_errors=True)
    print("SITE " + json.dumps(per_pair_entry(rec), default=str), flush=True)
    return rec


# --------------------------------------------------------------------------- #
# row, per-pair entry, supplement
# --------------------------------------------------------------------------- #
def per_pair_entry(rec: dict) -> dict:
    """The run record's per_pair[<pair id>] (RECORD_CONTRACT_phase5.md)."""
    c, sw, h, pr, el = rec.get("c2a") or {}, rec.get("sweep") or {}, rec.get("harmonize") or {}, rec.get("products"), rec["eligibility"]
    sel = rec.get("hr_selection") or {}
    return {"pair_id": rec["pair_id"], "site_name": rec["site_name"], "hr_id": rec["hr_id"], "lr_cruise": rec["lr_cruise"], "unit": rec["unit"],
            "designation": rec["designation"], "path": rec["path"], "out_root": rec["out_root"],
            "hr_native_res_m": c.get("hr_native_res_m"), "lr_native_res_m": c.get("lr_native_res_m"), "res_ratio": c.get("res_ratio"),
            "hr_res_m_unrounded": c.get("hr_res_m_unrounded"), "beam_footprint_m": c.get("beam_footprint_m"), "posting_m": c.get("posting_m"),
            "ship_grid_cell_m": (rec.get("grid") or {}).get("cell_m"), "values_source": c.get("source"),
            "max_recoverable_k": sw.get("max_recoverable_k"), "per_k": sw.get("per_k"), "k_sweep_status": sw.get("status"), "k_source": sw.get("k_source"),
            "products": ("built" if (pr and pr.get("available")) else ("unavailable" if pr else "none")),
            "products_reason": (pr or {}).get("reason") or (pr or {}).get("unavailable_reason"), "flags": (pr or {}).get("flags"),
            "ship_products_usable": rec["usable"], "usable_reason": rec["usable_reason"],
            "coreg_pass": el["coreg_pass"], "qa_components": h.get("qa_components"), "n_valid_tiles_256": h.get("n_valid_tiles_256"),
            "k_recoverable": el["k_recoverable"], "cells_across": el["cells_across"], "hr_res_in_range": el["hr_res_in_range"],
            "eligible": el["eligible"], "eligibility_reason": el["eligibility_reason"], "status": el["status"],
            "hr_grids": {"n_files": sel.get("n_files"), "n_grids_read": sel.get("n_grids_read"), "group_m": (sel.get("resolution_group") or {}).get("chosen"),
                         "kept": sel.get("kept"), "mosaic": h.get("mosaic")},
            "ship_swath_files": (rec.get("swath") or {}).get("n_swath_files"), "fetch": ({k: rec["fetch"][k] for k in ("n_ok", "n_planned", "complete")} if rec.get("fetch") else None),
            "site_record_sha256": None, "reused": bool(rec.get("reused")), "wall_s": rec.get("wall_s")}


def supplement_row(rec: dict, cols4: list) -> dict:
    c, sw, h, pr, el = rec.get("c2a") or {}, rec.get("sweep") or {}, rec.get("harmonize") or {}, rec.get("products"), rec["eligibility"]
    orr = Path(rec["out_root"])
    # paths as the v2.1 rows hold them: relative to OAK's root when the output root is on OAK (phase5), else absolute (rehearsal)
    rel = str((orr / rec["path"]).relative_to(C.OAK)) if str(orr).startswith(str(C.OAK) + "/") else str(orr / rec["path"])
    files = rec.get("files") or {}
    r = {k: None for k in cols4}
    have = "hr.tif" in files
    lon, lat = (rec.get("footprint_centroid") or [None, None])
    k = sw.get("max_recoverable_k")
    crs_hr = sorted({(g or {}).get("crs") for f, g in ((rec.get("hr_selection") or {}).get("grids") or {}).items() if (g or {}).get("status") == "kept"} - {None})
    r.update({
        "pair_id": rec["pair_id"], "site_name": rec["site_name"], "region": basin(lon, lat) if lon is not None else None,
        "hr_doi": rec["hr_id"], "hr_native_res_m": c.get("hr_native_res_m", np.nan), "lr_sonar": rec["sonar"], "lr_native_res_m": c.get("lr_native_res_m", np.nan),
        "res_ratio": c.get("res_ratio", np.nan), "depth_min_m": np.nan, "depth_max_m": np.nan, "native_crs_hr": ";".join(crs_hr) or None,
        "native_crs_lr": "EPSG:4326" if rec.get("grid") else None, "target_crs": h.get("target_crs"),
        "footprint_wkt": f"{rel}/footprint.geojson" if "footprint.geojson" in files else None, "license": P.LICENSE_MGDS,
        "verification_status": "phase5_step1", "raw_path_hr": rec["site_dir"], "raw_path_lr": (rec.get("swath") or {}).get("cruise_dir"),
        "harmonized_path_hr": f"{rel}/hr.tif" if have else None, "harmonized_path_lr": f"{rel}/lr.tif" if have else None,
        "checksum_hr": files.get("hr.tif"), "checksum_lr": files.get("lr.tif"),
        "horiz_offset_m": (h.get("coreg") or {}).get("offset_m", np.nan), "vert_offset_m": (h.get("coreg") or {}).get("dz_m", np.nan),
        "coreg_peak_psr": np.nan, "coreg_peak_eig_ratio": np.nan, "coreg_peak_agrees": np.nan,
        "coreg_status": ("pass" if (h.get("coreg") or {}).get("pass") else "fail") if h else None, "hr_source_type": "float",
        "leakage_unit": rec["unit"], "lr_cruise": rec["lr_cruise"],
        "hr_valid": f"{rel}/hr_valid.tif" if "hr_valid.tif" in files else None, "lr_valid": f"{rel}/lr_valid.tif" if "lr_valid.tif" in files else None,
        "joint_valid": f"{rel}/joint_valid.tif" if "joint_valid.tif" in files else None, "lr_valid_semantic": "real_sounding" if have else None,
        "checksum_hr_valid": files.get("hr_valid.tif"), "checksum_lr_valid": files.get("lr_valid.tif"), "checksum_joint_valid": files.get("joint_valid.tif"),
        "designation": rec["designation"], "harmonized_path": rel, "qa_status": ("pass" if h.get("qa_pass") else "fail") if h else None,
        "max_recoverable_k": float(k) if k is not None else np.nan, "k_sweep_status": sw.get("status"), "products_v2_flags": None,
        "ruling_source": "PHASE5_design_spec_2026-10-13; ACQ-R09 rulings S1-S3", "ship_products_usable": bool(rec["usable"]),
        "ship_products_usable_reason": rec["usable_reason"],
        "products_v2_1_flags": (";".join(pr.get("flags") or []) if (pr and pr.get("available")) else None),
        "manifest_version": "2.1+phase5_step1",
        "notes": (f"ACQ-R09 Phase 5 step 1 ({rec['mode']}); HR {len((rec.get('hr_selection') or {}).get('kept') or [])} kept grid(s); "
                  f"k from {sw.get('k_source')}; products {'built' if (pr and pr.get('available')) else ('unavailable' if pr else 'none')}; {el['status']}"
                  + (f": {el['eligibility_reason']}" if not el["eligible"] else "")),
    })
    for col in ELIG_COLS:
        r[col] = el[col]
    return r


def write_supplement(rows: list, sp: Path) -> dict:
    """The Phase 4 supplement's 64 fields (names and arrow types, read from its schema only) + the eligibility fields."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    s4 = pq.read_schema(P.SUPPLEMENT_PHASE4)
    extra = [pa.field("coreg_pass", pa.bool_()), pa.field("k_recoverable", pa.bool_()), pa.field("cells_across", pa.float64()),
             pa.field("hr_res_in_range", pa.bool_()), pa.field("eligible", pa.bool_()), pa.field("eligibility_reason", pa.string())]
    schema = pa.schema(list(s4) + extra)
    clean = [{k: (None if (isinstance(v, float) and np.isnan(v) and schema.field(k).type != pa.float64()) else v) for k, v in r.items()} for r in rows]
    t = pa.Table.from_pylist(clean, schema=schema)
    sp.parent.mkdir(parents=True, exist_ok=True)
    if sp.exists():
        sp.chmod(0o644)
    pq.write_table(t, sp); sp.chmod(0o444)
    back = pq.read_schema(sp)
    f4 = [(f.name, str(f.type)) for f in s4]
    got = [(f.name, str(f.type)) for f in back]
    if got[:len(f4)] != f4 or [n for n, _ in got[len(f4):]] != list(ELIG_COLS):
        raise StopRun(f"supplement schema differs from the Phase 4 supplement's: {set(got) ^ set(f4 + [(f.name, str(f.type)) for f in extra])}")
    return {"path": str(sp), "sha256": P.sha256_file(sp), "n_rows": t.num_rows, "n_columns": len(got), "schema_equal_phase4_first_64": True,
            "phase4_supplement_sha256": P.sha256_file(P.SUPPLEMENT_PHASE4), "eligibility_columns": list(ELIG_COLS)}


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=MODE_CHOICES)
    ap.add_argument("--site-list", default=None, help="rehearsal: the mock site list (phase5: refused unless it is inputs/phase5_sites.csv)")
    ap.add_argument("--sites", default=None, help="comma-separated hr ids (phase5: must be all eight)")
    ap.add_argument("--run-tag", default="", help="rehearsal: sub-directory of the scratch output root and record tag")
    ap.add_argument("--nproc", type=int, default=6); ap.add_argument("--batch-files", type=int, default=1)
    ap.add_argument("--signoff", default=None); ap.add_argument("--prereg-sha256", default=None); ap.add_argument("--freeze-record", default=None)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    t_run = time.time()
    cfg = dict(MODES[a.mode]); cfg["mode"] = a.mode
    if a.mode == "rehearsal" and not a.run_tag:
        raise Refusal("rehearsal: --run-tag is required")
    sl = Path(a.site_list) if (a.site_list and a.mode == "rehearsal") else Path(cfg["site_list"])
    sites = P.read_site_list(sl)
    ids = [s["hr_id"] for s in sites]
    requested = [x.strip() for x in a.sites.split(",") if x.strip()] if a.sites else list(ids)
    bad = [x for x in requested if x not in ids]
    if bad:
        raise Refusal(f"SITE LIST: {bad} not in the site list {sl} ({ids})")
    out_root = Path(cfg["out_root"]) / a.run_tag if (a.mode == "rehearsal") else Path(cfg["out_root"])
    work_root = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_p5" / (a.run_tag or "phase5")
    tag = a.run_tag if a.mode == "rehearsal" else time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run = {"directive": "ACQ-R09 code (Phase 5 step 1)", "mode": a.mode, "run_tag": tag, "sites": requested, "site_list": {"path": str(sl), "sha256": P.sha256_file(sl)},
           "out_root": str(out_root), "work_root": str(work_root), "sealed_root": str(cfg["sealed_root"]), "fetch": cfg["fetch"], "started": P.utc_now(),
           "host": P.hostname(), "cpu_model": P.cpu_model(), "code_commit": P.git_commit(), "nproc": a.nproc, "batch_files": a.batch_files,
           "mbsystem": C.MBSYSTEM_VERSION, "sandbox": C.SANDBOX, "container_digest": C.CONTAINER_DIGEST, "rulings": ["S1", "S2", "S3"]}
    run["fixed_input_sha256"] = P.check_fixed_inputs()
    # guard self-tests first (Phase 4 reader checks + the Phase 5 admission rules on the real names), before any allowance
    g4 = G4.run(write=False)
    real_tokens = [s["token"] for s in P.read_site_list(P.SITE_LIST)]
    mock_tokens = [s["token"] for s in sites] if a.mode == "rehearsal" else []
    g5 = GP.selftest(real_tokens, mock_tokens, out_root, work_root, decoy_mock=P.MOCK_ROOT / "MGDS_99999" / "decoy.grd")
    run["guard_selftest"] = {"phase4_reader_checks": {"n": g4["reader_checks"]["n"], "n_blocked": g4["reader_checks"]["n_blocked"], "all_passed": g4["all_passed"]},
                             "phase5": {k: v for k, v in g5.items() if k != "reader_checks"} | {"reader_checks": {k: v for k, v in g5["reader_checks"].items() if k != "rows"}}}
    if not (g4["all_passed"] and g5["all_passed"]):
        raise Refusal("guard self-test failed: " + json.dumps(run["guard_selftest"], default=str)[:400])
    run["locks"] = {}
    if a.mode == "phase5":                                     # mode branch: the locks, then the allowance
        run["locks"] = enforce_phase5_locks(a, cfg, sites, requested)
    elif a.freeze_record:
        run["locks"]["lock2_freeze_record"] = lock_freeze_record(a.freeze_record)
    if "lock2_freeze_record" in run["locks"]:
        run["freeze_record_sha256"] = run["locks"]["lock2_freeze_record"]["freeze_record_sha256"]
    toks = [s["token"] for s in sites if s["hr_id"] in requested]
    run["allowance"] = GP.install_phase5_allowance(toks, cfg["sealed_root"], [out_root, work_root], reason=cfg["allow_reason"])
    recs, rows, per_pair, ledger = {}, [], {}, []
    import pyarrow.parquet as pq
    cols4 = [f.name for f in pq.read_schema(P.SUPPLEMENT_PHASE4)]
    try:
        for s in sites:
            if s["hr_id"] not in requested:
                continue
            rec = run_site(s, cfg, out_root, work_root, a, ledger)
            recs[s["pair_id"]] = rec
            e = per_pair_entry(rec); e["site_record_sha256"] = P.sha256_file(out_root / "harmonized" / s["pair_id"] / "site_record.json")
            per_pair[s["pair_id"]] = e
            rows.append(supplement_row(rec, cols4))
    except StopRun as e:
        run.update({"status": "stopped", "error": str(e), "ledger": ledger, "pairs_done": list(per_pair), "per_pair": per_pair, "wall_s": round(time.time() - t_run, 1)})
        write_run_record(run, cfg, tag)
        log.error("STOP: %s", e)
        raise
    finally:
        GP.remove_phase5_allowance()
    run["loaded_repo_files"] = P.loaded_repo_files()
    if a.mode == "phase5" or a.freeze_record:
        run["locks"]["lock2_after_run"] = lock_freeze_record(a.freeze_record or P.FREEZE_RECORD)
    sp = Path(cfg["supplement"]) if a.mode == "phase5" else Path(cfg["supplement"]).with_name(f"supplement_rehearsal_{tag}.parquet")
    sup = write_supplement(rows, sp)
    hits = P.forbidden_keys(per_pair)
    if hits:
        raise StopRun(f"forbidden keys in per_pair: {hits[:8]}")
    run.update({"status": "complete", "supplement": sup["path"], "supplement_sha256": sup["sha256"], "supplement_schema": sup, "n_rows": sup["n_rows"],
                "pairs_done": list(per_pair), "per_pair": per_pair, "ledger": ledger, "wall_s": round(time.time() - t_run, 1), "finished": P.utc_now()})
    p = write_run_record(run, cfg, tag)
    for pid, e in per_pair.items():
        print(f"{pid:28s} hr {e['hr_native_res_m']} m  lr {e['lr_native_res_m']} m  cells {e['cells_across']}  k {e['max_recoverable_k']}  "
              f"products {e['products']} usable {e['ship_products_usable']}  {e['status']}" + (f" ({e['eligibility_reason']})" if not e["eligible"] else ""))
    print(f"run record {p} (sha256 {P.sha256_file(p)}); supplement {sp} (sha256 {sup['sha256'][:16]}…); wall {run['wall_s']} s")
    return 0


def write_run_record(run: dict, cfg: dict, tag: str) -> Path:
    p = Path(cfg["record_dir"]) / f"step1_run_{cfg['mode']}_{tag}.json"
    if p.exists():
        raise StopRun(f"run record {p} exists; not overwritten")
    return P.write_json(p, run, mode=0o444)


if __name__ == "__main__":
    sys.exit(main())
