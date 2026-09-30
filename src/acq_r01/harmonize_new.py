"""ACQ-R02 §6.3 — harmonize + co-register + QA one verified pair with the existing chain
(stage C grid -> harmonize.harmonize_pair -> masked rigid co-registration -> validity masks -> tiles),
then, for DEVELOPMENT pairs only, the current-standard k determination (C2c thresholds), the R3
QC figure and contract-v2 products.  CONFIRMATORY pairs are handled under the seal: outputs to OAK
harmonized_confirmatory/<unit>/<pair>/, and only pass/fail, the co-registration shift and valid-cell
counts are recorded (no residual amplitude statistic, no k, no products).

Usage (Slurm): python -m src.acq_r01.harmonize_new --hr MGDS:5174 --cruise AT42-06 [--nproc 8]
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

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rioxarray  # noqa: F401
from rasterio.warp import transform_bounds, reproject, Resampling
from scipy import ndimage as ndi

from src import harmonize as H, coregister as cor, gmt_grd
from src.acq_r01 import common as C
from src.acq_r01.grid_lr import beamwidth_for
from src.discovery.hr_format_gate import is_rgb_visualization
from src.discovery.stage_c5_sweep import _read_coards_grd

log = logging.getLogger("acq_r02.harm")
R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"
RAW_HR = C.OAK / "raw_hr"
GRIDDED = C.OAK / "raw_lr_gridded"
FILL = -9999.0
USBL_BOUND_M = 30.0
RASTER_EXT = (".tif", ".tiff", ".grd", ".nc", ".asc")
KS = (2, 4, 8, 16, 32)


def _utm(lon, lat):
    z = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + z}"


def catalog_crs(hr_id):
    for cat in (R02.parent / "ACQ-R01" / "discovery_rerun" / "hr_catalog.gpkg", C.REPO / "reports/discovery/hr_catalog.gpkg"):
        try:
            g = gpd.read_file(cat, layer="hr").set_index("hr_id")
        except Exception:
            continue
        if hr_id in g.index:
            for col in ("recovered_crs", "native_crs"):
                v = g.loc[hr_id].get(col) if hasattr(g.loc[hr_id], "get") else None
                if isinstance(v, str) and v.startswith("EPSG"):
                    return v
    return None


def materialize(hr_id, path: Path, out: Path):
    """Float elevation raster -> GeoTIFF with a real CRS (GMT classic / COARDS / rasterio)."""
    if out.exists():
        return out
    crs = catalog_crs(hr_id)
    try:
        if gmt_grd.is_gmt_grd(path):
            return gmt_grd.convert(path, out, crs=crs)
    except Exception:
        pass
    for cand in (str(path), "NETCDF:" + str(path)):
        try:
            with rasterio.open(cand) as ds:
                if ds.count >= 3 and all(d == "uint8" for d in ds.dtypes):
                    return None
                arr = ds.read(1).astype("float32"); tr = ds.transform; src_crs = ds.crs; nod = ds.nodata
            if tr is None or (abs(tr.a - 1) < 1e-12 and abs(tr.e - 1) < 1e-12):
                continue
            use = src_crs.to_string() if src_crs else crs
            if not use:
                continue
            prof = {"driver": "GTiff", "height": arr.shape[0], "width": arr.shape[1], "count": 1, "dtype": "float32", "crs": use,
                    "transform": tr, "nodata": nod if nod is not None else FILL, "compress": "DEFLATE", "BIGTIFF": "IF_SAFER"}
            with rasterio.open(out, "w", **prof) as d:
                d.write(arr, 1)
            return out
        except Exception:
            continue
    try:
        return _read_coards_grd(path, crs, out)
    except Exception:
        return None


def hr_rasters(hr_id) -> list[Path]:
    d = RAW_HR / hr_id.replace(":", "_")
    cands = [p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in RASTER_EXT and not p.name.endswith(".converted.tif")
             and "diff" not in p.name.lower() and "interp" not in p.name.lower() and "Int." not in p.name]
    return [p for p in cands if not is_rgb_visualization(p)[0]]


def hr_mosaic(hr_id, lr_bounds_4326, tmp: Path):
    kept = []
    for i, t in enumerate(hr_rasters(hr_id)):
        mt = materialize(hr_id, t, tmp / f"tile{i}.tif")
        if mt is None:
            continue
        with rasterio.open(str(mt)) as ds:
            if ds.crs is None:
                continue
            tb = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds); crs = str(ds.crs)
        w0, s0, e0, n0 = lr_bounds_4326
        if max(w0, tb[0]) < min(e0, tb[2]) and max(s0, tb[1]) < min(n0, tb[3]):
            kept.append((mt, (min(e0, tb[2]) - max(w0, tb[0])) * (min(n0, tb[3]) - max(s0, tb[1])), crs))
    if not kept:
        return None, 0
    if len(kept) == 1:
        return kept[0][0], 1
    crs0 = kept[0][2]
    if len(kept) > 8 or any(k[2] != crs0 for k in kept):
        return max(kept, key=lambda k: k[1])[0], len(kept)
    import rasterio.merge as rmerge
    srcs = [rasterio.open(k[0]) for k in kept]
    try:
        b = (min(s.bounds.left for s in srcs), min(s.bounds.bottom for s in srcs), max(s.bounds.right for s in srcs), max(s.bounds.top for s in srcs))
        span = max(b[2] - b[0], b[3] - b[1]); native = min(abs(s.res[0]) for s in srcs)
        if span / native > 3000.0:
            # dispersed dive patches (e.g. MGDS:32239: EMARK, Hydra, Puy des Folles tens of km apart): mosaicking would
            # coarsen the HR to span/3000; keep the patch with the largest LR overlap at native resolution instead
            for s_ in srcs:
                s_.close()
            log.warning("%s: %d HR patches span %.0f native cells; keeping the largest-overlap patch, no mosaic", hr_id, len(kept), span / native)
            return max(kept, key=lambda k: k[1])[0], len(kept)
        res = native
        mosaic, tr = rmerge.merge(srcs, res=res, nodata=FILL)
        out = tmp / "hr_mosaic.tif"
        prof = {"driver": "GTiff", "height": mosaic.shape[1], "width": mosaic.shape[2], "count": 1, "dtype": "float32", "crs": crs0,
                "transform": tr, "nodata": FILL, "compress": "DEFLATE", "BIGTIFF": "IF_SAFER"}
        with rasterio.open(out, "w", **prof) as d:
            d.write(mosaic[0].astype("float32"), 1)
        return out, len(kept)
    finally:
        for s in srcs:
            s.close()


def lr_to_tif(cruise, tmp: Path):
    p = GRIDDED / f"{cruise}__union.grd"
    out = tmp / f"lr_{cruise}.tif"
    with rasterio.open(str(p)) as ds:
        arr = ds.read(1).astype("float32"); prof = {"driver": "GTiff", "height": ds.height, "width": ds.width, "count": 1, "dtype": "float32",
                                                    "crs": ds.crs.to_string() if ds.crs else "EPSG:4326", "transform": ds.transform,
                                                    "nodata": ds.nodata if ds.nodata is not None else FILL}
    with rasterio.open(out, "w", **prof) as d:
        d.write(arr, 1)
    return out, abs(prof["transform"].a) * 111320 * math.cos(math.radians((prof["transform"].f + prof["transform"].e * prof["height"] / 2)))


def lr_real_on_hr(lr_tif, hr_ds):
    with rasterio.open(str(lr_tif)) as ds:
        src = ds.read(1, masked=True).filled(np.nan).astype("float64"); m = np.isfinite(src).astype("float32"); s_tr, s_crs = ds.transform, ds.crs
    dst = np.zeros((hr_ds.height, hr_ds.width), "float32")
    reproject(m, dst, src_transform=s_tr, src_crs=s_crs, dst_transform=hr_ds.transform, dst_crs=hr_ds.crs, src_nodata=0.0, dst_nodata=0.0, resampling=Resampling.average)
    return ndi.binary_erosion(dst >= 0.5, iterations=1, border_value=0)


def lock_dir(d: Path):
    for p in d.rglob("*"):
        if p.is_file():
            p.chmod(0o444)


# --------------------------------------------------------------------------- #
# §6.2 H1 cross-check: the NCEI processed grid is NOT the LR source (LR is gridded from the raw swath
# like every other pair); it is compared with the raw-swath LR over the harmonized LR grid (median
# offset and robust sigma), development pairs only.
# --------------------------------------------------------------------------- #
STAGE1_MANIFEST = C.REPO / "reports/discovery/stage1_download_manifest.csv"


def processed_lr_crosscheck(cruise: str, lr_out: Path, tmp: Path) -> dict:
    import gzip
    import requests
    rec = {"cruise": cruise}
    url = None
    if STAGE1_MANIFEST.exists():
        m = pd.read_csv(STAGE1_MANIFEST)
        hit = m[(m.role == "LR_processed") & (m.fetch_id == f"NCEI_MBBDB:{cruise}")]
        if len(hit):
            url = str(hit.iloc[0].url)
    if url is None:
        rec["status"] = "no_processed_product_listed"; return rec
    rec["url"] = url
    d = GRIDDED / "processed_crosscheck" / cruise; d.mkdir(parents=True, exist_ok=True)
    p = d / url.rsplit("/", 1)[-1]
    if not p.exists():
        with requests.get(url, headers={"User-Agent": "auv_ship_colocated_bathy/acq_r02"}, stream=True, timeout=600) as g:
            g.raise_for_status()
            with p.open("wb") as fh:
                for ch in g.iter_content(1 << 20):
                    fh.write(ch)
    rec["bytes"] = p.stat().st_size; rec["sha256"] = C.sha256_file(p)
    raw = p
    if p.suffix == ".gz":
        raw = p.with_suffix("")
        if not raw.exists():
            with gzip.open(p, "rb") as src, raw.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    if raw.suffix.lower() in (".xyz", ".txt", ".csv", ".dat"):
        rec["status"] = "processed_product_is_xyz_points_not_gridded"; return rec
    with rasterio.open(str(lr_out)) as ds:
        lr = ds.read(1, masked=True).filled(np.nan); tcrs, ttr = ds.crs, ds.transform; shp = lr.shape
        lr = np.where(np.isclose(lr, FILL, atol=1e-3), np.nan, lr)
    with rasterio.open(str(raw)) as ps:
        pcrs = ps.crs
        b = ps.bounds
        if pcrs is None and -180 <= b.left <= 180 and -90 <= b.bottom <= 90 and -90 <= b.top <= 90:
            pcrs = rasterio.crs.CRS.from_epsg(4326); rec["processed_crs_assumed"] = "EPSG:4326 (no CRS in file; geographic range)"
        if pcrs is None:
            rec["status"] = "processed_product_has_no_crs"; return rec
        src = ps.read(1, masked=True).filled(np.nan).astype("float32")
        if ps.nodata is not None:
            src = np.where(np.isclose(src, ps.nodata), np.nan, src)
        if np.nanmedian(src) > 0:
            src = -src; rec["processed_sign_flipped"] = True
        dst = np.full(shp, np.nan, "float32")
        reproject(src, dst, src_transform=ps.transform, src_crs=pcrs, dst_transform=ttr, dst_crs=tcrs,
                  resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan)
    ok = np.isfinite(lr) & np.isfinite(dst)
    if ok.sum() < 100:
        rec["status"] = f"insufficient_common_cells ({int(ok.sum())})"; return rec
    diff = lr[ok] - dst[ok]
    med = float(np.median(diff)); mad = float(np.median(np.abs(diff - med)))
    rec.update({"status": "ok", "processed_file": raw.name, "processed_res_native": [abs(ps.transform.a), abs(ps.transform.e)], "n_common": int(ok.sum()),
                "median_offset_m_rawswath_minus_processed": round(med, 3), "robust_sigma_m": round(1.4826 * mad, 3),
                "p05_m": round(float(np.percentile(diff, 5)), 3), "p95_m": round(float(np.percentile(diff, 95)), 3)})
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hr", required=True); ap.add_argument("--cruise", required=True); ap.add_argument("--nproc", type=int, default=8)
    ap.add_argument("--batch-files", type=int, default=1)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    t0 = time.time()
    C.assert_no_lockbox_cruise([a.cruise])
    v = pd.read_csv(R02 / "verification" / "candidates_verified.csv").set_index("hr_id")
    ua = json.loads((R02 / "verification" / "units_after.json").read_text())
    desig, unit_id = {}, {}
    for u in ua["units"]:
        for k, val in u["designations"].items():
            desig[k] = val; unit_id[k] = u["unit_id"]
    row = v.loc[a.hr]; d = desig.get(a.hr, "development"); unit = unit_id.get(a.hr, "")
    if str(d).startswith("dropped"):
        log.error("%s is dropped (%s); nothing to harmonize", a.hr, d); return 2
    conf = str(d).startswith("confirmatory")
    uid = a.hr.split(":")[1]
    pid = f"{a.cruise}__{'MGDS' if a.hr.startswith('MGDS') else 'PANGAEA'}_{uid}"
    out_dir = (C.HARMONIZED_CONFIRMATORY / unit / pid) if conf else (C.OAK / "harmonized" / pid)
    rec = {"pair_id": pid, "hr_id": a.hr, "lr_cruise": a.cruise, "designation": d, "unit": unit, "out_dir": str(out_dir),
           "hr_cruise": row.get("hr_cruise_final", ""), "set": row.get("set", "")}
    tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r02_harm" / pid; tmp.mkdir(parents=True, exist_ok=True)
    grid_rec = json.loads((R02 / "grid" / f"{a.cruise}.json").read_text())
    lr_tif, lr_posting_m = lr_to_tif(a.cruise, tmp)
    with rasterio.open(str(lr_tif)) as ds:
        lrb = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
    hr_tif, n_tiles = hr_mosaic(a.hr, lrb, tmp)
    if hr_tif is None:
        rec.update({"status": "reject", "reason": "no float HR raster overlaps the LR grid"}); _write(rec); return 1
    rec["hr_tiles_used"] = n_tiles
    with rasterio.open(str(hr_tif)) as ds:
        hb = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
    clon = (max(lrb[0], hb[0]) + min(lrb[2], hb[2])) / 2; clat = (max(lrb[1], hb[1]) + min(lrb[3], hb[3])) / 2
    tcrs = _utm(clon, clat); rec["target_crs"] = tcrs
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        hp = H.harmonize_pair(pair_id=pid, hr_raw=hr_tif, lr_raw=lr_tif, target_crs=tcrs, resample_kernel="bilinear", nodata=FILL,
                              out_dir=out_dir, vertical_sign="negative_down", min_overlap_area_km2=1.0)
        rec["overlap_km2"] = round(hp.overlap_area_km2, 3)
    except Exception as e:
        rec.update({"status": "reject", "reason": f"harmonize: {str(e)[:150]}"}); _write(rec); return 1
    hr_out, lr_out = out_dir / "hr.tif", out_dir / "lr.tif"
    # masked co-registration (the stage F fix)
    try:
        hr_da = rioxarray.open_rasterio(str(hr_out), masked=True).squeeze(); lr_da = rioxarray.open_rasterio(str(lr_out), masked=True).squeeze()
        cg = cor.estimate_rigid_xyz(hr_da, lr_da)
        corrected = cor.apply_xyz(hr_da, cg.dx_m, cg.dy_m, cg.dz_m)
        corrected.rio.write_nodata(np.nan, inplace=True)
        corrected.rio.to_raster(hr_out, compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")
        off = float(np.hypot(cg.dx_m, cg.dy_m))
        rec["coreg"] = {"dx_m": round(cg.dx_m, 2), "dy_m": round(cg.dy_m, 2), "dz_m": round(cg.dz_m, 2), "offset_m": round(off, 2), "n": int(cg.n_samples),
                        "pass": bool(off <= USBL_BOUND_M)}
        if not conf:
            rec["coreg"]["post_residual_mad_m"] = round(cg.post_residual_mad_m, 3)
    except Exception as e:
        rec["coreg"] = {"pass": False, "error": str(e)[:120]}
    with rasterio.open(str(hr_out)) as hds:
        hr_arr = hds.read(1); hr_real = np.isfinite(hr_arr) & ~np.isclose(hr_arr, FILL, atol=1e-3)
        lr_real = lr_real_on_hr(lr_out, hds); joint = hr_real & lr_real
        prof = {"driver": "GTiff", "height": hds.height, "width": hds.width, "count": 1, "dtype": "uint8", "crs": hds.crs, "transform": hds.transform, "nodata": 255, "compress": "DEFLATE"}
        tr = hds.transform; hr_res = abs(tr.a)
    for nm, arr in (("hr_valid", hr_real), ("lr_valid", lr_real), ("joint_valid", joint)):
        with rasterio.open(out_dir / f"{nm}.tif", "w", **prof) as dd:
            dd.write(arr.astype("uint8"), 1)
    T = 256; n_tiles_ok = sum(1 for r0 in range(0, joint.shape[0] - T + 1, T) for c0 in range(0, joint.shape[1] - T + 1, T) if joint[r0:r0 + T, c0:c0 + T].mean() >= 0.5)
    rec.update({"hr_res_m": round(hr_res, 3), "n_hr_valid": int(hr_real.sum()), "n_lr_valid": int(lr_real.sum()), "n_joint_valid": int(joint.sum()),
                "joint_area_km2": round(int(joint.sum()) * hr_res * hr_res / 1e6, 3), "n_valid_tiles_256": n_tiles_ok,
                "qa_pass": bool(rec.get("coreg", {}).get("pass") and rec.get("overlap_km2", 0) >= 1.0 and n_tiles_ok > 0)})
    if conf:
        rec["status"] = "harmonized_confirmatory (sealed: pass/fail, shift, counts only)"
        _write(rec); lock_dir(out_dir); shutil.rmtree(tmp, ignore_errors=True); return 0
    # ---- development only: lr_native (C2a max rule), R3 QC figure, k sweep, contract-v2 products ----
    with rasterio.open(str(lr_out)) as ds:
        lr_arr = ds.read(1, masked=True).filled(np.nan); posting = abs(ds.transform.a)
    jr = joint & hr_real
    rec["hr_p50_over_joint_m"] = round(float(np.nanpercentile(hr_arr[jr], 50)), 1) if jr.any() else None
    bw, bw_key = beamwidth_for(grid_rec.get("sonar", "")); depth = abs(float(np.nanmedian(lr_arr))) if np.isfinite(lr_arr).any() else grid_rec["footprint_depth_m"]
    footprint = 2 * depth * math.tan(math.radians(bw / 2))
    rec["lr_native"] = {"beam_footprint_m": round(footprint, 2), "posting_m": round(posting, 2), "lr_native_m": round(max(footprint, posting), 2), "beamwidth_deg": bw, "rule": "max(footprint, posting) (C2a)"}
    lr_native = max(footprint, posting)
    try:
        from src.discovery import stage_c2c_recalibrate as C2C
        C2C.pair_dir = lambda p: out_dir
        thr = json.loads((C.REPO / "reports/discovery/stage_c2c_calibration.json").read_text())["thresholds"]
        rec["k_sweep"] = C2C.sweep(pid, lr_native, thr); rec["k_sweep"]["thresholds"] = thr
    except Exception as e:
        rec["k_sweep"] = {"status": f"error: {str(e)[:120]}"}
    try:
        from src.discovery import stage_reaudit_r3 as R3
        R3.HARM = out_dir.parent
        qcd = C.OAK / "qc" / "acq_r02"; qcd.mkdir(parents=True, exist_ok=True)
        meta = {"reaudit_disposition": "acq_r02_new", "role": d, "morphology": "", "source_type": "float", "selected_source": a.hr,
                "lr_native_m": rec["lr_native"]["lr_native_m"], "f5_joint_fraction": round(float(joint.sum() / max(1, (hr_real | lr_real).sum())), 4),
                "f5_n_valid_tiles": n_tiles_ok, "dz_apply": rec.get("coreg", {}).get("dz_m")}
        png = qcd / f"{pid}.png"; R3.figure(pid, meta, png); rec["qc_figure"] = str(png)
    except Exception as e:
        rec["qc_figure_error"] = str(e)[:120]
    try:
        from src.acq_r01 import build_products_v2 as V2
        cruise_dir = C.RAW_SWATH_OAK / a.cruise
        res = V2.build_cruise(a.cruise, None, a.nproc, None, a.batch_files,
                              spec=[{"pair_id": pid, "pair_dir": str(out_dir), "cruise_dir": str(cruise_dir), "src_kind": "ncei_swath" if not a.cruise.startswith("PANGAEA_") else "provider_swath"}])
        rec["products_v2"] = res[0] if res else None
    except Exception as e:
        rec["products_v2"] = {"error": str(e)[:150]}
    if str(row.get("set", "")) == "H1":
        try:
            rec["processed_lr_crosscheck"] = processed_lr_crosscheck(a.cruise, lr_out, tmp)
        except Exception as e:
            rec["processed_lr_crosscheck"] = {"status": f"error: {str(e)[:120]}"}
    rec["status"] = "harmonized_development"; rec["wall_s"] = round(time.time() - t0, 1)
    _write(rec); lock_dir(out_dir); shutil.rmtree(tmp, ignore_errors=True)
    log.info("%s", json.dumps({k: rec[k] for k in ("pair_id", "status", "overlap_km2", "coreg", "n_valid_tiles_256", "lr_native", "k_sweep")}, default=str)[:800])
    return 0


def _write(rec):
    (R02 / "harmonize").mkdir(exist_ok=True)
    (R02 / "harmonize" / f"{rec['pair_id']}.json").write_text(json.dumps(rec, indent=1, default=str))
    log.info("[%s] %s", rec["pair_id"], rec.get("status"))


if __name__ == "__main__":
    sys.exit(main())
