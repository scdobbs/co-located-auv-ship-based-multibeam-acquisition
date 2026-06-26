"""HR / LR / candidate-pair catalog schemas.

Backed by GeoPackage for the in-repo, human-reviewable copy and GeoParquet
for downstream tools. Footprints are stored as polygons in EPSG:4326
(WGS84 lat/lon); native CRS / GSD / depth are kept as attributes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


# HR catalog row — one per gridded-bathymetry-product family per mission.
HR_COLUMNS = [
    "hr_id",                # stable ID we mint: "<source>:<doi_or_uid>"
    "source",               # MGDS / PANGAEA / SCIENCEBASE / SEANOE
    "doi",                  # DOI when present
    "source_uid",           # native uid in source (data_set_uid, PANGAEA id, ScienceBase id, ...)
    "title",
    "platform",
    "platform_type",
    "sonar",
    "native_res_m",         # parsed; None when unknown
    "native_crs",           # native CRS string (e.g. "EPSG:32610", "UTM-10N", "EPSG:4326")
    "format",               # "GeoTIFF", "NetCDF:Grid", "ESRI ASCII", ...
    "file_ids",             # comma-separated source-specific download IDs / URLs
    "license",
    "cruise_id",
    "start_date",
    "stop_date",
    "depth_min_m",
    "depth_max_m",
    "geographic_feature",   # e.g. "MontereyCanyon" / "EPR:9N"
    "sibling_dois",         # comma-separated DOIs in the same survey family
    "description",
    "harvested_at_utc",
    # geometry held by the GeoDataFrame; schema is for parquet compatibility
]

# LR catalog row — one per intersecting ship-survey footprint per HR query.
LR_COLUMNS = [
    "lr_id",                # "<source>:<cruise_id>:<survey_id>"
    "source",               # NCEI_MBBDB / NCEI_NOS / IHO_DCDB
    "cruise_id",
    "survey_id",
    "platform",
    "platform_type",        # always "Ship" for these
    "sonar",
    "start_date",
    "stop_date",
    "native_res_est_m",     # estimate or None
    "format",               # raw / processed grid / BAG
    "has_processed_grid",   # bool
    "metadata_url",
    "download_links",       # JSON-encoded list when multiple
    "license",
    "harvested_at_utc",
    "hr_id_query",          # which HR footprint triggered this match
]

# Candidate pair row — produced by the spatial join + scoring.
PAIR_COLUMNS = [
    "candidate_id",
    "hr_id", "hr_repo", "hr_doi", "hr_platform", "hr_sonar", "hr_native_res_m",
    "hr_format", "hr_file_ids", "hr_license",
    "lr_id", "lr_source", "lr_cruise_id", "lr_platform", "lr_sonar",
    "lr_has_processed_grid", "lr_native_res_est_m", "lr_metadata_url",
    "overlap_km2", "overlap_frac_hr", "res_ratio",
    "depth_min_m", "depth_max_m", "terrain_hint",
    "independence_verdict", "independence_reason",
    "score", "rank",
    "status",  # proposed / human_selected / human_rejected
    # geometry: HR∩LR overlap polygon
]


@dataclass
class HRRecord:
    hr_id: str
    source: str
    doi: str = ""
    source_uid: str = ""
    title: str = ""
    platform: str = ""
    platform_type: str = "AUV"
    sonar: str = ""
    native_res_m: float | None = None
    native_crs: str = ""
    format: str = ""
    file_ids: str = ""
    license: str = ""
    cruise_id: str = ""
    start_date: str = ""
    stop_date: str = ""
    depth_min_m: float | None = None
    depth_max_m: float | None = None
    geographic_feature: str = ""
    sibling_dois: str = ""
    description: str = ""
    harvested_at_utc: str = ""
    # geometry attached when written to GeoDataFrame
    geometry: Any = None


def write_hr_catalog(records: list[HRRecord], out_path: Path) -> Path:
    """Write a GeoPackage from a list of HRRecords."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    geoms = []
    for r in records:
        d = asdict(r)
        geoms.append(d.pop("geometry"))
        rows.append(d)
    gdf = gpd.GeoDataFrame(pd.DataFrame(rows), geometry=geoms, crs="EPSG:4326")
    gdf.to_file(out_path, driver="GPKG", layer="hr")
    return out_path


def read_hr_catalog(path: Path) -> gpd.GeoDataFrame:
    return gpd.read_file(path, layer="hr")
