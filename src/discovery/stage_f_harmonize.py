"""Phase 2 Stage F — harmonize + co-register + QA the 32 new pairs (Option A).

Reuses the established pipeline (harmonize.harmonize_pair, coregister,
qc.evaluate, qa.compute). The 21 validated pairs are untouchable (not touched).
Writes harmonized products to $DATA_ROOT/harmonized/<pair_id>/ + a v1.1 QA
overlay per pair. NO manifest/OAK writes (Stage G). HOLD for review after.

Multi-tile HR fix (the 2009_Amundsen×30045 lesson): mosaic the AUV tiles with
actual LR coverage, not the largest tile.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
import rasterio
import rioxarray  # noqa: F401  (registers .rio accessor)
import xarray as xr
from rasterio.warp import transform_bounds

from src import harmonize as H
from src import coregister as cor
from src import qc
from src import qa as QA
from src.discovery.stage_c5_sweep import materialize_hr, staged_hr_raster, catalog_crs

log = logging.getLogger("stage_f")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
GRIDDED = DATA / "raw_lr_gridded"
STAGING = DATA / "staging_phase1"
OUTROOT = DATA / "harmonized"
RASTER_EXT = (".tif", ".tiff", ".grd", ".nc", ".asc")

FILL = -9999.0
KERNEL = "bilinear"           # config resample_kernel (never nearest)
MIN_OVERLAP_KM2 = 1.0
USBL_BOUND_M = 30.0
MAD_THRESH_M = 5.0


def _utm_epsg(lon, lat):
    z = int((lon + 180) // 6) + 1
    return 32600 + z if lat >= 0 else 32700 + z


def _lr_to_tif(cruise, hr_id, tmp):
    """Materialize the gridded ship LR (.grd) to a GeoTIFF rioxarray can open."""
    p = GRIDDED / f"{cruise}__{hr_id.replace(':', '_')}.grd"
    if not p.exists():
        p = GRIDDED / f"{cruise}__union.grd"
    if not p.exists():
        return None
    out = tmp / f"lr_{cruise}.tif"
    if out.exists():
        return out
    with rasterio.open(str(p)) as ds:
        arr = ds.read(1).astype("float32")
        prof = {"driver": "GTiff", "height": ds.height, "width": ds.width, "count": 1,
                "dtype": "float32", "crs": ds.crs.to_string() if ds.crs else "EPSG:4326",
                "transform": ds.transform, "nodata": ds.nodata if ds.nodata is not None else FILL}
    with rasterio.open(out, "w", **prof) as d:
        d.write(arr, 1)
    return out


def _hr_mosaic(hr_id, lr_bounds_4326, tmp):
    """Materialize all HR tiles, keep those overlapping LR, mosaic them."""
    d = STAGING / hr_id.replace(":", "_")
    tiles = [p for p in d.iterdir()
             if p.suffix.lower() in RASTER_EXT and not p.name.endswith(".provenance.json")
             and not p.name.lower().endswith(".pdf") and "diff" not in p.name.lower()
             and "interp" not in p.name.lower() and "Int." not in p.name]
    # Re-audit C2: drop RGB visualization renders (3-band uint8) — they are not
    # bathymetry; reading band 1 = red channel caused the spurious "+255".
    from .hr_format_gate import is_rgb_visualization
    tiles = [p for p in tiles if not is_rgb_visualization(p)[0]]
    kept = []   # (path, overlap_area_deg2)
    w0, s0, e0, n0 = lr_bounds_4326
    for i, t in enumerate(tiles):
        # real hr_id (so catalog_crs resolves) + per-tile subdir (distinct outputs)
        mt = materialize_hr(hr_id, t, tmp / f"tile{i}")
        if mt is None:
            continue
        try:
            with rasterio.open(str(mt)) as ds:
                tb = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds) if ds.crs else None
                crs = ds.crs
        except Exception:
            continue
        if tb and max(w0, tb[0]) < min(e0, tb[2]) and max(s0, tb[1]) < min(n0, tb[3]):
            ov = (min(e0, tb[2]) - max(w0, tb[0])) * (min(n0, tb[3]) - max(s0, tb[1]))
            kept.append((mt, ov, str(crs)))
    if not kept:
        return None
    if len(kept) == 1:
        return kept[0][0]
    # Memory-bounded merge: same-CRS tiles via rasterio.merge with a resolution
    # cap (output <= ~3000 px/side). >8 tiles or mixed CRS -> single best tile.
    crs0 = kept[0][2]
    if len(kept) > 8 or any(k[2] != crs0 for k in kept):
        best = max(kept, key=lambda k: k[1])
        log.warning("[%s] %d tiles -> using single best-LR-covered tile (avoid OOM)", hr_id, len(kept))
        return best[0]
    import rasterio.merge as rmerge
    srcs = [rasterio.open(k[0]) for k in kept]
    try:
        b = (min(s.bounds.left for s in srcs), min(s.bounds.bottom for s in srcs),
             max(s.bounds.right for s in srcs), max(s.bounds.top for s in srcs))
        span = max(b[2] - b[0], b[3] - b[1])
        native = min(abs(s.res[0]) for s in srcs)
        res = max(native, span / 3000.0)
        mosaic, tr = rmerge.merge(srcs, res=res, nodata=FILL)
        out = tmp / f"hr_mosaic_{hr_id.replace(':', '_')}.tif"
        prof = {"driver": "GTiff", "height": mosaic.shape[1], "width": mosaic.shape[2],
                "count": 1, "dtype": "float32", "crs": crs0, "transform": tr,
                "nodata": FILL, "compress": "DEFLATE", "BIGTIFF": "IF_SAFER"}
        with rasterio.open(out, "w", **prof) as d:
            d.write(mosaic[0].astype("float32"), 1)
        return out
    finally:
        for s in srcs:
            s.close()


def harmonize_one(pair):
    cruise, hr_id, role = pair["cruise"], pair["hr_id"], pair["role"]
    pid = pair["pair_id"]
    tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "stage_f" / pid
    tmp.mkdir(parents=True, exist_ok=True)
    rec = {"pair_id": pid, "cruise": cruise, "hr_id": hr_id, "role": role,
           "morphology": pair.get("morphology"), "max_k": pair.get("max_k"),
           "uq_rms_m": pair.get("uq_rms_m"), "uq_char_m": pair.get("uq_char_m"),
           "lr_native_m": pair.get("lr_native_m")}
    lr_tif = _lr_to_tif(cruise, hr_id, tmp)
    if lr_tif is None:
        rec["status"] = "reject"; rec["reason"] = "no LR grid"; return rec
    with rasterio.open(str(lr_tif)) as ds:
        lrb = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
    hr_tif = _hr_mosaic(hr_id, lrb, tmp)
    if hr_tif is None:
        rec["status"] = "reject"; rec["reason"] = "HR unreadable / no LR-covered tile"; return rec
    # per-pair local UTM from footprint centroid
    with rasterio.open(str(hr_tif)) as ds:
        hb = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
    clon = (max(lrb[0], hb[0]) + min(lrb[2], hb[2])) / 2
    clat = (max(lrb[1], hb[1]) + min(lrb[3], hb[3])) / 2
    target_crs = f"EPSG:{_utm_epsg(clon, clat)}"
    out_dir = OUTROOT / pid
    try:
        hp = H.harmonize_pair(pair_id=pid, hr_raw=hr_tif, lr_raw=lr_tif,
                              target_crs=target_crs, resample_kernel=KERNEL,
                              nodata=FILL, out_dir=out_dir, vertical_sign="negative_down",
                              min_overlap_area_km2=MIN_OVERLAP_KM2)
    except H.HarmonizationError as e:
        rec["status"] = "reject"; rec["reason"] = str(e)[:120]; return rec
    rec["target_crs"] = target_crs
    rec["overlap_km2"] = round(hp.overlap_area_km2, 2) if hasattr(hp, "overlap_area_km2") else None
    hr_out = out_dir / "hr.tif"; lr_out = out_dir / "lr.tif"
    # co-register
    coreg = None
    try:
        hr_da = rioxarray.open_rasterio(str(hr_out)).squeeze()
        lr_da = rioxarray.open_rasterio(str(lr_out)).squeeze()
        coreg = cor.estimate_rigid_xyz(hr_da, lr_da)
        corrected = cor.apply_xyz(hr_da, coreg.dx_m, coreg.dy_m, coreg.dz_m)
        corrected.attrs.pop("_FillValue", None); corrected.encoding.pop("_FillValue", None)
        corrected.rio.write_nodata(FILL, encoded=True, inplace=True)
        corrected.rio.to_raster(hr_out, compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")
    except Exception as e:
        rec["coreg_note"] = f"coreg failed: {str(e)[:80]}"
    # QA
    qc_dir = out_dir / "qc"; qc_dir.mkdir(exist_ok=True)
    overlay = qc_dir / f"{pid}_overlay.png"
    try:
        qcr, status = qc.evaluate(
            sub_pair_id=pid, hr_path=hr_out, lr_path=lr_out, out_overlay_path=overlay,
            applied_dx_m=coreg.dx_m if coreg else 0.0,
            applied_dy_m=coreg.dy_m if coreg else 0.0,
            applied_dz_m=coreg.dz_m if coreg else 0.0,
            usbl_bound_m=USBL_BOUND_M,
            mad_m=coreg.post_residual_mad_m if coreg else None,
            mad_threshold_m=MAD_THRESH_M,
            min_peak_sharpness=None, peak_anisotropy_max=None)
        rec["status"] = status
        rec["psr"] = round(float(qcr.peak.psr), 2) if np.isfinite(qcr.peak.psr) else None
        rec["eig_ratio"] = round(float(qcr.peak.eig_ratio), 2) if np.isfinite(qcr.peak.eig_ratio) else None
        rec["peak_agrees"] = bool(qcr.peak.peak_agrees)
        rec["horiz_offset_m"] = round(float(qcr.horiz_offset_m), 2)
        rec["vert_offset_m"] = round(float(qcr.vert_offset_m), 2)
        rec["overlay"] = str(overlay)
    except Exception as e:
        rec["status"] = "needs_review"; rec["qc_note"] = f"qc failed: {str(e)[:80]}"
    if coreg:
        rec["coreg_dx"], rec["coreg_dy"], rec["coreg_dz"] = round(coreg.dx_m, 2), round(coreg.dy_m, 2), round(coreg.dz_m, 2)
        rec["coreg_mad_m"] = round(coreg.post_residual_mad_m, 2)
    rec["hr_out"] = str(hr_out); rec["lr_out"] = str(lr_out)
    return rec


def main(only=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import pandas as pd
    corpus = pd.read_csv(REPO / "reports/combined_corpus.csv")
    new = corpus[corpus.source == "new_c5c"].to_dict("records")
    if only:
        new = [p for p in new if p["pair_id"] in only]
    log.info("harmonizing %d new pairs", len(new))
    out = []
    for p in new:
        try:
            r = harmonize_one(p)
        except Exception as e:
            r = {"pair_id": p["pair_id"], "status": "error", "reason": str(e)[:150]}
        log.info("[%s] %s", r["pair_id"], r.get("status"))
        out.append(r)
        (REPO / "reports/discovery/stage_f_results.json").write_text(json.dumps(out, indent=2, default=str))
    from collections import Counter
    print("STATUS:", dict(Counter(r.get("status") for r in out)))


if __name__ == "__main__":
    import sys
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    main(only)
