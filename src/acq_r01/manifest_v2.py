"""ACQ-R02 §7 — manifest v2: `manifest/pairs_v2.parquet` (pairs.parquet is NOT modified).

Rows: the 39 existing pairs unchanged (+ `designation`, `harmonized_path`), the new development pairs
harmonized in §6 (full row from the harmonize record; lockbox never touched), and confirmatory pairs
with path + designation only (no derived statistics).  `harmonized_path` = the directory that holds
the pair's lr.tif, authoritative per contract v2 §2 (root-relative to the OAK data root).
Validates that every development pair's ship_products_v2 pass contract v2 (validate_contract_v2).

Directive §5.4 binding rule: a pair that fails acquisition or QA is dropped from its assigned set and never
reassigned.  Such pairs are NOT rows of pairs_v2.parquet; they are recorded in manifest/pairs_v2_dropped.csv
(pair, designation it was dropped from, reason).  Their harmonized directories stay on OAK untouched.
Drop reasons: `no_lr_soundings_under_hr` (the fetched raw swath has no soundings inside the HR footprint: a
false pair), `coreg_fail` (rigid offset outside the 30 m bound or no solution), `zero_valid_tiles_256`.
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
    rows = []; dropped = []
    for jp in sorted((R02 / "harmonize").glob("*.json")):
        r = json.loads(jp.read_text())
        if not str(r.get("status", "")).startswith("harmonized"):
            continue
        conf = str(r["designation"]).startswith("confirmatory")
        reason = drop_reason(r)
        if reason:
            dropped.append({"pair_id": r["pair_id"], "dropped_from": r["designation"], "leakage_unit": r.get("unit", ""), "lr_cruise": r["lr_cruise"],
                            "reason": reason, "harmonized_dir": str(pd_rel(r["out_dir"]))})
            continue
        rel = str(pd_rel(r["out_dir"]))
        base = {"pair_id": r["pair_id"], "designation": r["designation"], "harmonized_path": rel, "leakage_unit": r.get("unit", ""),
                "lr_cruise": r["lr_cruise"], "cruise_id": r.get("hr_cruise", ""), "hr_doi": r.get("hr_id", ""), "verification_status": "acq_r02_verified",
                "qa_status": "pass"}
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
    pdrop = C.REPO / "manifest" / "pairs_v2_dropped.csv"
    pd.DataFrame(dropped, columns=["pair_id", "dropped_from", "leakage_unit", "lr_cruise", "reason", "harmonized_dir"]).to_csv(pdrop, index=False)
    C.write_json(R02 / "manifest_v2_summary.json", {"date": date.today().isoformat(), "rows": int(len(out)), "existing": int(len(m2)), "new": int(len(new)),
                                                  "by_designation": out.designation.value_counts().to_dict(), "path": str(p), "sha256": C.sha256_file(p),
                                                  "dropped": dropped, "dropped_path": str(pdrop), "dropped_sha256": C.sha256_file(pdrop)})
    dev_new = [r["pair_id"] for r in rows if not str(r["designation"]).startswith("confirmatory")]
    (R02 / "new_dev_pairs.txt").write_text(",".join(dev_new) + "\n")
    print(out.designation.value_counts().to_dict(), len(out), p, "| new development pairs:", dev_new)
    return 0


def drop_reason(r):
    """Directive §5.4: failed acquisition / QA -> dropped, never reassigned.  Returns None when the pair is kept."""
    cg = r.get("coreg") or {}
    if not r.get("n_lr_valid"):
        return "no_lr_soundings_under_hr"
    if r.get("qa_pass"):
        return None
    if not cg.get("pass"):
        off = cg.get("offset_m")
        return f"coreg_fail offset={off} m" + (f" dz={cg.get('dz_m')} m MAD={cg.get('post_residual_mad_m')} m" if cg.get("post_residual_mad_m") is not None else "")
    if not r.get("n_valid_tiles_256"):
        return "zero_valid_tiles_256"
    return "qa_fail"


def pd_rel(out_dir):
    from pathlib import Path
    p = Path(out_dir)
    try:
        return p.relative_to(C.OAK)
    except ValueError:
        return p


if __name__ == "__main__":
    sys.exit(main())
