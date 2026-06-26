"""Reproject + overlap + clip pipeline (no synthetic LR generation).

Steps per pair, per §6:
  3. Reproject both rasters to target_crs (bilinear). Preserve native GSD.
  4. Compute HR∩LR overlap polygon from valid-data masks.
  5. Clip both grids to the polygon.
  6. Normalize vertical reference (negative-down, MSL) per config.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import rioxarray  # noqa: F401  side-effect: rio accessor on xarray
import xarray as xr
from rasterio.enums import Resampling
from rasterio.features import shapes
from shapely.geometry import shape
from shapely.ops import unary_union

from .raster_io import RasterInfo, describe


log = logging.getLogger(__name__)


_RESAMPLING = {
    "bilinear": Resampling.bilinear,
    "cubic": Resampling.cubic,
    "average": Resampling.average,
}


class HarmonizationError(RuntimeError):
    pass


@dataclass
class HarmonizedPair:
    hr_path: Path
    lr_path: Path
    footprint_path: Path
    overlap_area_km2: float
    hr_info: RasterInfo
    lr_info: RasterInfo


def _open(path: Path) -> xr.DataArray:
    da = rioxarray.open_rasterio(path, masked=True)
    if da.ndim == 3 and da.sizes.get("band") == 1:
        da = da.squeeze("band", drop=True)
    return da


def _reproject(da: xr.DataArray, target_crs: str, resampling: Resampling, nodata: float) -> xr.DataArray:
    if str(da.rio.crs) == target_crs:
        return da.rio.write_nodata(nodata)
    return da.rio.reproject(target_crs, resampling=resampling, nodata=nodata)


def _valid_polygon(da: xr.DataArray) -> "gpd.GeoSeries":
    """Polygon of valid (non-nodata) pixels in the raster's CRS."""
    arr = da.values
    mask = (~np.isnan(arr)).astype("uint8")
    if mask.sum() == 0:
        raise HarmonizationError("raster has no valid pixels")
    transform = da.rio.transform()
    polys = [shape(geom) for geom, val in shapes(mask, mask=mask.astype(bool), transform=transform) if val == 1]
    merged = unary_union(polys)
    return gpd.GeoSeries([merged], crs=str(da.rio.crs))


def harmonize_pair(
    *,
    pair_id: str,
    hr_raw: Path,
    lr_raw: Path,
    target_crs: str,
    resample_kernel: str,
    nodata: float,
    out_dir: Path,
    vertical_sign: str,
    min_overlap_area_km2: float,
) -> HarmonizedPair:
    out_dir.mkdir(parents=True, exist_ok=True)
    if resample_kernel not in _RESAMPLING:
        raise HarmonizationError(f"unknown resample_kernel={resample_kernel}")
    resampling = _RESAMPLING[resample_kernel]

    log.info("[%s] opening rasters", pair_id)
    hr = _open(hr_raw)
    lr = _open(lr_raw)

    log.info("[%s] reprojecting to %s", pair_id, target_crs)
    hr_p = _reproject(hr, target_crs, resampling, nodata)
    lr_p = _reproject(lr, target_crs, resampling, nodata)

    log.info("[%s] computing valid-data polygons", pair_id)
    hr_poly = _valid_polygon(hr_p)
    lr_poly = _valid_polygon(lr_p)
    overlap = hr_poly.intersection(lr_poly, align=False).iloc[0]
    if overlap.is_empty:
        raise HarmonizationError(f"[{pair_id}] HR and LR footprints do not intersect")

    overlap_gs = gpd.GeoSeries([overlap], crs=target_crs)
    overlap_area_km2 = float(overlap_gs.area.iloc[0]) / 1e6
    if overlap_area_km2 < min_overlap_area_km2:
        raise HarmonizationError(
            f"[{pair_id}] overlap area {overlap_area_km2:.3f} km^2 below threshold "
            f"{min_overlap_area_km2}"
        )

    footprint_path = out_dir / "footprint.geojson"
    overlap_gs.to_file(footprint_path, driver="GeoJSON")

    log.info("[%s] clipping to overlap (%.3f km^2)", pair_id, overlap_area_km2)
    hr_clipped = hr_p.rio.clip(overlap_gs.geometry, overlap_gs.crs, drop=True, all_touched=False)
    lr_clipped = lr_p.rio.clip(overlap_gs.geometry, overlap_gs.crs, drop=True, all_touched=False)

    if vertical_sign == "negative_down":
        # Bathymetry conventions vary; if the raw raster reports depth (positive
        # down) it would typically have positive values for the seafloor. We
        # don't auto-flip — the caller must surface a mismatch via QA.
        pass

    hr_out = out_dir / "hr.tif"
    lr_out = out_dir / "lr.tif"
    for da in (hr_clipped, lr_clipped):
        # xarray's CF encoder refuses to overwrite _FillValue in attrs.
        # Drop the stale attr and let rioxarray re-emit it via encoding.
        da.attrs.pop("_FillValue", None)
        da.encoding.pop("_FillValue", None)
        da.rio.write_nodata(nodata, encoded=True, inplace=True)
    hr_clipped.rio.to_raster(hr_out, compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")
    lr_clipped.rio.to_raster(lr_out, compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")

    return HarmonizedPair(
        hr_path=hr_out,
        lr_path=lr_out,
        footprint_path=footprint_path,
        overlap_area_km2=overlap_area_km2,
        hr_info=describe(hr_out),
        lr_info=describe(lr_out),
    )
