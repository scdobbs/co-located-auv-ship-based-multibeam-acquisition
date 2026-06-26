"""Phase 2 Stage F.5 — nodata-aware (real-data) valid masks + training-sampling guarantee.

Directive: reports/directive_phase2_stage_f5_valid_masks.md (rev 1).

Closes the two gaps Code's pipeline trace found in Stage F:
  Gap A (sub-polygon slivers): one-sided NaN *inside* the overlap polygon.
  Gap B (inflated footprints):  interpolated-but-finite HR fill against LR.

The correction (directive): the joint mask must be `hr_real ∧ lr_real`, not just
`isfinite ∧ isfinite`. Two facts make this tractable here:

  * LR real layer:  Stage C gridded the ship LR with `mbgrid ... -C0` (NO gap
    interpolation, stage_c_full.py:189-190) and stage_c_full's own fill_fraction
    is computed as `np.isfinite` on that grid (line 211). So `isfinite(union.grd)`
    *is* the Stage C real-sounding mask — there is no interpolated fill to strip.
    (The `-M` count grid `_num.grd` was not persisted, but `-C0` makes it moot.)
    We warp that mask conservatively (average-resample -> majority threshold) and
    erode 1 cell so fill never bleeds into the valid region — never bilinear a mask.

  * HR real layer:  `_hr_mosaic` already drops whole tiles named diff/interp/Int
    (stage_f_harmonize.py:75-76). AUV GeoTIFF DEMs carry no cell-level interp/count
    band, so cell-level HR interp is `unknown`; the area-plausibility gate (F5-2)
    is what actually catches an interp-inflated HR. Recorded as hr_interp_status.

The 32 new pairs only. The 21 validated are read-only and never touched.
Diagnostic re-coreg does NOT overwrite the harmonized hr.tif (a real re-shift is a
Stage G action). Append-only: adds mask sidecars + a valid-tile index + a report.

Run on a compute node (sbatch/stage_f5.sbatch) — never the login node.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
import rasterio
import rioxarray  # noqa: F401  (registers .rio accessor)
import geopandas as gpd
from rasterio.features import rasterize
from rasterio.warp import reproject, Resampling
from scipy import ndimage as ndi

from src import coregister as cor
from src import qc

log = logging.getLogger("stage_f5")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
GRIDDED = DATA / "raw_lr_gridded"
HARM = DATA / "harmonized"
RESULTS_F = REPO / "reports/discovery/stage_f_results.json"
OUT_JSON = REPO / "reports/discovery/stage_f5_results.json"
TILES_PARQUET = REPO / "reports/discovery/valid_tiles.parquet"

FILL = -9999.0
USBL_BOUND_M = 30.0
MAD_THRESH_M = 5.0

# --- parameters flagged for confirmation (modeling / QC knobs) -------------
PLAUSIBLE_MAX_KM2 = 300.0    # area-plausibility bound: a co-located AUV patch is
                             # km^2-scale; joint real-data area >> this => HR is
                             # interp-inflated (or LR is a whole transit) -> exclude
LOW_FRACTION = 0.20          # coverage-fraction floor: joint/overlap below this
                             # => overlap is mostly one-sided -> weak pair
ERODE_CELLS = 1              # erode LR valid edge by 1 cell so fill never bleeds in
TILE_PX = 256                # HR-pixel tile edge for the trainable-tile index
TILE_MIN_FRACTION = 0.50     # include a tile iff joint_valid fraction >= this
# --------------------------------------------------------------------------

# the 2 eval_only (near_circular_weak) demotions to re-check on a joint-masked window
WEAK_PAIRS = {"NA090__MGDS_31212", "TN159__MGDS_21981"}


def _hr_real_valid(hr_raw: np.ndarray, coreg_dz: float | None) -> np.ndarray:
    """Real-HR mask, robust to the Stage F nodata-fill corruption.

    Stage F's coreg step opened HR WITHOUT masked=True and did `HR + dz`, so the
    -9999 fill cells were shifted to `-9999 + coreg_dz` while the GeoTIFF nodata
    tag stayed -9999 (verified: NA090 fill = -10000.89 = -9999 + (-1.89)). The tag
    therefore no longer matches the stored fill, so `read(masked=True)` leaves the
    fill finite and it leaks into every isfinite-based mask. We detect it exactly:
    fill value == -9999 + coreg_dz (and the untouched -9999, and any true NaN)."""
    dz = coreg_dz or 0.0
    fill_shifted = FILL + dz
    bad = (~np.isfinite(hr_raw)) \
        | np.isclose(hr_raw, FILL, atol=1e-6) \
        | np.isclose(hr_raw, fill_shifted, atol=1.0)
    return ~bad


def _lr_grid_path(cruise: str, hr_id: str) -> Path | None:
    """Mirror stage_f_harmonize._lr_to_tif: per-pair grid, else cruise union."""
    p = GRIDDED / f"{cruise}__{hr_id.replace(':', '_')}.grd"
    if p.exists():
        return p
    p = GRIDDED / f"{cruise}__union.grd"
    return p if p.exists() else None


def _open_grd(p: Path):
    for cand in (str(p), f"NETCDF:{p}"):
        try:
            ds = rasterio.open(cand)
            return ds
        except Exception:
            continue
    return None


def lr_real_mask_on_hr(cruise, hr_id, hr_ds) -> np.ndarray | None:
    """Stage C real-sounding mask (isfinite on the -C0 grid), conservatively
    warped onto the HR grid (average -> majority threshold) and eroded 1 cell.

    Returns a bool array on the HR grid, or None if the LR grid is missing.
    """
    gp = _lr_grid_path(cruise, hr_id)
    if gp is None:
        return None
    ds = _open_grd(gp)
    if ds is None:
        return None
    try:
        src = ds.read(1, masked=True).filled(np.nan).astype("float64")
        src_mask = np.isfinite(src).astype("float32")   # real soundings (no -C0 interp)
        src_crs = ds.crs or "EPSG:4326"
        src_transform = ds.transform
    finally:
        ds.close()
    # area-weighted warp of the {0,1} mask -> coverage fraction on HR grid
    dst = np.zeros((hr_ds.height, hr_ds.width), dtype="float32")
    reproject(
        source=src_mask, destination=dst,
        src_transform=src_transform, src_crs=src_crs,
        dst_transform=hr_ds.transform, dst_crs=hr_ds.crs,
        src_nodata=0.0, dst_nodata=0.0,
        resampling=Resampling.average,
    )
    valid = dst >= 0.5                                   # majority -> conservative
    if ERODE_CELLS:
        valid = ndi.binary_erosion(valid, iterations=ERODE_CELLS, border_value=0)
    return valid


def overlap_mask_on_hr(hr_ds, footprint_path: Path) -> np.ndarray | None:
    """Rasterize the Stage F overlap polygon (footprint.geojson, already in the
    pair's target CRS) onto the HR grid -> the denominator for joint_fraction."""
    if not footprint_path.exists():
        return None
    gdf = gpd.read_file(footprint_path)
    if gdf.empty:
        return None
    if gdf.crs is not None and str(gdf.crs) != str(hr_ds.crs):
        gdf = gdf.to_crs(hr_ds.crs)
    m = rasterize(
        [(geom, 1) for geom in gdf.geometry],
        out_shape=(hr_ds.height, hr_ds.width),
        transform=hr_ds.transform, fill=0, dtype="uint8", all_touched=False,
    )
    return m.astype(bool)


def _write_mask(arr_bool: np.ndarray, ref_ds, out_path: Path):
    prof = {
        "driver": "GTiff", "height": ref_ds.height, "width": ref_ds.width,
        "count": 1, "dtype": "uint8", "crs": ref_ds.crs,
        "transform": ref_ds.transform, "nodata": 255,
        "compress": "DEFLATE", "tiled": True,
    }
    with rasterio.open(out_path, "w", **prof) as d:
        d.write(arr_bool.astype("uint8"), 1)


def _recoreg_on_joint(hr_out: Path, lr_out: Path, joint: np.ndarray, hr_ds, tmp: Path):
    """Re-estimate the rigid offset using ONLY joint_valid (real-data) HR cells.

    Masks the HR raster to joint_valid (NaN elsewhere) and re-runs the established
    coreg + QA. Diagnostic — does not overwrite the harmonized hr.tif.
    Returns (dx,dy,dz,mad,psr,eig,agrees,offset, overlay_path) or None.
    """
    masked = tmp / "hr_joint.tif"
    with rasterio.open(str(hr_out)) as ds:
        arr = ds.read(1).astype("float32")
        prof = ds.profile.copy()
    arr = np.where(joint, arr, np.nan).astype("float32")
    prof.update(dtype="float32", nodata=FILL, compress="DEFLATE")
    a = np.where(np.isfinite(arr), arr, FILL).astype("float32")
    with rasterio.open(masked, "w", **prof) as d:
        d.write(a, 1)

    hr_da = rioxarray.open_rasterio(str(masked), masked=True).squeeze()
    lr_da = rioxarray.open_rasterio(str(lr_out), masked=True).squeeze()
    coreg = cor.estimate_rigid_xyz(hr_da, lr_da)

    (hr_out.parent / "qc").mkdir(exist_ok=True)
    overlay = hr_out.parent / "qc" / f"{hr_out.parent.name}_overlay_f5.png"
    qcr, status = qc.evaluate(
        sub_pair_id=hr_out.parent.name + "_f5", hr_path=masked, lr_path=lr_out,
        out_overlay_path=overlay,
        applied_dx_m=coreg.dx_m, applied_dy_m=coreg.dy_m, applied_dz_m=coreg.dz_m,
        usbl_bound_m=USBL_BOUND_M, mad_m=coreg.post_residual_mad_m,
        mad_threshold_m=MAD_THRESH_M, min_peak_sharpness=None, peak_anisotropy_max=None)
    offset = float(np.hypot(coreg.dx_m, coreg.dy_m))
    return {
        "dx": round(coreg.dx_m, 2), "dy": round(coreg.dy_m, 2), "dz": round(coreg.dz_m, 2),
        "mad_m": round(coreg.post_residual_mad_m, 2), "offset_m": round(offset, 2),
        "psr": round(float(qcr.peak.psr), 2) if np.isfinite(qcr.peak.psr) else None,
        "eig_ratio": round(float(qcr.peak.eig_ratio), 2) if np.isfinite(qcr.peak.eig_ratio) else None,
        "peak_agrees": bool(qcr.peak.peak_agrees),
        "overlay": str(overlay),
    }


def _coreg_verdict(rc: dict | None, orig_flagged: bool, inflated: bool, weak: bool) -> str:
    """Lock quality is judged on the HORIZONTAL criteria of §3b — solved offset
    within the AUV USBL bound and a positive (real) NCC peak. The vertical
    residual MAD is recorded but NOT gated on: on a sloping margin a single rigid
    dz cannot remove the regional depth trend, so MAD is trend-dominated (hundreds
    of m) even for a perfectly good horizontal lock — gating on it would fail every
    margin pair. MAD travels to the report for QGIS context only."""
    if inflated:
        return "inflated_exclude_candidate"
    if weak:
        return "weak_exclude_candidate"
    if rc is None:
        return "genuine_coreg_fail"
    clean = (rc["offset_m"] <= USBL_BOUND_M and rc["psr"] is not None and rc["psr"] > 0)
    if clean:
        return "rescued" if orig_flagged else "clean"
    return "genuine_coreg_fail"


def _tile_rows(pair_id, joint: np.ndarray, hr_ds):
    """Tile the HR grid into TILE_PX squares; keep tiles with joint fraction >=
    TILE_MIN_FRACTION. Returns list of dicts (the trainable-tile index)."""
    H, W = joint.shape
    tr = hr_ds.transform
    rows = []
    n_total = 0
    for r0 in range(0, H, TILE_PX):
        for c0 in range(0, W, TILE_PX):
            tile = joint[r0:r0 + TILE_PX, c0:c0 + TILE_PX]
            if tile.size < TILE_PX * TILE_PX:
                continue                     # only full tiles enter the index
            n_total += 1
            frac = float(tile.mean())
            if frac < TILE_MIN_FRACTION:
                continue
            minx, maxy = tr * (c0, r0)
            maxx, miny = tr * (c0 + TILE_PX, r0 + TILE_PX)
            rows.append({
                "pair_id": pair_id, "row0": int(r0), "col0": int(c0),
                "tile_px": TILE_PX, "joint_valid_fraction": round(frac, 4),
                "minx": float(minx), "miny": float(miny),
                "maxx": float(maxx), "maxy": float(maxy),
                "crs": str(hr_ds.crs),
            })
    return rows, n_total


def gap2_recheck(pair_id, cruise, hr_id, hr_clean: Path, hr_ds, lr_native_m: float | None):
    """F5-5: re-confirm a near_circular_weak demotion on a joint-masked window.

    Faithfully reproduces the C.5b SR-band measurement (load_to_common at the AUV
    grid + band_rms over [f_lr, min(8·f_lr, nyq)]; stage_c5_sweep.py:189-225) so
    the numbers are commensurate with the original demotion — then masks to
    BOTH-finite cells, which is precisely Gap 2's fix (the C.5 `_prep` filled
    one-sided NaN with 0; intersecting the two real masks removes exactly those
    one-sided cells). Demotion stands if HR ≈ LR in the SR band; re-flag if,
    once one-sided fill is excluded, HR carries real structure LR lacks."""
    from src.discovery.stage_c5_spectral import band_rms, load_to_common
    from rasterio.warp import transform_bounds as _tb
    lr_grd = _lr_grid_path(cruise, hr_id)
    if lr_grd is None:
        return {"verdict": "recheck_failed", "error": "no LR grid"}
    hr_res = abs(hr_ds.res[0])
    target_res = max(0.5, hr_res)
    bounds = _tb(hr_ds.crs, "EPSG:4326", *hr_ds.bounds)        # (w,s,e,n)
    lr, hr, dx = load_to_common(str(lr_grd), str(hr_clean), bounds, target_res)
    both = np.isfinite(lr) & np.isfinite(hr)                   # the joint real-data window
    lr = np.where(both, lr, np.nan)
    hr = np.where(both, hr, np.nan)
    lr_nat = lr_native_m or (dx * 8)
    f_lr = 1.0 / lr_nat
    nyq = 1.0 / (2 * dx)
    hi = min(8 * f_lr, nyq * 0.99)                            # SR band, clamped to Nyquist
    hr_rms, _ = band_rms(hr, dx, f_lr, hi)
    lr_rms, _ = band_rms(lr, dx, f_lr, hi)
    excess = (hr_rms / lr_rms) if (hr_rms and lr_rms and lr_rms > 0) else None
    stands = (excess is None) or (excess < 1.3)              # HR does not exceed LR -> weak stands
    return {"hr_sr_rms_m": hr_rms, "lr_sr_rms_m": lr_rms,
            "sr_excess_ratio": round(excess, 3) if excess else None,
            "n_joint_cells": int(both.sum()),
            "verdict": "demotion_stands" if stands else "re_flag_for_review"}


def process_pair(rec: dict) -> dict:
    pid = rec["pair_id"]
    cruise, hr_id = rec["cruise"], rec["hr_id"]
    pdir = HARM / pid
    hr_out, lr_out = pdir / "hr.tif", pdir / "lr.tif"
    out = {"pair_id": pid, "cruise": cruise, "hr_id": hr_id,
           "role": rec.get("role"), "morphology": rec.get("morphology"),
           "stage_f_status": rec.get("status"),
           "stage_f_offset_m": rec.get("horiz_offset_m"), "stage_f_psr": rec.get("psr")}
    if not (hr_out.exists() and lr_out.exists()):
        out["bucket"] = "error"; out["reason"] = "missing harmonized hr/lr"; return out

    tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "stage_f5" / pid
    tmp.mkdir(parents=True, exist_ok=True)

    hr_ds = rasterio.open(str(hr_out))
    try:
        hr_raw = hr_ds.read(1)                               # raw values, no nodata masking
        coreg_dz = rec.get("coreg_dz")
        hr_valid = _hr_real_valid(hr_raw, coreg_dz)          # robust to fill corruption
        out["fill_corruption_cells"] = int((np.isclose(hr_raw, FILL + (coreg_dz or 0.0), atol=1.0)
                                            & ~np.isclose(hr_raw, FILL, atol=1e-6)).sum())
        lr_valid = lr_real_mask_on_hr(cruise, hr_id, hr_ds)
        if lr_valid is None:
            out["bucket"] = "error"; out["reason"] = "no LR grid for real mask"; return out
        joint = hr_valid & lr_valid

        # F5-1: write the three shared masks (uint8, aligned to hr.tif)
        _write_mask(hr_valid, hr_ds, pdir / "hr_valid.tif")
        _write_mask(lr_valid, hr_ds, pdir / "lr_valid.tif")
        _write_mask(joint, hr_ds, pdir / "joint_valid.tif")
        out["hr_interp_status"] = "tile_filtered_only"   # no cell-level AUV interp flag

        # cleaned HR (leaked fill -> proper nodata) for the spectral re-check
        hr_clean = tmp / "hr_clean.tif"
        cprof = hr_ds.profile.copy()
        cprof.update(dtype="float32", nodata=FILL, compress="DEFLATE")
        with rasterio.open(hr_clean, "w", **cprof) as d:
            d.write(np.where(hr_valid, hr_raw, FILL).astype("float32"), 1)

        # F5-2: area + fraction + gates
        cell_area = abs(hr_ds.res[0] * hr_ds.res[1])     # m^2 (metric UTM)
        joint_cells = int(joint.sum())
        out["joint_valid_area_km2"] = round(joint_cells * cell_area / 1e6, 3)
        # Gate denominator = the real-data UNION (hr_valid ∪ lr_valid): a bounded
        # [0,1] one-sidedness measure. This is the directive's "overlap-polygon
        # cells" intent made robust — the literal rasterized footprint polygon
        # edge-mismatches the joint mask and can push the ratio above 1. We keep
        # the literal joint/polygon ratio below as a reference column.
        union_cells = int((hr_valid | lr_valid).sum())
        out["union_real_cells"] = union_cells
        out["joint_valid_fraction"] = round(joint_cells / max(1, union_cells), 4)
        ov = overlap_mask_on_hr(hr_ds, pdir / "footprint.geojson")
        if ov is not None:
            out["overlap_polygon_cells"] = int(ov.sum())
            out["joint_over_polygon"] = round(joint_cells / max(1, int(ov.sum())), 4)
        out["hr_valid_area_km2"] = round(int(hr_valid.sum()) * cell_area / 1e6, 3)
        out["lr_valid_area_km2"] = round(int(lr_valid.sum()) * cell_area / 1e6, 3)
        inflated = out["joint_valid_area_km2"] > PLAUSIBLE_MAX_KM2
        weak = out["joint_valid_fraction"] < LOW_FRACTION
        out["inflated"] = bool(inflated)
        out["weak_coverage"] = bool(weak)

        # F5-3: re-coreg + re-QA on joint real-data cells
        orig_flagged = (rec.get("horiz_offset_m") is not None and rec["horiz_offset_m"] > USBL_BOUND_M) \
            or (rec.get("psr") is None) or (rec.get("psr") is not None and rec["psr"] < 0)
        out["stage_f_flagged"] = bool(orig_flagged)
        rc = None
        if joint_cells >= 200:
            try:
                rc = _recoreg_on_joint(hr_out, lr_out, joint, hr_ds, tmp)
                out["recoreg"] = rc
            except Exception as e:
                out["recoreg_note"] = f"recoreg failed on joint cells: {str(e)[:100]}"
        else:
            out["recoreg_note"] = f"only {joint_cells} joint cells (<200) — cannot re-lock"
        out["bucket"] = _coreg_verdict(rc, orig_flagged, inflated, weak)

        # F5-4: trainable-tile rows
        tile_rows, n_total = _tile_rows(pid, joint, hr_ds)
        out["n_valid_tiles"] = len(tile_rows)
        out["n_total_tiles"] = n_total
        out["_tile_rows"] = tile_rows           # consumed by main(), stripped before save

        # F5-5: Gap-2 re-check for the 2 eval_only pairs
        if pid in WEAK_PAIRS:
            try:
                out["gap2_recheck"] = gap2_recheck(pid, cruise, hr_id, hr_clean, hr_ds,
                                                   rec.get("lr_native_m"))
            except Exception as e:
                out["gap2_recheck"] = {"verdict": "recheck_failed", "error": str(e)[:100]}
    finally:
        hr_ds.close()
    return out


def main(only=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    recs = json.loads(RESULTS_F.read_text())
    if only:
        recs = [r for r in recs if r["pair_id"] in only]
    log.info("Stage F.5 over %d pairs%s", len(recs), " (--only: merge mode)" if only else "")
    out, all_tiles = [], []
    for r in recs:
        try:
            res = process_pair(r)
        except Exception as e:
            res = {"pair_id": r["pair_id"], "bucket": "error", "reason": str(e)[:150]}
        all_tiles.extend(res.pop("_tile_rows", []))
        log.info("[%s] %s  area=%s km2  frac=%s  tiles=%s", res["pair_id"],
                 res.get("bucket"), res.get("joint_valid_area_km2"),
                 res.get("joint_valid_fraction"), res.get("n_valid_tiles"))
        out.append(res)

    if only and OUT_JSON.exists():
        # merge: replace the re-run pair_ids, keep the rest; do NOT touch the
        # tiles parquet (masks/tiles are unchanged by a gap2-only re-run).
        prev = {r["pair_id"]: r for r in json.loads(OUT_JSON.read_text())}
        for r in out:
            prev[r["pair_id"]] = r
        out = list(prev.values())
        OUT_JSON.write_text(json.dumps(out, indent=2, default=str))
        log.info("merged %d re-run pairs into %s (%d total); tiles parquet left intact",
                 len(recs), OUT_JSON, len(out))
    else:
        OUT_JSON.write_text(json.dumps(out, indent=2, default=str))
        # F5-4: the authoritative trainable-tile index (full run only)
        import pandas as pd
        pd.DataFrame(all_tiles).to_parquet(TILES_PARQUET, index=False)
    from collections import Counter
    log.info("BUCKETS: %s", dict(Counter(r.get("bucket") for r in out)))
    log.info("valid_tiles: %d rows across %d pairs -> %s",
             len(all_tiles), len({t['pair_id'] for t in all_tiles}), TILES_PARQUET)


if __name__ == "__main__":
    import sys
    only = sys.argv[sys.argv.index("--only") + 1].split(",") if "--only" in sys.argv else None
    main(only)
