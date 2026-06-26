"""Stage C pilot fix — recompute fill/native_res/ratio against the TRUE HR
footprint polygon (not the grid bbox), and regenerate QC overlays with the real
polygon outline + correct LR extent. Operates on the existing gridded .grd
files; no MB-System re-run.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask

REPO = Path(__file__).resolve().parents[2]
GRIDDED = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/raw_lr_gridded")
MEAS = REPO / "reports/discovery/stage_c_pilot_measurements.json"
A6 = gpd.read_file(REPO / "reports/discovery/stage_a6_hr_footprints_2026-06-22.gpkg").set_index("hr_id")
CAT = gpd.read_file(REPO / "reports/discovery/hr_catalog.gpkg").set_index("hr_id")


def hr_res_for(hr_id):
    if hr_id in CAT.index:
        try:
            v = float(CAT.loc[hr_id, "native_res_m"])
            return v if v == v else None
        except Exception:
            return None
    return None


def _read(p):
    for cand in (str(p), f"NETCDF:{p}"):
        try:
            with rasterio.open(cand) as ds:
                a = np.asarray(ds.read(1, masked=True).filled(np.nan), dtype="float64")
                return a, ds.transform, ds.bounds, ds.res
        except Exception:
            continue
    return None, None, None, None


def overlay(grd, poly, bounds, cruise, hr_id, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    a, *_ = _read(grd)
    if a is None:
        return ""
    ls = LightSource(azdeg=315, altdeg=45)
    hs = ls.hillshade(np.nan_to_num(a, nan=float(np.nanmedian(a))), vert_exag=1.0, dx=1, dy=1)
    ext = [bounds.left, bounds.right, bounds.bottom, bounds.top]   # TRUE LR extent
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(hs, cmap="gray", origin="upper", extent=ext, aspect="auto")
    ax.imshow(np.where(np.isfinite(a), a, np.nan), origin="upper", extent=ext,
              cmap="viridis", alpha=0.45, aspect="auto")
    # real footprint polygon outline (thin AUV strip)
    geoms = poly.geoms if poly.geom_type == "MultiPolygon" else [poly]
    for gpoly in geoms:
        xs, ys = gpoly.exterior.xy
        ax.plot(xs, ys, color="red", lw=1.8)
    ax.set_title(f"{cruise} -> {hr_id}\nLR gridded (viridis) + HR footprint polygon (red)")
    ax.set_xlabel("lon"); ax.set_ylabel("lat")
    fig.savefig(out, dpi=130, bbox_inches="tight"); plt.close(fig)
    return str(out)


def main():
    rows = json.loads(MEAS.read_text())
    for r in rows:
        hr = r["hr_id"]; cruise = r["cruise"]
        grd = GRIDDED / f"{cruise}__{hr.replace(':','_')}.grd"
        if hr not in A6.index or not grd.exists():
            continue
        a, tr, bounds, res = _read(grd)
        poly = A6.loc[hr].geometry
        inpoly = ~geometry_mask([poly], out_shape=a.shape, transform=tr, invert=False)
        data = np.isfinite(a)
        n_in = int(inpoly.sum())
        fill_fp = round(float((data & inpoly).sum() / max(1, n_in)), 4)
        cell_m = r.get("achieved_cell_m")
        native = round(cell_m / math.sqrt(fill_fp), 2) if fill_fp > 0 and cell_m else cell_m
        r["fill_fraction_bbox"] = r.get("fill_fraction")
        r["fill_fraction"] = fill_fp                 # now over the real polygon
        r["footprint_pct_of_grid"] = round(100 * n_in / a.size, 1)
        r["lr_native_res_m"] = native
        hr_res = hr_res_for(hr)
        r["hr_native_res_m"] = hr_res
        r["provisional_ratio"] = round(native / hr_res, 2) if hr_res and hr_res > 0 else None
        r["coverage_verdict"] = "near_nadir" if fill_fp >= 0.15 else "outer_beam_grazing"
        # depth median within footprint
        vals = a[data & inpoly]
        if vals.size:
            r["grid_depth_median"] = round(float(np.nanmedian(vals)), 1)
        r["overlay_path"] = overlay(grd, poly, bounds, cruise, hr,
                                    GRIDDED / f"overlay_{cruise}__{hr.replace(':','_')}.png")
        print(f"{cruise:14s} {hr:12s} fill_fp={fill_fp:.3f} (bbox {r['fill_fraction_bbox']}) "
              f"native={native} ratio={r['provisional_ratio']} cov={r['coverage_verdict']}")
    MEAS.write_text(json.dumps(rows, indent=2, default=str))
    print(f"\nupdated {MEAS}")


if __name__ == "__main__":
    main()
