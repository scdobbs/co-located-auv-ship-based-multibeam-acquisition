"""v1.4.1 §4 — LR native-GSD enrichment.

Two paths:
  1. NCEI Geoportal ISO metadata per cruise. The MD_Resolution field, when
     present, gives the processed-grid GSD. Many older cruises don't
     publish this; we cache the JSON to avoid re-querying.
  2. Fallback heuristic by sonar + median depth band. Bracketed values
     are conservative — they're for ranking, not science.

Sets ``lr_native_res_est_m`` and ``lr_res_source`` ∈
``{"geoportal", "estimated", "unknown"}``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import geopandas as gpd
import requests


log = logging.getLogger(__name__)

_GEOPORTAL_BASE = ("https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/"
                   "gov.noaa.ngdc.mgg.multibeam:")
_HEADERS = {"User-Agent": "auv-ship-acq/0.1 (Sherlock; v1.4.1 enrichment)"}
_THROTTLE = 0.2

# Sonar fallback GSD bands.  (depth_band_m, gsd_m) per sonar family.
# Bands chosen to match published processed-grid conventions.
_SONAR_GSD = {
    # Deep-water EM122 family
    "em122":  [(2000, 25.0), (4000, 50.0), (6500, 100.0)],
    "em120":  [(2000, 25.0), (4000, 50.0), (6500, 100.0)],
    "em302":  [(1500, 15.0), (3500, 35.0), (5500, 60.0)],
    "em304":  [(1500, 15.0), (3500, 35.0), (5500, 60.0)],
    # Mid-water EM710 family
    "em710":  [(200, 5.0), (800, 10.0), (1500, 20.0)],
    "em712":  [(200, 5.0), (800, 10.0), (1500, 20.0)],
    # Shallow EM2040 family
    "em2040": [(50, 1.0), (200, 3.0), (500, 8.0)],
    # SeaBeam family
    "seabeam 2112": [(2000, 50.0), (4000, 100.0)],
    "seabeam 2000": [(2000, 50.0), (4000, 100.0)],
    "seabeam 1050": [(200, 5.0), (800, 15.0)],
    "atlas hydrosweep": [(2000, 30.0), (4000, 60.0)],
    "kongsberg em": [(2000, 25.0), (4000, 50.0)],  # last-resort EM*
}


def _band_lookup(sonar: str, depth_m: float | None) -> tuple[float | None, str]:
    if not sonar:
        return None, "unknown"
    s = sonar.lower()
    table = None
    for key, t in _SONAR_GSD.items():
        if key in s:
            table = t
            break
    if table is None:
        return None, "unknown"
    if depth_m is None:
        # Pick the median band as default
        mid = table[len(table) // 2]
        return float(mid[1]), "estimated"
    d = abs(depth_m)
    for band_d, gsd in table:
        if d <= band_d:
            return float(gsd), "estimated"
    return float(table[-1][1]), "estimated"


def fetch_geoportal_resolution(cruise_id: str, cache_dir: Path) -> float | None:
    """Try the NCEI Geoportal ISO endpoint and parse out a single GSD."""
    if not cruise_id:
        return None
    cache = cache_dir / f"{cruise_id}.json"
    if cache.exists():
        data = json.loads(cache.read_text())
    else:
        url = _GEOPORTAL_BASE + cruise_id + "_Multibeam"
        try:
            r = requests.get(url, params={"f": "json"}, timeout=5, headers=_HEADERS)
            time.sleep(_THROTTLE)
            data = r.json() if r.status_code == 200 else {"_status": r.status_code}
        except Exception as e:
            data = {"_error": str(e)[:120]}
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data))
    # Heuristic resolution extraction: look for spatialResolution / distance.
    if not isinstance(data, dict):
        return None
    for key in ("spatialResolution", "spatial_resolution", "resolutionValue",
                "MD_Resolution", "_source"):
        v = data.get(key)
        if v is None:
            continue
        text = json.dumps(v) if not isinstance(v, str) else v
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|meter|metre)\b", text, re.I)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def enrich(lr_gdf: gpd.GeoDataFrame, hr_gdf: gpd.GeoDataFrame,
           cache_dir: Path) -> gpd.GeoDataFrame:
    """Populate ``lr_native_res_est_m`` + ``lr_res_source`` on every LR row.

    Uses the HR depth_range_m for the sonar/depth fallback when the LR row
    has no native depth metadata.
    """
    out = lr_gdf.copy()
    out["lr_res_source"] = "unknown"
    # Existing schema name (catalog.py LR_COLUMNS) is ``native_res_est_m``.
    # Keep using that to stay compatible with the join.
    if "native_res_est_m" not in out.columns:
        out["native_res_est_m"] = None
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Build a quick depth lookup from HR by hr_id_query
    hr_depth = {}
    for _, r in hr_gdf.iterrows():
        d_min = r.get("depth_min_m"); d_max = r.get("depth_max_m")
        if d_min is None or d_max is None:
            continue
        try:
            depth = (float(d_min) + float(d_max)) / 2.0
        except Exception:
            continue
        hr_depth[r["hr_id"]] = depth

    seen_cruises = {}
    for i, r in out.iterrows():
        cruise = r.get("cruise_id") or ""
        if cruise in seen_cruises:
            gsd, source = seen_cruises[cruise]
        else:
            gsd = fetch_geoportal_resolution(cruise, cache_dir)
            source = "geoportal" if gsd is not None else "unknown"
            if gsd is None:
                gsd, source = _band_lookup(r.get("sonar") or "", hr_depth.get(r.get("hr_id_query")))
            seen_cruises[cruise] = (gsd, source)
        out.at[i, "native_res_est_m"] = gsd
        out.at[i, "lr_res_source"] = source
    return out
