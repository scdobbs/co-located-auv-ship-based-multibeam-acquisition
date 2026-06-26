"""USGS ScienceBase DOI → raster file URLs + citation.

Uses sciencebasepy to resolve a DOI to a ScienceBase item, then walks its
files/children for downloadable rasters. We surface URLs and let
src.download.fetch handle resume + checksum.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Iterable

from sciencebasepy import SbSession


log = logging.getLogger(__name__)


_RASTER_EXTS = (".tif", ".tiff", ".geotiff", ".nc", ".bag")


@dataclass
class SBResource:
    url: str
    filename: str
    size_bytes: int | None = None
    parent_item_id: str = ""
    title: str = ""


@dataclass
class SBRecord:
    doi: str
    item_id: str
    title: str
    citation: str
    license: str
    rasters: list[SBResource] = field(default_factory=list)
    raw_metadata: dict = field(default_factory=dict)


_DOI_RE = re.compile(r"10\.5066/[A-Z0-9]+", re.I)


def _normalise_doi(doi: str) -> str:
    m = _DOI_RE.search(doi)
    if not m:
        raise ValueError(f"not a ScienceBase DOI: {doi!r}")
    return m.group(0).upper()


def _resolve_item_id(sb: SbSession, doi: str) -> str:
    doi_n = _normalise_doi(doi)
    # ScienceBase supports lookup by DOI via the search API.
    hits = sb.find_items({"q": "", "filter": f"doi={doi_n.lower()}"})
    items = hits.get("items", []) if isinstance(hits, dict) else []
    for it in items:
        if (it.get("identifiers") or []):
            for ident in it["identifiers"]:
                if ident.get("key", "").lower() == doi_n.lower() or ident.get("value", "").lower() == doi_n.lower():
                    return it["id"]
        # Some records store DOI in summary; fall through
    if items:
        return items[0]["id"]
    raise LookupError(f"no ScienceBase item found for DOI {doi}")


def _iter_files(sb: SbSession, item_id: str, depth: int = 0, max_depth: int = 4) -> Iterable[SBResource]:
    if depth > max_depth:
        return
    item = sb.get_item(item_id)
    for f in item.get("files", []) or []:
        url = f.get("url") or f.get("downloadUri")
        name = f.get("name") or (url.rsplit("/", 1)[-1] if url else "")
        if url and name.lower().endswith(_RASTER_EXTS):
            yield SBResource(
                url=url,
                filename=name,
                size_bytes=f.get("size"),
                parent_item_id=item_id,
                title=item.get("title", ""),
            )
    for child in sb.get_child_ids(item_id) or []:
        yield from _iter_files(sb, child, depth=depth + 1, max_depth=max_depth)


def resolve(doi: str) -> SBRecord:
    sb = SbSession()  # anonymous; public data only
    item_id = _resolve_item_id(sb, doi)
    item = sb.get_item(item_id)
    citation = item.get("citation") or ""
    rights = ((item.get("rights") or "").strip()
              or "U.S. Geological Survey data release (public domain unless noted)")
    rasters = list(_iter_files(sb, item_id))
    if not rasters:
        log.warning("No rasters discovered under ScienceBase item %s for DOI %s", item_id, doi)
    return SBRecord(
        doi=doi,
        item_id=item_id,
        title=item.get("title", ""),
        citation=citation,
        license=rights,
        rasters=rasters,
        raw_metadata={"item_id": item_id, "link": item.get("link")},
    )
