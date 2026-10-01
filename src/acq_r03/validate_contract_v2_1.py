"""ACQ-R03 §2.5 — validate ship_products_v2_1 against INTERFACE_CONTRACT_v2.1 for every pair with products
(and the unavailable Cal DIG pairs).  v2 checks (schema, grid identity with lr.tif, NaN/count conditions, 81-row
surface, ranges, sign) plus: contract_version "2.1"; frame_offset block (basis none|grid_header_registration,
applied only with the latter, never fitted); qa sigma0_m / sigma_argmin_m / gain_m present and consistent with the
surface; flags reproduce the v2.1 gate from the recorded numbers; control: rasters equal v2 (NaN-aware) where no
frame offset is applied.  Output: reports_post_grl_review/ACQ-R03/contract_v2_1_validation.{json,md}.
Usage: python -m src.acq_r03.validate_contract_v2_1 [--pairs a,b]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys

import numpy as np
import pandas as pd
import rasterio

from src.acq_r01 import common as C
from src.acq_r03 import common as R

KEYS = {"contract_version", "pair_id", "lr_tif_path", "available", "unavailable_reason", "source", "beam_angle_method", "software", "commands", "grid",
        "frame_offset", "qa_vs_lr_tif", "created"}
AVAIL = ("ship_count", "ship_sd", "ship_rsd", "ship_xtrack_frac", "ship_beam_angle")
RASTERS = ("ship_count", "ship_sd", "ship_rsd", "ship_xtrack_frac", "ship_beam_angle", "ship_mean_regrid", "ship_median_regrid")
QA_KEYS = {"n_common_cells", "median_offset_m", "rms_m", "robust_sigma_m", "rms_over_median_s_lr", "robust_sigma_over_median_s_lr", "s_lr_source",
           "shift_argmin_cells", "shift_surface_file", "flags", "sigma0_m", "sigma_argmin_m", "gain_m"}
FO_KEYS = {"applied", "dx_m", "dy_m", "basis", "evidence"}


def validate(pid: str, pdir):
    d = pdir / "ship_products_v2_1"
    res = {"pair_id": pid, "dir": str(d), "errors": []}
    pj = d / "products.json"
    if not pj.exists():
        res["errors"].append("products.json missing"); return res
    p = json.loads(pj.read_text())
    if KEYS - set(p):
        res["errors"].append(f"missing keys {sorted(KEYS - set(p))}")
    if p.get("contract_version") != "2.1" or p.get("pair_id") != pid:
        res["errors"].append("contract_version/pair_id mismatch")
    fo = p.get("frame_offset") or {}
    if FO_KEYS - set(fo):
        res["errors"].append("frame_offset keys missing")
    if fo.get("basis") not in ("none", "grid_header_registration"):
        res["errors"].append("frame_offset basis invalid")
    if fo.get("applied") and fo.get("basis") != "grid_header_registration":
        res["errors"].append("frame offset applied without grid_header_registration basis")
    if not fo.get("applied") and (fo.get("dx_m") or fo.get("dy_m")):
        res["errors"].append("frame offset not applied but non-zero")
    res["frame_offset"] = fo
    av = p.get("available") or {}; res["available"] = all(av.get(k) for k in AVAIL)
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
        rows = list(csv.DictReader(sp.open()))
        if len(rows) != 81:
            res["errors"].append(f"shift surface has {len(rows)} rows, expected 81")
        else:
            s0 = [float(r["robust_sigma_m"]) for r in rows if float(r["dx_cells"]) == 0 and float(r["dy_cells"]) == 0][0]
            am = qa.get("shift_argmin_cells") or [0, 0]
            smin = [float(r["robust_sigma_m"]) for r in rows if float(r["dx_cells"]) == am[0] and float(r["dy_cells"]) == am[1]][0]
            if abs(s0 - qa["sigma0_m"]) > 1e-3 or abs(smin - qa["sigma_argmin_m"]) > 1e-3 or abs((s0 - smin) - qa["gain_m"]) > 2e-3:
                res["errors"].append("sigma0/sigma_argmin/gain inconsistent with the surface")
            # gate reproduction
            exp = []
            if qa["n_common_cells"] < 500:
                exp.append("insufficient_overlap")
            if "vertical_offset" in qa["flags"]:
                exp.append("vertical_offset")     # threshold depends on s_lr (recorded in products_extra); accepted as recorded
            if max(abs(am[0]), abs(am[1])) >= 0.5 and qa["gain_m"] >= max(0.10, 0.05 * qa["sigma0_m"]) - 1e-9:
                exp.append("registration_shift")
            if sorted(exp) != sorted(qa["flags"]):
                res["errors"].append(f"flags {qa['flags']} do not reproduce the v2.1 gate {exp}")
    with rasterio.open(pdir / "lr.tif") as lr:
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
        v2d = pdir / "ship_products_v2"; ctrl = {}
        # a documented v2 deficiency: files the June/ACQ-R02 build lost (mblist rc != 0, 0 rows) that v2.1 read (rc 0, rows > 0)
        v2_lost = []
        try:
            e2 = {q["file"]: q for q in json.loads((v2d / "products_extra.json").read_text())["per_file"]}
            e21 = {q["file"]: q for q in json.loads((d / "products_extra.json").read_text())["per_file"]}
            v2_lost = [f for f, q in e2.items() if q["rc"] != 0 and q["n_rows"] == 0 and f in e21 and e21[f]["rc"] == 0 and e21[f]["n_rows"] > 0]
            v21_lost = [f for f, q in e21.items() if q["rc"] != 0]
            if v21_lost:
                res["errors"].append(f"v2.1 build has {len(v21_lost)} failed mblist call(s): {v21_lost[:3]}")
        except Exception:
            pass
        for r in RASTERS:
            t2 = v2d / f"{r}.tif"
            if t2.exists():
                with rasterio.open(t2) as ds:
                    eq = np.array_equal(ds.read(1), arrs[r], equal_nan=True)
                ctrl[r] = bool(eq)
                if not eq and not fo.get("applied") and not v2_lost:
                    res["errors"].append(f"{r} differs from v2 without a frame offset")
        res["control_equal_v2"] = ctrl
        res["v2_lost_files"] = v2_lost
        res["cells"] = int(has.sum())
        with np.errstate(invalid="ignore", divide="ignore"):
            ratio = arrs["ship_rsd"] / arrs["ship_sd"]
        res["median_rsd_over_sd"] = round(float(np.nanmedian(ratio)), 3) if np.isfinite(ratio).any() else None
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--pairs", default=None); ap.add_argument("--out", default="contract_v2_1_validation")
    a = ap.parse_args(argv)
    m = pd.read_parquet(C.REPO / "manifest" / "pairs_v2.parquet").set_index("pair_id")
    new = (R.R02 / "new_dev_pairs.txt").read_text().strip().split(",")
    pids = a.pairs.split(",") if a.pairs else list(C.PAIRS_IN_SCOPE) + new
    C.assert_no_lockbox(pids)
    out = []
    for pid in pids:
        pdir = R.OAK / str(m.loc[pid, "harmonized_path"])
        out.append({**validate(pid, pdir), "unit": m.loc[pid, "leakage_unit"], "designation": m.loc[pid, "designation"]})
    R.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (R.REPORT_DIR / f"{a.out}.json").write_text(json.dumps(out, indent=1, default=str))
    md = ["| pair | unit | available | valid | n common | median off m | σ0 m | argmin (dx, dy) | σ argmin m | gain m | gate gain m | v2.1 flags | frame offset | = v2 | errors |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in out:
        q = r.get("qa") or {}; fo = r.get("frame_offset") or {}
        ce = r.get("control_equal_v2"); ce_s = ("all" if ce and all(ce.values()) else ((f"differ: v2 lost {len(r['v2_lost_files'])} file(s)" if r.get("v2_lost_files") else "DIFFER") if ce else "")) if r.get("available") else ""
        md.append(f"| {r['pair_id']} | {r['unit']} | {r.get('available')} | {'ok' if not r['errors'] else 'FAIL'} | {q.get('n_common_cells', '')} | {q.get('median_offset_m', '')} | "
                  f"{q.get('sigma0_m', '')} | {q.get('shift_argmin_cells', '')} | {q.get('sigma_argmin_m', '')} | {q.get('gain_m', '')} | {(q.get('registration_gate') or {}).get('min_gain_m', '')} | "
                  f"{','.join(q.get('flags', []) or []) or ('—' if r.get('available') else '')} | {'applied' if fo.get('applied') else 'none'} | {ce_s} | {'; '.join(r['errors'])} |")
    (R.REPORT_DIR / f"{a.out}.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    bad = [r["pair_id"] for r in out if r["errors"]]
    print(f"\n{len(out)} pairs validated, {len(bad)} with errors: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
