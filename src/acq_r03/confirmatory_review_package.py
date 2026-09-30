"""ACQ-R03 §5.2 — sealed confirmatory co-registration review package for KN182L03__MGDS_30193 (nu01a) and
SUM1004__MGDS_33090 (nu03).  Written to OAK harmonized_confirmatory/<unit>/<pair>/review/ (files 0444).

Contents (and nothing else): HR and LR hillshades before and after the rigid co-registration shift; matched HR and
LR contour lines at a common interval; the shift vector; the co-registration search surface (the MAD score of
`src/coregister.estimate_rigid_xyz` evaluated on a dense (dx, dy) grid, written in shift space); the HR navigation
basis if recorded.  No HR−LR difference map, residual statistic, amplitude, spectral or roughness quantity is
computed or written; nothing is printed except paths.  The sealed hr.tif holds the post-shift HR (apply_xyz with the
recorded dx, dy, dz); "before" is its exact inverse.
Usage (job): python -m src.acq_r03.confirmatory_review_package --pair KN182L03__MGDS_30193
"""
from __future__ import annotations

import argparse
import json
import sys

import geopandas as gpd
import numpy as np
import rasterio
import rioxarray  # noqa: F401
from rasterio.transform import from_origin
from shapely.geometry import LineString
from skimage import measure

from src import coregister as cor
from src.acq_r01 import common as C
from src.acq_r03 import common as R

NAV_BASIS = {  # what the files / catalog record about the HR navigation (checked in ACQ-R03; MGDS descriptions carry no USBL/DVL/LBL statement)
    "KN182L03__MGDS_30193": "not recorded by MGDS (description: Reson 7125 on Sentry, AT40-02; no USBL/DVL/LBL statement); file names carry 'navadjust' (post-processed, navigation-adjusted grids)",
    "SUM1004__MGDS_33090": "not recorded by MGDS (description: EM2040 on Sentry, NA179; no USBL/DVL/LBL statement); file names carry 'rnv' (renavigated grids)",
}
SEARCH_M = 36.0; STEP_M = 1.0


def hillshade_arr(z, dx, dy, az=315.0, alt=45.0):
    gy, gx = np.gradient(z, dy, dx)
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
    azr, altr = np.radians(az), np.radians(alt)
    hs = np.sin(altr) * np.cos(slope) + np.cos(altr) * np.sin(slope) * np.cos(azr - aspect)
    return np.where(np.isfinite(z), np.clip(hs, 0, 1), np.nan).astype("float32")


def write(path, arr, transform, crs):
    prof = {"driver": "GTiff", "height": arr.shape[0], "width": arr.shape[1], "count": 1, "dtype": "float32", "crs": crs, "transform": transform, "nodata": np.nan, "compress": "DEFLATE", "tiled": True, "BIGTIFF": "IF_SAFER"}
    with rasterio.open(path, "w", **prof) as d:
        d.write(arr.astype("float32"), 1)


def contours(z, transform, levels, source):
    feats = []
    for lv in levels:
        for c in measure.find_contours(np.where(np.isfinite(z), z, np.nan), lv):
            if len(c) < 3:
                continue
            xy = [transform * (col + 0.5, row + 0.5) for row, col in c]
            feats.append({"level_m": float(lv), "source": source, "geometry": LineString(xy)})
    return feats


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--pair", required=True)
    a = ap.parse_args(argv)
    C.assert_no_lockbox([a.pair])
    rec = json.loads((R.R02 / "harmonize" / f"{a.pair}.json").read_text())
    assert str(rec["designation"]).startswith("confirmatory"), "only confirmatory pairs"
    from pathlib import Path
    pdir = Path(rec["out_dir"])
    out = pdir / "review"; out.mkdir(exist_ok=True)
    for p in out.iterdir():
        p.chmod(0o644)
    cg = rec["coreg"]; dx, dy, dz = float(cg["dx_m"]), float(cg["dy_m"]), float(cg["dz_m"])
    with rasterio.open(pdir / "hr.tif") as ds:
        hr_after = ds.read(1, masked=True).filled(np.nan).astype("float64"); tr_a = ds.transform; crs = ds.crs; rx, ry = ds.res
    with rasterio.open(pdir / "lr.tif") as ds:
        lr = ds.read(1, masked=True).filled(np.nan).astype("float64"); tr_l = ds.transform; lx, ly = ds.res
    lr = np.where(np.isclose(lr, -9999.0, atol=1e-3), np.nan, lr)
    # before = exact inverse of coregister.apply_xyz (coordinates - (dx, dy), values - dz)
    hr_before = hr_after - dz
    tr_b = rasterio.Affine(tr_a.a, tr_a.b, tr_a.c - dx, tr_a.d, tr_a.e, tr_a.f - dy)
    write(out / "hr_hillshade_before_shift.tif", hillshade_arr(hr_before, rx, ry), tr_b, crs)
    write(out / "hr_hillshade_after_shift.tif", hillshade_arr(hr_after, rx, ry), tr_a, crs)
    lr_hs = hillshade_arr(lr, lx, ly)
    write(out / "lr_hillshade_before_shift.tif", lr_hs, tr_l, crs)   # the LR is the fixed frame: identical before and after
    write(out / "lr_hillshade_after_shift.tif", lr_hs, tr_l, crs)
    # matched contours at a common interval (chosen from the LR depth range; a round number)
    v = lr[np.isfinite(lr)]; rng = float(np.percentile(v, 95) - np.percentile(v, 5)) if v.size else 100.0
    interval = min((i for i in (2, 5, 10, 20, 50, 100) if rng / i <= 25), default=100)
    lo = np.floor(np.nanmin(v) / interval) * interval; hi = np.ceil(np.nanmax(v) / interval) * interval
    levels = np.arange(lo, hi + interval, interval)
    step = max(1, int(round(min(lx, ly) / (4 * rx))))          # contour the HR at ~LR/4 spacing to keep the vector size sane
    hb = hr_before[::step, ::step]; ha = hr_after[::step, ::step]
    tb = rasterio.Affine(tr_b.a * step, 0, tr_b.c, 0, tr_b.e * step, tr_b.f); ta = rasterio.Affine(tr_a.a * step, 0, tr_a.c, 0, tr_a.e * step, tr_a.f)
    feats = contours(lr, tr_l, levels, "lr") + contours(hb, tb, levels, "hr_before_shift") + contours(ha, ta, levels, "hr_after_shift")
    gpd.GeoDataFrame(feats, geometry="geometry", crs=crs).to_file(out / "contours.gpkg", layer=f"contours_{interval}m", driver="GPKG")
    # shift vector (HR centroid before -> after)
    hv = np.isfinite(hr_after); rows, cols = np.where(hv)
    cx, cy = tr_a * (float(cols.mean()) + 0.5, float(rows.mean()) + 0.5)
    vec = {"pair_id": a.pair, "unit": rec["unit"], "dx_m": dx, "dy_m": dy, "dz_m": dz, "horizontal_m": float(np.hypot(dx, dy)), "target_crs": str(crs),
           "definition": "src/coregister.estimate_rigid_xyz: HR moved by (dx, dy) and values by dz onto the LR (apply_xyz); search ±30 m coarse (4·HR gsd) + fine (HR gsd) around the coarse best"}
    gpd.GeoDataFrame([{**vec, "geometry": LineString([(cx - dx, cy - dy), (cx, cy)])}], geometry="geometry", crs=crs).to_file(out / "shift_vector.gpkg", layer="shift_vector", driver="GPKG")
    R.write_json(out / "shift_vector.json", vec)
    # co-registration search surface: the estimator's score (MAD of LR - HR samples, centred) on a dense (dx, dy) grid
    hr_da = rioxarray.open_rasterio(str(pdir / "hr.tif"), masked=True).squeeze()
    hr_da = hr_da.assign_coords(x=hr_da.x - dx, y=hr_da.y - dy) - dz              # the pre-shift HR, as the estimator saw it
    hr_da.rio.write_crs(crs, inplace=True)
    lr_da = rioxarray.open_rasterio(str(pdir / "lr.tif"), masked=True).squeeze()
    xs, ys, hv_ = cor._prepare_hr_sample(hr_da, n_max=80_000)
    grid = np.arange(-SEARCH_M, SEARCH_M + STEP_M, STEP_M)
    surf = np.full((grid.size, grid.size), np.nan, "float32")
    for i, sy in enumerate(grid):                     # rows: dy from +SEARCH (north, top) to -SEARCH
        for j, sx in enumerate(grid):
            r_ = cor._residuals(xs, ys, hv_, lr_da, float(sx), float(grid[::-1][i]))
            if r_.size:
                surf[i, j] = cor._mad(r_ - np.median(r_))
    # written in shift space: 1 m pixels, origin so that the (0, 0) shift sits at the HR centroid (displays as a small square in QGIS)
    tr_s = from_origin(cx - SEARCH_M - STEP_M / 2, cy + SEARCH_M + STEP_M / 2, STEP_M, STEP_M)
    write(out / "coreg_search_surface.tif", surf, tr_s, crs)
    with (out / "coreg_search_surface.csv").open("w") as f:
        f.write("dx_m,dy_m,score_mad_m\n")
        for i, sy in enumerate(grid[::-1]):
            for j, sx in enumerate(grid):
                f.write(f"{sx},{sy},{surf[i, j]}\n")
    readme = (f"# Sealed confirmatory review package — {a.pair} ({rec['unit']})\n\n"
              f"Contents per ACQ-R03 §5.2 only. CRS {crs}. Contour interval {interval} m (levels {lo:.0f}..{hi:.0f}); HR contoured at every {step} px.\n"
              f"- hr_hillshade_before_shift.tif / hr_hillshade_after_shift.tif: HR hillshade before / after the rigid shift (before = exact inverse of the recorded shift).\n"
              f"- lr_hillshade_before_shift.tif / lr_hillshade_after_shift.tif: LR hillshade (the LR is the fixed frame; the two files are identical by construction).\n"
              f"- contours.gpkg (layer contours_{interval}m): lr, hr_before_shift, hr_after_shift.\n"
              f"- shift_vector.gpkg / shift_vector.json: the recorded rigid shift (HR centroid before -> after).\n"
              f"- coreg_search_surface.tif / .csv: the estimator's score on a ±{SEARCH_M:.0f} m grid at {STEP_M:.0f} m, in shift space (raster origin at the HR centroid; pixel = 1 m of shift; north = +dy).\n"
              f"- HR navigation basis: {NAV_BASIS.get(a.pair, 'not recorded')}.\n"
              f"Criterion: reports_post_grl_review/ACQ-R03/confirmatory_review_criterion.md (committed before this package was rendered).\n")
    (out / "README.md").write_text(readme)
    for p in out.iterdir():
        p.chmod(0o444)
    print(json.dumps({"pair_id": a.pair, "review_dir": str(out), "files": sorted(p.name for p in out.iterdir())}, indent=1)); return 0


if __name__ == "__main__":
    sys.exit(main())
