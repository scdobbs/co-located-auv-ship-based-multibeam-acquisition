"""v1.4.1 orchestrator — re-process existing catalogs without re-harvesting.

Applies §1 footprint correction (seeds → valid-data polys; AUV-class
suspicious-area flag), §2 dedupe, §3 platform filter, §4 LR enrichment,
§5 re-score + triage view. Read-only against manifest and harmonized
rasters: only writes under ``reports/discovery/``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyproj
from shapely.ops import transform

from . import dedupe as dedupe_mod
from . import geoportal
from . import platform_filter as pf
from . import seeds as seeds_mod
from . import join as join_mod


log = logging.getLogger(__name__)


def _area_km2(geom) -> float:
    if geom is None or geom.is_empty:
        return 0.0
    cx, cy = geom.centroid.x, geom.centroid.y
    tr = pyproj.Transformer.from_crs(
        "EPSG:4326",
        f"+proj=laea +lat_0={cy} +lon_0={cx} +ellps=WGS84",
        always_xy=True,
    ).transform
    return float(transform(tr, geom).area) / 1e6


def rebuild_hr(hr_path: Path, manifest_path: Path) -> gpd.GeoDataFrame:
    """Apply §1 + §3 + §2 to the HR catalog. Returns the corrected GDF."""
    hr = gpd.read_file(hr_path, layer="hr")
    log.info("loaded %d HR rows", len(hr))

    # §1a — recompute seed geometries from harmonized raster valid-data masks.
    # We re-run the seed harvester (which now uses valid-mask polygons).
    fresh_seeds = seeds_mod.seed_from_manifest(manifest_path)
    seed_map = {r.hr_id: r for r in fresh_seeds}
    fixed = 0
    for i, row in hr.iterrows():
        sid = row["hr_id"]
        if sid in seed_map:
            new_geom = seed_map[sid].geometry
            if new_geom is not None and not new_geom.is_empty:
                hr.at[i, "geometry"] = new_geom
                fixed += 1
    log.info("§1 seed-geometry fix applied to %d rows", fixed)

    # v1.5.1 §4 — platform CLASSIFICATION (recording, not gating).
    # ``hr_class`` ∈ {auv, usv, surface_vessel} for stratification.
    # ``is_non_bathy`` is the only platform-level rejection signal — it
    # marks sidescan / sub-bottom / magnetometer products, which are NOT
    # bathymetry HR regardless of platform.
    is_auv = []; hr_class = []; reason = []; is_non_bathy = []
    for _, row in hr.iterrows():
        a, v, r = pf.classify(
            row.get("platform") or "",
            row.get("sonar") or "",
            row.get("description") or "",
            row.get("native_res_m"),
        )
        is_non_bathy.append(v == "non_bathy")
        # hr_class normalises non_bathy → surface_vessel for stratification
        # (the modelling step uses is_non_bathy separately for rejection).
        cls = v if v in ("auv", "usv", "surface_vessel") else "surface_vessel"
        is_auv.append(a); hr_class.append(cls); reason.append(r)
    hr["is_auv_grid"] = is_auv          # legacy alias = (hr_class == 'auv')
    hr["hr_class"] = hr_class
    hr["is_non_bathy"] = is_non_bathy
    hr["platform_verdict"] = hr_class    # backwards-compat
    hr["platform_reason"] = reason

    # §1b — footprint_suspect for AUV-class entries with implausibly large areas.
    # The heuristic targets metadata-bbox inflation; once Stage B has measured
    # the true valid-data polygon (geometry_source='stage_b_resolved') the
    # heuristic must not re-flag the row, even if the real area exceeds the
    # 60 km^2 threshold. Stage-B-failed-no-CRS rows stay suspect (we still
    # don't have a real polygon) and the Stage A tier classifier excludes them.
    if "geometry_source" not in hr.columns:
        hr["geometry_source"] = "metadata_bbox"
    hr["geometry_source"] = hr["geometry_source"].fillna("metadata_bbox")
    suspect = []; areas = []
    for _, row in hr.iterrows():
        a_km2 = _area_km2(row.geometry)
        areas.append(a_km2)
        src = row.get("geometry_source") or "metadata_bbox"
        if src in ("stage_b_resolved", "crs_recovered"):
            suspect.append(False)
        elif src in ("stage_b_failed_no_crs",
                     "crs_failed_verification", "crs_unrecoverable"):
            suspect.append(True)
        else:
            suspect.append(pf.footprint_suspect(a_km2, row.get("native_res_m"),
                                                row["is_auv_grid"]))
    hr["footprint_km2"] = areas
    hr["footprint_suspect"] = suspect

    # §2 — dedupe MGDS sibling rows.
    hr = dedupe_mod.dedupe(hr)
    return hr


def rebuild_lr(lr_path: Path, hr_gdf: gpd.GeoDataFrame, cache_dir: Path) -> gpd.GeoDataFrame:
    lr = gpd.read_file(lr_path, layer="lr")
    log.info("loaded %d LR rows", len(lr))
    lr = geoportal.enrich(lr, hr_gdf, cache_dir)
    return lr


def write_layers(hr_gdf: gpd.GeoDataFrame, lr_gdf: gpd.GeoDataFrame,
                 out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    hr_out = out_dir / "hr_catalog.gpkg"
    lr_out = out_dir / "lr_candidates.gpkg"
    hr_gdf.to_file(hr_out, driver="GPKG", layer="hr")
    lr_gdf.to_file(lr_out, driver="GPKG", layer="lr")
    return hr_out, lr_out
