"""v1.5.2 CRS recovery for Stage-B-failed-no-CRS HRs.

Many MGDS GMT ``.grd`` files were rejected by Stage B not because the
underlying data is bad but because the file lacks an embedded CRS tag.
This module attempts a **metadata-first** recovery, falling back to
**constrained inference** from the grid's coordinate ranges, and
**verifies every candidate CRS** against an independent statement of
geographic location (the MGDS ``geographic_extent`` bbox) before
accepting it.

Hard rules (per acquisition_directive_v1.5.2):
  * Recovery only runs on the CRS-failure subset; ratio rejects are
    never touched.
  * No blind EPSG:4326 assumption — inference is bounded by the grid's
    coordinate magnitudes.
  * Every CRS (metadata or inferred) is verified against the MGDS bbox
    or the grid stays excluded.
  * Read-only / append-only: writes only ``geometry_source = 'crs_recovered'``
    + ``recovered_crs`` columns on hr_catalog, plus per-HR cache JSON
    under ``$DATA_ROOT/discovery_cache/crs_recovery/``.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path

import re
import geopandas as gpd
import netCDF4 as nc
import numpy as np
import pyproj
import rasterio
from rasterio.transform import from_bounds
from shapely.geometry import box
from shapely.ops import transform, unary_union
from shapely.validation import make_valid
from shapely import wkb as shapely_wkb

from . import stage_b as stage_b_mod
from .. import gmt_grd as gmt_grd_mod


log = logging.getLogger(__name__)


_MGDS_NS = {"m": "http://www.marine-geo.org/services/xml/mgdsDataService"}


# Verification tolerance for the bbox check: recovered grid's geographic
# extent must overlap the ISO bbox by at least this fraction of the
# recovered extent (intersection-over-self). 0.8 = 80% of the grid sits
# inside the stated bbox. Tighter than IoU; the ISO bbox can be larger
# than the actual grid (it covers the whole dataset), but the grid must
# sit mostly inside the stated region.
_VERIFY_OVERLAP_MIN = 0.8


@dataclass
class RecoveryResult:
    hr_id: str
    status: str                      # crs_recovered | crs_unrecoverable | crs_failed_verification
    crs_source: str | None           # metadata | inferred_geographic | inferred_utm
    inferred_crs: str | None         # EPSG:xxxx
    iso_bbox: tuple[float, float, float, float] | None  # (W, S, E, N)
    grid_bbox_4326: tuple[float, float, float, float] | None
    overlap_fraction: float | None
    polygon_wkb_hex: str | None
    area_km2: float
    n_files: int
    n_files_ok: int
    reason: str
    notes: list[str]


# ---------- MGDS bbox lookup ----------

def load_mgds_bboxes(data_set_xml: Path) -> dict[str, tuple[float, float, float, float]]:
    """Return ``{uid: (W, S, E, N)}`` for every MGDS data_set."""
    root = ET.fromstring(data_set_xml.read_bytes())
    ds_list = root.find("m:data_sets", _MGDS_NS)
    out: dict[str, tuple[float, float, float, float]] = {}
    if ds_list is None:
        return out
    for ds in ds_list:
        uid = ds.get("uid")
        if not uid:
            continue
        ge = ds.find("m:details/m:geographic_extent", _MGDS_NS)
        if ge is None:
            ge = ds.find(".//{http://www.marine-geo.org/services/xml/mgdsDataService}geographic_extent")
        if ge is None:
            continue
        try:
            w = float(ge.get("westernmost"))
            e = float(ge.get("easternmost"))
            s = float(ge.get("southernmost"))
            n = float(ge.get("northernmost"))
        except (TypeError, ValueError):
            continue
        out[uid] = (w, s, e, n)
    return out


# ---------- .grd header read ----------

@dataclass
class GrdHeader:
    layout: str                         # 'gmt_classic' or 'gmt_v6'
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    nx: int
    ny: int
    metadata_crs_hint: str | None       # 'geographic' / 'projected' / None
    metadata_source: str | None         # which attr/long_name provided the hint


_ASC_UTM_HINT = re.compile(r"(?:^|_)(utm|u)(?:[._]|$)", re.I)


def read_asc_header(path: Path) -> GrdHeader | None:
    """Read an ESRI ASCII Grid (.asc) header.

    Header lines (case-insensitive):
      ncols, nrows, xllcorner|xllcenter, yllcorner|yllcenter, cellsize,
      NODATA_value.

    No CRS is embedded; a filename containing ``_utm`` or ``_u`` is
    recorded as a *hint* only — still subject to §2 verification.
    """
    try:
        with path.open("r", encoding="latin-1", errors="replace") as f:
            head: dict[str, float] = {}
            corner_is_center = False
            for _ in range(8):
                line = f.readline()
                if not line:
                    break
                parts = line.strip().split()
                if len(parts) < 2:
                    continue
                k = parts[0].lower()
                try:
                    v = float(parts[1])
                except ValueError:
                    continue
                head[k] = v
                if k == "xllcenter":
                    head["xllcorner"] = v
                    corner_is_center = True
                if k == "yllcenter":
                    head["yllcorner"] = v
                    corner_is_center = True
        if not {"ncols", "nrows", "xllcorner", "yllcorner", "cellsize"} <= head.keys():
            return None
        nx = int(head["ncols"]); ny = int(head["nrows"])
        cs = float(head["cellsize"])
        x_min = float(head["xllcorner"])
        y_min = float(head["yllcorner"])
        if corner_is_center:
            x_min -= cs / 2.0
            y_min -= cs / 2.0
        x_max = x_min + nx * cs
        y_max = y_min + ny * cs
        hint = None
        src = None
        if _ASC_UTM_HINT.search(path.name):
            hint = "projected"
            src = f"filename '{path.name}' contains UTM hint"
        return GrdHeader(
            layout="esri_asc",
            x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max,
            nx=nx, ny=ny,
            metadata_crs_hint=hint, metadata_source=src,
        )
    except Exception as e:
        log.warning("read_asc_header %s: %s", path.name, e)
        return None


def convert_asc_with_crs(in_path: Path, out_path: Path, crs_str: str,
                         nodata: float = -9999.0) -> Path:
    """Stamp a CRS onto an ESRI ASCII Grid by writing a sidecar .prj
    then translating to GeoTIFF via GDAL (rasterio).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prj = in_path.with_suffix(".prj")
    crs_obj = pyproj.CRS.from_user_input(crs_str)
    prj.write_text(crs_obj.to_wkt())
    try:
        with rasterio.open(in_path) as src:
            data = src.read(1)
            profile = src.profile.copy()
            # ESRI ASCII grids commonly have ncols/nrows that aren't
            # multiples of 16 — leave the output untiled (stripped) so
            # GDAL doesn't error on the alignment requirement.
            profile.update({
                "driver": "GTiff", "crs": crs_str,
                "compress": "DEFLATE", "tiled": False,
                "BIGTIFF": "IF_SAFER",
            })
            for k in ("blockxsize", "blockysize"):
                profile.pop(k, None)
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(data, 1)
    finally:
        try: prj.unlink()
        except FileNotFoundError: pass
    return out_path


def read_grd_header(path: Path) -> GrdHeader | None:
    """Read coordinate ranges + projection hints from a GMT ``.grd``.

    Supports both the classic 1-D-``z`` layout (``x_range``/``y_range`` /
    ``dimension`` variables) and the GMT-v6 / COARDS-CF 2-D layout
    (``x``, ``y``, ``z`` variables with ``actual_range`` attributes and
    ``long_name='Longitude'``/``'Latitude'``).
    """
    try:
        with nc.Dataset(path, "r") as ds:
            vars_ = list(ds.variables.keys())
            # Classic GMT layout
            if ("x_range" in vars_ and "y_range" in vars_
                    and "z" in vars_ and ds.variables["z"].ndim == 1):
                xr = ds.variables["x_range"][:]
                yr = ds.variables["y_range"][:]
                dim = ds.variables["dimension"][:]
                return GrdHeader(
                    layout="gmt_classic",
                    x_min=float(xr[0]), x_max=float(xr[1]),
                    y_min=float(yr[0]), y_max=float(yr[1]),
                    nx=int(dim[0]), ny=int(dim[1]),
                    metadata_crs_hint=None, metadata_source=None,
                )
            # GMT-v6 / CF 2-D layout
            if ("x" in vars_ and "y" in vars_ and "z" in vars_
                    and ds.variables["z"].ndim == 2):
                x = ds.variables["x"]
                y = ds.variables["y"]
                z = ds.variables["z"]
                # Prefer actual_range attribute (cheap; avoids reading full array).
                if "actual_range" in x.ncattrs():
                    xr = x.getncattr("actual_range")
                    x_min, x_max = float(xr[0]), float(xr[1])
                else:
                    arr = x[:]
                    x_min, x_max = float(arr.min()), float(arr.max())
                if "actual_range" in y.ncattrs():
                    yr = y.getncattr("actual_range")
                    y_min, y_max = float(yr[0]), float(yr[1])
                else:
                    arr = y[:]
                    y_min, y_max = float(arr.min()), float(arr.max())
                # Pull projection hint from long_names + description.
                xln = x.getncattr("long_name") if "long_name" in x.ncattrs() else ""
                yln = y.getncattr("long_name") if "long_name" in y.ncattrs() else ""
                desc = ds.getncattr("description") if "description" in ds.ncattrs() else ""
                hint, src = None, None
                if "Longitude" in str(xln) and "Latitude" in str(yln):
                    hint, src = "geographic", "long_name=Longitude/Latitude"
                elif "Easting" in str(xln) and "Northing" in str(yln):
                    hint, src = "projected", "long_name=Easting/Northing"
                if "Projection: Geographic" in str(desc):
                    hint, src = "geographic", (src + " + description=Projection:Geographic"
                                               if src else "description=Projection:Geographic")
                ny, nx = z.shape       # z is (rows=y, cols=x)
                return GrdHeader(
                    layout="gmt_v6",
                    x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max,
                    nx=int(nx), ny=int(ny),
                    metadata_crs_hint=hint, metadata_source=src,
                )
    except Exception as e:
        log.warning("read_grd_header %s: %s", path.name, e)
    return None


# ---------- CRS inference (per §1) ----------

def infer_crs(hdr: GrdHeader,
              iso_bbox: tuple[float, float, float, float] | None
              ) -> tuple[str | None, str, str]:
    """Return ``(epsg_or_None, crs_source, rule_fired)``.

    Per directive §1: metadata-first, then constrained inference from the
    grid coordinate ranges, then UTM with the zone derived from the ISO
    bbox centroid. ``crs_source`` is ``metadata`` whenever an embedded
    ``long_name``/``description`` field stated the projection (still
    subject to §2 verification).
    """
    x_min, x_max, y_min, y_max = hdr.x_min, hdr.x_max, hdr.y_min, hdr.y_max
    x_abs = max(abs(x_min), abs(x_max))
    y_abs = max(abs(y_min), abs(y_max))

    # §1.1 — metadata-stated projection. Stated geographic ⇒ EPSG:4326
    # IFF the coordinate magnitudes also pass the bound (don't trust a
    # stated CRS that's incompatible with its own data).
    if hdr.metadata_crs_hint == "geographic" and x_abs <= 360.5 and y_abs <= 90.5:
        return ("EPSG:4326", "metadata",
                f"{hdr.metadata_source}; x∈[{x_min:.3f},{x_max:.3f}] "
                f"y∈[{y_min:.3f},{y_max:.3f}] consistent")

    # §1.2 — constrained inference (no metadata, or metadata insufficient).
    if x_abs <= 360.5 and y_abs <= 90.5:
        return ("EPSG:4326", "inferred_geographic",
                f"x_range=[{x_min:.3f},{x_max:.3f}] y_range=[{y_min:.3f},{y_max:.3f}] "
                "consistent with geographic deg")

    if 1e4 <= x_abs <= 1.1e6 and y_abs <= 1.1e7 and y_abs >= 1e4:
        if iso_bbox is None:
            return (None, "inferred_utm",
                    "UTM-shaped coords but no ISO bbox to pick zone")
        w, s, e, n = iso_bbox
        centroid_lon = (w + e) / 2.0
        centroid_lat = (s + n) / 2.0
        zone = int((centroid_lon + 180.0) // 6.0) + 1
        zone = max(1, min(60, zone))
        epsg = (32600 if centroid_lat >= 0 else 32700) + zone
        return (f"EPSG:{epsg}", "inferred_utm",
                f"x_range=[{x_min:.0f},{x_max:.0f}] y_range=[{y_min:.0f},{y_max:.0f}]; "
                f"ISO centroid lon={centroid_lon:.2f} lat={centroid_lat:.2f} → UTM zone {zone}")

    return (None, "unknown",
            f"x_range=[{x_min:.3g},{x_max:.3g}] y_range=[{y_min:.3g},{y_max:.3g}] "
            "fits neither geographic nor UTM pattern cleanly")


# ---------- 2-D NetCDF → GeoTIFF with explicit CRS ----------

def convert_v6_with_crs(in_path: Path, out_path: Path, crs_str: str,
                        nodata: float = -9999.0) -> Path:
    """Write a GeoTIFF from a GMT-v6 / COARDS 2-D NetCDF, stamping the
    supplied CRS. Used after CRS recovery so the existing Stage-B
    valid-mask polygon extractor can read it.
    """
    in_path = Path(in_path); out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with nc.Dataset(in_path, "r") as ds:
        z = np.asarray(ds.variables["z"][:], dtype=np.float32)
        x = np.asarray(ds.variables["x"][:], dtype=np.float64)
        y = np.asarray(ds.variables["y"][:], dtype=np.float64)
    ny, nx = z.shape
    x_min, x_max = float(x.min()), float(x.max())
    y_min, y_max = float(y.min()), float(y.max())
    # GMT y is typically ascending (south→north); rasterio expects rows
    # top-down (north→south). Flip if needed.
    if y[0] < y[-1]:
        z = z[::-1, :]
    z = np.where(np.isfinite(z), z, np.float32(nodata))
    transform_d = from_bounds(x_min, y_min, x_max, y_max, nx, ny)
    profile = {
        "driver": "GTiff", "height": ny, "width": nx, "count": 1,
        "dtype": "float32", "crs": crs_str, "transform": transform_d,
        "nodata": nodata, "compress": "DEFLATE", "tiled": True,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(z, 1)
    log.debug("v6→GeoTIFF: %s → %s (%d×%d, %s)",
              in_path.name, out_path.name, nx, ny, crs_str)
    return out_path


# ---------- verification (per §2) ----------

def verify_against_iso(x_min: float, x_max: float, y_min: float, y_max: float,
                       crs_str: str, iso_bbox: tuple[float, float, float, float]
                       ) -> tuple[bool, float, tuple[float, float, float, float]]:
    """Reproject the grid bbox to EPSG:4326, compute its overlap with the
    ISO bbox. Returns ``(ok, overlap_fraction, grid_bbox_4326)``.
    """
    grid = box(x_min, y_min, x_max, y_max)
    if crs_str.upper() != "EPSG:4326":
        try:
            tr = pyproj.Transformer.from_crs(crs_str, "EPSG:4326",
                                             always_xy=True).transform
            grid_4326 = transform(tr, grid)
        except Exception as e:
            log.warning("verify reproj failed: %s", e)
            return False, 0.0, (0.0, 0.0, 0.0, 0.0)
    else:
        grid_4326 = grid

    g_w, g_s, g_e, g_n = grid_4326.bounds
    iso = box(*[iso_bbox[0], iso_bbox[1], iso_bbox[2], iso_bbox[3]])
    inter = grid_4326.intersection(iso)
    if grid_4326.is_empty or grid_4326.area == 0:
        return False, 0.0, (g_w, g_s, g_e, g_n)
    frac = float(inter.area / grid_4326.area)
    return frac >= _VERIFY_OVERLAP_MIN, frac, (g_w, g_s, g_e, g_n)


# ---------- per-HR recovery ----------

def recover_one(hr_id: str, file_ids: str,
                iso_bbox: tuple[float, float, float, float] | None,
                work_root: Path, cache_dir: Path,
                purge_after: bool = True) -> RecoveryResult:
    """End-to-end recovery for one HR: download → header → infer →
    verify → extract valid polygon.
    """
    cache_path = cache_dir / f"{hr_id.replace(':', '_')}.json"
    if cache_path.exists():
        try:
            d = json.loads(cache_path.read_text())
            return RecoveryResult(**d)
        except Exception:
            pass

    notes: list[str] = []
    uids = [u.strip() for u in file_ids.split(",") if u.strip()]
    hr_dir = work_root / hr_id.replace(":", "_")
    hr_dir.mkdir(parents=True, exist_ok=True)

    polys_4326 = []
    n_ok = 0
    crs_source_chosen: str | None = None
    inferred_crs_chosen: str | None = None
    grid_bbox_acc: tuple[float, float, float, float] | None = None
    overlap_acc: float | None = None
    status_per_file: list[str] = []

    for uid in uids:
        path = stage_b_mod._download_file(uid, hr_dir)
        if path is None:
            notes.append(f"download failed for {uid}")
            continue
        try:
            for raster_path in stage_b_mod._decompress(path):
                ext = raster_path.suffix.lower()
                hdr = None
                if ext == ".asc":
                    hdr = read_asc_header(raster_path)
                elif ext in (".grd", ".nc"):
                    hdr = read_grd_header(raster_path)
                if hdr is None:
                    notes.append(f"{raster_path.name}: not a recognised raster layout")
                    continue
                crs_str, crs_src, rule = infer_crs(hdr, iso_bbox)
                if crs_str is None:
                    status_per_file.append(f"{raster_path.name}: unrecoverable ({rule})")
                    continue
                if iso_bbox is None:
                    status_per_file.append(f"{raster_path.name}: no ISO bbox to verify against; rejected")
                    continue
                ok, frac, gbb = verify_against_iso(hdr.x_min, hdr.x_max,
                                                    hdr.y_min, hdr.y_max,
                                                    crs_str, iso_bbox)
                if not ok:
                    status_per_file.append(
                        f"{raster_path.name}: {crs_str} ({crs_src}) verify FAIL "
                        f"(overlap={frac:.2f}, grid_4326={gbb})")
                    continue
                # Verified — convert with the recovered CRS, extract valid polygon
                tmp_tif = raster_path.with_suffix(".recovered.tif")
                try:
                    if hdr.layout == "gmt_classic":
                        gmt_grd_mod.convert(raster_path, tmp_tif, crs=crs_str)
                    elif hdr.layout == "gmt_v6":
                        convert_v6_with_crs(raster_path, tmp_tif, crs_str)
                    elif hdr.layout == "esri_asc":
                        convert_asc_with_crs(raster_path, tmp_tif, crs_str)
                    else:
                        raise RuntimeError(f"unknown layout {hdr.layout}")
                    poly_native, native_crs = stage_b_mod._valid_polygon_from_raster(tmp_tif)
                    poly_4326 = stage_b_mod._native_to_4326(poly_native, native_crs)
                    if poly_4326 is None or poly_4326.is_empty:
                        status_per_file.append(f"{raster_path.name}: polygon empty after reproject")
                        continue
                    polys_4326.append(poly_4326)
                    n_ok += 1
                    crs_source_chosen = crs_src
                    inferred_crs_chosen = crs_str
                    grid_bbox_acc = gbb
                    overlap_acc = frac if overlap_acc is None else min(overlap_acc, frac)
                    status_per_file.append(
                        f"{raster_path.name}: OK ({crs_str}, {crs_src}, overlap={frac:.2f})")
                except Exception as e:
                    status_per_file.append(f"{raster_path.name}: convert/polygon failed: {e}")
                finally:
                    try: tmp_tif.unlink()
                    except FileNotFoundError: pass
        except Exception as e:
            notes.append(f"{path.name}: outer failure {e}")

    if polys_4326:
        def _clean(p):
            if p is None or p.is_empty:
                return None
            if not p.is_valid:
                p = make_valid(p)
            if p is None or p.is_empty:
                return None
            b = p.bounds
            if not all(np.isfinite(x) for x in b):
                return None
            if p.area <= 0:
                return None
            return p
        valid_polys = [q for q in (_clean(p) for p in polys_4326) if q is not None]
        merged = None
        try:
            if valid_polys:
                merged = unary_union(valid_polys)
                if merged is not None and not merged.is_valid:
                    merged = make_valid(merged)
        except Exception as e:
            notes.append(f"unary_union failed: {e}; falling back to largest single polygon")
            merged = None

        # Fallback: if the union didn't produce a usable polygon but
        # individual files DID recover, accept the largest single
        # polygon. Better than discarding a valid recovery because one
        # sibling raster's polygon was degenerate.
        def _usable(g) -> bool:
            return (g is not None and not g.is_empty
                    and np.isfinite(g.centroid.x) and np.isfinite(g.centroid.y)
                    and g.area > 0)
        if not _usable(merged) and valid_polys:
            largest = max(valid_polys, key=lambda p: p.area)
            if _usable(largest):
                notes.append(f"using largest single polygon ({len(valid_polys)} usable, union degenerate)")
                merged = largest

        if _usable(merged):
            wkb_hex = shapely_wkb.dumps(merged).hex()
            area_km2 = stage_b_mod._polygon_area_km2(merged)
            status = "crs_recovered"
            reason = (f"recovered {n_ok}/{len(uids)} files via {crs_source_chosen}; "
                      f"CRS={inferred_crs_chosen}; min overlap with ISO bbox "
                      f"{overlap_acc:.2f}")
        else:
            wkb_hex = None
            area_km2 = 0.0
            status = "crs_failed_verification"
            reason = (f"polygon union/fallback produced no usable geometry; "
                      f"CRS={inferred_crs_chosen} ({crs_source_chosen}) — "
                      "recovered polygons were geometrically degenerate")
    else:
        wkb_hex = None
        area_km2 = 0.0
        if iso_bbox is None:
            status = "crs_unrecoverable"
            reason = "no ISO bbox available for this data_set; cannot verify any inferred CRS"
        elif any("verify FAIL" in s for s in status_per_file):
            status = "crs_failed_verification"
            reason = "inferred CRS did not reconcile with MGDS ISO bbox"
        else:
            status = "crs_unrecoverable"
            reason = "header ranges fit neither geographic nor UTM bound; inference declined"

    result = RecoveryResult(
        hr_id=hr_id, status=status,
        crs_source=crs_source_chosen,
        inferred_crs=inferred_crs_chosen,
        iso_bbox=iso_bbox,
        grid_bbox_4326=grid_bbox_acc,
        overlap_fraction=overlap_acc,
        polygon_wkb_hex=wkb_hex,
        area_km2=area_km2,
        n_files=len(uids), n_files_ok=n_ok,
        reason=reason,
        notes=notes + status_per_file,
    )

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(asdict(result)))

    if purge_after and hr_dir.exists():
        try:
            for p in hr_dir.rglob("*"):
                if p.is_file():
                    p.unlink()
            for p in sorted(hr_dir.rglob("*"), reverse=True):
                if p.is_dir():
                    try: p.rmdir()
                    except OSError: pass
            hr_dir.rmdir()
        except Exception:
            pass
    return result


# ---------- apply to hr_catalog ----------

def apply_results(hr_path: Path, results: list[RecoveryResult]) -> None:
    """Update hr_catalog in place: write recovered geometry +
    ``geometry_source='crs_recovered'`` + ``recovered_crs`` for the
    HRs that successfully recovered. Failures get
    ``geometry_source='crs_failed_verification'`` or ``'crs_unrecoverable'``
    so Stage A can tier them with an honest reason.
    """
    hr = gpd.read_file(hr_path, layer="hr")
    if "geometry_source" not in hr.columns:
        hr["geometry_source"] = "metadata_bbox"
    if "recovered_crs" not in hr.columns:
        hr["recovered_crs"] = None
    by_id = {r.hr_id: r for r in results}
    n_ok = 0; n_failed_ver = 0; n_unrec = 0
    for i, row in hr.iterrows():
        r = by_id.get(row["hr_id"])
        if r is None:
            continue
        if r.status == "crs_recovered" and r.polygon_wkb_hex:
            poly = shapely_wkb.loads(bytes.fromhex(r.polygon_wkb_hex))
            hr.at[i, "geometry"] = poly
            hr.at[i, "footprint_km2"] = r.area_km2
            hr.at[i, "footprint_suspect"] = False
            hr.at[i, "geometry_source"] = "crs_recovered"
            hr.at[i, "recovered_crs"] = r.inferred_crs
            note = (f"CRS recovery: {r.inferred_crs} ({r.crs_source}); "
                    f"verified overlap={r.overlap_fraction:.2f}; "
                    f"{r.n_files_ok}/{r.n_files} files; area {r.area_km2:.2f} km^2")
            n_ok += 1
        else:
            hr.at[i, "geometry_source"] = r.status   # crs_failed_verification / crs_unrecoverable
            note = f"CRS recovery {r.status}: {r.reason}"
            if r.status == "crs_failed_verification":
                n_failed_ver += 1
            else:
                n_unrec += 1
        if "description" in hr.columns:
            base = hr.at[i, "description"] or ""
            hr.at[i, "description"] = (base + " | " + note)[:1500]
    hr.to_file(hr_path, driver="GPKG", layer="hr")
    log.info("CRS recovery applied: %d recovered, %d failed_verification, %d unrecoverable",
             n_ok, n_failed_ver, n_unrec)


# ---------- top-level run ----------

def run(hr_path: Path, mgds_cache_dir: Path,
        work_root: Path, cache_dir: Path,
        purge_after: bool = True) -> list[RecoveryResult]:
    hr = gpd.read_file(hr_path, layer="hr")
    # Re-attempt any prior recovery failure too, so this command is
    # idempotent and a code fix can rescue rows that were previously
    # marked crs_unrecoverable / crs_failed_verification.
    candidate_states = {"stage_b_failed_no_crs",
                        "crs_unrecoverable", "crs_failed_verification"}
    targets = hr[hr.get("geometry_source", "").isin(candidate_states)].copy()
    log.info("CRS recovery: %d candidate HRs", len(targets))
    bbox_map = load_mgds_bboxes(mgds_cache_dir / "mgds_AUV_Bathymetry_data_set.xml")

    results: list[RecoveryResult] = []
    for _, row in targets.iterrows():
        hr_id = row["hr_id"]
        if not hr_id.startswith("MGDS:"):
            log.info("skip non-MGDS %s", hr_id)
            continue
        uid = hr_id.split(":", 1)[1]
        iso = bbox_map.get(uid)
        file_ids = row.get("file_uids") or row.get("file_ids") or ""
        if not file_ids:
            results.append(RecoveryResult(
                hr_id=hr_id, status="crs_unrecoverable",
                crs_source=None, inferred_crs=None, iso_bbox=iso,
                grid_bbox_4326=None, overlap_fraction=None,
                polygon_wkb_hex=None, area_km2=0.0,
                n_files=0, n_files_ok=0,
                reason="no file_uids on catalog row",
                notes=[],
            ))
            continue
        log.info("recover %s (%d files, iso=%s)", hr_id,
                 len(file_ids.split(",")), iso)
        r = recover_one(hr_id, file_ids, iso, work_root, cache_dir,
                        purge_after=purge_after)
        log.info("  → %s (%s, %s, area=%.2f km^2)",
                 r.status, r.crs_source, r.inferred_crs, r.area_km2)
        results.append(r)

    apply_results(hr_path, results)
    return results
