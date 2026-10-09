"""ACQ-R05 §2 — build one pair's context grid, products and agreement statistics.

Output: <pair harmonized dir>/context_v1/ on OAK (resolved from manifest v2.1):
  ctx_lr.tif (float32, NaN nodata, lr.tif's CRS/pixel size, origin on lr.tif's lattice, footprint + 5 km),
  ctx_lr_valid.tif (uint8: finite cells), ship_products_v2_1/ (+ products.json), context.json, SHA256SUMS.
Existing harmonized files are never modified.  The builder refuses lockbox / confirmatory pair ids and paths (§5).

NCEI-swath pairs (§2.1): the pair's own LR cruise files with soundings in the context region (sources.select_files, from
the ACQ-R04 coverage pass), stage-C geographic `mbgrid -A2 -G3 -F1 -C0 -M -E dx/dy/degrees` over the context region
snapped to the recovered stage-C node lattice (lattice.geo_region_for_context), then the development warp
(harmonize._open + rioxarray reproject, bilinear, nodata -9999) onto the context lattice (explicit transform/shape;
the development chain's GDAL-default output grid is exactly lr.tif's lattice, verified in lattice.py), float32/NaN.
Provider-grid pairs (§2.2): the same raw provider grid, through harmonize._open/_reproject exactly as harmonize_pair
(identity for DISCOL/CCZ/Cal DIG whose raw CRS is the target; GDAL-default warp for TAG), cropped (not clipped) to
the context lattice; NaN where the provider grid does not cover the buffer.
Usage (Slurm): python -m src.acq_r05.build --pair NA090__MGDS_31212 [--nproc 4] [--force]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling

from src.acq_r05 import common as R
from src.acq_r05 import lattice as L
from src.acq_r05 import sources as S
from src.acq_r01 import common as C
from src.acq_r04 import common as R4
from src.acq_r04 import blocks as B4
from src import harmonize as H

log = logging.getLogger("acq_r05.build")
PRODUCT_RUNS = R.REPORT_DIR / "products_runs"
BUILD_RECS = R.REPORT_DIR / "builds"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def write_tif(path: Path, arr, crs, transform, nodata, dtype):
    path = Path(path)
    if path.exists():
        path.chmod(0o644)
    prof = {"driver": "GTiff", "dtype": dtype, "count": 1, "height": arr.shape[0], "width": arr.shape[1], "crs": crs, "transform": transform,
            "nodata": nodata, "compress": "DEFLATE", "tiled": True, "BIGTIFF": "IF_SAFER"}
    if dtype == "float32":
        prof["predictor"] = 3
    with rasterio.open(path, "w", **prof) as d:
        d.write(arr.astype(dtype), 1)
    R.chmod_ro(path)
    return R.sha256_file(path)


def median_s_lr(pair_id: str):
    """§3: the pair's median tile s_lr from the CNN repo's R04 tile table (tiles_v1.parquet, available to this repo);
    otherwise the SD of lr.tif in 128-px windows (stated)."""
    try:
        t = pd.read_parquet(R.TILES_V1_R04, columns=["pair", "s_lr"])
        v = t[t.pair == pair_id].s_lr
        if len(v):
            return float(v.median()), f"median of {len(v)} tile s_lr values, CNN repo R04 tiles_v1.parquet"
    except Exception as e:
        log.warning("R04 tile table unreadable: %s", e)
    lr = L.read_lr(pair_id); sds = []
    for r in range(0, lr.shape[0], 128):
        for c in range(0, lr.shape[1], 128):
            w = lr[r:r + 128, c:c + 128]; w = w[np.isfinite(w)]
            if w.size >= 64:
                sds.append(float(np.std(w)))
    return (float(np.median(sds)) if sds else None), "SD of lr.tif in 128-px windows (median over windows); pair absent from the R04 tile table"


def diff_stats(a, b, s_lr, label):
    """Statistics of (a - b) on cells where both are finite; a = context, b = reference."""
    both = np.isfinite(a) & np.isfinite(b)
    n = int(both.sum()); out = {"what": label, "n_cells": n, "n_reference_valid": int(np.isfinite(b).sum()),
                                "n_reference_valid_but_context_nan": int((np.isfinite(b) & ~np.isfinite(a)).sum())}
    if n == 0:
        return {**out, "median_diff": None, "rms": None, "robust_sigma": None, "max_abs_diff": None, "identical": False}
    d = (a[both] - b[both]).astype("float64")
    med = float(np.median(d)); rms = float(np.sqrt(np.mean(d ** 2))); rsig = float(1.4826 * np.median(np.abs(d - med))); mx = float(np.max(np.abs(d)))
    out.update({"median_diff": med, "rms": rms, "robust_sigma": rsig, "max_abs_diff": mx, "n_nonzero_diff": int((d != 0).sum()),
                "identical": bool(mx <= 1e-3 and out["n_reference_valid_but_context_nan"] == 0)})
    if s_lr:
        out.update({"median_diff_over_s_lr": med / s_lr, "rms_over_s_lr": rms / s_lr, "robust_sigma_over_s_lr": rsig / s_lr,
                    "frac_abs_diff_gt_0p1_s_lr": float(np.mean(np.abs(d) > 0.1 * s_lr))})
    return out


def coverage_stats(ctx_arr, ctx, lr):
    r0, c0 = ctx["lr_offset_row"], ctx["lr_offset_col"]; h, w = lr.shape
    valid = np.isfinite(ctx_arr)
    inner = np.zeros_like(valid); inner[r0:r0 + h, c0:c0 + w] = True
    return {"n_cells": int(valid.size), "n_valid": int(valid.sum()), "valid_fraction": float(valid.mean()),
            "valid_fraction_outside_lr_window": float(valid[~inner].mean()) if (~inner).any() else None,
            "valid_fraction_in_lr_window": float(valid[inner].mean()), "lr_valid_fraction": float(np.isfinite(lr).mean())}


# --------------------------------------------------------------------------- #
# NCEI-swath pairs
# --------------------------------------------------------------------------- #
def grid_ncei(pid: str, ctx: dict, src: dict, region: dict, files: list[str], wd: Path, persist_dir: Path) -> tuple[np.ndarray, dict]:
    cruise = R.lr_cruise(pid); raw = C.RAW_SWATH_OAK / cruise
    fmt = S.fmt_for(files[0])
    t = time.time(); loc = B4.decompress(raw, files, wd, workers=4); dec_s = time.time() - t
    dl = wd / "datalist.mb-1"; dl.write_text("".join(f"{n} {fmt}\n" for n in loc))
    root = f"ctx_{pid}"
    args = ["mbgrid", "-I", dl.name, "-O", root, "-R", region["R"], "-E", region["E"], *R4.MBGRID_FLAGS]
    t = time.time(); res, attempts, cmdline = R4.mb_bounded(args, wd, timeout=3 * 3600, attempts=6); grid_s = time.time() - t
    grd = wd / f"{root}.grd"
    if not grd.exists():
        raise R4.MBFailure(f"{pid}: mbgrid produced no grid: {res['stderr'][-300:]}")
    with rasterio.open(grd) as ds:
        gt = ds.transform; gnx, gny = ds.width, ds.height; gcrs = ds.crs.to_string() if ds.crs else "EPSG:4326"; gnd = ds.nodata
    gdx, gdy = gt.a, -gt.e; gw = gt.c + gdx / 2; gn = gt.f - gdy / 2
    lat_check = {"nx": [gnx, region["nx"]], "ny": [gny, region["ny"]], "dx_rel": gdx / region["dx"] - 1, "dy_rel": gdy / region["dy"] - 1,
                 "w_err_cells": (gw - region["w"]) / region["dx"], "n_err_cells": (gn - region["n"]) / region["dy"], "crs": gcrs}
    ok = gnx == region["nx"] and gny == region["ny"] and abs(lat_check["dx_rel"]) < 1e-9 and abs(lat_check["dy_rel"]) < 1e-9 \
        and abs(lat_check["w_err_cells"]) < 1e-6 and abs(lat_check["n_err_cells"]) < 1e-6
    if not ok:
        raise RuntimeError(f"{pid}: mbgrid lattice differs from the planned context lattice: {lat_check}")
    # development warp: (1) grd -> GeoTIFF with the grd's CRS/nodata; (2) harmonize._open + reproject bilinear nodata -9999 onto the context lattice
    tmp = wd / f"{root}_geo.tif"
    with rasterio.open(grd) as ds:
        arr = ds.read(1).astype("float32")
    with rasterio.open(tmp, "w", driver="GTiff", height=gny, width=gnx, count=1, dtype="float32", crs=gcrs, transform=gt,
                       nodata=gnd if gnd is not None else R.DEV_FILL) as d:
        d.write(arr, 1)
    da = H._open(tmp)
    p = da.rio.reproject(ctx["crs"], transform=ctx["affine"], shape=(ctx["height"], ctx["width"]), resampling=H._RESAMPLING["bilinear"], nodata=R.DEV_FILL)
    a = p.values.astype("float32")
    a[a == np.float32(R.DEV_FILL)] = np.nan; a[np.abs(a) >= 99999.0] = np.nan
    assert a.shape == (ctx["height"], ctx["width"])
    # persist the geographic grids next to the union grids on OAK (small; Phase-4 reproducibility)
    persisted = {}
    persist_dir.mkdir(parents=True, exist_ok=True)
    for suf in ("", "_num", "_sd"):
        s_ = wd / f"{root}{suf}.grd"
        if s_.exists():
            dst = persist_dir / f"{pid}__context_v1{suf}.grd"
            if dst.exists():
                dst.chmod(0o644)
            shutil.copyfile(s_, dst); R.chmod_ro(dst); persisted[f"grd{suf}"] = {"path": str(dst), "sha256": R.sha256_file(dst)}
    rec = {"mb_format": fmt, "n_files": len(files), "decompress_s": round(dec_s, 1), "mbgrid_s": round(grid_s, 1), "mbgrid_attempts": attempts,
           "mbgrid_command": cmdline, "mbgrid_region": region, "grd_lattice_check": lat_check, "grd_nodata": gnd,
           "warp": {"method": "harmonize._open (rioxarray, masked) + DataArray.rio.reproject(dst_crs=lr.tif CRS, transform=context lattice, shape=context shape, resampling=bilinear, nodata=-9999); -9999 and |z|>=99999 -> NaN; float32",
                    "development_chain_reference": "ACQ-R04 §5.1 (harmonize._reproject bilinear nodata -9999, GDAL default output grid == lr.tif lattice, verified by lattice.verify_lattice)"},
           "persisted_grids_oak": persisted}
    return a, rec


def products_ncei(pid: str, ctx_tif: Path, files: list[str], out_dir: Path, nproc: int, batch_files: int) -> dict:
    """Contract v2.1 builder, unchanged, with ctx_lr.tif in the role of lr.tif (§2.3)."""
    from src.acq_r03 import build_products_v2_1 as B
    from src.acq_r03 import common as R3
    R3.REPORT_DIR = PRODUCT_RUNS; PRODUCT_RUNS.mkdir(parents=True, exist_ok=True)
    cruise = R.lr_cruise(pid); raw = C.RAW_SWATH_OAK / cruise
    stg = R.STAGE / pid
    if stg.exists():
        shutil.rmtree(stg)
    (stg / "raw").mkdir(parents=True)
    shutil.copyfile(ctx_tif, stg / "lr.tif")
    for f in files:
        (stg / "raw" / f).symlink_to(raw / f)
    fman = json.loads((raw / "fetch_manifest.json").read_text())
    sub = [x for x in fman["files"] if (x.get("filename") or x.get("name")) in set(files)]
    missing = set(files) - {(x.get("filename") or x.get("name")) for x in sub}
    if missing:
        raise RuntimeError(f"{pid}: {len(missing)} selected files absent from the cruise fetch manifest: {sorted(missing)[:5]}")
    (stg / "raw" / "fetch_manifest.json").write_text(json.dumps({"cruise": cruise, "n_files_failed": 0, "files": sub,
                                                                  "note": "ACQ-R05 per-pair staging: the pair's context-region subset of the cruise fetch manifest"}))
    t0 = time.time()
    res = B.build([(pid, stg)], cruise, stg / "raw", "ncei_swath", nproc, batch_files)
    wall = time.time() - t0
    src_dir = stg / B.OUT_NAME; dst = out_dir / B.OUT_NAME
    if dst.exists():
        for p in dst.iterdir():
            p.chmod(0o644)
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    copied = {}
    for p in sorted(src_dir.iterdir()):
        shutil.copyfile(p, dst / p.name); R.chmod_ro(dst / p.name); copied[p.name] = R.sha256_file(dst / p.name)
    pj = json.loads((dst / "products.json").read_text())
    shutil.rmtree(stg, ignore_errors=True)
    return {"wall_s": round(wall, 1), "nproc": nproc, "batch_files": batch_files, "builder": "src.acq_r03.build_products_v2_1.build (unchanged)",
            "staging_note": "products.json lr_tif_path points at the scratch staging copy of ctx_lr.tif (same bytes as context_v1/ctx_lr.tif)",
            "available": pj.get("available"), "flags": (pj.get("qa_vs_lr_tif") or {}).get("flags"), "qa_vs_ctx_lr": pj.get("qa_vs_lr_tif"),
            "matches_ctx_lr_grid": (pj.get("grid") or {}).get("matches_lr_tif"), "files": copied, "result": res[0] if res else None}


def compare_products(pid: str, out_dir: Path, ctx: dict, s_lr) -> dict:
    """§3 products: ship_count and ship_rsd of the context products vs the existing ship_products_v2_1 on lr.tif's cells."""
    old = R.pair_dir(pid) / "ship_products_v2_1"; new = out_dir / "ship_products_v2_1"
    r0, c0, h, w = ctx["lr_offset_row"], ctx["lr_offset_col"], ctx["lr_height"], ctx["lr_width"]
    out = {}
    for name in ("ship_count", "ship_rsd"):
        po, pn = old / f"{name}.tif", new / f"{name}.tif"
        if not po.exists() or not pn.exists():
            out[name] = {"what": name, "note": f"missing: existing={po.exists()} context={pn.exists()}"}; continue
        with rasterio.open(po) as a_, rasterio.open(pn) as b_:
            oa = a_.read(1).astype("float64"); nb = b_.read(1).astype("float64")
            assert (a_.height, a_.width) == (h, w), (a_.shape, (h, w))
        sub = nb[r0:r0 + h, c0:c0 + w]
        st = diff_stats(sub, oa, s_lr if name == "ship_rsd" else None, name)
        if name == "ship_count":
            both = np.isfinite(sub) & np.isfinite(oa)
            st["frac_cells_count_differs"] = float(np.mean(sub[both] != oa[both])) if both.any() else None
            st["sum_count_existing"] = float(np.nansum(oa)); st["sum_count_context_on_lr_cells"] = float(np.nansum(sub))
        out[name] = st
    return out


# --------------------------------------------------------------------------- #
# provider-grid pairs
# --------------------------------------------------------------------------- #
def provider_context(pid: str, ctx: dict) -> tuple[np.ndarray, dict]:
    r = R.row(pid); raw = R.OAK / str(r["raw_path_lr"])
    if not raw.exists():
        raise FileNotFoundError(raw)
    with rasterio.open(raw) as ds:
        raw_hdr = {"crs": ds.crs.to_string(), "transform": list(ds.transform)[:6], "width": ds.width, "height": ds.height, "nodata": ds.nodata, "dtype": ds.dtypes[0]}
    da = H._open(raw)
    p = H._reproject(da, ctx["crs"], H._RESAMPLING["bilinear"], R.DEV_FILL)      # identity when the raw CRS is the target (as harmonize_pair)
    pt = p.rio.transform(); pa = p.values
    if pa.ndim == 3:
        pa = pa[0]
    pa = pa.astype("float64"); pa[pa == R.DEV_FILL] = np.nan
    if raw_hdr["nodata"] is not None and np.isfinite(raw_hdr["nodata"]):
        pa[pa == raw_hdr["nodata"]] = np.nan
    kx = (ctx["affine"].c - pt.c) / pt.a; ky = (ctx["affine"].f - pt.f) / pt.e
    align = {"warped_transform": list(pt)[:6], "warped_shape": list(pa.shape), "pixel_size_rel_diff": [ctx["dx"] / pt.a - 1, ctx["dy"] / (-pt.e) - 1],
             "context_origin_offset_px": [kx, ky], "identity_reproject": str(da.rio.crs) == ctx["crs"]}
    if not (abs(align["pixel_size_rel_diff"][0]) < 1e-9 and abs(align["pixel_size_rel_diff"][1]) < 1e-9 and abs(kx - round(kx)) < 1e-6 and abs(ky - round(ky)) < 1e-6):
        raise RuntimeError(f"{pid}: the warped provider grid is not on lr.tif's lattice: {align}")
    kx, ky = int(round(kx)), int(round(ky))
    out = np.full((ctx["height"], ctx["width"]), np.nan, "float32")
    # window of the warped grid that lands in the context array
    r_lo, r_hi = max(0, -ky), min(ctx["height"], pa.shape[0] - ky); c_lo, c_hi = max(0, -kx), min(ctx["width"], pa.shape[1] - kx)
    if r_hi > r_lo and c_hi > c_lo:
        out[r_lo:r_hi, c_lo:c_hi] = pa[r_lo + ky:r_hi + ky, c_lo + kx:c_hi + kx].astype("float32")
    rec = {"raw": {"path": str(raw), "sha256": R.sha256_file(raw), **raw_hdr}, "alignment": align,
           "method": "harmonize._open (rioxarray masked) + harmonize._reproject(target_crs, bilinear, nodata -9999) exactly as harmonize_pair, then a CROP (no footprint clip) to the context lattice; NaN where the provider grid does not cover the buffer (§2.2: no gridding of raw swath)",
           "context_window_of_warped_grid": {"rows": [r_lo + ky, r_hi + ky], "cols": [c_lo + kx, c_hi + kx]}}
    return out, rec


def products_provider(pid: str, out_dir: Path) -> dict:
    """§2.3 provider-grid pairs: products.json with available false and the ruling; no rasters."""
    from src.acq_r03 import build_products_v2_1 as B
    reason = R.PROVIDER_PRODUCT_RULING.get(pid, R.CALDIG_REASON)
    d = out_dir / B.OUT_NAME; d.mkdir(parents=True, exist_ok=True)
    pj = {"contract_version": B.CONTRACT, "pair_id": pid, "lr_tif_path": str(out_dir / "ctx_lr.tif"), "context_v1": True,
          "available": {k: False for k in B.AVAIL}, "unavailable_reason": reason,
          "source": {"kind": "none", "files": [], "mb_format": None, "processing_mode": None}, "beam_angle_method": None,
          "software": {"mbsystem": C.MBSYSTEM_VERSION, "code_commit": R.git_commit()}, "commands": [], "grid": None,
          "frame_offset": {"applied": False, "dx_m": 0.0, "dy_m": 0.0, "basis": "none", "evidence": "no swath products on the context grid; not applicable"},
          "qa_vs_lr_tif": None, "created": R.utc_now()}
    R.write_json(d / "products.json", pj)
    return {"available": pj["available"], "reason": reason, "files": {"products.json": R.sha256_file(d / "products.json")}}


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def verify_sums(out_dir: Path) -> dict:
    sums = (out_dir / "SHA256SUMS").read_text().splitlines()
    bad = []
    for ln in sums:
        h, name = ln.split("  ", 1)
        if R.sha256_file(out_dir / name) != h:
            bad.append(name)
    return {"n_files": len(sums), "n_bad": len(bad), "bad": bad}


def write_sums(out_dir: Path) -> dict:
    files = sorted(p for p in out_dir.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
    sp = out_dir / "SHA256SUMS"
    if sp.exists():
        sp.chmod(0o644)
    sp.write_text("".join(f"{R.sha256_file(p)}  {p.relative_to(out_dir)}\n" for p in files)); R.chmod_ro(sp)
    return verify_sums(out_dir)


def build(pid: str, nproc: int = 4, batch_files: int | None = None, force: bool = False, skip_products: bool = False) -> dict:
    R.refuse_sealed(pid)
    if pid not in R.PAIRS_IN_SCOPE:
        raise SystemExit(f"{pid}: not a development pair of units-v1 (+EW0207); refusing (§0.3)")
    t0 = time.time()
    out_dir = R.context_dir(pid); BUILD_RECS.mkdir(parents=True, exist_ok=True)
    if (out_dir / "context.json").exists() and not force:
        v = verify_sums(out_dir)
        if v["n_bad"] == 0:
            log.info("[%s] context_v1 present and verified (%d files); skipping (use --force to rebuild)", pid, v["n_files"])
            return {"pair_id": pid, "status": "already_built", "verify": v}
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = L.context_lattice(pid); lr_hdr = L.lr_header(pid); lr = L.read_lr(pid)
    rec = {"pair_id": pid, "unit": R.UNIT_OF[pid], "kind": "provider_grid" if R.is_provider(pid) else "ncei_swath", "lr_cruise": R.lr_cruise(pid),
           "lr_doi": str(R.row(pid)["lr_doi"]), "started": R.utc_now(), "host": os.uname().nodename, "code_commit": R.git_commit(),
           "directive": "ACQ-R05 2026-10-09", "buffer_m": R.BUFFER_M, "context_dir": str(out_dir),
           "lr_tif": {"path": lr_hdr["path"], "sha256": R.sha256_file(lr_hdr["path"]), "crs": lr_hdr["crs"], "transform": list(lr_hdr["transform"])[:6],
                      "width": lr_hdr["width"], "height": lr_hdr["height"], "nodata": lr_hdr["nodata"], "dtype": lr_hdr["dtype"]},
           "lattice": {k: v for k, v in ctx.items() if k != "affine"},
           "lr_pixel_offset_in_context": {"col": ctx["lr_offset_col"], "row": ctx["lr_offset_row"]}}
    wd = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r05_build" / pid
    if wd.exists():
        shutil.rmtree(wd)
    wd.mkdir(parents=True)
    files = []
    if R.is_provider(pid):
        arr, prov = provider_context(pid, ctx); rec["provider"] = prov
        rec["source_files"] = [{"name": Path(prov["raw"]["path"]).name, "path": prov["raw"]["path"], "sha256": prov["raw"]["sha256"]}]
        rec["commands"] = []
    else:
        src = L.source_lattice(pid); ver = L.verify_lattice(pid, src)
        if not ver["match"]:
            raise RuntimeError(f"{pid}: stage-C lattice not recovered ({src.get('how')}); not building on a guessed lattice")
        region = L.geo_region_for_context(ctx, src)
        cruise = R.lr_cruise(pid); cov = S.load_coverage(cruise)
        files = S.select_files(cov, region)
        if not files:
            raise RuntimeError(f"{pid}: no cruise file has soundings in the context region")
        fman = json.loads((C.RAW_SWATH_OAK / cruise / "fetch_manifest.json").read_text())
        sha = {(f.get("filename") or f.get("name")): f for f in fman["files"]}
        rec["source_lattice"] = src; rec["source_lattice_verification"] = ver
        rec["source_files"] = [{"name": f, "path": str(C.RAW_SWATH_OAK / cruise / f), "sha256": sha.get(f, {}).get("sha256"), "url": sha.get(f, {}).get("url"),
                                "size": sha.get(f, {}).get("size"), "n_soundings": cov["files"][f]["n"]} for f in files]
        rec["source_selection"] = {"rule": "files with a sounding in a 0.1-degree cell touched by the mbgrid region (ACQ-R04 coverage pass)", "n_selected": len(files),
                                   "n_cruise_files_on_oak": cov["n_files"], "coverage_record": str(S.SRC_DIR / f"{cruise}_coverage.json"),
                                   "unreadable_files_in_cruise": cov.get("unreadable_files", [])}
        arr, grec = grid_ncei(pid, ctx, src, region, files, wd, R.CTX_GRD_OAK)
        rec["gridding"] = grec; rec["commands"] = [grec["mbgrid_command"]]
    # §3 agreement inside the footprint
    s_lr, s_src = median_s_lr(pid)
    r0, c0 = ctx["lr_offset_row"], ctx["lr_offset_col"]
    sub = arr[r0:r0 + lr.shape[0], c0:c0 + lr.shape[1]].astype("float64")
    agree = diff_stats(sub, lr, s_lr, "ctx_lr vs lr.tif on lr.tif valid cells")
    flags = []
    if agree["n_cells"] and ((agree["robust_sigma"] is not None and s_lr and agree["robust_sigma"] > R.GATE_SIGMA_FRAC * s_lr) or abs(agree["median_diff"] or 0) > R.GATE_MEDIAN_M):
        flags.append("ctx_disagrees")
    if agree["n_cells"] == 0:
        flags.append("no_common_cells")
    rec["agreement"] = {**agree, "median_s_lr_m": s_lr, "s_lr_source": s_src, "gate": {"robust_sigma_over_s_lr_max": R.GATE_SIGMA_FRAC, "abs_median_max_m": R.GATE_MEDIAN_M}, "flags": flags}
    rec["coverage"] = coverage_stats(arr, ctx, lr)
    # write rasters
    sha_ctx = write_tif(out_dir / "ctx_lr.tif", arr, ctx["crs"], ctx["affine"], float("nan"), "float32")
    sha_val = write_tif(out_dir / "ctx_lr_valid.tif", np.isfinite(arr).astype("uint8"), ctx["crs"], ctx["affine"], None, "uint8")
    rec["outputs"] = {"ctx_lr.tif": sha_ctx, "ctx_lr_valid.tif": sha_val}
    # products
    if R.is_provider(pid):
        rec["products"] = products_provider(pid, out_dir)
    elif skip_products:
        rec["products"] = {"note": "skipped (--skip-products)"}
    else:
        bf = batch_files if batch_files is not None else (100 if len(files) > 500 else 1)
        rec["products"] = products_ncei(pid, out_dir / "ctx_lr.tif", files, out_dir, nproc, bf)
        rec["products_vs_existing"] = compare_products(pid, out_dir, ctx, s_lr)
    if pid in R.CONSUMER_OVERRIDES:
        rec["consumer_side_override"] = R.CONSUMER_OVERRIDES[pid]
    rec["wall_s"] = round(time.time() - t0, 1); rec["finished"] = R.utc_now(); rec["status"] = "built"
    R.write_json(out_dir / "context.json", rec)
    rec["sha256sums"] = write_sums(out_dir)
    if rec["sha256sums"]["n_bad"]:
        raise RuntimeError(f"{pid}: SHA256SUMS verification failed: {rec['sha256sums']}")
    R.write_json(BUILD_RECS / f"{pid}.json", rec, mode=0o644)
    shutil.rmtree(wd, ignore_errors=True)
    log.info("[%s] built in %.0f s: agreement n=%d median=%s rms=%s rsig=%s flags=%s; coverage valid=%.3f", pid, rec["wall_s"], agree["n_cells"], agree["median_diff"], agree["rms"], agree["robust_sigma"], flags, rec["coverage"]["valid_fraction"])
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", required=True); ap.add_argument("--nproc", type=int, default=4); ap.add_argument("--batch-files", type=int, default=None)
    ap.add_argument("--force", action="store_true"); ap.add_argument("--skip-products", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    R.check_fixed_inputs()
    rec = build(a.pair, a.nproc, a.batch_files, a.force, a.skip_products)
    print(json.dumps({k: rec.get(k) for k in ("pair_id", "status", "wall_s", "agreement", "coverage", "sha256sums")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
