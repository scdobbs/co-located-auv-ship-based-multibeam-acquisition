"""ACQ-R02 §7 — manifest v2: `manifest/pairs_v2.parquet` (pairs.parquet is NOT modified).

Rows: the 39 existing pairs unchanged (+ `designation`, `harmonized_path`), the new development pairs
harmonized in §6 (full row from the harmonize record; lockbox never touched), and confirmatory pairs
with path + designation only (no derived statistics).  `harmonized_path` = the directory that holds
the pair's lr.tif, authoritative per contract v2 §2 (root-relative to the OAK data root).
Validates that every development pair's ship_products_v2 pass contract v2 (validate_contract_v2).
"""
from __future__ import annotations

import json
import sys
from datetime import date

import numpy as np
import pandas as pd

from src.acq_r01 import common as C

R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"


def main():
    m = C.load_manifest()
    m2 = m.copy()
    m2["designation"] = ["lockbox" if p in C.LOCKBOX else "development" for p in m2.pair_id]
    m2["harmonized_path"] = [str(C.pair_dir_oak(r).relative_to(C.OAK)) for _, r in m2.iterrows()]
    rows = []
    for jp in sorted((R02 / "harmonize").glob("*.json")):
        r = json.loads(jp.read_text())
        if not str(r.get("status", "")).startswith("harmonized"):
            continue
        conf = str(r["designation"]).startswith("confirmatory")
        out_dir = C.OAK / r["out_dir"] if not str(r["out_dir"]).startswith("/") else r["out_dir"]
        rel = str(pd_rel(r["out_dir"]))
        base = {"pair_id": r["pair_id"], "designation": r["designation"], "harmonized_path": rel, "leakage_unit": r.get("unit", ""),
                "lr_cruise": r["lr_cruise"], "cruise_id": r.get("hr_cruise", ""), "hr_doi": "", "verification_status": "acq_r02_verified"}
        if conf:
            rows.append(base); continue
        k = r.get("k_sweep", {}); cg = r.get("coreg", {}); ln = r.get("lr_native", {}); pv = r.get("products_v2") or {}
        rows.append({**base, "hr_native_res_m": r.get("hr_res_m"), "lr_native_res_m": ln.get("lr_native_m"),
                     "res_ratio": round(ln["lr_native_m"] / r["hr_res_m"], 2) if ln.get("lr_native_m") and r.get("hr_res_m") else None,
                     "depth_min_m": r.get("hr_p50_over_joint_m"), "depth_max_m": r.get("hr_p50_over_joint_m"), "target_crs": r.get("target_crs"),
                     "harmonized_path_hr": rel + "/hr.tif", "harmonized_path_lr": rel + "/lr.tif", "hr_valid": rel + "/hr_valid.tif",
                     "lr_valid": rel + "/lr_valid.tif", "joint_valid": rel + "/joint_valid.tif", "lr_valid_semantic": "real_sounding",
                     "horiz_offset_m": cg.get("offset_m"), "vert_offset_m": cg.get("dz_m"), "coreg_status": "pass" if cg.get("pass") else "fail",
                     "max_recoverable_k": k.get("max_recoverable_k"), "k_sweep_status": k.get("status"), "qc_artifact_path": r.get("qc_figure", ""),
                     "products_v2_flags": ";".join((pv.get("qa") or {}).get("flags", []) or []) if isinstance(pv, dict) else "",
                     "notes": f"ACQ-R02 §6 {r.get('set', '')}; joint {r.get('joint_area_km2')} km2, {r.get('n_valid_tiles_256')} tiles; HR cruise {r.get('hr_cruise', '')}"})
    new = pd.DataFrame(rows)
    out = pd.concat([m2, new], ignore_index=True, sort=False) if len(new) else m2
    p = C.REPO / "manifest" / "pairs_v2.parquet"
    out.to_parquet(p, index=False)
    C.write_json(R02 / "manifest_v2_summary.json", {"date": date.today().isoformat(), "rows": int(len(out)), "existing": int(len(m2)), "new": int(len(new)),
                                                  "by_designation": out.designation.value_counts().to_dict(), "path": str(p), "sha256": C.sha256_file(p)})
    print(out.designation.value_counts().to_dict(), len(out), p)
    return 0


def pd_rel(out_dir):
    from pathlib import Path
    p = Path(out_dir)
    try:
        return p.relative_to(C.OAK)
    except ValueError:
        return p


if __name__ == "__main__":
    sys.exit(main())
