"""Stage C.5 S0 — calibrate the SR-signal metric on known references."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform_bounds

from src.discovery.stage_c5_spectral import perk_curve, load_to_common

REPO = Path(__file__).resolve().parents[2]
HARM = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/harmonized")
K_CAL = 2   # threshold-setting factor — resolvable for ALL references (even
            # the 5x Cal DIG pairs); slope is ~scale-invariant for red spectra.
KS = (2, 4, 8, 16, 32)


def _meta(lr_path, hr_path):
    with rasterio.open(hr_path) as ds:
        b = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
        hr_res = abs(ds.res[0])
    with rasterio.open(lr_path) as ds:
        lr_res = abs(ds.res[0])
    return b, lr_res, hr_res


def harmonized_pairs():
    pairs = []
    for d in sorted(HARM.rglob("hr.tif")):
        lr = d.parent / "lr.tif"
        if lr.exists():
            pairs.append((str(d.parent.relative_to(HARM)).replace("/", "__"), lr, d))
    return pairs


def _common(lr_path, hr_path):
    """Common grid at AUV-NATIVE resolution (Track A) — resolves every k up to
    the AUV Nyquist, not just k=8."""
    b, lr_res, hr_res = _meta(lr_path, hr_path)
    return load_to_common(lr_path, hr_path, b, max(0.5, hr_res)), lr_res


def localslope_at(curve, k):
    return curve["per_k"].get(str(k), {}).get("slope_local") if curve else None


def metric_on_pair(lr_path, hr_path):
    (lr, hr, dx), lr_res = _common(lr_path, hr_path)
    return perk_curve(lr, hr, dx, lr_res, KS), lr_res


def synth_refs(lr_path, hr_path):
    (lr, hr, dx), lr_res = _common(lr_path, hr_path)
    rng = np.random.RandomState(0)
    finite = np.isfinite(hr)
    amp = np.nanstd(hr[finite] - lr[finite]) if finite.any() else 1.0
    white = np.where(finite, lr + rng.standard_normal(hr.shape) * amp, np.nan)
    circ = np.where(finite, lr, np.nan)
    return (perk_curve(lr, white, dx, lr_res, KS),
            perk_curve(lr, circ, dx, lr_res, KS))


def main():
    pairs = harmonized_pairs()
    print(f"calibration (FINER/AUV-native grid): {len(pairs)} known-recoverable pairs")
    rec = []
    for name, lr, hr in pairs:
        try:
            curve, lrr = metric_on_pair(lr, hr)
            if curve:
                curve["name"] = name; curve["lr_res"] = round(lrr, 1)
                rec.append(curve)
        except Exception as e:
            print("  ERR", name, str(e)[:80])
    disc = next((p for p in pairs if "discol" in p[0]), pairs[0])
    white, circ = synth_refs(disc[1], disc[2])

    slopes = np.array([localslope_at(r, K_CAL) for r in rec
                       if localslope_at(r, K_CAL) is not None])
    cohs = np.array([r["edge_coh"] for r in rec if r["edge_coh"] is not None])
    w_s = localslope_at(white, K_CAL); c_s = localslope_at(circ, K_CAL)
    print(f"\n=== known-recoverable local slope @k={K_CAL} (target scale) ===")
    print(f"  slope:    median {np.median(slopes):.2f}  range [{slopes.min():.2f},{slopes.max():.2f}]")
    print(f"  edge_coh: median {np.median(cohs):.3f}  range [{cohs.min():.3f},{cohs.max():.3f}]")
    print(f"  white-roughness: slope={w_s} edge_coh={white['edge_coh']}")
    print(f"  circular:        slope={c_s} edge_coh={circ['edge_coh']}")

    flattest_rec = float(slopes.max())
    w = w_s if w_s is not None else -0.8
    rec_coh_hi = float(np.percentile(cohs, 90))
    circ_coh = circ["edge_coh"] if circ["edge_coh"] is not None else 0.27
    thr = {
        "slope_red": round(flattest_rec + 0.05, 2),
        "slope_white": round((flattest_rec + w) / 2, 2),
        "coh_circular": round((rec_coh_hi + circ_coh) / 2, 3),
        "grid": "AUV-native (Track A finer)",
    }
    print("\n=== derived thresholds (finer grid) ===", thr)
    out = {"k_cal": K_CAL, "ks": list(KS), "thresholds": thr,
           "white_ref": white, "circular_ref": circ, "per_pair": rec}
    (REPO / "reports/discovery/stage_c5b_calibration.json").write_text(
        json.dumps(out, indent=2, default=str))
    from src.discovery.stage_c5_spectral import perk_verdict
    n_rec = sum(perk_verdict(localslope_at(r, K_CAL), r["edge_coh"], thr) == "recoverable_signal"
                for r in rec)
    print(f"\nSANITY @k={K_CAL}: {n_rec}/{len(rec)} known-recoverable scored recoverable_signal")
    print(f"  white -> {perk_verdict(w_s, white['edge_coh'], thr)} ; "
          f"circular -> {perk_verdict(c_s, circ['edge_coh'], thr)}")
    print("wrote reports/discovery/stage_c5b_calibration.json")


if __name__ == "__main__":
    main()
