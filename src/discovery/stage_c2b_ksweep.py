"""C2b — re-run the k SR-signal sweep against the CORRECTED lr_native (C2a).

Re-runs the C.5-style per-k spectral check (recoverable red structure in the SR
band vs unpredictable roughness) on the FINAL harmonized grids, using each pair's
corrected `lr_native_res_m` from the manifest. k stays a single GLOBAL factor
(target = lr_native / k). Reports the per-pair max_recoverable_k distribution and
whether the structure/roughness crossover is still 8x or has moved.

Reads only (no canonical write). k lives in CLAUDE.md/pipeline.py, not the manifest.
"""
from __future__ import annotations
import json, logging
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import transform_bounds
import pandas as pd

from src.discovery.stage_c5_spectral import load_to_common, perk_curve, perk_verdict
from src.discovery.stage_c5_sweep import THR, KS

log = logging.getLogger("c2b")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
HARM = DATA / "harmonized"
CANON = REPO / "manifest/pairs.parquet"
OUT = REPO / "reports/discovery/stage_c2b_ksweep.json"


def pair_dir(pid):
    if pid.startswith("cal_dig_morro_bay__"):
        return HARM / "cal_dig_morro_bay" / pid.split("__", 1)[1]
    return HARM / pid


def sweep(pid, lr_native):
    d = pair_dir(pid)
    hr_p, lr_p = d / "hr.tif", d / "lr.tif"
    if not (hr_p.exists() and lr_p.exists()):
        return {"pair_id": pid, "status": "missing_grid"}
    with rasterio.open(str(hr_p)) as ds:
        hr_res = abs(ds.res[0])
        b = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
    target_res = max(0.5, hr_res)
    try:
        lr, hr, dx = load_to_common(str(lr_p), str(hr_p), b, target_res)
    except Exception as e:
        return {"pair_id": pid, "status": f"load_failed: {str(e)[:80]}"}
    curve = perk_curve(lr, hr, dx, lr_native, KS)
    if curve is None:
        return {"pair_id": pid, "status": "no_curve"}
    per_k = {}
    max_rec = None
    for k in KS:
        pk = curve["per_k"].get(str(k), {})
        v = perk_verdict(pk.get("slope_local"), curve["edge_coh"], THR)
        per_k[k] = v
        if v == "recoverable_signal":
            max_rec = k
    return {"pair_id": pid, "status": "ok", "lr_native_m": round(lr_native, 1),
            "edge_coh": curve.get("edge_coh"), "max_recoverable_k": max_rec, "per_k": per_k}


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    m = pd.read_parquet(CANON)
    rows = []
    for _, r in m.iterrows():
        lrn = float(r["lr_native_res_m"]) if str(r["lr_native_res_m"]) not in ("", "nan") else None
        if lrn is None:
            continue
        try:
            res = sweep(r["pair_id"], lrn)
        except Exception as e:
            res = {"pair_id": r["pair_id"], "status": f"error: {str(e)[:80]}"}
        rows.append(res)
        log.info("[%s] %s maxk=%s lr_native=%s", res["pair_id"], res.get("status"),
                 res.get("max_recoverable_k"), res.get("lr_native_m"))
    ok = [r for r in rows if r.get("status") == "ok"]
    from collections import Counter
    dist = Counter(r["max_recoverable_k"] for r in ok)
    # global crossover: the largest k at which a majority of pairs still recover signal
    n = len(ok)
    cross = None
    for k in KS:
        frac = sum(1 for r in ok if (r["max_recoverable_k"] or 0) >= k) / max(1, n)
        if frac >= 0.5:
            cross = k
    out = {"n_pairs_swept": n, "KS": list(KS),
           "max_recoverable_k_distribution": {str(kk): dist.get(kk, 0) for kk in (None, *KS)},
           "global_crossover_k_majority": cross, "prior_calibrated_k": 8,
           "moved": (cross != 8), "pairs": rows}
    OUT.write_text(json.dumps(out, indent=2, default=str))
    log.info("=== C2b: swept %d pairs; max_rec_k dist=%s ===", n, dict(dist))
    log.info("global crossover (majority recover) k=%s (prior=8); moved=%s", cross, cross != 8)
    log.info("wrote %s", OUT)


if __name__ == "__main__":
    main()
