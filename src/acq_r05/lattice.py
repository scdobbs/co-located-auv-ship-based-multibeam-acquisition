"""ACQ-R05 §1 / §2.1.2 — lattices.

Three lattices per pair:
  * lr.tif's UTM lattice (read from the file);
  * the CONTEXT lattice (§1): lr.tif's CRS and pixel size, origin on lr.tif's lattice, covering the footprint buffered
    by 5 km; the offset of lr.tif inside it is an integer number of pixels;
  * for NCEI-swath pairs, the geographic STAGE-C lattice the pair's lr.tif was warped from (§2.1.2 "snap the region
    so that its node lattice coincides with the lattice stage C used"), recovered as follows and VERIFIED by
    reproducing lr.tif's UTM lattice with GDAL's default warp output (rasterio.warp.calculate_default_transform,
    the grid harmonize._reproject uses when no resolution is given):
      - ACQ-R02 pairs: read from the persisted union grid on OAK raw_lr_gridded/<cruise>__union.grd;
      - June stage_c_full pairs (grids purged): re-derived from the code rule (stage_c_full.py:181-190): region =
        union of the cruise's live HR footprints (stage_b_fetch_list live_HR; A6 gpkg, catalog fallback) ± 1 km,
        -E cell*dlon/cell*dlat with cell = achieved_cell_m of stage_c_full_measurements.json (AT37-13: the unrounded
        2*depth*tan(bw/2); the 2-decimal cell changes the node count by one);
      - June pilot per-HR pairs (stage_c_pilot.grid_pair): region = A6 footprint bbox of the gridded HR ± 1 km,
        cell = est_cell_m of stage_c_pilot_measurements.json;
    with mbgrid's dimension rule, verified on all 18 ACQ-R02 grids: bounds kept exactly, n = round(span/spacing + 1),
    spacing = span/(n - 1).
Usage: python -m src.acq_r05.lattice [--pairs A,B]   -> reports_post_grl_review/ACQ-R05/lattice_recovery.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import calculate_default_transform
from shapely.geometry import box

from src.acq_r05 import common as R

# June provenance (which grid each June lr.tif was warped from; stage_f_harmonize._lr_to_tif prefers the per-HR grid)
JUNE_UNION = {"RR1506__MGDS_29779": "RR1506", "AT37-13__MGDS_31199": "AT37-13", "TN399__MGDS_30373": "TN399",
              "EW9801__MGDS_31425": "EW9801", "NA090__MGDS_31212": "NA090", "NA076__MGDS_32317": "NA076",
              "NA080__MGDS_31290": "NA080", "EW0207__MGDS_32556": "EW0207"}
JUNE_PILOT = {"AR26__MGDS_31838": ("AR26", "MGDS:31838"), "FK181031__MGDS_24618": ("FK181031", "MGDS:24620"),
              "TN299__MGDS_31253": ("TN299", "MGDS:31256"), "TN299__MGDS_27339": ("TN299", "MGDS:27339")}
ACQ_R02 = {"AT42-06__MGDS_5174": "AT42-06", "TN399__MGDS_33068": "TN399", "KM0923__MGDS_31429": "KM0923",
           "NA080__MGDS_31289": "NA080", "FK151121__MGDS_22383": "FK151121", "EX1402L2__MGDS_31073": "EX1402L2"}
assert set(JUNE_UNION) | set(JUNE_PILOT) | set(ACQ_R02) == set(R.NCEI_PAIRS)
GRD_CRS = "OGC:CRS84"   # how GDAL reads the mbgrid CF netCDF grids (verified on every ACQ-R02 union grid)


def lr_header(pair_id: str) -> dict:
    p = R.pair_dir(pair_id) / "lr.tif"
    with rasterio.open(p) as ds:
        return {"path": str(p), "crs": ds.crs.to_string(), "transform": ds.transform, "width": ds.width, "height": ds.height,
                "nodata": ds.nodata, "dtype": ds.dtypes[0]}


def read_lr(pair_id: str):
    """lr.tif as float64 with NaN nodata (both the -9999 tag and NaN)."""
    p = R.pair_dir(pair_id) / "lr.tif"
    with rasterio.open(p) as ds:
        a = ds.read(1).astype("float64"); nd = ds.nodata
    if nd is not None and np.isfinite(nd):
        a[a == nd] = np.nan
    a[np.abs(a) >= 9999.0] = np.nan
    return a


# --------------------------------------------------------------------------- #
# stage-C geographic lattice
# --------------------------------------------------------------------------- #
def _dlon_dlat(mlat):
    return 1 / (111320 * max(0.2, math.cos(math.radians(mlat)))), 1 / 111320


def _mbgrid_lattice(w, s, e, n, dx_req, dy_req):
    """mbgrid dimension rule (verified 18/18 on ACQ-R02 grids): bounds exact, n = round(span/spacing + 1)."""
    nx = int(round((e - w) / dx_req + 1)); ny = int(round((n - s) / dy_req + 1))
    return {"w": w, "s": s, "e": e, "n": n, "nx": nx, "ny": ny, "dx": (e - w) / (nx - 1), "dy": (n - s) / (ny - 1),
            "dx_requested": dx_req, "dy_requested": dy_req}


def _stage_c_region(w, s, e, n, cell):
    mlat = (s + n) / 2; dlon, dlat = _dlon_dlat(mlat)
    W, E, S, N = w - R.MARGIN_M * dlon, e + R.MARGIN_M * dlon, s - R.MARGIN_M * dlat, n + R.MARGIN_M * dlat
    return _mbgrid_lattice(W, S, E, N, cell * dlon, cell * dlat)


_A6 = _CAT = _FL = None


def _june_tables():
    global _A6, _CAT, _FL
    if _A6 is None:
        _A6 = gpd.read_file(R.REPO / "reports/discovery/stage_a6_hr_footprints_2026-06-22.gpkg").set_index("hr_id")
        _CAT = gpd.read_file(R.REPO / "reports/discovery/hr_catalog.gpkg").set_index("hr_id")
        _FL = pd.read_csv(R.REPO / "reports/stage_b_fetch_list_2026-06-22.csv").set_index("cruise")
    return _A6, _CAT, _FL


def _footprint_for(h):
    """stage_c_full.footprint_for, verbatim rule."""
    A6, CAT, _ = _june_tables()
    g = A6.loc[h].geometry if h in A6.index else None
    if g is not None:
        b = g.bounds
        if -180 <= b[0] and b[2] <= 180 and -90 <= b[1] and b[3] <= 90:
            return g
    if h in CAT.index and CAT.loc[h].geometry is not None:
        return CAT.loc[h].geometry
    return g


def source_lattice(pair_id: str) -> dict:
    """The geographic lattice of the grid lr.tif was warped from (NCEI pairs), with its recovery provenance."""
    R.refuse_sealed(pair_id)
    if pair_id in ACQ_R02:
        c = ACQ_R02[pair_id]; g = R.CTX_GRD_OAK / f"{c}__union.grd"
        rec = json.loads((R.R02 / "grid" / f"{c}.json").read_text())
        with rasterio.open(g) as ds:
            t = ds.transform; nx, ny = ds.width, ds.height; dx, dy = t.a, -t.e; crs = ds.crs.to_string()
        w = t.c + dx / 2; n = t.f - dy / 2
        lat = {"w": w, "s": n - (ny - 1) * dy, "e": w + (nx - 1) * dx, "n": n, "nx": nx, "ny": ny, "dx": dx, "dy": dy}
        return {**lat, "src_crs": crs, "kind": "acq_r02_union_grd", "cruise": c, "grd": str(g), "grd_sha256": R.sha256_file(g),
                "record": str(R.R02 / "grid" / f"{c}.json"), "cell_m": rec["cell_m"],
                "how": f"read from the persisted ACQ-R02 union grid {g.name} (mbgrid region {rec['region']})"}
    A6, CAT, FL = _june_tables()
    if pair_id in JUNE_UNION:
        c = JUNE_UNION[pair_id]
        live = [h for h in str(FL.loc[c, "live_HR"]).split(";") if h and (h in A6.index or h in CAT.index)]
        union = gpd.GeoSeries([_footprint_for(h) for h in live], crs="EPSG:4326").union_all()
        w, s, e, n = union.bounds
        meas = [r for r in json.load((R.REPO / "reports/discovery/stage_c_full_measurements.json").open()) if r.get("cruise") == c]
        rec = meas[0]
        cells = [("achieved_cell_m", float(rec["achieved_cell_m"])),
                 ("2*footprint_depth_m*tan(beamwidth/2)", 2 * float(rec["footprint_depth_m"]) * math.tan(math.radians(float(rec["beamwidth_deg"]) / 2)))]
        tried = []
        for label, cell in cells:
            lat = _stage_c_region(w, s, e, n, cell)
            v = verify_lattice(pair_id, {**lat, "src_crs": GRD_CRS})
            tried.append({"cell_rule": label, "cell_m": cell, "nx": lat["nx"], "ny": lat["ny"], "match": v["match"]})
            if v["match"]:
                return {**lat, "src_crs": GRD_CRS, "kind": "june_stage_c_full_union", "cruise": c, "live_hr": live, "cell_m": cell, "cell_rule": label,
                        "record": "reports/discovery/stage_c_full_measurements.json", "tried": tried,
                        "how": f"re-derived: stage_c_full.py:181-190 region = union of live HR footprints {live} +/- 1 km, cell = {label}; grid itself purged from scratch"}
        return {**_stage_c_region(w, s, e, n, cells[0][1]), "src_crs": GRD_CRS, "kind": "june_stage_c_full_union", "cruise": c, "live_hr": live,
                "cell_m": cells[0][1], "cell_rule": "achieved_cell_m (NOT VERIFIED)", "tried": tried, "how": "re-derived; no candidate reproduced lr.tif's lattice"}
    c, h = JUNE_PILOT[pair_id]
    w, s, e, n = A6.loc[h].geometry.bounds
    rec = [r for r in json.load((R.REPO / "reports/discovery/stage_c_pilot_measurements.json").open()) if r.get("cruise") == c and r.get("hr_id") == h][0]
    cell = float(rec["est_cell_m"])
    lat = _stage_c_region(w, s, e, n, cell)
    return {**lat, "src_crs": GRD_CRS, "kind": "june_stage_c_pilot_per_hr", "cruise": c, "gridded_hr": h, "cell_m": cell, "cell_rule": "est_cell_m",
            "record": "reports/discovery/stage_c_pilot_measurements.json",
            "how": f"re-derived: stage_c_pilot.grid_pair region = A6 footprint bbox of {h} +/- 1 km, cell = est_cell_m {cell}; grid itself purged from scratch"}


def verify_lattice(pair_id: str, lat: dict) -> dict:
    """Does GDAL's default warp output of this geographic lattice reproduce lr.tif's UTM lattice?  (pixel size equal to
    1e-9 relative; lr.tif origin on the warped lattice at an integer pixel offset, 1e-6 px)."""
    h = lr_header(pair_id); t = h["transform"]
    dx, dy = lat["dx"], lat["dy"]
    tr, W, H = calculate_default_transform(lat["src_crs"], h["crs"], lat["nx"], lat["ny"],
                                           lat["w"] - dx / 2, lat["s"] - dy / 2, lat["e"] + dx / 2, lat["n"] + dy / 2)
    kx = (t.c - tr.c) / tr.a; ky = (t.f - tr.f) / tr.e
    rel = t.a / tr.a - 1
    match = abs(rel) < 1e-9 and abs(kx - round(kx)) < 1e-6 and abs(ky - round(ky)) < 1e-6 and abs(t.e / tr.e - 1) < 1e-9
    return {"match": bool(match), "pixel_size_rel_diff": float(rel), "lr_offset_in_warped_px": [float(kx), float(ky)],
            "warped_default": {"transform": list(tr)[:6], "width": int(W), "height": int(H)}}


# --------------------------------------------------------------------------- #
# context lattice (§1)
# --------------------------------------------------------------------------- #
def context_lattice(pair_id: str, buffer_m: float = R.BUFFER_M) -> dict:
    h = lr_header(pair_id); t = h["transform"]
    fp = gpd.read_file(R.pair_dir(pair_id) / "footprint.geojson")
    if fp.crs is None or fp.crs.to_string() != h["crs"]:
        fp = fp.to_crs(h["crs"])
    buf = fp.geometry.union_all().buffer(buffer_m)
    minx, miny, maxx, maxy = buf.bounds
    dx, dy = t.a, -t.e                                   # dy > 0
    # snap outward to lr.tif's lattice: column/row index of the context origin relative to lr.tif's origin
    c0 = int(math.floor((minx - t.c) / dx)); c1 = int(math.ceil((maxx - t.c) / dx))
    r0 = int(math.floor((t.f - maxy) / dy)); r1 = int(math.ceil((t.f - miny) / dy))
    # lr.tif itself must lie inside (it does: footprint ⊂ buffer); guarantee anyway
    c0 = min(c0, 0); r0 = min(r0, 0); c1 = max(c1, h["width"]); r1 = max(r1, h["height"])
    width, height = c1 - c0, r1 - r0
    ctx_t = rasterio.Affine(dx, 0.0, t.c + c0 * dx, 0.0, -dy, t.f - r0 * dy)
    return {"crs": h["crs"], "transform": list(ctx_t)[:6], "affine": ctx_t, "width": width, "height": height, "dx": dx, "dy": dy,
            "lr_offset_col": -c0, "lr_offset_row": -r0, "lr_width": h["width"], "lr_height": h["height"],
            "bounds": [ctx_t.c, ctx_t.f - height * dy, ctx_t.c + width * dx, ctx_t.f], "buffer_m": buffer_m,
            "footprint_area_km2": float(fp.geometry.union_all().area / 1e6), "buffered_area_km2": float(buf.area / 1e6)}


def geo_region_for_context(ctx: dict, src: dict) -> dict:
    """§2.1.2: the mbgrid region for the context = the context box in lon/lat (segmentized, so curvature is covered)
    ± 1 km, snapped OUTWARD to the stage-C node lattice (same dx, dy; origin modulo dx, dy).  Returns the -R/-E strings
    and the node lattice mbgrid will produce (bounds exact, n = round(span/spacing + 1) -> exactly our n)."""
    import pyproj
    inv = pyproj.Transformer.from_crs(ctx["crs"], "EPSG:4326", always_xy=True)
    b = ctx["bounds"]; poly = box(*b).segmentize(500.0)
    xs, ys = inv.transform(*poly.exterior.xy); xs, ys = np.asarray(xs), np.asarray(ys)
    if xs.max() - xs.min() > 180:
        raise RuntimeError("context box straddles the antimeridian: not supported (no pair in scope does)")
    w, e, s, n = float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())
    dlon, dlat = _dlon_dlat((s + n) / 2)
    w -= R.MARGIN_M * dlon; e += R.MARGIN_M * dlon; s -= R.MARGIN_M * dlat; n += R.MARGIN_M * dlat
    dx, dy = src["dx"], src["dy"]
    i0 = math.floor((w - src["w"]) / dx); i1 = math.ceil((e - src["w"]) / dx)
    j0 = math.floor((s - src["s"]) / dy); j1 = math.ceil((n - src["s"]) / dy)
    W = src["w"] + i0 * dx; E = src["w"] + i1 * dx; S = src["s"] + j0 * dy; N = src["s"] + j1 * dy
    nx, ny = i1 - i0 + 1, j1 - j0 + 1
    rule = _mbgrid_lattice(W, S, E, N, dx, dy)
    assert rule["nx"] == nx and rule["ny"] == ny, (rule, nx, ny)
    return {"R": f"{W!r}/{E!r}/{S!r}/{N!r}", "E": f"{dx!r}/{dy!r}/degrees", "w": W, "s": S, "e": E, "n": N, "nx": nx, "ny": ny,
            "dx": dx, "dy": dy, "node_offset_from_source": [i0, j0], "spacing_rel_err_after_mbgrid": [rule["dx"] / dx - 1, rule["dy"] / dy - 1],
            "lonlat_box_unsnapped": [w, s, e, n]}


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", default=None)
    a = ap.parse_args(argv)
    pairs = a.pairs.split(",") if a.pairs else list(R.PAIRS_IN_SCOPE)
    out = {"generated": R.utc_now(), "code_commit": R.git_commit(), "pairs": {}}
    n_ok = 0
    for pid in pairs:
        ctx = context_lattice(pid)
        rec = {"unit": R.UNIT_OF[pid], "kind": "provider" if R.is_provider(pid) else "ncei_swath", "lr": {k: (list(v)[:6] if k == "transform" else v) for k, v in lr_header(pid).items()},
               "context": {k: v for k, v in ctx.items() if k != "affine"}}
        if not R.is_provider(pid):
            src = source_lattice(pid); v = verify_lattice(pid, src)
            rec["source_lattice"] = src; rec["verification"] = v
            rec["context_region"] = geo_region_for_context(ctx, src)
            n_ok += v["match"]
            print(f"{pid:48s} {src['kind']:28s} {src['nx']}x{src['ny']} cell={src.get('cell_m'):.3f} -> {'MATCH' if v['match'] else 'NO MATCH'}  ctx {ctx['width']}x{ctx['height']} off=({ctx['lr_offset_col']},{ctx['lr_offset_row']})  region {rec['context_region']['nx']}x{rec['context_region']['ny']}")
        else:
            print(f"{pid:48s} provider                      ctx {ctx['width']}x{ctx['height']} off=({ctx['lr_offset_col']},{ctx['lr_offset_row']})")
        out["pairs"][pid] = rec
    out["n_ncei_lattice_verified"] = n_ok; out["n_ncei"] = sum(1 for p in pairs if not R.is_provider(p))
    R.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (R.REPORT_DIR / "lattice_recovery.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"lattice verified {n_ok}/{out['n_ncei']} NCEI pairs; written lattice_recovery.json")
    return 0 if n_ok == out["n_ncei"] else 1


if __name__ == "__main__":
    sys.exit(main())
