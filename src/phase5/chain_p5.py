"""ACQ-R09 §2.5-2.8 — the development chain for one Phase 5 site, functions called unchanged.

The glue below reproduces, line for line, the development drivers that cannot be called whole for a Phase 5 site (they
read the ACQ-R02 verification tables): src/acq_r01/grid_lr.py main() (ship grid), src/acq_r01/harmonize_new.py main()
lines 305-352 (harmonize, masked rigid co-registration, validity masks, 256-tiles, qa_pass) and its development block
(C2a lr_native, C2c sweep, contract-v2.1 products).  Module attributes are redirected exactly where the drivers read
fixed paths (harmonize_new.GRIDDED -> the run's gridded directory, harmonize_new.hr_rasters -> the §3.2 kept grids,
stage_c2c_recalibrate.pair_dir -> the site's directory, acq_r03.common.REPORT_DIR -> the work directory), as the
development driver and the Phase 4 step did.  Not reproduced: the R3 QC figure (no image in Phase 5), hr_p50 and the
co-registration residual MAD (no depth statistic or amplitude is written), the H1 processed-grid cross-check.
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rioxarray  # noqa: F401
from rasterio.features import geometry_mask
from rasterio.warp import transform_bounds

from src import harmonize as H, coregister as cor
from src.acq_r01 import common as C
from src.acq_r01 import grid_lr as GL
from src.acq_r01 import harmonize_new as HN
from src.acq_r01 import fetch_plan as FP
from src.acq_r01 import fetch_swath as F
from src.acq_r01 import build_products as V1
from src.acq_r01 import build_products_v2 as V2   # noqa: F401  (chain)
from src.acq_r03 import common as R3
from src.acq_r03 import build_products_v2_1 as V21
from src.discovery import stage_c2c_recalibrate as C2C
from src.discovery import stage_c5_spectral        # noqa: F401  (chain)
from src.phase4 import sealed_step1 as S4            # frozen Phase 4 rules: usable_rule (C1), classify_builder_error (C2), counts
from src.phase5 import common_p5 as P

log = logging.getLogger("acq_r09.chain")
FILL = HN.FILL


class StopRun(RuntimeError):
    """Not a data-tied failure (container start / timeout, network, missing swath, write error): the run stops."""


class SiteFail(RuntimeError):
    """A data-tied failure of a site (unreadable format, no overlap ...): the site is not testable, the run continues."""


# --------------------------------------------------------------------------- #
# ship side: fetch (phase5 mode only) and counts
# --------------------------------------------------------------------------- #
def fetch_plan(site: dict, fp_4326, report_dir: Path) -> tuple:
    """src/acq_r01/fetch_plan.plan_ncei, unchanged (whole cruise if < 10 GB, else the navigation subset buffered by
    max(2 x depth, 1 km)); depth = ACQ-R08b's public depth_median_100m (the development planner used a catalog depth).
    Its listing cache is redirected to a Phase 5 directory.  Writes the per-file plan CSV; returns (csv, summary)."""
    old = FP.CACHE
    FP.CACHE = C.SCRATCH_DATA / "discovery_cache" / "acq_r09_phase5_fetch"
    try:
        d = P.depth_hint_m(site["hr_id"]) or 2000.0
        plan, summ = FP.plan_ncei(site["ship_cruise"], [fp_4326], d)
    finally:
        FP.CACHE = old
    summ = {k: v for k, v in summ.items()}
    summ["fetch_buffer_basis"] = "ACQ-R08b depth_median_100m (public metadata)"
    if not plan:
        raise SiteFail(f"fetch plan: {summ.get('status')} {summ.get('note', '')}"[:200])
    csv = Path(report_dir) / f"fetch_plan_{site['pair_id']}.csv"
    pd.DataFrame(plan).to_csv(csv, index=False)
    return csv, summ


def fetch(site: dict, plan_csv: Path, report_dir: Path, workers: int = P.FETCH_WORKERS) -> dict:
    """src/acq_r01/fetch_swath.main --plan-csv, unchanged, into OAK raw_lr_swath/<cruise> (its log directory
    redirected to the run's report directory)."""
    old_rep = C.REPORT_DIR
    C.REPORT_DIR = Path(report_dir)
    t0 = time.time()
    try:
        rc = F.main(["--plan-csv", str(plan_csv), "--cruises", site["ship_cruise"], "--workers", str(workers)])
    finally:
        C.REPORT_DIR = old_rep
    d = C.RAW_SWATH_OAK / site["ship_cruise"]
    man = json.loads((d / "fetch_manifest.json").read_text()) if (d / "fetch_manifest.json").exists() else {}
    n_planned, n_ok, n_failed = int(man.get("n_files_planned", 0)), int(man.get("n_files_ok", 0)), int(man.get("n_files_failed", 0))
    out = {"cruise": site["ship_cruise"], "cruise_dir": str(d), "plan_csv": str(plan_csv), "rc": rc, "n_planned": n_planned, "n_ok": n_ok,
           "n_failed": n_failed, "complete": rc == 0 and n_failed == 0 and n_planned > 0 and n_ok == n_planned, "wall_s": round(time.time() - t0, 1),
           "fetcher": "src/acq_r01/fetch_swath.py main --plan-csv (unchanged)"}
    if not out["complete"]:
        raise StopRun(f"{site['pair_id']}: swath fetch incomplete ({n_ok} of {n_planned} files, {n_failed} failed, rc {rc}); re-run resumes")
    return out


def swath_preflight(site: dict) -> dict:
    d = C.RAW_SWATH_OAK / site["ship_cruise"]
    if not d.is_dir() or not (d / "fetch_manifest.json").exists():
        raise StopRun(f"{site['pair_id']}: swath directory {d} or its fetch_manifest.json is missing")
    n_disk, n_man = S4.swath_count_on_disk(d), S4.manifest_swath_count(d)
    if n_disk != n_man:
        raise StopRun(f"{site['pair_id']}: {d.name} holds {n_disk} swath files but its fetch manifest lists {n_man}")
    return {"cruise_dir": str(d), "n_swath_files": n_disk, "n_manifest": n_man, "equal": True,
            "fetch_manifest_sha256": P.sha256_file(d / "fetch_manifest.json")}


class mb_retry:
    """During gridding only: C.mb retried on a container start failure (rc 255 / timeout; ACQ-R03 infra lesson) and a
    persistent one stops the run, so that a failed container start is never read as 'no soundings'.  Commands, arguments
    and outputs are unchanged."""
    def __enter__(self):
        self._orig = C.mb; self.calls = []
        orig = self._orig

        def wrapped(args, **kw):
            last = None
            for attempt in range(3):
                kw2 = dict(kw); kw2.setdefault("timeout", 6 * 3600)
                try:
                    r = orig(args, **kw2)
                except Exception as e:                       # subprocess.TimeoutExpired
                    last = f"{type(e).__name__}"; continue
                self.calls.append({"prog": args[0], "rc": r.returncode, "attempt": attempt + 1})
                if r.returncode != 255:
                    return r
                last = f"rc 255: {(r.stderr or '')[-120:]}"
            raise StopRun(f"MB-System container failed 3 times ({args[0]}): {last}")
        C.mb = wrapped
        return self.calls

    def __exit__(self, *exc):
        C.mb = self._orig
        return False


# --------------------------------------------------------------------------- #
# ship grid (grid_lr.main, lines 136-178, with the footprint of the kept grids)
# --------------------------------------------------------------------------- #
def grid_ship(site: dict, fp_4326, gridded_dir: Path, wd: Path, region_rule: str = "grid_region") -> dict:
    """The development gridder.  region_rule "grid_region" (current grid_lr, commit 4122090 on) is the only rule the
    entry script uses; "whole_footprint_pre_4122090" (no patch-cluster cut, as grid_lr before 4122090 gridded FK151121,
    NA080 and KM0923) exists for the ACQ-R09 FK151121 isolation harness only (ruling S3)."""
    t0 = time.time()
    cruise = site["ship_cruise"]
    if region_rule == "grid_region":
        union, region_note = GL.grid_region(fp_4326, lr_fp=GL.lr_catalog_footprint(cruise))
    elif region_rule == "whole_footprint_pre_4122090":
        union, region_note = fp_4326, "HARNESS ONLY: whole footprint, no grid_region (grid_lr before 4122090)"
    else:
        raise ValueError(region_rule)
    with mb_retry() as calls:
        try:
            dl, files, fmt = GL.prepare(cruise, wd)
        except ValueError as e:
            if "cannot infer MB format" in str(e):
                raise SiteFail(f"ship grid: unsupported swath format ({str(e)[:120]})") from e
            raise
        depth = GL.footprint_depth(dl, wd, union)
        bw, bw_key = GL.beamwidth_for(site["sonar"])
        if not math.isfinite(depth):
            depth = 2000.0; region_note += "; no soundings inside the footprint bbox, depth fallback 2000 m (grid_lr rule)"
        cell = 2.0 * depth * math.tan(math.radians(bw / 2))
        w, s, e, n = union.bounds; mlat = (s + n) / 2
        dlon = 1 / (111320 * max(0.2, math.cos(math.radians(mlat)))); dlat = 1 / 111320
        R = f"{w - 1000 * dlon}/{e + 1000 * dlon}/{s - 1000 * dlat}/{n + 1000 * dlat}"
        root = f"grid_{cruise}"
        cmd = ["mbgrid", "-I", dl.name, "-O", root, "-R", R, "-E", f"{cell * dlon}/{cell * dlat}/degrees", "-A2", "-G3", "-F1", "-C0", "-M"]
        r = C.mb(cmd, cwd=str(wd))
    grd = wd / f"{root}.grd"
    if not grd.exists():
        raise SiteFail(f"ship grid: mbgrid produced no grid (rc {r.returncode}): {(r.stderr or r.stdout or '')[-200:]}")
    gridded_dir.mkdir(parents=True, exist_ok=True)
    outs = {}
    for suf in ("", "_num", "_sd"):
        src = wd / f"{root}{suf}.grd"
        if src.exists():
            dst = gridded_dir / f"{cruise}__union{suf}.grd"
            if dst.exists():
                dst.chmod(0o644)
            shutil.copyfile(src, dst); dst.chmod(0o444); outs[suf or "grid"] = {"path": str(dst), "sha256": P.sha256_file(dst)}
    with rasterio.open(str(grd)) as ds:
        arr = ds.read(1, masked=True).filled(np.nan); tr = ds.transform
    inpoly = ~geometry_mask([fp_4326], out_shape=arr.shape, transform=tr, invert=False)
    fill = round(float((np.isfinite(arr) & inpoly).sum() / max(1, inpoly.sum())), 4)
    del arr
    rec = {"cruise": cruise, "hr": [site["hr_id"]], "n_files": len(files), "format": fmt, "sonar": site["sonar"], "beamwidth_deg": bw, "beamwidth_key": bw_key,
           "cell_m": round(cell, 2), "region": R, "region_choice": region_note, "region_rule": region_rule, "mbgrid_command": C.mb_cmdline(cmd), "mode": "raw", "outputs": outs,
           "fill_fraction_per_hr": {site["hr_id"]: fill}, "wall_s": round(time.time() - t0, 1), "mbsystem": C.MBSYSTEM_VERSION,
           "sandbox": C.SANDBOX, "container_digest": C.CONTAINER_DIGEST, "code": "src/acq_r01/grid_lr.py main() lines 136-178 (functions unchanged)"}
    shutil.rmtree(wd, ignore_errors=True)
    return rec


# --------------------------------------------------------------------------- #
# harmonize + co-register + masks + tiles (harmonize_new.main lines 305-352)
# --------------------------------------------------------------------------- #
def harmonize(site: dict, kept_raw: list, gridded_dir: Path, out_dir: Path, tmp: Path) -> dict:
    pid = site["pair_id"]; cruise = site["ship_cruise"]
    tmp.mkdir(parents=True, exist_ok=True)
    old_g, old_r = HN.GRIDDED, HN.hr_rasters
    HN.GRIDDED = Path(gridded_dir)
    HN.hr_rasters = lambda hr_id: list(kept_raw)               # ruling S1: the §3.2 kept grids, in rule order
    rec = {"pair_id": pid}
    try:
        lr_tif, _ = HN.lr_to_tif(cruise, tmp)
        with rasterio.open(str(lr_tif)) as ds:
            lrb = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
        hr_tif, n_tiles = HN.hr_mosaic(site["hr_id"], lrb, tmp)
        if hr_tif is None:
            raise SiteFail("no kept HR grid overlaps the ship grid")
        rec["hr_tiles_overlapping_lr"] = n_tiles
        rec["mosaic"] = mosaic_members(Path(hr_tif), kept_raw, lrb, tmp)
        with rasterio.open(str(hr_tif)) as ds:
            hb = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
        clon = (max(lrb[0], hb[0]) + min(lrb[2], hb[2])) / 2; clat = (max(lrb[1], hb[1]) + min(lrb[3], hb[3])) / 2
        tcrs = HN._utm(clon, clat); rec["target_crs"] = tcrs
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            hp = H.harmonize_pair(pair_id=pid, hr_raw=hr_tif, lr_raw=lr_tif, target_crs=tcrs, resample_kernel="bilinear", nodata=FILL,
                                  out_dir=out_dir, vertical_sign="negative_down", min_overlap_area_km2=1.0)
            rec["overlap_km2"] = round(hp.overlap_area_km2, 3)
        except Exception as e:
            raise SiteFail(f"harmonize: {str(e)[:150]}") from e
    finally:
        HN.GRIDDED, HN.hr_rasters = old_g, old_r
    hr_out, lr_out = out_dir / "hr.tif", out_dir / "lr.tif"
    try:
        hr_da = rioxarray.open_rasterio(str(hr_out), masked=True).squeeze(); lr_da = rioxarray.open_rasterio(str(lr_out), masked=True).squeeze()
        cg = cor.estimate_rigid_xyz(hr_da, lr_da)
        corrected = cor.apply_xyz(hr_da, cg.dx_m, cg.dy_m, cg.dz_m)
        corrected.rio.write_nodata(np.nan, inplace=True)
        corrected.rio.to_raster(hr_out, compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")
        off = float(np.hypot(cg.dx_m, cg.dy_m))
        rec["coreg"] = {"dx_m": round(cg.dx_m, 2), "dy_m": round(cg.dy_m, 2), "dz_m": round(cg.dz_m, 2), "offset_m": round(off, 2), "n": int(cg.n_samples),
                        "pass": bool(off <= P.USBL_BOUND_M), "estimated": True}
    except Exception as e:
        rec["coreg"] = {"pass": False, "estimated": False, "error": str(e)[:120]}
    with rasterio.open(str(hr_out)) as hds:
        hr_arr = hds.read(1); hr_real = np.isfinite(hr_arr) & ~np.isclose(hr_arr, FILL, atol=1e-3)
        lr_real = HN.lr_real_on_hr(lr_out, hds); joint = hr_real & lr_real
        prof = {"driver": "GTiff", "height": hds.height, "width": hds.width, "count": 1, "dtype": "uint8", "crs": hds.crs, "transform": hds.transform, "nodata": 255, "compress": "DEFLATE"}
        tr = hds.transform; hr_res = abs(tr.a)
    del hr_arr
    for nm, arr in (("hr_valid", hr_real), ("lr_valid", lr_real), ("joint_valid", joint)):
        with rasterio.open(out_dir / f"{nm}.tif", "w", **prof) as dd:
            dd.write(arr.astype("uint8"), 1)
    T = P.WIN
    n_tiles_ok = sum(1 for r0 in range(0, joint.shape[0] - T + 1, T) for c0 in range(0, joint.shape[1] - T + 1, T) if joint[r0:r0 + T, c0:c0 + T].mean() >= 0.5)
    rec.update({"hr_res_m_unrounded": hr_res, "hr_res_m": round(hr_res, 3), "n_hr_valid": int(hr_real.sum()), "n_lr_valid": int(lr_real.sum()), "n_joint_valid": int(joint.sum()),
                "joint_area_km2": round(int(joint.sum()) * hr_res * hr_res / 1e6, 3), "n_valid_tiles_256": n_tiles_ok})
    qa = {"offset_within_30m": bool(rec["coreg"].get("pass")), "overlap_ge_1km2": bool(rec.get("overlap_km2", 0) >= P.MIN_OVERLAP_KM2), "tiles_gt_0": bool(n_tiles_ok > 0),
          "coreg_estimated": bool(rec["coreg"].get("estimated"))}
    rec["qa_components"] = qa
    rec["qa_pass"] = bool(rec["coreg"].get("pass") and rec.get("overlap_km2", 0) >= 1.0 and n_tiles_ok > 0)     # harmonize_new.py line 352
    return rec


def mosaic_members(hr_tif: Path, kept_raw: list, lrb, tmp: Path) -> dict:
    """Which kept grids the development mosaic used: hr_mosaic writes tile{i}.tif per kept grid i and returns either one of
    them (single grid / dispersed fallback) or hr_mosaic.tif (the grids whose box meets the ship grid)."""
    name = hr_tif.name
    if name.startswith("tile") and name.endswith(".tif"):
        i = int(name[4:-4]); return {"kind": "single grid" if len(kept_raw) == 1 else "one grid (development mosaic rule)", "grids": [kept_raw[i].name]}
    used = []
    for i, rp in enumerate(kept_raw):
        t = tmp / f"tile{i}.tif"
        if not t.exists():
            continue
        with rasterio.open(str(t)) as ds:
            if ds.crs is None:
                continue
            tb = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
        if max(lrb[0], tb[0]) < min(lrb[2], tb[2]) and max(lrb[1], tb[1]) < min(lrb[3], tb[3]):
            used.append(rp.name)
    return {"kind": "mosaic (rasterio.merge, first wins, native resolution)", "grids": used}


# --------------------------------------------------------------------------- #
# C2a lr_native + C2c sweep (harmonize_new.main development block)
# --------------------------------------------------------------------------- #
def c2a(site: dict, out_dir: Path) -> dict:
    with rasterio.open(out_dir / "hr.tif") as ds:
        hr_res = abs(ds.transform.a)
    with rasterio.open(out_dir / "lr.tif") as ds:
        lr_arr = ds.read(1, masked=True).filled(np.nan); posting = abs(ds.transform.a)
    bw, bw_key = GL.beamwidth_for(site["sonar"])
    if not np.isfinite(lr_arr).any():
        raise SiteFail("lr.tif has no finite cell")
    footprint = 2 * abs(float(np.nanmedian(lr_arr))) * math.tan(math.radians(bw / 2))
    del lr_arr
    lr_native = max(footprint, posting)
    hr_n, lr_n = round(hr_res, 3), round(lr_native, 2)
    return {"hr_native_res_m": hr_n, "lr_native_res_m": lr_n, "lr_native_unrounded_m": lr_native, "hr_res_m_unrounded": hr_res,
            "res_ratio": round(lr_n / hr_n, 2) if hr_n else None, "beam_footprint_m": round(footprint, 2), "posting_m": round(posting, 2),
            "beamwidth_deg": bw, "beamwidth_key": bw_key, "sonar": site["sonar"], "rule": "max(footprint, posting) (C2a)",
            "source": "C2a rule computed by this step (Phase 5)", "code": "src/acq_r01/harmonize_new.py main(): lr_native block"}


def sweep(site: dict, out_dir: Path, lr_native_unrounded: float) -> dict:
    thr = json.loads(P.C2C_CALIBRATION.read_text())["thresholds"]
    old = C2C.pair_dir
    C2C.pair_dir = lambda p: out_dir
    try:
        rec = C2C.sweep(site["pair_id"], lr_native_unrounded, thr)
    finally:
        C2C.pair_dir = old
    rec["thresholds"] = thr; rec["k_source"] = "stage_c2c_recalibrate.sweep (this run)"; rec["swept"] = True
    rec["code"] = "src/discovery/stage_c2c_recalibrate.py sweep -> src/discovery/stage_c5_spectral.py perk_curve/perk_verdict"
    return rec


# --------------------------------------------------------------------------- #
# contract-v2.1 products + usability (rules C1-C3 of the Phase 4 step, unchanged)
# --------------------------------------------------------------------------- #
def products(site: dict, out_dir: Path, cruise_dir: Path, nproc: int, batch_files: int, work: Path) -> dict:
    pid = site["pair_id"]
    work.mkdir(parents=True, exist_ok=True)
    old = R3.REPORT_DIR
    R3.REPORT_DIR = work                                        # the builder's run summary json (and header_check lookup) stay in the work dir
    t0 = time.time()
    try:
        V21.build([(pid, out_dir)], site["ship_cruise"], cruise_dir, "ncei_swath", nproc, batch_files)
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        data_tied, reason = S4.classify_builder_error(e)
        if not data_tied:
            raise StopRun(f"{pid}: product builder failed (not data-tied): {reason}") from e
        d = out_dir / V21.OUT_NAME
        if d.exists():
            shutil.rmtree(d)
        d.mkdir()
        (d / "products.json").write_text(json.dumps(S4.unavailable_products_json(pid, out_dir / "lr.tif", reason), indent=1, default=str))
        return {"available": False, "reason": reason, "rule": "C2 data-tied builder failure", "flags": [], "wall_s": round(time.time() - t0, 1)}
    finally:
        R3.REPORT_DIR = old
    pj = json.loads((out_dir / V21.OUT_NAME / "products.json").read_text())
    ex = json.loads((out_dir / V21.OUT_NAME / "products_extra.json").read_text())
    per_file = ex.get("per_file", [])
    n_listed = len(pj["source"]["files"]); n_read = len(per_file); n_rc0 = sum(1 for r in per_file if r.get("rc") == 0)
    if batch_files <= 1 and (n_read != n_listed or n_rc0 != n_listed):
        raise StopRun(f"{pid}: {n_listed} swath files listed, {n_read} read, {n_rc0} with rc 0")
    return {"available": bool(pj.get("available")) and all(pj["available"].values()), "unavailable_reason": pj.get("unavailable_reason"),
            "flags": list((pj.get("qa_vs_lr_tif") or {}).get("flags") or []), "mb_format": pj["source"]["mb_format"], "n_files_listed": n_listed,
            "n_files_read": n_read, "n_files_rc0": n_rc0, "matches_lr_tif": (pj.get("grid") or {}).get("matches_lr_tif"), "wall_s": round(time.time() - t0, 1),
            "builder": "src/acq_r03/build_products_v2_1.py build (unchanged)"}


# --------------------------------------------------------------------------- #
# eligibility (spec §3.3 items 1-3)
# --------------------------------------------------------------------------- #
def eligibility(harm: dict | None, c2a_rec: dict | None, sweep_rec: dict | None, fail: str | None) -> dict:
    reasons = []
    coreg_pass = bool(harm and harm.get("qa_pass"))
    if fail:
        reasons.append(fail)
    if harm and not coreg_pass:
        q = harm.get("qa_components", {})
        if not q.get("coreg_estimated"):
            reasons.append("co-registration could not be estimated")
        elif not q.get("offset_within_30m"):
            reasons.append("co-registration offset above the 30 m development bound")
        if not q.get("overlap_ge_1km2"):
            reasons.append("overlap below 1 km2")
        if not q.get("tiles_gt_0"):
            reasons.append("no 256-px tile with >= 50 % joint-valid cells")
    k = (sweep_rec or {}).get("max_recoverable_k")
    k_ok = k is not None
    if sweep_rec is not None and not k_ok:
        reasons.append(f"the frozen sweep recovers no k (status {sweep_rec.get('status')})")
    cells = None; hr_ok = False
    if c2a_rec:
        cells = P.WIN * c2a_rec["hr_res_m_unrounded"] / c2a_rec["lr_native_res_m"]
        hr_ok = P.HR_MIN <= c2a_rec["hr_res_m_unrounded"] <= P.HR_MAX
        if not (P.CELLS_MIN <= cells <= P.CELLS_MAX):
            reasons.append(f"{cells:.4f} ship cells across a 256-px window, outside {P.CELLS_MIN}-{P.CELLS_MAX}")
        if not hr_ok:
            reasons.append(f"HR spacing {c2a_rec['hr_res_m_unrounded']:.4f} m outside {P.HR_MIN}-{P.HR_MAX} m")
    cells_ok = cells is not None and P.CELLS_MIN <= cells <= P.CELLS_MAX
    eligible = bool(coreg_pass and k_ok and cells_ok and hr_ok and not fail)
    return {"coreg_pass": coreg_pass, "k_recoverable": bool(k_ok), "cells_across": (round(cells, 6) if cells is not None else None), "cells_in_range": bool(cells_ok),
            "hr_res_in_range": bool(hr_ok), "eligible": eligible, "eligibility_reason": "" if eligible else "; ".join(dict.fromkeys(reasons)) or "not testable",
            "status": "eligible (C1 set at step 1)" if eligible else "not testable",
            "definitions": {"coreg_pass": "harmonize_new qa_pass: offset <= 30 m, overlap >= 1 km2, >= 1 256-px tile with >= 50 % joint-valid cells",
                            "k_recoverable": "stage_c2c_recalibrate.sweep max_recoverable_k is not None",
                            "cells_across": "256 x |hr.tif pixel| (unrounded) / lr_native_res_m, in [3.88, 51.2]",
                            "hr_res_in_range": "0.985 <= |hr.tif pixel| (unrounded) <= 4.99 m"}}
