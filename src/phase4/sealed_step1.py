"""ACQ-R06 Part A / ACQ-R06b Part A — Phase 4 step 1: the entry script that completes a sealed pair's manifest row.

Per pair, in this order:
  1. read the pair's harmonized hr.tif, lr.tif and the three masks — no re-gridding, no re-harmonization, no new
     co-registration; the recorded co-registration and qa_status stand;
  2. hr_native_res_m and lr_native_res_m by the C2a rule exactly as src/acq_r01/harmonize_new.py computes them for a
     new pair (beam footprint 2·depth·tan(bw/2) at the median depth of all valid cells of the harmonized lr.tif, bw from
     src/acq_r01/grid_lr.beamwidth_for(<sonar string>), posting = |lr.tif pixel|, lr_native = max(footprint, posting));
     ACQ-R06b A1: a pair whose manifest v2.1 designation is `lockbox` takes its prior (June) values instead —
     hr/lr native from the manifest row, k and verdicts from the June sweep record — with a records-only consistency
     check (June lr_native == manifest lr_native at the manifest's precision, else rule C4);
  3. the C2c sweep the chain calls — src/discovery/stage_c2c_recalibrate.sweep on the harmonized pair with the
     reports/discovery/stage_c2c_calibration.json thresholds — giving max_recoverable_k and k_sweep_status;
  4. if the pair has a k: contract-v2.1 ship products on the grid of lr.tif (src/acq_r03/build_products_v2_1.build,
     unchanged) with products.json and its QA; a pair with no k gets no products.  ACQ-R06b A2: a lockbox pair whose
     LR cruise is absent from OAK raw_lr_swath/ and listed in the June plan is fetched first (src/acq_r01/fetch_swath,
     unchanged); an incomplete fetch makes that pair's products unavailable and the run continues;
  5. ship_products_usable by rule C1;
  6. one supplement row with the manifest v2.1 columns.
  Outputs (ACQ-R06b A3) are written into the pair's output directory by a recorded, reversed permission change: the
  directory's mode is recorded, owner write added to that directory only, ship_products_v2_1/, step1_record.json and
  sweep_record.json written (new files 0444, the subdirectory 0555), the directory's mode restored.  Existing
  targets are never opened for writing (a present target stops the run).

Modes.  --mode rehearsal: development pairs, guard fully on, outputs (and any fetch) under a scratch root.
        --mode phase4: the five sealed pairs only; locks: sign-off, freeze record, pair list, single run, fetch trigger set.
The two modes differ only in the pair list, the guard allow-list and the output root (MODES); the phase4 locks and the
phase4 allowance are the only other places that consult the mode (see the report's mode-branch table).

Usage: python -m src.phase4.sealed_step1 --mode rehearsal --run-tag r06b [--pairs a,b] [--nproc 6] [--batch-files 1]
       python -m src.phase4.sealed_step1 --mode phase4 --signoff <file> --prereg-sha256 <hex> [--freeze-record <json>]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import stat as statmod
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
from src.acq_r01 import fetch_swath as F              # the unchanged fetcher (ACQ-R06b A2)
from src.acq_r03 import common as R3
from src.acq_r03 import build_products_v2_1 as V21
from src.discovery import stage_c5_spectral           # noqa: F401
from src.discovery import stage_c2c_recalibrate as C2C
from src.phase4 import common as P
from src.phase4 import guard_selftest as G

log = logging.getLogger("acq_r06.step1")
MODE_CHOICES = ("rehearsal", "phase4")

# The only mode-dependent table: pair list, guard allow-list, output root (+ the supplement path under that root).
# The swath root of a fetch is <output root>/raw_lr_swath (OAK's own raw_lr_swath/ in phase4 mode).
MODES = {
    "rehearsal": {"pairs": tuple(P.REHEARSAL10), "allow": (), "out_root": P.SCRATCH_ROOT, "supplement": P.SUPPLEMENT_REHEARSAL},
    "phase4": {"pairs": tuple(P.SEALED_PAIRS), "allow": P.sealed_allow_tokens(), "out_root": C.OAK, "supplement": P.SUPPLEMENT_PHASE4},
}
OUTPUT_TARGETS = (V21.OUT_NAME, "step1_record.json", "sweep_record.json")
FETCH_WORKERS = 6


class Refusal(RuntimeError):
    """A lock or a pair-list refusal; raised before any sealed file is opened."""


class StopRun(RuntimeError):
    """Rule C4: any error that is not a data-tied builder failure (or an incomplete lockbox fetch) stops the run."""


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


def lock_fetch_trigger(pairs):
    """ACQ-R06b A2: the set of cruises the fetch trigger names must be exactly the two lockbox cruises (before any fetch)."""
    trig = fetch_trigger(pairs)
    got = set(trig)
    if got != set(P.LOCKBOX_FETCH_SET):
        raise Refusal(f"LOCK 5 fetch trigger: triggered cruises {sorted(got)} != {sorted(P.LOCKBOX_FETCH_SET)}; no fetch")
    return {"triggered": {c: sorted(v) for c, v in trig.items()}}


def enforce_phase4_locks(a, pairs, cfg) -> dict:
    """Order: sign-off, freeze record, pair list, single run, fetch trigger.  Any failure raises Refusal before any sealed read."""
    rec = {}
    rec["lock1_signoff"] = lock_signoff(a.signoff, a.prereg_sha256)
    rec["lock2_freeze_record"] = lock_freeze_record(a.freeze_record or P.FREEZE_RECORD)
    rec["lock3_pair_list"] = lock_pair_list(pairs, a.run_tag)
    rec["lock4_single_run"] = lock_single_run(cfg["supplement"])
    rec["lock5_fetch_trigger"] = lock_fetch_trigger(pairs)
    return rec


# --------------------------------------------------------------------------- #
# swath: trigger, fetch, counts (ACQ-R06b A2)
# --------------------------------------------------------------------------- #
def fetch_trigger(pairs) -> dict:
    """cruise -> pairs: a pair's LR cruise is fetched iff the pair's designation is `lockbox`, the cruise directory is
    absent from OAK raw_lr_swath/ (root listing) and the June plan lists it.  A confirmatory pair with a missing
    swath directory is not fetched (rule C4 stops it at the count preflight)."""
    m = P.manifest().set_index("pair_id")
    listing = P.oak_swath_listing(); plan = P.june_plan_cruises()
    trig = {}
    for pid in pairs:
        row = m.loc[pid]; c = str(row["lr_cruise"])
        if str(row["designation"]) == P.PRIOR_VALUE_DESIGNATION and c not in listing and c in plan:
            trig.setdefault(c, []).append(pid)
    return trig


def swath_count_on_disk(cruise_dir: Path) -> int:
    return len(V1.swath_files(cruise_dir))


def manifest_swath_count(cruise_dir: Path) -> int:
    """Entries of fetch_manifest.json that hold a file (the fetcher lists its `empty_file` outcomes with size 0 and no file)."""
    fm = json.loads((cruise_dir / "fetch_manifest.json").read_text())
    if fm.get("n_files_failed", 0):
        raise StopRun(f"{cruise_dir.name}: fetch_manifest.json records {fm['n_files_failed']} failed files")
    return sum(1 for f in fm["files"] if int(f.get("size", 0)) > 0)


def preflight_swath(pairs, triggered: dict) -> dict:
    """Every cruise the step will read without fetching must exist on OAK and hold exactly its fetch-manifest count."""
    m = P.manifest().set_index("pair_id"); out = {}
    listing = P.oak_swath_listing()                       # existence from the root listing (no stat of a sealed path)
    for pid in pairs:
        c = str(m.loc[pid]["lr_cruise"])
        if c in triggered or c in out:
            continue
        d = C.RAW_SWATH_OAK / c
        if c not in listing:
            raise StopRun(f"{pid}: swath directory {d} is missing and the pair is not a lockbox fetch (rule C4)")
        n_disk, n_man = swath_count_on_disk(d), manifest_swath_count(d)
        out[c] = {"n_disk": n_disk, "n_manifest": n_man, "equal": n_disk == n_man}
        if n_disk != n_man:
            raise StopRun(f"{pid}: {c} holds {n_disk} swath files but its fetch manifest lists {n_man} (rule C4)")
    return out


def fetch_cruise(cruise: str, swath_root: Path, report_dir: Path, plan_csv=None, workers: int = FETCH_WORKERS) -> dict:
    """ACQ-R06b A2: src/acq_r01/fetch_swath.main --plan-csv <June plan> --cruises <cruise>, unchanged, with its output
    root and log directory redirected (module attributes), then restored.  Returns the per-cruise outcome."""
    plan_csv = Path(plan_csv or P.JUNE_FILE_PLAN)
    old_root, old_rep = C.RAW_SWATH_OAK, C.REPORT_DIR
    C.RAW_SWATH_OAK = Path(swath_root); C.REPORT_DIR = Path(report_dir)
    t0 = time.time()
    try:
        swath_root.mkdir(parents=True, exist_ok=True)
        rc = F.main(["--plan-csv", str(plan_csv), "--cruises", cruise, "--workers", str(workers)])
    finally:
        C.RAW_SWATH_OAK, C.REPORT_DIR = old_root, old_rep
    d = Path(swath_root) / cruise
    man = json.loads((d / "fetch_manifest.json").read_text()) if (d / "fetch_manifest.json").exists() else {}
    n_planned = int(man.get("n_files_planned", 0)); n_ok = int(man.get("n_files_ok", 0)); n_failed = int(man.get("n_files_failed", 0))
    complete = rc == 0 and n_failed == 0 and n_planned > 0 and n_ok == n_planned
    return {"cruise": cruise, "cruise_dir": str(d), "plan_csv": str(plan_csv), "rc": rc, "n_planned": n_planned, "n_ok": n_ok, "n_failed": n_failed,
            "complete": complete, "wall_s": round(time.time() - t0, 1), "fetcher": "src/acq_r01/fetch_swath.py main --plan-csv (unchanged)",
            "reason": None if complete else f"lockbox fetch incomplete ({n_ok} of {n_planned} files)"}


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
    """Step 1: open hr.tif, lr.tif and the three masks; record shapes, CRS, nodata and the file hashes."""
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
    """The sonar string the C2a beam-width lookup receives: the cruise's ACQ-R02 grid record (the --sonar argument of
    grid_lr) when it exists, else the manifest row's lr_sonar.  Returns (sonar, source, grid_record or None)."""
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
            "source": "C2a rule computed by this step", "rule": "max(footprint, posting) (C2a)",
            "code": "src/acq_r01/harmonize_new.py main(): lr_native block; src/acq_r01/grid_lr.py beamwidth_for"}


def _ndp(x: float) -> int:
    s = repr(float(x))
    return len(s.split(".")[1]) if "." in s else 0


def prior_values(pid: str, row) -> tuple:
    """ACQ-R06b A1 (rulings H-1 / H-3): hr/lr native from the manifest v2.1 row, k and verdicts from the June sweep
    record; consistency check: the June record's lr_native equals the manifest's at the manifest's precision."""
    hr = row.get("hr_native_res_m"); lr = row.get("lr_native_res_m")
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in (hr, lr)):
        raise StopRun(f"{pid}: designation {P.PRIOR_VALUE_DESIGNATION} but the manifest row holds no hr/lr native ({hr}, {lr})")
    j = P.june_sweep_record().get(pid)
    if j is None:
        raise StopRun(f"{pid}: designation {P.PRIOR_VALUE_DESIGNATION} but the June sweep record holds no entry for it")
    jl = j.get("lr_native_m")
    nd = _ndp(lr)
    if jl is None or round(float(jl), nd) != round(float(lr), nd):
        raise StopRun(f"{pid}: A1 consistency check failed: June sweep record lr_native_m {jl} != manifest lr_native_res_m {lr} (rule C4)")
    hr_v, lr_v = float(hr), float(lr)
    c2a = {"hr_native_res_m": hr_v, "lr_native_res_m": lr_v, "lr_native_unrounded_m": lr_v, "res_ratio": round(lr_v / hr_v, 2) if hr_v else None,
           "source": "manifest v2.1 row (prior June values; ACQ-R06b A1, rulings H-1/H-3)", "rule": "prior values kept; no C2a computation",
           "consistency_check": {"june_sweep_lr_native_m": jl, "manifest_lr_native_res_m": lr_v, "precision_dp": nd, "equal": True}}
    k = j.get("max_recoverable_k")
    sweep = {"pair_id": pid, "status": j.get("status"), "max_recoverable_k": (int(k) if k is not None else None), "per_k": j.get("per_k"),
             "lr_native_m": jl, "edge_coh": j.get("edge_coh"), "k_source": "June C2c sweep record reports/discovery/stage_c2c_sweep.json (prior value; ACQ-R06b A1)",
             "swept": False, "code": "no sweep run"}
    return c2a, sweep


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
    """products.json with every available flag false (contract v2.1 §5 structure, as build_products_v2_1.write_unavailable)."""
    return {"contract_version": V21.CONTRACT, "pair_id": pid, "lr_tif_path": str(lr_path),
            "available": {k: False for k in V21.AVAIL}, "unavailable_reason": reason,
            "source": {"kind": "none", "files": [], "mb_format": None, "processing_mode": None}, "beam_angle_method": None,
            "software": {"mbsystem": C.MBSYSTEM_VERSION, "container": f"apptainer sandbox {C.SANDBOX}", "code_commit": C.git_commit()},
            "commands": [], "grid": None,
            "frame_offset": {"applied": False, "dx_m": 0.0, "dy_m": 0.0, "basis": "none", "evidence": "no products built; not applicable"},
            "qa_vs_lr_tif": None, "created": datetime.now(timezone.utc).isoformat()}


def build_products(pid: str, pdir: Path, stage_root: Path, cruise: str, cruise_dir: Path, nproc: int, batch_files: int) -> dict:
    """Step 4: src/acq_r03/build_products_v2_1.build, unchanged, on a staging copy of the pair's lr.tif; the finished
    ship_products_v2_1/ stays in the staging directory until write_outputs copies it into the pair's output directory."""
    stage = stage_root / pid
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copyfile(pdir / "lr.tif", stage / "lr.tif")
    R3.REPORT_DIR = stage                             # the builder's run summary json stays with the staged products
    src_kind = "provider_swath" if cruise.startswith("PANGAEA_") else "ncei_swath"   # as harmonize_new.py
    t0 = time.time()
    try:
        res = V21.build([(pid, stage)], cruise, cruise_dir, src_kind, nproc, batch_files)
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        data_tied, reason = classify_builder_error(e)
        if not data_tied:
            shutil.rmtree(stage, ignore_errors=True)
            raise StopRun(f"{pid}: product builder failed (not data-tied; rule C4): {reason}") from e
        return {"available": False, "reason": reason, "error_class": type(e).__name__, "rule": "C2 data-tied builder failure",
                "wall_s": round(time.time() - t0, 1), "products_json": unavailable_products_json(pid, pdir / "lr.tif", reason), "staged_dir": None}
    wall = time.time() - t0
    src_dir = stage / V21.OUT_NAME
    pj = json.loads((src_dir / "products.json").read_text())
    ex = json.loads((src_dir / "products_extra.json").read_text()) if (src_dir / "products_extra.json").exists() else {}
    per_file = ex.get("per_file", [])
    n_listed = len(pj["source"]["files"]); n_read = len(per_file); n_rc0 = sum(1 for r in per_file if r.get("rc") == 0)
    if batch_files <= 1 and (n_read != n_listed or n_rc0 != n_listed):
        raise StopRun(f"{pid}: {n_listed} swath files listed, {n_read} read, {n_rc0} with rc 0 — a listed file was not read")
    avail = bool(pj.get("available")) and all(pj["available"].values())
    return {"available": avail, "unavailable_reason": pj.get("unavailable_reason"), "flags": list((pj.get("qa_vs_lr_tif") or {}).get("flags") or []),
            "qa_vs_lr_tif": pj.get("qa_vs_lr_tif"), "mb_format": pj["source"]["mb_format"], "n_files_listed": n_listed, "n_files_read": n_read,
            "n_files_rc0": n_rc0, "beam_angle_method": pj.get("beam_angle_method"), "frame_offset": pj.get("frame_offset"),
            "matches_lr_tif": (pj.get("grid") or {}).get("matches_lr_tif"), "wall_s": round(wall, 1), "nproc": nproc, "batch_files": batch_files,
            "builder": "src/acq_r03/build_products_v2_1.py build (unchanged)", "result": res[0] if res else None, "staged_dir": str(src_dir),
            "cruise_dir": str(cruise_dir), "lr_tif_source": str(pdir / "lr.tif"),
            "staging_note": "products.json lr_tif_path names the node-local staging copy of lr.tif (same bytes; sha256 in inputs)"}


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
    if "sonar" in c2a:
        basis = (f"lr_native by the ACQ-R02 chain C2a rule (sonar '{c2a['sonar']}' from {c2a['sonar_source']}, bw {c2a['beamwidth_deg']} deg, "
                 f"depth {c2a['depth_m']} m = {c2a['depth_basis']}, footprint {c2a['beam_footprint_m']} m, posting {c2a['posting_m']} m)")
    else:
        basis = f"hr/lr native kept from {c2a['source']}"
    fetched = rec.get("fetch")
    note = (f"ACQ-R06 step1 ({mode}, {P.utc_now()[:10]}): {basis}; k from {sw.get('k_source')}; "
            f"products {'built' if (pr and pr.get('available')) else ('unavailable' if pr else 'none (no k)')}"
            + (f"; LR swath fetched by the step ({fetched['n_ok']} of {fetched['n_planned']} files)" if fetched else "")
            + (f"; filled empty columns {', '.join(filled)}" if filled else ""))
    r["notes"] = (str(r.get("notes") or "") + " | " + note).strip(" |")
    r["manifest_version"] = "2.1+phase4_step1"
    rec["row_filled_columns"] = filled
    return r


def write_outputs(out_dir: Path, products: dict | None, sweep_rec: dict, step_rec: dict) -> dict:
    """ACQ-R06b A3: record the directory's mode, add owner write to that directory only, write ship_products_v2_1/,
    sweep_record.json and step1_record.json (new files 0444, the subdirectory 0555), restore the directory's mode.
    Existing targets are never opened for writing: a present target stops the run."""
    present = [t for t in OUTPUT_TARGETS if (out_dir / t).exists()]
    if present:
        raise StopRun(f"{out_dir}: output target(s) already present {present}; existing files are never opened for writing")
    mode_before = out_dir.stat().st_mode & 0o7777
    rec = {"out_dir": str(out_dir), "mode_before": oct(mode_before), "mode_opened": None, "mode_after": None, "restored": None, "files": {}}
    step_rec["write_path"] = rec
    err = None
    try:
        os.chmod(out_dir, mode_before | statmod.S_IWUSR)
        rec["mode_opened"] = oct(out_dir.stat().st_mode & 0o7777)
        if products is not None:
            dst = out_dir / V21.OUT_NAME; dst.mkdir()
            if products.get("staged_dir"):
                for p in sorted(Path(products["staged_dir"]).iterdir()):
                    shutil.copyfile(p, dst / p.name); os.chmod(dst / p.name, 0o444); rec["files"][f"{V21.OUT_NAME}/{p.name}"] = P.sha256_file(dst / p.name)
            else:
                P.write_json(dst / "products.json", products["products_json"]); rec["files"][f"{V21.OUT_NAME}/products.json"] = P.sha256_file(dst / "products.json")
            os.chmod(dst, 0o555)
        P.write_json(out_dir / "sweep_record.json", sweep_rec); rec["files"]["sweep_record.json"] = P.sha256_file(out_dir / "sweep_record.json")
        P.write_json(out_dir / "step1_record.json", step_rec); rec["files"]["step1_record.json"] = P.sha256_file(out_dir / "step1_record.json")
    except OSError as e:                                         # the write failed: restore, then stop (rule C4) with the modes found
        err = e
    finally:
        try:
            os.chmod(out_dir, mode_before)
            rec["mode_after"] = oct(out_dir.stat().st_mode & 0o7777); rec["restored"] = rec["mode_after"] == rec["mode_before"]
        except Exception as e:                                   # noqa: BLE001
            rec["mode_after"] = f"restore failed: {type(e).__name__}: {e}"; rec["restored"] = False
    if err is not None:
        raise StopRun(f"{out_dir}: write path failed (rule C4): {type(err).__name__}: {err}; modes before {rec['mode_before']} opened {rec['mode_opened']} after {rec['mode_after']}") from err
    if not rec["restored"]:
        raise StopRun(f"{out_dir}: directory mode not restored (before {rec['mode_before']}, after {rec['mode_after']}) (rule C4)")
    return rec


def run_pair(pid: str, cfg: dict, out_root: Path, nproc: int, batch_files: int, ledger: list, stage_root: Path | None = None) -> tuple:
    t0 = time.time()
    m = P.manifest().set_index("pair_id")
    if pid not in m.index:
        raise StopRun(f"{pid}: not a manifest v2.1 row")
    row = m.loc[pid]
    cruise = str(row["lr_cruise"]); designation = str(row["designation"])
    pdir = pair_dir_of(row)
    rel = str(row["harmonized_path"])
    out_dir = out_root / rel
    if not str(out_dir.resolve()).startswith(str(cfg["out_root"].resolve())):
        raise StopRun(f"{pid}: output directory {out_dir} is outside the mode's output root {cfg['out_root']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stage_root = stage_root or Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r06_step1"
    rec = {"pair_id": pid, "lr_cruise": cruise, "unit": row.get("leakage_unit"), "designation": designation, "pair_dir": str(pdir),
           "out_dir": str(out_dir), "host": P.hostname(), "cpu_model": P.cpu_model(), "started": P.utc_now()}
    # 1 inputs
    rec["inputs"] = read_inputs(pid, pdir); ledger.append({"pair_id": pid, "item": "inputs", "status": "read", "reason": "hr.tif, lr.tif, 3 masks"})
    # 2 + 3: prior values (A1) or C2a + sweep
    if designation == P.PRIOR_VALUE_DESIGNATION:
        rec["c2a"], rec["sweep"] = prior_values(pid, row)
        ledger.append({"pair_id": pid, "item": "c2a", "status": "prior values kept (no C2a)", "reason": rec["c2a"]["source"]})
        ledger.append({"pair_id": pid, "item": "sweep", "status": "not run (prior k kept)", "reason": f"k={rec['sweep'].get('max_recoverable_k')} from {rec['sweep']['k_source']}"})
    else:
        rec["c2a"] = c2a_rule(pid, pdir, cruise, row); ledger.append({"pair_id": pid, "item": "c2a", "status": "computed", "reason": rec["c2a"]["sonar_source"]})
        try:
            rec["sweep"] = sweep(pid, pdir, rec["c2a"]["lr_native_unrounded_m"])
        except Exception as e:
            raise StopRun(f"{pid}: sweep raised (rule C4): {type(e).__name__}: {str(e)[:200]}") from e
        ledger.append({"pair_id": pid, "item": "sweep", "status": rec["sweep"].get("status"), "reason": f"k={rec['sweep'].get('max_recoverable_k')}"})
    k = rec["sweep"].get("max_recoverable_k")
    # swath: fetch trigger (A2)
    trig = fetch_trigger([pid]); rec["fetch"] = None
    swath_root = out_root / "raw_lr_swath"
    if cruise in trig:
        rec["fetch"] = fetch_cruise(cruise, swath_root, out_dir, P.JUNE_FILE_PLAN, FETCH_WORKERS)
        cruise_dir = Path(rec["fetch"]["cruise_dir"])
        ledger.append({"pair_id": pid, "item": "fetch", "status": "complete" if rec["fetch"]["complete"] else "incomplete",
                       "reason": f"{rec['fetch']['n_ok']} of {rec['fetch']['n_planned']} files (rc {rec['fetch']['rc']})"})
    else:
        cruise_dir = C.RAW_SWATH_OAK / cruise
    # 4 products
    if k is None:
        rec["products"] = None; ledger.append({"pair_id": pid, "item": "products", "status": "not built", "reason": f"no k (k_sweep_status {rec['sweep'].get('status')}; rule C3)"})
    elif rec["fetch"] is not None and not rec["fetch"]["complete"]:
        reason = rec["fetch"]["reason"]
        rec["products"] = {"available": False, "reason": reason, "rule": "ACQ-R06b A2 incomplete lockbox fetch", "staged_dir": None,
                           "products_json": unavailable_products_json(pid, pdir / "lr.tif", reason)}
        ledger.append({"pair_id": pid, "item": "products", "status": "unavailable", "reason": reason})
    else:
        rec["products"] = build_products(pid, pdir, stage_root, cruise, cruise_dir, nproc, batch_files)
        ledger.append({"pair_id": pid, "item": "products", "status": "built" if rec["products"]["available"] else "unavailable",
                       "reason": rec["products"].get("reason") or rec["products"].get("unavailable_reason") or f"{rec['products']['n_files_read']} files read; flags {rec['products']['flags']}"})
    # 5 usable
    rec["usable"], rec["usable_reason"] = usable_rule(rec["products"])
    # 6 row
    r = supplement_row(row, rec, cfg["mode"])
    rec["wall_s"] = round(time.time() - t0, 1); rec["finished"] = P.utc_now()
    summary = {"pair_id": pid, "designation": designation, "hr_native_res_m": rec["c2a"]["hr_native_res_m"], "lr_native_res_m": rec["c2a"]["lr_native_res_m"],
               "values_source": rec["c2a"]["source"], "max_recoverable_k": k, "k_sweep_status": rec["sweep"].get("status"), "k_source": rec["sweep"].get("k_source"),
               "per_k": rec["sweep"].get("per_k"), "fetch": ({k_: rec["fetch"][k_] for k_ in ("n_ok", "n_planned", "complete", "reason")} if rec["fetch"] else None),
               "products": ("built" if (rec["products"] and rec["products"]["available"]) else ("unavailable" if rec["products"] else "none")),
               "products_reason": (rec["products"] or {}).get("reason") or (rec["products"] or {}).get("unavailable_reason"),
               "flags": (rec["products"] or {}).get("flags"), "ship_products_usable": rec["usable"], "wall_s": rec["wall_s"]}
    rec["summary"] = summary
    # write path (A3)
    prods = rec["products"]
    wp = write_outputs(out_dir, prods, rec["sweep"], rec)
    if prods and prods.get("staged_dir"):
        shutil.rmtree(Path(prods["staged_dir"]).parent, ignore_errors=True)
    summary["write_path"] = {k_: wp[k_] for k_ in ("mode_before", "mode_opened", "mode_after", "restored")}
    ledger.append({"pair_id": pid, "item": "write", "status": "written, mode restored" if wp["restored"] else "MODE NOT RESTORED", "reason": f"{len(wp['files'])} files; dir {wp['mode_before']} -> {wp['mode_opened']} -> {wp['mode_after']}"})
    print("PAIR " + json.dumps({k_: v for k_, v in summary.items() if k_ != "per_k"}, default=str), flush=True)
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
    run = {"directive": "ACQ-R06b", "mode": a.mode, "run_tag": a.run_tag, "pairs": pairs, "out_root": str(out_root), "started": P.utc_now(),
           "host": P.hostname(), "cpu_model": P.cpu_model(), "code_commit": P.git_commit(), "nproc": a.nproc, "batch_files": a.batch_files,
           "mbsystem": C.MBSYSTEM_VERSION, "sandbox": C.SANDBOX, "container_digest": C.CONTAINER_DIGEST}
    run["fixed_input_sha256"] = P.check_fixed_inputs()
    guard = G.run(write=False); run["guard_selftest"] = {k: v for k, v in guard.items() if k != "reader_checks"}
    run["guard_selftest"]["reader_checks"] = {"n": guard["reader_checks"]["n"], "n_blocked": guard["reader_checks"]["n_blocked"]}
    if not guard["all_passed"]:
        raise Refusal("guard self-test failed: " + json.dumps(run["guard_selftest"], default=str)[:300])
    if a.mode == "phase4":                                   # mode branch 2: the locks, then the allowance
        run["locks"] = enforce_phase4_locks(a, pairs, cfg)
        run["allowance"] = list(C.install_phase4_allowance(cfg["allow"], reason="ACQ-R06 phase4 locks passed: sign-off, freeze record, pair list, single run, fetch trigger"))
    run["fetch_trigger"] = {c: sorted(v) for c, v in fetch_trigger(pairs).items()}
    rows, recs, ledger = [], {}, []
    try:
        run["swath_preflight"] = preflight_swath(pairs, run["fetch_trigger"])
        for pid in pairs:
            r, rec = run_pair(pid, cfg, out_root, a.nproc, a.batch_files, ledger)
            rows.append(r); recs[pid] = rec["summary"]
    except StopRun as e:
        run.update({"status": "stopped (rule C4)", "error": str(e), "ledger": ledger, "pairs_done": list(recs), "per_pair": recs, "wall_s": round(time.time() - t_run, 1)})
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
