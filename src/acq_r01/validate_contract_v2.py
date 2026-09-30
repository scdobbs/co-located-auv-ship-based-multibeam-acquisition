"""ACQ-R02 §2.4 — validate every in-scope pair's ship_products_v2 against INTERFACE_CONTRACT_v2.

Checks: products.json v2 keys; if available: the seven rasters exist, float32, nodata NaN, grid
identical to lr.tif, count NaN exactly where no soundings, sd NaN where count < 2, rsd NaN where
count < 3, xtrack in [0,1], beam angle in [0,90], medians/means finite only where count >= 1,
mean/median sign as lr.tif, qa_shift_surface.csv present with 81 rows; if unavailable: no rasters
and a reason.  Also re-checks the v2-vs-v1 control equality.  Lockbox pairs are never touched.
Output: reports_post_grl_review/ACQ-R02/contract_v2_validation.{json,md}
Usage: python -m src.acq_r01.validate_contract_v2 [--pairs a,b]   (default: the 34 in-scope pairs)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys

import numpy as np
import rasterio

from src.acq_r01 import common as C

KEYS = {"contract_version", "pair_id", "lr_tif_path", "available", "unavailable_reason", "source", "beam_angle_method",
        "software", "commands", "grid", "qa_vs_lr_tif", "created"}
AVAIL = ("ship_count", "ship_sd", "ship_rsd", "ship_xtrack_frac", "ship_beam_angle")
RASTERS = ("ship_count", "ship_sd", "ship_rsd", "ship_xtrack_frac", "ship_beam_angle", "ship_mean_regrid", "ship_median_regrid")
QA_KEYS = {"n_common_cells", "median_offset_m", "rms_m", "robust_sigma_m", "rms_over_median_s_lr",
           "robust_sigma_over_median_s_lr", "s_lr_source", "shift_argmin_cells", "shift_surface_file", "flags"}


def validate(row):
    d = C.pair_dir_oak(row) / "ship_products_v2"
    res = {"pair_id": row.pair_id, "unit": C.UNIT_OF.get(row.pair_id), "dir": str(d), "errors": []}
    pj = d / "products.json"
    if not pj.exists():
        res["errors"].append("products.json missing"); return res
    p = json.loads(pj.read_text())
    miss = KEYS - set(p)
    if miss:
        res["errors"].append(f"missing keys {sorted(miss)}")
    if p.get("contract_version") != 2 or p.get("pair_id") != row.pair_id:
        res["errors"].append("contract_version/pair_id mismatch")
    av = p.get("available") or {}
    res["available"] = all(av.get(k) for k in AVAIL)
    tifs = [d / f"{r}.tif" for r in RASTERS]
    if not res["available"]:
        if any(t.exists() for t in tifs):
            res["errors"].append("unavailable but rasters present")
        if not p.get("unavailable_reason"):
            res["errors"].append("unavailable without reason")
        return res
    qa = p.get("qa_vs_lr_tif") or {}
    if QA_KEYS - set(qa):
        res["errors"].append(f"qa keys missing {sorted(QA_KEYS - set(qa))}")
    res["flags"] = qa.get("flags"); res["qa"] = qa
    if p.get("beam_angle_method") not in ("launch_angle", "geometric"):
        res["errors"].append("beam_angle_method invalid")
    sp = d / (qa.get("shift_surface_file") or "qa_shift_surface.csv")
    if not sp.exists():
        res["errors"].append("shift surface csv missing")
    else:
        with sp.open() as f:
            n = sum(1 for _ in csv.DictReader(f))
        if n != 81:
            res["errors"].append(f"shift surface has {n} rows, expected 81")
    with rasterio.open(C.pair_dir_oak(row) / "lr.tif") as lr:
        lcrs, ltr, lshape = lr.crs, lr.transform, lr.shape
        lr_arr = lr.read(1, masked=True).filled(np.nan)
    arrs = {}
    for r, t in zip(RASTERS, tifs):
        if not t.exists():
            res["errors"].append(f"{r}.tif missing"); continue
        with rasterio.open(t) as ds:
            if ds.dtypes[0] != "float32":
                res["errors"].append(f"{r} dtype {ds.dtypes[0]}")
            if ds.nodata is not None and not np.isnan(ds.nodata):
                res["errors"].append(f"{r} nodata {ds.nodata}")
            if not (ds.crs == lcrs and ds.transform == ltr and ds.shape == lshape):
                res["errors"].append(f"{r} grid != lr.tif")
            arrs[r] = ds.read(1)
    if len(arrs) == len(RASTERS):
        n = arrs["ship_count"]; has = np.isfinite(n)
        if (n[has] < 1).any():
            res["errors"].append("count < 1 where finite")
        for r in ("ship_xtrack_frac", "ship_beam_angle", "ship_mean_regrid", "ship_median_regrid"):
            if (np.isfinite(arrs[r]) & ~has).any():
                res["errors"].append(f"{r} finite where count is NaN")
            if (has & ~np.isfinite(arrs[r])).any() and r in ("ship_mean_regrid", "ship_median_regrid"):
                res["errors"].append(f"{r} NaN where count >= 1")
        if (np.isfinite(arrs["ship_sd"]) & ~(has & (n >= 2))).any():
            res["errors"].append("sd finite where count < 2")
        if (np.isfinite(arrs["ship_rsd"]) & ~(has & (n >= 3))).any():
            res["errors"].append("rsd finite where count < 3")
        if ((has & (n >= 3)) & ~np.isfinite(arrs["ship_rsd"])).any():
            res["errors"].append("rsd NaN where count >= 3")
        x = arrs["ship_xtrack_frac"][np.isfinite(arrs["ship_xtrack_frac"])]
        if x.size and (x.min() < 0 or x.max() > 1.0001):
            res["errors"].append("xtrack_frac out of [0,1]")
        b = arrs["ship_beam_angle"][np.isfinite(arrs["ship_beam_angle"])]
        if b.size and (b.min() < 0 or b.max() > 90):
            res["errors"].append("beam_angle out of [0,90]")
        for r in ("ship_mean_regrid", "ship_median_regrid"):
            mm = arrs[r]; both = np.isfinite(mm) & np.isfinite(lr_arr)
            if both.any() and np.sign(np.nanmedian(mm[both])) != np.sign(np.nanmedian(lr_arr[both])):
                res["errors"].append(f"{r} sign differs from lr.tif")
        # control vs v1
        v1d = d.parent / "ship_products_v1"
        for r in ("ship_count", "ship_sd", "ship_xtrack_frac", "ship_beam_angle"):
            t1 = v1d / f"{r}.tif"
            if t1.exists():
                with rasterio.open(t1) as ds:
                    if not np.array_equal(ds.read(1), arrs[r], equal_nan=True):
                        res["errors"].append(f"{r} differs from v1")
        res["cells"] = int(has.sum())
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = arrs["ship_rsd"] / arrs["ship_sd"]
        res["median_rsd_over_sd"] = round(float(np.nanmedian(ratio)), 3) if np.isfinite(ratio).any() else None
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", default=None); ap.add_argument("--manifest", default=None)
    ap.add_argument("--out", default="contract_v2_validation")
    a = ap.parse_args(argv)
    import pandas as pd
    m = pd.read_parquet(a.manifest) if a.manifest else C.load_manifest()
    pids = a.pairs.split(",") if a.pairs else list(C.PAIRS_IN_SCOPE)
    rows = m[m.pair_id.isin(pids)]
    C.assert_no_lockbox(rows.pair_id)
    out = [validate(r) for _, r in rows.iterrows()]
    rd = C.REPO / "reports_post_grl_review" / "ACQ-R02"; rd.mkdir(parents=True, exist_ok=True)
    (rd / f"{a.out}.json").write_text(json.dumps(out, indent=1, default=str))
    md = ["| pair | unit | available | valid | n common | median off m | robust σ m | robust σ / med s_lr | RMS m | argmin shift | flags | median rsd/sd | errors |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in out:
        q = r.get("qa") or {}
        md.append(f"| {r['pair_id']} | {r['unit']} | {r.get('available')} | {'ok' if not r['errors'] else 'FAIL'} | {q.get('n_common_cells', '')} | "
                  f"{q.get('median_offset_m', '')} | {q.get('robust_sigma_m', '')} | {q.get('robust_sigma_over_median_s_lr', '')} | {q.get('rms_m', '')} | "
                  f"{q.get('shift_argmin_cells', '')} | {','.join(q.get('flags', []) or []) or ('—' if r.get('available') else '')} | {r.get('median_rsd_over_sd', '')} | {'; '.join(r['errors'])} |")
    (rd / f"{a.out}.md").write_text("\n".join(md))
    print("\n".join(md))
    bad = [r["pair_id"] for r in out if r["errors"]]
    print(f"\n{len(out)} pairs validated, {len(bad)} with errors: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
