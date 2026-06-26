"""PANGAEA DOI → attached raster URLs + citation.

Two discovery paths:
  1. Standard: parse the dataset's metaxml for ``hs.pangaea.de/...`` URLs.
     This works for "simple" PANGAEA releases (e.g. DISCOL, the CCZ AUV +
     ship products) where the dataset wraps a small number of files.
  2. Tabular-dataset fallback (added for AtlantOS-style multi-file
     releases like M127 868686): fetch ``?format=textfile`` and parse the
     data-row table for ``URL file`` columns. Filter to bathymetric grids
     by ``Content`` (skip magnetic anomaly, backscatter, ship track,
     ungridded soundings, area shapefile, etc.).
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field

import requests
from pangaeapy import PanDataSet


log = logging.getLogger(__name__)


_RASTER_EXTS = (".tif", ".tiff", ".geotiff", ".nc", ".grd")
_URL_RE = re.compile(r"https?://[^<>\s\"']+")

# Filename / description fragments that indicate a non-bathymetric product
# even when the file extension says raster. Drop magnetic anomaly, backscatter,
# water column, ship track shapefile zips, etc.
_NON_BATHY_HINTS = (
    "magnetic", "backscatter", "track", "shapefile", "watercolumn",
    "water_column", "anomaly",
)
_BATHY_HINTS = ("bathy", "topo", "depth", "grid")


@dataclass
class PangaeaResource:
    url: str
    filename: str
    size_bytes: int | None = None


@dataclass
class PangaeaRecord:
    doi: str
    title: str
    citation: str
    license: str
    abstract: str
    rasters: list[PangaeaResource] = field(default_factory=list)
    raw_metadata: dict = field(default_factory=dict)


def _doi_to_id(doi: str) -> int:
    m = re.search(r"PANGAEA\.(\d+)", doi)
    if not m:
        raise ValueError(f"can't parse PANGAEA DOI: {doi}")
    return int(m.group(1))


def _license_str(lic) -> str:
    if lic is None:
        return ""
    for attr in ("uri", "label", "name", "code"):
        v = getattr(lic, attr, None)
        if v:
            return str(v)
    return str(lic)


def _filter_raster_url(url: str) -> bool:
    u = url.lower()
    if not u.endswith(_RASTER_EXTS):
        return False
    name = u.rsplit("/", 1)[-1]
    if any(h in name for h in _NON_BATHY_HINTS):
        return False
    return True


def _rasters_from_textfile(doi: str) -> list[PangaeaResource]:
    """Fallback for tabular PANGAEA datasets: pull the textfile data table
    and parse rows whose Content describes a bathymetric grid + whose URL
    points to a raster file.
    """
    try:
        r = requests.get(f"https://doi.pangaea.de/{doi}?format=textfile", timeout=30,
                         headers={"User-Agent": "auv-ship-acq/0.1"})
        r.raise_for_status()
    except Exception as e:
        log.warning("PANGAEA %s textfile fetch failed: %s", doi, e)
        return []
    text = r.text
    if "*/" not in text:
        return []
    _, _, data = text.partition("*/")
    data = data.lstrip("\n")
    reader = csv.DictReader(io.StringIO(data), delimiter="\t")
    out: list[PangaeaResource] = []
    for row in reader:
        url = (row.get("URL file") or "").strip()
        if not url:
            continue
        if not _filter_raster_url(url):
            continue
        content = (row.get("Content") or "").lower()
        name = url.rsplit("/", 1)[-1].lower()
        if any(h in content for h in _NON_BATHY_HINTS) or any(h in name for h in _NON_BATHY_HINTS):
            continue
        # Prefer hits that look bathymetric; skip XYZ ungridded soundings etc.
        # (URL filter already enforces extensions; the content guard catches
        # non-bathy products that happen to be GeoTIFFs.)
        if not any(h in content for h in _BATHY_HINTS) and not any(h in name for h in _BATHY_HINTS):
            continue
        size = None
        sz = row.get("File size [kByte]") or row.get("File size [Byte]")
        try:
            size = int(float(sz)) * 1024 if "kByte" in (row or {}) else int(float(sz))
        except Exception:
            pass
        out.append(PangaeaResource(url=url, filename=url.rsplit("/", 1)[-1], size_bytes=size))
    return out


def resolve(doi: str) -> PangaeaRecord:
    pid = _doi_to_id(doi)
    ds = PanDataSet(pid, enable_cache=False)
    urls = set(_URL_RE.findall(ds.metaxml or ""))
    rasters: list[PangaeaResource] = []
    for u in sorted(urls):
        u = u.rstrip("/.,;)")
        if _filter_raster_url(u):
            rasters.append(PangaeaResource(url=u, filename=u.rsplit("/", 1)[-1]))
    if not rasters:
        # Fallback for tabular-dataset releases (e.g. AtlantOS M127 868686)
        # where the raster URLs are in the data table, not the metaxml.
        log.info("PANGAEA %s: metaxml had no rasters; trying textfile fallback", doi)
        rasters = _rasters_from_textfile(doi)
    if not rasters:
        log.warning("PANGAEA %s: no rasters found in metaxml OR textfile; URI=%s", doi, ds.uri)
    return PangaeaRecord(
        doi=doi,
        title=ds.title or "",
        citation=ds.citation or "",
        license=_license_str(getattr(ds, "licence", None)),
        abstract=getattr(ds, "abstract", "") or "",
        rasters=rasters,
        raw_metadata={
            "id": ds.id,
            "uri": ds.uri,
            "date": getattr(ds, "date", None),
            "year": getattr(ds, "year", None),
            "geometryextent": getattr(ds, "geometryextent", None),
            "mintimeextent": getattr(ds, "mintimeextent", None),
            "maxtimeextent": getattr(ds, "maxtimeextent", None),
        },
    )
