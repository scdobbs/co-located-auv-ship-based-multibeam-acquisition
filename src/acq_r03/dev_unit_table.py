"""ACQ-R03 §6.5 — development-unit table from manifest v2.1: per unit the pairs, tiles at >= 50 % joint validity,
k (or no-k), products availability / usability, v2.1 flags, basin and setting; counts of usable units and pairs
(excluding no-k pairs), with and without usable ship channels.  Output: reports_post_grl_review/ACQ-R03/dev_unit_table.{md,csv,json}
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from src.acq_r01 import common as C
from src.acq_r03 import common as R


def tiles_for(pid: str, row, vt: pd.DataFrame) -> int | None:
    if pid in vt.index:
        return int(vt.loc[pid])
    for d in (R.REPORT_DIR / "harmonize", R.R02 / "harmonize"):
        for name in (f"{pid}_lrv2_1_r5.json", f"{pid}.json"):
            p = d / name
            if p.exists():
                rec = json.loads(p.read_text())
                if "n_valid_tiles_256" in rec:
                    return int(rec["n_valid_tiles_256"])
    return None


def main():
    m = pd.read_parquet(C.REPO / "manifest" / "pairs_v2_1.parquet")
    v = pd.read_parquet(C.OAK / "manifest" / "valid_tiles.parquet")
    vt = (v.joint_valid_fraction >= 0.5).groupby(v.pair_id).sum()
    dev = m[m.designation.astype(str).str.startswith("development")].copy()
    rows = []
    for _, r in dev.iterrows():
        k = r.get("max_recoverable_k"); nok = k is None or (isinstance(k, float) and np.isnan(k))
        pj = C.OAK / str(r.harmonized_path) / "ship_products_v2_1" / "products.json"
        avail = False
        if pj.exists():
            avail = all(json.loads(pj.read_text())["available"].values())
        rows.append({"unit": r.leakage_unit, "pair_id": r.pair_id, "tiles_ge50": tiles_for(r.pair_id, r, vt), "k": None if nok else int(k), "no_k": bool(nok),
                     "qa": r.get("qa_status"), "products_available": avail, "ship_products_usable": bool(r.ship_products_usable) if r.ship_products_usable is not None and not (isinstance(r.ship_products_usable, float) and np.isnan(r.ship_products_usable)) else False,
                     "v2_1_flags": r.get("products_v2_1_flags") or "", "basin": r.get("region"), "setting": r.get("terrain_class"), "ruling": r.get("ruling_source") or ""})
    t = pd.DataFrame(rows).sort_values(["unit", "pair_id"])
    t.to_csv(R.REPORT_DIR / "dev_unit_table_pairs.csv", index=False)
    units = []
    for u, g in t.groupby("unit"):
        usable_pairs = g[~g.no_k]
        units.append({"unit": u, "n_pairs": int(len(g)), "pairs": "; ".join(g.pair_id), "tiles_ge50": int(g.tiles_ge50.fillna(0).sum()),
                      "k": "; ".join(("no-k" if r.no_k else str(r.k)) for r in g.itertuples()),
                      "n_usable_pairs (with k)": int(len(usable_pairs)), "products_available": f"{int(g.products_available.sum())}/{len(g)}",
                      "ship_products_usable": f"{int(g.ship_products_usable.sum())}/{len(g)}", "v2_1_flags": "; ".join(f or "—" for f in g.v2_1_flags),
                      "basin": g.basin.iloc[0], "setting": g.setting.iloc[0], "unit_usable": bool(len(usable_pairs) > 0),
                      "unit_usable_with_ship_channels": bool((usable_pairs.ship_products_usable).any())})
    U = pd.DataFrame(units)
    U.to_csv(R.REPORT_DIR / "dev_unit_table.csv", index=False)
    counts = {"development_units": int(len(U)), "development_pairs": int(len(t)), "usable_units (>=1 pair with k)": int(U.unit_usable.sum()),
              "usable_pairs (with k)": int((~t.no_k).sum()), "no_k_pairs": int(t.no_k.sum()),
              "usable_units_with_usable_ship_channels": int(U.unit_usable_with_ship_channels.sum()),
              "usable_pairs_with_usable_ship_channels": int(((~t.no_k) & t.ship_products_usable).sum()),
              "pairs_with_products_available": int(t.products_available.sum()), "pairs_with_usable_products": int(t.ship_products_usable.sum())}
    md = ["| unit | pairs | tiles ≥50 % | k | usable pairs (k) | products available | ship products usable | v2.1 flags | basin | setting |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in U.itertuples():
        md.append(f"| {r.unit} | {r.pairs} | {r.tiles_ge50:,} | {r.k} | {r._6} | {r.products_available} | {r.ship_products_usable} | {r.v2_1_flags} | {r.basin} | {r.setting} |")
    md += ["", "**Counts:** " + "; ".join(f"{k} = {v}" for k, v in counts.items())]
    (R.REPORT_DIR / "dev_unit_table.md").write_text("\n".join(md) + "\n")
    R.write_json(R.REPORT_DIR / "dev_unit_table.json", {"units": units, "counts": counts, "generated": R.utc_now()})
    print("\n".join(md)); return 0


if __name__ == "__main__":
    sys.exit(main())
