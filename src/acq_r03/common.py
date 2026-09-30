"""ACQ-R03 shared paths and helpers. Importing installs the lockbox guard (via src.acq_r01.common)."""
from __future__ import annotations

import io
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from src.acq_r01 import common as C  # noqa: F401  (installs the lockbox guard)

REPORT_DIR = C.REPO / "reports_post_grl_review" / "ACQ-R03"
R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"
OAK = C.OAK
RAW_SWATH = C.RAW_SWATH_OAK
REVIEW_DIR = OAK / "review" / "acq_r03"
HEADERS = {"User-Agent": "auv-ship-acq/0.4 (Sherlock; ACQ-R03 PANGAEA footprint-subset fetch; stephencoledobbs@gmail.com)"}

# PANGAEA raw-swath datasets of the two development units (ACQ-R02 §4/§6; ACQ-R03 §1)
PANGAEA_UNITS = {
    "PANGAEA_864677": {"dataset": "864677", "doi": "10.1594/PANGAEA.864677", "cruise": "M114/1", "unit": "pu01",
                       "site": "Chapopote asphalt volcano (Gulf of Mexico)", "hr": "PANGAEA:889317",
                       "url_col": "URL all (Link to .all file)", "name_col": "File name (.all File)",
                       "size_col": "File size [kByte]", "geometry": "WKT (shiptrack geometry)"},
    "PANGAEA_892317": {"dataset": "892317", "doi": "10.1594/PANGAEA.892317", "cruise": "M112/1", "unit": "pu00",
                       "site": "Venere mud volcano (Ionian Sea)", "hr": "PANGAEA:884112",
                       "url_col": "URL file", "name_col": "File name", "size_col": "File size [kByte]", "geometry": None},
}
BUFFER_M = 4000.0          # the repo's nav-subset rule (ACQ-R02 fetch_plan: .fnv tracks ∩ HR footprint buffered by 4 km)
SIZE_TOL_B = 1024          # advertised kByte column ±1 kB


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tab_export_path(dataset: str) -> Path:
    return REPORT_DIR / f"pangaea_{dataset}_tab_export.txt"


def fetch_tab_export(dataset: str, refresh: bool = False) -> Path:
    """The dataset's tab export (verbatim), saved once in the report directory."""
    p = tab_export_path(dataset)
    if p.exists() and not refresh:
        return p
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    r = requests.get(f"https://doi.pangaea.de/10.1594/PANGAEA.{dataset}?format=textfile", headers=HEADERS, timeout=180)
    r.raise_for_status()
    p.write_text(r.text)
    return p


def parse_tab_export(path: Path) -> pd.DataFrame:
    """Data table of a PANGAEA tab export: everything after the closing '*/' of the metadata header."""
    lines = path.read_text().splitlines()
    s = next(i for i, l in enumerate(lines) if l.startswith("*/")) + 1
    return pd.read_csv(io.StringIO("\n".join(lines[s:])), sep="\t", dtype=str, keep_default_na=False)


def kbyte_to_bytes(s: str) -> int:
    return int(round(float(s) * 1024))


_KONGSBERG_TIME = re.compile(r"(?:^|_)(\d{4})_(\d{8})_(\d{6})_")


def kongsberg_start_time(name: str):
    """Start time encoded in a Kongsberg file name NNNN_YYYYMMDD_HHMMSS_*.all (also S0_NNNN_... )."""
    m = _KONGSBERG_TIME.search(name)
    if not m:
        return None
    return datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def utm_epsg(lon: float, lat: float) -> str:
    z = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + z}"


def hr_footprint_buffered(hr_id: str):
    """(buffered footprint polygon in local UTM, its EPSG, raw footprint area km2, buffered area km2)."""
    import geopandas as gpd
    fp = gpd.read_file(OAK / "raw_hr" / hr_id.replace(":", "_") / "footprint.geojson").set_crs("EPSG:4326", allow_override=True)
    c = fp.geometry.union_all().centroid
    epsg = utm_epsg(c.x, c.y)
    g = fp.to_crs(epsg).geometry.union_all()
    return g.buffer(BUFFER_M), epsg, g.area / 1e6, g.buffer(BUFFER_M).area / 1e6


def mbinfo_reads(path: Path, fmt: int = 58) -> tuple[bool, str]:
    """True when MB-System's mbinfo parses the file and reports at least one record."""
    path = Path(path)
    r = C.mb(["mbinfo", f"-F{fmt}", "-I", path.name], cwd=str(path.parent))
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"Number of Records:\s+(\d+)", out)
    ok = r.returncode == 0 and m is not None and int(m.group(1)) > 0
    return ok, (m.group(0) if m else out[-200:])


def load_manifest(cruise_dir: Path) -> dict:
    p = cruise_dir / "fetch_manifest.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"cruise": cruise_dir.name, "source": "PANGAEA (hs.pangaea.de), ACQ-R03 §1 footprint-subset fetch",
            "created": utc_now(), "files": []}


def save_manifest(cruise_dir: Path, man: dict) -> None:
    man["updated"] = utc_now()
    files = man.get("files", [])
    man["n_files_ok"] = len(files); man["n_files_failed"] = int(len(man.get("failed", []) or []))
    man["bytes_ok"] = int(sum(int(f.get("size", 0)) for f in files))
    p = cruise_dir / "fetch_manifest.json"
    if p.exists():
        p.chmod(0o644)
    p.write_text(json.dumps(man, indent=1, default=str))
    p.chmod(0o444)
    sums = cruise_dir / "SHA256SUMS"
    if sums.exists():
        sums.chmod(0o644)
    sums.write_text("".join(f"{f['sha256']}  {f['name']}\n" for f in files if f.get("sha256")))
    sums.chmod(0o444)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str))
