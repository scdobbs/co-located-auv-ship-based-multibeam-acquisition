"""USGS CMGDS (cmgds.marine.usgs.gov) data-release fetcher.

The Cal DIG DOIs (10.5066/P97QM7NF, 10.5066/P9QQZ27U) resolve via doi.org to
the USGS Coastal/Marine Geoscience data-release portal rather than to
ScienceBase. CMGDS does not expose a separate REST API — the file URLs are
documented as ``/data-releases/media/...`` hrefs on the official landing
page. We treat those hrefs as the canonical download path (user-approved
deviation from the directive's "sciencebasepy" guidance, 2026-06-02).

This module provides ``prepare(doi, role, out_dir, kind, mosaic)`` which:
  1. fetches the landing page
  2. extracts media hrefs whose filename matches ``kind``
  3. downloads each (zip or tif) into out_dir
  4. unzips zips
  5. optionally mosaics multiple GeoTIFFs into a single output
  6. returns the path of the canonical raster + a provenance dict
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import requests
import rasterio

from .download import fetch


log = logging.getLogger(__name__)


BASE = "https://cmgds.marine.usgs.gov"
_HREF_RE = re.compile(r'href="(/data-releases/media/[^"]+)"')


@dataclass
class CMGDSResource:
    url: str
    filename: str


@dataclass
class CMGDSResult:
    tiles: list[Path]
    sources: list[CMGDSResource] = field(default_factory=list)
    landing_url: str = ""
    citation: str = ""
    license: str = "U.S. Geological Survey data release (public domain)"


def _landing_url(doi: str) -> str:
    suffix = doi.split("/", 1)[1]
    return f"{BASE}/data-releases/datarelease/10.5066-{suffix}/"


def _list_media(doi: str) -> list[CMGDSResource]:
    url = _landing_url(doi)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    hrefs = sorted(set(_HREF_RE.findall(r.text)))
    out: list[CMGDSResource] = []
    for h in hrefs:
        fname = h.rsplit("/", 1)[-1]
        out.append(CMGDSResource(url=f"{BASE}{h}", filename=fname))
    return out


def _filter(resources: list[CMGDSResource], kind: str) -> list[CMGDSResource]:
    """Filter to bathymetry zips/tifs; skip thumbnails, csvs, jpegs, metadata."""
    keep: list[CMGDSResource] = []
    for r in resources:
        name = r.filename.lower()
        if kind not in name:
            continue
        if not (name.endswith(".zip") or name.endswith(".tif") or name.endswith(".tiff")):
            continue
        if "thumbnail" in name:
            continue
        keep.append(r)
    return keep


def _unzip(zip_path: Path, dest: Path) -> list[Path]:
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = dest / Path(info.filename).name  # flatten
            with zf.open(info) as src, target.open("wb") as out:
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    out.write(b)
            extracted.append(target)
    return extracted


def prepare(
    *,
    doi: str,
    role: str,
    out_dir: Path,
    kind: Literal["bathy", "bathymetry"] = "bathy",
) -> CMGDSResult:
    """Download CMGDS bathymetry rasters for one DOI.

    Args:
        doi: USGS CMGDS DOI (resolves to cmgds.marine.usgs.gov landing page).
        role: 'hr' or 'lr' — used only to name output files.
        out_dir: per-pair raw directory on scratch.
        kind: filename substring used to keep only bathymetry files
              (rejects chirp/backscatter/substrate/etc.).

    Returns all extracted GeoTIFFs. Caller decides whether to mosaic, treat
    as separate sub-pairs, etc. For Cal DIG HR the release expands to ~19
    small dive-patch tiles scattered across the study area — those are
    individually smaller than the LR and should be paired per-tile.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    landing = _landing_url(doi)
    log.info("[%s] CMGDS landing %s", role, landing)
    media = _list_media(doi)
    sources = _filter(media, kind=kind)
    if not sources:
        raise RuntimeError(f"[{role}] no CMGDS '{kind}' rasters for DOI {doi}")

    tiles: list[Path] = []
    for src in sources:
        local = out_dir / f"{role}_{src.filename}"
        fetch(src.url, local)
        if local.suffix.lower() == ".zip":
            extract_dir = out_dir / f"{local.stem}_extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            for f in _unzip(local, extract_dir):
                if f.suffix.lower() in (".tif", ".tiff"):
                    tiles.append(f)
        elif local.suffix.lower() in (".tif", ".tiff"):
            tiles.append(local)

    if not tiles:
        raise RuntimeError(f"[{role}] CMGDS download for {doi} produced no GeoTIFFs")

    log.info("[%s] CMGDS %s yielded %d tile(s)", role, doi, len(tiles))
    return CMGDSResult(
        tiles=tiles,
        sources=sources,
        landing_url=landing,
        citation=f"USGS CMGDS data release {doi}",
    )
