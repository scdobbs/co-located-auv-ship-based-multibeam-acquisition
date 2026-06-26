"""Convert a GMT NetCDF Classic-format .grd file to a GeoTIFF.

The legacy GMT format (used by some PANGAEA AtlantOS releases — e.g. M127
868686 transit grids) stores the grid as a 1-D ``z`` array of length
``xysize`` plus scalar metadata variables (``x_range``, ``y_range``,
``spacing``, ``dimension``). GDAL's standard NetCDF driver can't open this
shape directly — we reshape to 2-D and write a tiled GeoTIFF that the rest
of the pipeline can treat as a normal raster.

The CRS is not stored in the .grd file itself; the caller passes it
explicitly (typically extracted from the filename, e.g. ``UTM24N`` →
``EPSG:32624``).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import netCDF4 as nc
import numpy as np
import rasterio
from rasterio.transform import from_bounds


log = logging.getLogger(__name__)


_UTM_FROM_FILENAME = re.compile(r"UTM(\d{1,2})([NS])", re.I)


def crs_from_filename(name: str) -> str | None:
    """Best-effort CRS guess from the AtlantOS filename convention."""
    m = _UTM_FROM_FILENAME.search(name)
    if not m:
        return None
    zone = int(m.group(1))
    hemi = m.group(2).upper()
    epsg = (32600 if hemi == "N" else 32700) + zone
    return f"EPSG:{epsg}"


def is_gmt_grd(path: Path) -> bool:
    """Sniff for GMT NetCDF Classic format: starts with CDF magic and has
    the GMT-specific structure (1-D ``z``, ``x_range``, ``y_range``)."""
    p = Path(path)
    if p.suffix.lower() != ".grd":
        return False
    try:
        with p.open("rb") as f:
            head = f.read(4)
        if head[:3] != b"CDF":
            return False
        with nc.Dataset(p, "r") as ds:
            return ("z" in ds.variables
                    and ds.variables["z"].ndim == 1
                    and "x_range" in ds.variables
                    and "dimension" in ds.variables)
    except Exception:
        return False


def convert(in_path: Path, out_path: Path,
            crs: str | None = None, nodata: float = -9999.0) -> Path:
    """Read a GMT NetCDF Classic .grd and write a GeoTIFF.

    Returns the output path on success; raises on bad format.
    """
    in_path = Path(in_path); out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    crs_str = crs or crs_from_filename(in_path.name) or "EPSG:4326"

    with nc.Dataset(in_path, "r") as ds:
        z_flat = np.asarray(ds.variables["z"][:], dtype=np.float32)
        nx, ny = int(ds.variables["dimension"][0]), int(ds.variables["dimension"][1])
        x0, x1 = (float(v) for v in ds.variables["x_range"][:])
        y0, y1 = (float(v) for v in ds.variables["y_range"][:])

    if z_flat.size != nx * ny:
        raise ValueError(
            f"{in_path.name}: z has {z_flat.size} elements but dimension says {nx}*{ny}={nx*ny}"
        )
    # GMT layout: row-major from TOP-left (i.e. north-most row first).
    arr = z_flat.reshape(ny, nx)
    # Replace the GMT nodata sentinel (typically NaN already, but be defensive).
    arr = np.where(np.isfinite(arr), arr, np.float32(nodata))

    transform = from_bounds(x0, y0, x1, y1, nx, ny)
    profile = {
        "driver": "GTiff", "height": ny, "width": nx, "count": 1,
        "dtype": "float32", "crs": crs_str, "transform": transform,
        "nodata": nodata, "compress": "DEFLATE", "tiled": True,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(arr, 1)
    log.info("GMT-grd → GeoTIFF: %s → %s (%d x %d, %s)",
             in_path.name, out_path.name, nx, ny, crs_str)
    return out_path
