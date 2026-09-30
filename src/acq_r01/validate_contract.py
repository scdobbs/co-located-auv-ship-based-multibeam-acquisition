"""ACQ-R01 §2.2 step 5 — validate every in-scope pair's ship_products_v1 against INTERFACE_CONTRACT_v1.

Checks: products.json present with the §3 keys; if available: the five rasters exist, float32,
nodata NaN, CRS/transform/shape identical to lr.tif, count NaN exactly where no soundings, sd NaN
where count < 2, xtrack_frac within [0, 1], beam angle within [0, 90], mean depth negative-up sign like
lr.tif; if unavailable: no rasters and a reason.  Lockbox pairs are never touched.
(The CNN repo commits the reference validator, R04 §6.2; this is the producer-side copy.)
Output: reports_post_grl_review/ACQ-R01/contract_validation.{json,md}
"""
from __future__ import annotations

import json
import sys

import numpy as np
import rasterio

from src.acq_r01 import common as C

KEYS = {"contract_version", "pair_id", "available", "unavailable_reason", "source", "software", "commands", "grid",
        "qa_vs_lr_tif", "created"}
RASTERS = ("ship_sd", "ship_count", "ship_xtrack_frac", "ship_beam_angle", "ship_mean_regrid")


def validate(row):
    d = C.pair_dir_oak(row) / "ship_products_v1"
    res = {"pair_id": row.pair_id, "unit": C.UNIT_OF.get(row.pair_id), "dir": str(d), "errors": []}
    pj = d / "products.json"
    if not pj.exists():
        res["errors"].append("products.json missing"); return res
    p = json.loads(pj.read_text())
    miss = KEYS - set(p)
    if miss:
        res["errors"].append(f"missing keys {sorted(miss)}")
    if p.get("contract_version") != 1 or p.get("pair_id") != row.pair_id:
        res["errors"].append("contract_version/pair_id mismatch")
    av = p.get("available") or {}
    res["available"] = all(av.get(k) for k in ("ship_sd", "ship_count", "ship_xtrack_frac", "ship_beam_angle"))
    res["flag"] = (p.get("qa_vs_lr_tif") or {}).get("flag")
    tifs = [d / f"{r}.tif" for r in RASTERS]
    if not res["available"]:
        if any(t.exists() for t in tifs):
            res["errors"].append("unavailable but rasters present")
        if not p.get("unavailable_reason"):
            res["errors"].append("unavailable without reason")
        return res
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
                res["errors"].append(f"{r} nodata {ds.nodata} (expected NaN)")
            if not (ds.crs == lcrs and ds.transform == ltr and ds.shape == lshape):
                res["errors"].append(f"{r} grid != lr.tif")
            arrs[r] = ds.read(1)
    if len(arrs) == len(RASTERS):
        n = arrs["ship_count"]
        has = np.isfinite(n)
        if (n[has] < 1).any():
            res["errors"].append("count < 1 where finite")
        for r in ("ship_xtrack_frac", "ship_beam_angle", "ship_mean_regrid"):
            if (np.isfinite(arrs[r]) & ~has).any():
                res["errors"].append(f"{r} finite where count is NaN")
        if (np.isfinite(arrs["ship_sd"]) & ~(has & (n >= 2))).any():
            res["errors"].append("sd finite where count < 2")
        x = arrs["ship_xtrack_frac"][np.isfinite(arrs["ship_xtrack_frac"])]
        if x.size and (x.min() < 0 or x.max() > 1.0001):
            res["errors"].append(f"xtrack_frac range [{x.min():.3f},{x.max():.3f}]")
        b = arrs["ship_beam_angle"][np.isfinite(arrs["ship_beam_angle"])]
        if b.size and (b.min() < 0 or b.max() > 90):
            res["errors"].append(f"beam_angle range [{b.min():.1f},{b.max():.1f}]")
        mm = arrs["ship_mean_regrid"]; both = np.isfinite(mm) & np.isfinite(lr_arr)
        if both.any() and np.sign(np.nanmedian(mm[both])) != np.sign(np.nanmedian(lr_arr[both])):
            res["errors"].append("mean_regrid sign differs from lr.tif")
        res["cells"] = int(has.sum()); res["lr_valid_cells"] = int(np.isfinite(lr_arr).sum())
        res["frac_lr_valid_covered"] = round(float((has & np.isfinite(lr_arr)).sum() / max(1, np.isfinite(lr_arr).sum())), 4)
    res["qa"] = p.get("qa_vs_lr_tif")
    return res


def main():
    m = C.load_manifest()
    rows = m[m.pair_id.isin(C.PAIRS_IN_SCOPE)]
    C.assert_no_lockbox(rows.pair_id)
    out = [validate(r) for _, r in rows.iterrows()]
    C.write_json(C.REPORT_DIR / "contract_validation.json", out)
    md = ["| pair | unit | available | valid | QA flag | RMS m | med m | MAD m | RMS/med s_lr | cells (LR-valid covered) | errors |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in out:
        q = r.get("qa") or {}
        md.append(f"| {r['pair_id']} | {r['unit']} | {r.get('available')} | {'ok' if not r['errors'] else 'FAIL'} | {r.get('flag')} | "
                  f"{q.get('rms_m', '')} | {q.get('median_offset_m', '')} | {q.get('mad_m', '')} | {q.get('rms_over_median_s_lr', '')} | "
                  f"{r.get('cells', '')} ({r.get('frac_lr_valid_covered', '')}) | {'; '.join(r['errors'])} |")
    (C.REPORT_DIR / "contract_validation.md").write_text("\n".join(md))
    print("\n".join(md))
    bad = [r["pair_id"] for r in out if r["errors"]]
    print(f"\n{len(out)} pairs validated, {len(bad)} with errors: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
