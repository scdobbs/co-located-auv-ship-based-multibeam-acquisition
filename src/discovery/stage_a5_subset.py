"""Phase 2 Stage A.5 — nav-first footprint subsetting for large raw-LR cruises.

See `reports/directive_phase2_stage_a5_footprint_subset.md`. For each raw-LR
cruise with whole_GB >= THRESHOLD (default 10), this:

  1. Builds the true valid-data footprint of every HR the cruise serves
     (polygonised from the staged grids, NOT bbox), unions them, buffers
     outward by max(2*depth, 1 km) to capture ship-swath coverage.
  2. Fetches per-swath-file nav (.fnv) ONLY — no swath bulk fetch.
  3. Tests each swath file's nav track against the buffered footprint union.
  4. Emits a per-cruise verdict (exclude / keep-subset / keep-whole) and a
     revised budget vs the 865 GB Stage-A baseline.

Recommendations only — executes no exclusions, no swath fetch. HOLD at Gate 1.

Guardrails honoured: nav-only fetch, real polygons, over-include at the margin,
idempotent/cached, escalate-don't-absorb (missing nav / bbox-only -> flagged).
"""

from __future__ import annotations

import csv
import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import geopandas as gpd
import numpy as np
import pyproj
import rasterio
import requests
from rasterio.features import shapes
from shapely.geometry import shape, LineString, MultiPoint
from shapely.ops import transform as shp_transform, unary_union

from src.discovery.raw_lr_dryrun import (
    _ROW, _ext_of, _list_dir, data_dir_from_iso, resolve_data_dir,
)
from src import gmt_grd as gmt_grd_mod

log = logging.getLogger("stage_a5")

REPO = Path(__file__).resolve().parents[2]
DATA_ROOT = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
CACHE = DATA_ROOT / "discovery_cache"
GEOPORTAL = CACHE / "geoportal"
DIRLIST = CACHE / "ncei_dirlist"
NAVCACHE = CACHE / "nav"
STAGING = DATA_ROOT / "staging_phase1"
STAGE_A_JSON = REPO / "reports/discovery/stage_a_raw_lr_sizes_2026-06-22.json"
HR_CATALOG = REPO / "reports/discovery/hr_catalog.gpkg"

THRESHOLD_GB = 10.0
_HEADERS = {"User-Agent": "auv-ship-acq/0.2 (Sherlock; phase2 stage-A.5 nav; "
                          "stephencoledobbs@gmail.com)"}
_THROTTLE = 0.15
_THUMB = 800                      # decimated raster side for polygonisation
_MIN_BUFFER_M = 1000.0

# HR that are dropped/invalid and must not anchor a footprint.
DROPPED_HR = {"MGDS:30272", "MGDS:24425", "MGDS:20836"}

# Raster extensions worth polygonising (skip PDFs, sidecars, compressed dups).
RASTER_EXT = (".tif", ".tiff", ".grd", ".nc", ".asc")


# --------------------------------------------------------------------------- #
# Listing -> per-file records (swath vs nav), from cached HTML (no network)
# --------------------------------------------------------------------------- #
def _basekey(name: str) -> str:
    n = name
    for suf in (".fnv", ".fbt", ".inf"):
        if n.endswith(suf):
            n = n[: -len(suf)]
            break
    if n.endswith(".gz"):
        n = n[:-3]
    return n


@dataclass
class FileRec:
    url: str
    name: str
    bytes: int
    kind: str          # swath | nav | ancillary
    key: str


def iter_cruise_files(data_url: str, listing_cache: Path) -> list[FileRec]:
    """Walk cached autoindex listings under data_url; classify each file."""
    recs: list[FileRec] = []
    stack = [data_url]
    seen: set[str] = set()
    while stack:
        url = stack.pop()
        if url in seen:
            continue
        seen.add(url)
        html = _list_dir(url, listing_cache)
        if html is None:
            continue
        for m in _ROW.finditer(html):
            href = m.group("href")
            if href.startswith(("/", "?", "http")):
                continue
            if href.endswith("/"):
                stack.append(urljoin(url, href))
                continue
            from src.discovery.raw_lr_dryrun import _human_to_bytes
            nb = _human_to_bytes(m.group("size"))
            if nb is None:
                continue
            if href.endswith(".fnv"):
                kind = "nav"
            elif _ext_of(href) in (".fbt", ".inf", ".fnv") or href.endswith((".fbt", ".inf")):
                kind = "ancillary"
            elif re.search(r"\.all\.gz$|\.gsf\.gz$|\.all\.mb\d+\.gz$|\.gsf\.mb\d+\.gz$"
                           r"|\.mb\d+\.gz$|\.mb\d+$|\.all$|\.gsf$", href):
                kind = "swath"
            else:
                kind = "ancillary"
            recs.append(FileRec(urljoin(url, href), href, nb, kind, _basekey(href)))
    return recs


# --------------------------------------------------------------------------- #
# HR footprint (true valid-data polygon) in EPSG:4326
# --------------------------------------------------------------------------- #
def _valid_poly_native(path: Path, override_crs: str | None):
    """(poly, crs_str, depth_median_m, used_bbox). Decimated read; if the raster
    carries no CRS, fall back to override_crs (from the HR catalog)."""
    cands = [str(path)]
    if path.suffix.lower() in (".nc", ".grd"):
        cands.append(f"NETCDF:{path}")
    last = None
    for cand in cands:
        try:
            with rasterio.open(cand) as ds:
                crs = ds.crs.to_string() if ds.crs else override_crs
                if not crs:
                    last = "no CRS (and no override)"
                    continue
                h, w = ds.height, ds.width
                if not h or not w:
                    last = "empty"; continue
                sy = max(1, h // _THUMB); sx = max(1, w // _THUMB)
                arr = ds.read(1, out_shape=(h // sy, w // sx), masked=True)
                td = ds.transform * ds.transform.scale(sx, sy)
            a = np.asarray(arr.filled(np.nan) if hasattr(arr, "filled") else arr,
                           dtype="float64")
            valid = np.isfinite(a)
            if hasattr(arr, "mask") and not np.isscalar(arr.mask) and arr.mask.ndim:
                valid &= ~arr.mask
            if valid.ndim != 2:
                valid = np.squeeze(valid)
            if valid.sum() == 0:
                last = "no valid pixels"; continue
            depth = float(np.nanmedian(np.abs(a[valid]))) if np.isfinite(a[valid]).any() else float("nan")
            polys = [shape(g) for g, v in shapes(valid.astype("uint8"),
                     mask=valid, transform=td) if v == 1]
            if not polys:
                last = "no shapes"; continue
            return unary_union(polys), crs, depth, False
        except Exception as e:
            last = str(e)[:160]
    if gmt_grd_mod.is_gmt_grd(path):
        try:
            tmp = path.with_suffix(".a5conv.tif")
            gmt_grd_mod.convert(path, tmp)
            r = _valid_poly_native(tmp, override_crs)
            try: tmp.unlink()
            except FileNotFoundError: pass
            return r
        except Exception as e:
            last = f"gmt convert: {e}"
    raise RuntimeError(last or "no polygon")


def _to_4326(poly, src_crs: str):
    tr = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True).transform
    return shp_transform(tr, poly)


def _staged_rasters(hr_id: str) -> list[Path]:
    d = STAGING / hr_id.replace(":", "_").replace("/", "_")
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir()):
        if p.name.endswith(".a5conv.tif"):
            continue  # our own transient GMT-conversion output; never an HR grid
        if p.suffix.lower() in RASTER_EXT and not p.name.endswith(".provenance.json"):
            out.append(p)
        elif p.name.endswith(".grd.gz"):  # gmt grd needs decompress; skip if .grd twin exists
            twin = p.with_suffix("")  # strip .gz -> .grd
            if not twin.exists():
                out.append(p)
    return out


def hr_footprint_4326(hr_id: str, cat_row) -> tuple[object | None, float, bool, str]:
    """Return (poly4326, depth_m, used_bbox, note) for one HR."""
    override = None
    if cat_row is not None:
        override = (cat_row.get("recovered_crs") or cat_row.get("native_crs") or None)
    rasters = _staged_rasters(hr_id)
    rasters = [r for r in rasters if not r.name.lower().endswith(".pdf")]
    if not rasters:
        # No usable raster (e.g. PDF-only). Fall back to catalog geom (bbox) w/ flag.
        if cat_row is not None and cat_row.geometry is not None:
            return cat_row.geometry, _depth_from_cat(cat_row), True, "no raster; catalog geom (bbox?) used"
        return None, float("nan"), True, "no raster and no catalog geom"
    polys, depths, notes = [], [], []
    for r in rasters:
        try:
            p, crs, depth, _ = _valid_poly_native(r, override)
            polys.append(_to_4326(p, crs)); depths.append(depth)
        except Exception as e:
            notes.append(f"{r.name}:{e}")
    if not polys:
        if cat_row is not None and cat_row.geometry is not None:
            return cat_row.geometry, _depth_from_cat(cat_row), True, "raster polygonise failed; catalog geom used; " + ";".join(notes)[:120]
        return None, float("nan"), True, "raster polygonise failed; " + ";".join(notes)[:160]
    depth = np.nanmedian([d for d in depths if math.isfinite(d)]) if any(math.isfinite(d) for d in depths) else _depth_from_cat(cat_row)
    return unary_union(polys), float(depth), False, (";".join(notes)[:120] if notes else "")


def _depth_from_cat(cat_row) -> float:
    if cat_row is None:
        return float("nan")
    dmn, dmx = cat_row.get("depth_min_m"), cat_row.get("depth_max_m")
    vals = [abs(float(v)) for v in (dmn, dmx) if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return float(np.mean(vals)) if vals else float("nan")


def _utm_for(lon: float, lat: float) -> str:
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


def buffer_4326(poly, depth_m: float) -> tuple[object, float]:
    """Buffer a 4326 polygon by max(2*depth, 1km), computed in local UTM."""
    c = poly.centroid
    utm = _utm_for(c.x, c.y)
    fwd = pyproj.Transformer.from_crs("EPSG:4326", utm, always_xy=True).transform
    inv = pyproj.Transformer.from_crs(utm, "EPSG:4326", always_xy=True).transform
    buf_m = max(2.0 * depth_m, _MIN_BUFFER_M) if math.isfinite(depth_m) else _MIN_BUFFER_M
    return shp_transform(inv, shp_transform(fwd, poly).buffer(buf_m)), buf_m / 1000.0


# --------------------------------------------------------------------------- #
# Nav fetch + parse
# --------------------------------------------------------------------------- #
def fetch_nav(rec: FileRec, cruise_dir: Path,
              session: requests.Session | None = None) -> Path | None:
    cruise_dir.mkdir(parents=True, exist_ok=True)
    out = cruise_dir / rec.name
    if out.exists():
        return out
    getter = session or requests
    try:
        r = getter.get(rec.url, headers=_HEADERS, timeout=60)
    except Exception as e:
        log.warning("nav fetch %s failed: %s", rec.url, e); return None
    if r.status_code != 200:
        log.warning("nav %s -> HTTP %s", rec.url, r.status_code); return None
    out.write_bytes(r.content)
    return out


def prefetch_nav(recs: list[FileRec], cruise_dir: Path, workers: int = 8) -> None:
    """Concurrently download missing nav files for a cruise (idempotent)."""
    cruise_dir.mkdir(parents=True, exist_ok=True)
    todo = [r for r in recs if not (cruise_dir / r.name).exists()]
    if not todo:
        return
    from concurrent.futures import ThreadPoolExecutor
    sessions = [requests.Session() for _ in range(workers)]
    def _job(i_rec):
        i, rec = i_rec
        fetch_nav(rec, cruise_dir, session=sessions[i % workers])
        time.sleep(_THROTTLE)   # modest per-worker politeness
    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_job, enumerate(todo)))
    for s in sessions:
        s.close()


def parse_fnv_track(path: Path):
    """Return a shapely geometry (LineString/MultiPoint) of lon/lat, or None."""
    pts = []
    try:
        txt = path.read_text(errors="replace")
    except Exception:
        return None
    for ln in txt.splitlines():
        f = ln.split()
        if len(f) < 9:
            continue
        try:
            lon = float(f[7]); lat = float(f[8])
        except ValueError:
            continue
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            pts.append((lon, lat))
    if not pts:
        return None
    return LineString(pts) if len(pts) >= 2 else MultiPoint(pts)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
@dataclass
class CruiseVerdict:
    cruise: str
    whole_gb: float
    subset_gb: float = 0.0
    n_files_total: int = 0
    n_files_intersect: int = 0
    n_nav_missing: int = 0
    buffer_km: float = 0.0
    hr_used: list[str] = field(default_factory=list)
    hr_dropped: list[str] = field(default_factory=list)
    footprint_bbox_flag: bool = False
    verdict: str = ""
    note: str = ""


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    d = json.loads(STAGE_A_JSON.read_text())
    targets = [r for r in d["per_cruise"] if r["fetch_estimate_gb"] >= THRESHOLD_GB]
    targets.sort(key=lambda x: -x["fetch_estimate_gb"])
    cat = gpd.read_file(HR_CATALOG).set_index("hr_id")
    log.info("Stage A.5: %d target cruises (>= %.0f GB)", len(targets), THRESHOLD_GB)

    footprint_rows = []   # for persisted gpkg
    verdicts: list[CruiseVerdict] = []

    for t in targets:
        cruise = t["cruise"]
        cv = CruiseVerdict(cruise=cruise, whole_gb=t["fetch_estimate_gb"])
        hrs = [h for h in t["hr_served"].split(";") if h]
        # --- footprints ---
        polys = []
        for hr in hrs:
            if hr in DROPPED_HR:
                cv.hr_dropped.append(hr); continue
            row = cat.loc[hr] if hr in cat.index else None
            if row is not None and getattr(row, "ndim", 1) > 1:
                row = row.iloc[0]
            poly, depth, used_bbox, note = hr_footprint_4326(hr, row)
            if poly is None:
                cv.hr_dropped.append(hr)
                cv.note += f"{hr}: no footprint ({note}); "
                continue
            bpoly, bkm = buffer_4326(poly, depth)
            cv.hr_used.append(hr); cv.buffer_km = max(cv.buffer_km, bkm)
            cv.footprint_bbox_flag |= used_bbox
            polys.append(bpoly)
            footprint_rows.append({"cruise": cruise, "hr_id": hr, "depth_m": depth,
                                   "buffer_km": bkm, "used_bbox": used_bbox,
                                   "note": note, "geometry": bpoly})
            if note:
                cv.note += f"{hr}: {note}; "
        log.info("[%s] HR used=%s dropped=%s buffer=%.1fkm bbox_flag=%s",
                 cruise, cv.hr_used, cv.hr_dropped, cv.buffer_km, cv.footprint_bbox_flag)

        if not polys:
            cv.verdict = "exclude_no_valid_hr"
            cv.note += "no valid HR footprint to test against; "
            verdicts.append(cv); continue
        fp_union = unary_union(polys)

        # --- nav fetch + intersection ---
        iso_url = data_dir_from_iso(cruise, GEOPORTAL)
        work_url, _ = resolve_data_dir(iso_url, DIRLIST) if iso_url else (None, "")
        if not work_url:
            cv.verdict = "needs_manual_nav"; cv.note += "data dir unresolved; "
            verdicts.append(cv); continue
        recs = iter_cruise_files(work_url, DIRLIST)
        swath = [r for r in recs if r.kind == "swath"]
        nav = {r.key: r for r in recs if r.kind == "nav"}
        cv.n_files_total = len(swath)
        cdir = NAVCACHE / cruise
        prefetch_nav([nav[s.key] for s in swath if s.key in nav], cdir)
        for s in swath:
            navrec = nav.get(s.key)
            track = None
            if navrec is not None:
                npath = cdir / navrec.name
                if npath.exists():
                    track = parse_fnv_track(npath)
            if track is None:
                cv.n_nav_missing += 1
                # over-include: keep a file we cannot test
                cv.n_files_intersect += 1
                cv.subset_gb += s.bytes / 1024**3
                continue
            if track.intersects(fp_union):
                cv.n_files_intersect += 1
                cv.subset_gb += s.bytes / 1024**3

        # --- verdict ---
        frac = cv.subset_gb / cv.whole_gb if cv.whole_gb else 0.0
        if cv.n_files_intersect == 0:
            cv.verdict = "transit_no_overlap"          # -> recommend EXCLUDE
        elif frac >= 0.85:
            cv.verdict = "keep_whole"
        else:
            cv.verdict = "keep_subset"
        log.info("[%s] files %d/%d intersect (nav_missing=%d) subset=%.2f/%.2f GB -> %s",
                 cruise, cv.n_files_intersect, cv.n_files_total, cv.n_nav_missing,
                 cv.subset_gb, cv.whole_gb, cv.verdict)
        verdicts.append(cv)

    _write_outputs(d, targets, verdicts, footprint_rows)


def _write_outputs(stage_a, targets, verdicts, footprint_rows):
    today = date.today().isoformat()
    # revised budget
    target_names = {t["cruise"] for t in targets}
    small_sum = sum(r["fetch_estimate_gb"] for r in stage_a["per_cruise"]
                    if r["cruise"] not in target_names)
    keep_sum = sum(v.subset_gb for v in verdicts
                   if v.verdict in ("keep_subset", "keep_whole"))
    excluded = [v.cruise for v in verdicts if v.verdict.startswith(("transit", "exclude"))]
    manual = [v.cruise for v in verdicts if v.verdict == "needs_manual_nav"]
    revised = small_sum + keep_sum
    baseline = stage_a["grand_fetch_estimate_gb"]

    csv_path = REPO / f"reports/stage_a5_footprint_subset_{today}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cruise", "whole_GB", "subset_GB", "n_files_total",
                    "n_files_intersect", "n_nav_missing", "fraction_kept",
                    "buffer_km", "footprint_bbox_flag", "hr_used", "hr_dropped",
                    "verdict", "note"])
        for v in verdicts:
            frac = round(v.subset_gb / v.whole_gb, 3) if v.whole_gb else 0
            w.writerow([v.cruise, round(v.whole_gb, 2), round(v.subset_gb, 2),
                        v.n_files_total, v.n_files_intersect, v.n_nav_missing, frac,
                        round(v.buffer_km, 1), v.footprint_bbox_flag,
                        ";".join(v.hr_used), ";".join(v.hr_dropped),
                        v.verdict, v.note.strip()])

    summary = {
        "generated": today, "threshold_gb": THRESHOLD_GB,
        "n_targets": len(targets),
        "baseline_fetch_gb": baseline,
        "small_cruises_whole_gb": round(small_sum, 2),
        "targets_kept_subset_gb": round(keep_sum, 2),
        "revised_total_gb": round(revised, 2),
        "savings_gb": round(baseline - revised, 2),
        "excluded_cruises": excluded,
        "needs_manual_nav": manual,
        "per_cruise": [vars(v) for v in verdicts],
    }
    (REPO / f"reports/stage_a5_footprint_subset_{today}.json").write_text(
        json.dumps(summary, indent=2, default=str))

    if footprint_rows:
        gdf = gpd.GeoDataFrame(footprint_rows, geometry="geometry", crs="EPSG:4326")
        gdf.to_file(REPO / f"reports/discovery/stage_a5_hr_footprints_{today}.gpkg",
                    driver="GPKG", layer="footprints")

    print("\n=========== STAGE A.5 SUMMARY ===========")
    print(f"targets (>= {THRESHOLD_GB:.0f} GB)   : {len(targets)}")
    print(f"baseline fetch         : {baseline} GB")
    print(f"  small (41) whole     : {small_sum:.2f} GB")
    print(f"  targets kept subset  : {keep_sum:.2f} GB")
    print(f"REVISED TOTAL          : {revised:.2f} GB  (saves {baseline-revised:.2f} GB)")
    print(f"excluded (transit)     : {excluded}")
    print(f"needs_manual_nav       : {manual}")
    print(f"\nwrote {csv_path}")


if __name__ == "__main__":
    main()
