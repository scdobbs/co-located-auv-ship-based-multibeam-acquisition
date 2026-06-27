"""C2c — re-calibrate the C.5 threshold (THR) on the FINAL-grid setup, then
re-run the k SR-signal sweep against the corrected lr_native (resolves the C2b
confound).

C2b found the max-recoverable-k crossover moving 8 -> ~2, but it reused the OLD
C.5b THR. The directive asks: re-calibrate THR on THIS setup (same harmonized
grids + same corrected lr_native), so the crossover is measured like-for-like.

Re-calibration anchors = ONLY the 21 validated pairs (ground-truth recoverable),
NOT every harmonized dir (the calibration set must be the known-recoverable
ground truth — the new pairs are the unknowns under test). Synthetic white +
circular controls built from DISCOL, as in the original C.5b. lr_native for every
pair = the corrected manifest value (documented beam footprint, max rule).

Reads only. k stays a single GLOBAL factor; k lives in CLAUDE.md/pipeline.py,
not the manifest. No canonical write.
"""
from __future__ import annotations
import json, logging
from collections import Counter
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import transform_bounds
import pandas as pd

from src.discovery.stage_c5_spectral import load_to_common, perk_curve, perk_verdict
from src.discovery.validated_anchor import VALIDATED_PAIR_IDS, is_new

log = logging.getLogger("c2c")
REPO = Path(__file__).resolve().parents[2]
HARM = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/harmonized")
CANON = REPO / "manifest/pairs.parquet"
OUT_CAL = REPO / "reports/discovery/stage_c2c_calibration.json"
OUT_SWEEP = REPO / "reports/discovery/stage_c2c_sweep.json"
K_CAL = 2
KS = (2, 4, 8, 16, 32)


def pair_dir(pid):
    if pid.startswith("cal_dig_morro_bay__"):
        return HARM / "cal_dig_morro_bay" / pid.split("__", 1)[1]
    return HARM / pid


def _load(pid):
    d = pair_dir(pid)
    hr_p, lr_p = d / "hr.tif", d / "lr.tif"
    if not (hr_p.exists() and lr_p.exists()):
        return None
    with rasterio.open(str(hr_p)) as ds:
        hr_res = abs(ds.res[0])
        b = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
    lr, hr, dx = load_to_common(str(lr_p), str(hr_p), b, max(0.5, hr_res))
    return lr, hr, dx


def _slope_at(curve, k):
    return curve["per_k"].get(str(k), {}).get("slope_local") if curve else None


def recalibrate(lrn):
    """Derive THR on the 21 validated anchors (final harmonized grids)."""
    rec = []
    for pid in sorted(VALIDATED_PAIR_IDS):
        try:
            loaded = _load(pid)
            if loaded is None:
                log.warning("calib: missing grid %s", pid); continue
            lr, hr, dx = loaded
            c = perk_curve(lr, hr, dx, lrn[pid], KS)
            if c:
                c["name"] = pid; rec.append(c)
        except Exception as e:
            log.warning("calib ERR %s: %s", pid, str(e)[:80])
    assert len(rec) >= 20, f"too few calibration anchors resolved: {len(rec)}"

    # synthetic white + circular from DISCOL
    lr, hr, dx = _load("discol_so242_1")
    rng = np.random.RandomState(0)
    finite = np.isfinite(hr)
    amp = np.nanstd(hr[finite] - lr[finite]) if finite.any() else 1.0
    white = perk_curve(lr, np.where(finite, lr + rng.standard_normal(hr.shape) * amp, np.nan),
                       dx, lrn["discol_so242_1"], KS)
    circ = perk_curve(lr, np.where(finite, lr, np.nan), dx, lrn["discol_so242_1"], KS)

    slopes = np.array([_slope_at(r, K_CAL) for r in rec if _slope_at(r, K_CAL) is not None])
    cohs = np.array([r["edge_coh"] for r in rec if r["edge_coh"] is not None])
    w_s = _slope_at(white, K_CAL); c_s = _slope_at(circ, K_CAL)
    flattest_rec = float(slopes.max())
    w = w_s if w_s is not None else -0.8
    thr = {"slope_red": round(flattest_rec + 0.05, 2),
           "slope_white": round((flattest_rec + w) / 2, 2),
           "coh_circular": round((float(np.percentile(cohs, 90)) +
                                  (circ["edge_coh"] if circ["edge_coh"] is not None else 0.27)) / 2, 3),
           "grid": "AUV-native final harmonized; anchors=21 validated; corrected lr_native"}
    # sanity
    n_rec = sum(perk_verdict(_slope_at(r, K_CAL), r["edge_coh"], thr) == "recoverable_signal" for r in rec)
    cal = {"k_cal": K_CAL, "ks": list(KS), "thresholds": thr,
           "n_anchors": len(rec), "n_anchor_recoverable_at_kcal": n_rec,
           "white_verdict": perk_verdict(w_s, white["edge_coh"], thr),
           "circular_verdict": perk_verdict(c_s, circ["edge_coh"], thr),
           "anchor_slope_median": round(float(np.median(slopes)), 2),
           "anchor_slope_range": [round(float(slopes.min()), 2), round(float(slopes.max()), 2)],
           "white_slope": w_s, "circular_slope": c_s,
           "circular_edge_coh": circ["edge_coh"]}
    OUT_CAL.write_text(json.dumps(cal, indent=2, default=str))
    log.info("RECALIBRATION: anchors=%d, %d/%d recoverable@k%d; white->%s circ->%s; THR=%s",
             len(rec), n_rec, len(rec), K_CAL, cal["white_verdict"], cal["circular_verdict"], thr)
    return thr, cal


def sweep(pid, lr_native, thr):
    try:
        loaded = _load(pid)
    except Exception as e:
        return {"pair_id": pid, "status": f"load_failed: {str(e)[:60]}"}
    if loaded is None:
        return {"pair_id": pid, "status": "missing_grid"}
    lr, hr, dx = loaded
    curve = perk_curve(lr, hr, dx, lr_native, KS)
    if curve is None:
        return {"pair_id": pid, "status": "no_curve"}
    per_k, max_rec = {}, None
    for k in KS:
        v = perk_verdict(curve["per_k"].get(str(k), {}).get("slope_local"), curve["edge_coh"], thr)
        per_k[k] = v
        if v == "recoverable_signal":
            max_rec = k
    return {"pair_id": pid, "status": "ok", "lr_native_m": round(lr_native, 1),
            "edge_coh": curve.get("edge_coh"), "max_recoverable_k": max_rec, "per_k": per_k}


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    m = pd.read_parquet(CANON)
    lrn = {r["pair_id"]: float(r["lr_native_res_m"]) for _, r in m.iterrows()
           if str(r["lr_native_res_m"]) not in ("", "nan")}

    thr, cal = recalibrate(lrn)

    rows = [sweep(pid, lrn[pid], thr) for pid in m["pair_id"] if pid in lrn]
    ok = [r for r in rows if r.get("status") == "ok"]
    dist = Counter(r["max_recoverable_k"] for r in ok)
    n = len(ok)
    cross = None
    for k in KS:
        if sum(1 for r in ok if (r["max_recoverable_k"] or 0) >= k) / max(1, n) >= 0.5:
            cross = k
    # split validated vs new
    dist_new = Counter(r["max_recoverable_k"] for r in ok if is_new(r["pair_id"]))
    dist_val = Counter(r["max_recoverable_k"] for r in ok if not is_new(r["pair_id"]))
    out = {"calibration": cal, "n_swept": n, "KS": list(KS),
           "max_recoverable_k_distribution": {str(kk): dist.get(kk, 0) for kk in (None, *KS)},
           "dist_new_pairs": {str(kk): dist_new.get(kk, 0) for kk in (None, *KS)},
           "dist_validated": {str(kk): dist_val.get(kk, 0) for kk in (None, *KS)},
           "global_crossover_k_majority": cross,
           "c2b_crossover_was": 2, "c5c_original_crossover_was": 8,
           "pairs": rows}
    OUT_SWEEP.write_text(json.dumps(out, indent=2, default=str))
    log.info("=== C2c SWEEP: %d pairs; dist=%s ===", n, dict(dist))
    log.info("  new-pair dist=%s ; validated dist=%s", dict(dist_new), dict(dist_val))
    log.info("  GLOBAL crossover (majority recover) k=%s [recalibrated THR]; "
             "(c5c orig=8, c2b=2)", cross)
    log.info("wrote %s and %s", OUT_CAL, OUT_SWEEP)


if __name__ == "__main__":
    main()
