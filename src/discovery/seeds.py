"""Static seed HR entries for non-MGDS archives (v1.4 §3).

PANGAEA + USGS ScienceBase/CMGDS + SEANOE register here as small seed
entries so the unified catalog covers the AUV grids we've already
acquired. Footprints are taken from the manifest's harmonized HR rasters
where available (small read, no harm), or hardcoded from the directive.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import shapes
from rasterio.warp import transform_geom
from shapely.geometry import box, shape
from shapely.ops import unary_union

from .catalog import HRRecord


log = logging.getLogger(__name__)


def _footprint_from_raster(raster_path: Path) -> tuple[object | None, str]:
    """Return (lat/lon polygon of *valid-data extent*, native_crs).

    v1.4.1 §1: extract the true coverage polygon by walking the valid-pixel
    mask, not the bbox. The bbox systematically inflates AUV multi-patch
    surveys (Cal DIG: 19 dive patches sparsely scattered over ~80 km of
    coastline).
    """
    if not raster_path or not Path(raster_path).exists():
        return None, ""
    with rasterio.open(raster_path) as ds:
        native_crs = ds.crs.to_string() if ds.crs else ""
        # Read a downsampled view if the raster is enormous.
        h, w = ds.height, ds.width
        target = 2048
        if h > target or w > target:
            sy = max(1, h // target); sx = max(1, w // target)
            arr = ds.read(1, out_shape=(h // sy, w // sx), masked=True)
            transform = ds.transform * ds.transform.scale(sx, sy)
        else:
            arr = ds.read(1, masked=True)
            transform = ds.transform
        if hasattr(arr, "mask"):
            valid = (~arr.mask).astype("uint8")
        else:
            nd = ds.nodata
            valid = ((arr != nd) & np.isfinite(arr)).astype("uint8") if nd is not None else np.isfinite(arr).astype("uint8")
        if valid.sum() == 0:
            return None, native_crs
        polys = [shape(geom) for geom, val in shapes(valid, mask=valid.astype(bool), transform=transform) if val == 1]
        poly = unary_union(polys)
    if native_crs and native_crs != "EPSG:4326":
        try:
            geom_geojson = transform_geom(native_crs, "EPSG:4326", poly.__geo_interface__,
                                          precision=6)
            poly = shape(geom_geojson)
        except Exception as e:
            log.warning("reproject footprint %s -> 4326 failed: %s", raster_path, e)
            return None, native_crs
    return poly, native_crs


def seed_from_manifest(manifest_path: Path) -> list[HRRecord]:
    """Read the existing pairs manifest and emit one HR seed per unique pair_id.
    Read-only: we only consume the manifest, never modify it.
    """
    if not Path(manifest_path).exists():
        log.warning("manifest %s not found; no seeds emitted", manifest_path)
        return []
    df = pd.read_parquet(manifest_path)
    out: list[HRRecord] = []
    now = datetime.now(timezone.utc).isoformat()
    for _, r in df.iterrows():
        pair_id = str(r["pair_id"])
        source_label = _source_for_doi(str(r.get("hr_doi") or ""))
        hr_path = Path(str(r.get("harmonized_path_hr") or ""))
        poly, native_crs = _footprint_from_raster(hr_path)
        if poly is None or poly.is_empty:
            continue
        out.append(HRRecord(
            hr_id=f"{source_label}:{pair_id}",
            source=source_label,
            doi=str(r.get("hr_doi") or ""),
            source_uid=pair_id,
            title=f"{r.get('site_name','')} — {r.get('cruise_id','')}",
            platform=str(r.get("hr_platform") or "AUV"),
            platform_type="AUV",
            sonar=str(r.get("hr_sonar") or ""),
            native_res_m=float(r["hr_native_res_m"]) if pd.notna(r.get("hr_native_res_m")) else None,
            native_crs=native_crs or str(r.get("native_crs_hr") or ""),
            format="GeoTIFF",  # harmonized output is always GeoTIFF
            file_ids=str(r.get("harmonized_path_hr") or ""),
            license=str(r.get("license") or "").split(";")[0].replace("HR:", "").strip(),
            cruise_id=str(r.get("cruise_id") or ""),
            start_date=str(r.get("acquisition_date") or ""),
            stop_date="",
            depth_min_m=float(r["depth_min_m"]) if pd.notna(r.get("depth_min_m")) else None,
            depth_max_m=float(r["depth_max_m"]) if pd.notna(r.get("depth_max_m")) else None,
            geographic_feature=str(r.get("region") or ""),
            sibling_dois="",
            description=str(r.get("notes") or "")[:400],
            harvested_at_utc=now,
            geometry=poly,
        ))
    log.info("manifest seeds: %d HR records", len(out))
    return out


def _source_for_doi(doi: str) -> str:
    if not doi:
        return "MANIFEST"
    if "PANGAEA" in doi.upper():
        return "PANGAEA"
    if "10.5066" in doi:
        return "SCIENCEBASE"
    if "SEANOE" in doi.upper() or "17882" in doi:
        return "SEANOE"
    return "MANIFEST"
