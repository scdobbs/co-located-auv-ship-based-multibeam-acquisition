"""ACQ-R03 §6 / rulings R5 — apply the stage-C standard to 2009_Amundsen__MGDS_30046 and unify the lr_native depth
definition for both lu18 pairs.

Depth definition (stated once, applied to both pairs): the MEDIAN DEPTH OF THE PAIR'S OWN HR (all valid cells of the
harmonized hr.tif).  Stage-C cell = 2 · depth · tan(bw/2), bw = 1° (Kongsberg EM302).  C2a lr_native = max(footprint at
that depth, grid posting).

30046: regrid the LR from the raw swath on OAK (raw_lr_swath/2009_Amundsen/) with the stage-C recipe (`mbgrid -A2 -G3
-F1 -C0 -M`, raw mode) over the pair's HR footprint + 1 km, at the own-depth cell; harmonize against the existing
(June, co-registered) hr.tif; masked rigid co-registration QA; masks; 256-tiles; C2a lr_native; C2c k sweep; R3 QC
figure; contract-v2.1 products.  Outputs go to a NEW versioned directory <pair>/lrv2_1/ (hr.tif, lr.tif, masks,
footprint, ship_products_v2_1/ — so the contract's "<dir of lr.tif>/ship_products_v2_1/" rule resolves), with the
ruling's names as copies/links in the pair dir: lr_v2_1.tif, hr_v2_1.tif, *_valid_v2_1.tif, ship_products_v2_1_lrv2_1 ->
lrv2_1/ship_products_v2_1.  The June lr.tif, hr.tif, masks and products are not modified.
30047: lr_native under the unified depth definition and its k sweep re-run; nothing regridded.
Records: reports_post_grl_review/ACQ-R03/{grid,harmonize}/*_r5.json.
Usage (job): python -m src.acq_r03.amundsen_regrid_r5 [--nproc 4]
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
from pathlib import Path

import numpy as np
import rasterio
import rioxarray  # noqa: F401
from rasterio.warp import transform_bounds, reproject, Resampling
from scipy import ndimage as ndi

from src import harmonize as H, coregister as cor
from src.acq_r01 import common as C
from src.acq_r01.grid_lr import prepare, beamwidth_for
from src.acq_r01.harmonize_new import lr_real_on_hr, lock_dir, FILL, USBL_BOUND_M
from src.acq_r03 import common as R

log = logging.getLogger("acq_r03.r5")
CRUISE = "2009_Amundsen"; SONAR = "Kongsberg EM302"
P46 = "2009_Amundsen__MGDS_30046"; P47 = "2009_Amundsen__MGDS_30047"
GRIDDED = C.OAK / "raw_lr_gridded"
DEPTH_DEF = "median depth of the pair's own HR (all valid cells of the harmonized hr.tif), positive metres"


def own_hr_depth(pdir: Path) -> float:
    with rasterio.open(pdir / "hr.tif") as ds:
        a = ds.read(1, masked=True).filled(np.nan)
    a = np.where(np.isclose(a, FILL, atol=1e-3), np.nan, a)
    return float(abs(np.nanmedian(a)))


def footprint_m(depth: float, bw: float) -> float:
    return 2 * depth * math.tan(math.radians(bw / 2))


def regrid_30046(pdir: Path, cell_m: float, depth: float, bw: float, wd: Path) -> dict:
    t0 = time.time()
    dl, files, fmt = prepare(CRUISE, wd)
    with rasterio.open(pdir / "hr.tif") as ds:
        w, s, e, n = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
    mlat = (s + n) / 2
    dlon = 1 / (111320 * max(0.2, math.cos(math.radians(mlat)))); dlat = 1 / 111320
    Rg = f"{w - 1000 * dlon}/{e + 1000 * dlon}/{s - 1000 * dlat}/{n + 1000 * dlat}"
    root = f"grid_{P46}_lrv2_1"
    cmd = ["mbgrid", "-I", dl.name, "-O", root, "-R", Rg, "-E", f"{cell_m * dlon}/{cell_m * dlat}/degrees", "-A2", "-G3", "-F1", "-C0", "-M"]
    r = C.mb(cmd, cwd=str(wd), timeout=6 * 3600)
    grd = wd / f"{root}.grd"
    if not grd.exists():
        raise RuntimeError(f"mbgrid produced no grid: {(r.stderr or r.stdout)[-400:]}")
    outs = {}
    for suf in ("", "_num", "_sd"):
        src = wd / f"{root}{suf}.grd"
        if src.exists():
            dst = GRIDDED / f"{P46}__lrv2_1{suf}.grd"
            if dst.exists():
                dst.chmod(0o644)
            shutil.copyfile(src, dst); dst.chmod(0o444); outs[suf or "grid"] = str(dst)
    with rasterio.open(str(grd)) as ds:
        arr = ds.read(1, masked=True).filled(np.nan)
    rec = {"pair_id": P46, "cruise": CRUISE, "ruling": "rulings_ACQ-R03 R5", "n_files": len(files), "format": fmt, "sonar": SONAR, "beamwidth_deg": bw,
           "depth_definition": DEPTH_DEF, "own_hr_median_depth_m": round(depth, 1), "cell_m": round(cell_m, 3), "region": Rg,
           "mbgrid_command": C.mb_cmdline(cmd), "mode": "raw", "outputs": outs, "grid_depth_median": round(float(np.nanmedian(arr)), 1) if np.isfinite(arr).any() else None,
           "grid_fill_fraction": round(float(np.isfinite(arr).mean()), 4), "wall_s": round(time.time() - t0, 1), "mbsystem": C.MBSYSTEM_VERSION, "code_commit": C.git_commit()}
    R.write_json(R.REPORT_DIR / "grid" / f"{P46}_lrv2_1_r5.json", rec)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--nproc", type=int, default=4)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    C.assert_no_lockbox([P46, P47]); C.assert_no_lockbox_cruise([CRUISE])
    bw, _ = beamwidth_for(SONAR)
    harm = C.OAK / "harmonized"; p46 = harm / P46; p47 = harm / P47
    d46, d47 = own_hr_depth(p46), own_hr_depth(p47)
    fp46, fp47 = footprint_m(d46, bw), footprint_m(d47, bw)
    thr = json.loads((C.REPO / "reports/discovery/stage_c2c_calibration.json").read_text())["thresholds"]
    from src.discovery import stage_c2c_recalibrate as C2C
    # ---- 30047: unified lr_native + k sweep (no regrid) ----
    with rasterio.open(p47 / "lr.tif") as ds:
        post47 = abs(ds.transform.a)
    ln47 = max(fp47, post47)
    C2C.pair_dir = lambda p: p47
    k47 = C2C.sweep(P47, ln47, thr)
    rec47 = {"pair_id": P47, "ruling": "rulings_ACQ-R03 R5", "depth_definition": DEPTH_DEF, "own_hr_median_depth_m": round(d47, 1),
             "lr_native": {"beam_footprint_m": round(fp47, 2), "posting_m": round(post47, 2), "lr_native_m": round(ln47, 2), "beamwidth_deg": bw, "rule": "max(footprint at own-HR median depth, posting) (C2a)"},
             "previous_lr_native_m": 4.87, "previous_depth_basis": "harmonized-LR median depth (279 m)", "k_sweep": {**k47, "thresholds": thr}, "regridded": False}
    R.write_json(R.REPORT_DIR / "harmonize" / f"{P47}_r5.json", rec47)
    log.info("30047: depth %.1f fp %.2f posting %.2f lr_native %.2f k=%s", d47, fp47, post47, ln47, k47.get("max_recoverable_k"))
    # ---- 30046: regrid at own-depth cell ----
    cell = fp46
    wd = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r03_r5" / CRUISE
    grid_rec = regrid_30046(p46, cell, d46, bw, wd)
    stage = p46 / "lrv2_1"; stage.mkdir(exist_ok=True)
    for q in stage.rglob("*"):
        if q.is_file():
            q.chmod(0o644)
    tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r03_r5" / "harm"; tmp.mkdir(parents=True, exist_ok=True)
    # materialise the new grid as a GeoTIFF (GDAL puts the pixel centres on the netCDF nodes)
    src_grd = Path(grid_rec["outputs"]["grid"]); lr_tif = tmp / "lr_lrv2_1.tif"
    with rasterio.open(str(src_grd)) as ds:
        arr = ds.read(1).astype("float32"); prof = {"driver": "GTiff", "height": ds.height, "width": ds.width, "count": 1, "dtype": "float32",
                                                    "crs": ds.crs.to_string() if ds.crs else "EPSG:4326", "transform": ds.transform, "nodata": ds.nodata if ds.nodata is not None else FILL}
    with rasterio.open(lr_tif, "w", **prof) as d:
        d.write(arr, 1)
    with rasterio.open(p46 / "hr.tif") as ds:
        tcrs = ds.crs.to_string()
    hp = H.harmonize_pair(pair_id=P46, hr_raw=p46 / "hr.tif", lr_raw=lr_tif, target_crs=tcrs, resample_kernel="bilinear", nodata=FILL,
                          out_dir=stage, vertical_sign="negative_down", min_overlap_area_km2=1.0)
    hr_out, lr_out = stage / "hr.tif", stage / "lr.tif"
    hr_da = rioxarray.open_rasterio(str(hr_out), masked=True).squeeze(); lr_da = rioxarray.open_rasterio(str(lr_out), masked=True).squeeze()
    cg = cor.estimate_rigid_xyz(hr_da, lr_da)
    corrected = cor.apply_xyz(hr_da, cg.dx_m, cg.dy_m, cg.dz_m); corrected.rio.write_nodata(np.nan, inplace=True)
    corrected.rio.to_raster(hr_out, compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")
    off = float(np.hypot(cg.dx_m, cg.dy_m))
    coreg = {"dx_m": round(cg.dx_m, 2), "dy_m": round(cg.dy_m, 2), "dz_m": round(cg.dz_m, 2), "offset_m": round(off, 2), "n": int(cg.n_samples), "pass": bool(off <= USBL_BOUND_M),
             "post_residual_mad_m": round(cg.post_residual_mad_m, 3), "note": "re-co-registration of the June (already co-registered) HR against the new LR; expected small"}
    with rasterio.open(str(hr_out)) as hds:
        hr_arr = hds.read(1); hr_real = np.isfinite(hr_arr) & ~np.isclose(hr_arr, FILL, atol=1e-3)
        lr_real = lr_real_on_hr(lr_out, hds); joint = hr_real & lr_real
        mprof = {"driver": "GTiff", "height": hds.height, "width": hds.width, "count": 1, "dtype": "uint8", "crs": hds.crs, "transform": hds.transform, "nodata": 255, "compress": "DEFLATE"}
        hr_res = abs(hds.transform.a)
    for nm, arr_ in (("hr_valid", hr_real), ("lr_valid", lr_real), ("joint_valid", joint)):
        with rasterio.open(stage / f"{nm}.tif", "w", **mprof) as dd:
            dd.write(arr_.astype("uint8"), 1)
    T = 256; n_tiles = sum(1 for r0 in range(0, joint.shape[0] - T + 1, T) for c0 in range(0, joint.shape[1] - T + 1, T) if joint[r0:r0 + T, c0:c0 + T].mean() >= 0.5)
    with rasterio.open(str(lr_out)) as ds:
        post46 = abs(ds.transform.a)
    ln46 = max(fp46, post46)
    C2C.pair_dir = lambda p: stage
    k46 = C2C.sweep(P46, ln46, thr)
    rec = {"pair_id": P46, "ruling": "rulings_ACQ-R03 R5", "depth_definition": DEPTH_DEF, "own_hr_median_depth_m": round(d46, 1), "grid": grid_rec,
           "out_dir": str(stage), "overlap_km2": round(hp.overlap_area_km2, 3), "coreg": coreg, "hr_res_m": round(hr_res, 3),
           "n_hr_valid": int(hr_real.sum()), "n_lr_valid": int(lr_real.sum()), "n_joint_valid": int(joint.sum()), "joint_area_km2": round(int(joint.sum()) * hr_res * hr_res / 1e6, 3),
           "n_valid_tiles_256": n_tiles, "qa_pass": bool(coreg["pass"] and hp.overlap_area_km2 >= 1.0 and n_tiles > 0),
           "lr_native": {"beam_footprint_m": round(fp46, 2), "posting_m": round(post46, 2), "lr_native_m": round(ln46, 2), "beamwidth_deg": bw, "rule": "max(footprint at own-HR median depth, posting) (C2a)"},
           "previous": {"lr_native_m": 16.0, "posting_m": 16.01, "grid": "2009_Amundsen__MGDS_30045.grd (June pilot, 915 m)"}, "k_sweep": {**k46, "thresholds": thr}}
    try:
        from src.discovery import stage_reaudit_r3 as R3
        R3.HARM = p46
        qcd = C.OAK / "qc" / "acq_r03"; qcd.mkdir(parents=True, exist_ok=True)
        meta = {"reaudit_disposition": "acq_r03_r5", "role": "development", "morphology": "shelf_slope", "source_type": "float", "selected_source": "MGDS:30046",
                "lr_native_m": rec["lr_native"]["lr_native_m"], "f5_joint_fraction": round(float(joint.sum() / max(1, (hr_real | lr_real).sum())), 4), "f5_n_valid_tiles": n_tiles, "dz_apply": coreg["dz_m"]}
        png = qcd / f"{P46}_lrv2_1.png"; R3.figure("lrv2_1", meta, png); rec["qc_figure"] = str(png)
    except Exception as e:
        rec["qc_figure_error"] = str(e)[:150]
    from src.acq_r03 import build_products_v2_1 as V21
    res = V21.build([(P46, stage)], CRUISE, C.RAW_SWATH_OAK / CRUISE, "ncei_swath", a.nproc, 1)
    rec["products_v2_1"] = res[0] if res else None
    # ruling names in the pair dir: copies of the versioned LR/HR/masks, link to the products
    for src_name, dst_name in (("lr.tif", "lr_v2_1.tif"), ("hr.tif", "hr_v2_1.tif"), ("hr_valid.tif", "hr_valid_v2_1.tif"), ("lr_valid.tif", "lr_valid_v2_1.tif"),
                               ("joint_valid.tif", "joint_valid_v2_1.tif"), ("footprint.geojson", "footprint_v2_1.geojson")):
        dst = p46 / dst_name
        if dst.exists() or dst.is_symlink():
            dst.chmod(0o644); dst.unlink()
        shutil.copyfile(stage / src_name, dst)
    link = p46 / "ship_products_v2_1_lrv2_1"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to("lrv2_1/ship_products_v2_1")
    rec["ruling_names"] = {"lr_v2_1.tif": "copy of lrv2_1/lr.tif", "hr_v2_1.tif": "copy of lrv2_1/hr.tif (re-co-registered)", "ship_products_v2_1_lrv2_1": "symlink -> lrv2_1/ship_products_v2_1"}
    rec["status"] = "harmonized_development_lrv2_1"
    R.write_json(R.REPORT_DIR / "harmonize" / f"{P46}_lrv2_1_r5.json", rec)
    lock_dir(stage)
    for q in p46.iterdir():
        if q.is_file() and "v2_1" in q.name:
            q.chmod(0o444)
    shutil.rmtree(wd, ignore_errors=True); shutil.rmtree(tmp, ignore_errors=True)
    log.info("%s", json.dumps({k: rec[k] for k in ("coreg", "n_valid_tiles_256", "lr_native", "qa_pass")}, default=str))
    log.info("k46=%s k47=%s", k46.get("max_recoverable_k"), k47.get("max_recoverable_k"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
