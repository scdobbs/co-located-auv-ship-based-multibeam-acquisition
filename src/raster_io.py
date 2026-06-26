"""Raster metadata extraction with strict fail-fast.

Per §6 step 2: read native CRS, resolution, units, vertical reference, and
nodata for each grid. If any is missing or ambiguous, stop and flag — do not
assume.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine


class RasterMetadataError(RuntimeError):
    pass


@dataclass
class RasterInfo:
    path: Path
    crs: str
    crs_units: str
    pixel_size_x_m: float
    pixel_size_y_m: float
    nodata: float | None
    width: int
    height: int
    bounds: tuple[float, float, float, float]
    transform: Affine
    vertical_ref: str
    tags: dict
    band_count: int

    @property
    def gsd_m(self) -> float:
        return (abs(self.pixel_size_x_m) + abs(self.pixel_size_y_m)) / 2


def _vertical_ref(tags: dict, profile_tags: dict) -> str:
    """Pull a vertical reference hint from raster tags. Return 'unknown' if
    there's nothing to go on, so the caller can decide to flag.
    """
    candidates = [
        tags.get("VERTICAL_DATUM"),
        tags.get("VERT_CS"),
        tags.get("vertical_datum"),
        tags.get("AREA_OR_POINT"),  # informational
        profile_tags.get("VERTICAL_DATUM"),
    ]
    for c in candidates:
        if c:
            return str(c)
    return "unknown"


def describe(path: Path) -> RasterInfo:
    p = Path(path)
    with rasterio.open(p) as ds:
        if ds.crs is None:
            raise RasterMetadataError(f"{p}: missing CRS")
        crs = CRS.from_user_input(ds.crs)
        units = crs.linear_units or "unknown"
        if units.lower() not in ("metre", "meter", "metres", "meters", "m"):
            # Lat/long datasets reach us in Tier 2 (e.g. AtlantOS M127 AUV
            # GeoTIFFs are exported in EPSG:4326 even though gridded at 2 m
            # in projected space). describe() can still report shape +
            # bounds; gsd_m will be in degrees and is NOT a meaningful
            # metric — callers must use the pair's declared `native_res_m`
            # for any comparison instead of `info.gsd_m`.
            if not crs.is_projected:
                import logging as _l
                _l.getLogger(__name__).warning(
                    "%s: CRS is geographic (%s); gsd_m will be in degrees, "
                    "not metres. harmonize will reproject.", p, crs.to_string(),
                )
        tr = ds.transform
        info = RasterInfo(
            path=p,
            crs=crs.to_string(),
            crs_units=units,
            pixel_size_x_m=float(tr.a),
            pixel_size_y_m=float(tr.e),
            nodata=ds.nodata,
            width=ds.width,
            height=ds.height,
            bounds=tuple(ds.bounds),
            transform=tr,
            vertical_ref=_vertical_ref(ds.tags(), ds.profile.get("tags", {}) if isinstance(ds.profile.get("tags", {}), dict) else {}),
            tags=ds.tags(),
            band_count=ds.count,
        )
    if info.nodata is None:
        raise RasterMetadataError(f"{p}: missing nodata value; refusing to guess")
    if info.gsd_m <= 0:
        raise RasterMetadataError(f"{p}: degenerate pixel size {info.pixel_size_x_m}x{info.pixel_size_y_m}")
    return info
