"""ACQ-R02 §6/§8 — acquisition summary tables from fetch manifests, grid records and harmonize records.
Outputs reports_post_grl_review/ACQ-R02/acquisition_table.{md,csv} (development pairs: full QA; confirmatory: sealed fields only).
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from src.acq_r01 import common as C

R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"


def main():
    cruises = []
    for gp in sorted((R02 / "grid").glob("*.json")):
        g = json.loads(gp.read_text()); cr = g["cruise"]
        fm = C.RAW_SWATH_OAK / cr / "fetch_manifest.json"
        f = json.loads(fm.read_text()) if fm.exists() else {}
        cruises.append({"cruise": cr, "files_on_oak": f.get("n_files_ok"), "gb_on_oak": round(f.get("bytes_ok", 0) / 1e9, 2) if f else None, "fetch_complete": f.get("n_files_failed") == 0 if f else None,
                        "format": g.get("format"), "sonar": g.get("sonar"), "beamwidth_deg": g.get("beamwidth_deg"), "depth_m": g.get("footprint_depth_m"), "cell_m": g.get("cell_m"),
                        "region_choice": (g.get("region_choice") or "whole footprint")[:60], "n_valid": g.get("n_valid"), "wall_s": g.get("wall_s")})
    cdf = pd.DataFrame(cruises); cdf.to_csv(R02 / "acquisition_cruises.csv", index=False)
    rows = []
    for jp in sorted((R02 / "harmonize").glob("*.json")):
        r = json.loads(jp.read_text()); conf = str(r.get("designation", "")).startswith("confirmatory")
        cg = r.get("coreg") or {}; k = r.get("k_sweep") or {}; pv = r.get("products_v2") or {}; q = (pv.get("qa") or {}) if isinstance(pv, dict) else {}; xc = r.get("processed_lr_crosscheck") or {}
        row = {"pair_id": r["pair_id"], "set": r.get("set"), "unit": r.get("unit"), "designation": r.get("designation"), "status": r.get("status", "")[:26],
               "hr_res_m": r.get("hr_res_m"), "hr_tiles": r.get("hr_tiles_used"), "overlap_km2": r.get("overlap_km2"), "n_lr_valid": r.get("n_lr_valid"), "joint_km2": r.get("joint_area_km2"),
               "valid_tiles_256": r.get("n_valid_tiles_256"), "coreg_offset_m": cg.get("offset_m"), "coreg_dz_m": cg.get("dz_m"), "coreg_pass": cg.get("pass"), "qa_pass": r.get("qa_pass"),
               "coreg_error": cg.get("error")}
        if not conf:
            row.update({"post_residual_mad_m": cg.get("post_residual_mad_m"), "lr_native_m": (r.get("lr_native") or {}).get("lr_native_m"), "k_status": k.get("status"), "max_k": k.get("max_recoverable_k"),
                        "v2_flags": ",".join(q.get("flags") or []) if q else (pv.get("error", "")[:40] if isinstance(pv, dict) else ""), "v2_robust_sigma_m": q.get("robust_sigma_m"), "v2_median_off_m": q.get("median_offset_m"),
                        "xcheck": (xc.get("status") or "")[:45], "xcheck_median_m": xc.get("median_offset_m_rawswath_minus_processed"), "xcheck_sigma_m": xc.get("robust_sigma_m")})
        rows.append(row)
    df = pd.DataFrame(rows); df.to_csv(R02 / "acquisition_table.csv", index=False)
    md = ["## LR cruises fetched / gridded", "", "| cruise | files | GB | complete | fmt | sonar | bw° | depth m | cell m | region | wall s |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, c in cdf.iterrows():
        md.append(f"| {c.cruise} | {c.files_on_oak} | {c.gb_on_oak} | {c.fetch_complete} | {c.format} | {c.sonar} | {c.beamwidth_deg} | {c.depth_m} | {c.cell_m} | {c.region_choice} | {c.wall_s} |")
    md += ["", "## Pairs harmonized", "", "| pair | set | unit | designation | HR res m | tiles | overlap km² | LR valid cells | joint km² | tiles≥50% | coreg off m | dz m | coreg | QA | MAD m | LR native m | k | v2 flags | v2 σ m | H1 x-check |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        g = lambda k: r.get(k) if pd.notna(r.get(k)) else ""
        md.append(f"| {r.pair_id} | {g('set')} | {g('unit')} | {g('designation')} | {g('hr_res_m')} | {g('hr_tiles')} | {g('overlap_km2')} | {g('n_lr_valid')} | {g('joint_km2')} | {g('valid_tiles_256')} | {g('coreg_offset_m')} | {g('coreg_dz_m')} | {'pass' if r.coreg_pass else 'FAIL'} | {'pass' if r.qa_pass else 'fail'} | {g('post_residual_mad_m')} | {g('lr_native_m')} | {g('max_k')} | {g('v2_flags')} | {g('v2_robust_sigma_m')} | {g('xcheck')} {g('xcheck_median_m')} {g('xcheck_sigma_m')} |")
    (R02 / "acquisition_table.md").write_text("\n".join(md)); print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
