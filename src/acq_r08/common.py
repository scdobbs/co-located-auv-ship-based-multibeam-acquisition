"""ACQ-R08 shared definitions — metadata-only inventory of candidate pairs for a second blind test.

Importing this module (which imports ``src.acq_r01.common``, so the lockbox guard is installed first) also installs the
ACQ-R08 **blindness guard**:

* ``rasterio.open``, ``numpy.load``, ``xarray.open_dataset`` / ``open_dataarray`` and ``rioxarray.open_rasterio`` raise
  ``PermissionError`` for the whole process (no raster, grid or array file of any kind is opened);
* every ``requests.get`` / ``requests.head`` is logged (host, path, kind, status, bytes) to ``network_log.jsonl`` and is
  refused when the URL path ends in a data / image extension (``.tif .bag .grd .nc .asc .xyz .all .mb* .zip .gz .png
  .jpg .pdf .sid .kmz ...``): only catalog APIs, ISO/XML/JSON records, directory listings and footprint queries pass.

Everything else here is bookkeeping shared by the pool scripts: paths, the exclusion set (§1), the §3 estimates and the
status rule, and small geometry helpers.
"""
from __future__ import annotations

import builtins
import json
import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import requests
from shapely.geometry import box, shape
from shapely.ops import transform, unary_union

from src.acq_r01 import common as C   # installs the lockbox guard

log = logging.getLogger("acq_r08")
STAMP = "2026-10-12"
OUT = C.REPO / "reports_post_grl_review" / "ACQ-R08"
CACHE = C.SCRATCH_DATA / "discovery_cache" / f"acq_r08_{STAMP}"
MANIFEST_V21 = C.REPO / "manifest" / "pairs_v2_1.parquet"
R01 = C.REPO / "reports_post_grl_review" / "ACQ-R01"
R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"
R03 = C.REPO / "reports_post_grl_review" / "ACQ-R03"
NET_LOG = OUT / "network_log.jsonl"
UA = {"User-Agent": "auv-ship-acq/0.5 (Sherlock; ACQ-R08 metadata inventory; stephencoledobbs@gmail.com)"}

# §3 development range and planning numbers (directive, verbatim)
CELLS_MIN, CELLS_MAX = 3.88, 51.2
HR_MIN, HR_MAX = 1.0, 4.99
# the manifest v2.1 development pairs carry hr_native_res_m down to 0.989 m (UTM cell of a nominal 1 m grid); the directive's
# "1.0" is read as that nominal 1 m, so the lower bound is applied at 0.985 m (challenge note in the report)
HR_MIN_APPLIED = 0.985
RATIO_BAND = 4.5          # k >= 2 under the 0.45 cycles/px clip
TILES_FLOOR = 300
EXCL_KM, FLAG_KM = 10.0, 50.0

# documented across-track beamwidths (deg) by ship sonar family — the C2a standard table of ACQ-R01 discovery_rerun
BEAMWIDTH = [("em122", 1.0), ("em120", 1.0), ("em302", 1.0), ("em304", 1.0), ("em300", 1.0), ("em710", 1.0),
             ("em712", 1.0), ("em1002", 2.0), ("em2040", 1.0), ("em124", 1.0), ("em3002", 1.5), ("em3000", 1.5),
             ("em1000", 3.3), ("em12", 1.8), ("em950", 3.3),
             ("seabeam 2100", 2.0), ("seabeam 2112", 2.0), ("seabeam 2000", 3.3), ("seabeam 3012", 1.5),
             ("seabeam 3050", 1.5), ("seabeam 1050", 1.5), ("seabeam 1180", 1.5), ("sea beam", 2.67), ("seabeam", 2.67),
             ("hydrosweep", 2.3), ("reson", 1.0), ("elac", 1.5), ("simrad", 1.0), ("kongsberg", 1.0)]
COMPOSITE_RE = re.compile(r"\bGMRT\b|\bGEBCO\b|composite|synthes|compil|merged|mosaic|multi-?source|\bSRTM\b|USGS", re.I)
VEHICLE_RE = re.compile(r"\bAUV\b|\bROV\b|\bHOV\b|Sentry|REMUS|HUGIN|ABYSS|Abyss|AsterX|MARUM-SEAL|\bSEAL\b|Jason|Alvin|"
                        r"D\. ?Allan B|Mapping AUV|Autosub|Bluefin|Hercules|Doc Ricketts|Tiburon|SuBastian|Girona|Iver|"
                        r"Nereus|near-bottom|Kraken|Tethys", re.I)
SETTING_RE = [(re.compile(r"vent|hydrothermal|black smoker|\bTAG\b|Lucky Strike|Menez|Logatchev|Endeavour|Juan de Fuca|"
                          r"Mid-Atlantic|Rainbow|seep field", re.I), "hydrothermal_vent"),
              (re.compile(r"nodule|abyssal|plain|\bCCZ\b|Clarion|Peru Basin|DISCOL|manganese", re.I), "abyssal_plain"),
              (re.compile(r"seamount|volcan|caldera|ridge|rift|spreading|\barc\b|Etna|Kolumbo|Santorini|lava|axial|"
                          r"fracture zone|transform|guyot|knoll", re.I), "volcanic_or_seamount"),
              (re.compile(r"canyon|slope|margin|shelf|fjord|pockmark|seep|mud volcano|delta|estuar|\bbay\b|harbou?r|"
                          r"landslide|escarpment|gully|channel|fan\b|levee|bank\b|cold seep|asphalt", re.I), "continental_margin"),
              (re.compile(r"polar|Arctic|Antarctic|\bice\b|glacier|Beaufort|Svalbard|Greenland", re.I), "polar")]
DATA_EXT = (".tif", ".tiff", ".bag", ".grd", ".nc", ".asc", ".xyz", ".all", ".kmall", ".gsf", ".zip", ".gz", ".tgz",
            ".tar", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".sid", ".kmz", ".kml", ".img", ".bil", ".flt", ".hdf",
            ".h5", ".mb", ".s7k", ".wcd", ".xtf", ".las", ".laz", ".7z", ".rar", ".bin", ".dat", ".raw")
_MB_EXT_RE = re.compile(r"\.mb\d+(\.gz)?$", re.I)


# ----------------------------------------------------------------------------------------------------------------- #
# Blindness guard
# ----------------------------------------------------------------------------------------------------------------- #
_GUARD_STATE = {"installed": False, "raster_open_refused": 0, "data_url_refused": 0, "requests": 0}


def _refuse(what):
    def f(*a, **k):
        _GUARD_STATE["raster_open_refused"] += 1
        raise PermissionError(f"ACQ-R08 blindness guard: {what} is refused for the whole inventory run (metadata only)")
    return f


def _kind_of(url: str) -> str:
    h = urlparse(url).netloc.lower(); p = urlparse(url).path.lower()
    if "marine-geo.org" in h:
        return "catalog API (MGDS FileServer)"
    if "ws.pangaea.de" in h:
        return "catalog API (PANGAEA Elasticsearch)"
    if "api.datacite.org" in h:
        return "catalog API (DataCite REST)"
    if "sciencebase.gov" in h:
        return "catalog API (USGS ScienceBase)"
    if "gis.ngdc.noaa.gov" in h:
        return "footprint query (NCEI ArcGIS multibeam footprints)"
    if "ncei.noaa.gov" in h and "/opensearch" in p:
        return "catalog API (NCEI Geoportal OpenSearch)"
    if "ncei.noaa.gov" in h and "/rest/metadata/item/" in p:
        return "ISO / JSON record (NCEI Geoportal item)"
    if "data.ngdc.noaa.gov" in h:
        return "file listing (NCEI autoindex)"
    if "doi.org" in h:
        return "DOI resolver (HEAD)"
    return f"other ({h})"


_real_get, _real_head = requests.get, requests.head


def _logged(method, real):
    def f(url, *a, **k):
        path = urlparse(url).path.lower()
        if path.endswith(DATA_EXT) or _MB_EXT_RE.search(path):
            _GUARD_STATE["data_url_refused"] += 1
            raise PermissionError(f"ACQ-R08 blindness guard: data/image URL refused: {url}")
        t0 = time.time(); status = None; nbytes = None; err = ""
        try:
            r = real(url, *a, **k)
            status, nbytes = r.status_code, len(r.content or b"")
            return r
        except Exception as e:
            err = str(e)[:120]; raise
        finally:
            _GUARD_STATE["requests"] += 1
            rec = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"), "method": method, "kind": _kind_of(url),
                   "host": urlparse(url).netloc, "path": urlparse(url).path[:160], "status": status, "bytes": nbytes,
                   "s": round(time.time() - t0, 2), "err": err}
            try:
                NET_LOG.parent.mkdir(parents=True, exist_ok=True)
                with builtins.open(NET_LOG, "a") as fh:
                    fh.write(json.dumps(rec) + "\n")
            except Exception:
                pass
    return f


def install_blindness_guard():
    if _GUARD_STATE["installed"]:
        return
    try:
        import rasterio
        rasterio.open = _refuse("rasterio.open")
    except Exception:
        pass
    np.load = _refuse("numpy.load")
    try:
        import xarray
        xarray.open_dataset = _refuse("xarray.open_dataset"); xarray.open_dataarray = _refuse("xarray.open_dataarray")
        xarray.open_mfdataset = _refuse("xarray.open_mfdataset")
    except Exception:
        pass
    try:
        import rioxarray
        rioxarray.open_rasterio = _refuse("rioxarray.open_rasterio")
    except Exception:
        pass
    requests.get = _logged("GET", _real_get)
    requests.head = _logged("HEAD", _real_head)
    _GUARD_STATE["installed"] = True


def guard_selftest() -> dict:
    """Prove the guard: every probe must raise."""
    probes = []
    for name, fn, arg in [("rasterio.open", lambda: __import__("rasterio").open("/tmp/x.tif"), None),
                          ("numpy.load", lambda: np.load("/tmp/x.npy"), None),
                          ("requests.get .tif", lambda: requests.get("https://example.org/a/b.tif"), None),
                          ("requests.get .bag", lambda: requests.get("https://example.org/H1/BAG/H1_MB_4m.bag"), None),
                          ("requests.get .mb58.gz", lambda: requests.get("https://example.org/x/0001.mb58.gz"), None),
                          ("requests.get .png", lambda: requests.get("https://example.org/x/preview.png"), None),
                          ("requests.get .zip", lambda: requests.get("https://example.org/x/grid.zip"), None)]:
        try:
            fn(); probes.append({"probe": name, "blocked": False})
        except PermissionError:
            probes.append({"probe": name, "blocked": True})
        except Exception as e:
            probes.append({"probe": name, "blocked": False, "error": str(e)[:80]})
    return {"installed": _GUARD_STATE["installed"], "probes": probes, "all_blocked": all(p["blocked"] for p in probes)}


def guard_state() -> dict:
    return dict(_GUARD_STATE)


install_blindness_guard()


# ----------------------------------------------------------------------------------------------------------------- #
# Small helpers
# ----------------------------------------------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hav_km(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))


def _local_tr(lon, lat):
    return pyproj.Transformer.from_crs("EPSG:4326", f"+proj=aeqd +lat_0={lat} +lon_0={lon} +ellps=WGS84",
                                       always_xy=True).transform


def area_km2(geom) -> float:
    if geom is None or geom.is_empty:
        return 0.0
    c = geom.centroid
    return float(transform(_local_tr(c.x, c.y), geom).area) / 1e6


def dist_km(g1, g2) -> float:
    """Geodesic-ish separation of two WGS84 geometries (0 when they touch/overlap), via a local AEQD projection."""
    if g1 is None or g2 is None or g1.is_empty or g2.is_empty:
        return float("nan")
    if g1.intersects(g2):
        return 0.0
    c = g1.centroid
    tr = _local_tr(c.x, c.y)
    try:
        return float(transform(tr, g1).distance(transform(tr, g2))) / 1000.0
    except Exception:
        return hav_km((c.x, c.y), (g2.centroid.x, g2.centroid.y))


def inter_km2(g1, g2) -> float:
    if g1 is None or g2 is None or g1.is_empty or g2.is_empty or not g1.intersects(g2):
        return 0.0
    try:
        return area_km2(g1.intersection(g2))
    except Exception:
        return area_km2(g1.buffer(0).intersection(g2.buffer(0)))


def beamwidth(sonar):
    s = (sonar if isinstance(sonar, str) else "").lower().replace("-", " ").replace("_", " ")
    s2 = s.replace(" ", "")
    for k, v in BEAMWIDTH:
        if k in s or k.replace(" ", "") in s2:
            return v
    return None


def setting_of(text: str) -> str:
    for rx, name in SETTING_RE:
        if rx.search(text or ""):
            return name
    return "unknown"


def basin(lon: float, lat: float) -> str:
    from src.acq_r01.discovery_rerun import basin as _b
    return _b(lon, lat)


def releasable_of(license_text: str) -> tuple[str, str]:
    """(releasable, note). CC-BY / CC0 / public domain: yes. CC-BY-NC(-SA): yes-conditional (non-commercial, share-alike
    conditions on derived products; the corpus pairs were acquired under the same MGDS terms). Restricted / not stated:
    unknown."""
    t = (license_text or "").lower()
    if re.search(r"restrict|embargo|401|not public|permission", t):
        return "no", "restricted"
    if re.search(r"cc0|public.?domain|public domain|us federal|u\.s\. federal|open data|cc-by-4|cc by 4|cc-by-3|cc by 3|"
                 r"creative commons attribution 4|creative commons attribution 3|cc-by(?!-nc)|cc by(?! nc)", t):
        return "yes", "open licence"
    if re.search(r"nc|non.?commercial|share.?alike|cc-by-nc|by-nc", t):
        return "yes_conditional", "CC-BY-NC(-SA): non-commercial / share-alike conditions on derived products"
    if "mgds" in t:
        return "yes_conditional", "MGDS default terms (typically CC-BY-NC-SA 3.0); record does not state a licence"
    return "unknown", "licence not stated in the catalog record"


# ----------------------------------------------------------------------------------------------------------------- #
# Exclusion set (§1): manifest v2.1 pairs (incl. EW0207, lockbox, confirmatory), every pair rejected in ACQ-R01..R07,
# and the Cal DIG area. Footprints: vector files only — never a raster.
# ----------------------------------------------------------------------------------------------------------------- #
def _read_gj(path: Path):
    g = gpd.read_file(path)
    if g.crs is not None and str(g.crs).upper() != "EPSG:4326":
        g = g.to_crs("EPSG:4326")
    return g.geometry.union_all() if hasattr(g.geometry, "union_all") else unary_union(list(g.geometry))


def load_manifest_v21() -> pd.DataFrame:
    return pd.read_parquet(MANIFEST_V21)


def r01_hr_catalog() -> gpd.GeoDataFrame:
    return gpd.read_file(R01 / "discovery_rerun" / "hr_catalog.gpkg", layer="hr").set_index("hr_id")


def r02_hr_footprints() -> gpd.GeoDataFrame:
    g = gpd.read_file(R02 / "verification" / "hr_footprints.gpkg")
    if g.crs is not None and str(g.crs).upper() != "EPSG:4326":
        g = g.to_crs("EPSG:4326")
    return g.set_index("hr_id")


def june_hr_catalog() -> gpd.GeoDataFrame:
    return gpd.read_file(C.REPO / "reports/discovery/hr_catalog.gpkg", layer="hr").set_index("hr_id")


def mgds_id_of_pair(pair_id: str):
    return f"MGDS:{pair_id.split('__MGDS_')[1]}" if "__MGDS_" in pair_id else None


def build_exclusion_set() -> tuple[gpd.GeoDataFrame, dict]:
    """One row per excluded footprint: kind ∈ {manifest_v2_1, lockbox, confirmatory, rejected_sept, cal_dig_area}.
    Returns (gdf, notes)."""
    m = load_manifest_v21()
    r01 = r01_hr_catalog(); r02 = r02_hr_footprints(); jun = june_hr_catalog()
    la = pd.read_csv(C.REPO / "reports/discovery/leakage_assignment.csv").set_index("pair_id")
    rows, notes = [], {"footprint_sources": {}, "missing": []}

    def push(kind, ref, geom, src, extra=None):
        if geom is None or geom.is_empty:
            notes["missing"].append({"kind": kind, "ref": ref, "source_tried": src}); return
        d = {"kind": kind, "ref": ref, "footprint_source": src, "geometry": geom}
        d.update(extra or {}); rows.append(d)
        notes["footprint_sources"][src] = notes["footprint_sources"].get(src, 0) + 1

    for _, r in m.iterrows():
        pid = r.pair_id; des = str(r.designation); mid = mgds_id_of_pair(pid)
        hp = str(r.harmonized_path) if isinstance(r.harmonized_path, str) else ""
        if pid in C.LOCKBOX:
            # never open anything under the lockbox directories: catalog footprint (MGDS bbox) + June centroid
            g = r01.loc[mid].geometry if mid in r01.index else None
            cen = (float(la.loc[pid, "centroid_lon"]), float(la.loc[pid, "centroid_lat"])) if pid in la.index else None
            push("lockbox", pid, g, "ACQ-R01 discovery hr_catalog (MGDS catalog footprint; lockbox dir never opened)",
                 {"centroid_lon": cen[0] if cen else None, "centroid_lat": cen[1] if cen else None, "unit": r.leakage_unit})
            continue
        if des == "confirmatory" or "harmonized_confirmatory" in hp:
            g = r02.loc[mid].geometry if mid in r02.index else (r01.loc[mid].geometry if mid in r01.index else None)
            src = "ACQ-R02 verification hr_footprints.gpkg (sealed dir never opened)" if mid in r02.index else "ACQ-R01 hr_catalog (catalog bbox)"
            push("confirmatory", pid, g, src, {"unit": r.leakage_unit}); continue
        gj = C.OAK / hp / "footprint.geojson" if hp else None
        if gj is not None and gj.exists():
            push("manifest_v2_1", pid, _read_gj(gj), "OAK harmonized/<pair>/footprint.geojson", {"unit": r.leakage_unit, "designation": des})
        elif mid and mid in r02.index:
            push("manifest_v2_1", pid, r02.loc[mid].geometry, "ACQ-R02 verification hr_footprints.gpkg", {"unit": r.leakage_unit, "designation": des})
        elif mid and mid in r01.index:
            push("manifest_v2_1", pid, r01.loc[mid].geometry, "ACQ-R01 hr_catalog (catalog bbox)", {"unit": r.leakage_unit, "designation": des})
        else:
            push("manifest_v2_1", pid, None, f"none ({gj})")

    # pairs rejected in ACQ-R01..R07 (September): verification drops, manifest v2 / v2.1 dropped lists, R01 gate drops
    sept = []
    v = pd.read_csv(R02 / "verification" / "candidates_verified.csv")
    for _, r in v[v.status != "verified"].iterrows():
        sept.append((r.hr_id, f"ACQ-R02 verification: {r.status}"))
    for f in ("pairs_v2_dropped.csv", "pairs_v2_1_dropped.csv"):
        for _, r in pd.read_csv(C.REPO / "manifest" / f).iterrows():
            mid = mgds_id_of_pair(r.pair_id) or ("PANGAEA:889317" if "889317" in r.pair_id else r.pair_id)
            sept.append((mid, f"{f}: {r.reason}"))
    cg = pd.read_csv(R01 / "discovery_rerun" / "candidates_gated.csv")
    for _, r in cg[cg.status.isin(["gate_excluded", "render_no_elevation", "not_auv_bathymetry"])].iterrows():
        if r.status == "gate_excluded" and "ratio" in str(r.reason):
            continue      # rejected only by the retired ratio gate: re-screened under Pool C (directive §2), not excluded by §1.1
        sept.append((r.hr_id, f"ACQ-R01 gate: {r.status}"))
    pan = pd.read_csv(R02 / "discovery_pangaea" / "auv_datasets.csv").astype({"id": str}).set_index("id")
    seen = set()
    for hid, why in sept:
        if hid in seen:
            continue
        seen.add(hid)
        g, src = None, ""
        if hid in r02.index:
            g, src = r02.loc[hid].geometry, "ACQ-R02 verification hr_footprints.gpkg"
        elif hid in r01.index:
            g, src = r01.loc[hid].geometry, "ACQ-R01 hr_catalog (catalog bbox)"
        elif hid in jun.index:
            g, src = jun.loc[hid].geometry, "June hr_catalog (catalog bbox)"
        elif hid.startswith("PANGAEA:") and hid.split(":")[1] in pan.index:
            p = pan.loc[hid.split(":")[1]]
            g, src = box(float(p.west), float(p.south), float(p.east), float(p.north)).buffer(0.002), "ACQ-R02 PANGAEA discovery record (ES bbox)"
        # dropped pairs that were harmonized have an (unsealed) OAK footprint
        for d in (C.REPO / "manifest" / "pairs_v2_1_dropped.csv", C.REPO / "manifest" / "pairs_v2_dropped.csv"):
            dd = pd.read_csv(d)
            hit = dd[dd.pair_id.apply(lambda p: (mgds_id_of_pair(p) == hid) or ("889317" in p and hid == "PANGAEA:889317"))]
            if len(hit):
                hdir = str(hit.iloc[0].harmonized_dir)
                if "harmonized_confirmatory" in hdir:
                    continue
                gj = C.OAK / hdir / "footprint.geojson"
                if gj.exists():
                    g, src = _read_gj(gj), "OAK harmonized/<pair>/footprint.geojson (dropped pair, unsealed)"
                break
        push("rejected_sept", hid, g, src or "none", {"reason": why})

    # Cal DIG area: union of the 20 Cal DIG pair footprints, convex hull, 25 km buffer (the ship mosaic's extent is not
    # in any catalog record we may read without opening the raster; the pair footprints are the acquired part of it)
    cal = [r for r in rows if r["kind"] == "manifest_v2_1" and str(r["ref"]).startswith("cal_dig")]
    if cal:
        hull = unary_union([r["geometry"] for r in cal]).convex_hull
        c = hull.centroid; tr = _local_tr(c.x, c.y); inv = pyproj.Transformer.from_crs(
            f"+proj=aeqd +lat_0={c.y} +lon_0={c.x} +ellps=WGS84", "EPSG:4326", always_xy=True).transform
        area = transform(inv, transform(tr, hull).buffer(25_000))
        push("cal_dig_area", "Cal DIG I / Morro Bay", area, "convex hull of the 20 Cal DIG pair footprints + 25 km")
    g = gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs="EPSG:4326")
    notes["n_by_kind"] = g.kind.value_counts().to_dict()
    return g, notes


_EXCL_CACHE = {}


def _radius_km(geom) -> float:
    c = geom.centroid; b = geom.bounds
    return max(hav_km((c.x, c.y), (x, y)) for x in (b[0], b[2]) for y in (b[1], b[3]))


def _prepared_exclusions(excl: gpd.GeoDataFrame, kinds):
    key = (id(excl), tuple(kinds))
    if key not in _EXCL_CACHE:
        rows = []
        for _, e in excl[excl.kind.isin(kinds)].iterrows():
            c = e.geometry.centroid
            rows.append((e.ref, e.kind, e.geometry, (c.x, c.y), _radius_km(e.geometry)))
        _EXCL_CACHE[key] = rows
    return _EXCL_CACHE[key]


def nearest_exclusion(geom, excl: gpd.GeoDataFrame, kinds=("manifest_v2_1", "lockbox", "confirmatory", "rejected_sept")):
    """(nearest_ref, nearest_kind, km, overlaps_ref_list) over the given kinds. A centroid/radius lower bound skips far
    polygons; one local AEQD projection per candidate serves every precise distance."""
    rows = _prepared_exclusions(excl, kinds)
    c = geom.centroid; rg = _radius_km(geom)
    best = (None, None, float("inf")); over = []; tr = None; gp = None
    cand = []
    for ref, kind, eg, ec, re_ in rows:
        lb = hav_km((c.x, c.y), ec) - rg - re_
        cand.append((max(lb, 0.0), ref, kind, eg))
    cand.sort(key=lambda t: t[0])
    for lb, ref, kind, eg in cand:
        if lb > best[2] and lb > FLAG_KM:
            break
        if geom.intersects(eg):
            over.append(ref); best = (ref, kind, 0.0) if 0.0 < best[2] else best
            continue
        if tr is None:
            tr = _local_tr(c.x, c.y); gp = transform(tr, geom)
        try:
            d = float(gp.distance(transform(tr, eg))) / 1000.0
        except Exception:
            d = hav_km((c.x, c.y), (eg.centroid.x, eg.centroid.y))
        if d < best[2]:
            best = (ref, kind, d)
    return best[0], best[1], (round(best[2], 1) if best[2] < float("inf") else None), over


# ----------------------------------------------------------------------------------------------------------------- #
# §3 estimates and status
# ----------------------------------------------------------------------------------------------------------------- #
def lr_estimate(stated_res_m, sonar: str, depth_m):
    """(lr_est_m, method, weak). Stated product spacing wins; else beam footprint 2*depth*tan(bw/2) at mean depth."""
    stated_res_m, depth_m = _num(stated_res_m), _num(depth_m)
    if stated_res_m and stated_res_m > 0:
        return float(stated_res_m), "stated gridded product spacing (NCEI Geoportal MD_Resolution)", False
    sonar = sonar if isinstance(sonar, str) else ""
    bw = beamwidth(sonar)
    if bw is None and sonar.strip():
        bw_used, weak, note = 1.5, True, f"beamwidth unknown for '{sonar}' → 1.5° default"
    elif bw is None:
        bw_used, weak, note = 1.5, True, "sonar not stated → 1.5° default"
    else:
        bw_used, weak, note = bw, False, f"documented across-track beamwidth {bw}° ({sonar})"
    if depth_m is None or not (depth_m > 0):
        return None, "needs download (depth not in catalog record)", True
    return round(2 * depth_m * math.tan(math.radians(bw_used / 2)), 2), f"beam footprint 2·z·tan(bw/2) at mean depth {depth_m:.0f} m; {note}", weak


def _num(x):
    """None for None/NaN/non-finite, else float."""
    try:
        if x is None or (isinstance(x, str) and not x.strip()):
            return None
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def estimates(hr_res_m, lr_est_m, overlap_km2):
    hr_res_m, lr_est_m, overlap_km2 = _num(hr_res_m), _num(lr_est_m), _num(overlap_km2)
    e = {"cells_across_est": None, "ratio_est": None, "band_feasible": None, "tiles_est": None}
    if hr_res_m and lr_est_m:
        e["cells_across_est"] = round(256 * hr_res_m / lr_est_m, 2)
        e["ratio_est"] = round(lr_est_m / hr_res_m, 2)
        e["band_feasible"] = bool(e["ratio_est"] >= RATIO_BAND)
    if hr_res_m and overlap_km2 is not None:
        e["tiles_est"] = int(math.floor(overlap_km2 / (128 * hr_res_m / 1000.0) ** 2))
    return e


def status_of(rec: dict) -> tuple[str, str]:
    """in range / outside range / uncertain per §3 (definite failures first, then weak fields)."""
    fails, weak = [], []
    hr = _num(rec.get("hr_res_m"))
    if hr is None:
        weak.append("hr_res_m needs download (not in catalog record)")
    elif not (HR_MIN_APPLIED <= hr <= HR_MAX):
        fails.append(f"hr_res_m {hr:.3g} outside 1.0–4.99 (applied ≥ 0.985)")
    if not rec.get("lr_cruise"):
        fails.append("no independent ship cruise with raw swath over the footprint")
    elif rec.get("lr_raw_available") is False:
        fails.append("ship cruise has no raw swath available")
    if _num(rec.get("lr_est_m")) is None:
        weak.append(f"lr_est_m: {rec.get('lr_est_method')}")
    else:
        if rec.get("band_feasible") is False:
            (weak if rec.get("lr_est_weak") else fails).append(f"band infeasible: ratio_est {rec.get('ratio_est')} < 4.5")
        c = _num(rec.get("cells_across_est"))
        if c is not None and not (CELLS_MIN <= c <= CELLS_MAX):
            (weak if rec.get("lr_est_weak") else fails).append(f"cells_across_est {c} outside 3.88–51.2")
        if rec.get("lr_est_weak") and not fails:
            weak.append(f"lr_est_m method weak: {rec.get('lr_est_method')}")
    t = _num(rec.get("tiles_est"))
    if t is None:
        weak.append("tiles_est: overlap needs footprint")
    elif t < TILES_FLOOR:
        if rec.get("footprint_kind", "").startswith("bbox") or rec.get("footprint_suspect"):
            fails.append(f"tiles_est {t} < 300 even on the bbox upper bound")
        else:
            fails.append(f"tiles_est {t} < 300")
    elif rec.get("footprint_kind", "").startswith("bbox") or rec.get("footprint_suspect"):
        weak.append("overlap/tiles are a bbox upper bound (true footprint needs download)")
    rel = rec.get("releasable")
    if rel == "no":
        fails.append("not releasable (restricted)")
    elif rel == "unknown":
        weak.append("licence not stated")
    if rec.get("hr_format_issue"):
        weak.append(rec["hr_format_issue"])
    if fails:
        return "outside range", "; ".join(fails)
    if weak:
        return "uncertain", "; ".join(weak)
    return "in range", ""


def write_json(path: Path, obj):
    C.write_json(path, obj)


def md_table(df: pd.DataFrame, cols: list[str], maxw: int = 70) -> list[str]:
    def fmt(v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return ""
        if isinstance(v, float):
            return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 1e6 else f"{v:.3g}"
        s = str(v).replace("|", "/").replace("\n", " ")
        return s if len(s) <= maxw else s[:maxw - 1] + "…"
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(fmt(r.get(c)) for c in cols) + " |")
    return out
