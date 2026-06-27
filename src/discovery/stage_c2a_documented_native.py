"""C2a — documented beam-footprint LR_native + A/B/C branch (the revised standard).

lr_native = documented beam-footprint resolution = 2*depth*tan(beamwidth/2) from
the cruise's documented sonar. Reconcile against the original-grid posting:
  Case A: posting ~ footprint            -> lr_native = footprint (metadata-only)
  Case B: posting >> footprint (>2x)     -> grid built too coarse -> RE-GRID
  Case C: posting << footprint (<0.5x)   -> over-posted -> lr_native = footprint (metadata-only)

New pairs only (18); the 21 validated already carry documented source res (untouched).
Reports the 3 numbers + case per pair. No canonical write (HOLD for Steve).
"""
from __future__ import annotations
import json, logging, math, re
from pathlib import Path
import numpy as np
import rasterio
import pandas as pd

log = logging.getLogger("c2a")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
GRID = DATA / "raw_lr_gridded"
RAWLR = DATA / "raw_lr"
CANON = REPO / "manifest/pairs.parquet"
OUT = REPO / "reports/discovery/stage_c2a_documented_native.json"

# MB-System format -> (sonar family, nominal beam width deg)
FMT_SONAR = {"21": ("Atlas Hydrosweep DS", 2.3), "41": ("SeaBeam 2100", 2.0),
             "56": ("Simrad EM (.all)", 1.0), "58": ("Kongsberg EM (.all)", 1.0),
             "121": ("Kongsberg EM", 1.0), "183": ("SeaBeam 2120/MR1 class", 2.0),
             "94": ("L-3 ELAC/SeaBeam XSE", 1.5)}


def lr_format_sonar(cruise):
    d = RAWLR / cruise
    fn = next((p.name for p in d.iterdir() if re.search(r"\.mb\d+", p.name)), "") if d.is_dir() else ""
    fmt = (re.search(r"\.mb(\d+)", fn) or [None, "?"])[1]
    son, bw = FMT_SONAR.get(fmt, ("unknown", 1.0))
    em = re.search(r"EM\s?\d{3,4}", fn)
    if em:
        son = "Kongsberg " + em.group(0); bw = 1.0
    return fmt, son, bw


def grid_posting_m(cruise):
    cands = sorted(GRID.glob(f"{cruise}__*.grd"), key=lambda p: 0 if "union" in p.name else 1)
    for gp in cands:
        for c in (str(gp), "NETCDF:" + str(gp)):
            try:
                ds = rasterio.open(c)
            except Exception:
                continue
            res = abs(ds.res[0]); b = ds.bounds; crs = ds.crs; ds.close()
            postm = res * 111320 * math.cos(math.radians((b.bottom + b.top) / 2)) if (crs and crs.is_geographic) else res
            return round(float(postm), 1), gp.name
    return None, None


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    m = pd.read_parquet(CANON)
    new = m[~m.verification_status.astype(str).str.contains("validated")]
    rows = []
    for _, r in new.sort_values("pair_id").iterrows():
        pid = r["pair_id"]; cruise = pid.rsplit("__MGDS", 1)[0]
        depth = abs(float(r["depth_max_m"])) if str(r["depth_max_m"]) not in ("", "nan") else None
        fmt, son, bw = lr_format_sonar(cruise)
        footprint = round(2 * depth * math.tan(math.radians(bw / 2)), 1) if depth else None
        posting, gfile = grid_posting_m(cruise)
        recorded = float(r["lr_native_res_m"])
        case = None; note = ""
        if footprint and posting:
            ratio = posting / footprint
            if ratio > 2.0:
                case = "B_regrid (posting>>footprint)"
            elif ratio < 0.5:
                case = "C_overposted (posting<<footprint)"
            else:
                case = "A_ok (posting~footprint)"
        corrected = footprint  # lr_native = documented beam footprint
        hr_nat = float(r["hr_native_res_m"]) if str(r["hr_native_res_m"]) not in ("", "nan") else 1.0
        rows.append({"pair_id": pid, "lr_cruise": cruise, "sonar": son, "beamwidth_deg": bw,
                     "depth_m": depth, "documented_footprint_m": footprint, "grid_posting_m": posting,
                     "grid_file": gfile, "recorded_lr_native_m": recorded, "case": case,
                     "proposed_lr_native_m": corrected,
                     "proposed_res_ratio": round(corrected / hr_nat, 2) if (corrected and hr_nat) else None,
                     "recorded_vs_proposed_x": round(max(recorded / corrected, corrected / recorded), 2) if (corrected and recorded) else None})
    from collections import Counter
    cc = Counter(r["case"].split("_")[0] if r["case"] else "?" for r in rows)
    out = {"n_new_pairs": len(rows), "case_counts": dict(cc), "pairs": rows}
    OUT.write_text(json.dumps(out, indent=2, default=str))
    log.info("=== C2a documented-native (new pairs) ===")
    log.info(f"{'pair_id':28s} {'sonar':22s} {'bw':4s} {'fp_m':6s} {'post':6s} {'rec':7s} {'->lrnat':7s} {'case'}")
    for r in rows:
        log.info(f"{r['pair_id']:28s} {str(r['sonar'])[:22]:22s} {r['beamwidth_deg']:<4} {str(r['documented_footprint_m']):6s} {str(r['grid_posting_m']):6s} {str(r['recorded_lr_native_m']):7s} {str(r['proposed_lr_native_m']):7s} {r['case']}")
    log.info("CASE COUNTS: %s", dict(cc))
    log.info("wrote %s", OUT)


if __name__ == "__main__":
    main()
