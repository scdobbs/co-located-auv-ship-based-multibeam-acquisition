"""ACQ-R03 §3.2 — AT37-05__MGDS_24043 review package (development pair; Steve decides under the §3.1 criterion).

Writes to OAK review/acq_r03/AT37-05__MGDS_24043/ (all in lr.tif's CRS, EPSG:32613):
  lr_hillshade.tif, hr_hillshade.tif, ship_count.tif, ship_rsd.tif (copies of the contract products),
  bimodal_gap.tif / bimodal_minor_frac.tif (exact 1-D 2-means per cell with >= 6 soundings),
  bimodal_cells.tif (1 where minor fraction >= 0.2 and gap >= 10 m),
  windows_top3.gpkg (the three 2 x 2 km windows with the most bimodal cells) and windows_top3_points.gpkg
  (every sounding inside them: file, ping, beam, depth, cluster, cell row/col),
  line_offsets.csv (per pair of overlapping swath files: median over shared cells of median_i - median_j, MAD,
  n shared cells, local robust spread), line_summary.csv, summary.json.
Soundings: the same raw mblist extraction as the contract products (-MA, lr.tif window), with the beam and ping
identifiers added (-O "XYZ#NM": lon, lat, topo, beam, ping, unix time), one call per swath file so the file is known.
Usage (job): python -m src.acq_r03.at37_review_package [--nproc 8]
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import Point, box

from src.acq_r01 import common as C
from src.acq_r01 import build_products as V1
from src.acq_r03 import common as R

PAIR = "AT37-05__MGDS_24043"; CRUISE = "AT37-05"
OUT = R.REVIEW_DIR / PAIR
COLS = ["lon", "lat", "topo", "beam", "ping", "utime"]
MIN_N = 6; MINOR_FRAC = 0.2; GAP_M = 10.0; WIN_M = 2000.0
CACHE = C.SCRATCH_DATA / "acq_r03_at37_cache"


def _worker(args):
    src, fmt, window, workdir = args
    src = Path(src); workdir = Path(workdir); workdir.mkdir(parents=True, exist_ok=True)
    local = workdir / src.name[:-3]
    try:
        with gzip.open(src, "rb") as s, local.open("wb") as d:
            shutil.copyfileobj(s, d, 1 << 22)
        w, e, s_, n = window
        cmd = ["mblist", f"-F{fmt}", "-I", local.name, "-MA", "-R", f"{w:.6f}/{e:.6f}/{s_:.6f}/{n:.6f}", "-O", "XYZ#NM"]
        cache = CACHE / (src.name + ".parquet")
        if cache.exists():                                   # re-run after a stalled container: reuse the extracted soundings
            df = pd.read_parquet(cache)
            return {"file": src.name, "n": int(len(df)), "df": df if len(df) else None, "cmd": C.mb_cmdline(cmd) + "  # cached", "rc": 0}
        r = None
        for attempt in range(2):                             # a container start can stall indefinitely on a node: bounded, retried once
            try:
                r = C.mb(cmd, cwd=str(workdir), timeout=1200); break
            except subprocess.TimeoutExpired:
                r = None
        if r is None:
            return {"file": src.name, "n": 0, "df": None, "cmd": C.mb_cmdline(cmd), "rc": -9, "note": "mblist/container timeout (2 x 1200 s)"}
        out = r.stdout or ""
        if not out.strip():
            pd.DataFrame(columns=COLS + ["file"]).to_parquet(cache, index=False)
            return {"file": src.name, "n": 0, "df": None, "cmd": C.mb_cmdline(cmd), "rc": r.returncode}
        df = pd.read_csv(io.StringIO(out), sep="\t", header=None, names=COLS, dtype="float64", engine="c", na_values=["NaN", "nan"], on_bad_lines="skip")
        df["file"] = src.name
        df.to_parquet(cache, index=False)
        return {"file": src.name, "n": int(len(df)), "df": df, "cmd": C.mb_cmdline(cmd), "rc": r.returncode}
    finally:
        for p in [local] + [workdir / (local.name + ext) for ext in (".inf", ".fbt", ".fnv", ".esf", ".par", ".resf")]:
            try:
                p.unlink()
            except Exception:
                pass


def hillshade(path, out, az=315.0, alt=45.0):
    with rasterio.open(path) as ds:
        z = ds.read(1, masked=True).filled(np.nan).astype("float64"); prof = ds.profile; dx, dy = ds.res
    gy, gx = np.gradient(z, dy, dx)
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
    azr, altr = np.radians(az), np.radians(alt)
    hs = np.sin(altr) * np.cos(slope) + np.cos(altr) * np.sin(slope) * np.cos(azr - aspect)
    hs = np.where(np.isfinite(z), np.clip(hs, 0, 1), np.nan).astype("float32")
    prof.update(dtype="float32", nodata=np.nan, count=1, compress="DEFLATE")
    with rasterio.open(out, "w", **prof) as d:
        d.write(hs, 1)


def two_means_split(z):
    """Exact 1-D 2-means (k=2): the split of the sorted values minimising the within-cluster SS."""
    z = np.sort(np.asarray(z, float)); n = z.size
    cs = np.cumsum(z); cs2 = np.cumsum(z * z)
    k = np.arange(1, n)                       # left cluster = z[:k]
    l_ss = cs2[k - 1] - cs[k - 1] ** 2 / k
    r_n = n - k; r_s = cs[-1] - cs[k - 1]; r_s2 = cs2[-1] - cs2[k - 1]
    r_ss = r_s2 - r_s ** 2 / r_n
    i = int(np.argmin(l_ss + r_ss)); kk = i + 1
    m1, m2 = cs[kk - 1] / kk, (cs[-1] - cs[kk - 1]) / (n - kk)
    return abs(m2 - m1), min(kk, n - kk) / n, (z[kk - 1] + z[kk]) / 2


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--nproc", type=int, default=8)
    a = ap.parse_args(argv)
    t0 = time.time()
    C.assert_no_lockbox([PAIR]); C.assert_no_lockbox_cruise([CRUISE])
    pdir = R.OAK / "harmonized" / PAIR; OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.rglob("*"):
        if p.is_file():
            p.chmod(0o644)
    geom = V1.lr_window(pdir / "lr.tif")
    ny, nx = geom["shape"]; tr = geom["transform"]; crs = geom["crs"]
    files = V1.swath_files(C.RAW_SWATH_OAK / CRUISE); fmt = V1.fmt_for(files[0].name)
    workdir = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r03_at37"; CACHE.mkdir(parents=True, exist_ok=True)
    dfs, cmds, per_file = [], [], []
    with ProcessPoolExecutor(max_workers=a.nproc) as ex:
        for r in ex.map(_worker, [(str(f), fmt, geom["window"], str(workdir / f.name)) for f in files], chunksize=1):
            per_file.append({"file": r["file"], "n_rows": r["n"], "rc": r["rc"], **({"note": r["note"]} if r.get("note") else {})}); cmds.append(r["cmd"])
            if r["df"] is not None:
                dfs.append(r["df"])
    s = pd.concat(dfs, ignore_index=True)
    import pyproj
    t = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = t.transform(s.lon.values, s.lat.values)
    col = np.floor((x - tr.c) / tr.a).astype("int64"); row = np.floor((y - tr.f) / tr.e).astype("int64")
    inside = (row >= 0) & (row < ny) & (col >= 0) & (col < nx) & np.isfinite(s.topo.values)
    s = s[inside].copy(); s["x"] = x[inside]; s["y"] = y[inside]; s["row"] = row[inside]; s["col"] = col[inside]; s["cell"] = s.row * nx + s.col
    s["depth_m"] = -s.topo
    n_sound = len(s)
    # per-cell 2-means
    gap = np.full(ny * nx, np.nan, "float32"); minor = np.full(ny * nx, np.nan, "float32"); cnt = np.zeros(ny * nx, "int64"); split = {}
    for cell, g in s.groupby("cell"):
        cnt[cell] = len(g)
        if len(g) >= MIN_N:
            gp, mf, thr = two_means_split(g.topo.values); gap[cell] = gp; minor[cell] = mf; split[cell] = thr
    bim = np.isfinite(gap) & (minor >= MINOR_FRAC) & (gap >= GAP_M)
    prof = {"driver": "GTiff", "height": ny, "width": nx, "count": 1, "dtype": "float32", "crs": crs, "transform": tr, "nodata": np.nan, "compress": "DEFLATE"}
    for name, arr in (("bimodal_gap", gap), ("bimodal_minor_frac", minor), ("bimodal_cells", np.where(cnt >= MIN_N, bim.astype("float32"), np.nan))):
        with rasterio.open(OUT / f"{name}.tif", "w", **prof) as d:
            d.write(np.asarray(arr, "float32").reshape(ny, nx), 1)
    # context rasters
    hillshade(pdir / "lr.tif", OUT / "lr_hillshade.tif"); hillshade(pdir / "hr.tif", OUT / "hr_hillshade.tif")
    for name in ("ship_count", "ship_rsd"):
        shutil.copyfile(pdir / "ship_products_v2" / f"{name}.tif", OUT / f"{name}.tif")
    # 2 x 2 km windows ranked by the number of bimodal cells
    cw = int(round(WIN_M / abs(tr.a))); ch = int(round(WIN_M / abs(tr.e)))
    bim2 = bim.reshape(ny, nx); gap2 = gap.reshape(ny, nx); cnt2 = cnt.reshape(ny, nx)
    wins = []
    for r0 in range(0, ny, ch):
        for c0 in range(0, nx, cw):
            b = bim2[r0:r0 + ch, c0:c0 + cw]; g = gap2[r0:r0 + ch, c0:c0 + cw]; k = cnt2[r0:r0 + ch, c0:c0 + cw]
            nb = int(b.sum()); ne = int((k >= MIN_N).sum())
            if ne == 0:
                continue
            x0, y0 = tr * (c0, r0 + min(ch, ny - r0)); x1, y1 = tr * (c0 + min(cw, nx - c0), r0)
            wins.append({"r0": r0, "c0": c0, "n_bimodal": nb, "n_eligible": ne, "frac_bimodal": round(nb / ne, 4), "mean_gap_bimodal_m": float(np.nanmean(g[b])) if nb else 0.0, "geometry": box(x0, y0, x1, y1)})
    wins.sort(key=lambda w: (w["n_bimodal"], w["mean_gap_bimodal_m"]), reverse=True)
    top = wins[:3]
    gpd.GeoDataFrame([{k: v for k, v in w.items()} for w in top], geometry="geometry", crs=crs).assign(rank=range(1, len(top) + 1)).to_file(OUT / "windows_top3.gpkg", layer="windows", driver="GPKG")
    pts = []
    for rank, w in enumerate(top, 1):
        m = (s.row >= w["r0"]) & (s.row < w["r0"] + ch) & (s.col >= w["c0"]) & (s.col < w["c0"] + cw)
        g = s[m].copy(); g["window_rank"] = rank
        g["cluster"] = [("deep" if (c in split and z < split[c]) else ("shallow" if c in split else "n/a")) for c, z in zip(g.cell, g.topo)]
        pts.append(g)
    P = pd.concat(pts, ignore_index=True) if pts else s.iloc[:0]
    gpd.GeoDataFrame(P[["file", "ping", "beam", "utime", "depth_m", "topo", "cluster", "row", "col", "window_rank"]], geometry=[Point(xy) for xy in zip(P.x, P.y)], crs=crs).to_file(OUT / "windows_top3_points.gpkg", layer="soundings", driver="GPKG")
    # per-line table: per (file, cell) medians and within-line robust spread; every overlapping pair of files
    fc = s.groupby(["file", "cell"]).topo.agg(median="median", n="size", mad=lambda v: float(np.median(np.abs(v - np.median(v))))).reset_index()
    fc["rsd"] = 1.4826 * fc["mad"]
    lines = sorted(fc.file.unique()); rows_ = []
    piv_m = fc.pivot(index="cell", columns="file", values="median"); piv_r = fc.pivot(index="cell", columns="file", values="rsd")
    for i, fi in enumerate(lines):
        for fj in lines[i + 1:]:
            both = piv_m[fi].notna() & piv_m[fj].notna(); nsh = int(both.sum())
            if nsh == 0:
                continue
            d = (piv_m.loc[both, fi] - piv_m.loc[both, fj]).values
            spread = float(np.nanmedian(np.r_[piv_r.loc[both, fi].values, piv_r.loc[both, fj].values]))
            med = float(np.median(d)); mad = float(np.median(np.abs(d - med)))
            rows_.append({"line_i": fi, "line_j": fj, "n_shared_cells": nsh, "median_diff_m": round(med, 2), "mad_diff_m": round(mad, 2), "local_robust_spread_m": round(spread, 2),
                          "abs_median_diff_over_spread": round(abs(med) / spread, 2) if spread > 0 else None, "exceeds_local_spread": bool(abs(med) > spread)})
    lo = pd.DataFrame(rows_); lo.to_csv(OUT / "line_offsets.csv", index=False)
    ls = s.groupby("file").agg(n_soundings=("topo", "size"), n_cells=("cell", "nunique"), median_depth_m=("depth_m", "median"), t_start=("utime", "min"), t_end=("utime", "max")).reset_index()
    ls["t_start"] = pd.to_datetime(ls.t_start, unit="s"); ls["t_end"] = pd.to_datetime(ls.t_end, unit="s"); ls.to_csv(OUT / "line_summary.csv", index=False)
    n_el = int((cnt >= MIN_N).sum())
    summ = {"pair_id": PAIR, "cruise": CRUISE, "n_swath_files": len(files), "n_files_failed_extraction": sum(1 for p in per_file if p["rc"] != 0), "n_files_with_soundings_in_grid": int(s.file.nunique()), "n_soundings_in_grid": n_sound,
            "cells_with_soundings": int((cnt > 0).sum()), "cells_eligible_(count>=6)": n_el, "cells_bimodal": int(bim.sum()), "fraction_bimodal_of_eligible": round(float(bim.sum()) / max(1, n_el), 4),
            "bimodal_rule": {"min_count": MIN_N, "minor_fraction_min": MINOR_FRAC, "gap_min_m": GAP_M}, "gap_m_percentiles_eligible": {p: round(float(np.nanpercentile(gap[np.isfinite(gap)], p)), 2) for p in (50, 75, 90, 95)} if np.isfinite(gap).any() else None,
            "line_pairs_overlapping": int(len(lo)), "line_pairs_exceeding_local_spread": int(lo.exceeds_local_spread.sum()) if len(lo) else 0,
            "median_abs_line_diff_m": round(float(lo.median_diff_m.abs().median()), 2) if len(lo) else None, "max_abs_line_diff_m": round(float(lo.median_diff_m.abs().max()), 2) if len(lo) else None,
            "median_local_spread_m": round(float(lo.local_robust_spread_m.median()), 2) if len(lo) else None,
            "line_pairs_with_>=20_shared_cells": lo[lo.n_shared_cells >= 20].sort_values("median_diff_m", key=np.abs, ascending=False).head(15).to_dict("records") if len(lo) else [],
            "windows_top3": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in w.items() if k != "geometry"} for w in top],
            "mblist_commands": cmds[:2] + ["..."], "per_file": per_file, "wall_s": round(time.time() - t0, 1), "code_commit": C.git_commit(), "generated": R.utc_now()}
    R.write_json(OUT / "summary.json", summ); R.write_json(R.REPORT_DIR / "at37_05_review_summary.json", summ)
    for p in OUT.rglob("*"):
        if p.is_file():
            p.chmod(0o444)
    shutil.rmtree(workdir, ignore_errors=True)
    print(json.dumps({k: v for k, v in summ.items() if k not in ("per_file", "mblist_commands", "line_pairs_with_>=20_shared_cells")}, indent=1, default=str)); return 0


if __name__ == "__main__":
    sys.exit(main())
