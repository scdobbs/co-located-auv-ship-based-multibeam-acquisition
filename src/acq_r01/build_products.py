"""ACQ-R01 §2.2 steps 2-5 — build INTERFACE_CONTRACT_v1 ship-side products for one LR cruise.

Per pair served by the cruise (manifest ``lr_cruise`` == cruise, in the §2.1 scope):

  1. ``mblist`` (MB-System 5.8.2beta06, pinned Apptainer sandbox) dumps every VALID beam
     (``-MA``) of every swath file whose pings fall inside the pair's lr.tif window
     (``-R``), with: longitude, latitude, topography (positive up, as lr.tif),
     bathymetry acrosstrack distance, flat-bottom grazing angle, beam depression angle
     from vertical (``,A``), beam flag, ping count, unix time.  Field codes verified
     against the installed man page (see products.json "commands" and the report).
  2. Swath half-width per ping = max |acrosstrack| over that ping's valid beams.
     xtrack_frac = |acrosstrack| / half-width.  Beam angle from vertical = ``,A`` when
     the format supplies it, else 90 - flat-bottom grazing angle (recorded per cruise).
  3. Soundings are transformed EPSG:4326 -> lr.tif CRS with PROJ (pyproj), the same
     library rasterio/GDAL used in stage F, and binned DIRECTLY onto the lr.tif grid
     (its CRS, transform, shape; no mbgrid, no interpolation).
  4. QA of ship_mean_regrid vs lr.tif on common cells; flag exceeds_0.10 on
     RMS / median s_lr.  Nothing is tuned or re-gridded.
  5. Rasters + products.json written to
     $OAK/auv_ship_colocated_bathy/harmonized/<pair dir>/ship_products_v1/ (0444).

Processing mode = raw (stage C gridded raw; C-full-0 spot check).  Lockbox guard installed
on import of src.acq_r01.common; lockbox pairs/cruises can never be selected here.

Usage (inside a Slurm job):
  python -m src.acq_r01.build_products --cruise NA090 [--nproc 8] [--pairs a,b]
  python -m src.acq_r01.build_products --cruise SO242_1_EM122 --provider discol_so242_1
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import os
import re
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import transform_bounds

from src.acq_r01 import common as C

log = logging.getLogger("acq_r01.products")

# mblist output columns, in order (verified against the installed mblist man page,
# MB-System 5.8.2beta06):
#   X  longitude (decimal degrees, WGS84) of the beam (with -MA)
#   Y  latitude  (decimal degrees, WGS84) of the beam
#   Z  topography (positive upwards) (m)        -> same sign as lr.tif
#   D  bathymetry acrosstrack distance (m)
#   G  flat bottom grazing angle (degrees)
#   ,A beam depression angle measured from vertical down (degrees)
#   F  beamflag numeric value (0 = good)
#   N  ping count
#   M  unix (epoch) time in decimal seconds
MBLIST_O = "XYZDG,AFNM"
COLS = ["lon", "lat", "topo", "xtrack", "grazing", "beam_dep", "flag", "ping", "utime"]

# Provider-grid units whose raw swath was retrieved from PANGAEA (ACQ-R01 §2.2 step 6).
PROVIDER_SWATH = {
    "discol_so242_1": {"cruise_dir": "SO242_1_EM122", "kind": "provider_swath",
                       "doi": "10.1594/PANGAEA.859528"},
    "tag_m127": {"cruise_dir": "M127_EM122", "kind": "provider_swath",
                 "doi": "10.1594/PANGAEA.899408"},
    "ccz_so268_1": {"cruise_dir": "SO268_1_EM122", "kind": "provider_swath",
                    "doi": "10.1594/PANGAEA.919755"},
}


def fmt_for(name: str) -> int:
    m = re.search(r"\.mb(\d+)(?:\.gz)?$", name)
    if m:
        return int(m.group(1))
    if re.search(r"\.all(\.gz)?$", name, re.I):
        return 58            # Kongsberg .all (3rd-gen); stage C used 58 for *.all.mb58.gz
    if re.search(r"\.gsf(\.gz)?$", name, re.I):
        return 121
    raise ValueError(f"cannot infer MB format for {name}")


def swath_files(cruise_dir: Path) -> list[Path]:
    return sorted(p for p in cruise_dir.iterdir()
                  if p.is_file() and not p.name.endswith((".fnv", ".json", ".part"))
                  and p.name not in ("SHA256SUMS",)
                  and (p.name.endswith(".gz") or re.search(r"\.(mb\d+|all|gsf)$", p.name, re.I)))


def lr_window(lr_path: Path, margin_factor: float = 3.0, min_margin_m: float = 2000.0):
    """lr.tif geometry + a geographic window: bounds in EPSG:4326 padded by
    max(min_margin, margin_factor*|median depth|) so that pings whose nav is
    outside the grid but whose outer beams reach into it are still read."""
    with rasterio.open(lr_path) as ds:
        arr = ds.read(1, masked=True).filled(np.nan).astype("float64")
        if ds.nodata is not None:
            arr[arr == ds.nodata] = np.nan
        crs, tr, shape = ds.crs, ds.transform, (ds.height, ds.width)
        b = ds.bounds
    depth = float(np.nanmedian(np.abs(arr))) if np.isfinite(arr).any() else 1000.0
    m = max(min_margin_m, margin_factor * depth)
    w, s, e, n = transform_bounds(crs, "EPSG:4326", b.left - m, b.bottom - m, b.right + m, b.top + m)
    return {"crs": crs, "transform": tr, "shape": shape, "lr": arr, "depth_med": depth,
            "margin_m": m, "window": (w, e, s, n)}


def _run_mblist_one(args):
    """Worker: (swath paths (one or many), fmt, window, workdir, grid, z_ref) -> per-file grid
    ACCUMULATORS (binned inside the worker, so the parent never holds raw soundings), plus the
    exact command line, row count and any stderr.  With several paths the files are listed in a
    datalist and read by ONE mblist call (-F-1); the ping key (N, unix time) keeps pings distinct."""
    srcs, fmt, window, workdir, grid, z_ref = args
    srcs = [Path(x) for x in ([srcs] if isinstance(srcs, str) else srcs)]
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    made, locals_ = [], []
    try:
        for src in srcs:
            local = workdir / (src.name[:-3] if src.name.endswith(".gz") else src.name)
            if src.name.endswith(".gz"):
                if not local.exists():
                    with gzip.open(src, "rb") as s, local.open("wb") as d:
                        shutil.copyfileobj(s, d, 1 << 22)
                    made.append(local)
            elif not local.exists():
                local.symlink_to(src); made.append(local)
            locals_.append(local)
        w, e, s_, n = window
        if len(locals_) == 1:
            cmd = ["mblist", f"-F{fmt}", "-I", locals_[0].name, "-MA", "-R", f"{w:.6f}/{e:.6f}/{s_:.6f}/{n:.6f}",
                   "-O", MBLIST_O]
            dl = None
        else:
            dl = workdir / f"datalist_{locals_[0].name}_{len(locals_)}.mb-1"
            dl.write_text("".join(f"{l.name} {fmt}\n" for l in locals_))
            cmd = ["mblist", "-F-1", "-I", dl.name, "-MA", "-R", f"{w:.6f}/{e:.6f}/{s_:.6f}/{n:.6f}", "-O", MBLIST_O]
        r = C.mb(cmd, cwd=str(workdir))
        cmdline = f"(cd {workdir} && {C.mb_cmdline(cmd)})" + (f"  # datalist: {', '.join(l.name for l in locals_)}" if dl else "")
        out = r.stdout or ""
        base = {"file": srcs[0].name if len(srcs) == 1 else f"{srcs[0].name} .. {srcs[-1].name} ({len(srcs)} files)",
                "n": 0, "acc": None, "stats": None, "cmd": cmdline, "rc": r.returncode,
                "stderr": (r.stderr or "")[-300:]}
        if not out.strip():
            return base
        df = pd.read_csv(io.StringIO(out), sep="\t", header=None, names=COLS, dtype="float64", engine="c",
                         na_values=["NaN", "nan"], on_bad_lines="skip")
        del out
        if df.shape[1] != len(COLS):
            base["stderr"] = f"unexpected column count {df.shape[1]}"; return base
        a = df.to_numpy(); del df
        import pyproj
        transformer = pyproj.Transformer.from_crs("EPSG:4326", grid["crs"], always_xy=True)
        acc, stats = bin_array(a, grid["shape"], grid["transform"], z_ref, transformer)
        base.update({"n": int(a.shape[0]), "acc": acc, "stats": stats})
        return base
    finally:
        for local in made:
            try:
                local.unlink()
            except Exception:
                pass
            for ext in (".inf", ".fbt", ".fnv", ".esf", ".par", ".resf"):
                try:
                    (workdir / (local.name + ext)).unlink()
                except Exception:
                    pass


def per_ping_geometry(a: np.ndarray):
    """Half-width per ping = max|xtrack| among the ping's valid beams.  Ping identity =
    (ping count N, unix time M): unique within a file and across a multi-file datalist run."""
    ping = a[:, COLS.index("ping")]
    utime = a[:, COLS.index("utime")]
    xt = np.abs(a[:, COLS.index("xtrack")])
    order = np.lexsort((ping, utime))
    ping_s, ut_s, xt_s = ping[order], utime[order], xt[order]
    new_grp = np.r_[True, (np.diff(ping_s) != 0) | (np.diff(ut_s) != 0)]
    starts = np.flatnonzero(new_grp)
    hw = np.maximum.reduceat(xt_s, starts)
    gid = np.cumsum(new_grp) - 1
    hw_per_row = hw[gid]
    out = np.empty_like(xt)
    out[order] = hw_per_row
    return out, len(starts)


ACC_KEYS = ("n", "sz", "szz", "sx", "sx_n", "sa_dep", "sa_dep_n", "sa_graz", "sa_graz_n")


def empty_acc(ny, nx):
    return {k: np.zeros(ny * nx, dtype="float64") for k in ACC_KEYS}


def empty_stats():
    return {"n_rows": 0, "n_pings": 0, "n_flag_nonzero": 0, "n_beamdep_valid": 0,
            "n_out_of_grid": 0, "n_hw_zero": 0, "hw_sum": 0.0, "hw_n": 0}


def merge_acc(acc, stats, acc2, stats2):
    if acc2 is None:
        return
    for k in ACC_KEYS:
        acc[k] += acc2[k]
    for k in stats:
        stats[k] += stats2[k]


def bin_array(a: np.ndarray, shape, transform, z_ref: float, transformer):
    """Bin one file's soundings (n x 9 mblist columns) onto the lr.tif grid; returns
    (accumulators, stats).  transform = affine coefficients [a, b, c, d, e, f]."""
    ny, nx = shape
    ta, tc, te, tf = transform[0], transform[2], transform[4], transform[5]
    acc = empty_acc(ny, nx); stats = empty_stats()
    if a is None or a.shape[0] == 0:
        return acc, stats
    lon, lat = a[:, 0], a[:, 1]
    topo, xt, graz, bdep, flag = a[:, 2], a[:, 3], a[:, 4], a[:, 5], a[:, 6]
    stats["n_rows"] += int(a.shape[0])
    stats["n_flag_nonzero"] += int((flag != 0).sum())
    hw, npings = per_ping_geometry(a)
    stats["n_pings"] += npings
    stats["hw_sum"] += float(hw.sum()); stats["hw_n"] += int(hw.size)
    ok_hw = hw > 0
    stats["n_hw_zero"] += int((~ok_hw).sum())
    xfrac = np.where(ok_hw, np.abs(xt) / np.where(ok_hw, hw, 1.0), np.nan)
    bd_ok = np.isfinite(bdep) & (bdep > 0) & (bdep < 90)
    stats["n_beamdep_valid"] += int(bd_ok.sum())
    x, y = transformer.transform(lon, lat)
    col = np.floor((x - tc) / ta).astype("int64")
    row = np.floor((y - tf) / te).astype("int64")
    inside = (row >= 0) & (row < ny) & (col >= 0) & (col < nx) & np.isfinite(topo)
    stats["n_out_of_grid"] += int((~inside).sum())
    if not inside.any():
        return acc, stats
    idx = (row[inside] * nx + col[inside])
    z = topo[inside] - z_ref
    acc["n"] += np.bincount(idx, minlength=ny * nx)
    acc["sz"] += np.bincount(idx, weights=z, minlength=ny * nx)
    acc["szz"] += np.bincount(idx, weights=z * z, minlength=ny * nx)
    xf = xfrac[inside]; xf_ok = np.isfinite(xf)
    acc["sx"] += np.bincount(idx[xf_ok], weights=xf[xf_ok], minlength=ny * nx)
    acc["sx_n"] += np.bincount(idx[xf_ok], minlength=ny * nx)
    # beam angle accumulated separately for both methods; chosen at the end:
    #   ',A' = beam depression angle from vertical (launch angle, includes refraction), or
    #   geometric fallback atan(|acrosstrack| / |depth|) if the format does not carry ',A'
    geom_angle = np.degrees(np.arctan2(np.abs(xt), np.abs(topo)))
    for key, val in (("sa_dep", np.where(bd_ok, bdep, np.nan)[inside]),
                     ("sa_graz", geom_angle[inside])):
        v_ok = np.isfinite(val)
        acc[key] += np.bincount(idx[v_ok], weights=val[v_ok], minlength=ny * nx)
        acc[key + "_n"] += np.bincount(idx[v_ok], minlength=ny * nx)
    return acc, stats


def finalize(acc, stats, geom, z_ref):
    ny, nx = geom["shape"]
    n = acc["n"]
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(n > 0, acc["sz"] / np.where(n > 0, n, 1) + z_ref, np.nan)
        var = np.where(n > 1, (acc["szz"] - acc["sz"] ** 2 / np.where(n > 0, n, 1)) / np.where(n > 1, n - 1, 1), np.nan)
        sd = np.sqrt(np.clip(var, 0, None))
        sd[n < 2] = np.nan
        sxn = acc.get("sx_n", np.zeros_like(n))
        xfrac = np.where(sxn > 0, acc["sx"] / np.where(sxn > 0, sxn, 1), np.nan)
        # beam angle: use ,A (beam depression) if it was valid for >= 99% of rows, else 90-G
        use_dep = stats["n_rows"] > 0 and stats["n_beamdep_valid"] >= 0.99 * stats["n_rows"]
        key = "sa_dep" if use_dep else "sa_graz"
        an = acc.get(key + "_n", np.zeros_like(n)); asum = acc.get(key, np.zeros_like(n))
        angle = np.where(an > 0, asum / np.where(an > 0, an, 1), np.nan)
    count = np.where(n > 0, n, np.nan)
    out = {k: v.reshape(ny, nx).astype("float32") for k, v in
           (("ship_count", count), ("ship_mean_regrid", mean), ("ship_sd", sd),
            ("ship_xtrack_frac", xfrac), ("ship_beam_angle", angle))}
    method = ("mblist ',A' beam depression angle measured from vertical down (launch angle)" if use_dep
              else "geometric atan(|acrosstrack| / |depth|) (mblist ',A' not carried by this format)")
    return out, method


def write_raster(path: Path, arr: np.ndarray, geom):
    prof = {"driver": "GTiff", "height": geom["shape"][0], "width": geom["shape"][1], "count": 1,
            "dtype": "float32", "crs": geom["crs"], "transform": geom["transform"], "nodata": np.nan,
            "compress": "DEFLATE", "tiled": True, "BIGTIFF": "IF_SAFER"}
    if path.exists():
        path.chmod(0o644); path.unlink()
    with rasterio.open(path, "w", **prof) as d:
        d.write(arr, 1)
    path.chmod(0o444)


def qa_vs_lr(mean: np.ndarray, lr: np.ndarray, median_s_lr):
    common = np.isfinite(mean) & np.isfinite(lr)
    n = int(common.sum())
    if n == 0:
        return {"n_common_cells": 0, "rms_m": None, "median_offset_m": None, "mad_m": None,
                "rms_over_median_s_lr": None, "flag": "no_common_cells"}
    d = (mean[common] - lr[common]).astype("float64")
    rms = float(np.sqrt(np.mean(d ** 2))); med = float(np.median(d)); mad = float(np.median(np.abs(d - med)))
    ratio = float(rms / median_s_lr) if median_s_lr and median_s_lr > 0 else None
    flag = "ok" if (ratio is not None and ratio <= 0.10) else ("exceeds_0.10" if ratio is not None else "s_lr_unavailable")
    return {"n_common_cells": n, "rms_m": round(rms, 4), "median_offset_m": round(med, 4),
            "mad_m": round(mad, 4), "rms_over_median_s_lr": round(ratio, 4) if ratio is not None else None,
            "flag": flag}


_SLR_CACHE = {}


def median_s_lr(pair_id: str):
    """Median per-tile s_lr for the pair from the CNN repo's frozen tile tables
    (R03 expanded patch index, else R02 patch index, else R03 s3 per-tile table)."""
    if not _SLR_CACHE:
        srcs = [("R03 patches_clean_expanded/patch_index.parquet",
                 "/scratch/users/scdobbs/grl_review/R03/patches_clean_expanded/patch_index.parquet", "pair_id"),
                ("R02 patches_clean/patch_index.parquet",
                 "/scratch/users/scdobbs/grl_review/R02/patches_clean/patch_index.parquet", "pair_id"),
                ("R03 s3/s3_pertile.parquet", "/scratch/users/scdobbs/grl_review/R03/s3/s3_pertile.parquet", "pid")]
        for name, p, col in srcs:
            try:
                d = pd.read_parquet(p, columns=[col, "s_lr"])
                d = d[~d[col].isin(C.LOCKBOX)]
                _SLR_CACHE[name] = d.groupby(col).s_lr.median().to_dict()
            except Exception as e:
                log.warning("s_lr source %s unreadable: %s", name, e)
    for name, tab in _SLR_CACHE.items():
        if pair_id in tab:
            return float(tab[pair_id]), name
    return None, None


def build_cruise(cruise: str, provider_pair: str | None, nproc: int, only_pairs=None, batch_files: int = 1):
    t0 = time.time()
    m = C.load_manifest()
    if provider_pair:
        info = PROVIDER_SWATH[provider_pair]
        rows = m[m.pair_id == provider_pair]
        cruise_dir = C.RAW_SWATH_OAK / info["cruise_dir"]
        src_kind = info["kind"]
    else:
        C.assert_no_lockbox_cruise([cruise])
        rows = m[(m.lr_cruise == cruise) & m.pair_id.isin(C.PAIRS_IN_SCOPE)]
        cruise_dir = C.RAW_SWATH_OAK / cruise
        src_kind = "ncei_swath"
    if only_pairs:
        rows = rows[rows.pair_id.isin(only_pairs)]
    C.assert_no_lockbox(rows.pair_id.tolist())
    if rows.empty:
        log.error("no in-scope pairs for cruise %s", cruise); return []
    files = swath_files(cruise_dir)
    if not files:
        log.error("no swath files under %s", cruise_dir); return []
    fman = json.loads((cruise_dir / "fetch_manifest.json").read_text())
    if fman.get("n_files_failed", 0):
        raise RuntimeError(f"{cruise}: fetch incomplete ({fman['n_files_failed']} failed files) — not building products "
                           f"on a partial swath set; re-run the fetch first")
    sha = {(f.get("name") or f["filename"]): (f.get("url"), f["sha256"]) for f in fman["files"]}
    if len(sha) != len(files):
        raise RuntimeError(f"{cruise}: {len(files)} swath files on disk vs {len(sha)} in fetch_manifest.json")
    fmt = fmt_for(files[0].name)
    workdir = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r01" / cruise
    results = []
    for _, row in rows.iterrows():
        pid = row.pair_id
        pdir = C.pair_dir_oak(row)
        lr_path = pdir / "lr.tif"
        geom = lr_window(lr_path)
        z_ref = float(np.nanmedian(geom["lr"])) if np.isfinite(geom["lr"]).any() else 0.0
        log.info("[%s] %s: lr %s %s window=%s margin=%.0fm files=%d fmt=%d", cruise, pid, geom["crs"],
                 geom["shape"], [round(v, 4) for v in geom["window"]], geom["margin_m"], len(files), fmt)
        grid = {"crs": geom["crs"].to_string(), "transform": list(geom["transform"])[:6], "shape": tuple(geom["shape"])}
        groups = [files[i:i + batch_files] for i in range(0, len(files), max(1, batch_files))]
        tasks = [([str(f) for f in g] if batch_files > 1 else str(g[0]), fmt, geom["window"], str(workdir / pid), grid, z_ref) for g in groups]
        cmds, per_file = [], []
        acc, stats = empty_acc(*geom["shape"]), empty_stats()
        with ProcessPoolExecutor(max_workers=nproc) as ex:
            for r in ex.map(_run_mblist_one, tasks, chunksize=1):
                cmds.append(r["cmd"]); per_file.append({"file": r["file"], "n_rows": r["n"], "rc": r["rc"],
                                                        "stderr": r["stderr"]})
                merge_acc(acc, stats, r["acc"], r["stats"])
        prods, angle_method = finalize(acc, stats, geom, z_ref)
        out_dir = pdir / "ship_products_v1"
        out_dir.mkdir(exist_ok=True)
        for name in ("ship_sd", "ship_count", "ship_xtrack_frac", "ship_beam_angle", "ship_mean_regrid"):
            write_raster(out_dir / f"{name}.tif", prods[name], geom)
        # grid identity check by re-opening
        with rasterio.open(out_dir / "ship_sd.tif") as a, rasterio.open(lr_path) as b:
            matches = (a.crs == b.crs and a.transform == b.transform and a.shape == b.shape)
        slr, slr_src = median_s_lr(pid)
        qa = qa_vs_lr(prods["ship_mean_regrid"].astype("float64"), geom["lr"], slr)
        n_cells = int(np.isfinite(prods["ship_count"]).sum())
        pj = {
            "contract_version": 1,
            "pair_id": pid,
            "available": {"ship_sd": n_cells > 0, "ship_count": n_cells > 0,
                          "ship_xtrack_frac": n_cells > 0, "ship_beam_angle": n_cells > 0},
            "unavailable_reason": None if n_cells > 0 else "no soundings fell inside lr.tif grid",
            "source": {"kind": src_kind,
                       "files": [{"name": f.name, "url": sha.get(f.name, (None, None))[0],
                                  "sha256": sha.get(f.name, (None, None))[1]} for f in files],
                       "mb_format": fmt, "processing_mode": "raw"},
            "software": {"mbsystem": C.MBSYSTEM_VERSION,
                         "container": f"apptainer sandbox {C.SANDBOX} (docker.io/mbari/mbsystem {C.CONTAINER_DIGEST})",
                         "code_commit": C.git_commit()},
            "commands": cmds,
            "grid": {"crs": geom["crs"].to_string(), "transform": list(geom["transform"])[:6],
                     "shape": [int(geom["shape"][0]), int(geom["shape"][1])], "matches_lr_tif": bool(matches)},
            "qa_vs_lr_tif": qa,
            "created": datetime.now(timezone.utc).isoformat(),
        }
        extra = {
            "pair_id": pid, "cruise": cruise, "lr_tif": str(lr_path), "z_ref_m": z_ref,
            "window_4326_wesn": geom["window"], "margin_m": geom["margin_m"], "lr_median_depth_m": geom["depth_med"],
            "n_swath_files": len(files), "n_files_with_rows": int(sum(1 for p in per_file if p["n_rows"] > 0)),
            "n_soundings_in_window": stats["n_rows"], "n_pings_in_window": stats["n_pings"],
            "n_soundings_binned": int(acc["n"].sum()), "n_out_of_grid": stats["n_out_of_grid"],
            "n_flag_nonzero": stats["n_flag_nonzero"], "n_beamdep_valid": stats["n_beamdep_valid"],
            "n_halfwidth_zero": stats["n_hw_zero"],
            "halfwidth_mean_m": (stats["hw_sum"] / stats["hw_n"]) if stats["hw_n"] else None,
            "beam_angle_method": angle_method, "cells_with_soundings": n_cells,
            "cells_lr_valid": int(np.isfinite(geom["lr"]).sum()),
            "median_s_lr_m": slr, "median_s_lr_source": slr_src,
            "per_file": per_file, "wall_s": round(time.time() - t0, 1),
            "mblist_field_codes": {"O": MBLIST_O, "columns": COLS,
                                   "verified_against": "/usr/local/share/man/man1/mblist.1 in the sandbox (MB-System 5.8.2beta06)"},
        }
        for name, obj in (("products.json", pj), ("products_extra.json", extra)):
            p = out_dir / name
            if p.exists():
                p.chmod(0o644)
            p.write_text(json.dumps(obj, indent=1, default=str)); p.chmod(0o444)
        log.info("[%s] %s: cells=%d/%d qa=%s angle=%s", cruise, pid, n_cells, extra["cells_lr_valid"], qa, angle_method)
        results.append({"pair_id": pid, "cruise": cruise, "out_dir": str(out_dir), "qa": qa, "cells": n_cells,
                        "cells_lr_valid": extra["cells_lr_valid"], "n_soundings": stats["n_rows"],
                        "angle_method": angle_method, "matches_lr_tif": bool(matches)})
    shutil.rmtree(workdir, ignore_errors=True)
    C.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (C.REPORT_DIR / f"products_{cruise}.json").write_text(json.dumps(results, indent=1, default=str))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cruise", required=True)
    ap.add_argument("--provider", default=None, help="provider pair id (discol_so242_1 | tag_m127)")
    ap.add_argument("--nproc", type=int, default=8)
    ap.add_argument("--pairs", default=None)
    ap.add_argument("--batch-files", type=int, default=1, help="files per mblist datalist call (1 = one call per file)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    only = a.pairs.split(",") if a.pairs else None
    res = build_cruise(a.cruise, a.provider, a.nproc, only, a.batch_files)
    print(json.dumps(res, indent=1, default=str))
    return 0 if res else 1


if __name__ == "__main__":
    sys.exit(main())
