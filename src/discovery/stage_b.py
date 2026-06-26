"""v1.5 Stage B — resolve true HR geometry for the `needs_geometry` set.

For each HR flagged ``footprint_suspect`` (or explicitly listed):
  1. Download each constituent file via MGDS FileDownloadServer.
  2. Decompress / extract as needed (``.grd.gz`` → ``.grd``;
     ``.zip`` → unpack).
  3. Open at downsampled resolution (≤1024×1024) — we only need the
     *coverage shape*, not the depth values; reading full-res 5-GB grids
     would be wasteful.
  4. Extract the valid-data polygon via ``rasterio.features.shapes`` on
     the (~nodata) mask.
  5. Union across files in the HR; reproject to EPSG:4326.
  6. Cache per HR (JSON WKB + metadata) so re-runs skip cleanly.
  7. Optionally purge the downloaded raw files (default: keep until
     batch completes, then sweep).

Read-only / append-only against the manifest. Writes only to:
  * ``$DATA_ROOT/discovery_cache/stage_b/<hr_id>/`` (download + cache)
  * ``reports/discovery/hr_catalog.gpkg`` (geometry update in place;
    this is a discovery artifact, not the harmonized manifest).
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
import pyproj
import rasterio
import requests
from rasterio.features import shapes
from shapely.geometry import shape, mapping
from shapely.ops import transform, unary_union
from shapely import wkb as shapely_wkb

from . import mgds as mgds_mod
from .. import gmt_grd as gmt_grd_mod


log = logging.getLogger(__name__)


# MGDS migrated its file-download endpoint mid-2026. The legacy
# ``marine-geo.org/services/FileDownloadServer`` URL now 301-redirects to a
# /tools/search/ path that 404s — but the *new* download endpoint at
# api.marine-geo.org works fine and still accepts ``data_uid``.
FILEDOWNLOAD_BASE = "https://api.marine-geo.org/services/download/Document_Accept.php"
_DOWNLOAD_PARAMS = {"client": "DataLink"}  # additional params; data_uid is added per-request
_HEADERS = {"User-Agent": "auv-ship-acq/0.1 (Sherlock; v1.5 stage_b)"}
_THROTTLE = 0.2
_TARGET_THUMB = 1024


@dataclass
class HRGeomResult:
    hr_id: str
    polygon_wkb: bytes | None
    area_km2: float
    n_files: int
    n_files_ok: int
    errors: list[str]
    total_bytes: int


def _polygon_area_km2(poly) -> float:
    """Equal-area projection for a single-polygon area in km^2."""
    if poly is None or poly.is_empty:
        return 0.0
    cx, cy = poly.centroid.x, poly.centroid.y
    tr = pyproj.Transformer.from_crs(
        "EPSG:4326",
        f"+proj=laea +lat_0={cy} +lon_0={cx} +ellps=WGS84",
        always_xy=True,
    ).transform
    return float(transform(tr, poly).area) / 1e6


def _native_to_4326(poly, src_crs: str):
    if str(src_crs).upper() in ("EPSG:4326", "WGS84"):
        return poly
    try:
        tr = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True).transform
        return transform(tr, poly)
    except Exception as e:
        log.warning("reproj %s -> 4326 failed: %s", src_crs, e)
        return None


def _valid_polygon_from_raster(path: Path) -> tuple[object | None, str]:
    """Return (poly_in_native_crs, native_crs_str). Reads downsampled."""
    candidates = [str(path)]
    # rasterio sometimes needs NETCDF: prefix for .nc / .grd
    if path.suffix.lower() in (".nc", ".grd"):
        candidates.append(f"NETCDF:{path}")
    last_err = None
    for cand in candidates:
        try:
            with rasterio.open(cand) as ds:
                if ds.crs is None:
                    last_err = "no CRS"
                    continue
                h, w = ds.height, ds.width
                if h == 0 or w == 0:
                    last_err = "empty raster"
                    continue
                sy = max(1, h // _TARGET_THUMB)
                sx = max(1, w // _TARGET_THUMB)
                arr = ds.read(1, out_shape=(h // sy, w // sx), masked=True)
                transform_d = ds.transform * ds.transform.scale(sx, sy)
                native_crs = ds.crs.to_string()
            # Materialise a 2-D uint8 valid-pixel mask. Masked arrays may
            # have scalar mask (False) when nothing is masked — broadcast
            # to the data shape.
            if hasattr(arr, "mask"):
                m = arr.mask
                if np.isscalar(m) or (hasattr(m, "ndim") and m.ndim == 0):
                    valid = np.ones(arr.shape, dtype="uint8") if not m else np.zeros(arr.shape, dtype="uint8")
                else:
                    valid = (~m).astype("uint8")
                # Belt-and-braces: drop any non-finite values the mask missed.
                finite = np.isfinite(np.asarray(arr.filled(0.0) if hasattr(arr, "filled") else arr, dtype="float32"))
                valid = (valid & finite.astype("uint8"))
            else:
                a = np.asarray(arr, dtype="float32")
                nd = getattr(ds, "nodata", None)
                if nd is not None:
                    valid = ((a != nd) & np.isfinite(a)).astype("uint8")
                else:
                    valid = np.isfinite(a).astype("uint8")
            if valid.ndim != 2:
                valid = np.squeeze(valid)
            if valid.ndim != 2:
                last_err = f"valid mask is {valid.ndim}D not 2D"
                continue
            if valid.sum() == 0:
                last_err = "no valid pixels"
                continue
            polys = [shape(g) for g, val in
                     shapes(valid, mask=valid.astype(bool), transform=transform_d)
                     if val == 1]
            if not polys:
                last_err = "no shapes"
                continue
            return unary_union(polys), native_crs
        except Exception as e:
            last_err = str(e)[:200]
    # Try GMT NetCDF Classic via custom converter
    if gmt_grd_mod.is_gmt_grd(path):
        try:
            tmp_tif = path.with_suffix(".converted.tif")
            gmt_grd_mod.convert(path, tmp_tif)
            poly, crs = _valid_polygon_from_raster(tmp_tif)
            try:
                tmp_tif.unlink()
            except FileNotFoundError:
                pass
            return poly, crs
        except Exception as e:
            last_err = f"gmt convert: {e}"
    raise RuntimeError(last_err or "could not extract polygon")


def _decompress(path: Path) -> list[Path]:
    """Expand .gz / .zip; return list of usable raster file paths."""
    suf = path.suffix.lower()
    if suf == ".gz":
        out = path.with_suffix("")  # strip .gz
        if not out.exists():
            with gzip.open(path, "rb") as src, out.open("wb") as dst:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    dst.write(chunk)
        return [out]
    if suf == ".zip":
        out_dir = path.with_suffix("_unzipped")
        out_dir.mkdir(parents=True, exist_ok=True)
        extracted: list[Path] = []
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = Path(info.filename).name
                target = out_dir / name
                if not target.exists():
                    with zf.open(info) as src, target.open("wb") as dst:
                        while True:
                            chunk = src.read(1 << 20)
                            if not chunk:
                                break
                            dst.write(chunk)
                if target.suffix.lower() in (".tif", ".tiff", ".grd", ".nc",
                                              ".asc", ".bag"):
                    extracted.append(target)
        return extracted
    return [path]


def _download_file(data_uid: str, out_dir: Path) -> Path | None:
    """Fetch a single MGDS file by data_uid; returns the local path."""
    sess = requests.Session()
    sess.headers.update(_HEADERS)
    out_dir.mkdir(parents=True, exist_ok=True)
    params = {**_DOWNLOAD_PARAMS, "data_uid": data_uid}
    # Stream the body; Content-Disposition gives the canonical filename.
    try:
        r = sess.get(FILEDOWNLOAD_BASE, params=params, stream=True,
                     timeout=600, allow_redirects=True)
        if r.status_code != 200:
            r.close()
            log.warning("download data_uid=%s status %s", data_uid, r.status_code)
            return None
        cd = r.headers.get("Content-Disposition", "")
        m = re.search(r'filename="?([^";]+)', cd)
        fname = m.group(1).strip() if m else f"data_uid_{data_uid}.bin"
        target = out_dir / fname
        if target.exists() and target.stat().st_size > 0:
            r.close()
            return target
        with target.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
        time.sleep(_THROTTLE)
        return target
    except Exception as e:
        log.warning("download data_uid=%s failed: %s", data_uid, e)
        return None


def resolve_one(hr_id: str, file_ids: str, work_root: Path, cache_dir: Path,
                purge_after: bool = True) -> HRGeomResult:
    """Resolve true geometry for a single HR."""
    cache_path = cache_dir / f"{hr_id.replace(':', '_')}.json"
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            poly = shapely_wkb.loads(bytes.fromhex(data["wkb_hex"])) if data.get("wkb_hex") else None
            return HRGeomResult(
                hr_id=hr_id, polygon_wkb=bytes.fromhex(data["wkb_hex"]) if data.get("wkb_hex") else None,
                area_km2=data.get("area_km2", 0.0),
                n_files=data.get("n_files", 0), n_files_ok=data.get("n_files_ok", 0),
                errors=data.get("errors", []),
                total_bytes=data.get("total_bytes", 0),
            )
        except Exception:
            pass

    uids = [u.strip() for u in file_ids.split(",") if u.strip()]
    hr_dir = work_root / hr_id.replace(":", "_")
    hr_dir.mkdir(parents=True, exist_ok=True)

    polys_4326 = []
    errors: list[str] = []
    n_ok = 0
    total_bytes = 0

    for uid in uids:
        path = _download_file(uid, hr_dir)
        if path is None:
            errors.append(f"download failed for data_uid={uid}")
            continue
        total_bytes += path.stat().st_size
        try:
            for raster_path in _decompress(path):
                try:
                    poly, src_crs = _valid_polygon_from_raster(raster_path)
                except Exception as e:
                    errors.append(f"{raster_path.name}: {e}")
                    continue
                if poly is None or poly.is_empty:
                    continue
                poly4326 = _native_to_4326(poly, src_crs)
                if poly4326 is None or poly4326.is_empty:
                    errors.append(f"{raster_path.name}: reproject 4326 failed")
                    continue
                polys_4326.append(poly4326)
                n_ok += 1
        except Exception as e:
            errors.append(f"{path.name}: {e}")

    if polys_4326:
        merged = unary_union(polys_4326)
        area_km2 = _polygon_area_km2(merged)
        wkb_hex = shapely_wkb.dumps(merged).hex()
    else:
        merged = None
        area_km2 = 0.0
        wkb_hex = None

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "hr_id": hr_id,
        "wkb_hex": wkb_hex,
        "area_km2": area_km2,
        "n_files": len(uids), "n_files_ok": n_ok,
        "errors": errors[:50],
        "total_bytes": total_bytes,
    }))

    if purge_after and hr_dir.exists():
        try:
            for p in hr_dir.rglob("*"):
                if p.is_file():
                    p.unlink()
            # remove any empty subdirs
            for p in sorted(hr_dir.rglob("*"), reverse=True):
                if p.is_dir():
                    try: p.rmdir()
                    except OSError: pass
            hr_dir.rmdir()
        except Exception:
            pass

    return HRGeomResult(
        hr_id=hr_id,
        polygon_wkb=bytes.fromhex(wkb_hex) if wkb_hex else None,
        area_km2=area_km2,
        n_files=len(uids), n_files_ok=n_ok,
        errors=errors,
        total_bytes=total_bytes,
    )


def apply_results(hr_path: Path, results: list[HRGeomResult]) -> None:
    """Update the HR catalog in place: writes geometry + footprint_km2 +
    clears footprint_suspect for HRs Stage B resolved, and records
    ``geometry_source`` ('stage_b_resolved' on success, 'stage_b_failed_no_crs'
    on failure) so the rebuild's footprint heuristic doesn't re-flag rows
    Stage B has already authoritatively measured.
    """
    hr = gpd.read_file(hr_path, layer="hr")
    if "footprint_km2" not in hr.columns:
        hr["footprint_km2"] = 0.0
    if "geometry_source" not in hr.columns:
        hr["geometry_source"] = "metadata_bbox"
    by_id = {r.hr_id: r for r in results}
    n_ok = 0
    n_failed = 0
    for i, row in hr.iterrows():
        r = by_id.get(row["hr_id"])
        if r is None:
            continue
        if r.polygon_wkb is not None and r.area_km2 > 0:
            new_poly = shapely_wkb.loads(r.polygon_wkb)
            hr.at[i, "geometry"] = new_poly
            hr.at[i, "footprint_km2"] = r.area_km2
            hr.at[i, "footprint_suspect"] = False
            hr.at[i, "geometry_source"] = "stage_b_resolved"
            note = f"Stage B resolved {r.area_km2:.2f} km^2 from {r.n_files_ok}/{r.n_files} files"
            n_ok += 1
        else:
            hr.at[i, "geometry_source"] = "stage_b_failed_no_crs"
            note = (f"Stage B failed: {len(r.errors)} file errors, "
                    f"{r.n_files_ok}/{r.n_files} files ok (likely .grd lacks CRS)")
            n_failed += 1
        if "description" in hr.columns:
            base = hr.at[i, "description"] or ""
            hr.at[i, "description"] = (base + " | " + note)[:1000]
    hr.to_file(hr_path, driver="GPKG", layer="hr")
    log.info("Stage B applied: %d resolved, %d failed-no-crs", n_ok, n_failed)


def run(needs_geometry_hr_ids: Iterable[str], hr_path: Path, work_root: Path,
        cache_dir: Path, purge_after: bool = True) -> list[HRGeomResult]:
    hr = gpd.read_file(hr_path, layer="hr")
    by_id = hr.set_index("hr_id")
    results: list[HRGeomResult] = []
    target_ids = list(needs_geometry_hr_ids)
    log.info("Stage B: %d HRs to resolve", len(target_ids))
    for hid in target_ids:
        if hid not in by_id.index:
            log.warning("Stage B: %s not in HR catalog", hid)
            continue
        row = by_id.loc[hid]
        file_ids = row.get("file_ids") or ""
        if not file_ids:
            log.warning("Stage B: %s has no file_ids", hid)
            continue
        log.info("Stage B [%s] %d files (%.1f MB est)",
                 hid, len(file_ids.split(",")), 0.0)
        try:
            r = resolve_one(hid, file_ids, work_root, cache_dir, purge_after=purge_after)
            log.info("  → %.2f km^2, %d/%d files ok, %d errors",
                     r.area_km2, r.n_files_ok, r.n_files, len(r.errors))
            results.append(r)
        except Exception as e:
            log.exception("Stage B [%s] failed: %s", hid, e)
    apply_results(hr_path, results)
    return results
