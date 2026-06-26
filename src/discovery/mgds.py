"""MGDS (Marine Geoscience Data System) AUV bathymetry harvester.

Uses the FileServer REST API documented at
https://www.marine-geo.org/services/FileServer/wadl.

Two passes:
  1. ``format=data_set`` (~179 datasets) for the survey-family listing
     with DOI, title, description, platform, dates.
  2. ``format=geoms`` (per-file detail) for the actual bounds, native
     resolution, depth range, and the per-file ``data_uid`` needed for
     later download via FileDownloadServer.

The two passes are joined on ``data_set_uid`` so each HR catalog row
represents one mission's gridded-bathymetry product, with the per-file
union footprint and the constituent file IDs as ``file_ids``.

License: MGDS data is generally CC-BY-NC-SA, but we record only what
the metadata declares (often unlabelled).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pyproj
import requests
from shapely.geometry import Polygon, box
from shapely.ops import unary_union, transform

from .catalog import HRRecord


log = logging.getLogger(__name__)

_SERVICE = "https://www.marine-geo.org/services/FileServer"
_NS = {"m": "http://www.marine-geo.org/services/xml/mgdsDataService"}
_THROTTLE = 0.5  # seconds between requests
_RES_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m|meter|metre)(?![a-z])", re.I)


def _fetch_xml(params: dict[str, Any], cache_path: Path | None = None) -> bytes:
    if cache_path and cache_path.exists():
        log.info("cache hit: %s", cache_path)
        return cache_path.read_bytes()
    log.info("MGDS fetch %s", params)
    r = requests.get(_SERVICE, params=params, timeout=120,
                     headers={"User-Agent": "auv-ship-acq/0.1 (Sherlock)"})
    r.raise_for_status()
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(r.content)
    time.sleep(_THROTTLE)
    return r.content


def fetch_data_sets(cache_dir: Path) -> ET.Element:
    body = _fetch_xml(
        {"platform_type": "AUV", "data_type": "Bathymetry", "format": "data_set"},
        cache_dir / "mgds_AUV_Bathymetry_data_set.xml",
    )
    return ET.fromstring(body)


def fetch_geoms(cache_dir: Path) -> ET.Element:
    body = _fetch_xml(
        {"platform_type": "AUV", "data_type": "Bathymetry", "format": "geoms"},
        cache_dir / "mgds_AUV_Bathymetry_geoms.xml",
    )
    return ET.fromstring(body)


# ---------- per-file -> footprint polygon ----------

def _parse_coordinate_type(s: str) -> str | None:
    """Map MGDS 'coordinate_type' strings to an EPSG code (best-effort).

    Examples observed:
      'UTM-10N' -> EPSG:32610
      'UTM-23S' -> EPSG:32723
      'Geographic' -> EPSG:4326
      'Local XY' -> None (no georef)
    """
    if not s:
        return None
    s = s.strip()
    if s.lower() in ("geographic", "wgs84", "epsg:4326"):
        return "EPSG:4326"
    m = re.match(r"UTM[-_ ]?(\d{1,2})\s*([NSns])", s)
    if m:
        zone = int(m.group(1))
        hemi = m.group(2).upper()
        return f"EPSG:{(32600 if hemi == 'N' else 32700) + zone}"
    return None


def _file_polygon(file_el: ET.Element) -> tuple[Polygon | None, str | None]:
    meta = file_el.find("m:metadata", _NS)
    if meta is None:
        return None, None
    coord_type = meta.get("coordinate_type") or ""
    crs = _parse_coordinate_type(coord_type)
    bnd = meta.find("m:bounds", _NS)
    if bnd is None:
        return None, crs
    try:
        w = float(bnd.get("west")); e = float(bnd.get("east"))
        s = float(bnd.get("south")); n = float(bnd.get("north"))
    except (TypeError, ValueError):
        return None, crs
    if not (e > w and n > s):
        return None, crs
    return box(w, s, e, n), crs


def _to_wgs84(geom: Polygon, src_crs: str) -> Polygon:
    """Reproject a polygon to EPSG:4326. Returns the original on failure."""
    if not src_crs or src_crs == "EPSG:4326":
        return geom
    try:
        tr = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True).transform
        return transform(tr, geom)
    except Exception as e:
        log.warning("CRS reproject %s->4326 failed: %s", src_crs, e)
        return geom


# ---------- main harvest ----------

@dataclass
class _DatasetAgg:
    data_set_uid: str
    doi: str = ""
    title: str = ""
    description: str = ""
    platform: str = ""
    cruise_id: str = ""
    start_date: str = ""
    stop_date: str = ""
    file_format: str = ""
    geographic_feature: str = ""
    license: str = ""
    file_uids: list[str] = field(default_factory=list)
    file_polys_4326: list[Polygon] = field(default_factory=list)
    native_crs_set: set[str] = field(default_factory=set)
    file_x_res: list[float] = field(default_factory=list)
    file_min_z: list[float] = field(default_factory=list)
    file_max_z: list[float] = field(default_factory=list)


def harvest(cache_dir: Path) -> list[HRRecord]:
    """Run a full MGDS AUV-bathymetry harvest and return HRRecord objects.

    Idempotent: API responses are cached under ``cache_dir/mgds_*.xml``.
    """
    data_sets_root = fetch_data_sets(cache_dir)
    geoms_root = fetch_geoms(cache_dir)

    # Index dataset-level info by data_set_uid
    aggs: dict[str, _DatasetAgg] = {}
    for ds in data_sets_root.find("m:data_sets", _NS) or []:
        uid = ds.get("uid") or ""
        if not uid:
            continue
        agg = _DatasetAgg(data_set_uid=uid)
        agg.doi = ds.get("data_doi") or ""
        agg.title = ds.get("title") or ""
        agg.file_format = ds.get("general_type") or ""
        desc_el = ds.find("m:description", _NS)
        agg.description = (desc_el.text or "") if desc_el is not None else ""
        ent = ds.find("m:ds_entry", _NS)
        if ent is not None:
            agg.cruise_id = ent.get("id") or ""
            agg.platform = (ent.get("platform_prefix") or "").strip() + " " + (ent.get("platform") or "").strip()
            agg.platform = agg.platform.strip()
            agg.start_date = ent.get("start_date") or ""
            agg.stop_date = ent.get("stop_date") or ""
        gf = ds.find("m:geographic_feature", _NS)
        if gf is not None:
            agg.geographic_feature = (gf.text or "").strip() or gf.get("human_readable") or ""
        ff = ds.find("m:file_format", _NS)
        if ff is not None:
            agg.file_format = ff.get("human_readable") or (ff.text or "") or agg.file_format
        aggs[uid] = agg

    # Walk per-file geoms and accrue per-dataset footprint + resolution.
    files_root = geoms_root.find("m:files", _NS)
    if files_root is None:
        log.warning("MGDS geoms response has no <files>")
    else:
        for f in files_root:
            ds_uid = f.get("data_set_uid") or ""
            f_uid = f.get("data_uid") or ""
            if ds_uid not in aggs:
                # File belongs to a dataset we didn't see in data_set view
                # (probably non-Bathymetry siblings). Skip.
                continue
            agg = aggs[ds_uid]
            agg.file_uids.append(f_uid)
            poly, crs = _file_polygon(f)
            if poly is None:
                continue
            if crs:
                agg.native_crs_set.add(crs)
                poly4326 = _to_wgs84(poly, crs)
                agg.file_polys_4326.append(poly4326)
            grid = f.find("m:metadata/m:grid", _NS)
            if grid is not None:
                try:
                    raw_xres = abs(float(grid.get("x_res")))
                    # If native CRS is geographic (lat/lon), x_res is in
                    # degrees; convert to metres using the file footprint's
                    # mean latitude. Projected CRS already in metres.
                    if crs == "EPSG:4326":
                        # Use the centroid latitude of the file polygon for conversion.
                        lat = (poly.bounds[1] + poly.bounds[3]) / 2.0 if poly else 0.0
                        import math
                        meters_per_deg_lat = 111_132.0
                        # Approximate: 1° lon at lat = 111320 * cos(lat).
                        # Use the smaller of the two to be conservative (so
                        # we don't over-report resolution).
                        m_per_deg = min(meters_per_deg_lat,
                                        111_320.0 * abs(math.cos(math.radians(lat))))
                        raw_xres = raw_xres * m_per_deg
                    agg.file_x_res.append(raw_xres)
                except (TypeError, ValueError):
                    pass
                try:
                    agg.file_min_z.append(float(grid.get("min_z")))
                except (TypeError, ValueError):
                    pass
                try:
                    agg.file_max_z.append(float(grid.get("max_z")))
                except (TypeError, ValueError):
                    pass

    # Convert to HRRecords. Skip datasets with no usable footprint or only
    # raw / non-grid formats — but be permissive (the human triages).
    out: list[HRRecord] = []
    now = datetime.now(timezone.utc).isoformat()
    for uid, agg in aggs.items():
        if not agg.file_polys_4326:
            log.info("MGDS %s (%s) skipped: no footprint", uid, agg.title[:60])
            continue
        footprint = unary_union(agg.file_polys_4326)
        if footprint.is_empty:
            continue
        native_res = (sum(agg.file_x_res) / len(agg.file_x_res)) if agg.file_x_res else _parse_res_from_description(agg.description, agg.title)
        depth_min = min(agg.file_min_z) if agg.file_min_z else None
        depth_max = max(agg.file_max_z) if agg.file_max_z else None
        sonar = _parse_sonar(agg.description)
        out.append(HRRecord(
            hr_id=f"MGDS:{uid}",
            source="MGDS",
            doi=agg.doi,
            source_uid=uid,
            title=agg.title,
            platform=_parse_auv_platform(agg.description, agg.platform),
            platform_type="AUV",
            sonar=sonar,
            native_res_m=float(native_res) if native_res else None,
            native_crs=next(iter(agg.native_crs_set), "") if agg.native_crs_set else "",
            format=agg.file_format,
            file_ids=",".join(agg.file_uids),
            license="MGDS (per-record; typically CC-BY-NC-SA)",
            cruise_id=agg.cruise_id,
            start_date=agg.start_date,
            stop_date=agg.stop_date,
            depth_min_m=float(depth_min) if depth_min is not None else None,
            depth_max_m=float(depth_max) if depth_max is not None else None,
            geographic_feature=agg.geographic_feature,
            sibling_dois="",  # MGDS data_set is already deduped
            description=agg.description[:1000],
            harvested_at_utc=now,
            geometry=footprint,
        ))
    log.info("MGDS harvest: %d records", len(out))
    return out


_AUV_NAMES = ("ABE", "Sentry", "REMUS", "ABYSS", "MAUV", "AsterX", "IDEFIX", "MBARI AUV")


def _parse_auv_platform(description: str, platform_fallback: str) -> str:
    """Pull a more specific AUV name from the description if present."""
    for n in _AUV_NAMES:
        if re.search(rf"\bAUV\s+{re.escape(n)}\b", description, re.I) or re.search(rf"\b{re.escape(n)}\s+AUV\b", description, re.I) or re.search(rf"\b{re.escape(n)}\b", description, re.I):
            return n
    return platform_fallback or "AUV"


def _parse_sonar(description: str) -> str:
    """Sonar names from the description text."""
    for pat in (r"Reson\s+SeaBat\s+[\w-]+", r"Reson\s+\d+", r"Kongsberg\s+EM\d+",
                r"Imagenex\s+\d+", r"Simrad\s+EM\s*\d+"):
        m = re.search(pat, description, re.I)
        if m:
            return m.group(0)
    return ""


def _parse_res_from_description(description: str, title: str) -> float | None:
    """Last-resort native-resolution parser from text descriptions."""
    for txt in (title, description):
        for m in _RES_RE.finditer(txt or ""):
            try:
                val = float(m.group(1))
                if 0.1 <= val <= 200:  # plausible bathy resolution
                    return val
            except ValueError:
                continue
    return None
