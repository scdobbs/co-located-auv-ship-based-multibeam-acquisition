"""NCEI Multibeam Bathymetry Database (MBBDB) LR harvester.

§4 requires runtime confirmation of the ArcGIS layer URL (NCEI moves
layers around). We discover the multibeam-footprints layer once via the
services directory, then query it per HR footprint with
``spatialRel=intersects, f=geojson``.

Footprints come back as MultiPolygons in WGS84. Per-survey metadata
(platform, instrument, dates, download URL) is in the feature properties.
Optional follow-up via the Geoportal ISO endpoint can add processed-grid
vs raw-only distinction; that lives in :func:`enrich_geoportal` and is
applied on demand.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape


log = logging.getLogger(__name__)

ARCGIS_ROOT = "https://gis.ngdc.noaa.gov/arcgis/rest/services"
_THROTTLE = 0.3
_HEADERS = {"User-Agent": "auv-ship-acq/0.1 (Sherlock; v1.4 discovery)"}


@dataclass
class _Layer:
    base_url: str            # full URL up to /MapServer or /FeatureServer/<id>
    name: str
    geom_type: str


def discover_layer() -> _Layer:
    """Find the multibeam-footprints layer at runtime (§4 hard rule)."""
    # Probe likely candidates; the directory enumerates them.
    candidates = [
        f"{ARCGIS_ROOT}/multibeam_footprints/MapServer/0",       # primary - polygons
        f"{ARCGIS_ROOT}/multibeam_datasets/MapServer/0",          # fallback - polylines
    ]
    for u in candidates:
        try:
            j = requests.get(u, params={"f": "json"}, timeout=30, headers=_HEADERS).json()
        except Exception:
            continue
        name = j.get("name", "")
        gt = j.get("geometryType", "")
        if name and "footprint" in name.lower() and "polygon" in gt.lower():
            log.info("NCEI layer (polygon): %s [%s]", u, name)
            return _Layer(u, name, gt)
        if name and "polygon" in gt.lower():
            log.info("NCEI layer (polygon fallback): %s [%s]", u, name)
            return _Layer(u, name, gt)
    # Last resort: tracklines (polyline)
    for u in candidates:
        try:
            j = requests.get(u, params={"f": "json"}, timeout=30, headers=_HEADERS).json()
        except Exception:
            continue
        if j.get("name"):
            log.warning("NCEI: using polyline layer %s; spatial-join precision reduced.", u)
            return _Layer(u, j["name"], j.get("geometryType", ""))
    raise RuntimeError("could not locate any NCEI multibeam layer")


def query_intersects(layer: _Layer, bbox: tuple[float, float, float, float],
                     max_records: int = 200) -> list[dict[str, Any]]:
    """Query for ship-survey features intersecting an HR bbox (WGS84)."""
    xmin, ymin, xmax, ymax = bbox
    params = {
        "where": "1=1",
        "geometry": json.dumps({
            "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
            "spatialReference": {"wkid": 4326},
        }),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultRecordCount": max_records,
    }
    r = requests.get(f"{layer.base_url}/query", params=params, timeout=120, headers=_HEADERS)
    r.raise_for_status()
    time.sleep(_THROTTLE)
    return json.loads(r.text).get("features", [])


def _bbox(geom) -> tuple[float, float, float, float] | None:
    if geom is None or geom.is_empty:
        return None
    return tuple(geom.bounds)  # (minx, miny, maxx, maxy)


def harvest_for_hr_catalog(hr_path: Path, cache_dir: Path, out_path: Path,
                           max_records_per_hr: int = 100) -> Path:
    """For each HR in the catalog, query NCEI and write all intersecting
    ship-survey footprints to a GeoPackage layer ``lr``.
    """
    layer = discover_layer()
    hr_gdf = gpd.read_file(hr_path, layer="hr")
    if hr_gdf.crs is None or str(hr_gdf.crs).lower() != "epsg:4326":
        hr_gdf = hr_gdf.to_crs("EPSG:4326")
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    geoms = []
    now = datetime.now(timezone.utc).isoformat()
    seen = set()

    for _, hr in hr_gdf.iterrows():
        hr_id = hr["hr_id"]
        bbox = _bbox(hr.geometry)
        if bbox is None:
            continue
        cache_path = cache_dir / f"{hr_id.replace(':','_').replace('/','_')}.geojson"
        if cache_path.exists():
            feats = json.loads(cache_path.read_text()).get("features", [])
        else:
            try:
                feats = query_intersects(layer, bbox, max_records=max_records_per_hr)
            except Exception as e:
                log.warning("NCEI query for %s failed: %s", hr_id, e)
                continue
            cache_path.write_text(json.dumps({"features": feats}))
        log.info("HR %s: %d NCEI hits", hr_id, len(feats))
        for f in feats:
            props = f.get("properties") or {}
            survey_id = props.get("SURVEY_ID") or props.get("DATASET_NAME") or ""
            ncei_id = props.get("NCEI_ID") or props.get("NGDC_ID") or ""
            # De-duplicate by (HR, SURVEY_AND_VERSION or SURVEY_ID) so re-queries
            # don't double-emit (this still emits the same survey per HR pair,
            # which is correct — same LR survey can pair with multiple HRs).
            key = (hr_id, props.get("SURVEY_AND_VERSION") or survey_id)
            if key in seen:
                continue
            seen.add(key)
            try:
                g = shape(f.get("geometry"))
            except Exception:
                g = None
            if g is None or g.is_empty:
                continue
            ms_start = props.get("START_TIME"); ms_end = props.get("END_TIME")
            start_iso = _ms_to_iso(ms_start); end_iso = _ms_to_iso(ms_end)
            rows.append({
                "lr_id": f"NCEI_MBBDB:{survey_id}",
                "source": "NCEI_MBBDB",
                "cruise_id": survey_id,
                "survey_id": survey_id,
                "platform": props.get("PLATFORM") or "",
                "platform_type": "Ship",
                "sonar": props.get("INSTRUMENT") or "",
                "start_date": start_iso,
                "stop_date": end_iso,
                "native_res_est_m": None,
                "format": props.get("Version") and "processed footprint" or "",
                "has_processed_grid": None,   # enriched optionally via Geoportal
                "metadata_url": props.get("DOWNLOAD_URL") or "",
                "download_links": props.get("DOWNLOAD_URL") or "",
                "license": "NOAA NCEI public-domain (US Federal)",
                "harvested_at_utc": now,
                "hr_id_query": hr_id,
            })
            geoms.append(g)
    gdf = gpd.GeoDataFrame(pd.DataFrame(rows), geometry=geoms, crs="EPSG:4326")
    gdf.to_file(out_path, driver="GPKG", layer="lr")
    log.info("NCEI LR harvest: %d rows -> %s", len(gdf), out_path)
    return out_path


def _ms_to_iso(ms: Any) -> str:
    if ms in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except Exception:
        return ""
