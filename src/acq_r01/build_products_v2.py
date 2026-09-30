"""ACQ-R02 §2 — INTERFACE_CONTRACT_v2 ship-side products for one LR cruise (v1 code kept).

Same soundings, same window, same `mblist` field codes and the same per-file binning as v1
(`build_products.py`; the v1 rasters count/sd/xtrack_frac/beam_angle/mean_regrid are recomputed by
the very same code path, so they must equal v1 exactly — verified per pair, NaN-aware).  New in v2:

  * every sounding that falls inside the lr.tif grid is also returned as (cell index, z) and the
    parent computes EXACT per-cell medians by sorting on cell index:
      ship_median_regrid = median(z)                     (count >= 1, QA only)
      ship_rsd           = 1.4826 * median(|z - median|)  (count >= 3)
  * v2 QA on ship_median_regrid vs lr.tif over common valid cells: n, median offset, RMS,
    robust sigma (1.4826 * MAD), both over median s_lr, and the +-1-cell / 0.25-step bilinear
    shift surface (81 shifts) with its argmin -> `qa_shift_surface.csv`.  Flags:
    insufficient_overlap (< 500 cells), vertical_offset (|median| > max(0.5 m, 0.05 * median s_lr)),
    registration_shift (argmin != (0, 0)).
  * v2 products.json (contract v2 §5); products written to <dir of lr.tif>/ship_products_v2/.

Usage (Slurm): python -m src.acq_r01.build_products_v2 --cruise NA090 [--nproc 8] [--batch-files 100]
               python -m src.acq_r01.build_products_v2 --cruise M127_EM122 --provider tag_m127
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import map_coordinates

from src.acq_r01 import common as C
from src.acq_r01 import build_products as V1

log = logging.getLogger("acq_r01.products_v2")
SHIFTS = np.arange(-1.0, 1.0001, 0.25)
MIN_COMMON = 500
RASTERS_V2 = ("ship_count", "ship_sd", "ship_rsd", "ship_xtrack_frac", "ship_beam_angle",
              "ship_mean_regrid", "ship_median_regrid")
CONTROL = ("ship_count", "ship_sd", "ship_xtrack_frac", "ship_beam_angle")


def _worker(args):
    """One mblist call per file (or datalist batch); v1 binning (shared code -> v1 equality) plus the
    (cell index, z) pairs of every sounding inside the grid for the exact per-cell medians."""
    srcs, fmt, window, workdir, grid, z_ref = args
    srcs_l = [Path(x) for x in ([srcs] if isinstance(srcs, str) else srcs)]
    workdir = Path(workdir); workdir.mkdir(parents=True, exist_ok=True)
    import gzip
    made, locals_ = [], []
    try:
        for src in srcs_l:
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
            cmd = ["mblist", f"-F{fmt}", "-I", locals_[0].name, "-MA", "-R", f"{w:.6f}/{e:.6f}/{s_:.6f}/{n:.6f}", "-O", V1.MBLIST_O]
            dl = None
        else:
            dl = workdir / f"datalist_{locals_[0].name}_{len(locals_)}.mb-1"
            dl.write_text("".join(f"{l.name} {fmt}\n" for l in locals_))
            cmd = ["mblist", "-F-1", "-I", dl.name, "-MA", "-R", f"{w:.6f}/{e:.6f}/{s_:.6f}/{n:.6f}", "-O", V1.MBLIST_O]
        r = C.mb(cmd, cwd=str(workdir))
        cmdline = f"(cd {workdir} && {C.mb_cmdline(cmd)})" + (f"  # datalist: {', '.join(l.name for l in locals_)}" if dl else "")
        out = r.stdout or ""
        base = {"file": srcs_l[0].name if len(srcs_l) == 1 else f"{srcs_l[0].name} .. {srcs_l[-1].name} ({len(srcs_l)} files)",
                "n": 0, "acc": None, "stats": None, "idx": None, "z": None, "cmd": cmdline, "rc": r.returncode,
                "stderr": (r.stderr or "")[-300:]}
        if not out.strip():
            return base
        df = pd.read_csv(io.StringIO(out), sep="\t", header=None, names=V1.COLS, dtype="float64", engine="c",
                         na_values=["NaN", "nan"], on_bad_lines="skip")
        del out
        a = df.to_numpy(); del df
        import pyproj
        tr = pyproj.Transformer.from_crs("EPSG:4326", grid["crs"], always_xy=True)
        acc, stats = V1.bin_array(a, grid["shape"], grid["transform"], z_ref, tr)
        ny, nx = grid["shape"]; ta, tc, te, tf = grid["transform"][0], grid["transform"][2], grid["transform"][4], grid["transform"][5]
        x, y = tr.transform(a[:, 0], a[:, 1])
        col = np.floor((x - tc) / ta).astype("int64"); row = np.floor((y - tf) / te).astype("int64")
        inside = (row >= 0) & (row < ny) & (col >= 0) & (col < nx) & np.isfinite(a[:, 2])
        base.update({"n": int(a.shape[0]), "acc": acc, "stats": stats,
                     "idx": (row[inside] * nx + col[inside]).astype("int32"), "z": a[inside, 2].astype("float64")})
        assert int(inside.sum()) == int(acc["n"].sum()), "row/bin count mismatch"
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


def cell_medians(idx: np.ndarray, z: np.ndarray, ncell: int):
    """Exact per-cell median and 1.4826*MAD by sorting on (cell, value)."""
    med = np.full(ncell, np.nan); rsd = np.full(ncell, np.nan); cnt = np.zeros(ncell, dtype="int64")
    if idx.size == 0:
        return med, rsd, cnt
    order = np.lexsort((z, idx)); idx_s, z_s = idx[order], z[order]
    starts = np.r_[0, np.flatnonzero(np.diff(idx_s)) + 1]; counts = np.diff(np.r_[starts, idx_s.size])
    cells = idx_s[starts]
    lo = starts + (counts - 1) // 2; hi = starts + counts // 2
    med_c = 0.5 * (z_s[lo] + z_s[hi])
    med[cells] = med_c; cnt[cells] = counts
    # MAD: sort |z - median(cell)| within cells
    gid = np.repeat(np.arange(cells.size), counts)
    d = np.abs(z_s - med_c[gid])
    order2 = np.lexsort((d, gid)); d_s = d[order2]
    mad_c = 0.5 * (d_s[lo] + d_s[hi])
    ok = counts >= 3
    rsd[cells[ok]] = 1.4826 * mad_c[ok]
    return med, rsd, cnt


def shift_surface(m: np.ndarray, lr: np.ndarray):
    """Robust sigma of (bilinearly shifted m - lr) on common cells for every (dx, dy) in SHIFTS^2."""
    ny, nx = m.shape
    rows, cols = np.mgrid[0:ny, 0:nx].astype("float64")
    m_f = np.where(np.isfinite(m), m, np.nan)
    surf = []
    for dy in SHIFTS:
        for dx in SHIFTS:
            if dx == 0 and dy == 0:
                sh = m_f
            else:
                sh = map_coordinates(m_f, [rows - dy, cols - dx], order=1, mode="constant", cval=np.nan, prefilter=False)
            common = np.isfinite(sh) & np.isfinite(lr)
            n = int(common.sum())
            if n:
                d = sh[common] - lr[common]
                rs = float(1.4826 * np.median(np.abs(d - np.median(d))))
            else:
                rs = np.nan
            surf.append((float(dx), float(dy), rs, n))
    return surf


def qa_v2(median_m: np.ndarray, lr: np.ndarray, median_s_lr, s_lr_source, out_csv: Path):
    common = np.isfinite(median_m) & np.isfinite(lr)
    n = int(common.sum())
    flags = []
    if n < MIN_COMMON:
        flags.append("insufficient_overlap")
    if n == 0:
        return {"n_common_cells": 0, "median_offset_m": None, "rms_m": None, "robust_sigma_m": None,
                "rms_over_median_s_lr": None, "robust_sigma_over_median_s_lr": None, "s_lr_source": s_lr_source,
                "shift_argmin_cells": None, "shift_surface_file": out_csv.name, "flags": flags + ["no_common_cells"]}
    d = (median_m[common] - lr[common]).astype("float64")
    med = float(np.median(d)); rms = float(np.sqrt(np.mean(d ** 2)))
    rsig = float(1.4826 * np.median(np.abs(d - med)))
    thr = max(0.5, 0.05 * median_s_lr) if median_s_lr else 0.5
    if abs(med) > thr:
        flags.append("vertical_offset")
    surf = shift_surface(median_m.astype("float64"), lr.astype("float64"))
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["dx_cells", "dy_cells", "robust_sigma_m", "n_common"]); w.writerows(surf)
    vals = np.array([s[2] for s in surf]); vals = np.where(np.isfinite(vals), vals, np.inf)
    i0 = [i for i, s in enumerate(surf) if s[0] == 0 and s[1] == 0][0]
    imin = int(np.argmin(vals))
    if vals[imin] >= vals[i0] - 1e-9:      # ties with (0,0) count as (0,0)
        imin = i0
    argmin = [surf[imin][0], surf[imin][1]]
    if argmin != [0.0, 0.0]:
        flags.append("registration_shift")
    return {"n_common_cells": n, "median_offset_m": round(med, 4), "rms_m": round(rms, 4), "robust_sigma_m": round(rsig, 4),
            "rms_over_median_s_lr": round(rms / median_s_lr, 4) if median_s_lr else None,
            "robust_sigma_over_median_s_lr": round(rsig / median_s_lr, 4) if median_s_lr else None,
            "s_lr_source": s_lr_source, "shift_argmin_cells": argmin, "shift_surface_file": out_csv.name, "flags": flags}


def control_vs_v1(out_dir: Path, prods: dict) -> dict:
    v1d = out_dir.parent / "ship_products_v1"
    res = {}
    for name in CONTROL:
        p = v1d / f"{name}.tif"
        if not p.exists():
            res[name] = "v1 missing"; continue
        with rasterio.open(p) as ds:
            a = ds.read(1)
        res[name] = "equal" if np.array_equal(a, prods[name], equal_nan=True) else f"DIFFERS (max|d|={np.nanmax(np.abs(a - prods[name])):.3g}, nan mismatch={int((np.isnan(a) != np.isnan(prods[name])).sum())})"
    return res


def build_cruise(cruise, provider_pair, nproc, only_pairs=None, batch_files=1, spec=None):
    """spec (ACQ-R02 new pairs): list of {pair_id, pair_dir, cruise_dir, src_kind, s_lr_override} —
    bypasses the manifest; otherwise pairs come from the manifest (ACQ-R01 scope)."""
    t0 = time.time()
    if spec:
        items = [(d["pair_id"], Path(d["pair_dir"])) for d in spec]
        cruise_dir = Path(spec[0]["cruise_dir"]); src_kind = spec[0].get("src_kind", "ncei_swath")
        C.assert_no_lockbox([p for p, _ in items])
    else:
        m = C.load_manifest()
        if provider_pair:
            info = V1.PROVIDER_SWATH[provider_pair]
            rows = m[m.pair_id == provider_pair]; cruise_dir = C.RAW_SWATH_OAK / info["cruise_dir"]; src_kind = info["kind"]
        else:
            C.assert_no_lockbox_cruise([cruise])
            rows = m[(m.lr_cruise == cruise) & m.pair_id.isin(C.PAIRS_IN_SCOPE)]; cruise_dir = C.RAW_SWATH_OAK / cruise; src_kind = "ncei_swath"
        if only_pairs:
            rows = rows[rows.pair_id.isin(only_pairs)]
        C.assert_no_lockbox(rows.pair_id.tolist())
        items = [(r.pair_id, C.pair_dir_oak(r)) for _, r in rows.iterrows()]
    files = V1.swath_files(cruise_dir)
    fman = json.loads((cruise_dir / "fetch_manifest.json").read_text())
    if fman.get("n_files_failed", 0):
        raise RuntimeError(f"{cruise}: fetch incomplete")
    sha = {(f.get("name") or f["filename"]): (f.get("url"), f["sha256"]) for f in fman["files"]}
    fmt = V1.fmt_for(files[0].name)
    workdir = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r02" / cruise
    results = []
    for pid, pdir in items:
        lr_path = pdir / "lr.tif"
        geom = V1.lr_window(lr_path)
        z_ref = float(np.nanmedian(geom["lr"])) if np.isfinite(geom["lr"]).any() else 0.0
        grid = {"crs": geom["crs"].to_string(), "transform": list(geom["transform"])[:6], "shape": tuple(geom["shape"])}
        groups = [files[i:i + batch_files] for i in range(0, len(files), max(1, batch_files))]
        tasks = [([str(f) for f in g] if batch_files > 1 else str(g[0]), fmt, geom["window"], str(workdir / pid), grid, z_ref) for g in groups]
        log.info("[%s] %s: %d files, %d tasks", cruise, pid, len(files), len(tasks))
        cmds, per_file, idxs, zs = [], [], [], []
        acc, stats = V1.empty_acc(*geom["shape"]), V1.empty_stats()
        with ProcessPoolExecutor(max_workers=nproc) as ex:
            for r in ex.map(_worker, tasks, chunksize=1):
                cmds.append(r["cmd"]); per_file.append({"file": r["file"], "n_rows": r["n"], "rc": r["rc"], "stderr": r["stderr"]})
                V1.merge_acc(acc, stats, r["acc"], r["stats"])
                if r["idx"] is not None and r["idx"].size:
                    idxs.append(r["idx"]); zs.append(r["z"])
        prods, angle_method = V1.finalize(acc, stats, geom, z_ref)
        ny, nx = geom["shape"]
        idx = np.concatenate(idxs) if idxs else np.zeros(0, "int32"); z = np.concatenate(zs) if zs else np.zeros(0)
        med, rsd, cnt = cell_medians(idx, z, ny * nx)
        assert np.array_equal(cnt.reshape(ny, nx), np.nan_to_num(prods["ship_count"]).astype("int64")), "median count != bin count"
        prods["ship_median_regrid"] = med.reshape(ny, nx).astype("float32")
        prods["ship_rsd"] = rsd.reshape(ny, nx).astype("float32")
        out_dir = pdir / "ship_products_v2"; out_dir.mkdir(exist_ok=True)
        for name in RASTERS_V2:
            V1.write_raster(out_dir / f"{name}.tif", prods[name], geom)
        with rasterio.open(out_dir / "ship_rsd.tif") as a, rasterio.open(lr_path) as b:
            matches = (a.crs == b.crs and a.transform == b.transform and a.shape == b.shape)
        slr, slr_src = V1.median_s_lr(pid)
        if slr is None:
            slr_src = "none (new pair: no CNN-repo tile table yet)"
        csv_path = out_dir / "qa_shift_surface.csv"
        if csv_path.exists():
            csv_path.chmod(0o644)
        qa = qa_v2(prods["ship_median_regrid"].astype("float64"), geom["lr"], slr, slr_src, csv_path)
        csv_path.chmod(0o444)
        ctrl = control_vs_v1(out_dir, prods)
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = prods["ship_rsd"] / prods["ship_sd"]
        rsd_over_sd = float(np.nanmedian(ratio)) if np.isfinite(ratio).any() else None
        n_cells = int(np.isfinite(prods["ship_count"]).sum())
        pj = {"contract_version": 2, "pair_id": pid, "lr_tif_path": str(lr_path),
              "available": {k: n_cells > 0 for k in ("ship_count", "ship_sd", "ship_rsd", "ship_xtrack_frac", "ship_beam_angle")},
              "unavailable_reason": None if n_cells > 0 else "no soundings fell inside lr.tif grid",
              "source": {"kind": src_kind, "files": [{"name": f.name, "url": sha.get(f.name, (None, None))[0], "sha256": sha.get(f.name, (None, None))[1]} for f in files],
                         "mb_format": fmt, "processing_mode": "raw"},
              "beam_angle_method": "launch_angle" if angle_method.startswith("mblist ',A'") else "geometric",
              "software": {"mbsystem": C.MBSYSTEM_VERSION, "container": f"apptainer sandbox {C.SANDBOX} (docker.io/mbari/mbsystem {C.CONTAINER_DIGEST})", "code_commit": C.git_commit()},
              "commands": cmds,
              "grid": {"crs": geom["crs"].to_string(), "transform": list(geom["transform"])[:6], "shape": [int(ny), int(nx)], "matches_lr_tif": bool(matches)},
              "qa_vs_lr_tif": qa, "created": datetime.now(timezone.utc).isoformat()}
        extra = {"pair_id": pid, "cruise": cruise, "n_soundings_binned": int(idx.size), "cells_with_soundings": n_cells,
                 "cells_lr_valid": int(np.isfinite(geom["lr"]).sum()), "median_rsd_over_sd": rsd_over_sd,
                 "control_vs_v1": ctrl, "beam_angle_method_detail": angle_method, "window_4326_wesn": geom["window"],
                 "margin_m": geom["margin_m"], "z_ref_m": z_ref, "median_s_lr_m": slr, "median_s_lr_source": slr_src,
                 "per_file": per_file, "wall_s": round(time.time() - t0, 1), "batch_files": batch_files}
        for name, obj in (("products.json", pj), ("products_extra.json", extra)):
            p = out_dir / name
            if p.exists():
                p.chmod(0o644)
            p.write_text(json.dumps(obj, indent=1, default=str)); p.chmod(0o444)
        log.info("[%s] %s: cells=%d qa=%s ctrl=%s rsd/sd=%s", cruise, pid, n_cells, qa, ctrl, rsd_over_sd)
        results.append({"pair_id": pid, "cruise": cruise, "qa": qa, "control_vs_v1": ctrl, "median_rsd_over_sd": rsd_over_sd,
                        "cells": n_cells, "beam_angle_method": pj["beam_angle_method"], "matches_lr_tif": bool(matches)})
    shutil.rmtree(workdir, ignore_errors=True)
    rd = C.REPO / "reports_post_grl_review" / "ACQ-R02"; rd.mkdir(parents=True, exist_ok=True)
    (rd / f"products_v2_{cruise}.json").write_text(json.dumps(results, indent=1, default=str))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cruise", required=True); ap.add_argument("--provider", default=None)
    ap.add_argument("--nproc", type=int, default=8); ap.add_argument("--pairs", default=None)
    ap.add_argument("--batch-files", type=int, default=1)
    ap.add_argument("--spec", default=None, help="JSON list of {pair_id, pair_dir, cruise_dir, src_kind} for new pairs")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    spec = json.loads(Path(a.spec).read_text()) if a.spec else None
    res = build_cruise(a.cruise, a.provider, a.nproc, a.pairs.split(",") if a.pairs else None, a.batch_files, spec)
    print(json.dumps(res, indent=1, default=str))
    return 0 if res else 1


if __name__ == "__main__":
    sys.exit(main())
