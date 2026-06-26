"""R5 — validated-21 spot-check through the corrected reader (read-only, OAK).

The reader question is reopened, so re-confirm the 21 calibration-anchor pairs:
band structure (are any multi-band RGB like the 9 new visualization pairs?),
corrected-reader p50, and out-of-bounds cell counts. Read-only; not modified.
"""
from __future__ import annotations
import json, logging
from pathlib import Path
import numpy as np
import rasterio

log = logging.getLogger("r5")
REPO = Path(__file__).resolve().parents[2]
OAK = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy/harmonized")
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/harmonized")
OUT = REPO / "reports/discovery/stage_reaudit_r5_validated21.json"

VALIDATED = [
    "discol_so242_1", "ccz_so268_1", "tag_m127",
] + [f"cal_dig_morro_bay/{s}" for s in [
    "20180426m2_Channel1000", "20180427m1_Channel700", "20180427m3_PockmarkNorth",
    "20180428m1_Cable", "201804_LuciaChica2m", "20190314m4_LuciaChica970m",
    "20190315m1_HeadlessCanyon", "20190316m1_BankTop", "20190317m1_1000mGully",
    "20190317m2_600mGully", "20190318m2_Transect601060m", "20190510m1_BankFlankHoles",
    "20190510m2_BankFlankIncipCh", "20190511m1_6thHeadlessCany",
    "20190511m2_BankTopEofCanyon3", "basin_flank", "luciachica_2007", "pockmark_south"]]


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out = []
    for name in VALIDATED:
        p = OAK / name / "hr.tif"
        if not p.exists():
            p = DATA / name / "hr.tif"
        rec = {"pair": name, "path": str(p)}
        try:
            with rasterio.open(str(p)) as ds:
                rec["count"] = ds.count
                rec["dtypes"] = list(ds.dtypes)
                rec["colorinterp"] = [c.name for c in ds.colorinterp]
                rec["nodata"] = ds.nodata
                dec = max(1, int(((ds.width*ds.height)/2e6)**0.5))
                a = ds.read(1, out_shape=(max(1, ds.height//dec), max(1, ds.width//dec))).astype("float64")
                nd = ds.nodata
                if nd is not None:
                    a = np.where(np.isclose(a, nd, atol=1e-3), np.nan, a)
            v = a[np.isfinite(a)]
            rec["is_multiband_rgb"] = bool(ds.count >= 3 and all(d == "uint8" for d in ds.dtypes))
            if v.size:
                rec["p50"] = round(float(np.percentile(v, 50)), 2)
                rec["min"] = round(float(v.min()), 2)
                rec["max"] = round(float(v.max()), 2)
                rec["n_positive"] = int((v > 50).sum())
                rec["n_lt_-8000"] = int((v < -8000).sum())
        except Exception as e:
            rec["error"] = str(e)[:150]
        log.info("[%s] count=%s dt=%s rgb=%s p50=%s pos=%s", name, rec.get("count"),
                 (rec.get("dtypes") or [""])[0], rec.get("is_multiband_rgb"),
                 rec.get("p50"), rec.get("n_positive"))
        out.append(rec)
    OUT.write_text(json.dumps(out, indent=2, default=str))
    n_rgb = sum(1 for r in out if r.get("is_multiband_rgb"))
    log.info("RGB among 21: %d ; wrote %s", n_rgb, OUT)


if __name__ == "__main__":
    main()
