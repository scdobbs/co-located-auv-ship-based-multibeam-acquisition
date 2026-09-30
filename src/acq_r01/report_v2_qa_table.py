"""ACQ-R02 §2.6 — per-pair v2 QA table for the report (from products.json + qa_shift_surface.csv),
including the shift-surface gain sigma(0,0) - sigma(argmin) so a reader can judge a 0.25-cell argmin.
Output: reports_post_grl_review/ACQ-R02/v2_qa_table.{md,csv}
"""
from __future__ import annotations

import csv
import json
import sys

import pandas as pd

from src.acq_r01 import common as C

R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"


def main():
    m = C.load_manifest(); rows = []
    for _, r in m[m.pair_id.isin(C.PAIRS_IN_SCOPE)].iterrows():
        d = C.pair_dir_oak(r) / "ship_products_v2"; pj = d / "products.json"
        if not pj.exists():
            rows.append({"pair_id": r.pair_id, "unit": C.UNIT_OF.get(r.pair_id), "available": None, "note": "missing"}); continue
        p = json.loads(pj.read_text()); q = p.get("qa_vs_lr_tif") or {}
        rec = {"pair_id": r.pair_id, "unit": C.UNIT_OF.get(r.pair_id), "available": all(p["available"].values())}
        if not rec["available"]:
            rec["note"] = (p.get("unavailable_reason") or "")[:60]; rows.append(rec); continue
        gain = None
        sp = d / (q.get("shift_surface_file") or "qa_shift_surface.csv")
        if sp.exists():
            with sp.open() as f:
                surf = {(float(x["dx_cells"]), float(x["dy_cells"])): float(x["robust_sigma_m"]) for x in csv.DictReader(f)}
            am = tuple(q.get("shift_argmin_cells") or (0.0, 0.0))
            if (0.0, 0.0) in surf and am in surf:
                gain = round(surf[(0.0, 0.0)] - surf[am], 4)
        ex = d / "products_extra.json"; e = json.loads(ex.read_text()) if ex.exists() else {}
        rec.update({"n_common": q.get("n_common_cells"), "median_offset_m": q.get("median_offset_m"), "robust_sigma_m": q.get("robust_sigma_m"),
                    "robust_sigma_over_s_lr": q.get("robust_sigma_over_median_s_lr"), "rms_m": q.get("rms_m"), "argmin": q.get("shift_argmin_cells"),
                    "sigma_gain_at_argmin_m": gain, "qa_flags": ",".join(q.get("flags") or []) or "—", "median_rsd_over_sd": e.get("median_rsd_over_sd"),
                    "control_vs_v1": ";".join(f"{k}:{v}" for k, v in (e.get("control_vs_v1") or {}).items()), "beam_angle": p.get("beam_angle_method")})
        rows.append(rec)
    df = pd.DataFrame(rows); df.to_csv(R02 / "v2_qa_table.csv", index=False)
    md = ["| pair | unit | n common | median off m | robust σ m | robust σ / s_lr | RMS m | argmin (dx,dy) cells | σ gain at argmin m | flags | median rsd/sd | v1 control |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        if r.get("available") is False:
            md.append(f"| {r.pair_id} | {r.unit} | available: false ({r.get('note', '')}) | | | | | | | | | |"); continue
        ctrl = "equal" if r.get("control_vs_v1") and all(v.endswith(":equal") for v in str(r.control_vs_v1).split(";")) else r.get("control_vs_v1")
        md.append(f"| {r.pair_id} | {r.unit} | {r.n_common} | {r.median_offset_m} | {r.robust_sigma_m} | {r.robust_sigma_over_s_lr} | {r.rms_m} | {r.argmin} | {r.sigma_gain_at_argmin_m} | {r.qa_flags} | {r.median_rsd_over_sd} | {ctrl} |")
    (R02 / "v2_qa_table.md").write_text("\n".join(md)); print("\n".join(md))
    av = df[df.available == True]
    print("\nflag counts:", av.qa_flags.str.split(",").explode().value_counts().to_dict(), "| pairs with no flag:", int((av.qa_flags == "—").sum()), "of", len(av))
    return 0


if __name__ == "__main__":
    sys.exit(main())
