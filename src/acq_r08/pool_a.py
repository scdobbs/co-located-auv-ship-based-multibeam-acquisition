"""ACQ-R08 Pool A — near-bottom (AUV / ROV / HOV) high-resolution bathymetry grids, metadata only.

Sources (current catalogs, fresh cache under $GROUP_SCRATCH discovery_cache/acq_r08_<date>/):
  * MGDS FileServer (the repo's harvester, unchanged except an optional platform_type: AUV, ROV, HOV);
  * PANGAEA Elasticsearch (the ACQ-R02 harvester + classifiers, new cache);
  * DataCite REST (SEANOE 10.17882, BODC 10.5285, USGS 10.5066 and any other repository with a geoLocation box);
  * USGS ScienceBase catalog API;
  * NCEI multibeam footprint layer (full pull, paged) — both the ship LR pool and any vehicle surveys archived there.
Nothing is downloaded, opened or rendered: the blindness guard in ``common`` refuses raster opens and data URLs.

Outputs: reports_post_grl_review/ACQ-R08/pool_a/{hr_records.csv, candidates.csv, funnel.json, hr_footprints.gpkg}.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import box, shape

from src.acq_r08 import common as K
from src.acq_r01 import common as C
from src.discovery import catalog as cat, mgds, platform_filter as pf, dedupe as dedupe_mod, geoportal
from src.discovery.raw_lr_dryrun import data_dir_from_iso, resolve_data_dir, size_cruise
from src.acq_r01 import pangaea_discovery as PD

log = logging.getLogger("acq_r08.pool_a")
OUT = K.OUT / "pool_a"
NCEI_LAYER = "https://gis.ngdc.noaa.gov/arcgis/rest/services/multibeam_footprints/MapServer/0"
PAGE = 500
GRID_FMT_RE = re.compile(r"grid|netcdf|esri|ascii|gmt|geotiff$|float|bag|xyz grid|surfer|arc", re.I)
RENDER_FMT_RE = re.compile(r"raster|image|map|pdf|kml|jpeg|jpg|png|tiff? \(raster\)|hillshade", re.I)
RAW_TITLE_RE = re.compile(r"\braw\b|navigation and swath|swath bathymetry data|\.all\b|soundings|point cloud", re.I)
GRID_TITLE_RE = re.compile(r"grid|gridded|processed|DEM|digital elevation|raster|GeoTIFF|netCDF|mosaic|resolution|bathymetric map", re.I)
NONBATHY_RE = re.compile(r"magnetic|magnetometer|photo|image mosaic|photomosaic|video|sidescan|side-scan|sub-?bottom|chirp|CTD|"
                         r"turbidity|water column|benchmark|software|MB-System|navigation only|track line|backscatter (?:data|only|mosaic)",
                         re.I)
DATACITE_QUERIES = ["AUV bathymetry", "near-bottom bathymetry", '"autonomous underwater vehicle" bathymetry', "Sentry bathymetry",
                    "REMUS bathymetry", "HUGIN bathymetry", "AsterX bathymetry", "Abyss bathymetry", "MARUM-SEAL bathymetry",
                    '"mapping AUV" bathymetry', "ROV bathymetry grid", "SuBastian bathymetry", "Hercules bathymetry",
                    "Jason bathymetry grid", "Alvin bathymetry grid", "AUV multibeam grid"]
SCIENCEBASE_QUERIES = ["AUV bathymetry", '"autonomous underwater vehicle" bathymetry', "Sentry bathymetry", "near-bottom bathymetry",
                       "REMUS bathymetry", "MBARI AUV", "AUV multibeam"]
SKIP_PUBLISHER_RE = re.compile(r"Marine Geoscience Data System|MGDS|PANGAEA", re.I)
PRIOR_DESIGNATED = {"PANGAEA:884112": "ACQ-R02 unit pu00 (Venere, M112/1) designated development, not acquired (M112 host throttling)",
                    "PANGAEA:958275": "ACQ-R02 unit pu03 (Kolumbo, POS510) designated confirmatory, LR restricted (401)",
                    "MGDS:30368": "ACQ-R01 unit nu02 (RP15DI86) designated development, legacy swath format pending"}
# HR acquisition cruises known from this repo's own September records (metadata, not data): the Venere MARUM-SEAL grid
# (884112) was flown from METEOR M112 / POSEIDON POS499 (REPORT_ACQ-R02 §4; the PANGAEA record itself names no campaign)
PRIOR_CRUISE = {"PANGAEA:884112": ["M112", "M112/1", "POS499"]}
# PANGAEA ids / DOIs of the corpus provider HR (DISCOL, CCZ, TAG) and their ship grids
CORPUS_PANGAEA = {"905580", "915765", "899415", "905579", "915764", "899408", "892662"}


# ----------------------------------------------------------------------------------------------------------------- #
# Harvests
# ----------------------------------------------------------------------------------------------------------------- #
def harvest_mgds() -> gpd.GeoDataFrame:
    recs = []
    for pt in ("AUV", "ROV", "HOV"):
        r = mgds.harvest(K.CACHE / "mgds", pt)
        log.info("MGDS %s: %d records", pt, len(r)); recs += r
    cat.write_hr_catalog(recs, OUT / "hr_catalog_mgds_raw.gpkg")
    g = gpd.read_file(OUT / "hr_catalog_mgds_raw.gpkg", layer="hr")
    # record-level classification (recording, not gating) — the repo's platform filter
    cls = [pf.classify(r.platform or "", r.sonar or "", r.description or "", r.native_res_m) for _, r in g.iterrows()]
    g["is_auv_grid"] = [c[0] for c in cls]; g["hr_class"] = [c[1] for c in cls]; g["is_non_bathy"] = [c[1] == "non_bathy" for c in cls]
    g["footprint_km2"] = [K.area_km2(x) for x in g.geometry]
    g["footprint_suspect"] = [pf.footprint_suspect(a, r, True) for a, r in zip(g.footprint_km2, g.native_res_m)]
    g["geometry_source"] = "metadata_bbox"
    g["file_bytes"] = g.source_uid.map(mgds_sizes()).fillna(0).astype(float)
    return g


def mgds_sizes() -> dict:
    out = {}
    ns = {"m": "http://www.marine-geo.org/services/xml/mgdsDataService"}
    for pt in ("AUV", "ROV", "HOV"):
        p = K.CACHE / "mgds" / f"mgds_{pt}_Bathymetry_geoms.xml"
        if not p.exists():
            continue
        root = ET.fromstring(p.read_bytes()); files = root.find("m:files", ns)
        for f in (files if files is not None else []):
            fi = f.find("m:file_info", ns)
            try:
                out[f.get("data_set_uid")] = out.get(f.get("data_set_uid"), 0) + int((fi.get("data_file_size") if fi is not None else 0) or 0)
            except ValueError:
                pass
    return out


def mgds_format_class(fmt: str, title: str) -> str:
    f = fmt or ""; t = title or ""
    if RAW_TITLE_RE.search(t) and not GRID_TITLE_RE.search(t):
        return "raw_swath"
    if RENDER_FMT_RE.search(f) and not re.search(r"grid|netcdf|ascii|gmt", f, re.I):
        return "render"
    if GRID_FMT_RE.search(f) or GRID_TITLE_RE.search(t):
        return "grid"
    return "unknown"


def harvest_pangaea() -> tuple[pd.DataFrame, pd.DataFrame]:
    PD.CACHE = K.CACHE / "pangaea"           # fresh cache; the ACQ-R02 queries and classifiers unchanged
    auv_raw = PD.harvest(PD.AUV_QUERIES, "AUV"); ship_raw = PD.harvest(PD.SHIP_QUERIES, "ship")
    auv = PD.classify_auv(auv_raw); ship = PD.classify_ship(ship_raw)
    auv.attrs["n_hits"] = int(len(auv_raw)); ship.attrs["n_hits"] = int(len(ship_raw))
    auv.to_csv(OUT / "pangaea_auv_datasets.csv", index=False); ship.to_csv(OUT / "pangaea_ship_datasets.csv", index=False)
    return auv, ship


def _dc_all(query: str, extra: dict | None = None) -> list[dict]:
    cache = K.CACHE / "datacite" / (re.sub(r"[^A-Za-z0-9]+", "_", query + json.dumps(extra or {}))[:90] + ".json")
    if cache.exists():
        return json.loads(cache.read_text())
    out, cursor = [], "1"
    for _ in range(40):
        params = {"query": query, "page[size]": 100, "page[cursor]": cursor}; params.update(extra or {})
        r = requests.get("https://api.datacite.org/dois", params=params, headers=K.UA, timeout=120)
        if r.status_code != 200:
            log.warning("DataCite %s -> %s", query, r.status_code); break
        j = r.json(); out += j.get("data", [])
        nxt = j.get("links", {}).get("next")
        if not nxt or not j.get("data"):
            break
        m = re.search(r"page%5Bcursor%5D=([^&]+)", nxt) or re.search(r"page\[cursor\]=([^&]+)", nxt)
        if not m:
            break
        cursor = requests.utils.unquote(m.group(1)); time.sleep(0.4)
    cache.parent.mkdir(parents=True, exist_ok=True); cache.write_text(json.dumps(out))
    return out


def harvest_datacite() -> pd.DataFrame:
    rows, seen = [], set()
    for q in DATACITE_QUERIES:
        for d in _dc_all(q):
            a = d["attributes"]; doi = a["doi"].lower()
            if doi in seen:
                continue
            seen.add(doi)
            pub = a.get("publisher"); pub = pub if isinstance(pub, str) else (pub or {}).get("name", "")
            title = (a.get("titles") or [{}])[0].get("title", "")
            desc = " ".join(x.get("description", "") for x in (a.get("descriptions") or []))
            geo = a.get("geoLocations") or []
            bbox = None
            for g in geo:
                b = g.get("geoLocationBox")
                if b:
                    try:
                        bbox = (float(b["westBoundLongitude"]), float(b["southBoundLatitude"]), float(b["eastBoundLongitude"]), float(b["northBoundLatitude"]))
                    except Exception:
                        bbox = None
                    if bbox:
                        break
            pt = None
            if bbox is None:
                for g in geo:
                    p = g.get("geoLocationPoint")
                    if p:
                        try:
                            pt = (float(p["pointLongitude"]), float(p["pointLatitude"]))
                        except Exception:
                            pt = None
                        if pt:
                            break
            rights = "; ".join(x.get("rights", "") or x.get("rightsIdentifier", "") for x in (a.get("rightsList") or []))
            sizes = "; ".join(a.get("sizes") or [])
            rows.append({"doi": doi, "publisher": pub, "title": title, "description": desc[:2000], "year": a.get("publicationYear"),
                         "created": (a.get("created") or "")[:10], "rights": rights, "sizes": sizes, "formats": "; ".join(a.get("formats") or []),
                         "has_box": bbox is not None, "has_point": pt is not None, "bbox": json.dumps(bbox) if bbox else "", "point": json.dumps(pt) if pt else "",
                         "resource_type": (a.get("types") or {}).get("resourceTypeGeneral", ""), "query": q})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "datacite_hits.csv", index=False)
    return df


def classify_datacite(df: pd.DataFrame) -> pd.DataFrame:
    t = df.title.fillna("") + " | " + df.description.fillna("")
    keep = (t.str.contains(K.VEHICLE_RE) & t.str.contains(r"bathymetr|multibeam|MBES|seafloor topography", case=False)
            & df.title.str.contains(GRID_TITLE_RE) & ~df.title.str.contains(NONBATHY_RE)
            & ~df.publisher.fillna("").str.contains(SKIP_PUBLISHER_RE) & ~df.doi.str.contains(r"10\.26022|10\.60521|10\.1594/ieda|10\.1594/pangaea")
            & df.resource_type.isin(["Dataset", "Collection", "Other", ""]))
    d = df[keep].copy()
    res = t[d.index].str.extract(PD.RES_RE)
    d["hr_res_m"] = pd.to_numeric(res[0].fillna(res[1]).fillna(res[2]), errors="coerce")
    dep = t[d.index].str.extract(PD.DEPTH_RE)
    d["depth_min_m"] = pd.to_numeric(dep[0].fillna(dep[2]).fillna(dep[3]), errors="coerce")
    d["depth_max_m"] = pd.to_numeric(dep[1].fillna(dep[2]).fillna(dep[3]), errors="coerce")
    d["is_raw"] = d.title.str.contains(RAW_TITLE_RE) & ~d.title.str.contains(r"grid|processed|resolution", case=False)
    return d


def harvest_sciencebase() -> pd.DataFrame:
    rows, seen = [], set()
    for q in SCIENCEBASE_QUERIES:
        cache = K.CACHE / "sciencebase" / (re.sub(r"[^A-Za-z0-9]+", "_", q) + ".json")
        if cache.exists():
            j = json.loads(cache.read_text())
        else:
            r = requests.get("https://www.sciencebase.gov/catalog/items", params={"q": q, "format": "json", "max": 100,
                             "fields": "title,summary,spatial,dates,identifiers,webLinks,files,rights"}, headers=K.UA, timeout=90)
            j = r.json() if r.status_code == 200 else {"total": None, "items": [], "_status": r.status_code}
            cache.parent.mkdir(parents=True, exist_ok=True); cache.write_text(json.dumps(j)); time.sleep(0.4)
        for it in j.get("items", []):
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            bb = (it.get("spatial") or {}).get("boundingBox") or {}
            bbox = (bb.get("minX"), bb.get("minY"), bb.get("maxX"), bb.get("maxY")) if bb else None
            doi = ""
            for ident in it.get("identifiers") or []:
                if "doi" in str(ident.get("scheme", "")).lower() or str(ident.get("key", "")).startswith("10."):
                    doi = ident.get("key", "")
            files = it.get("files") or []
            rows.append({"sb_id": it["id"], "doi": doi.replace("https://doi.org/", "").lower(), "title": it.get("title", ""), "summary": (it.get("summary") or "")[:1500],
                         "bbox": json.dumps(bbox) if bbox and None not in bbox else "", "n_files": len(files),
                         "file_bytes": sum(int(f.get("size") or 0) for f in files), "rights": it.get("rights", ""), "query": q, "total_for_query": j.get("total")})
    df = pd.DataFrame(rows); df.to_csv(OUT / "sciencebase_hits.csv", index=False)
    return df


def refresh_ncei_footprints() -> gpd.GeoDataFrame:
    """Full pull of the NCEI multibeam footprint layer (polygons; 500 per page — the service answers HTTP 500 to
    2,000-feature pages with geometry, checked 2026-10-12)."""
    p = K.CACHE / "ncei" / "ncei_all_footprints.geojson"
    if p.exists():
        return gpd.read_file(p)
    feats, off = [], 0
    while True:
        params = {"where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": "4326", "f": "geojson",
                  "resultOffset": off, "resultRecordCount": PAGE}
        for attempt in range(4):
            try:
                r = requests.get(f"{NCEI_LAYER}/query", params=params, headers=K.UA, timeout=300); r.raise_for_status()
                j = json.loads(r.text); break
            except Exception as e:
                log.warning("NCEI page %d attempt %d: %s", off, attempt, e); time.sleep(5 * (attempt + 1)); j = None
        if not j:
            raise RuntimeError("NCEI footprint layer unreachable")
        f = j.get("features", []); feats += f
        if len(f) < PAGE:
            break
        off += PAGE; time.sleep(0.5)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    return gpd.read_file(p)


# ----------------------------------------------------------------------------------------------------------------- #
# HR record normalisation
# ----------------------------------------------------------------------------------------------------------------- #
def _norm(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


CRUISE_TOKEN_RE = re.compile(r"\b([A-Z]{1,4}[a-z]?\d{2,6}(?:[A-Z]{1,2}\d{0,2})?(?:[-/]\d{1,2}[A-Za-z]?)?)\b")
NOT_CRUISE_RE = re.compile(r"^(EM|ME|SB|HS|GPS|UTM|EPSG|WGS|NAD|M3|P\d|D\d|V\d|S\d|G\d|T\d|R\d|L\d|N\d|K\d|H\d|ISO)", re.I)


def cruise_tokens(*texts) -> list[str]:
    """Cruise / expedition identifiers named in catalog text (MV1205, AT26-09, KN210-05, TN365, FKt230918, SO242/1, M112/1,
    POS510, MSM16-2, DY152 ...). The MGDS data_set view carries no cruise id in the current XML (checked 2026-10-13)."""
    out = []
    for t in texts:
        for m in CRUISE_TOKEN_RE.findall(str(t or "")):
            if NOT_CRUISE_RE.match(m) or re.fullmatch(r"[A-Z]?\d{4}", m) or len(m) < 4:
                continue
            if m not in out:
                out.append(m)
    return out


def hr_records(mg: gpd.GeoDataFrame, pan: pd.DataFrame, dc: pd.DataFrame, sb: pd.DataFrame, ncei: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    rows = []
    # --- MGDS (deduped by the repo's sibling collapse; grid formats preferred inside a cluster)
    mg2 = dedupe_mod.dedupe(mg)
    fmt_of = dict(zip(mg.hr_id, mg.format)); title_of = dict(zip(mg.hr_id, mg.title)); doi_of = dict(zip(mg.hr_id, mg.doi))
    for _, r in mg2.iterrows():
        fc = mgds_format_class(r.format, r.title)
        sibs = [s for s in str(r.get("sibling_hr_ids") or "").split(";") if s]
        chosen, chosen_fmt = r.hr_id, r.format
        if fc != "grid":
            for s in sibs:
                if mgds_format_class(fmt_of.get(s, ""), title_of.get(s, "")) == "grid":
                    chosen, chosen_fmt, fc = s, fmt_of.get(s), "grid"; break
        vehicle = "AUV" if r.hr_class == "auv" else str(r.platform_type or "")
        rows.append({"pool": "A", "source": "MGDS", "hr_id": r.hr_id, "hr_id_grid_product": chosen, "doi": r.doi or doi_of.get(chosen, ""),
                     "title": r.title, "platform": r.platform, "vehicle_class": vehicle, "hr_cruise": r.cruise_id or "",
                     "hr_res_m": float(r.native_res_m) if pd.notna(r.native_res_m) else None,
                     "hr_res_source": "MGDS per-file grid metadata (x_res)" if pd.notna(r.native_res_m) else "not stated",
                     "depth_min_m": _depth(r.depth_min_m), "depth_max_m": _depth(r.depth_max_m),
                     "depth_source": "MGDS per-file grid metadata (min_z/max_z)" if _depth(r.depth_max_m) is not None else "not stated (or nodata value in record)",
                     "year": str(r.start_date or "")[:4], "format": chosen_fmt, "format_class": fc, "is_non_bathy": bool(r.is_non_bathy),
                     "license": r.license or "", "size_hr_gb": round(float(r.file_bytes or 0) / 1e9, 3) if pd.notna(r.file_bytes) else None,
                     "footprint_kind": "catalog polygon (MGDS per-file bounds union)", "footprint_suspect": bool(r.footprint_suspect),
                     "text": f"{r.title} {r.geographic_feature or ''} {str(r.description or '')[:600]}", "region_hint": r.geographic_feature or "",
                     "siblings": ";".join(sibs), "geometry": r.geometry})
    # --- PANGAEA
    for _, r in pan.iterrows():
        rows.append({"pool": "A", "source": "PANGAEA", "hr_id": f"PANGAEA:{r.id}", "hr_id_grid_product": f"PANGAEA:{r.id}", "doi": r.doi,
                     "title": r.title, "platform": r.hr_platform, "vehicle_class": "AUV", "hr_cruise": str(r.campaigns or "").split(";")[0],
                     "hr_res_m": float(r.hr_res_m) if pd.notna(r.hr_res_m) else None, "hr_res_source": "title/abstract regex" if pd.notna(r.hr_res_m) else "not stated",
                     "depth_min_m": float(r.depth_min_m) if pd.notna(r.depth_min_m) else None, "depth_max_m": float(r.depth_max_m) if pd.notna(r.depth_max_m) else None,
                     "depth_source": "title/abstract regex" if pd.notna(r.depth_max_m) else "not stated", "year": str(r.start or "")[:4],
                     "format": "PANGAEA dataset (grid files)", "format_class": "raw_swath" if bool(r.hr_raw_only) else "grid", "is_non_bathy": False,
                     "license": "PANGAEA CC-BY-4.0 (default licence of the record)", "size_hr_gb": None,
                     "footprint_kind": "bbox (PANGAEA record)", "footprint_suspect": bool(r.bbox_deg2 > 0.05),
                     "text": f"{r.title} {str(r.abstract or '')[:600]}", "region_hint": "", "siblings": "", "campaigns": r.campaigns,
                     "geometry": box(r.west, r.south, r.east, r.north) if r.west != r.east and r.south != r.north else box(r.west - 0.005, r.south - 0.005, r.east + 0.005, r.north + 0.005)})
    # --- DataCite-indexed repositories (SEANOE, BODC, USGS, other)
    for _, r in dc.iterrows():
        if r.bbox:
            w, s, e, n = json.loads(r.bbox); kind = "bbox (DataCite geoLocationBox)"
            geom = box(w, s, e, n) if (w != e and s != n) else box(w - 0.005, s - 0.005, e + 0.005, n + 0.005)
        elif r.point:
            x, y = json.loads(r.point); geom = box(x - 0.01, y - 0.01, x + 0.01, y + 0.01); kind = "point (DataCite geoLocationPoint, ±0.01°)"
        else:
            geom, kind = None, "none"
        src = "SEANOE" if r.doi.startswith("10.17882") else ("BODC" if r.doi.startswith("10.5285") else ("USGS" if r.doi.startswith("10.5066") else f"other ({r.publisher})"))
        rows.append({"pool": "A", "source": src, "hr_id": f"DOI:{r.doi}", "hr_id_grid_product": f"DOI:{r.doi}", "doi": r.doi, "title": r.title,
                     "platform": (K.VEHICLE_RE.search(r.title + " " + r.description) or [""])[0] if K.VEHICLE_RE.search(r.title + " " + r.description) else "",
                     "vehicle_class": "near-bottom vehicle", "hr_cruise": "",
                     "hr_res_m": float(r.hr_res_m) if pd.notna(r.hr_res_m) else None, "hr_res_source": "title/abstract regex" if pd.notna(r.hr_res_m) else "not stated",
                     "depth_min_m": float(r.depth_min_m) if pd.notna(r.depth_min_m) else None, "depth_max_m": float(r.depth_max_m) if pd.notna(r.depth_max_m) else None,
                     "depth_source": "title/abstract regex" if pd.notna(r.depth_max_m) else "not stated", "year": str(r.year or ""),
                     "format": r.formats or "", "format_class": "raw_swath" if bool(r.is_raw) else "grid", "is_non_bathy": False,
                     "license": r.rights or "", "size_hr_gb": _size_gb(r.sizes), "footprint_kind": kind, "footprint_suspect": (K.area_km2(geom) > 60) if geom is not None else True,
                     "text": f"{r.title} {r.description[:600]}", "region_hint": "", "siblings": "", "geometry": geom})
    # --- ScienceBase
    for _, r in sb.iterrows():
        t = f"{r.title} {r.summary}"
        if not (K.VEHICLE_RE.search(t) and re.search(r"bathymetr|multibeam", t, re.I)):
            continue
        if r.bbox:
            w, s, e, n = json.loads(r.bbox); geom = box(w, s, e, n)
        else:
            geom = None
        res = re.search(PD.RES_RE, t); dep = re.search(PD.DEPTH_RE, t)
        rows.append({"pool": "A", "source": "ScienceBase", "hr_id": f"SB:{r.sb_id}", "hr_id_grid_product": f"SB:{r.sb_id}", "doi": r.doi, "title": r.title,
                     "platform": (K.VEHICLE_RE.search(t) or [""])[0], "vehicle_class": "near-bottom vehicle", "hr_cruise": "",
                     "hr_res_m": float(next((g for g in res.groups() if g), None)) if res else None, "hr_res_source": "title/summary regex" if res else "not stated",
                     "depth_min_m": None, "depth_max_m": float(next((g for g in dep.groups() if g), None)) if dep else None,
                     "depth_source": "title/summary regex" if dep else "not stated", "year": "", "format": "", "format_class": "grid",
                     "is_non_bathy": False, "license": r.rights or "USGS data release (public domain)", "size_hr_gb": round(float(r.file_bytes) / 1e9, 3) if r.file_bytes else None,
                     "footprint_kind": "bbox (ScienceBase spatial)", "footprint_suspect": (K.area_km2(geom) > 60) if geom is not None else True,
                     "text": t, "region_hint": "", "siblings": "", "geometry": geom})
    # --- NCEI: vehicle surveys archived in the multibeam database (raw swath, not grids — recorded for the funnel)
    veh = ncei[(ncei.PLATFORM.fillna("") + " " + ncei.INSTRUMENT.fillna("")).str.contains(r"\bAUV\b|\bROV\b|Sentry|REMUS|HUGIN|Jason|Alvin|glider", case=False)]
    for _, r in veh.iterrows():
        rows.append({"pool": "A", "source": "NCEI_MBBDB", "hr_id": f"NCEI:{r.SURVEY_ID}", "hr_id_grid_product": "", "doi": "", "title": f"NCEI multibeam survey {r.SURVEY_ID} ({r.PLATFORM}, {r.INSTRUMENT})",
                     "platform": r.PLATFORM, "vehicle_class": "vehicle (NCEI archive)", "hr_cruise": r.SURVEY_ID, "hr_res_m": None, "hr_res_source": "not stated (raw swath archive)",
                     "depth_min_m": None, "depth_max_m": None, "depth_source": "not stated", "year": str(r.SURVEY_YEAR or "")[:4], "format": "raw swath",
                     "format_class": "raw_swath", "is_non_bathy": False, "license": "NOAA NCEI public domain", "size_hr_gb": None,
                     "footprint_kind": "catalog polygon (NCEI footprint)", "footprint_suspect": False, "text": "", "region_hint": "", "siblings": "", "geometry": r.geometry})
    g = gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs="EPSG:4326")
    toks = []
    for _, r in g.iterrows():
        t = cruise_tokens(r.hr_cruise, r.get("campaigns", ""), r.title, r.text) + PRIOR_CRUISE.get(r.hr_id, [])
        toks.append(";".join(dict.fromkeys(t)))
    g["hr_cruise_tokens"] = toks
    g["hr_cruise"] = [r.hr_cruise if str(r.hr_cruise or "").strip() and str(r.hr_cruise) != "nan" else (t.split(";")[0] if t else "") for (_, r), t in zip(g.iterrows(), toks)]
    g["setting"] = [K.setting_of(f"{r.text} {r.region_hint}") for _, r in g.iterrows()]
    g["lon"] = [x.centroid.x if x is not None and not x.is_empty else None for x in g.geometry]
    g["lat"] = [x.centroid.y if x is not None and not x.is_empty else None for x in g.geometry]
    g["basin"] = [K.basin(a, b) if a is not None else "" for a, b in zip(g.lon, g.lat)]
    g["hr_footprint_km2"] = [round(K.area_km2(x), 2) if x is not None else None for x in g.geometry]
    rel = [K.releasable_of(x) for x in g.license]
    g["releasable"] = [x[0] for x in rel]; g["releasable_note"] = [x[1] for x in rel]
    g["prior_exposure"] = g.hr_id.map(PRIOR_DESIGNATED).fillna("")
    return g


def _depth(z):
    """abs(z) when 0 < |z| <= 11,000 m, else None (MGDS records carry nodata values such as 99999)."""
    try:
        v = abs(float(z))
    except (TypeError, ValueError):
        return None
    return v if 0 < v <= 11000 and math.isfinite(v) else None


def _size_gb(sizes: str):
    if not sizes:
        return None
    m = re.search(r"([\d.]+)\s*(GB|MB|KB|TB|bytes?)", str(sizes), re.I)
    if not m:
        return None
    v = float(m.group(1)); u = m.group(2).upper()
    return round(v * {"TB": 1000, "GB": 1, "MB": 1e-3, "KB": 1e-6, "BYTE": 1e-9, "BYTES": 1e-9}.get(u, 1), 3)


# ----------------------------------------------------------------------------------------------------------------- #
# §1 exclusions + §3 estimates
# ----------------------------------------------------------------------------------------------------------------- #
def corpus_identity(m: pd.DataFrame) -> tuple[set, set]:
    ids = set(); dois = set()
    for pid in m.pair_id:
        mid = K.mgds_id_of_pair(pid)
        if mid:
            ids.add(mid)
    for d in list(m.hr_doi.dropna()) + list(m.hr_superseded_doi.dropna()):
        if d:
            dois.add(str(d).replace("https://doi.org/", "").lower())
    ids |= {f"PANGAEA:{x}" for x in CORPUS_PANGAEA}
    return ids, dois


def screen(hr: gpd.GeoDataFrame, ncei: gpd.GeoDataFrame, pan_ship: pd.DataFrame, excl: gpd.GeoDataFrame, sept_rejected_ids: set,
           pool_c_ids: dict) -> pd.DataFrame:
    m = K.load_manifest_v21(); corpus_ids, corpus_dois = corpus_identity(m)
    corpus_hr_cruises = {_norm(x) for x in m.cruise_id.dropna()} | {_norm(x) for x in m.lr_cruise.dropna()}
    ships = ncei[~(ncei.PLATFORM.fillna("") + " " + ncei.INSTRUMENT.fillna("")).str.contains(r"\bAUV\b|\bROV\b|Sentry|REMUS|HUGIN|Jason|Alvin|glider", case=False)].copy()
    ships["cruise_norm"] = ships.SURVEY_ID.map(_norm)
    sidx = ships.sindex
    rows = []
    for _, h in hr.iterrows():
        rec = {k: h[k] for k in hr.columns if k != "geometry"}
        g = h.geometry
        rec["excluded_by"] = ""; rec["exclusion_detail"] = ""; rec["pool_eligible"] = True
        # pool definition: a near-bottom bathymetry *grid*
        if h.is_non_bathy:
            rec["pool_eligible"] = False; rec["not_eligible_reason"] = "non-bathymetry product (sidescan / sub-bottom / magnetics)"
        elif h.format_class == "raw_swath":
            rec["pool_eligible"] = False; rec["not_eligible_reason"] = "raw swath / soundings only (no gridded product in the record)"
        elif h.format_class == "render":
            rec["pool_eligible"] = False; rec["not_eligible_reason"] = "render only (image GeoTIFF / map), no elevation grid sibling"
        elif g is None or g.is_empty:
            rec["pool_eligible"] = False; rec["not_eligible_reason"] = "no footprint in the catalog record"
        else:
            rec["not_eligible_reason"] = ""
        if g is not None and not g.is_empty:
            ref, kind, km, over = K.nearest_exclusion(g, excl)
            rec["nearest_corpus_ref"] = ref; rec["nearest_corpus_kind"] = kind; rec["nearest_corpus_km"] = km; rec["overlaps_corpus"] = ";".join(over)
            rec["within_50km"] = bool(km is not None and km <= K.FLAG_KM)
            rec["in_cal_dig_area"] = bool(excl[excl.kind == "cal_dig_area"].intersects(g).any())
        else:
            rec.update({"nearest_corpus_ref": None, "nearest_corpus_kind": None, "nearest_corpus_km": None, "overlaps_corpus": "", "within_50km": False, "in_cal_dig_area": False})
        rec["pool_c_rescreen"] = pool_c_ids.get(h.hr_id, "")
        if not rec["pool_eligible"]:
            rows.append(rec); continue
        # §1.1 identity / overlap
        doi = str(h.doi or "").replace("https://doi.org/", "").lower()
        if h.hr_id in corpus_ids or h.hr_id_grid_product in corpus_ids or (doi and doi in corpus_dois):
            rec["excluded_by"] = "1"; rec["exclusion_detail"] = "is a manifest v2.1 pair (HR id / DOI)"
        elif h.hr_id in sept_rejected_ids or h.hr_id_grid_product in sept_rejected_ids:
            rec["excluded_by"] = "1"; rec["exclusion_detail"] = "rejected in ACQ-R01..R07 (HR id)"
        elif any(s in sept_rejected_ids or s in corpus_ids for s in str(h.siblings or "").split(";") if s):
            rec["excluded_by"] = "1"; rec["exclusion_detail"] = "sibling product of a manifest / rejected pair"
        elif rec["overlaps_corpus"]:
            rec["excluded_by"] = "1"; rec["exclusion_detail"] = f"footprint overlaps {rec['overlaps_corpus'][:120]}"
        elif rec["nearest_corpus_km"] is not None and rec["nearest_corpus_km"] < K.EXCL_KM:
            rec["excluded_by"] = "2"; rec["exclusion_detail"] = f"{rec['nearest_corpus_km']} km from {rec['nearest_corpus_ref']}"
        elif rec["in_cal_dig_area"]:
            rec["excluded_by"] = "3"; rec["exclusion_detail"] = "inside the Cal DIG area"
        if rec["excluded_by"]:
            rows.append(rec); continue
        # LR candidates: NCEI ship surveys (raw swath archive) + PANGAEA raw ship datasets (other campaigns)
        cands = []
        htoks = {_norm(x) for x in str(h.get("hr_cruise_tokens") or "").split(";") if x} | ({_norm(h.hr_cruise)} if str(h.hr_cruise or "").strip() else set())
        htoks.discard("")
        for i in sidx.query(g, predicate="intersects"):
            s = ships.iloc[i]
            ov = K.inter_km2(g, s.geometry)
            if ov <= 0:
                continue
            same = _norm(s.SURVEY_ID) in htoks
            comp = bool(K.COMPOSITE_RE.search(f"{s.SURVEY_ID} {s.PLATFORM} {s.SOURCE}"))
            cands.append({"lr_id": f"NCEI:{s.SURVEY_ID}", "lr_cruise": s.SURVEY_ID, "lr_platform": s.PLATFORM, "lr_sonar": s.INSTRUMENT,
                          "lr_year": str(s.SURVEY_YEAR or "")[:4] if pd.notna(s.SURVEY_YEAR) else str(s.START_TIME or "")[:4], "lr_source": "NCEI MBBDB (raw swath)",
                          "overlap_km2": round(ov, 2), "same_cruise": same, "composite": comp, "raw": bool(s.DOWNLOAD_URL),
                          "in_corpus_lr": _norm(s.SURVEY_ID) in corpus_hr_cruises})
        if len(pan_ship):
            b = g.bounds
            sh = pan_ship[(pan_ship.west <= b[2]) & (pan_ship.east >= b[0]) & (pan_ship.south <= b[3]) & (pan_ship.north >= b[1])]
            camp = {c for c in str(h.get("campaigns") or "").split(";") if c}
            for _, s in sh.iterrows():
                if s.bbox_deg2 > 30:
                    continue
                scamp = {c for c in str(s.campaigns).split(";") if c}
                scamp_n = {_norm(c) for c in scamp} | {_norm(c.split("/")[0]) for c in scamp}
                cands.append({"lr_id": f"PANGAEA:{s.id}", "lr_cruise": ";".join(sorted(scamp)) or f"PANGAEA:{s.id}", "lr_platform": s.basis, "lr_sonar": s.sonar or "",
                              "lr_year": str(s.start or "")[:4], "lr_source": f"PANGAEA ({s.lr_kind})", "overlap_km2": round(K.inter_km2(g, box(s.west, s.south, s.east, s.north)), 2),
                              "same_cruise": bool(camp & scamp) or bool(htoks & scamp_n), "composite": bool(K.COMPOSITE_RE.search(s.title)), "raw": s.lr_kind == "pangaea_raw_swath",
                              "in_corpus_lr": bool(scamp & {"SO242/1", "SO268/1", "M127"})})
        rec["n_lr_options"] = len(cands)
        rec["lr_same_cruise_available"] = ";".join(c["lr_cruise"] for c in cands if c["same_cruise"])[:120]
        indep = [c for c in cands if not c["same_cruise"] and not c["composite"] and c["raw"]]
        indep.sort(key=lambda c: -c["overlap_km2"])
        if not cands:
            rec["lr_cruise"] = ""; rec["lr_note"] = "no ship multibeam survey over the footprint (NCEI / PANGAEA)"
        elif not indep:
            if all(c["composite"] for c in cands):
                rec["excluded_by"] = "4"; rec["exclusion_detail"] = "only compilation LR available"
            elif all(c["same_cruise"] or not c["raw"] for c in cands):
                rec["excluded_by"] = "5"; rec["exclusion_detail"] = "the only ship multibeam over the footprint is the HR's own cruise (or has no raw swath)"
            rec["lr_cruise"] = ""
        if rec["excluded_by"]:
            rows.append(rec); continue
        dvals = [abs(v) for v in (K._num(h.depth_min_m), K._num(h.depth_max_m)) if v is not None]
        depth = sum(dvals) / len(dvals) if dvals else None      # mean of the stated range; one bound if the other is nodata
        rec["depth_mean_m"] = depth
        rec["hr_res_m"] = K._num(h.hr_res_m)
        rec["overlap_is_upper_bound"] = str(h.footprint_kind).startswith(("bbox", "point")) or bool(h.footprint_suspect)
        rec["hr_format_issue"] = "" if h.format_class == "grid" else f"format class {h.format_class}"
        # evaluate every independent LR candidate (up to 8 by overlap); keep the one with the best status, then most tiles
        rank = {"in range": 0, "uncertain": 1, "outside range": 2}
        evals = []
        for c in indep[:8]:
            stated = geoportal.fetch_geoportal_resolution(c["lr_cruise"], K.CACHE / "geoportal") if c["lr_source"].startswith("NCEI") else None
            lr_est, method, weak = K.lr_estimate(stated, c["lr_sonar"], depth)
            e = dict(rec); e.update({k: c[k] for k in ("lr_id", "lr_cruise", "lr_platform", "lr_sonar", "lr_year", "lr_source", "overlap_km2")})
            e["lr_raw_available"] = c["raw"]; e["lr_in_corpus_as_lr_cruise"] = c["in_corpus_lr"]; e["overlap_km2_est"] = c["overlap_km2"]
            e["lr_est_m"] = lr_est; e["lr_est_method"] = method; e["lr_est_weak"] = weak
            e.update(K.estimates(rec["hr_res_m"], lr_est, c["overlap_km2"]))
            e["status"], e["status_reason"] = K.status_of(e)
            evals.append(e)
        if evals:
            evals.sort(key=lambda e: (rank.get(e["status"], 3), -(e.get("tiles_est") or 0), -(e.get("overlap_km2") or 0)))
            best = evals[0]; rec = best
            rec["lr_alternatives"] = " | ".join(f"{e['lr_cruise']} ({e['lr_sonar']}, {e['overlap_km2']} km², cells {e['cells_across_est']}, {e['status']})" for e in evals[1:4])
            rec["lr_candidates_evaluated"] = len(evals)
        else:
            rec.update({"lr_id": "", "lr_cruise": "", "lr_platform": "", "lr_sonar": "", "lr_year": "", "lr_source": "", "overlap_km2": None,
                        "lr_raw_available": None, "lr_in_corpus_as_lr_cruise": False, "lr_alternatives": "", "overlap_km2_est": None,
                        "lr_est_m": None, "lr_est_method": "no independent ship cruise", "lr_est_weak": True, "lr_candidates_evaluated": 0})
            rec.update(K.estimates(rec["hr_res_m"], None, None))
            rec["status"], rec["status_reason"] = K.status_of(rec)
        rows.append(rec)
    df = pd.DataFrame(rows)
    for c, v in (("status", ""), ("status_reason", ""), ("lr_cruise", ""), ("lr_source", ""), ("tiles_est", None), ("size_hr_gb", None), ("within_50km", False)):
        if c not in df.columns:
            df[c] = v
    return df


def add_lr_sizes(df: pd.DataFrame) -> pd.DataFrame:
    """Raw-swath volume of the chosen NCEI LR cruise, from the NCEI autoindex listing (file list only), for candidates
    that are in range or uncertain."""
    sizes = {}
    for cr in df[df.status.isin(["in range", "uncertain"]) & df.lr_source.fillna("").str.startswith("NCEI")].lr_cruise.dropna().unique():
        try:
            iso = data_dir_from_iso(cr, K.CACHE / "geoportal")
            url, _ = resolve_data_dir(iso, K.CACHE / "ncei_dirlist") if iso else (None, "")
            sizes[cr] = round(size_cruise(cr, url, K.CACHE / "ncei_dirlist").total_bytes / 1e9, 2) if url else None
        except Exception as e:
            log.warning("size %s: %s", cr, e); sizes[cr] = None
    df["size_lr_gb"] = df.lr_cruise.map(sizes)
    df["size_est_gb"] = [round((a or 0) + (b or 0), 2) if (a is not None or b is not None) else None for a, b in zip(df.size_hr_gb, df.size_lr_gb)]
    df["size_note"] = ["" if (a is not None and b is not None) else ("HR size needs file listing; " if a is None else "") + ("LR size needs listing" if b is None else "")
                       for a, b in zip(df.size_hr_gb, df.size_lr_gb)]
    return df


def funnel(df: pd.DataFrame) -> dict:
    out = {}
    for src, d in df.groupby("source"):
        el = d[d.pool_eligible]
        f = {"records_found": int(len(d)), "not_a_grid_or_non_bathy": int((~d.pool_eligible).sum()),
             "not_eligible_breakdown": d[~d.pool_eligible].not_eligible_reason.value_counts().to_dict()}
        for rule in ("1", "2", "3", "4", "5"):
            f[f"excluded_rule_{rule}"] = int((el.excluded_by == rule).sum())
        s = el[el.excluded_by == ""]
        f["screened_under_s3"] = int(len(s))
        f["in_range"] = int((s.status == "in range").sum()); f["outside_range"] = int((s.status == "outside range").sum()); f["uncertain"] = int((s.status == "uncertain").sum())
        f["outside_by_condition"] = _by_condition(s[s.status == "outside range"])
        f["uncertain_by_field"] = _by_condition(s[s.status == "uncertain"])
        f["within_50km_flagged"] = int(s.within_50km.sum())
        out[src] = f
    tot = {"records_found": int(len(df)), "not_a_grid_or_non_bathy": int((~df.pool_eligible).sum())}
    el = df[df.pool_eligible]
    for rule in ("1", "2", "3", "4", "5"):
        tot[f"excluded_rule_{rule}"] = int((el.excluded_by == rule).sum())
    s = el[el.excluded_by == ""]
    tot.update({"screened_under_s3": int(len(s)), "in_range": int((s.status == "in range").sum()), "outside_range": int((s.status == "outside range").sum()),
                "uncertain": int((s.status == "uncertain").sum()), "outside_by_condition": _by_condition(s[s.status == "outside range"]),
                "uncertain_by_field": _by_condition(s[s.status == "uncertain"])})
    out["TOTAL"] = tot
    return out


def _by_condition(d: pd.DataFrame) -> dict:
    c = {}
    for r in d.status_reason.fillna(""):
        for part in [p.strip() for p in r.split(";") if p.strip()]:
            key = re.sub(r"[-\d.]+", "#", part.split(":")[0]).strip()
            c[key] = c.get(key, 0) + 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--skip-harvest", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT.mkdir(parents=True, exist_ok=True); K.CACHE.mkdir(parents=True, exist_ok=True)
    st = K.guard_selftest(); K.write_json(K.OUT / "guard_selftest.json", st)
    if not st["all_blocked"]:
        raise SystemExit("blindness guard self-test failed")
    t0 = time.time()
    mg = harvest_mgds(); log.info("MGDS total %d (%.0fs)", len(mg), time.time() - t0)
    pan, pan_ship = harvest_pangaea(); log.info("PANGAEA AUV %d ship %d", len(pan), len(pan_ship))
    dc_all = harvest_datacite(); dc = classify_datacite(dc_all); log.info("DataCite hits %d -> %d near-bottom grid datasets", len(dc_all), len(dc))
    sb = harvest_sciencebase(); log.info("ScienceBase items %d", len(sb))
    ncei = refresh_ncei_footprints(); log.info("NCEI footprints %d", len(ncei))
    hr = hr_records(mg, pan, dc, sb, ncei)
    hr.drop(columns=["text"]).to_file(OUT / "hr_footprints.gpkg", driver="GPKG", layer="hr")
    excl, notes = K.build_exclusion_set()
    excl.to_file(K.OUT / "exclusion_footprints.gpkg", driver="GPKG", layer="excl")
    K.write_json(K.OUT / "exclusion_set_notes.json", notes)
    sept = set(excl[excl.kind == "rejected_sept"].ref)
    pool_c_ids = json.loads((K.OUT / "pool_c" / "rescreen_ids.json").read_text()) if (K.OUT / "pool_c" / "rescreen_ids.json").exists() else {}
    df = screen(hr, ncei, pan_ship, excl, sept, pool_c_ids)
    df = add_lr_sizes(df)
    df.drop(columns=["text"], errors="ignore").to_csv(OUT / "hr_records.csv", index=False)
    cand = df[df.pool_eligible & (df.excluded_by == "")].copy()
    cand.drop(columns=["text"], errors="ignore").to_csv(OUT / "candidates.csv", index=False)
    fun = funnel(df); fun["_harvest"] = {"mgds_records": int(len(mg)), "mgds_by_platform_type": mg.platform_type.value_counts().to_dict(),
                                         "pangaea_auv_hits": pan.attrs.get("n_hits"), "pangaea_auv_bathymetry_datasets": int(len(pan)),
                                         "pangaea_ship_hits": pan_ship.attrs.get("n_hits"), "pangaea_ship_datasets": int(len(pan_ship)),
                                         "datacite_hits": int(len(dc_all)), "datacite_near_bottom_grid_datasets": int(len(dc)),
                                         "sciencebase_items": int(len(sb)), "ncei_footprints": int(len(ncei)), "generated": K.now_iso(),
                                         "elapsed_s": round(time.time() - t0)}
    K.write_json(OUT / "funnel.json", fun)
    K.write_json(K.OUT / "guard_state_pool_a.json", K.guard_state())
    print(json.dumps(fun["TOTAL"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
