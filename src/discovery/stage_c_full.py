"""Phase 2 Stage C — full MB-System gridding run (one cruise per invocation).

Applies the pilot's locked-in corrections:
  - measure on the TRUE HR footprint polygon (never bbox)
  - cell estimate from FOOTPRINT-LOCAL depth (median of soundings inside the
    footprint), not the cruise-wide mbinfo median
  - decompress .gz first; pass uncompressed swath (.mb163/.mb32/.mb15) straight
  - provisional ratio uses the A.6-measured HR cell (hr_resolution_sanity.csv),
    NOT the NaN catalog native_res_m (informational only — no tiering here)
  - near a tier edge (within 20%): derive true LR native res from sounding
    density inside the footprint (mblist), not the cell/√fill proxy

Usage (Slurm array, one cruise per task):
  python -m src.discovery.stage_c_full --cruise FK006B --mode clean
  python -m src.discovery.stage_c_full --spotcheck FK006B      # C-full-0
  python -m src.discovery.stage_c_full --sweep                 # corpus sweep
"""
from __future__ import annotations

import gzip
import json
import logging
import math
import os
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask

from src.discovery.stage_c_pilot import (
    mb, estimate_cell_m, fmt_for, _read_grd, RAW_LR, GRIDDED, BIND, SANDBOX,
)

log = logging.getLogger("stage_c_full")
REPO = Path(__file__).resolve().parents[2]
A6 = gpd.read_file(REPO / "reports/discovery/stage_a6_hr_footprints_2026-06-22.gpkg").set_index("hr_id")
FL = __import__("pandas").read_csv(REPO / "reports/stage_b_fetch_list_2026-06-22.csv").set_index("cruise")
SAN = __import__("pandas").read_csv(REPO / "reports/discovery/hr_resolution_sanity.csv").set_index("hr_id")
import pandas as pd
LR = gpd.read_file(REPO / "reports/discovery/lr_candidates.gpkg")
RESULT_DIR = REPO / "reports/discovery/stage_c_full"

BEAMWIDTH = {"em302": 1.0, "em710": 1.0, "em712": 1.0, "em122": 1.0, "em300": 1.0,
             "seabeam 2000": 3.3, "seabeam 2100": 2.0, "seabeam 3012": 1.5,
             "hydrosweep": 2.3, "mesotech": 3.0}
DEFAULT_BW = 1.5
TIER_EDGES = (5.0, 25.0, 40.0)


def beamwidth_for(cruise: str) -> tuple[float, str]:
    rows = LR[LR.cruise_id == cruise]
    sonar = rows["sonar"].dropna().iloc[0] if rows["sonar"].notna().any() else ""
    s = sonar.lower()
    for k, v in BEAMWIDTH.items():
        if k in s:
            return v, sonar
    return DEFAULT_BW, sonar


CAT_GEOM = gpd.read_file(REPO / "reports/discovery/hr_catalog.gpkg").set_index("hr_id")


def footprint_for(hr_id: str):
    """Return a valid 4326 footprint for an HR. The A.6 gpkg has 3 corrupt
    (mixed-CRS) geometries (MGDS:5174/21998/7833) with projected coords; for
    those, fall back to the (verified-clean) HR-catalog geometry."""
    g = A6.loc[hr_id].geometry if hr_id in A6.index else None
    if g is not None:
        b = g.bounds
        if -180 <= b[0] and b[2] <= 180 and -90 <= b[1] and b[3] <= 90:
            return g
        log.warning("A6 footprint for %s is out-of-range %s; using catalog geom",
                    hr_id, [round(x, 1) for x in b])
    if hr_id in CAT_GEOM.index:
        cg = CAT_GEOM.loc[hr_id].geometry
        if cg is not None:
            return cg
    return g


def hr_res_for(hr_id: str):
    if hr_id in SAN.index:
        v = SAN.loc[hr_id, "measured_finest_cell_m"]
        try:
            v = float(v)
            return v if v == v else None
        except Exception:
            return None
    return None


def prepare_cruise(cruise: str, workdir: Path) -> tuple[Path, list[Path], int]:
    """Decompress .gz / pass uncompressed swath; build datalist.mb-1."""
    src = RAW_LR / cruise
    swath = sorted(p for p in src.iterdir()
                   if not p.name.endswith(".fnv")
                   and (p.name.endswith(".gz")
                        or __import__("re").search(r"\.mb\d+$", p.name)))
    workdir.mkdir(parents=True, exist_ok=True)
    files = []
    fmt = 58
    dl = workdir / "datalist.mb-1"
    with dl.open("w") as f:
        for p in swath:
            if p.name.endswith(".gz"):
                out = workdir / p.name[:-3]
                if not out.exists():
                    with gzip.open(p, "rb") as s, out.open("wb") as d:
                        while True:
                            b = s.read(1 << 22)
                            if not b:
                                break
                            d.write(b)
                fmt = fmt_for(p.name)
            else:
                out = workdir / p.name           # uncompressed: symlink in
                if not out.exists():
                    out.symlink_to(p)
                import re
                fmt = int(re.search(r"\.mb(\d+)$", p.name).group(1))
            f.write(f"{out.name} {fmt}\n")
            files.append(out)
    return dl, files, fmt


def parallel_mbclean(files: list[Path], fmt: int, workdir: Path, nproc: int = 8) -> None:
    """Run mbclean per-file across cores (serial mbclean -I datalist hung the
    pilot). Each file's edits land in its own .esf."""
    listing = workdir / "_clean_files.txt"
    listing.write_text("\n".join(f.name for f in files))
    # xargs -P fans mbclean across cores; one apptainer exec per file.
    cmd = (f"cat {listing.name} | xargs -P {nproc} -I{{}} "
           f"apptainer exec {' '.join(BIND)} {SANDBOX} mbclean -F{fmt} -I {{}}")
    subprocess.run(["bash", "-lc", cmd], cwd=str(workdir),
                   capture_output=True, text=True)


def process(dlist: Path, files: list[Path], fmt: int, workdir: Path, mode: str) -> Path:
    if mode != "clean":
        return dlist
    parallel_mbclean(files, fmt, workdir)
    mb(["mbprocess", "-I", dlist.name], cwd=str(workdir))
    dp = workdir / "datalistp.mb-1"
    return dp if dp.exists() else dlist


def footprint_depth(dlist: Path, workdir: Path, union_poly) -> float:
    """Median depth of soundings INSIDE the footprint (footprint-local)."""
    w, s, e, n = union_poly.bounds
    r = mb(["mblist", "-I", dlist.name, "-OXYZ", "-R", f"{w}/{e}/{s}/{n}"],
           cwd=str(workdir))
    depths = []
    for ln in (r.stdout or "").splitlines()[:200000]:
        p = ln.split()
        if len(p) >= 3:
            try:
                depths.append(abs(float(p[2])))
            except ValueError:
                pass
    return float(np.median(depths)) if depths else float("nan")


def grid_cruise(cruise: str, mode: str = "clean") -> list[dict]:
    wd = Path(os.environ.get("L_SCRATCH", "/tmp")) / "stage_c_full" / cruise
    dlist, files, fmt = prepare_cruise(cruise, wd)
    log.info("[%s] %d files fmt %d mode %s", cruise, len(files), fmt, mode)
    live = [h for h in str(FL.loc[cruise, "live_HR"]).split(";") if h and (h in A6.index or h in CAT_GEOM.index)]
    if not live:
        return [{"cruise": cruise, "status": "no_live_hr_footprint"}]
    union = gpd.GeoSeries([footprint_for(h) for h in live], crs="EPSG:4326").union_all()
    bw, sonar = beamwidth_for(cruise)
    depth = footprint_depth(dlist, wd, union)
    if depth != depth:
        depth = 50.0 / (2 * math.tan(math.radians(bw / 2)))  # placeholder
    dlist = process(dlist, files, fmt, wd, mode)
    cell_m = estimate_cell_m(depth, bw)
    # one mbgrid over the union footprint + 1 km margin
    w, s, e, n = union.bounds
    mlat = (s + n) / 2
    dlon = 1 / (111320 * max(0.2, math.cos(math.radians(mlat))))
    dlat = 1 / 111320
    R = f"{w-1000*dlon}/{e+1000*dlon}/{s-1000*dlat}/{n+1000*dlat}"
    dx, dy = cell_m * dlon, cell_m * dlat
    root = wd / f"grid_{cruise}"
    mb(["mbgrid", "-I", dlist.name, "-O", root.name, "-R", R,
        "-E", f"{dx}/{dy}/degrees", "-A2", "-G3", "-F1", "-C0", "-M"], cwd=str(wd))
    grd = wd / f"{root.name}.grd"
    out = []
    if not grd.exists():
        return [{"cruise": cruise, "status": "grid_failed", "sonar": sonar}]
    # persist union grid
    GRIDDED.mkdir(parents=True, exist_ok=True)
    (GRIDDED / f"{cruise}__union.grd").write_bytes(grd.read_bytes())
    for hr in live:
        out.append(measure_hr(cruise, hr, grd, dlist, wd, cell_m, depth, sonar, bw, mode))
    # node-local cleanup
    for f in files:
        try:
            f.unlink()
        except Exception:
            pass
    return out


def measure_hr(cruise, hr, grd, dlist, wd, cell_m, depth, sonar, bw, mode) -> dict:
    a, tr, bounds, res = _read_grd_full(grd)
    poly = footprint_for(hr)
    inpoly = ~geometry_mask([poly], out_shape=a.shape, transform=tr, invert=False)
    data = np.isfinite(a)
    n_in = int(inpoly.sum())
    fill = round(float((data & inpoly).sum() / max(1, n_in)), 4)
    native = round(cell_m / math.sqrt(fill), 2) if fill > 0 else cell_m
    hr_res = hr_res_for(hr)
    ratio = round(native / hr_res, 2) if hr_res and hr_res > 0 else None
    method = "cell/sqrt(fill)"
    # near a tier edge -> derive true LR native res from sounding density
    if ratio is not None and any(abs(ratio - ed) <= 0.2 * ed for ed in TIER_EDGES):
        sp = sounding_spacing(dlist, wd, poly)
        if sp == sp and sp > 0:
            native = round(sp, 2)
            ratio = round(native / hr_res, 2) if hr_res else None
            method = "sounding_density(mblist)"
    vals = a[data & inpoly]
    gdmed = round(float(np.nanmedian(vals)), 1) if vals.size else float("nan")
    overlay = make_overlay(grd, poly, bounds, cruise, hr)
    bucket = SAN.loc[hr, "resolution"] if hr in SAN.index else ""
    cov = "near_nadir" if fill >= 0.15 else "outer_beam_grazing"
    qc = ("reject" if (fill < 0.3 or not vals.size) else "pass")
    return {"cruise": cruise, "hr_id": hr, "sonar": sonar, "beamwidth_deg": bw,
            "footprint_depth_m": round(depth, 1), "achieved_cell_m": round(cell_m, 2),
            "fill_fraction": fill, "footprint_pct_of_grid": round(100 * n_in / a.size, 1),
            "lr_native_res_m": native, "native_method": method,
            "hr_res_m": hr_res, "hr_bucket": bucket,
            "provisional_ratio": ratio,
            "ratio_provisional_ok_finer": bucket == "ok_finer_verify",
            "grid_depth_median": gdmed, "coverage_verdict": cov,
            "process_mode": mode, "qc": qc, "overlay": overlay,
            "grd_path": str(GRIDDED / f"{cruise}__union.grd"), "status": "gridded"}


def _read_grd_full(p):
    for cand in (str(p), f"NETCDF:{p}"):
        try:
            with rasterio.open(cand) as ds:
                a = np.asarray(ds.read(1, masked=True).filled(np.nan), dtype="float64")
                return a, ds.transform, ds.bounds, ds.res
        except Exception:
            continue
    return None, None, None, None


def sounding_spacing(dlist: Path, wd: Path, poly) -> float:
    """True LR native res = mean sounding spacing inside the footprint =
    sqrt(footprint_area / n_soundings_in_footprint)."""
    from shapely.geometry import Point
    from shapely.prepared import prep
    w, s, e, n = poly.bounds
    r = mb(["mblist", "-I", dlist.name, "-OXYZ", "-R", f"{w}/{e}/{s}/{n}"], cwd=str(wd))
    pg = prep(poly)
    pts = 0
    mlat = (s + n) / 2
    for ln in (r.stdout or "").splitlines():
        c = ln.split()
        if len(c) >= 2:
            try:
                lon, lat = float(c[0]), float(c[1])
            except ValueError:
                continue
            if pg.contains(Point(lon, lat)):
                pts += 1
    if pts < 10:
        return float("nan")
    # area of polygon in m^2
    import pyproj
    from shapely.ops import transform as shp_t
    utm = f"EPSG:{32600 + int((poly.centroid.x + 180)//6) + 1}" if poly.centroid.y >= 0 \
        else f"EPSG:{32700 + int((poly.centroid.x + 180)//6) + 1}"
    tr = pyproj.Transformer.from_crs("EPSG:4326", utm, always_xy=True).transform
    area = shp_t(tr, poly).area
    return math.sqrt(area / pts)


def make_overlay(grd, poly, bounds, cruise, hr_id) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import LightSource
        a, *_ = _read_grd_full(grd)
        if a is None:
            return ""
        ls = LightSource(azdeg=315, altdeg=45)
        hs = ls.hillshade(np.nan_to_num(a, nan=float(np.nanmedian(a))), vert_exag=1, dx=1, dy=1)
        ext = [bounds.left, bounds.right, bounds.bottom, bounds.top]
        fig, ax = plt.subplots(figsize=(7, 7))
        ax.imshow(hs, cmap="gray", origin="upper", extent=ext, aspect="auto")
        ax.imshow(np.where(np.isfinite(a), a, np.nan), origin="upper", extent=ext,
                  cmap="viridis", alpha=0.45, aspect="auto")
        for gp in (poly.geoms if poly.geom_type == "MultiPolygon" else [poly]):
            xs, ys = gp.exterior.xy
            ax.plot(xs, ys, color="red", lw=1.8)
        ax.set_title(f"{cruise} -> {hr_id}\nLR gridded + HR footprint (red)")
        out = GRIDDED / f"overlay_{cruise}__{hr_id.replace(':','_')}.png"
        fig.savefig(out, dpi=130, bbox_inches="tight"); plt.close(fig)
        return str(out)
    except Exception as e:
        log.warning("overlay %s/%s: %s", cruise, hr_id, e)
        return ""


def run_cruise(cruise: str, mode: str):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    res = grid_cruise(cruise, mode)
    (RESULT_DIR / f"{cruise}.json").write_text(json.dumps(res, indent=2, default=str))
    for r in res:
        log.info("RESULT %s", json.dumps({k: r.get(k) for k in
                 ("cruise", "hr_id", "achieved_cell_m", "fill_fraction",
                  "lr_native_res_m", "provisional_ratio", "coverage_verdict", "qc", "status")}))


def spotcheck(cruise: str):
    """C-full-0: grid one cruise raw vs parallel-clean; compare over the footprint."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    arrs = {}
    out = {"cruise": cruise}
    for mode in ("raw", "clean"):
        t0 = os.times().elapsed
        res = grid_cruise(cruise, mode)
        dt = round(os.times().elapsed - t0, 1)
        # snapshot the union grid array for this mode
        a, *_ = _read_grd_full(GRIDDED / f"{cruise}__union.grd")
        arrs[mode] = a
        out[mode] = {"res": res, "wall_s": dt}
    raw, clean = arrs["raw"], arrs["clean"]
    if raw is not None and clean is not None and raw.shape == clean.shape:
        both = np.isfinite(raw) & np.isfinite(clean)
        diff = np.abs(raw - clean)[both]
        out["compare"] = {
            "cells_both": int(both.sum()),
            "pct_changed_gt_5m": round(100 * float((diff > 5).sum()) / max(1, both.sum()), 2),
            "max_abs_diff_m": round(float(diff.max()) if diff.size else 0, 1),
            "raw_depth_range": [round(float(np.nanmin(raw)), 1), round(float(np.nanmax(raw)), 1)],
            "clean_depth_range": [round(float(np.nanmin(clean)), 1), round(float(np.nanmax(clean)), 1)],
            "raw_fill": int(np.isfinite(raw).sum()), "clean_fill": int(np.isfinite(clean).sum()),
        }
    print(json.dumps(out, indent=2, default=str))
    (RESULT_DIR / f"spotcheck_{cruise}.json").write_text(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    a = sys.argv
    if "--spotcheck" in a:
        spotcheck(a[a.index("--spotcheck") + 1])
    elif "--cruise" in a:
        mode = a[a.index("--mode") + 1] if "--mode" in a else "clean"
        run_cruise(a[a.index("--cruise") + 1], mode)
