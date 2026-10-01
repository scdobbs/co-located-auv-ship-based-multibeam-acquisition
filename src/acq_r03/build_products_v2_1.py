"""ACQ-R03 §2.4 — INTERFACE_CONTRACT_v2.1 ship-side products for one LR cruise / pair.

Same soundings, window, `mblist` field codes, per-file binning, exact per-cell medians and shift surface as v2
(the v2 code is imported; the only change in the binning path is the frame-offset shim, which adds (dx_m, dy_m)
to every sounding's projected position before binning — with (0, 0) the arithmetic is exact, so rasters equal v2
bit-for-bit; verified per pair, NaN-aware).  New in v2.1 (contract §0, §4, §5):
  * `frame_offset` per pair from header_check.json (basis grid_header_registration only; never fitted);
  * the gate: registration_shift only if max(|dx|,|dy|) at the argmin >= 0.50 cell AND gain >= max(0.10 m, 0.05 σ0);
  * qa_vs_lr_tif carries sigma0_m, sigma_argmin_m, gain_m; contract_version "2.1"; directory ship_products_v2_1/.
ship_products_v1/ and ship_products_v2/ are not touched.

Usage (Slurm): python -m src.acq_r03.build_products_v2_1 --cruise NA090 [--nproc 8] [--batch-files 100]
               python -m src.acq_r03.build_products_v2_1 --cruise M127_EM122 --provider tag_m127
               python -m src.acq_r03.build_products_v2_1 --pair AT37-05__MGDS_24043           (ACQ-R02 new pair)
               python -m src.acq_r03.build_products_v2_1 --unavailable-unit CalDIG --reason "..."
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from src.acq_r01 import common as C
from src.acq_r01 import build_products as V1
from src.acq_r01 import build_products_v2 as V2
from src.acq_r03 import common as R

log = logging.getLogger("acq_r03.products_v2_1")
CONTRACT = "2.1"
OUT_NAME = "ship_products_v2_1"
RASTERS = V2.RASTERS_V2
AVAIL = ("ship_count", "ship_sd", "ship_rsd", "ship_xtrack_frac", "ship_beam_angle")


class _Shifted:
    """pyproj-Transformer shim: soundings are binned in lr.tif's effective frame (contract v2.1 §0.2)."""
    def __init__(self, tr, dx, dy):
        self.tr, self.dx, self.dy = tr, float(dx), float(dy)

    def transform(self, lon, lat):
        x, y = self.tr.transform(lon, lat)
        if self.dx == 0.0 and self.dy == 0.0:
            return x, y
        return x + self.dx, y + self.dy


def _worker(args):
    """v2 worker with the frame-offset shim (identical code path otherwise)."""
    srcs, fmt, window, workdir, grid, z_ref, dx, dy = args
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
            cmd = ["mblist", f"-F{fmt}", "-I", locals_[0].name, "-MA", "-R", f"{w:.6f}/{e:.6f}/{s_:.6f}/{n:.6f}", "-O", V1.MBLIST_O]; dl = None
        else:
            dl = workdir / f"datalist_{locals_[0].name}_{len(locals_)}.mb-1"
            dl.write_text("".join(f"{l.name} {fmt}\n" for l in locals_))
            cmd = ["mblist", "-F-1", "-I", dl.name, "-MA", "-R", f"{w:.6f}/{e:.6f}/{s_:.6f}/{n:.6f}", "-O", V1.MBLIST_O]
        r = None
        for attempt in range(6):                             # bounded (a container start can stall in fuse-overlayfs) and retried: under
            try:                                             # concurrent starts apptainer fails with "fuse-overlayfs failed to mount ... in 10s"
                r = C.mb(cmd, cwd=str(workdir), timeout=2400)   # (rc 255, no output); a repeat start succeeds (seen in June and today)
                if r.returncode == 0:
                    break
                time.sleep(15 * (attempt + 1))
            except subprocess.TimeoutExpired:
                r = None; time.sleep(15)
        cmdline = f"(cd {workdir} && {C.mb_cmdline(cmd)})" + (f"  # datalist: {', '.join(l.name for l in locals_)}" if dl else "")
        if r is None:
            return {"file": srcs_l[0].name if len(srcs_l) == 1 else f"{srcs_l[0].name} .. ({len(srcs_l)} files)", "n": 0, "acc": None, "stats": None, "idx": None, "z": None,
                    "cmd": cmdline, "rc": -9, "stderr": "mblist/container timeout (2 x 2400 s)"}
        out = r.stdout or ""
        base = {"file": srcs_l[0].name if len(srcs_l) == 1 else f"{srcs_l[0].name} .. {srcs_l[-1].name} ({len(srcs_l)} files)",
                "n": 0, "acc": None, "stats": None, "idx": None, "z": None, "cmd": cmdline, "rc": r.returncode, "stderr": (r.stderr or "")[-300:]}
        if not out.strip():
            return base
        df = pd.read_csv(io.StringIO(out), sep="\t", header=None, names=V1.COLS, dtype="float64", engine="c", na_values=["NaN", "nan"], on_bad_lines="skip")
        del out
        a = df.to_numpy(); del df
        import pyproj
        tr = _Shifted(pyproj.Transformer.from_crs("EPSG:4326", grid["crs"], always_xy=True), dx, dy)
        acc, stats = V1.bin_array(a, grid["shape"], grid["transform"], z_ref, tr)
        ny, nx = grid["shape"]; ta, tc, te, tf = grid["transform"][0], grid["transform"][2], grid["transform"][4], grid["transform"][5]
        x, y = tr.transform(a[:, 0], a[:, 1])
        col = np.floor((x - tc) / ta).astype("int64"); row = np.floor((y - tf) / te).astype("int64")
        inside = (row >= 0) & (row < ny) & (col >= 0) & (col < nx) & np.isfinite(a[:, 2])
        base.update({"n": int(a.shape[0]), "acc": acc, "stats": stats, "idx": (row[inside] * nx + col[inside]).astype("int32"), "z": a[inside, 2].astype("float64")})
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


def qa_v2_1(median_m, lr, median_s_lr, s_lr_source, out_csv: Path):
    """Contract v2.1 §4: same statistics and 81-shift surface as v2; the registration_shift gate is tightened."""
    common = np.isfinite(median_m) & np.isfinite(lr)
    n = int(common.sum()); flags = []
    if n < V2.MIN_COMMON:
        flags.append("insufficient_overlap")
    base = {"n_common_cells": n, "median_offset_m": None, "rms_m": None, "robust_sigma_m": None, "rms_over_median_s_lr": None,
            "robust_sigma_over_median_s_lr": None, "s_lr_source": s_lr_source, "shift_argmin_cells": None, "shift_surface_file": out_csv.name,
            "sigma0_m": None, "sigma_argmin_m": None, "gain_m": None, "registration_gate": {"min_shift_cells": 0.5, "min_gain_m": None}, "flags": flags}
    if n == 0:
        base["flags"] = flags + ["no_common_cells"]; return base
    d = (median_m[common] - lr[common]).astype("float64")
    med = float(np.median(d)); rms = float(np.sqrt(np.mean(d ** 2))); rsig = float(1.4826 * np.median(np.abs(d - med)))
    thr = max(0.5, 0.05 * median_s_lr) if median_s_lr else 0.5
    if abs(med) > thr:
        flags.append("vertical_offset")
    surf = V2.shift_surface(median_m.astype("float64"), lr.astype("float64"))
    with out_csv.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["dx_cells", "dy_cells", "robust_sigma_m", "n_common"]); w.writerows(surf)
    vals = np.array([s[2] for s in surf]); vals = np.where(np.isfinite(vals), vals, np.inf)
    i0 = [i for i, s in enumerate(surf) if s[0] == 0 and s[1] == 0][0]
    imin = int(np.argmin(vals))
    if vals[imin] >= vals[i0] - 1e-9:
        imin = i0
    argmin = [surf[imin][0], surf[imin][1]]
    s0 = float(vals[i0]); smin = float(vals[imin]); gain = s0 - smin
    min_gain = max(0.10, 0.05 * s0)
    if max(abs(argmin[0]), abs(argmin[1])) >= 0.5 and gain >= min_gain:
        flags.append("registration_shift")
    base.update({"median_offset_m": round(med, 4), "rms_m": round(rms, 4), "robust_sigma_m": round(rsig, 4),
                 "rms_over_median_s_lr": round(rms / median_s_lr, 4) if median_s_lr else None,
                 "robust_sigma_over_median_s_lr": round(rsig / median_s_lr, 4) if median_s_lr else None,
                 "shift_argmin_cells": argmin, "sigma0_m": round(s0, 4), "sigma_argmin_m": round(smin, 4), "gain_m": round(gain, 4),
                 "registration_gate": {"min_shift_cells": 0.5, "min_gain_m": round(min_gain, 4)}, "flags": flags})
    return base


def frame_offset_for(pid: str) -> dict:
    p = R.REPORT_DIR / "header_check.json"
    rec = json.loads(p.read_text())["pairs"].get(pid) if p.exists() else None
    if rec is None:
        return {"applied": False, "dx_m": 0.0, "dy_m": 0.0, "basis": "none", "evidence": "pair not in the ACQ-R03 §2.2 header check (v2 argmin < 0.5 cell); no frame offset"}
    fo = dict(rec["frame_offset"])
    if fo.get("applied") and fo.get("basis") != "grid_header_registration":
        raise RuntimeError(f"{pid}: frame offset may be applied only with basis grid_header_registration")
    return fo


def control_vs_v2(out_dir: Path, prods: dict, applied: bool) -> dict:
    v2d = out_dir.parent / "ship_products_v2"; res = {}
    for name in RASTERS:
        p = v2d / f"{name}.tif"
        if not p.exists():
            res[name] = "v2 missing"; continue
        with rasterio.open(p) as ds:
            a = ds.read(1)
        eq = np.array_equal(a, prods[name], equal_nan=True)
        res[name] = "equal" if eq else (f"differs (frame offset applied)" if applied else f"DIFFERS (max|d|={np.nanmax(np.abs(a - prods[name])):.3g}, nan mismatch={int((np.isnan(a) != np.isnan(prods[name])).sum())})")
    return res


def build(items, cruise, cruise_dir: Path, src_kind: str, nproc: int, batch_files: int):
    t0 = time.time()
    files = V1.swath_files(cruise_dir)
    fman = json.loads((cruise_dir / "fetch_manifest.json").read_text())
    if fman.get("n_files_failed", 0):
        raise RuntimeError(f"{cruise}: fetch incomplete")
    sha = {(f.get("name") or f["filename"]): (f.get("url"), f["sha256"]) for f in fman["files"]}
    fmt = V1.fmt_for(files[0].name)
    workdir = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r03" / cruise
    results = []
    for pid, pdir in items:
        lr_path = pdir / "lr.tif"
        geom = V1.lr_window(lr_path)
        z_ref = float(np.nanmedian(geom["lr"])) if np.isfinite(geom["lr"]).any() else 0.0
        grid = {"crs": geom["crs"].to_string(), "transform": list(geom["transform"])[:6], "shape": tuple(geom["shape"])}
        fo = frame_offset_for(pid)
        dx, dy = (float(fo["dx_m"]), float(fo["dy_m"])) if fo.get("applied") else (0.0, 0.0)
        groups = [files[i:i + batch_files] for i in range(0, len(files), max(1, batch_files))]
        tasks = [([str(f) for f in g] if batch_files > 1 else str(g[0]), fmt, geom["window"], str(workdir / pid), grid, z_ref, dx, dy) for g in groups]
        log.info("[%s] %s: %d files, %d tasks, frame offset applied=%s (%.2f, %.2f) m", cruise, pid, len(files), len(tasks), fo.get("applied"), dx, dy)
        cmds, per_file, idxs, zs = [], [], [], []
        acc, stats = V1.empty_acc(*geom["shape"]), V1.empty_stats()
        with ProcessPoolExecutor(max_workers=nproc) as ex:
            for r in ex.map(_worker, tasks, chunksize=1):
                cmds.append(r["cmd"]); per_file.append({"file": r["file"], "n_rows": r["n"], "rc": r["rc"], "stderr": r["stderr"]})
                V1.merge_acc(acc, stats, r["acc"], r["stats"])
                if r["idx"] is not None and r["idx"].size:
                    idxs.append(r["idx"]); zs.append(r["z"])
        bad = [p for p in per_file if p["rc"] != 0]
        if bad:
            raise RuntimeError(f"{pid}: {len(bad)} mblist call(s) failed or timed out ({bad[:3]}); not writing products on a partial swath set")
        prods, angle_method = V1.finalize(acc, stats, geom, z_ref)
        ny, nx = geom["shape"]
        idx = np.concatenate(idxs) if idxs else np.zeros(0, "int32"); z = np.concatenate(zs) if zs else np.zeros(0)
        med, rsd, cnt = V2.cell_medians(idx, z, ny * nx)
        assert np.array_equal(cnt.reshape(ny, nx), np.nan_to_num(prods["ship_count"]).astype("int64")), "median count != bin count"
        prods["ship_median_regrid"] = med.reshape(ny, nx).astype("float32"); prods["ship_rsd"] = rsd.reshape(ny, nx).astype("float32")
        out_dir = pdir / OUT_NAME; out_dir.mkdir(exist_ok=True)
        for name in RASTERS:
            V1.write_raster(out_dir / f"{name}.tif", prods[name], geom)
        with rasterio.open(out_dir / "ship_rsd.tif") as a_, rasterio.open(lr_path) as b_:
            matches = (a_.crs == b_.crs and a_.transform == b_.transform and a_.shape == b_.shape)
        slr, slr_src = V1.median_s_lr(pid)
        if slr is None:
            slr_src = "none (new pair: no CNN-repo tile table yet)"
        csv_path = out_dir / "qa_shift_surface.csv"
        if csv_path.exists():
            csv_path.chmod(0o644)
        qa = qa_v2_1(prods["ship_median_regrid"].astype("float64"), geom["lr"], slr, slr_src, csv_path); csv_path.chmod(0o444)
        ctrl = control_vs_v2(out_dir, prods, bool(fo.get("applied")))
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = prods["ship_rsd"] / prods["ship_sd"]
        rsd_over_sd = float(np.nanmedian(ratio)) if np.isfinite(ratio).any() else None
        n_cells = int(np.isfinite(prods["ship_count"]).sum())
        pj = {"contract_version": CONTRACT, "pair_id": pid, "lr_tif_path": str(lr_path),
              "available": {k: n_cells > 0 for k in AVAIL}, "unavailable_reason": None if n_cells > 0 else "no soundings fell inside lr.tif grid",
              "source": {"kind": src_kind, "files": [{"name": f.name, "url": sha.get(f.name, (None, None))[0], "sha256": sha.get(f.name, (None, None))[1]} for f in files],
                         "mb_format": fmt, "processing_mode": "raw"},
              "beam_angle_method": "launch_angle" if angle_method.startswith("mblist ',A'") else "geometric",
              "software": {"mbsystem": C.MBSYSTEM_VERSION, "container": f"apptainer sandbox {C.SANDBOX} (docker.io/mbari/mbsystem {C.CONTAINER_DIGEST})", "code_commit": C.git_commit()},
              "commands": cmds, "grid": {"crs": geom["crs"].to_string(), "transform": list(geom["transform"])[:6], "shape": [int(ny), int(nx)], "matches_lr_tif": bool(matches)},
              "frame_offset": fo, "qa_vs_lr_tif": qa, "created": datetime.now(timezone.utc).isoformat()}
        extra = {"pair_id": pid, "cruise": cruise, "n_soundings_binned": int(idx.size), "cells_with_soundings": n_cells, "cells_lr_valid": int(np.isfinite(geom["lr"]).sum()),
                 "median_rsd_over_sd": rsd_over_sd, "control_vs_v2": ctrl, "beam_angle_method_detail": angle_method, "window_4326_wesn": geom["window"],
                 "margin_m": geom["margin_m"], "z_ref_m": z_ref, "median_s_lr_m": slr, "median_s_lr_source": slr_src, "per_file": per_file,
                 "wall_s": round(time.time() - t0, 1), "batch_files": batch_files, "nproc": nproc}
        for name, obj in (("products.json", pj), ("products_extra.json", extra)):
            p = out_dir / name
            if p.exists():
                p.chmod(0o644)
            p.write_text(json.dumps(obj, indent=1, default=str)); p.chmod(0o444)
        log.info("[%s] %s: cells=%d flags=%s argmin=%s gain=%s ctrl=%s", cruise, pid, n_cells, qa["flags"], qa["shift_argmin_cells"], qa["gain_m"], ctrl)
        results.append({"pair_id": pid, "cruise": cruise, "qa": qa, "frame_offset": fo, "control_vs_v2": ctrl, "median_rsd_over_sd": rsd_over_sd,
                        "cells": n_cells, "beam_angle_method": pj["beam_angle_method"], "matches_lr_tif": bool(matches)})
    shutil.rmtree(workdir, ignore_errors=True)
    R.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    tag = cruise if len(items) != 1 else f"{cruise}__{items[0][0]}"
    (R.REPORT_DIR / f"products_v2_1_{tag}.json").write_text(json.dumps(results, indent=1, default=str))
    return results


def write_unavailable(unit: str, reason: str):
    """Contract v2.1 §5: pairs without swath (Cal DIG) — every available flag false, no rasters."""
    m = C.load_manifest(); pids = C.ALL15[unit] if unit in C.ALL15 else C.EW0207[unit]
    rows = m[m.pair_id.isin(pids)]; C.assert_no_lockbox(rows.pair_id); written = []
    for _, row in rows.iterrows():
        out_dir = C.pair_dir_oak(row) / OUT_NAME; out_dir.mkdir(exist_ok=True)
        if any(out_dir.glob("*.tif")):
            raise RuntimeError(f"{row.pair_id}: rasters present in {out_dir}; refusing to mark unavailable")
        pj = {"contract_version": CONTRACT, "pair_id": row.pair_id, "lr_tif_path": str(C.pair_dir_oak(row) / "lr.tif"),
              "available": {k: False for k in AVAIL}, "unavailable_reason": reason,
              "source": {"kind": "none", "files": [], "mb_format": None, "processing_mode": None}, "beam_angle_method": None,
              "software": {"mbsystem": C.MBSYSTEM_VERSION, "container": f"apptainer sandbox {C.SANDBOX}", "code_commit": C.git_commit()},
              "commands": [], "grid": None,
              "frame_offset": {"applied": False, "dx_m": 0.0, "dy_m": 0.0, "basis": "none", "evidence": "no swath products; not applicable"},
              "qa_vs_lr_tif": None, "created": datetime.now(timezone.utc).isoformat()}
        p = out_dir / "products.json"
        if p.exists():
            p.chmod(0o644)
        p.write_text(json.dumps(pj, indent=1)); p.chmod(0o444); written.append(str(p))
    return written


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cruise", default=None); ap.add_argument("--provider", default=None); ap.add_argument("--pair", default=None)
    ap.add_argument("--nproc", type=int, default=8); ap.add_argument("--batch-files", type=int, default=1)
    ap.add_argument("--unavailable-unit", default=None); ap.add_argument("--reason", default=None)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.unavailable_unit:
        w = write_unavailable(a.unavailable_unit, a.reason or "ship LR is a processed mosaic without retrievable per-beam soundings (NOS BAG); no swath products")
        print(json.dumps(w, indent=1)); return 0
    if a.pair:
        C.assert_no_lockbox([a.pair])
        rec = json.loads((R.R02 / "harmonize" / f"{a.pair}.json").read_text())
        if str(rec.get("designation", "")).startswith("confirmatory"):
            raise SystemExit(f"{a.pair} is confirmatory: products only at Phase 4")
        cruise = a.cruise or rec["lr_cruise"]; C.assert_no_lockbox_cruise([cruise])
        items = [(a.pair, Path(rec["out_dir"]))]; cruise_dir = C.RAW_SWATH_OAK / cruise
        src_kind = "provider_swath" if cruise.startswith("PANGAEA_") else "ncei_swath"
    else:
        m = C.load_manifest()
        if a.provider:
            info = V1.PROVIDER_SWATH[a.provider]; rows = m[m.pair_id == a.provider]; cruise_dir = C.RAW_SWATH_OAK / info["cruise_dir"]; src_kind = info["kind"]; cruise = a.cruise
        else:
            cruise = a.cruise; C.assert_no_lockbox_cruise([cruise])
            rows = m[(m.lr_cruise == cruise) & m.pair_id.isin(C.PAIRS_IN_SCOPE)]; cruise_dir = C.RAW_SWATH_OAK / cruise; src_kind = "ncei_swath"
        C.assert_no_lockbox(rows.pair_id.tolist())
        items = [(r.pair_id, C.pair_dir_oak(r)) for _, r in rows.iterrows()]
    res = build(items, cruise, cruise_dir, src_kind, a.nproc, a.batch_files)
    print(json.dumps(res, indent=1, default=str)); return 0 if res else 1


if __name__ == "__main__":
    sys.exit(main())
