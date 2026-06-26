"""HR-format gate (re-audit carry-over C2) — reject RGB *visualization renders*.

The 2026-06-26 re-audit found that 9 harvested HR products were 3-band uint8
RGB slope/hillshade *renders* (e.g. MBARI `..._Topo1m_slope...` exports), not
float bathymetry. `materialize_hr` read band 1 = the red channel (0-255), which
produced the spurious "+255" elevations. These renders pass a visual look and a
depth-*range* sanity check (they resemble terrain), so the gate must be
**byte-level**, not visual.

Use `is_rgb_visualization()` at harvest/staging/tile-selection time to skip such
files, and `pick_elevation_tile()` to choose a genuine float-elevation tile.

A GMT `.grd` cannot be opened by rasterio directly; callers that handle `.grd`
(via `gmt_grd`) should treat it as elevation and not pass it here.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import rasterio

log = logging.getLogger(__name__)

_RGB = {"red", "green", "blue"}


def is_rgb_visualization(path) -> tuple[bool, str]:
    """True iff the raster is a 3+-band uint8 image with RGB color interpretation
    — i.e. a visualization render, not elevation. Also flags the case where a
    Terrain-RGB decode is the only way values could be elevation but is
    implausible. Returns (is_render, reason). Unreadable/`.grd` -> (False, ...)."""
    p = Path(path)
    if p.suffix.lower() == ".grd":
        return False, "grd_not_rgb"          # GMT float grid; handled elsewhere
    try:
        with rasterio.open(str(p)) as ds:
            ci = {c.name for c in ds.colorinterp}
            all_uint8 = all(d == "uint8" for d in ds.dtypes)
            multiband = ds.count >= 3
    except Exception as e:
        return False, f"unreadable:{str(e)[:40]}"
    if multiband and all_uint8 and (ci & _RGB):
        return True, f"rgb_uint8_render(count={ds.count},colorinterp={sorted(ci & _RGB)})"
    if multiband and all_uint8:
        return True, f"multiband_uint8_render(count={ds.count})"
    return False, "single_or_float"


def is_float_elevation(path) -> bool:
    """True iff the raster reads as single-band float/int with plausible
    seafloor depth magnitudes (handles negative-down and positive-down)."""
    p = Path(path)
    if p.suffix.lower() == ".grd":
        return True                          # GMT float grid
    try:
        with rasterio.open(str(p)) as ds:
            if ds.count != 1 or ds.dtypes[0] == "uint8":
                return False
            dec = max(1, int(((ds.width * ds.height) / 1e6) ** 0.5))
            a = ds.read(1, out_shape=(max(1, ds.height // dec), max(1, ds.width // dec))).astype("float64")
            nd = ds.nodata
        if nd is not None:
            a = a[~np.isclose(a, nd, atol=1e-3)]
        a = a[np.isfinite(a)]
        if a.size == 0:
            return False
        mag = np.percentile(np.abs(a), 50)
        return bool(5.0 <= mag <= 11000.0)   # plausible ocean depth in metres
    except Exception:
        return False


def pick_elevation_tile(tiles) -> Path | None:
    """From candidate HR tiles, return the largest genuine float-elevation tile,
    skipping RGB visualization renders. None if no elevation tile exists."""
    cands = sorted((Path(t) for t in tiles), key=lambda p: -p.stat().st_size)
    for t in cands:
        render, _ = is_rgb_visualization(t)
        if render:
            continue
        if is_float_elevation(t):
            return t
    return None
