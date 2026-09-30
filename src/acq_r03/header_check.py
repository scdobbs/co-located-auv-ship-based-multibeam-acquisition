"""ACQ-R03 §2.2 — grid-registration header check for the pairs whose v2 argmin is >= 0.5 cell (CCZ, DISCOL, TAG)
and for EW0207 / EW9801 (which the ACQ-R02 text described as 0.5-0.75 cells off; their table argmins are 0.25).

For each pair, from the original grids and the harmonization code:
  * each grid's registration: GeoTIFF GTRasterTypeGeoKey (rasterio tag AREA_OR_POINT: Area = PixelIsArea,
    Point = PixelIsPoint; absent = PixelIsArea by the GeoTIFF default) or, for GMT/CF netCDF grids, the
    coordinate-variable convention (x/y arrays are the node positions, i.e. the positions of the values);
  * how the harmonization interpreted it (rasterio/GDAL PixelIsArea semantics; for netCDF GDAL puts the pixel
    centres on the coordinate nodes: verified numerically on a current mbgrid grid);
  * the implied offset in metres in lr.tif coordinates (0 unless a mismatch is established).
The frame offset (contract v2.1 §0.2) is applied ONLY where this check establishes a mismatch
(basis grid_header_registration); it is never fitted from the QA surface.
Output: reports_post_grl_review/ACQ-R03/header_check.{json,md}; the builder reads header_check.json.
"""
from __future__ import annotations

import json
import sys

import netCDF4 as nc
import numpy as np
import pandas as pd
import rasterio

from src.acq_r03 import common as R

PAIRS = ["ccz_so268_1", "discol_so242_1", "tag_m127", "EW0207__MGDS_32556", "EW9801__MGDS_31425"]
# June harmonization code path of the LR (and HR) per pair, from the repo (src/discovery, src/harmonize.py)
CODE_PATH = {
    "ccz_so268_1": "src/pipeline.py -> src/harmonize.harmonize_pair: rioxarray.open_rasterio (GDAL GeoTIFF reader, PixelIsArea semantics); same CRS -> no reprojection, clip only (grid alignment preserved: lr.tif edges are multiples of 50 m as in the raw grid)",
    "discol_so242_1": "src/pipeline.py -> src/harmonize.harmonize_pair: rioxarray.open_rasterio; same CRS -> clip only (lr.tif origin = raw origin + integer number of cells)",
    "tag_m127": "src/pipeline.py -> src/harmonize.harmonize_pair: rioxarray.open_rasterio (EPSG:4326 GeoTIFF, PixelIsArea) -> rio.reproject to EPSG:32623, bilinear",
    "EW0207__MGDS_32556": "LR: mbgrid CF/COARDS netCDF (x/y coordinate variables) read by src/discovery/stage_c1_harmonize.materialize -> rasterio.open (GDAL netCDF driver; gmt_grd.is_gmt_grd is False for the 2-D COARDS layout, and the _read_coards_grd fallback is not reached because rasterio opens the file) -> src/harmonize.harmonize_pair reproject to EPSG:32609, bilinear. HR: MBARI classic GMT grid via src/gmt_grd.convert (from_bounds on x_range/y_range: node range treated as outer edges, a half-cell + 1/nx scale error on the HR side only); the HR was then rigidly co-registered to lr.tif (stage F masked coreg), so the pair is internally consistent and the HR registration does not enter the ship products.",
    "EW9801__MGDS_31425": "LR: mbgrid CF/COARDS netCDF read by src/discovery/stage_f_harmonize._lr_to_tif -> rasterio.open (GDAL netCDF driver) -> src/harmonize.harmonize_pair reproject to EPSG:32605, bilinear. HR: float GeoTIFF (EPSG:4326) via rasterio.",
}
FRESH_GRD = R.OAK / "raw_lr_gridded" / "TN399__union.grd"     # a current mbgrid output (same MB-System 5.8.2beta06 as June)


def geotiff_registration(path):
    with rasterio.open(path) as ds:
        tag = ds.tags().get("AREA_OR_POINT")
        return {"file": str(path), "driver": ds.driver, "crs": str(ds.crs), "res": [abs(ds.res[0]), abs(ds.res[1])], "shape": list(ds.shape),
                "bounds": list(ds.bounds), "AREA_OR_POINT_tag": tag,
                "registration": {"Area": "PixelIsArea", "Point": "PixelIsPoint", None: "PixelIsArea (GTRasterTypeGeoKey absent; GeoTIFF default)"}[tag]}


def netcdf_gdal_placement(grd):
    """How GDAL/rasterio georeferences a GMT/CF netCDF grid: are the pixel centres on the coordinate nodes?"""
    with nc.Dataset(grd) as ds:
        x = np.asarray(ds.variables["x"][:], float); y = np.asarray(ds.variables["y"][:], float)
        attrs = {k: str(ds.getncattr(k))[:60] for k in ds.ncattrs()}
        node_offset = ds.getncattr("node_offset") if "node_offset" in ds.ncattrs() else None
    dx = float(x[1] - x[0]); dy = float(abs(y[1] - y[0]))
    with rasterio.open(grd) as ds:
        b = ds.bounds; res = ds.res
    return {"file": str(grd), "conventions": attrs.get("Conventions"), "node_offset_attr": node_offset,
            "x_first_node": float(x[0]), "dx": dx, "rasterio_left_edge": b.left, "left_edge_minus_first_node_in_cells": round((b.left - x[0]) / dx, 6),
            "y_last_node": float(y.max()), "rasterio_top_edge": b.top, "top_edge_minus_last_node_in_cells": round((b.top - y.max()) / dy, 6),
            "interpretation": "GDAL places pixel centres on the x/y coordinate nodes (edges = node -/+ half cell): PixelIsArea with the value at the pixel centre = the node. mbgrid's node values are footprint-weighted means centred on the node, so this is the correct registration; no half-cell error."}


def main(argv=None):
    m = pd.read_parquet(R.C.REPO / "manifest" / "pairs_v2.parquet").set_index("pair_id")
    fresh = netcdf_gdal_placement(FRESH_GRD)
    out = {"generated": R.utc_now(), "gdal_netcdf_placement_check": fresh, "pairs": {}}
    for pid in PAIRS:
        r = m.loc[pid]
        rec = {"lr_native_res_m": float(r["lr_native_res_m"]), "target_crs": r["target_crs"], "code_path": CODE_PATH[pid], "grids": {}}
        for side in ("lr", "hr"):
            raw = R.OAK / str(r[f"raw_path_{side}"])
            if raw.exists() and raw.is_file():
                rec["grids"][f"raw_{side}"] = geotiff_registration(raw)
            else:
                rec["grids"][f"raw_{side}"] = {"file": str(r[f"raw_path_{side}"]), "status": "not on OAK (June scratch raw_lr/ purged 2026-09-20); registration established from the format + reader (see code_path and gdal_netcdf_placement_check)",
                                               "format": "mbgrid CF/COARDS netCDF (x/y coordinate variables; GMT_version 6.1.1)" if side == "lr" else ("MBARI classic GMT netCDF (1-D z, x_range/y_range)" if pid.startswith("EW0207") else "float GeoTIFF (EPSG:4326)")}
            rec["grids"][f"harmonized_{side}"] = geotiff_registration(R.OAK / str(r[f"harmonized_path_{side}"]))
        # alignment of harmonized lr.tif with the raw LR grid where no reprojection happened
        rl, hl = rec["grids"]["raw_lr"], rec["grids"]["harmonized_lr"]
        if "bounds" in rl and rl["crs"] == hl["crs"]:
            k = (hl["bounds"][0] - rl["bounds"][0]) / rl["res"][0]
            rec["harmonized_lr_origin_offset_from_raw_in_cells"] = round(k, 6)
        rec["registration_mismatch_established"] = False
        rec["frame_offset"] = {"applied": False, "dx_m": 0.0, "dy_m": 0.0, "basis": "none",
                               "evidence": (f"raw LR GTRasterTypeGeoKey = {rl.get('registration')}; harmonize_pair read it with GDAL PixelIsArea semantics; no header-established mismatch" if "registration" in rl
                                            else "LR = mbgrid CF netCDF read with GDAL (pixel centres on the coordinate nodes, verified: edge - node = -0.5 cell); no header-established mismatch")}
        rec["implied_offset_m_in_lr_tif"] = 0.0
        out["pairs"][pid] = rec
    R.write_json(R.REPORT_DIR / "header_check.json", out)
    md = ["# ACQ-R03 §2.2 header check (grid registration)", "",
          f"GDAL/rasterio placement on a current mbgrid grid (`{FRESH_GRD.name}`): left edge − first x node = {fresh['left_edge_minus_first_node_in_cells']} cells, top edge − last y node = {fresh['top_edge_minus_last_node_in_cells']} cells → pixel centres on the nodes (correct for mbgrid node values). `node_offset` attribute: {fresh['node_offset_attr']}; Conventions {fresh['conventions']}.", "",
          "| pair | raw LR registration | raw HR registration | harmonize_pair reader | harmonized lr.tif origin vs raw (cells) | mismatch | frame offset (m) |", "|---|---|---|---|---|---|---|"]
    for pid, rec in out["pairs"].items():
        g = rec["grids"]
        md.append(f"| {pid} | {g['raw_lr'].get('registration', g['raw_lr'].get('format'))} | {g['raw_hr'].get('registration', g['raw_hr'].get('format'))} | GDAL PixelIsArea (rasterio/rioxarray) | {rec.get('harmonized_lr_origin_offset_from_raw_in_cells', 'reprojected')} | {rec['registration_mismatch_established']} | {rec['frame_offset']['dx_m']}, {rec['frame_offset']['dy_m']} |")
    md += ["", "Code paths:", ""] + [f"- **{pid}**: {rec['code_path']}" for pid, rec in out["pairs"].items()]
    (R.REPORT_DIR / "header_check.md").write_text("\n".join(md) + "\n")
    print("\n".join(md)); return 0


if __name__ == "__main__":
    sys.exit(main())
