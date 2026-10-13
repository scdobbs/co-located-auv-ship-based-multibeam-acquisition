"""ACQ-R08b shared definitions — download the second-test candidate grids and measure header, footprint, one rounded
median depth and a tile count; nothing else about the relief (directive §1, §3).

Importing this module imports ``src.acq_r01.common`` (lockbox guard, extended by ACQ-R08b with the ``sealed_candidates_v3``
root and every candidate id).  The §3 scripts call :func:`allow` once, which installs the named allowance and records it
in ``guard_log.jsonl``.  Network requests are logged (host, path, kind, status, bytes) — downloads are allowed here, so
unlike ACQ-R08 no URL is refused.  A write guard refuses matplotlib / PIL imports and any image-extension file written by
these scripts.
"""
from __future__ import annotations

import builtins
import json
import logging
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pyproj
import requests
from shapely.ops import transform, unary_union

from src.acq_r01 import common as C

log = logging.getLogger("acq_r08b")
STAMP = "2026-10-13"
OUT = C.REPO / "reports_post_grl_review" / "ACQ-R08b"
FOOTPRINTS = OUT / "footprints"
SEALED = C.SEALED_CANDIDATES_V3
CACHE = C.SCRATCH_DATA / "discovery_cache" / f"acq_r08b_{STAMP}"
R08 = C.REPO / "reports_post_grl_review" / "ACQ-R08"
R08_CACHE = C.SCRATCH_DATA / "discovery_cache" / "acq_r08_2026-10-12"
GUARD_LOG = OUT / "guard_log.jsonl"
NET_LOG = OUT / "network_log.jsonl"
UA = {"User-Agent": "auv-ship-acq/0.6 (Sherlock; ACQ-R08b candidate header/footprint; stephencoledobbs@gmail.com)"}
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".pdf", ".eps", ".ps", ".webp", ".tiff_preview")

# §3 development range (ACQ-R08 §3, lower bound applied at 0.985 m as in ACQ-R08)
CELLS_MIN, CELLS_MAX = 3.88, 51.2
HR_MIN, HR_MAX = 0.985, 4.99
RATIO_BAND = 4.5
TILES_FLOOR = 300
WIN, STRIDE, VALID_FLOOR = 256, 128, 0.5
EXCL_KM, FLAG_KM = 10.0, 50.0

# documented across-track beamwidth (deg) and nominal usable swath width (× depth) per ship sonar family
BEAMWIDTH = [("em122", 1.0), ("em120", 1.0), ("em302", 1.0), ("em304", 1.0), ("em300", 1.0), ("em710", 1.0), ("em712", 1.0),
             ("em1002", 2.0), ("em2040", 1.0), ("em124", 1.0), ("seabeam 2100", 2.0), ("seabeam 2112", 2.0), ("seabeam 2000", 3.3),
             ("seabeam 3012", 1.5), ("seabeam 3050", 1.5), ("seabeam 1050", 1.5), ("hydrosweep ds-2", 2.3), ("hydrosweep ds", 2.3),
             ("hydrosweep", 2.3), ("seabeam", 2.67), ("reson", 1.0), ("simrad", 1.0), ("kongsberg", 1.0)]
# nominal usable swath width as a multiple of water depth (sector ≈ 120° → 3.5×z for the modern Kongsberg deep-water
# systems and SeaBeam 3012; 120° → 3.0×z for SeaBeam 2100/2112/2000; 90° → 2.0×z for Hydrosweep DS); half of it buffers the
# navigation track (directive §3 ship_coverage)
SWATH_FACTOR = [("em122", 3.5), ("em120", 3.5), ("em302", 3.5), ("em304", 3.5), ("em300", 3.5), ("em710", 3.5), ("em712", 3.5),
                ("em124", 3.5), ("seabeam 3012", 3.5), ("seabeam 3050", 3.5), ("seabeam 2100", 3.0), ("seabeam 2112", 3.0),
                ("seabeam 2000", 3.0), ("seabeam 1050", 3.0), ("hydrosweep", 2.0), ("seabeam", 2.5), ("simrad", 3.5), ("kongsberg", 3.5)]

# candidate registry (directive §2): id → download source and the ship partner as in ACQ-R08
CANDIDATES = {
    "MGDS:31860": {"source": "MGDS", "r08_status": "in range", "lr": "MV1003", "lr_alt": ["RC2901", "VANC05MV"]},
    "MGDS:31675": {"source": "MGDS", "r08_status": "in range", "lr": "KN173L02", "lr_alt": ["KN204-01", "KN161L08"]},
    "MGDS:31954": {"source": "MGDS", "r08_status": "in range", "lr": "AT26-24", "lr_alt": ["VANC02MV"]},
    "MGDS:30368": {"source": "MGDS", "r08_status": "uncertain", "lr": "Escanaba", "lr_alt": ["MGLN46MV", "EX0904"]},
    "MGDS:18210": {"source": "MGDS", "r08_status": "uncertain", "lr": "TN188", "lr_alt": ["MV1007", "EX1103"]},
    "MGDS:31811": {"source": "MGDS", "r08_status": "uncertain", "lr": "EW0004", "lr_alt": ["TN188", "EX1103"]},
    "MGDS:24756": {"source": "MGDS", "r08_status": "uncertain", "lr": "Monterey", "lr_alt": ["KIWI01RR", "RB1604", "MV1405"]},
    "MGDS:22436": {"source": "MGDS", "r08_status": "uncertain", "lr": "KN161L04", "lr_alt": ["AT04L04", "EW9704", "EW0301"]},
    "MGDS:21415": {"source": "MGDS", "r08_status": "uncertain", "lr": "MV1209", "lr_alt": ["MV1217", "AT07L09", "TN338"]},
    "PANGAEA:958275": {"source": "PANGAEA", "r08_status": "uncertain", "lr": "PANGAEA:895437 (M143 EM122)", "lr_alt": ["PANGAEA:895497 (M143 EM710)", "PANGAEA:993972 (M215)", "PANGAEA:993973 (M215)", "PANGAEA:981058 (MSM132)"],
                       "lr_access_check": ["895437", "895497", "993972", "993973", "981058"]},
    "SEANOE:55744": {"source": "SEANOE", "r08_status": "uncertain", "doi": "10.17882/55744", "landing": "https://www.seanoe.org/data/00446/55744/",
                     "lr": "PANGAEA:975981 (M51/4 Hydrosweep DS-2)", "lr_alt": ["PANGAEA:895437 (M143 EM122)"], "lr_access_check": ["975981", "895437"]},
}
NOT_PROCESSED = {"MGDS:31979": "ROV point file, 0.04 km² (directive §2)",
                 "DOI:10.5285/31b8167c-4d8d-07f0-e063-7086abc03df1": "BODC BioCam record: broken footprint, implausible ship match (directive §2)",
                 "DOI:10.5285/31c95277-80ab-34ff-e063-7086abc04e84": "BODC BioCam record: broken footprint, implausible ship match (directive §2)"}
RULINGS = ["R1 downloading the candidate high-resolution grids is allowed, provided no output can bias the later test",
           "R2 Pool B (NOS BAG) is dropped", "R3 MGDS conditional terms (CC-BY-NC-SA) are accepted, as for the development corpus",
           "R4 Escanaba Trough (MGDS:30368) stays a candidate; only its metadata has been seen",
           "R5 Steve has not seen any Monterey Canyon AUV data (MGDS:24756); no prior exposure"]


def tok(hr_id: str) -> str:
    return hr_id.replace(":", "_")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def jlog(path: Path, rec: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with builtins.open(path, "a") as fh:
        fh.write(json.dumps({"t": now_iso(), **rec}, default=str) + "\n")


# ----------------------------------------------------------------------------------------------------------------- #
# Guard: allowance, self-test, write guard, network log
# ----------------------------------------------------------------------------------------------------------------- #
def allow(script: str) -> tuple:
    reason = f"ACQ-R08b §3 script {script} installs the sealed-candidate allowance for its own reads/writes"
    t = C.install_r08b_allowance(reason)
    jlog(GUARD_LOG, {"event": "allowance_installed", "script": script, "tokens": list(t), "pid": os.getpid()})
    return t


def guard_selftest(write: bool = True) -> dict:
    """Every patched reader on the sealed root, every candidate directory and a file inside each; all must raise the
    guard's PermissionError.  Run BEFORE the allowance is installed."""
    import numpy as np
    import pandas as pd
    import rasterio
    import geopandas as gpd
    import pyogrio
    readers = {"builtins.open": lambda p: builtins.open(p, "rb"), "rasterio.open": rasterio.open, "numpy.load": np.load,
               "geopandas.read_file": gpd.read_file, "pyogrio.read_dataframe": pyogrio.read_dataframe, "pandas.read_parquet": pd.read_parquet}
    targets = {"root": str(SEALED), "root file": str(SEALED / "SHA256SUMS")}
    for i in C.SEALED_CANDIDATE_IDS:
        targets[f"dir:{i}"] = str(SEALED / tok(i)); targets[f"file:{i}"] = str(SEALED / tok(i) / "grid.grd")
        targets[f"elsewhere:{i}"] = f"/tmp/{tok(i)}/copy.tif"
    for l in C.LOCKBOX:
        targets[f"lockbox:{l}"] = str(C.OAK / "harmonized" / l / "lr.tif")
    rows, n_blocked = [], 0
    for tn, p in targets.items():
        for rn, fn in readers.items():
            try:
                fn(p); res = "NOT BLOCKED"
            except PermissionError as e:
                res = "blocked" if "GUARD" in str(e) else f"PermissionError not from guard: {e}"
            except Exception as e:
                res = f"NOT BLOCKED ({type(e).__name__})"
            rows.append({"target": tn, "reader": rn, "result": res}); n_blocked += res == "blocked"
    # control: an unsealed repo file must open
    ctl = {"path": str(C.REPO / "manifest" / "pairs_v2_1.parquet")}
    try:
        pd.read_parquet(ctl["path"]); ctl["opened"] = True
    except Exception as e:
        ctl["opened"] = False; ctl["error"] = str(e)[:100]
    out = {"probes": len(rows), "blocked": n_blocked, "all_blocked": n_blocked == len(rows), "control_opened": ctl["opened"],
           "allowance_installed": bool(C.r08b_allowance()), "targets": len(targets), "readers": list(readers), "rows": rows, "at": now_iso()}
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "guard_selftest.json").write_text(json.dumps(out, indent=1))
        jlog(GUARD_LOG, {"event": "selftest", "probes": len(rows), "blocked": n_blocked, "all_blocked": out["all_blocked"], "control_opened": ctl["opened"]})
    return out


_real_import = builtins.__import__


def _guarded_import(name, *a, **k):
    if name.split(".")[0] in ("matplotlib", "PIL", "imageio", "cv2", "skimage", "seaborn", "plotly", "bokeh"):
        raise PermissionError(f"ACQ-R08b write guard: import of {name} refused (no image, plot or preview may be produced)")
    return _real_import(name, *a, **k)


_real_open = builtins.open


def install_write_guard():
    builtins.__import__ = _guarded_import
    cur = builtins.open

    def guarded(file, mode="r", *a, **k):
        try:
            s = str(os.fspath(file)) if not isinstance(file, int) else ""
        except TypeError:
            s = str(file)
        if any(m in str(mode) for m in ("w", "a", "x", "+")) and s.lower().endswith(IMAGE_EXT):
            raise PermissionError(f"ACQ-R08b write guard: refusing to write an image/plot file {s}")
        return cur(file, mode, *a, **k)
    builtins.open = guarded


def _kind_of(url: str) -> str:
    h = urlparse(url).netloc.lower(); p = urlparse(url).path.lower()
    if "marine-geo.org" in h:
        return "MGDS FileDownloadServer (candidate grid file)" if "download" in p.lower() else "MGDS FileServer (catalog)"
    if "doi.pangaea.de" in h or "ws.pangaea.de" in h:
        return "PANGAEA dataset metadata / file listing"
    if "pangaea.de" in h:
        return "PANGAEA file"
    if "seanoe.org" in h:
        return "SEANOE landing page / data file"
    if "api.datacite.org" in h or "doi.org" in h:
        return "DataCite / DOI record"
    if "data.ngdc.noaa.gov" in h:
        return "NCEI navigation file (.fnv)" if p.endswith(".fnv") else "NCEI file listing (autoindex)"
    if "ncei.noaa.gov" in h:
        return "NCEI Geoportal record"
    if "gis.ngdc.noaa.gov" in h:
        return "NCEI footprint service"
    return f"other ({h})"


_rget = requests.get


def _logged_get(url, *a, **k):
    t0 = time.time(); st = None; nb = None; err = ""
    try:
        r = _rget(url, *a, **k); st = r.status_code
        nb = None if k.get("stream") else len(r.content or b"")
        return r
    except Exception as e:
        err = str(e)[:100]; raise
    finally:
        jlog(NET_LOG, {"method": "GET", "kind": _kind_of(url), "host": urlparse(url).netloc, "path": urlparse(url).path[:160], "status": st, "bytes": nb, "s": round(time.time() - t0, 2), "err": err})


def install_net_log():
    requests.get = _logged_get


# ----------------------------------------------------------------------------------------------------------------- #
# Geometry helpers
# ----------------------------------------------------------------------------------------------------------------- #
def utm_for(lon: float, lat: float) -> str:
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


def to_utm(geom, epsg: str):
    return transform(pyproj.Transformer.from_crs("EPSG:4326", epsg, always_xy=True).transform, geom)


def to_4326(geom, epsg: str):
    return transform(pyproj.Transformer.from_crs(epsg, "EPSG:4326", always_xy=True).transform, geom)


def hav_km(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))


def dist_km(g1, g2) -> float:
    if g1.intersects(g2):
        return 0.0
    c = g1.centroid; epsg = utm_for(c.x, c.y)
    try:
        return float(to_utm(g1, epsg).distance(to_utm(g2, epsg))) / 1000.0
    except Exception:
        return hav_km((c.x, c.y), (g2.centroid.x, g2.centroid.y))


def beamwidth(sonar: str):
    s = (sonar if isinstance(sonar, str) else "").lower().replace("-", " ")
    for k, v in BEAMWIDTH:
        if k in s or k.replace(" ", "") in s.replace(" ", ""):
            return v
    return None


def swath_factor(sonar: str):
    s = (sonar if isinstance(sonar, str) else "").lower().replace("-", " ")
    for k, v in SWATH_FACTOR:
        if k in s or k.replace(" ", "") in s.replace(" ", ""):
            return v
    return None


def status_of(rec: dict) -> tuple[str, str]:
    fails = []
    hr = rec.get("hr_res_m")
    if hr is None:
        fails.append("hr_res_m not readable")
    elif not (HR_MIN <= hr <= HR_MAX):
        fails.append(f"hr_res_m {hr:.3g} outside 0.985–4.99")
    if not rec.get("lr_cruise"):
        fails.append("no independent ship cruise")
    elif rec.get("lr_raw_downloadable") is False:
        fails.append("independent raw swath not downloadable")
    r = rec.get("ratio_est")
    if r is not None and r < RATIO_BAND:
        fails.append(f"ratio_est {r:.2f} < 4.5")
    c = rec.get("cells_across_est")
    if c is not None and not (CELLS_MIN <= c <= CELLS_MAX):
        fails.append(f"cells_across_est {c:.2f} outside 3.88–51.2")
    t = rec.get("tiles_est")
    if t is None:
        fails.append("tiles_est not computed")
    elif t < TILES_FLOOR:
        fails.append(f"tiles_est {t} < 300")
    if rec.get("releasable") not in ("yes", "yes_conditional"):
        fails.append("not releasable")
    return ("outside range", "; ".join(fails)) if fails else ("in range", "")


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str))
