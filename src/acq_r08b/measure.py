"""ACQ-R08b step 2 — measure header, validity footprint, one rounded median depth, ship coverage and tile count per
candidate (directive §3).  The only depth-derived number written anywhere is ``depth_median_100m``.

Per candidate (sealed directory, read under the §3 allowance):
  * bathymetry grids = the downloaded raster files minus companion products by name (backscatter / amplitude / sidescan /
    count / sd / slope / shade ...); GMT and COARDS netCDF are converted to GeoTIFF inside the sealed directory;
  * header: cell size (native units and metres), CRS, extent, nodata, size; one row per grid;
  * the finest native resolution whose grids cover the survey (union footprint ≥ 80 % of the largest group) is used;
  * validity mask = finite and not nodata; `valid_km2` by cell count × cell area (per-row cosine for geographic grids);
    `hr_footprint` = polygon of the mask (block-pooled to ~50 m, simplified 50 m in local UTM) → GeoJSON, EPSG:4326;
  * `depth_median_100m` = round(median(|valid depths|) / 100) × 100, computed once over the chosen grids, nothing else;
  * ship coverage = NCEI navigation (.fnv) tracks of the ship cruise, buffered by half the nominal swath width
    (SWATH_FACTOR × depth / 2) in local UTM, intersected with hr_footprint; fallback = the NCEI footprint polygon;
  * `tiles_est` = 256-px windows at stride 128 with ≥ 50 % valid cells inside hr_footprint ∩ ship coverage, on each chosen
    grid at its native resolution, summed over grids;
  * lr_est_m = 2·depth·tan(bw/2), cells_across_est, ratio_est, status (ACQ-R08 §3 rule), nearest corpus footprint, same site.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
import time
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features
from shapely.geometry import shape, box, mapping, LineString
from shapely.ops import unary_union

from src.acq_r08b import common as K
from src.acq_r01 import common as C
from src.discovery.raw_lr_dryrun import data_dir_from_iso, resolve_data_dir
from src.discovery.stage_a5_subset import iter_cruise_files, prefetch_nav, parse_fnv_track
from src.discovery import geoportal

log = logging.getLogger("acq_r08b.measure")
AUX_RE = re.compile(r"backscatter|backs|amplitude|amp[_c]|zamp|_A[34]F?\d*|sidescan|side-scan|_ss\b|zss|mbss|ssc|_num\b|_sd\b|stdev|count|slope|shade|hillshade|rugos|aspect|"
                    r"intensity|mosaic_bs|_bs\b|beamangle|curvature|roughness|tpi|\bbpi\b|texture|photo|image|topodiff|_diff|interp|\dmint|fill", re.I)
HR_GROUP_MAX_RES = 5.0      # grids coarser than this are regional / ship context bundled with the record, not the survey
RASTER_EXT = (".grd", ".nc", ".tif", ".tiff", ".asc", ".bag", ".img", ".flt")
SIMPLIFY_M = 50.0


# ----------------------------------------------------------------------------------------------------------------- #
# Grid access (header + mask + values); every function returns only what §3 allows
# ----------------------------------------------------------------------------------------------------------------- #
def openable(rp: Path, conv_dir: Path, crs_hint: str) -> str | None:
    """A rasterio-openable path for a downloaded grid (converting GMT / COARDS netCDF inside the sealed directory)."""
    from src import gmt_grd
    from src.discovery.stage_c5_sweep import _read_coards_grd
    conv_dir.mkdir(parents=True, exist_ok=True)
    if rp.name.lower().endswith(".gz"):
        import gzip, shutil
        unz = conv_dir / rp.name[:-3]
        if not unz.exists():
            with gzip.open(rp, "rb") as fi, open(unz, "wb") as fo:
                shutil.copyfileobj(fi, fo)
        rp = unz
    try:
        if gmt_grd.is_gmt_grd(rp):
            out = conv_dir / (rp.stem + ".gmtconv.tif")
            if not out.exists():
                gmt_grd.convert(rp, out, crs=crs_hint)
            return str(out)
    except Exception as e:
        log.info("%s: not GMT-convertible (%s)", rp.name, type(e).__name__)
    for cand in (str(rp), f"NETCDF:{rp}"):
        try:
            with rasterio.open(cand) as ds:
                t = ds.transform
                if t is not None and not (abs(t.a - 1) < 1e-12 and abs(t.e - 1) < 1e-12) and ds.count >= 1:
                    return cand
        except Exception:
            continue
    try:
        out = conv_dir / (rp.stem + ".coards.tif")
        if not out.exists():
            _read_coards_grd(rp, crs_hint, out)
        return str(out)
    except Exception as e:
        log.warning("%s: unreadable (%s)", rp.name, type(e).__name__)
        return None


def header(path: str, crs_hint: str) -> dict:
    with rasterio.open(path) as ds:
        t = ds.transform; crs = ds.crs.to_string() if ds.crs else (crs_hint or "")
        b = ds.bounds
        geo = (ds.crs.is_geographic if ds.crs else (abs(b.left) <= 360 and abs(b.top) <= 90))
        rx, ry = abs(t.a), abs(t.e)
        if geo:
            lat = (b.bottom + b.top) / 2
            rx_m, ry_m = rx * 111_320 * math.cos(math.radians(lat)), ry * 111_132
        else:
            rx_m, ry_m = rx, ry
        return {"path": path, "width": ds.width, "height": ds.height, "crs": crs, "geographic": bool(geo), "res_native": [rx, ry],
                "res_x_m": round(rx_m, 4), "res_y_m": round(ry_m, 4), "res_m": round(math.sqrt(rx_m * ry_m), 4),
                "extent": [b.left, b.bottom, b.right, b.top], "nodata": ds.nodata, "dtype": str(ds.dtypes[0]), "bands": ds.count}


def read_mask_and_values(path: str, nodata):
    with rasterio.open(path) as ds:
        a = ds.read(1).astype("float64")
    valid = np.isfinite(a)
    if nodata is not None and np.isfinite(nodata):
        valid &= ~np.isclose(a, nodata)
    valid &= np.abs(a) < 20000          # physical bound; large sentinel values (e.g. 99999 / -99999) are nodata
    vals = np.abs(a[valid])
    return valid, vals


def cell_area_km2(h: dict, valid: np.ndarray) -> float:
    if not h["geographic"]:
        return float(valid.sum()) * h["res_native"][0] * h["res_native"][1] / 1e6
    # geographic: per-row area = dlon·cos(lat)·111.32 km × dlat·111.132 km
    top = h["extent"][3]; dy = h["res_native"][1]; dx = h["res_native"][0]
    rows = np.arange(valid.shape[0]); lat = top - (rows + 0.5) * dy
    per_row = valid.sum(axis=1).astype("float64")
    return float((per_row * dx * 111.32 * np.cos(np.radians(lat)) * dy * 111.132).sum())


def mask_polygon_4326(h: dict, valid: np.ndarray):
    """Polygon of the validity mask in EPSG:4326 (block-pooled to ≈ 50 m, then simplified 50 m in local UTM)."""
    f = max(1, int(round(SIMPLIFY_M / max(h["res_m"], 1e-6))))
    H, W = valid.shape
    if f > 1:
        Hc, Wc = (H // f) * f, (W // f) * f
        pooled = valid[:Hc, :Wc].reshape(Hc // f, f, Wc // f, f).any(axis=(1, 3))
        # keep the ragged edge
        if Hc < H or Wc < W:
            full = np.zeros((math.ceil(H / f), math.ceil(W / f)), dtype=bool); full[:pooled.shape[0], :pooled.shape[1]] = pooled
            if Hc < H:
                full[-1, :pooled.shape[1]] |= valid[Hc:, :Wc].reshape(H - Hc, Wc // f, f).any(axis=(0, 2))
            if Wc < W:
                full[:pooled.shape[0], -1] |= valid[:Hc, Wc:].reshape(Hc // f, f, W - Wc).any(axis=(1, 2))
            pooled = full
    else:
        pooled = valid
    with rasterio.open(h["path"]) as ds:
        t = ds.transform * rasterio.Affine.scale(f, f); crs = ds.crs
    geoms = [shape(g) for g, v in features.shapes(pooled.astype("uint8"), mask=pooled, transform=t) if v == 1]
    if not geoms:
        return None
    poly = unary_union(geoms)
    if crs is not None and not crs.is_geographic:
        import pyproj
        from shapely.ops import transform as stransform
        poly = stransform(pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform, poly)
    elif crs is None and not h["geographic"] and h["crs"]:
        import pyproj
        from shapely.ops import transform as stransform
        poly = stransform(pyproj.Transformer.from_crs(h["crs"], "EPSG:4326", always_xy=True).transform, poly)
    c = poly.centroid; epsg = K.utm_for(c.x, c.y)
    return K.to_4326(K.to_utm(poly, epsg).buffer(0).simplify(SIMPLIFY_M), epsg).buffer(0)


def tiles_in(h: dict, valid: np.ndarray, cov_4326) -> int:
    """256-px windows at stride 128 with ≥ 50 % cells valid AND inside the coverage polygon."""
    if cov_4326 is None or cov_4326.is_empty:
        return 0
    with rasterio.open(h["path"]) as ds:
        crs = ds.crs; t = ds.transform
    cov = cov_4326
    tgt = crs if crs is not None else (h["crs"] if (not h["geographic"] and h["crs"]) else None)
    if tgt is not None and not (crs is not None and crs.is_geographic):
        import pyproj
        from shapely.ops import transform as stransform
        cov = stransform(pyproj.Transformer.from_crs("EPSG:4326", tgt, always_xy=True).transform, cov_4326)
    covm = features.rasterize([(mapping(cov), 1)], out_shape=valid.shape, transform=t, fill=0, dtype="uint8").astype(bool)
    m = (valid & covm).astype("int64")
    H, W = m.shape
    if H < K.WIN or W < K.WIN:
        return 0
    cs = np.zeros((H + 1, W + 1), dtype="int64"); cs[1:, 1:] = m.cumsum(0).cumsum(1)
    n = 0
    rows = range(0, H - K.WIN + 1, K.STRIDE); cols = range(0, W - K.WIN + 1, K.STRIDE)
    need = K.VALID_FLOOR * K.WIN * K.WIN
    for r in rows:
        r2 = r + K.WIN
        s = cs[r2, np.array(cols) + K.WIN] - cs[r, np.array(cols) + K.WIN] - cs[r2, np.array(cols)] + cs[r, np.array(cols)]
        n += int((s >= need).sum())
    return n


def tiles_union(fp_4326, cov_4326, res_m: float, epsg: str) -> int:
    """256-px windows at stride 128 with ≥ 50 % of their cells inside hr_footprint ∩ ship_coverage, counted once on a
    raster at `res_m` in the local UTM over the union footprint (repeat-survey epochs and grid versions are not double
    counted).  Computed in horizontal bands of 256 rows (no size cap)."""
    if cov_4326 is None or cov_4326.is_empty:
        return 0
    poly = K.to_utm(fp_4326.intersection(cov_4326).buffer(0), epsg)
    if poly.is_empty:
        return 0
    x0, y0, x1, y1 = poly.bounds
    W, H = int(math.ceil((x1 - x0) / res_m)), int(math.ceil((y1 - y0) / res_m))
    if W < K.WIN or H < K.WIN:
        return 0
    shapes = [(mapping(poly), 1)]
    need = K.VALID_FLOOR * K.WIN * K.WIN; n = 0
    cols = np.arange(0, W - K.WIN + 1, K.STRIDE)
    for r in range(0, H - K.WIN + 1, K.STRIDE):
        t = rasterio.transform.from_origin(x0, y1 - r * res_m, res_m, res_m)
        band = features.rasterize(shapes, out_shape=(K.WIN, W), transform=t, fill=0, dtype="uint8")
        colsum = band.sum(axis=0, dtype="int64")
        cs = np.concatenate([[0], np.cumsum(colsum)])
        sums = cs[cols + K.WIN] - cs[cols]
        n += int((sums >= need).sum())
    return n


# ----------------------------------------------------------------------------------------------------------------- #
# Ship coverage from navigation
# ----------------------------------------------------------------------------------------------------------------- #
def ship_tracks(cruise: str, aoi_4326) -> tuple[list, dict]:
    geoportal.fetch_geoportal_resolution(cruise, K.R08_CACHE / "geoportal")
    iso = data_dir_from_iso(cruise, K.R08_CACHE / "geoportal")
    url, note = resolve_data_dir(iso, K.R08_CACHE / "ncei_dirlist") if iso else (None, "no ISO data dir")
    info = {"cruise": cruise, "data_url": url, "n_nav_files": 0, "n_nav_fetched": 0, "n_tracks_in_aoi": 0, "method": ""}
    if not url:
        return [], info
    recs = iter_cruise_files(url, K.R08_CACHE / "ncei_dirlist")
    nav = [r for r in recs if r.kind == "nav"]; info["n_nav_files"] = len(nav)
    cdir = K.CACHE / "nav" / cruise.replace("/", "_")
    prefetch_nav(nav, cdir, workers=6)
    tracks = []
    for r in nav:
        p = cdir / r.name
        if not p.exists():
            continue
        info["n_nav_fetched"] += 1
        g = parse_fnv_track(p)
        if g is not None and g.intersects(aoi_4326):
            tracks.append(g)
    info["n_tracks_in_aoi"] = len(tracks); info["method"] = "NCEI .fnv navigation tracks (per swath file) buffered by half the nominal swath width in local UTM"
    return tracks, info


def pangaea_tracks(pid: str, aoi_4326) -> tuple[list, dict]:
    """Ship coverage source for a PANGAEA raw-swath dataset: per-file WKT tracks from the tab export when present, else the
    dataset's bounding box (upper bound, flagged)."""
    import requests
    from shapely import wkt as swkt
    cache = K.CACHE / "pangaea_tab" / f"{pid}.txt"; cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        r = requests.get(f"https://doi.pangaea.de/10.1594/PANGAEA.{pid}?format=textfile", headers=K.UA, timeout=120)
        cache.write_text(r.text if r.status_code == 200 else f"HTTP {r.status_code}")
    txt = cache.read_text()
    info = {"cruise": f"PANGAEA:{pid}", "n_nav_files": 0, "n_nav_fetched": 0, "n_tracks_in_aoi": 0, "method": ""}
    if txt.startswith("HTTP"):
        info["method"] = f"PANGAEA listing {txt}"; return [], info
    tracks = []
    for m in re.finditer(r"(?:LINESTRING|MULTILINESTRING)\s*\([^\n\t]*\)", txt):
        try:
            g = swkt.loads(m.group(0)); info["n_nav_files"] += 1
            if g.intersects(aoi_4326):
                tracks.append(g)
        except Exception:
            continue
    info["n_nav_fetched"] = info["n_nav_files"]; info["n_tracks_in_aoi"] = len(tracks)
    if tracks:
        info["method"] = "PANGAEA tab-export per-file WKT ship tracks buffered by half the nominal swath width"; return tracks, info
    # per-file start positions (the raw-swath tab export lists one row per file with its start lat/lon and time)
    try:
        import io
        lines = txt.splitlines(); s0 = [i for i, l in enumerate(lines) if l.startswith("*/")][0] + 1
        df = pd.read_csv(io.StringIO("\n".join(lines[s0:])), sep="\t")
        lat_c = [c for c in df.columns if c.lower().startswith("file start latitude")]; lon_c = [c for c in df.columns if c.lower().startswith("file start longitude")]
        t_c = [c for c in df.columns if c.lower().startswith("file start date")]
        if lat_c and lon_c:
            d2 = df[[lon_c[0], lat_c[0]] + (t_c[:1])].dropna()
            if t_c:
                d2 = d2.sort_values(t_c[0])
            pts = list(zip(d2[lon_c[0]].astype(float), d2[lat_c[0]].astype(float)))
            info["n_nav_files"] = len(pts); info["n_nav_fetched"] = len(pts)
            segs = []
            for a, b in zip(pts[:-1], pts[1:]):
                if K.hav_km(a, b) <= 20.0:
                    segs.append(LineString([a, b]))
            segs = [g for g in segs if g.intersects(aoi_4326)]
            if segs:
                info["n_tracks_in_aoi"] = len(segs); info["method"] = "PANGAEA tab-export per-file start positions joined into track segments (≤ 20 km), buffered by half the nominal swath width"
                return segs, info
    except Exception as e:
        info["parse_error"] = str(e)[:80]
    def _f(label):
        m = re.search(label + r":\s*(-?[\d.]+)", txt)
        return float(m.group(1)) if m else None
    s_, w, n, e = _f("SOUTH-BOUND LATITUDE"), _f("WEST-BOUND LONGITUDE"), _f("NORTH-BOUND LATITUDE"), _f("EAST-BOUND LONGITUDE")
    if None not in (s_, w, n, e):
        info["method"] = "PANGAEA dataset bounding box (upper bound; the listing has no per-file tracks)"
        return [box(w, s_, e, n)], info
    info["method"] = "no coverage source in the PANGAEA listing"; return [], info


def coverage(cruise: str, sonar: str, depth_m: float, fp_4326, ncei_fp: gpd.GeoDataFrame):
    c = fp_4326.centroid; epsg = K.utm_for(c.x, c.y)
    aoi = K.to_4326(K.to_utm(fp_4326, epsg).buffer(25_000), epsg)
    if cruise.startswith("PANGAEA:"):
        pid = re.search(r"PANGAEA:(\d+)", cruise).group(1)
        tracks, info = pangaea_tracks(pid, aoi)
        if tracks and tracks[0].geom_type == "Polygon":
            inter = fp_4326.intersection(tracks[0]).buffer(0)
            km2 = float(K.to_utm(inter, epsg).area) / 1e6 if not inter.is_empty else 0.0
            info.update({"coverage_km2": round(km2, 3), "coverage_fraction": round(km2 / max(float(K.to_utm(fp_4326, epsg).area) / 1e6, 1e-9), 3), "depth_used_m": depth_m})
            return (inter if not inter.is_empty else None), info
    else:
        tracks, info = ship_tracks(cruise, aoi)
    sf = K.swath_factor(sonar) or 3.0
    half = sf * depth_m / 2.0
    info.update({"swath_factor": sf, "half_swath_m": round(half, 1), "depth_used_m": depth_m})
    if tracks:
        cov = unary_union([K.to_utm(t, epsg).buffer(half) for t in tracks])
        cov4 = K.to_4326(cov, epsg).buffer(0)
    else:
        sub = ncei_fp[ncei_fp.SURVEY_ID.astype(str) == cruise]
        cov4 = unary_union(list(sub.geometry)).buffer(0) if len(sub) else None
        info["method"] = "NCEI multibeam footprint service polygon (no navigation tracks in the area)" if cov4 is not None else "no coverage source"
    inter = fp_4326.intersection(cov4).buffer(0) if cov4 is not None and not cov4.is_empty else None
    km2 = float(K.to_utm(inter, epsg).area) / 1e6 if inter is not None and not inter.is_empty else 0.0
    info["coverage_km2"] = round(km2, 3); info["coverage_fraction"] = round(km2 / max(float(K.to_utm(fp_4326, epsg).area) / 1e6, 1e-9), 3)
    return inter, info


# ----------------------------------------------------------------------------------------------------------------- #
# Per candidate
# ----------------------------------------------------------------------------------------------------------------- #
def grids_of(d: Path, rec: dict) -> list[Path]:
    files = []
    for f in rec.get("files", []):
        if not f.get("name"):
            continue
        p = d / f["name"]
        if p.suffix.lower() == ".zip":
            ex = d / "_extracted"; ex.mkdir(exist_ok=True)
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if n.lower().endswith(RASTER_EXT) and not (ex / n).exists():
                        z.extract(n, ex)
            files += [q for q in ex.rglob("*") if q.suffix.lower() in RASTER_EXT]
        elif p.suffix.lower() in RASTER_EXT or p.name.lower().endswith(".grd.gz"):
            files.append(p)
    return sorted(set(files))


def measure_candidate(hid: str, dl: dict, excl: gpd.GeoDataFrame, ncei_fp: gpd.GeoDataFrame, lr_meta: dict) -> dict:
    c = K.CANDIDATES[hid]; d = Path(dl["dir"])
    out = {"hr_id": hid, "source": c["source"], "r08_status": c["r08_status"], "doi": dl.get("doi", c.get("doi", "")), "title": dl.get("title", ""),
           "files": [f["name"] for f in dl.get("files", [])], "n_files": len(dl.get("files", [])), "size_gb": round(dl.get("bytes", 0) / 1e9, 3),
           "sha256": [f["sha256"] for f in dl.get("files", [])], "grids": [], "status": "", "status_reason": ""}
    grids = grids_of(d, dl)
    bathy = [g for g in grids if not AUX_RE.search(g.name)]
    out["n_raster_files"] = len(grids); out["n_bathymetry_grids"] = len(bathy); out["companion_files_skipped"] = [g.name for g in grids if AUX_RE.search(g.name)]
    hint = dl.get("catalog_crs") or ""
    heads = []
    for g in bathy:
        p = openable(g, d / "_conv", hint)
        if p:
            h = header(p, hint); h["file"] = g.name; heads.append(h)
    out["grids"] = [{k: v for k, v in h.items() if k != "path"} for h in heads]
    if not heads:
        out["status"], out["status_reason"] = "outside range", "no readable bathymetry grid"; return out
    # resolution groups: finest whose union footprint ≥ 80 % of the largest group's
    groups = {}
    per = {}
    for h in heads:
        valid, vals = read_mask_and_values(h["path"], h["nodata"])
        per[h["file"]] = {"h": h, "valid": valid, "vals": vals, "km2": cell_area_km2(h, valid), "poly": mask_polygon_4326(h, valid)}
        groups.setdefault(round(h["res_m"], 2), []).append(h["file"])
    area_of = {r: sum(per[f]["km2"] for f in fs) for r, fs in groups.items()}
    fine = {r: a for r, a in area_of.items() if r <= HR_GROUP_MAX_RES} or area_of     # survey grids (≤ 5 m); coarser = bundled context
    amax = max(fine.values())
    chosen_res = min(r for r, a in fine.items() if a >= 0.8 * amax)
    chosen = groups[chosen_res]
    out["resolution_groups"] = {str(r): {"n_grids": len(fs), "valid_km2": round(a, 3)} for r, fs in groups.items() for a in [area_of[r]]}
    out["chosen_res_group_m"] = chosen_res; out["chosen_grids"] = chosen
    hr_res = float(np.mean([per[f]["h"]["res_m"] for f in chosen])); out["hr_res_m"] = round(hr_res, 4)
    out["crs"] = sorted({per[f]["h"]["crs"] for f in chosen}); out["extent_4326"] = None
    polys = [per[f]["poly"] for f in chosen if per[f]["poly"] is not None]
    fp = unary_union(polys).buffer(0) if polys else None
    if fp is None or fp.is_empty:
        out["status"], out["status_reason"] = "outside range", "empty validity mask"; return out
    out["extent_4326"] = [round(x, 5) for x in fp.bounds]
    out["valid_km2_sum_of_grids"] = round(sum(per[f]["km2"] for f in chosen), 3)
    c0 = fp.centroid; epsg = K.utm_for(c0.x, c0.y); out["local_utm"] = epsg
    out["hr_footprint_km2"] = round(float(K.to_utm(fp, epsg).area) / 1e6, 3)
    out["valid_km2"] = out["hr_footprint_km2"]          # union of the chosen grids' validity masks (repeat epochs / versions counted once)
    # the single depth number
    vals = np.concatenate([per[f]["vals"] for f in chosen]) if chosen else np.array([])
    dm = float(np.median(vals)) if vals.size else None
    depth100 = int(round(dm / 100.0) * 100) if dm is not None else None
    del vals
    out["depth_median_100m"] = depth100
    for f in per:
        per[f]["vals"] = None
    # footprint vector (allowed output)
    fp_path = K.FOOTPRINTS / f"fp_{hid.replace(':', '-')}.geojson"
    gpd.GeoDataFrame({"hr_id": [hid], "valid_km2": [out["valid_km2"]], "hr_res_m": [out["hr_res_m"]]}, geometry=[fp], crs="EPSG:4326").to_file(fp_path, driver="GeoJSON")
    out["hr_footprint_file"] = str(fp_path.relative_to(C.REPO))
    # ship side
    out["lr_cruise"], out["lr_sonar"], out["lr_year"] = c["lr"], lr_meta.get(c["lr"], {}).get("sonar", ""), lr_meta.get(c["lr"], {}).get("year", "")
    acc = (dl.get("access_checks") or [{}])[0]
    if "pangaea_id" in acc:
        out["lr_raw_downloadable"] = (acc.get("status") == 200); out["lr_swath_gb"] = None; out["lr_n_swath_files"] = acc.get("n_swath_urls_listed")
        inside = re.search(r"\((.*?)\)", c["lr"]).group(1) if "(" in c["lr"] else ""
        out["lr_sonar"] = " ".join(inside.split()[1:]) if len(inside.split()) > 1 else ""; out["lr_year"] = ""
    else:
        out["lr_raw_downloadable"] = bool(acc.get("downloadable")); out["lr_swath_gb"] = acc.get("swath_gb"); out["lr_n_swath_files"] = acc.get("n_swath_files")
    bw = K.beamwidth(out["lr_sonar"]) or 1.5
    out["lr_beamwidth_deg"] = bw; out["lr_beamwidth_source"] = "documented" if K.beamwidth(out["lr_sonar"]) else "default 1.5°"
    out["lr_est_m"] = round(2 * depth100 * math.tan(math.radians(bw / 2)), 2) if depth100 else None
    out["cells_across_est"] = round(256 * hr_res / out["lr_est_m"], 2) if out["lr_est_m"] else None
    out["ratio_est"] = round(out["lr_est_m"] / hr_res, 2) if out["lr_est_m"] else None
    tried = []
    for cr in [c["lr"]] + [a for a in c.get("lr_alt", []) if not a.startswith("PANGAEA")]:
        sonar = lr_meta.get(cr, {}).get("sonar", "") or (out["lr_sonar"] if cr == c["lr"] else "")
        inter, info = coverage(cr, sonar, depth100 or 0, fp, ncei_fp)
        tiles = tiles_union(fp, inter, hr_res, epsg) if inter is not None else 0
        info["tiles_est"] = tiles; info["tiles_est_sum_of_grids"] = (sum(tiles_in(per[f]["h"], per[f]["valid"], inter) for f in chosen) if inter is not None else 0); tried.append(info)
        if cr == c["lr"] or tiles >= K.TILES_FLOOR:
            if cr != c["lr"] and tiles >= K.TILES_FLOOR:
                out["lr_note"] = f"primary cruise {c['lr']} gave {tried[0]['tiles_est']} tiles; alternative {cr} used"
                out["lr_cruise"], out["lr_sonar"], out["lr_year"] = cr, sonar, lr_meta.get(cr, {}).get("year", "")
                bw = K.beamwidth(sonar) or 1.5; out["lr_beamwidth_deg"] = bw
                out["lr_est_m"] = round(2 * depth100 * math.tan(math.radians(bw / 2)), 2); out["cells_across_est"] = round(256 * hr_res / out["lr_est_m"], 2); out["ratio_est"] = round(out["lr_est_m"] / hr_res, 2)
                acc2 = lr_meta.get(cr, {}).get("access") or {}; out["lr_raw_downloadable"] = bool(acc2.get("downloadable")); out["lr_swath_gb"] = acc2.get("swath_gb"); out["lr_n_swath_files"] = acc2.get("n_swath_files")
            out["ship_coverage"] = info; out["tiles_est"] = tiles
            if inter is not None and not inter.is_empty:
                cp = K.FOOTPRINTS / f"shipcov_{hid.replace(':', '-')}_{cr.replace('/', '_')}.geojson"
                gpd.GeoDataFrame({"hr_id": [hid], "lr_cruise": [cr]}, geometry=[inter], crs="EPSG:4326").to_file(cp, driver="GeoJSON")
                out["ship_coverage_file"] = str(cp.relative_to(C.REPO))
            if tiles >= K.TILES_FLOOR:
                break
    out["lr_cruises_tried"] = tried
    # nearest corpus / sealed / rejected footprint
    best = (None, None, float("inf"))
    for _, e in excl[excl.kind.isin(["manifest_v2_1", "lockbox", "confirmatory", "rejected_sept"])].iterrows():
        dd = K.dist_km(fp, e.geometry)
        if dd < best[2]:
            best = (e.ref, e.kind, dd)
    out["nearest_corpus_ref"], out["nearest_corpus_kind"], out["nearest_corpus_km"] = best[0], best[1], round(best[2], 1)
    out["releasable"] = "yes_conditional" if c["source"] == "MGDS" else ("yes_conditional" if c["source"] == "SEANOE" else "yes")
    out["license"] = {"MGDS": "MGDS default CC-BY-NC-SA (ruling R3)", "SEANOE": "CC-BY-NC-SA 4.0 (DataCite record)", "PANGAEA": "CC-BY-4.0"}[c["source"]]
    out["status"], out["status_reason"] = K.status_of(out)
    out["_fp"] = fp
    return out


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    K.install_write_guard(); K.install_net_log(); K.OUT.mkdir(parents=True, exist_ok=True); K.FOOTPRINTS.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    dl = json.loads((K.OUT / "download_manifest.json").read_text())
    excl = gpd.read_file(K.R08 / "exclusion_footprints.gpkg", layer="excl")
    ncei_fp = gpd.read_file(K.R08_CACHE / "ncei" / "ncei_all_footprints.geojson")
    lr_meta = {}
    for _, r in ncei_fp.iterrows():
        lr_meta[str(r.SURVEY_ID)] = {"sonar": str(r.INSTRUMENT or ""), "year": str(int(r.SURVEY_YEAR)) if pd.notna(r.SURVEY_YEAR) else str(r.START_TIME or "")[:4]}
    K.allow("measure.py")
    from src.acq_r08b.download import ncei_access
    for hid, c in K.CANDIDATES.items():
        for cr in [c["lr"]] + c.get("lr_alt", []):
            if not cr.startswith("PANGAEA") and cr in lr_meta and "access" not in lr_meta[cr]:
                lr_meta[cr]["access"] = ncei_access(cr)
    results, fps = [], {}
    for hid, c in K.CANDIDATES.items():
        rec = dl["candidates"].get(hid, {})
        if not rec.get("downloaded"):
            results.append({"hr_id": hid, "source": c["source"], "r08_status": c["r08_status"], "status": "excluded", "status_reason": rec.get("skipped_reason", "not downloaded"),
                            "lr_cruise": c["lr"], "access_checks": rec.get("access_checks", [])}); continue
        try:
            r = measure_candidate(hid, rec, excl, ncei_fp, lr_meta)
        except Exception as e:
            log.exception("%s failed", hid); r = {"hr_id": hid, "source": c["source"], "r08_status": c["r08_status"], "status": "outside range", "status_reason": f"measurement failed: {type(e).__name__}: {str(e)[:120]}"}
        fps[hid] = r.pop("_fp", None); results.append(r)
        log.info("%s: %s (%s) tiles=%s cells=%s", hid, r["status"], r.get("status_reason", ""), r.get("tiles_est"), r.get("cells_across_est"))
    # same site
    ids = [h for h, g in fps.items() if g is not None]
    for r in results:
        h = r["hr_id"]
        if h not in fps or fps[h] is None:
            continue
        same = [o for o in ids if o != h and K.dist_km(fps[h], fps[o]) <= K.EXCL_KM]
        r["same_site_as"] = ";".join(same)
    K.write_json(K.OUT / "candidates_measured.json", {"generated": K.now_iso(), "elapsed_s": round(time.time() - t0), "results": results, "rulings": K.RULINGS, "not_processed": K.NOT_PROCESSED})
    cols = ["hr_id", "source", "r08_status", "status", "status_reason", "hr_res_m", "crs", "extent_4326", "n_files", "size_gb", "valid_km2", "hr_footprint_km2", "hr_footprint_file",
            "depth_median_100m", "lr_cruise", "lr_sonar", "lr_year", "lr_raw_downloadable", "lr_swath_gb", "lr_est_m", "lr_beamwidth_deg", "cells_across_est", "ratio_est",
            "tiles_est", "same_site_as", "nearest_corpus_ref", "nearest_corpus_km", "releasable", "doi", "title"]
    df = pd.DataFrame([{k: (json.dumps(r.get(k)) if isinstance(r.get(k), (list, dict)) else r.get(k)) for k in cols} | {"ship_coverage_km2": (r.get("ship_coverage") or {}).get("coverage_km2"),
                       "ship_coverage_fraction": (r.get("ship_coverage") or {}).get("coverage_fraction"), "ship_coverage_method": (r.get("ship_coverage") or {}).get("method")} for r in results])
    df.to_csv(K.OUT / "candidates_measured.csv", index=False)
    print(df[["hr_id", "status", "hr_res_m", "depth_median_100m", "valid_km2", "lr_cruise", "lr_est_m", "cells_across_est", "tiles_est", "status_reason"]].to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
