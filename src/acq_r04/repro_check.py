"""ACQ-R04 §4.2 — reproduction spot-check of 12 kept blocks (fresh process, from the raw files on scratch).

Choice: numpy.random.default_rng(20261004); the instrument families present in the corpus manifest, in an rng
permutation, are cycled; each turn draws one not-yet-chosen block of that family uniformly -> 12 blocks covering
min(12, #families) families (>= 4 required).
Per block: decompress its files anew, re-run the coverage pass over them, recompute the block's median depth and
cell, re-run the same mbgrid command, rebuild the contract-v2.1 products (unchanged builder) in a scratch directory,
and compare with the persisted version on OAK (grid.tif and every product raster): max |diff| and NaN-mask
mismatches.  QC figure per block (hillshade of grid.tif, ship_count, ship_rsd) to the report directory.
Usage (Slurm): python -m src.acq_r04.repro_check --manifest pretrain_manifest_v1.parquet [--root OAK|STAGE]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r04 import blocks as B


def choose(man: pd.DataFrame, n=12):
    rng = np.random.default_rng(R.SEED_SPOT)
    fams = sorted(man.instrument_family.unique())
    fams = [fams[i] for i in rng.permutation(len(fams))]
    pools = {f: man[man.instrument_family == f].sort_values(["cruise", "block"]).reset_index(drop=True) for f in fams}
    taken = {f: set() for f in fams}; out = []
    while len(out) < min(n, len(man)):
        progressed = False
        for f in fams:
            if len(out) >= n:
                break
            left = [i for i in range(len(pools[f])) if i not in taken[f]]
            if not left:
                continue
            i = left[int(rng.integers(len(left)))]; taken[f].add(i); out.append(pools[f].iloc[i]); progressed = True
        if not progressed:
            break
    return pd.DataFrame(out).reset_index(drop=True)


def hillshade(z, dx, az=315, alt=45):
    gy, gx = np.gradient(np.nan_to_num(z, nan=np.nanmedian(z)), dx)
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
    a, b = math.radians(az), math.radians(alt)
    hs = np.sin(b) * np.cos(slope) + np.cos(b) * np.sin(slope) * np.cos(a - aspect)
    return np.where(np.isfinite(z), hs, np.nan)


def figure(bdir: Path, out_png: Path, title: str):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with rasterio.open(bdir / "grid.tif") as ds:
        z = ds.read(1); dx = ds.transform.a
    rd = lambda n: rasterio.open(bdir / "ship_products_v2_1" / f"{n}.tif").read(1)
    cnt, rsd = rd("ship_count"), rd("ship_rsd")
    fig, ax = plt.subplots(1, 3, figsize=(15, 5))
    ax[0].imshow(hillshade(z, dx), cmap="gray"); ax[0].set_title(f"grid.tif hillshade (cell {dx:.1f} m)")
    i1 = ax[1].imshow(cnt, cmap="viridis"); ax[1].set_title("ship_count"); fig.colorbar(i1, ax=ax[1], shrink=0.8)
    i2 = ax[2].imshow(rsd, cmap="magma", vmax=np.nanpercentile(rsd, 99) if np.isfinite(rsd).any() else None); ax[2].set_title("ship_rsd (m)")
    fig.colorbar(i2, ax=ax[2], shrink=0.8)
    for a in ax:
        a.set_xticks([]); a.set_yticks([])
    fig.suptitle(title); fig.tight_layout(); fig.savefig(out_png, dpi=110); plt.close(fig)


def cmp(a_path, b_path):
    with rasterio.open(a_path) as a, rasterio.open(b_path) as b:
        A, Bm = a.read(1).astype("float64"), b.read(1).astype("float64")
        same_grid = (a.crs == b.crs and a.transform == b.transform and a.shape == b.shape)
    if A.shape != Bm.shape:
        return {"same_grid": False, "max_abs_diff": None, "nan_mismatch": None}
    both = np.isfinite(A) & np.isfinite(Bm)
    return {"same_grid": bool(same_grid), "max_abs_diff": float(np.max(np.abs(A[both] - Bm[both]))) if both.any() else 0.0,
            "nan_mismatch": int((np.isfinite(A) != np.isfinite(Bm)).sum())}


def repro_one(row, root: Path):
    cd = B.cdir_name(row.cruise)
    pdir = root / cd / row.block
    bj = json.loads((pdir / "block.json").read_text())
    zc, ei, ni = B.parse_block_id(row.block)
    raw = R.PRETRAIN_RAW / cd
    fman = json.loads((raw / "fetch_manifest.json").read_text())
    wd = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r04_repro" / cd / row.block
    shutil.rmtree(wd, ignore_errors=True); wd.mkdir(parents=True)
    loc = B.decompress(raw, bj["files"], wd)
    cov, _ = B.coverage_pass(wd, loc, bj["mb_format"])
    b = cov.blocks.get((zc, ei, ni))
    dmed = B.Coverage.median_depth(b)
    cell = 2.0 * dmed * math.tan(math.radians(bj["beamwidth_deg"] / 2.0))
    rec = {"cruise": row.cruise, "block": row.block, "family": row.instrument_family, "median_depth_persisted": bj["median_depth_m"],
           "median_depth_repro": round(dmed, 2), "n_soundings_persisted": bj["n_soundings"], "n_soundings_repro": b["n"],
           "cell_persisted": bj["cell_m"], "cell_repro": round(cell, 4)}
    args = B.mbgrid_args(f"dl_{row.block}.mb-1", f"g_{row.block}", zc, ei, ni, cell)
    res = B.run_mbgrid_batch(wd, [(row.block, loc, args)], bj["mb_format"])
    if not res[row.block]["ok"]:
        rec["error"] = f"mbgrid failed {res[row.block]}"; return rec
    tdir = R.SCR / "pretrain_v1_repro" / cd / row.block
    shutil.rmtree(tdir, ignore_errors=True); tdir.mkdir(parents=True)
    B.grd_to_tif(wd / f"g_{row.block}.grd", tdir / "grid.tif", B.zone_epsg(zc))
    (tdir / "lr.tif").symlink_to("grid.tif")
    rec["grid.tif"] = cmp(pdir / "grid.tif", tdir / "grid.tif")
    pr = B.run_products(row.cruise, row.block + "_repro", tdir, bj["files"], fman["files"], R.WORK_LOGS / cd / "repro")
    for f in sorted((pdir / "ship_products_v2_1").glob("*.tif")):
        rec[f.name] = cmp(f, tdir / "ship_products_v2_1" / f.name)
    rec["products_usable_persisted"] = bj.get("products", {}).get("usable"); rec["products_usable_repro"] = pr["usable"]
    shutil.rmtree(wd, ignore_errors=True)
    figure(pdir, R.REPORT_DIR / "qc" / f"{cd}__{row.block}.png",
           f"{row.cruise} {row.block} — {row.instrument_family}, depth {bj['median_depth_m']:.0f} m, cell {bj['cell_m']:.1f} m, fill {bj['fill']:.2f}")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--manifest", default="pretrain_manifest_v1.parquet")
    ap.add_argument("--root", default="OAK", choices=["OAK", "STAGE"])
    a = ap.parse_args(argv)
    man = pd.read_parquet(R.REPORT_DIR / a.manifest)
    pick = choose(man)
    if pick.instrument_family.nunique() < 4:
        print(f"WARNING: only {pick.instrument_family.nunique()} families in the corpus")
    (R.REPORT_DIR / "qc").mkdir(parents=True, exist_ok=True)
    root = R.OAK_OUT if a.root == "OAK" else R.STAGE
    recs = []
    for row in pick.itertuples():
        try:
            recs.append(repro_one(row, root))
        except Exception as e:
            recs.append({"cruise": row.cruise, "block": row.block, "family": row.instrument_family, "error": f"{type(e).__name__}: {e}"})
        R.write_json(R.REPORT_DIR / "repro_check_v1.json", {"generated": R.utc_now(), "seed": R.SEED_SPOT, "root": str(root),
                                                             "manifest": a.manifest, "blocks": recs, "code_commit": C.git_commit()})
    flat = []
    for r in recs:
        for k, v in r.items():
            if isinstance(v, dict):
                flat.append({"cruise": r["cruise"], "block": r["block"], "family": r["family"], "raster": k, **v})
    pd.DataFrame(flat).to_csv(R.REPORT_DIR / "repro_check_v1.csv", index=False)
    print(json.dumps(recs, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
