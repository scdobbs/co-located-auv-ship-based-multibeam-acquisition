"""ACQ-R04 — pilot before/after the gridding-representation change (steering ruling 2026-10-03).

before = pilot v0, direct-UTM mbgrid (block dirs preserved in pretrain_v1_stage_pilot_v0_directutm/, run records in
pretrain_v1_logs_pilot_v0_directutm/); after = dev_chain (stage-C geographic mbgrid + stage-F bilinear warp to UTM,
pretrain_v1_stage/ and pretrain_v1_logs/).  Per cruise and overall: blocks total / kept / by status, products usable,
flag counts, nominal cell (2 d tan(bw/2)) and realised grid cell (grid.tif pixel size), fill.
Writes pilot_compare.csv (per cruise x version), pilot_compare_blocks.csv (per block x version), pilot_compare.json.
Usage: python -m src.acq_r04.pilot_compare
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from src.acq_r04 import common as R
from src.acq_r04.blocks import cdir_name

V = {"before_direct_utm": (R.SCR / "pretrain_v1_stage_pilot_v0_directutm", R.SCR / "pretrain_v1_logs_pilot_v0_directutm"),
     "after_dev_chain": (R.STAGE, R.WORK_LOGS)}


def main():
    cruises = (R.REPORT_DIR / "pilot_cruises.txt").read_text().split()
    rows, brows = [], []
    for ver, (stage, logs) in V.items():
        for c in cruises:
            cd = cdir_name(c)
            rec = json.loads((logs / cd / "cruise_record.json").read_text())
            bl = []
            for bj in sorted((stage / cd).glob("*/block.json")):
                b = json.loads(bj.read_text()); p = b.get("products", {})
                pj = bj.parent / "ship_products_v2_1" / "products.json"
                qa = (json.loads(pj.read_text()).get("qa_vs_lr_tif") or {}) if pj.exists() else {}
                bl.append({"version": ver, "cruise": c, "block": b["block"], "median_depth_m": b["median_depth_m"], "cell_nominal_m": b["cell_m"],
                           "cell_grid_m": b["cell_m_actual"][0], "fill": b["fill"], "usable": bool(p.get("usable")),
                           "flags": ";".join(p.get("flags") or []), "qa_median_offset_m": qa.get("median_offset_m"),
                           "qa_robust_sigma_m": qa.get("robust_sigma_m")})
            brows += bl
            d = pd.DataFrame(bl)
            st = rec.get("block_status", {})
            rows.append({"version": ver, "cruise": c, "family": rec["family"], "blocks_total": rec["blocks_total"], "kept": rec["blocks_kept"],
                         "drop_fill": st.get("drop_fill", 0), "drop_depth": st.get("drop_depth", 0), "drop_guard": st.get("drop_exclusion_guard", 0),
                         "fail_mbgrid": st.get("fail_mbgrid", 0), "usable": int(d.usable.sum()) if len(d) else 0,
                         "vertical_offset": int(d.flags.str.contains("vertical_offset").sum()) if len(d) else 0,
                         "registration_shift": int(d.flags.str.contains("registration_shift").sum()) if len(d) else 0,
                         "cell_grid_min_m": d.cell_grid_m.min() if len(d) else np.nan, "cell_grid_median_m": d.cell_grid_m.median() if len(d) else np.nan,
                         "cell_grid_max_m": d.cell_grid_m.max() if len(d) else np.nan, "fill_median": d.fill.median() if len(d) else np.nan,
                         "wall_s": rec.get("wall_s"), "failures": len(rec.get("failures", []))})
    df = pd.DataFrame(rows); B = pd.DataFrame(brows)
    df.to_csv(R.REPORT_DIR / "pilot_compare.csv", index=False); B.to_csv(R.REPORT_DIR / "pilot_compare_blocks.csv", index=False)
    tot = {}
    for ver in V:
        d = df[df.version == ver]; b = B[B.version == ver]
        tot[ver] = {"blocks_total": int(d.blocks_total.sum()), "kept": int(d.kept.sum()), "drop_fill": int(d.drop_fill.sum()),
                    "drop_depth": int(d.drop_depth.sum()), "fail_mbgrid": int(d.fail_mbgrid.sum()), "usable": int(d.usable.sum()),
                    "vertical_offset": int(d.vertical_offset.sum()), "registration_shift": int(d.registration_shift.sum()),
                    "cell_nominal_min_median_max_m": [float(b.cell_nominal_m.min()), float(b.cell_nominal_m.median()), float(b.cell_nominal_m.max())],
                    "cell_grid_min_median_max_m": [float(b.cell_grid_m.min()), float(b.cell_grid_m.median()), float(b.cell_grid_m.max())],
                    "fill_median": float(b.fill.median()), "wall_s": float(d.wall_s.sum()), "failures": int(d.failures.sum())}
    both = B.pivot_table(index=["cruise", "block"], columns="version", values="cell_grid_m").dropna()
    tot["blocks_kept_in_both"] = int(len(both))
    tot["cell_grid_ratio_after_over_before_median"] = float((both["after_dev_chain"] / both["before_direct_utm"]).median()) if len(both) else None
    R.write_json(R.REPORT_DIR / "pilot_compare.json", {"generated": R.utc_now(), "totals": tot})
    print(df.to_string()); print(json.dumps(tot, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
