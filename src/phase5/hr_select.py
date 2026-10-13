"""ACQ-R09 §2.4 — the high-resolution grids of one site, by the spec §3.2 rules, mechanically (no viewing).

  0. inputs: the top-level files of the site's sealed directory (`_conv/`, `_extracted/` and other directories left by
     ACQ-R08b are ignored); `.gz` members are decompressed and `.zip` members extracted into the node-local work
     directory; companion products are skipped by name with the ACQ-R08b pattern (src/acq_r08b/measure.AUX_RE:
     backscatter, amplitude, sidescan, count / sd, slope / shade, difference, interpolated ...);
  1. each remaining raster goes through the development materializer (src/acq_r01/harmonize_new.materialize, unchanged:
     float elevation -> GeoTIFF with a CRS; RGB renders and CRS-less non-geographic grids drop out); header by the
     ACQ-R08b header reader; validity mask = finite, not nodata, |z| < 20 km (as ACQ-R08b); valid area by cell count;
  2. resolution group (spec §3.2.1, the ACQ-R08b rule): grids grouped by round(cell size in m, 2); groups inside
     0.985-4.99 m; the finest group whose valid area (sum over its grids, as ACQ-R08b computed it) is >= 80 % of the
     largest such group's;
  3. repeat surveys (spec §3.2.2, ruling S2): two grids of the group overlap when their validity masks share >= 50 % of
     the smaller one's valid area; per connected set of overlapping grids the kept grid is the one whose acquisition year
     is closest to the ship cruise year (dates from a YYYYMMDD in the file name, else an acquisition/survey date
     attribute), ties -> larger valid area -> file name; an undated grid makes the set a tie (larger valid area decides);
     grids overlapping a kept grid are dropped; grids below the threshold are all kept;
  4. the kept grids, in that rule order (closest year, larger area, name), are what the development mosaic receives
     (ruling S1); their footprint (src/acq_r01/verify_candidates.polygon_with_crs_fallback, unchanged, union) defines the
     ship-grid region exactly as the development gridder's HR footprints did.
Every grid kept, dropped or skipped is recorded with its reason.  No depth statistic is computed: values are read only
to form the validity mask.
"""
from __future__ import annotations

import gzip
import logging
import re
import shutil
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, transform_bounds
from shapely.ops import unary_union

from src.acq_r01 import common as C
from src.acq_r01 import harmonize_new as HN
from src.acq_r01 import verify_candidates as VC
from src.acq_r08b import measure as M8
from src.phase5 import common_p5 as P

log = logging.getLogger("acq_r09.hr")
_DATE8 = re.compile(r"(?<!\d)((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")
_DATE_KEY = re.compile(r"(acquisition|survey|collection|start)[_ ]?(date|time|year)", re.I)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
SKIP_NAMES = ("SHA256SUMS", "download_manifest.json")


# --------------------------------------------------------------------------- #
# 0. inputs
# --------------------------------------------------------------------------- #
def stage_inputs(site_dir: Path, work: Path) -> tuple:
    """Top-level files of the site directory -> raster files in the work directory.  Returns (rasters, file records)."""
    raw = work / "raw"; raw.mkdir(parents=True, exist_ok=True)
    files, rasters = [], []
    for p in sorted(Path(site_dir).iterdir()):
        if not p.is_file() or p.name in SKIP_NAMES or p.name.startswith("."):
            continue
        rec = {"name": p.name, "bytes": p.stat().st_size, "sha256": P.sha256_file(p), "members": []}
        files.append(rec)
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if n.lower().endswith(M8.RASTER_EXT):
                        dst = raw / Path(n).name
                        with z.open(n) as fi, open(dst, "wb") as fo:
                            shutil.copyfileobj(fi, fo)
                        rasters.append(dst); rec["members"].append(dst.name)
            continue
        if p.name.lower().endswith(".gz"):
            dst = raw / p.name[:-3]
            with gzip.open(p, "rb") as fi, open(dst, "wb") as fo:
                shutil.copyfileobj(fi, fo, 1 << 22)
        else:
            dst = raw / p.name
            shutil.copyfile(p, dst)
        if dst.suffix.lower() in M8.RASTER_EXT:
            rasters.append(dst); rec["members"].append(dst.name)
    return rasters, files


# --------------------------------------------------------------------------- #
# 1. per grid
# --------------------------------------------------------------------------- #
def valid_mask(path: str, nodata) -> np.ndarray:
    """Finite, not nodata, |z| < 20 km (the ACQ-R08b mask).  Only the boolean mask leaves this function."""
    with rasterio.open(path) as ds:
        a = ds.read(1).astype("float64")
    v = np.isfinite(a)
    if nodata is not None and np.isfinite(nodata):
        v &= ~np.isclose(a, nodata)
    v &= np.abs(a) < 20000
    del a
    return v


def grid_date(raw: Path) -> tuple:
    """(year or None, source).  A YYYYMMDD in the file name, else an acquisition / survey date attribute."""
    m = _DATE8.search(raw.name)
    if m:
        return int(m.group(1)), f"file name ({m.group(0)})"
    try:
        for cand in (str(raw), f"NETCDF:{raw}"):
            try:
                with rasterio.open(cand) as ds:
                    tags = dict(ds.tags())
                break
            except Exception:
                tags = {}
        for k, v in tags.items():
            if _DATE_KEY.search(k):
                y = _YEAR.search(str(v))
                if y:
                    return int(y.group(1)), f"metadata {k}"
    except Exception:
        pass
    return None, "undated (no YYYYMMDD in the file name, no acquisition/survey date attribute)"


def describe(hr_id: str, rasters: list, work: Path) -> tuple:
    """Companion filter + development materializer + header + mask for every raster."""
    mat = work / "materialized"; mat.mkdir(parents=True, exist_ok=True)
    grids, skipped = [], []
    hint = HN.catalog_crs(hr_id) or ""
    for i, rp in enumerate(rasters):
        if M8.AUX_RE.search(rp.name):
            skipped.append({"file": rp.name, "status": "skipped", "reason": "companion product by name (ACQ-R08b AUX_RE)"}); continue
        try:
            mt = HN.materialize(hr_id, rp, mat / f"g{i:03d}.tif")
        except Exception as e:
            mt = None; err = f"{type(e).__name__}: {str(e)[:80]}"
        else:
            err = None
        if mt is None:
            skipped.append({"file": rp.name, "status": "skipped", "reason": "not materialized by harmonize_new.materialize (not a float elevation raster with a usable CRS)" + (f" [{err}]" if err else "")}); continue
        with rasterio.open(str(mt)) as ds:
            has_crs = ds.crs is not None
        if not has_crs:
            skipped.append({"file": rp.name, "status": "skipped", "reason": "materialized grid has no CRS"}); continue
        h = M8.header(str(mt), hint)
        v = valid_mask(str(mt), h["nodata"])
        km2 = M8.cell_area_km2(h, v)
        with rasterio.open(str(mt)) as ds:
            b4326 = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
        year, dsrc = grid_date(rp)
        grids.append({"file": rp.name, "raw": rp, "tif": mt, "h": h, "valid": v, "valid_km2": km2, "res_m": h["res_m"], "group": round(h["res_m"], 2),
                      "crs": h["crs"], "bounds_4326": b4326, "year": year, "date_source": dsrc})
    return grids, skipped


# --------------------------------------------------------------------------- #
# 2. resolution group
# --------------------------------------------------------------------------- #
def resolution_group(grids: list) -> tuple:
    groups = {}
    for g in grids:
        groups.setdefault(g["group"], []).append(g)
    area = {r: sum(g["valid_km2"] for g in gs) for r, gs in groups.items()}
    inside = {r: a for r, a in area.items() if P.HR_MIN <= r <= P.HR_MAX}
    rec = {"groups": {str(r): {"n_grids": len(groups[r]), "valid_km2": round(area[r], 3), "in_range": r in inside} for r in sorted(groups)}}
    if not inside:
        rec["chosen"] = None; rec["reason"] = f"no resolution group inside {P.HR_MIN}-{P.HR_MAX} m"
        return None, rec
    amax = max(inside.values())
    chosen = min(r for r, a in inside.items() if a >= P.GROUP_COVER * amax)
    rec.update({"chosen": chosen, "largest_group_km2": round(amax, 3), "rule": "finest group in 0.985-4.99 m whose valid area >= 80 % of the largest group's (ACQ-R08b rule)"})
    return chosen, rec


# --------------------------------------------------------------------------- #
# 3. repeat surveys
# --------------------------------------------------------------------------- #
def _bbox_hit(a, b) -> bool:
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def overlap_km2(gi: dict, gj: dict) -> float:
    """Area (km2) of gi's valid cells that are also valid in gj (gj's mask resampled onto gi's grid, nearest)."""
    with rasterio.open(str(gi["tif"])) as a, rasterio.open(str(gj["tif"])) as b:
        dst = np.zeros(gi["valid"].shape, "uint8")
        reproject(gj["valid"].astype("uint8"), dst, src_transform=b.transform, src_crs=b.crs, dst_transform=a.transform, dst_crs=a.crs,
                  src_nodata=None, dst_nodata=None, resampling=Resampling.nearest)
    return float(M8.cell_area_km2(gi["h"], gi["valid"] & (dst > 0)))


def overlaps(group: list) -> dict:
    """(i, j) -> fraction of the smaller grid's valid area shared, for every pair with intersecting bounding boxes."""
    out = {}
    for i in range(len(group)):
        for j in range(i + 1, len(group)):
            gi, gj = group[i], group[j]
            if not _bbox_hit(gi["bounds_4326"], gj["bounds_4326"]):
                continue
            km2 = overlap_km2(gi, gj)
            small = min(gi["valid_km2"], gj["valid_km2"])
            out[(i, j)] = km2 / small if small > 0 else 0.0
    return out


def rule_key(g: dict, ship_year: int, use_dates: bool) -> tuple:
    d = abs(g["year"] - ship_year) if (use_dates and g["year"] is not None) else 0
    return (d, -g["valid_km2"], g["file"])


def select_repeat(group: list, ship_year: int) -> tuple:
    """Ruling S2.  Returns (kept grids in rule order, decisions, overlap table)."""
    ov = overlaps(group)
    edges = {k: f for k, f in ov.items() if f >= P.OVERLAP_FRAC}
    n = len(group)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for (i, j) in edges:
        parent[find(i)] = find(j)
    comps = {}
    for i in range(n):
        comps.setdefault(find(i), []).append(i)
    kept, decisions = [], {}
    for members in comps.values():
        use_dates = all(group[i]["year"] is not None for i in members)
        order = sorted(members, key=lambda i: rule_key(group[i], ship_year, use_dates))
        kept_here = []
        for i in order:
            hit = [k for k in kept_here if (min(i, k), max(i, k)) in edges]
            if hit:
                k = hit[0]; f = edges[(min(i, k), max(i, k))]
                if use_dates and group[i]["year"] != group[k]["year"] and abs(group[i]["year"] - ship_year) != abs(group[k]["year"] - ship_year):
                    why = f"acquisition year {group[i]['year']} farther from the ship year {ship_year} than {group[k]['file']} ({group[k]['year']})"
                elif group[i]["valid_km2"] != group[k]["valid_km2"]:
                    why = f"smaller valid area than {group[k]['file']}" + ("" if use_dates else " (an undated grid in the set: tie on date)")
                else:
                    why = f"tie with {group[k]['file']} on date and area; file-name order"
                decisions[i] = {"status": "dropped", "reason": f"repeat survey: overlaps kept {group[k]['file']} by {f:.0%} of the smaller grid; {why}"}
            else:
                kept_here.append(i); decisions[i] = {"status": "kept", "reason": "no overlap >= 50 % with a grid ranked before it"}
        kept += kept_here
    use_all = all(group[i]["year"] is not None for i in kept)
    kept = sorted(kept, key=lambda i: rule_key(group[i], ship_year, use_all))
    table = [{"a": group[i]["file"], "b": group[j]["file"], "shared_fraction_of_smaller": round(f, 4), "overlap": f >= P.OVERLAP_FRAC} for (i, j), f in sorted(ov.items())]
    return [group[i] for i in kept], {group[i]["file"]: decisions[i] for i in range(n)}, table


# --------------------------------------------------------------------------- #
# 4. footprint of the kept grids
# --------------------------------------------------------------------------- #
def footprint(hr_id: str, kept: list, work: Path):
    """Union of verify_candidates.polygon_with_crs_fallback over the kept raw grids (the development HR footprint)."""
    fpw = work / "footprint"; fpw.mkdir(parents=True, exist_ok=True)
    polys = []
    for g in kept:
        p4326, crs, how = VC.polygon_with_crs_fallback(Path(g["raw"]), hr_id, fpw)
        polys.append(p4326); g["footprint_crs"] = crs; g["footprint_crs_source"] = how
    return unary_union(polys) if polys else None


def select(site: dict, site_dir: Path, work: Path) -> dict:
    """The whole §3.2 selection for one site.  Returns {"record": ..., "kept_raw": [...], "footprint": geom or None}."""
    rasters, files = stage_inputs(site_dir, work)
    grids, skipped = describe(site["hr_id"], rasters, work)
    rec = {"hr_id": site["hr_id"], "n_files": len(files), "files": files, "n_rasters": len(rasters), "n_grids_read": len(grids),
           "skipped": skipped, "rules": "spec §3.2.1 (ACQ-R08b group rule), §3.2.2 + ruling S2 (>= 50 % of the smaller grid), ruling S1 (development mosaic)"}
    chosen, grec = resolution_group(grids)
    rec["resolution_group"] = grec
    per = {}
    for g in grids:
        per[g["file"]] = {"res_m": round(g["res_m"], 4), "group": g["group"], "crs": g["crs"], "valid_km2": round(g["valid_km2"], 3), "year": g["year"], "date_source": g["date_source"]}
    if chosen is None:
        for g in grids:
            per[g["file"]].update({"status": "dropped", "reason": grec["reason"]})
        rec["grids"] = per; rec["kept"] = []
        return {"record": rec, "kept_raw": [], "footprint": None, "kept": []}
    group = [g for g in grids if g["group"] == chosen]
    for g in grids:
        if g["group"] != chosen:
            per[g["file"]].update({"status": "dropped", "reason": f"resolution group {g['group']} m is not the chosen group {chosen} m"})
    kept, decisions, table = select_repeat(group, site["year"])
    for f, d in decisions.items():
        per[f].update(d)
    rec["grids"] = per; rec["overlaps"] = table
    rec["kept"] = [g["file"] for g in kept]
    fp = footprint(site["hr_id"], kept, work)
    for g in kept:
        per[g["file"]]["footprint_crs"] = g.get("footprint_crs"); per[g["file"]]["footprint_crs_source"] = g.get("footprint_crs_source")
    for g in grids:
        g["valid"] = None
    rec["footprint_bounds_4326"] = list(fp.bounds) if fp is not None else None
    return {"record": rec, "kept_raw": [Path(g["raw"]) for g in kept], "footprint": fp, "kept": kept}
