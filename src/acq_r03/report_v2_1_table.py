"""ACQ-R03 §2.7 — v2.1 flag table next to the v2 flags, for every pair with ship products.
Output: reports_post_grl_review/ACQ-R03/v2_1_flag_table.{md,csv}
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from src.acq_r01 import common as C
from src.acq_r03 import common as R


def main():
    m = pd.read_parquet(C.REPO / "manifest" / "pairs_v2.parquet").set_index("pair_id")
    new = (R.R02 / "new_dev_pairs.txt").read_text().strip().split(",")
    rows = []
    for pid in list(C.PAIRS_IN_SCOPE) + new:
        pdir = R.OAK / str(m.loc[pid, "harmonized_path"])
        p2 = pdir / "ship_products_v2" / "products.json"; p21 = pdir / "ship_products_v2_1" / "products.json"
        if not p2.exists():
            continue
        j2 = json.loads(p2.read_text()); j21 = json.loads(p21.read_text()) if p21.exists() else None
        if not all(j2["available"].values()):
            continue
        q2 = j2["qa_vs_lr_tif"]; q21 = (j21 or {}).get("qa_vs_lr_tif") or {}
        fo = (j21 or {}).get("frame_offset") or {}
        rows.append({"pair_id": pid, "unit": m.loc[pid, "leakage_unit"], "designation": m.loc[pid, "designation"], "n_common": q2["n_common_cells"],
                     "median_offset_m": q2["median_offset_m"], "v2_argmin": str(q2["shift_argmin_cells"]), "v2_flags": ",".join(q2["flags"]) or "—",
                     "v2_1_built": j21 is not None, "frame_offset": ("applied" if fo.get("applied") else "none") if j21 else "",
                     "v2_1_argmin": str(q21.get("shift_argmin_cells", "")), "sigma0_m": q21.get("sigma0_m"), "sigma_argmin_m": q21.get("sigma_argmin_m"), "gain_m": q21.get("gain_m"),
                     "gate_min_gain_m": (q21.get("registration_gate") or {}).get("min_gain_m"), "v2_1_flags": (",".join(q21.get("flags", [])) or "—") if j21 else ""})
    df = pd.DataFrame(rows); df.to_csv(R.REPORT_DIR / "v2_1_flag_table.csv", index=False)
    md = ["| pair | unit | n common | median off m | v2 argmin | v2 flags | v2.1 argmin | σ0 m | σ argmin m | gain m | gate gain m | frame offset | v2.1 flags |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['pair_id']} | {r['unit']} | {r['n_common']:,} | {r['median_offset_m']} | {r['v2_argmin']} | {r['v2_flags']} | {r['v2_1_argmin']} | {r['sigma0_m']} | {r['sigma_argmin_m']} | {r['gain_m']} | {r['gate_min_gain_m']} | {r['frame_offset']} | {r['v2_1_flags']} |")
    n2 = {f: sum(1 for r in rows if f in r["v2_flags"]) for f in ("registration_shift", "vertical_offset", "insufficient_overlap")}
    n21 = {f: sum(1 for r in rows if f in r["v2_1_flags"]) for f in ("registration_shift", "vertical_offset", "insufficient_overlap")}
    md += ["", f"Pairs with products: {len(rows)}; built v2.1: {sum(1 for r in rows if r['v2_1_built'])}. Flag counts v2 → v2.1: registration_shift {n2['registration_shift']} → {n21['registration_shift']}, vertical_offset {n2['vertical_offset']} → {n21['vertical_offset']}, insufficient_overlap {n2['insufficient_overlap']} → {n21['insufficient_overlap']}; unflagged {sum(1 for r in rows if r['v2_flags'] == '—')} → {sum(1 for r in rows if r['v2_1_flags'] == '—')}."]
    (R.REPORT_DIR / "v2_1_flag_table.md").write_text("\n".join(md) + "\n"); print("\n".join(md)); return 0


if __name__ == "__main__":
    sys.exit(main())
