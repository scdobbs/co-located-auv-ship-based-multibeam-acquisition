"""C2 refine — measure native res from the ORIGINAL LR grid posting (true native,
pre-reprojection) for the flagged pairs, to resolve the harmonized-lr.tif proxy's
reprojection-coarsening ambiguity. Validated-21 use documented source res.
"""
from __future__ import annotations
import json, logging, math
from pathlib import Path
import numpy as np
import rasterio
import pandas as pd

log = logging.getLogger("c2r")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
GRID = DATA / "raw_lr_gridded"
HARM = DATA / "harmonized"
CANON = REPO / "manifest/pairs.parquet"
OUT = REPO / "reports/discovery/stage_c2_refine.json"

# flagged pair -> original LR grid actually used
FLAGGED_LR = {
    "TN159__MGDS_21981": "TN159__union.grd", "RR1506__MGDS_29779": "RR1506__union.grd",
    "TN399__MGDS_30373": "TN399__union.grd", "TN268__MGDS_30466": "TN268__union.grd",
    "NA090__MGDS_31212": "NA090__union.grd", "EW9801__MGDS_31425": "EW9801__union.grd",
    "2009_Amundsen__MGDS_30046": "2009_Amundsen__MGDS_30045.grd", "AT37-13__MGDS_31199": "AT37-13__union.grd",
    "TN299__MGDS_27339": "TN299__MGDS_27339.grd", "NA080__MGDS_31290": "NA080__union.grd",
}


def grid_native(path):
    for c in (str(path), "NETCDF:" + str(path)):
        try:
            ds = rasterio.open(c)
        except Exception:
            continue
        res = abs(ds.res[0]); crs = ds.crs
        b = ds.bounds
        a = ds.read(1, masked=True).filled(np.nan).astype("float64")
        nd = ds.nodata
        ds.close()
        if crs and crs.is_geographic:
            lat = (b.bottom + b.top) / 2
            postm = res * 111320 * math.cos(math.radians(lat))
        else:
            postm = res
        fin = np.isfinite(a)
        if nd is not None:
            fin &= ~np.isclose(a, nd, atol=1e-3)
        fill = float(fin.mean()) if a.size else 0.0
        return {"posting_m": round(float(postm), 1), "fill": round(fill, 3),
                "native_sqrt_fill_m": round(float(postm) / max(0.05, fill) ** 0.5, 1)}
    return None


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    m = pd.read_parquet(CANON)
    rec = {r["pair_id"]: r for r in m.to_dict("records")}
    out = {"flagged_refined": [], "note": "measured from ORIGINAL LR grid posting (pre-reprojection true native)"}
    for pid, gfile in FLAGGED_LR.items():
        g = grid_native(GRID / gfile)
        recorded = float(rec[pid]["lr_native_res_m"])
        depth = abs(float(rec[pid]["depth_max_m"]))
        est = round(2 * depth * math.tan(math.radians(0.5)), 1)
        r = {"pair_id": pid, "lr_grid": gfile, "recorded": recorded,
             "beam_estimate_m": est, **(g or {"err": "unreadable"})}
        truem = (g or {}).get("native_sqrt_fill_m")
        if truem:
            ratio = round(max(recorded / truem, truem / recorded), 2)
            r["recorded_vs_originalgrid_x"] = ratio
            r["still_flagged"] = bool(ratio > 1.8)
            r["proposed_lr_native_res_m"] = truem
            r["proposed_res_ratio"] = round(truem / float(rec[pid]["hr_native_res_m"]), 2)
        out["flagged_refined"].append(r)
        log.info("%-26s recorded=%s posting=%s native(sqrtfill)=%s est=%s -> x%s flagged=%s",
                 pid, recorded, (g or {}).get("posting_m"), truem, est, r.get("recorded_vs_originalgrid_x"), r.get("still_flagged"))
    OUT.write_text(json.dumps(out, indent=2, default=str))
    log.info("still flagged after original-grid refine: %d/10",
             sum(1 for r in out["flagged_refined"] if r.get("still_flagged")))
    log.info("wrote %s", OUT)


if __name__ == "__main__":
    main()
