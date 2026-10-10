"""ACQ-R06 Part A — Phase 4 step 1: the entry script that completes a sealed pair's manifest row.

Per pair, in this order (directive Part A):
  1. read the pair's harmonized hr.tif, lr.tif and the three masks — no re-gridding, no re-harmonization, no new
     co-registration; the recorded co-registration and qa_status stand;
  2. hr_native_res_m and lr_native_res_m by the C2a rule exactly as src/acq_r01/harmonize_new.py computes them for a
     new pair: beam footprint 2·depth·tan(bw/2) at the MEDIAN DEPTH OF ALL VALID CELLS OF THE HARMONIZED lr.tif, bw from
     src/acq_r01/grid_lr.beamwidth_for(<sonar string>), posting = |lr.tif pixel size|, lr_native = max(footprint, posting);
  3. the C2c sweep the chain calls — src/discovery/stage_c2c_recalibrate.sweep on the harmonized pair with the
     reports/discovery/stage_c2c_calibration.json thresholds — giving max_recoverable_k and k_sweep_status; a pair in
     PRIOR_K_PAIRS (the two lockbox pairs) keeps its prior k and is not swept;
  4. if the pair has a k: contract-v2.1 ship products on the grid of lr.tif (src/acq_r03/build_products_v2_1.build,
     unchanged) with products.json and its QA; a pair with no k gets no products;
  5. ship_products_usable by rule C1;
  6. one supplement row with the manifest v2.1 columns.

Modes.  --mode rehearsal: development pairs, guard fully on, outputs under a scratch root (nothing on OAK is written).
        --mode phase4: the five sealed pairs only; locks: sign-off file with the pre-registration sha256, freeze record
        (sha256 of this script and of every repo file it imports), pair list exactly the five, supplement absent (one run).
The two modes differ only in the pair list, the guard allow-list and the output root (MODES); the phase4 locks and the
phase4 allowance are the only other places that consult the mode (see the report's mode-branch table).

Usage: python -m src.phase4.sealed_step1 --mode rehearsal --run-tag full [--pairs a,b] [--nproc 6] [--batch-files 1]
       python -m src.phase4.sealed_step1 --mode phase4 --signoff <file> --prereg-sha256 <hex> [--freeze-record <json>]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from src.acq_r01 import common as C
from src.acq_r01.grid_lr import beamwidth_for
from src.acq_r01 import build_products as V1          # noqa: F401  (chain: imported so that the freeze record sees it)
from src.acq_r01 import build_products_v2 as V2       # noqa: F401
from src.acq_r03 import common as R3
from src.acq_r03 import build_products_v2_1 as V21
from src.discovery import stage_c5_spectral           # noqa: F401
from src.discovery import stage_c2c_recalibrate as C2C
from src.phase4 import common as P
from src.phase4 import guard_selftest as G

log = logging.getLogger("acq_r06.step1")
MODE_CHOICES = ("rehearsal", "phase4")

# The only mode-dependent table: pair list, guard allow-list, output root (+ the supplement path under that root).
MODES = {
    "rehearsal": {"pairs": tuple(P.REHEARSAL10), "allow": (), "out_root": P.SCRATCH_ROOT, "supplement": P.SUPPLEMENT_REHEARSAL},
    "phase4": {"pairs": tuple(P.SEALED_PAIRS), "allow": P.sealed_allow_tokens(), "out_root": C.OAK, "supplement": P.SUPPLEMENT_PHASE4},
}


class Refusal(RuntimeError):
    """A lock or a pair-list refusal; raised before any sealed file is opened."""


class StopRun(RuntimeError):
    """Rule C4: any error that is not a data-tied builder failure stops the run before the supplement is written."""


# --------------------------------------------------------------------------- #
# locks (phase4 mode)
# --------------------------------------------------------------------------- #
def lock_signoff(signoff, prereg_sha256):
    if not signoff or not prereg_sha256:
        raise Refusal("LOCK 1 sign-off: --signoff and --prereg-sha256 are required in phase4 mode")
    h = str(prereg_sha256).strip().lower()
    if len(h) != 64 or any(ch not in "0123456789abcdef" for ch in h):
        raise Refusal(f"LOCK 1 sign-off: --prereg-sha256 is not a sha256 hex digest: {prereg_sha256!r}")
    p = Path(signoff)
    if not p.exists():
        raise Refusal(f"LOCK 1 sign-off: {p} does not exist")
    txt = p.read_text(errors="replace")
    if h not in txt.lower():
        raise Refusal(f"LOCK 1 sign-off: {p} does not hold the pre-registration sha256 {h}")
    return {"signoff": str(p), "prereg_sha256": h, "signoff_sha256": P.sha256_file(p)}


def lock_freeze_record(freeze_record):
    p = Path(freeze_record)
    if not p.exists():
        raise Refusal(f"LOCK 2 freeze record: {p} does not exist")
    rec = json.loads(p.read_text())
    files = rec.get("files") or {}
    me = "src/phase4/sealed_step1.py"
    if me not in files:
        raise Refusal(f"LOCK 2 freeze record: {p} has no entry for {me}")
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


def lock_pair_list(pairs, run_tag):
    want = set(P.SEALED_PAIRS)
    if set(pairs) != want or len(pairs) != len(want):
        raise Refusal(f"LOCK 3 pair list: must be exactly the five sealed pairs {sorted(want)}; got {sorted(pairs)}")
    if run_tag:
        raise Refusal(f"LOCK 3 pair list: --run-tag is not accepted in phase4 mode (outputs go to the pairs' own directories); got {run_tag!r}")
    return {"pairs": sorted(pairs)}


def lock_single_run(supplement):
    p = Path(supplement)
    if p.exists():
        raise Refusal(f"LOCK 4 single run: {p} already exists (sha256 {P.sha256_file(p)}); there is one run")
    return {"supplement": str(p)}


def enforce_phase4_locks(a, pairs, cfg) -> dict:
    """Order: sign-off, freeze record, pair list, single run.  Any failure raises Refusal before any sealed read."""
    rec = {}
    rec["lock1_signoff"] = lock_signoff(a.signoff, a.prereg_sha256)
    rec["lock2_freeze_record"] = lock_freeze_record(a.freeze_record or P.FREEZE_RECORD)
    rec["lock3_pair_list"] = lock_pair_list(pairs, a.run_tag)
    rec["lock4_single_run"] = lock_single_run(cfg["supplement"])
    return rec


# --------------------------------------------------------------------------- #
# the chain, per pair
# --------------------------------------------------------------------------- #
def pair_dir_of(row) -> Path:
    """The pair's harmonized directory on OAK (manifest harmonized_path; harmonized_path_lr's parent when present)."""
    hp = row.get("harmonized_path_lr")
    if isinstance(hp, str) and hp:
        return C.OAK / Path(hp).parent
    return C.OAK / str(row["harmonized_path"])


def read_inputs(pid: str, pdir: Path) -> dict:
    """Step 1: open hr.tif, lr.tif and the three masks; record shapes, CRS, nodata and the file hashes.  Nothing is
    re-gridded, re-harmonized or co-registered."""
    out = {"pair_dir": str(pdir), "files": {}}
    for name in ("hr.tif", "lr.tif", "hr_valid.tif", "lr_valid.tif", "joint_valid.tif"):
        p = pdir / name
        if not p.exists():
            raise StopRun(f"{pid}: {p} is missing")
        with rasterio.open(p) as ds:
            out["files"][name] = {"shape": [ds.height, ds.width], "crs": ds.crs.to_string() if ds.crs else None, "nodata": ds.nodata,
                                  "dtype": ds.dtypes[0], "pixel": [abs(ds.transform.a), abs(ds.transform.e)], "sha256": P.sha256_file(p)}
    f = out["files"]
    if f["hr.tif"]["crs"] != f["lr.tif"]["crs"]:
        raise StopRun(f"{pid}: hr.tif CRS {f['hr.tif']['crs']} != lr.tif CRS {f['lr.tif']['crs']}")
    for m in ("hr_valid.tif", "lr_valid.tif", "joint_valid.tif"):
        if f[m]["shape"] != f["hr.tif"]["shape"]:
            raise StopRun(f"{pid}: mask {m} shape {f[m]['shape']} != hr.tif shape {f['hr.tif']['shape']}")
    out["target_crs"] = f["lr.tif"]["crs"]
    return out


def sonar_for(pid: str, cruise: str, row) -> tuple:
    """The sonar string the C2a rule's beam-width lookup receives.  The ACQ-R02 chain reads it from the cruise's grid
    record (reports_post_grl_review/ACQ-R02/grid/<cruise>.json, 'sonar' = the --sonar argument of grid_lr); for a
    cruise without such a record (June pairs, the lockbox cruises) the manifest row's lr_sonar is the only recorded
    string.  Returns (sonar, source, grid_record or None)."""
    gp = P.R02 / "grid" / f"{cruise}.json"
    if gp.exists():
        g = json.loads(gp.read_text())
        return str(g.get("sonar", "")), f"ACQ-R02 grid record grid/{cruise}.json:sonar", g
    s = row.get("lr_sonar")
    if isinstance(s, str) and s:
        return s, "manifest v2.1 lr_sonar (no ACQ-R02 grid record for this cruise)", None
    raise StopRun(f"{pid}: no sonar string: neither ACQ-R02 grid/{cruise}.json nor manifest lr_sonar")


def c2a_rule(pid: str, pdir: Path, cruise: str, row) -> dict:
    """Step 2, exactly src/acq_r01/harmonize_new.py main() (the 'development only: lr_native (C2a max rule)' block):
         hr_res   = |hr.tif pixel size|                                   -> hr_native_res_m = round(hr_res, 3)
         lr_arr   = lr.tif read masked -> NaN;  posting = |lr.tif pixel size|
         depth    = |nanmedian(lr_arr)|  (all valid cells of the harmonized lr.tif; grid record footprint_depth_m only if none)
         bw       = beamwidth_for(sonar)[0];  footprint = 2 * depth * tan(bw/2)
         lr_native = max(footprint, posting)                              -> lr_native_res_m = round(lr_native, 2)
       res_ratio = round(lr_native_res_m / hr_native_res_m, 2) as manifest_v2.py."""
    with rasterio.open(pdir / "hr.tif") as ds:
        hr_res = abs(ds.transform.a)
    with rasterio.open(pdir / "lr.tif") as ds:
        lr_arr = ds.read(1, masked=True).filled(np.nan); posting = abs(ds.transform.a)
    sonar, sonar_source, grid_rec = sonar_for(pid, cruise, row)
    bw, bw_key = beamwidth_for(sonar)
    if np.isfinite(lr_arr).any():
        depth = abs(float(np.nanmedian(lr_arr))); depth_basis = "median of all valid cells of the harmonized lr.tif (harmonize_new.py)"
    else:
        if grid_rec is None:
            raise StopRun(f"{pid}: lr.tif has no finite cell and there is no grid record footprint_depth_m")
        depth = float(grid_rec["footprint_depth_m"]); depth_basis = "grid record footprint_depth_m (lr.tif has no finite cell)"
    footprint = 2 * depth * math.tan(math.radians(bw / 2))
    lr_native = max(footprint, posting)
    hr_native_res_m = round(hr_res, 3); lr_native_res_m = round(lr_native, 2)
    return {"hr_native_res_m": hr_native_res_m, "lr_native_res_m": lr_native_res_m, "lr_native_unrounded_m": lr_native,
            "res_ratio": round(lr_native_res_m / hr_native_res_m, 2) if hr_native_res_m else None,
            "beam_footprint_m": round(footprint, 2), "posting_m": round(posting, 2), "depth_m": round(depth, 1), "depth_basis": depth_basis,
            "beamwidth_deg": bw, "beamwidth_key": bw_key, "sonar": sonar, "sonar_source": sonar_source,
            "rule": "max(footprint, posting) (C2a)", "code": "src/acq_r01/harmonize_new.py main(): lr_native block; src/acq_r01/grid_lr.py beamwidth_for"}


def prior_k(pid: str, row) -> dict:
    """Step 3 for PRIOR_K_PAIRS: the manifest row's k if it holds one, else the June C2c sweep record's k."""
    k = row.get("max_recoverable_k"); st = row.get("k_sweep_status")
    if k is not None and not (isinstance(k, float) and np.isnan(k)):
        return {"status": st if isinstance(st, str) else "ok", "max_recoverable_k": int(k), "k_source": "manifest v2.1 row", "swept": False}
    j = json.loads(P.JUNE_C2C_SWEEP.read_text())
    for r in j.get("pairs", []):
        if r.get("pair_id") == pid:
            kk = r.get("max_recoverable_k")
            return {"status": r.get("status"), "max_recoverable_k": (int(kk) if kk is not None else None), "lr_native_m_of_record": r.get("lr_native_m"),
                    "k_source": "June C2c sweep record reports/discovery/stage_c2c_sweep.json (manifest v2.1 row holds no k)", "swept": False}
    raise StopRun(f"{pid}: in PRIOR_K_PAIRS but neither the manifest row nor the June sweep record holds a k")


def sweep(pid: str, pdir: Path, lr_native_unrounded: float) -> dict:
    """Step 3: the sweep the ACQ-R02 chain runs (harmonize_new.py: C2C.pair_dir redirected to the pair's directory,
    thresholds from stage_c2c_calibration.json, the unrounded lr_native)."""
    thr = json.loads(P.C2C_CALIBRATION.read_text())["thresholds"]
    C2C.pair_dir = lambda p: pdir                     # the chain's own redirection (harmonize_new.py)
    rec = C2C.sweep(pid, lr_native_unrounded, thr)
    rec["thresholds"] = thr; rec["k_source"] = "stage_c2c_recalibrate.sweep (this run)"; rec["swept"] = True
    rec["code"] = "src/discovery/stage_c2c_recalibrate.py sweep -> src/discovery/stage_c5_spectral.py perk_curve/perk_verdict"
    return rec


def classify_builder_error(e: BaseException) -> tuple:
    """Rule C2: data-tied builder failures (unsupported sonar format, a format MB-System cannot read) -> products
    unavailable, the pair stays in.  Container timeouts / start failures, missing swath, incomplete fetches and
    anything else -> rule C4 (stop)."""
    msg = str(e)
    if isinstance(e, ValueError) and "cannot infer MB format" in msg:
        return True, "unsupported_format: " + msg[:200]
    if isinstance(e, RuntimeError) and "mblist call(s) failed" in msg:
        if "timeout" in msg or "'rc': 255" in msg or "'rc': -9" in msg:
            return False, "mblist failed by container timeout / start failure (not data-tied): " + msg[:200]
        return True, "mblist_failed_on_file (MB-System non-zero on the swath file): " + msg[:300]
    return False, f"{type(e).__name__}: {msg[:300]}"


def unavailable_products_json(pid: str, lr_path: Path, reason: str) -> dict:
    """Rule C2: products.json with every available flag false (contract v2.1 §5 structure, as build_products_v2_1.write_unavailable)."""
    return {"contract_version": V21.CONTRACT, "pair_id": pid, "lr_tif_path": str(lr_path),
            "available": {k: False for k in V21.AVAIL}, "unavailable_reason": reason,
            "source": {"kind": "none", "files": [], "mb_format": None, "processing_mode": None}, "beam_angle_method": None,
            "software": {"mbsystem": C.MBSYSTEM_VERSION, "container": f"apptainer sandbox {C.SANDBOX}", "code_commit": C.git_commit()},
            "commands": [], "grid": None,
            "frame_offset": {"applied": False, "dx_m": 0.0, "dy_m": 0.0, "basis": "none", "evidence": "builder failed on the data; not applicable"},
            "qa_vs_lr_tif": None, "created": datetime.now(timezone.utc).isoformat()}


def build_products(pid: str, pdir: Path, out_dir: Path, cruise: str, nproc: int, batch_files: int) -> dict:
    """Step 4: src/acq_r03/build_products_v2_1.build, unchanged, on a staging copy of the pair's lr.tif (so that the
    builder never writes next to the source); the finished ship_products_v2_1/ is copied into out_dir."""
    stage = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r06_step1" / pid
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copyfile(pdir / "lr.tif", stage / "lr.tif")
    R3.REPORT_DIR = out_dir                           # the builder's run summary json lands in the pair's output directory
    cruise_dir = C.RAW_SWATH_OAK / cruise
    src_kind = "provider_swath" if cruise.startswith("PANGAEA_") else "ncei_swath"   # as harmonize_new.py
    t0 = time.time()
    try:
        res = V21.build([(pid, stage)], cruise, cruise_dir, src_kind, nproc, batch_files)
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        data_tied, reason = classify_builder_error(e)
        shutil.rmtree(stage, ignore_errors=True)
        if not data_tied:
            raise StopRun(f"{pid}: product builder failed (not data-tied; rule C4): {reason}") from e
        dst = out_dir / V21.OUT_NAME; dst.mkdir(parents=True, exist_ok=True)
        pj = unavailable_products_json(pid, pdir / "lr.tif", reason)
        P.write_json(dst / "products.json", pj)
        return {"available": False, "reason": reason, "error_class": type(e).__name__, "rule": "C2 data-tied builder failure",
                "wall_s": round(time.time() - t0, 1), "files": {"products.json": P.sha256_file(dst / "products.json")}, "products_json": pj}
    wall = time.time() - t0
    src_dir = stage / V21.OUT_NAME; dst = out_dir / V21.OUT_NAME
    if dst.exists():
        for p in dst.iterdir():
            p.chmod(0o644)
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    copied = {}
    for p in sorted(src_dir.iterdir()):
        shutil.copyfile(p, dst / p.name); (dst / p.name).chmod(0o444); copied[p.name] = P.sha256_file(dst / p.name)
    pj = json.loads((dst / "products.json").read_text())
    ex = json.loads((dst / "products_extra.json").read_text()) if (dst / "products_extra.json").exists() else {}
    shutil.rmtree(stage, ignore_errors=True)
    per_file = ex.get("per_file", [])
    n_listed = len(pj["source"]["files"]); n_read = len(per_file); n_rc0 = sum(1 for r in per_file if r.get("rc") == 0)
    if batch_files <= 1 and (n_read != n_listed or n_rc0 != n_listed):
        raise StopRun(f"{pid}: {n_listed} swath files listed, {n_read} read, {n_rc0} with rc 0 — a listed file was not read")
    avail = bool(pj.get("available")) and all(pj["available"].values())
    return {"available": avail, "unavailable_reason": pj.get("unavailable_reason"), "flags": list((pj.get("qa_vs_lr_tif") or {}).get("flags") or []),
            "qa_vs_lr_tif": pj.get("qa_vs_lr_tif"), "mb_format": pj["source"]["mb_format"], "n_files_listed": n_listed, "n_files_read": n_read,
            "n_files_rc0": n_rc0, "beam_angle_method": pj.get("beam_angle_method"), "frame_offset": pj.get("frame_offset"),
            "matches_lr_tif": (pj.get("grid") or {}).get("matches_lr_tif"), "wall_s": round(wall, 1), "nproc": nproc, "batch_files": batch_files,
            "files": copied, "builder": "src/acq_r03/build_products_v2_1.py build (unchanged)", "result": res[0] if res else None,
            "lr_tif_source": str(pdir / "lr.tif"), "staging_note": "products.json lr_tif_path names the node-local staging copy of lr.tif (same bytes; sha256 in inputs)"}


def usable_rule(products) -> tuple:
    """Rule C1: ship_products_usable = true iff the products were built (available: true) and products.json carries none
    of the contract-v2.1 flags registration_shift, vertical_offset, insufficient_overlap."""
    if products is None:
        return False, "no products (no k)"
    if not products.get("available"):
        return False, f"products unavailable: {products.get('reason') or products.get('unavailable_reason')}"
    flags = [f for f in (products.get("flags") or []) if f in P.CONTRACT_V21_FLAGS]
    if flags:
        return False, "flagged: " + ";".join(flags) + " (contract v2.1, rule C1)"
    return True, "available, no contract-v2.1 flags (rule C1)"


def supplement_row(row: pd.Series, rec: dict, mode: str) -> dict:
    """Step 6: the pair's manifest v2.1 row with the step-1 quantities set; empty path / CRS columns of a sealed row are
    filled from the files step 1 read.  Columns = manifest v2.1 columns."""
    r = row.to_dict(); r["pair_id"] = row.name                 # the row comes from the manifest indexed by pair_id
    c2a, sw, pr = rec["c2a"], rec["sweep"], rec.get("products")
    r["hr_native_res_m"] = c2a["hr_native_res_m"]; r["lr_native_res_m"] = c2a["lr_native_res_m"]; r["res_ratio"] = c2a["res_ratio"]
    k = sw.get("max_recoverable_k")
    r["max_recoverable_k"] = float(k) if k is not None else np.nan
    r["k_sweep_status"] = sw.get("status")
    r["products_v2_1_flags"] = (";".join(pr.get("flags") or []) if (pr is not None and pr.get("available")) else None)
    r["ship_products_usable"] = rec["usable"]; r["ship_products_usable_reason"] = rec["usable_reason"]
    rel = str(row["harmonized_path"])
    filled = []
    for col, name in (("harmonized_path_hr", "hr.tif"), ("harmonized_path_lr", "lr.tif"), ("hr_valid", "hr_valid.tif"),
                      ("lr_valid", "lr_valid.tif"), ("joint_valid", "joint_valid.tif")):
        v = r.get(col)
        if not (isinstance(v, str) and v):
            r[col] = f"{rel}/{name}"; filled.append(col)
    if not (isinstance(r.get("target_crs"), str) and r["target_crs"]):
        r["target_crs"] = rec["inputs"]["target_crs"]; filled.append("target_crs")
    note = (f"ACQ-R06 step1 ({mode}, {P.utc_now()[:10]}): lr_native by the ACQ-R02 chain C2a rule (sonar '{c2a['sonar']}' from {c2a['sonar_source']}, "
            f"bw {c2a['beamwidth_deg']} deg, depth {c2a['depth_m']} m = {c2a['depth_basis']}, footprint {c2a['beam_footprint_m']} m, posting {c2a['posting_m']} m); "
            f"k from {sw.get('k_source')}; products {'built' if (pr and pr.get('available')) else ('unavailable' if pr else 'none (no k)')}"
            + (f"; filled empty columns {', '.join(filled)}" if filled else ""))
    r["notes"] = (str(r.get("notes") or "") + " | " + note).strip(" |")
    r["manifest_version"] = "2.1+phase4_step1"
    rec["row_filled_columns"] = filled
    return r


def run_pair(pid: str, cfg: dict, out_root: Path, nproc: int, batch_files: int, ledger: list) -> tuple:
    t0 = time.time()
    m = P.manifest().set_index("pair_id")
    if pid not in m.index:
        raise StopRun(f"{pid}: not a manifest v2.1 row")
    row = m.loc[pid]
    cruise = str(row["lr_cruise"])
    pdir = pair_dir_of(row)
    rel = str(row["harmonized_path"])
    out_dir = out_root / rel
    if not str(out_dir.resolve()).startswith(str(cfg["out_root"].resolve())):
        raise StopRun(f"{pid}: output directory {out_dir} is outside the mode's output root {cfg['out_root']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = {"pair_id": pid, "lr_cruise": cruise, "unit": row.get("leakage_unit"), "designation": row.get("designation"), "pair_dir": str(pdir),
           "out_dir": str(out_dir), "host": P.hostname(), "cpu_model": P.cpu_model(), "started": P.utc_now()}
    # 1 inputs
    rec["inputs"] = read_inputs(pid, pdir); ledger.append({"pair_id": pid, "item": "inputs", "status": "read", "reason": "hr.tif, lr.tif, 3 masks"})
    # 2 C2a
    rec["c2a"] = c2a_rule(pid, pdir, cruise, row); ledger.append({"pair_id": pid, "item": "c2a", "status": "computed", "reason": rec["c2a"]["sonar_source"]})
    # 3 k
    if pid in P.PRIOR_K_PAIRS:
        rec["sweep"] = prior_k(pid, row); ledger.append({"pair_id": pid, "item": "sweep", "status": "not run (prior k kept)", "reason": rec["sweep"]["k_source"]})
    else:
        try:
            rec["sweep"] = sweep(pid, pdir, rec["c2a"]["lr_native_unrounded_m"])
        except Exception as e:
            raise StopRun(f"{pid}: sweep raised (rule C4): {type(e).__name__}: {str(e)[:200]}") from e
        ledger.append({"pair_id": pid, "item": "sweep", "status": rec["sweep"].get("status"), "reason": f"k={rec['sweep'].get('max_recoverable_k')}"})
    P.write_json(out_dir / "sweep_record.json", rec["sweep"])
    k = rec["sweep"].get("max_recoverable_k")
    # 4 products
    if k is None:
        rec["products"] = None; ledger.append({"pair_id": pid, "item": "products", "status": "not built", "reason": f"no k (k_sweep_status {rec['sweep'].get('status')}; rule C3)"})
    else:
        rec["products"] = build_products(pid, pdir, out_dir, cruise, nproc, batch_files)
        ledger.append({"pair_id": pid, "item": "products", "status": "built" if rec["products"]["available"] else "unavailable",
                       "reason": rec["products"].get("reason") or rec["products"].get("unavailable_reason") or f"{rec['products']['n_files_read']} files read; flags {rec['products']['flags']}"})
    # 5 usable
    rec["usable"], rec["usable_reason"] = usable_rule(rec["products"])
    # 6 row
    r = supplement_row(row, rec, cfg["mode"])
    rec["wall_s"] = round(time.time() - t0, 1); rec["finished"] = P.utc_now()
    summary = {"pair_id": pid, "hr_native_res_m": rec["c2a"]["hr_native_res_m"], "lr_native_res_m": rec["c2a"]["lr_native_res_m"],
               "max_recoverable_k": k, "k_sweep_status": rec["sweep"].get("status"),
               "products": ("built" if (rec["products"] and rec["products"]["available"]) else ("unavailable" if rec["products"] else "none")),
               "flags": (rec["products"] or {}).get("flags"), "ship_products_usable": rec["usable"], "wall_s": rec["wall_s"]}
    rec["summary"] = summary
    P.write_json(out_dir / "step1_record.json", rec, mode=0o644)
    print("PAIR " + json.dumps(summary, default=str), flush=True)
    return r, rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=MODE_CHOICES)
    ap.add_argument("--pairs", default=None, help="comma-separated subset of the mode's pair list (phase4: must be all five)")
    ap.add_argument("--run-tag", default="", help="rehearsal: sub-directory of the scratch output root")
    ap.add_argument("--nproc", type=int, default=6); ap.add_argument("--batch-files", type=int, default=1)
    ap.add_argument("--signoff", default=None); ap.add_argument("--prereg-sha256", default=None); ap.add_argument("--freeze-record", default=None)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    t_run = time.time()
    cfg = dict(MODES[a.mode]); cfg["mode"] = a.mode
    pairs = [p.strip() for p in a.pairs.split(",") if p.strip()] if a.pairs else list(cfg["pairs"])
    bad = [p for p in pairs if p not in cfg["pairs"]]
    if bad:
        raise Refusal(f"pair list: {bad} not in the {a.mode} pair list {list(cfg['pairs'])}")
    out_root = cfg["out_root"] / a.run_tag if a.run_tag else cfg["out_root"]
    run = {"directive": "ACQ-R06", "mode": a.mode, "run_tag": a.run_tag, "pairs": pairs, "out_root": str(out_root), "started": P.utc_now(),
           "host": P.hostname(), "cpu_model": P.cpu_model(), "code_commit": P.git_commit(), "nproc": a.nproc, "batch_files": a.batch_files,
           "mbsystem": C.MBSYSTEM_VERSION, "sandbox": C.SANDBOX, "container_digest": C.CONTAINER_DIGEST}
    run["fixed_input_sha256"] = P.check_fixed_inputs()
    guard = G.run(write=False); run["guard_selftest"] = {k: v for k, v in guard.items() if k != "reader_checks"}
    run["guard_selftest"]["reader_checks"] = {"n": guard["reader_checks"]["n"], "n_blocked": guard["reader_checks"]["n_blocked"]}
    if not guard["all_passed"]:
        raise Refusal("guard self-test failed: " + json.dumps(run["guard_selftest"], default=str)[:300])
    if a.mode == "phase4":                                   # mode branch 2: the locks, then the allowance
        run["locks"] = enforce_phase4_locks(a, pairs, cfg)
        run["allowance"] = list(C.install_phase4_allowance(cfg["allow"], reason="ACQ-R06 phase4 locks passed: sign-off, freeze record, pair list, single run"))
    rows, recs, ledger = [], {}, []
    try:
        for pid in pairs:
            r, rec = run_pair(pid, cfg, out_root, a.nproc, a.batch_files, ledger)
            rows.append(r); recs[pid] = rec["summary"]
    except StopRun as e:
        run.update({"status": "stopped (rule C4)", "error": str(e), "ledger": ledger, "pairs_done": list(recs), "wall_s": round(time.time() - t_run, 1)})
        write_run_record(run, cfg, a)
        log.error("STOP (rule C4): %s", e)
        raise
    run["loaded_repo_files"] = P.loaded_repo_files()
    if a.mode == "phase4":                                   # mode branch 3: re-verify the freeze record after the run (lazy imports)
        run["locks"]["lock2_after_run"] = lock_freeze_record(a.freeze_record or P.FREEZE_RECORD)
    cols = list(P.manifest().columns)
    sup = pd.DataFrame(rows)[cols]
    sp = Path(cfg["supplement"]) if not a.run_tag else Path(cfg["supplement"]).with_name(Path(cfg["supplement"]).stem + f"_{a.run_tag}.parquet")
    sp.parent.mkdir(parents=True, exist_ok=True)
    if sp.exists():
        sp.chmod(0o644)
    sup.to_parquet(sp, index=False); sp.chmod(0o444)
    run.update({"status": "complete", "supplement": str(sp), "supplement_sha256": P.sha256_file(sp), "n_rows": len(sup), "pairs_done": list(recs),
                "per_pair": recs, "ledger": ledger, "wall_s": round(time.time() - t_run, 1), "finished": P.utc_now()})
    write_run_record(run, cfg, a)
    for pid, s in recs.items():
        print(f"{pid:30s} hr {s['hr_native_res_m']:>7} m  lr {s['lr_native_res_m']:>7} m  k {str(s['max_recoverable_k']):>4}  {str(s['k_sweep_status']):10s} "
              f"products {s['products']:11s} flags {s['flags']}  usable {s['ship_products_usable']}")
    print(f"supplement {sp} ({len(sup)} rows, sha256 {run['supplement_sha256'][:16]}…); wall {run['wall_s']} s")
    return 0


def write_run_record(run: dict, cfg: dict, a) -> Path:
    tag = a.run_tag or "run"
    p = (P.REHEARSAL_DIR if cfg["mode"] == "rehearsal" else P.REPORT_DIR) / f"step1_run_{cfg['mode']}_{tag}.json"
    return P.write_json(p, run, mode=0o644)


if __name__ == "__main__":
    sys.exit(main())
