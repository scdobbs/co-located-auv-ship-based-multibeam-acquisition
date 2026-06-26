"""Phase 2 Stage A — raw-LR byte-size dry-run (non-destructive).

Goal (handoff brief §5 Stage A / §8.2): produce a *precise* total-GB figure
and a per-cruise size table for the raw NCEI MBBDB ship cruises that Phase 2
must fetch and grid. **No fetching of bulk data** — this only lists NCEI
directory indexes and sums the advertised file sizes.

Method
------
1. The 76 raw-LR *references* in ``staging_state_20260605.json`` collapse to a
   smaller set of *unique cruises* (one cruise can serve several HR). We size
   each unique cruise once.
2. Each cruise's authoritative data directory is read from the cruise's cached
   NCEI Geoportal ISO record (``sys_xml_clob``) — NOT constructed by hand, because
   the ship-name path segment is normalised unpredictably
   (``thomas_g._thompson`` vs ``thomas_g_thompson``).
3. We GET the Apache autoindex for that directory (cached to scratch so re-runs
   are idempotent and don't re-hit NCEI), recurse into any subdirectories, and
   sum the advertised file sizes.

Precision note
--------------
The autoindex advertises human-rounded sizes ("75M", "1.2G"), so each file
carries ~1% rounding error. These errors are random and uncorrelated, so the
*per-cruise* and *grand* totals are accurate to well within 1% — i.e. precise
to the GB, which is the tolerance the Gate-1 storage/retention decision needs.
The summed bytes are the **compressed download footprint** (the ``.all.mb*.gz``
files that will actually be fetched), which is exactly the figure Gate-1
question 1 (does it fit the scratch budget) requires. Uncompressed working size
during MB-System gridding is a separate Stage-C / ``$L_SCRATCH`` concern.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests


log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "auv-ship-acq/0.2 (Sherlock; phase2 stage-A dry-run; "
                          "stephencoledobbs@gmail.com)"}
_THROTTLE = 0.4          # polite gap between live NCEI requests
_MAX_DEPTH = 4           # safety cap on directory recursion

# Apache autoindex data row: <a href="NAME">..</a> ... <td ..>SIZE</td>
# SIZE is "-" for directories, else like "43K" / "75M" / "1.2G" / "512".
_ROW = re.compile(
    r'<a href="(?P<href>[^"?][^"]*)">[^<]*</a>\s*</td>'
    r'\s*<td[^>]*>[^<]*</td>'           # last-modified column
    r'\s*<td[^>]*>\s*(?P<size>[0-9.]+[KMGT]?|-)\s*</td>',
    re.I,
)

_UNIT = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}


def _human_to_bytes(s: str) -> int | None:
    """Convert an Apache autoindex size token to bytes. None for dirs ('-')."""
    s = s.strip()
    if s in ("-", ""):
        return None
    m = re.fullmatch(r"([0-9.]+)([KMGT]?)", s)
    if not m:
        return None
    return int(round(float(m.group(1)) * _UNIT[m.group(2)]))


def data_dir_from_iso(cruise: str, geoportal_cache: Path) -> str | None:
    """Pull the authoritative ``data.ngdc.noaa.gov/.../multibeam/...`` directory
    URL out of the cruise's cached Geoportal ISO record."""
    p = geoportal_cache / f"{cruise}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
        xml = d.get("_source", {}).get("sys_xml_clob", "")
    except Exception:
        return None
    urls = re.findall(r'https://data\.ngdc\.noaa\.gov/platforms/[^\s<"]+', xml)
    # Prefer the deepest multibeam data directory.
    mb = [u for u in dict.fromkeys(urls) if "/multibeam/" in u and "/data/" in u]
    if not mb:
        mb = [u for u in dict.fromkeys(urls) if "/multibeam/" in u]
    if not mb:
        return None
    u = sorted(mb, key=len)[-1]
    return u if u.endswith("/") else u + "/"


@dataclass
class CruiseSize:
    cruise: str
    data_url: str
    status: str = "ok"                 # ok | empty | lookup_failed
    n_files: int = 0
    total_bytes: int = 0
    ext_bytes: dict[str, int] = field(default_factory=dict)
    ext_counts: dict[str, int] = field(default_factory=dict)
    n_dirs_listed: int = 0
    note: str = ""


def _ship_segment_variants(data_url: str) -> list[str]:
    """The ISO sometimes records a verbose ship segment (``noaa_ship_..._(r337)``)
    that 404s; the live tree uses a stripped form (``okeanos_explorer``). Yield
    candidate ``.../multibeam/data/`` parents with normalised ship segments."""
    m = re.match(r"(.*/ships/)([^/]+)(/.+/multibeam/data/)", data_url)
    if not m:
        return []
    pre, ship, post = m.groups()
    cands = []
    for s in (ship,
              re.sub(r"^noaa_ship_", "", ship),
              re.sub(r"_\([^)]*\)$", "", ship),
              re.sub(r"_\([^)]*\)$", "", re.sub(r"^noaa_ship_", "", ship))):
        if s not in cands:
            cands.append(s)
    return [pre + s + post for s in cands]


def _pick_version_dir(parent: str, listing_cache: Path) -> str | None:
    """Given a ``.../multibeam/data/`` dir, return the deepest usable swath dir
    (highest version, MB/ subdir if present)."""
    html = _list_dir(parent, listing_cache)
    if html is None:
        return None
    versions = sorted(h for h in (mm.group("href") for mm in _ROW.finditer(html))
                      if h.endswith("/") and not h.startswith(("/", "?", "http")))
    for v in reversed(versions):
        for sub in ("MB/", ""):
            cand = urljoin(parent, v) + sub
            if _list_dir(cand, listing_cache) is not None:
                return cand
    return None


def resolve_data_dir(data_url: str, listing_cache: Path) -> tuple[str | None, str]:
    """Confirm the ISO data dir lists, else fall back to (a) discovering the real
    version subdir under ``.../multibeam/data/`` and (b) normalising the ship
    path segment. Returns (working_url, note); working_url None if nothing works.
    """
    if _list_dir(data_url, listing_cache) is not None:
        return data_url, ""
    base = re.match(r"(.*/multibeam/data/)", data_url)
    if not base:
        return None, "ISO path 404 and no /multibeam/data/ parent to probe"
    # Try the ISO-advertised parent first, then ship-segment variants.
    parents = [base.group(1)] + _ship_segment_variants(base.group(1))
    seen: set[str] = set()
    for parent in parents:
        if parent in seen:
            continue
        seen.add(parent)
        cand = _pick_version_dir(parent, listing_cache)
        if cand is not None:
            note = "" if parent == base.group(1) and cand.startswith(data_url[:len(parent)]) else \
                   f"ISO path 404; recovered via {cand}"
            return cand, note
    return None, f"ISO path 404; no usable version dir (tried {len(parents)} ship variants)"


def _list_dir(url: str, cache_dir: Path) -> str | None:
    """GET an autoindex page, caching the HTML to scratch. None on HTTP error."""
    key = re.sub(r"[^A-Za-z0-9]+", "_", url.replace("https://data.ngdc.noaa.gov/", ""))
    cache = cache_dir / f"{key}.html"
    if cache.exists():
        return cache.read_text(errors="replace")
    try:
        r = requests.get(url, headers=_HEADERS, timeout=60)
        time.sleep(_THROTTLE)
    except Exception as e:
        log.warning("list %s failed: %s", url, e)
        return None
    if r.status_code != 200:
        log.warning("list %s -> HTTP %s", url, r.status_code)
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(r.text, errors="replace")
    return r.text


def size_cruise(cruise: str, data_url: str, listing_cache: Path) -> CruiseSize:
    """Recursively sum advertised file sizes under a cruise's data directory."""
    cs = CruiseSize(cruise=cruise, data_url=data_url)
    stack = [(data_url, 0)]
    seen: set[str] = set()
    while stack:
        url, depth = stack.pop()
        if url in seen:
            continue
        seen.add(url)
        html = _list_dir(url, listing_cache)
        if html is None:
            if url == data_url:
                cs.status = "lookup_failed"
                cs.note = "data directory returned HTTP error"
                return cs
            cs.note += f"subdir error: {url}; "
            continue
        cs.n_dirs_listed += 1
        for m in _ROW.finditer(html):
            href = m.group("href")
            if href.startswith(("/", "?")) or href.startswith("http"):
                continue                       # sort links / parent / absolute nav
            if href.endswith("/"):             # subdirectory
                if depth + 1 <= _MAX_DEPTH:
                    stack.append((urljoin(url, href), depth + 1))
                continue
            nbytes = _human_to_bytes(m.group("size"))
            if nbytes is None:
                continue
            ext = _ext_of(href)
            cs.n_files += 1
            cs.total_bytes += nbytes
            cs.ext_bytes[ext] = cs.ext_bytes.get(ext, 0) + nbytes
            cs.ext_counts[ext] = cs.ext_counts.get(ext, 0) + 1
    if cs.n_files == 0 and cs.status == "ok":
        cs.status = "empty"
        cs.note += "no data files found in listing; "
    return cs


def _ext_of(name: str) -> str:
    n = name.lower()
    for suf in (".all.mb58.gz", ".all.mb59.gz", ".gsf.mb121.gz", ".mb58.gz",
                ".mb59.gz", ".mb88.gz", ".all.gz", ".gsf.gz"):
        if n.endswith(suf):
            return suf
    # fall back to last two dotted components if gz, else last
    if n.endswith(".gz"):
        parts = n.split(".")
        return "." + ".".join(parts[-2:])
    return "." + n.split(".")[-1] if "." in n else "(none)"
