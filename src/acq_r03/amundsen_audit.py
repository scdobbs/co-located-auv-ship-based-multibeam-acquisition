"""ACQ-R03 §4 — Amundsen `lr_native` audit (unit lu18): 2009_Amundsen__MGDS_30046 (June, 16 m) vs
2009_Amundsen__MGDS_30047 (ACQ-R02, gridded at 2.91 m).  For each pair: the median depth under its HR, the
documented-beam-footprint value, the gridding cell actually used and where it came from, and the C2a
lr_native = max(footprint, posting).  Reads records only; nothing is regridded or modified.
Output: reports_post_grl_review/ACQ-R03/amundsen_lr_native_audit.{json,md}
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
import pandas as pd
import rasterio

from src.acq_r03 import common as R

BW = 1.0   # Kongsberg EM302 documented beam width (deg), the value both records use


def fp(depth):
    return 2 * abs(depth) * math.tan(math.radians(BW / 2))


def hr_median_over_joint(pdir):
    with rasterio.open(pdir / "hr.tif") as h, rasterio.open(pdir / "joint_valid.tif") as j:
        hr = h.read(1, masked=True).filled(np.nan); jv = j.read(1) == 1
    v = hr[jv & np.isfinite(hr)]
    return float(np.median(v)) if v.size else None


def main():
    m = pd.read_parquet(R.C.REPO / "manifest" / "pairs_v2.parquet").set_index("pair_id")
    rep = R.C.REPO / "reports"
    c2a = json.loads((rep / "discovery" / "stage_c2a_documented_native.json").read_text())
    c2a_row = next(p for p in c2a["pairs"] if p["pair_id"] == "2009_Amundsen__MGDS_30046")
    apply_row = next(c for c in json.loads((rep / "discovery" / "stage_c2a_apply_result.json").read_text())["changes"] if c["pair_id"] == "2009_Amundsen__MGDS_30046")
    pilot = next(p for p in json.loads((rep / "discovery" / "stage_c_pilot_measurements.json").read_text()) if p.get("cruise") == "2009_Amundsen" and p.get("hr_id") == "MGDS:30045")
    state = json.loads((rep / "discovery" / "staging_state_20260605.json").read_text())
    grid47 = json.loads((R.R02 / "grid" / "2009_Amundsen.json").read_text())
    harm47 = json.loads((R.R02 / "harmonize" / "2009_Amundsen__MGDS_30047.json").read_text())
    p46 = R.OAK / str(m.loc["2009_Amundsen__MGDS_30046", "harmonized_path"]); p47 = R.OAK / str(m.loc["2009_Amundsen__MGDS_30047", "harmonized_path"])
    d46 = hr_median_over_joint(p46); d47 = hr_median_over_joint(p47)
    with rasterio.open(p46 / "lr.tif") as ds:
        post46 = abs(ds.res[0])
    with rasterio.open(p47 / "lr.tif") as ds:
        post47 = abs(ds.res[0])
    out = {"generated": R.utc_now(), "rule": "C2a: lr_native = max(documented beam footprint 2·depth·tan(bw/2), grid posting); stage C cell = footprint at the median depth of the soundings inside the HR footprint bbox", "beamwidth_deg": BW,
           "pairs": {
               "2009_Amundsen__MGDS_30046": {
                   "median_depth_under_hr_m": {"hr_median_over_joint_now": round(d46, 1), "june_record_depth_m": c2a_row["depth_m"], "june_hr_p50_over_joint": -238.8},
                   "documented_footprint_m": {"at_june_record_depth": round(fp(c2a_row["depth_m"]), 2), "june_record_value": c2a_row["documented_footprint_m"]},
                   "gridding_cell_used_m": {"value": c2a_row["grid_posting_m"], "lr_tif_posting_now": round(post46, 2), "grid_file": c2a_row["grid_file"],
                                            "origin": f"June stage-C pilot grid for HR MGDS:30045 (stage_c_pilot_measurements.json): est_cell 15.98 m = 2·depth·tan(0.5°) at the MEDIAN DEPTH OF THE MGDS:30045 FOOTPRINT BBOX, {pilot['median_depth_m']} m (grid depth range {pilot['grid_depth_min']}..{pilot['grid_depth_max']} m); the 30046 pair (C1 phase 1, 2026-06-26) was harmonized against that existing grid, not regridded at its own footprint depth"},
                   "lr_native_c2a_m": {"recorded": float(m.loc["2009_Amundsen__MGDS_30046", "lr_native_res_m"]), "rule_eval": f"max({c2a_row['documented_footprint_m']}, {c2a_row['grid_posting_m']}) = {apply_row['new_lr']}",
                                       "june_case": c2a_row["case"], "june_note": state["stage_c2a_documented_native"]["caseB_amundsen"]}},
               "2009_Amundsen__MGDS_30047": {
                   "median_depth_under_hr_m": {"hr_median_over_joint_now": round(d47, 1), "acq_r02_hr_p50_over_joint": harm47["hr_p50_over_joint_m"],
                                               "grid_footprint_depth_m (soundings in HR bbox)": grid47["footprint_depth_m"], "harmonized_lr_median_depth_used_for_lr_native": round(harm47["lr_native"]["beam_footprint_m"] / (2 * math.tan(math.radians(BW / 2))), 1)},
                   "documented_footprint_m": {"at_grid_footprint_depth": round(fp(grid47["footprint_depth_m"]), 2), "at_harmonized_lr_median_depth (used)": harm47["lr_native"]["beam_footprint_m"], "at_hr_median_over_joint": round(fp(d47), 2)},
                   "gridding_cell_used_m": {"value": grid47["cell_m"], "lr_tif_posting_now": round(post47, 2), "origin": "ACQ-R02 grid_lr.py: 2·depth·tan(0.5°) at the median depth of the soundings inside the MGDS:30047 footprint bbox (grid/2009_Amundsen.json footprint_depth_m); region = LR-seeded 5 km patch cluster"},
                   "lr_native_c2a_m": {"recorded": float(m.loc["2009_Amundsen__MGDS_30047", "lr_native_res_m"]), "rule_eval": f"max({harm47['lr_native']['beam_footprint_m']}, {harm47['lr_native']['posting_m']}) = {harm47['lr_native']['lr_native_m']}", "record": harm47["lr_native"]}}}}
    same_rule = "Both pairs record lr_native = max(footprint, posting) (C2a)."
    dev = ("The difference (16 m vs 4.87 m) is NOT explained by depth: both HR sit at 220–240 m (footprints 3.9–4.2 m). "
           "30046's posting (16 m) comes from a grid whose cell was set by the 915 m median depth of the MGDS:30045 footprint bbox, i.e. the stage-C cell rule applied to a different, deeper HR; "
           "the pair was never gridded at its own footprint depth (Steve's June C2a case-B ruling: lr_native = 16 m posting, no regrid). "
           "30047's posting (2.91 m) follows the standard rule at its own footprint depth (166.8 m), and its lr_native (4.87 m) uses the footprint at the harmonized-LR median depth (279 m), not the HR median (223 m) or the grid depth (167 m): a third depth definition inside one pair.")
    out["verdict"] = {"same_rule": same_rule, "explained_by_depth": False, "deviation": dev,
                      "hold": "HOLD H-A (§4): 2009_Amundsen__MGDS_30046's 16 m posting deviates from the standard stage-C cell (its own-footprint cell would be ≈ 4.2 m); the two lu18 pairs therefore carry lr_native 16 m and 4.87 m over the same shelf at the same depth. Steve's call: keep the June ruling (16 m, no regrid) or regrid 30046 at its own footprint depth in a later directive. Nothing modified here."}
    R.write_json(R.REPORT_DIR / "amundsen_lr_native_audit.json", out)
    a, b = out["pairs"]["2009_Amundsen__MGDS_30046"], out["pairs"]["2009_Amundsen__MGDS_30047"]
    md = ["# ACQ-R03 §4 — Amundsen lr_native audit (lu18)", "", "| item | 2009_Amundsen__MGDS_30046 (June) | 2009_Amundsen__MGDS_30047 (ACQ-R02) |", "|---|---|---|",
          f"| median depth under HR (joint cells, now) | {a['median_depth_under_hr_m']['hr_median_over_joint_now']} m (June record 238.8 m) | {b['median_depth_under_hr_m']['hr_median_over_joint_now']} m (grid footprint depth {grid47['footprint_depth_m']} m; harmonized-LR median used for lr_native 279 m) |",
          f"| documented beam footprint (EM302, 1°) | {a['documented_footprint_m']['june_record_value']} m at 238.8 m | {b['documented_footprint_m']['at_grid_footprint_depth']} m at 166.8 m; {harm47['lr_native']['beam_footprint_m']} m at 279 m (used); {b['documented_footprint_m']['at_hr_median_over_joint']} m at the HR median |",
          f"| gridding cell used | {a['gridding_cell_used_m']['value']} m — June pilot grid `2009_Amundsen__MGDS_30045.grd`, cell = footprint at the 915.5 m median depth of the MGDS:30045 footprint bbox; 30046 harmonized against it (C1 phase 1) | {grid47['cell_m']} m — `grid/2009_Amundsen.json`, footprint at 166.8 m (soundings in the 30047 bbox) |",
          f"| C2a lr_native = max(footprint, posting) | max(4.2, 16.0) = 16.0 m (case B_regrid; June ruling: keep posting, no regrid) | max(4.87, 2.92) = 4.87 m |",
          "", f"**Verdict.** {same_rule} {dev}", "", f"**{out['verdict']['hold']}**"]
    (R.REPORT_DIR / "amundsen_lr_native_audit.md").write_text("\n".join(md) + "\n")
    print("\n".join(md)); return 0


if __name__ == "__main__":
    sys.exit(main())
