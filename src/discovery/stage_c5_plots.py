"""Stage C.5 S4 — spectral QC plots: PSD of LR vs HR with the SR band shaded,
for calibration references + representative corpus pairs + flagged pairs."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.discovery.stage_c5_spectral import load_to_common, radial_psd
from src.discovery.stage_c5_sweep import (
    lr_grid_path, staged_hr_raster, materialize_hr, footprint_for, catalog_crs,
)
import rasterio
from rasterio.warp import transform_bounds

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "reports/discovery/stage_c5_qc"
OUT.mkdir(parents=True, exist_ok=True)
CAL = json.loads((REPO / "reports/discovery/stage_c5b_calibration.json").read_text())
THR = CAL["thresholds"]


def _overlap_bounds(lr_p, hr_p, poly):
    bb = [poly.bounds]
    for p in (lr_p, hr_p):
        with rasterio.open(str(p)) as ds:
            if ds.crs:
                bb.append(transform_bounds(ds.crs, "EPSG:4326", *ds.bounds))
    w = max(x[0] for x in bb); s = max(x[1] for x in bb)
    e = min(x[2] for x in bb); n = min(x[3] for x in bb)
    return (w, s, e, n) if (w < e and s < n) else None


def plot_pair(cruise, hr_id, lr_native, label, tag):
    lr_p = lr_grid_path(cruise, hr_id)
    hr_p = materialize_hr(hr_id, staged_hr_raster(hr_id), "/tmp/c5plot")
    poly = footprint_for(hr_id)
    b = _overlap_bounds(lr_p, hr_p, poly)
    if b is None:
        return
    lr, hr, dx = load_to_common(str(lr_p), str(hr_p), b, max(1.0, lr_native / 16))
    fcl, pl = radial_psd(lr, dx)
    fch, ph = radial_psd(hr, dx)
    if fch is None:
        return
    f_lr = 1.0 / lr_native
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.loglog(fch, ph, "-", color="C1", label="AUV HR")
    ax.loglog(fcl, pl, "-", color="C0", label="ship LR")
    for k, c in zip((2, 4, 8), ("#cce", "#aac", "#88a")):
        ax.axvspan(f_lr, k * f_lr, color=c, alpha=0.25, zorder=0)
    ax.axvline(f_lr, color="k", ls="--", lw=0.8)
    ax.set_xlabel("spatial frequency (cycles/m)"); ax.set_ylabel("radial PSD")
    ax.set_title(f"{label}\n{cruise} -> {hr_id}  (SR bands k=2/4/8 shaded)")
    ax.legend()
    fig.savefig(OUT / f"psd_{tag}.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    print("wrote", OUT / f"psd_{tag}.png")


def main():
    sweep = json.loads((REPO / "reports/discovery/stage_c5b_sweep.json").read_text())
    ok = [r for r in sweep if r["status"] == "ok"]
    # representative recoverable (deep rescue), a circular_leak, a no_spectrum
    picks = []
    rescue = [r for r in ok if (r.get("prior_ratio") or 0) > 40 and r["max_recoverable_k"]]
    if rescue:
        r = rescue[0]; picks.append((r, "deep-pair RESCUE (recoverable)", "rescue"))
    leak = [r for r in ok if r["per_k"]["4"]["verdict"] == "circular_leak"]
    if leak:
        r = leak[0]; picks.append((r, "circular_leak (independence flag)", "circular"))
    shallow = [r for r in ok if r["max_recoverable_k"] is None and r["per_k"]["4"]["verdict"] != "circular_leak"]
    if shallow:
        r = shallow[0]; picks.append((r, "unrecoverable (roughness/degenerate)", "rough"))
    rec = [r for r in ok if r["max_recoverable_k"] == 8][:1]
    if rec:
        picks.append((rec[0], "recoverable @8x", "recov8"))
    # corpus per-k recoverable-count curve
    import collections
    ks=['2','4','8','16','32']
    counts=[sum(1 for r in ok if r['per_k'][k].get('verdict') in ('recoverable_signal','circular_leak')) for k in ks]
    fig,ax=plt.subplots(figsize=(6,4)); ax.plot([2,4,8,16,32],counts,'o-')
    ax.set_xscale('log',base=2); ax.set_xlabel('SR factor k (target=LR/k)'); ax.set_ylabel('pairs w/ recoverable red SR structure')
    ax.set_title('Corpus per-k recoverable curve (finer grid)'); ax.grid(alpha=0.3)
    fig.savefig(OUT/'corpus_perk_curve.png',dpi=120,bbox_inches='tight'); plt.close(fig); print('wrote corpus_perk_curve.png')
    for r, label, tag in picks:
        try:
            plot_pair(r["cruise"], r["hr_id"], float(r["lr_native_m"]), label, tag)
        except Exception as e:
            print("plot fail", r["cruise"], r["hr_id"], str(e)[:80])


if __name__ == "__main__":
    main()
