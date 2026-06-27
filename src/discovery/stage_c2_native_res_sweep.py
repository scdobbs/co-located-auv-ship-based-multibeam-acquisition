"""C2 — native-res / res_ratio estimate-vs-measured sweep across ALL manifest pairs.

NA076's lr_native=221 was a ~10x derivation artifact; the same derivation set every
row's native res. Here, per pair:
  - estimate  = beam-footprint lower bound = 2*depth*tan(0.5deg)  (sonar+depth)
  - measured  = harmonized lr.tif cell size / sqrt(fill) over the footprint
    (the actual LR grid resolution in the product; -C0 grids -> ~sounding density)
  - recorded  = manifest lr_native_res_m
Flag where recorded disagrees with measured by > FLAG_X. Propose metadata-only
corrections (rasters unchanged). Present to Steve before Phase 2. Read-only.
"""
from __future__ import annotations
import json, logging, math
from pathlib import Path
import numpy as np
import rasterio
import pandas as pd

log = logging.getLogger("c2")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
HARM = DATA / "harmonized"
CANON = REPO / "manifest/pairs.parquet"
OUT = REPO / "reports/discovery/stage_c2_native_res_sweep.json"
FLAG_X = 1.8   # flag if recorded/measured or measured/recorded > this


def measured_lr_native(pid):
    """harmonized lr.tif metric cell size + fill -> sounding-density proxy."""
    p = HARM / pid / "lr.tif"
    if not p.exists():
        return None
    with rasterio.open(str(p)) as ds:
        res = abs(ds.res[0])
        crs = ds.crs
        a = ds.read(1, masked=True).filled(np.nan).astype("float64")
        nd = ds.nodata
    if crs and crs.is_geographic:
        res = res * 111320.0   # deg->m (approx; harmonized are UTM so usually metric already)
    fin = np.isfinite(a)
    if nd is not None:
        fin &= ~np.isclose(a, nd, atol=1e-3)
    fill = float(fin.mean()) if a.size else 0.0
    cell = float(res)
    proxy = cell / max(0.05, fill) ** 0.5
    return {"lr_cell_m": round(cell, 2), "fill": round(fill, 3), "measured_native_m": round(proxy, 1)}


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    m = pd.read_parquet(CANON)
    rows = []
    for _, r in m.iterrows():
        pid = r["pair_id"]
        depth = abs(float(r["depth_max_m"])) if pd.notna(r["depth_max_m"]) and str(r["depth_max_m"]) != "" else None
        est = round(2 * depth * math.tan(math.radians(0.5)), 1) if depth else None
        meas = measured_lr_native(pid)
        rec = {"pair_id": pid, "recorded_lr_native_m": float(r["lr_native_res_m"]) if pd.notna(r["lr_native_res_m"]) and str(r["lr_native_res_m"]) != "" else None,
               "depth_m": depth, "beam_footprint_estimate_m": est, **(meas or {})}
        recd, mz = rec["recorded_lr_native_m"], (meas or {}).get("measured_native_m")
        if recd and mz and mz > 0:
            ratio = max(recd / mz, mz / recd)
            rec["recorded_vs_measured_x"] = round(ratio, 2)
            rec["flag"] = bool(ratio > FLAG_X)
            if rec["flag"]:
                rec["proposed_lr_native_res_m"] = mz
                rec["proposed_res_ratio"] = round(mz / float(r["hr_native_res_m"]), 2) if pd.notna(r["hr_native_res_m"]) and float(r["hr_native_res_m"]) > 0 else None
        rows.append(rec)
    flagged = [r for r in rows if r.get("flag")]
    out = {"flag_threshold_x": FLAG_X, "n_pairs": len(rows), "n_flagged": len(flagged),
           "flagged": flagged, "all": rows}
    OUT.write_text(json.dumps(out, indent=2, default=str))
    log.info("C2 sweep: %d pairs, %d flagged (>%.1fx recorded-vs-measured)", len(rows), len(flagged), FLAG_X)
    for f in sorted(flagged, key=lambda x: -x.get("recorded_vs_measured_x", 0)):
        log.info("  FLAG %-26s recorded=%s measured=%s (%sx) -> propose %s",
                 f["pair_id"], f["recorded_lr_native_m"], f.get("measured_native_m"),
                 f.get("recorded_vs_measured_x"), f.get("proposed_lr_native_res_m"))
    log.info("wrote %s", OUT)


if __name__ == "__main__":
    main()
