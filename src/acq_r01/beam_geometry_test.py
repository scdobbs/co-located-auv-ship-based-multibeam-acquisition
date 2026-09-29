"""ACQ-R01 §2.4 — beam-geometry test: does the resolved-band tilt follow cross-track position?

Inputs (read-only):
  * R03 per-tile table  /scratch/users/scdobbs/grl_review/R03/s3/s3_pertile.parquet
    (T_res, T_res_lp, slope = R02 bicubic tile slope, s_lr, key = <pid>_r<r0>_c<c0>.npz)
  * tile footprints = the R02/R03 clean-patch windows: 256 x 256 HR px at (r0, c0) on the
    pair's harmonized hr.tif grid (extract_clean_patches.py, hr_px=256); hr.tif and lr.tif
    share the CRS (stage F), so a tile's bounds map directly onto lr.tif cells.
  * ship_products_v1/ship_xtrack_frac.tif and ship_beam_angle.tif (built by build_products.py)

Method (native NCEI units only: NA090, NA080, TN399, RR1506, AT37-13, FK181031, TN299, EW0207):
  1. plane^2 = T_res^2 - T_res_lp^2 per tile (tiles with plane^2 <= 0 dropped and counted).
  2. per tile: mean ship_xtrack_frac and mean ship_beam_angle over the LR cells the tile covers.
  3. within-unit Spearman rho of log plane with mean xtrack_frac; partial rho given log slope and
     log s_lr (residualise both on [log slope, log s_lr] by within-unit OLS, Spearman of residuals).
     The same for log T_res_lp.
  4. per unit + median over units, bootstrap over units (2,000 resamples, seed 20260929) 95% CI.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy.stats import spearmanr

from src.acq_r01 import common as C

S3 = "/scratch/users/scdobbs/grl_review/R03/s3/s3_pertile.parquet"
UNITS = {**C.NATIVE7, **C.EW0207}
WIN = 256
SEED = 20260929
NBOOT = 2000
EPS = 1e-6


def tile_rc(key: str):
    m = re.search(r"_r(\d{6})_c(\d{6})\.npz$", key)
    return int(m.group(1)), int(m.group(2))


def tile_lr_means(pid: str, keys: list[str]):
    m = C.load_manifest(); row = m[m.pair_id == pid].iloc[0]
    pdir = C.pair_dir_oak(row)
    with rasterio.open(pdir / "hr.tif") as h:
        htr = h.transform
    sp = pdir / "ship_products_v1"
    with rasterio.open(sp / "ship_xtrack_frac.tif") as a, rasterio.open(sp / "ship_beam_angle.tif") as b:
        xf = a.read(1); ba = b.read(1); ltr = a.transform; ny, nx = a.shape
    out = {}
    for k in keys:
        r0, c0 = tile_rc(k)
        x0, y0 = htr * (c0, r0); x1, y1 = htr * (c0 + WIN, r0 + WIN)
        xmin, xmax = min(x0, x1), max(x0, x1); ymin, ymax = min(y0, y1), max(y0, y1)
        cmin = int(np.floor((xmin - ltr.c) / ltr.a)); cmax = int(np.ceil((xmax - ltr.c) / ltr.a))
        rmin = int(np.floor((ymax - ltr.f) / ltr.e)); rmax = int(np.ceil((ymin - ltr.f) / ltr.e))
        rmin, rmax = max(rmin, 0), min(rmax, ny); cmin, cmax = max(cmin, 0), min(cmax, nx)
        if rmax <= rmin or cmax <= cmin:
            out[k] = (np.nan, np.nan, 0); continue
        wx = xf[rmin:rmax, cmin:cmax]; wb = ba[rmin:rmax, cmin:cmax]
        n = int(np.isfinite(wx).sum())
        out[k] = (float(np.nanmean(wx)) if n else np.nan, float(np.nanmean(wb)) if n else np.nan, n)
    return out


def partial_spearman(y, x, ctrl):
    """Spearman of residuals after OLS of y and x on ctrl (with intercept)."""
    A = np.c_[ctrl, np.ones(len(y))]
    ry = y - A @ np.linalg.lstsq(A, y, rcond=None)[0]
    rx = x - A @ np.linalg.lstsq(A, x, rcond=None)[0]
    return float(spearmanr(ry, rx)[0])


def main():
    df = pd.read_parquet(S3)
    df = df[~df.pid.isin(C.LOCKBOX)]
    rows = []
    for unit, pids in UNITS.items():
        for pid in pids:
            d = df[df.pid == pid].copy()
            means = tile_lr_means(pid, d.key.tolist())
            d["xtrack_frac"] = [means[k][0] for k in d.key]
            d["beam_angle"] = [means[k][1] for k in d.key]
            d["n_lr_cells"] = [means[k][2] for k in d.key]
            rows.append(d)
    t = pd.concat(rows, ignore_index=True)
    t["plane2"] = t.T_res ** 2 - t.T_res_lp ** 2
    t["plane"] = np.sqrt(np.clip(t.plane2, 0, None))
    per_unit, drop = [], {}
    for unit in UNITS:
        d = t[t.unit == unit]
        n0 = len(d)
        d = d[(d.plane2 > 0) & np.isfinite(d.xtrack_frac) & np.isfinite(d.beam_angle) & (d.slope > 0) & (d.s_lr > 0) & (d.T_res_lp > 0)]
        drop[unit] = {"n_tiles": n0, "n_used": len(d), "n_plane2_le_0": int((t[t.unit == unit].plane2 <= 0).sum()),
                      "n_no_ship_cells": int((~np.isfinite(t[t.unit == unit].xtrack_frac)).sum())}
        if len(d) < 8:
            continue
        lp, llp = np.log(d.plane + EPS), np.log(d.T_res_lp + EPS)
        ctrl = np.c_[np.log(d.slope + EPS), np.log(d.s_lr + EPS)]
        r = {"unit": unit, "n": len(d),
             "rho_plane_xtrack": float(spearmanr(lp, d.xtrack_frac)[0]),
             "rho_plane_xtrack_partial": partial_spearman(lp.values, d.xtrack_frac.values, ctrl),
             "rho_plane_beamangle": float(spearmanr(lp, d.beam_angle)[0]),
             "rho_plane_beamangle_partial": partial_spearman(lp.values, d.beam_angle.values, ctrl),
             "rho_treslp_xtrack": float(spearmanr(llp, d.xtrack_frac)[0]),
             "rho_treslp_xtrack_partial": partial_spearman(llp.values, d.xtrack_frac.values, ctrl),
             "rho_treslp_beamangle": float(spearmanr(llp, d.beam_angle)[0]),
             "rho_treslp_beamangle_partial": partial_spearman(llp.values, d.beam_angle.values, ctrl),
             "median_xtrack_frac": float(d.xtrack_frac.median()), "median_beam_angle": float(d.beam_angle.median()),
             "median_plane_m": float(d.plane.median()), "median_T_res_lp_m": float(d.T_res_lp.median())}
        per_unit.append(r)
    pu = pd.DataFrame(per_unit)
    rng = np.random.default_rng(SEED)
    summary = {}
    dev = pu[pu.unit != "EW0207"]           # EW0207 reported separately, never pooled (R04 §0.1)
    for col in [c for c in pu.columns if c.startswith("rho_")]:
        v = dev[col].values
        boots = np.array([np.median(rng.choice(v, size=len(v), replace=True)) for _ in range(NBOOT)])
        summary[col] = {"median_over_units": float(np.median(v)), "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                        "n_units": int(len(v)), "ew0207": float(pu.loc[pu.unit == "EW0207", col].iloc[0]) if (pu.unit == "EW0207").any() else None}
    out = {"per_unit": per_unit, "summary_native7": summary, "dropped": drop, "n_boot": NBOOT, "seed": SEED,
           "inputs": {"s3_pertile": S3, "tile_window_hr_px": WIN}}
    C.write_json(C.REPORT_DIR / "beam_geometry_test.json", out)
    t.to_parquet(C.REPORT_DIR / "beam_geometry_pertile.parquet")
    md = ["| unit | n | ρ(log plane, xtrack) | partial | ρ(log plane, beam angle) | partial | ρ(log T_res_lp, xtrack) | partial | ρ(log T_res_lp, beam angle) | partial |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in per_unit:
        md.append(f"| {r['unit']} | {r['n']} | {r['rho_plane_xtrack']:+.2f} | {r['rho_plane_xtrack_partial']:+.2f} | {r['rho_plane_beamangle']:+.2f} | {r['rho_plane_beamangle_partial']:+.2f} | {r['rho_treslp_xtrack']:+.2f} | {r['rho_treslp_xtrack_partial']:+.2f} | {r['rho_treslp_beamangle']:+.2f} | {r['rho_treslp_beamangle_partial']:+.2f} |")
    md.append("")
    md.append("| statistic (native 7, median over units) | median | 95% CI (bootstrap over units, 2000) | EW0207 (separate) |")
    md.append("|---|---|---|---|")
    for k, v in summary.items():
        md.append(f"| {k} | {v['median_over_units']:+.3f} | [{v['ci95'][0]:+.3f}, {v['ci95'][1]:+.3f}] | {v['ew0207']:+.3f} |" if v['ew0207'] is not None else f"| {k} | {v['median_over_units']:+.3f} | [{v['ci95'][0]:+.3f}, {v['ci95'][1]:+.3f}] | n/a |")
    (C.REPORT_DIR / "beam_geometry_test.md").write_text("\n".join(md))
    print("\n".join(md)); print(json.dumps(drop, indent=1))


if __name__ == "__main__":
    main()
