"""ACQ-R03 §5.1 — extract the recorded basis of every existing corpus pair accepted with a co-registration offset
> 30 m: manifest rows (coreg_status carrying QGIS_signed_off / offset>30m_USBL_QGIS_basis / QGIS_R3_approved with
offset > 30 m), their notes, and the June report/directive lines that state how such pairs were judged.
Output: reports_post_grl_review/ACQ-R03/confirmatory_review_criterion_records.json (quoted in the .md).
"""
from __future__ import annotations

import json
import re
import sys

import pandas as pd

from src.acq_r03 import common as R

REPORTS = ["reports/stage_f_harmonization_2026-06-23.md", "reports/stage_f5_valid_masks_2026-06-23.md",
           "reports/stage_c1_reharvest_step2_harmonization_2026-06-26.md", "reports/stage_c1_phase1_report_2026-06-26.md",
           "reports/stage_c1_append_report_2026-06-26.md", "reports/stage_manifest_completeness_report_2026-06-26.md",
           "reports/directive_phase2_stage_f5_valid_masks.md"]
CODE = ["src/discovery/stage_c1_phase1_execute.py", "src/discovery/stage_c1_append.py"]


def main():
    m = pd.read_parquet(R.C.REPO / "manifest" / "pairs_v2.parquet")
    acc = m[(m.horiz_offset_m > 30) & m.coreg_status.astype(str).str.contains("QGIS")]
    rows = []
    for _, r in acc.iterrows():
        rows.append({"pair_id": r.pair_id, "leakage_unit": r.leakage_unit, "designation": r.designation, "horiz_offset_m": float(r.horiz_offset_m),
                     "vert_offset_m": float(r.vert_offset_m) if pd.notna(r.vert_offset_m) else None, "coreg_status": r.coreg_status,
                     "coreg_peak_psr": None if pd.isna(r.coreg_peak_psr) else float(r.coreg_peak_psr), "notes": r.notes, "qc_artifact_path": r.qc_artifact_path})
    quotes = []
    pat = re.compile(r"(?i)qgis|usbl|bad lock|real alignment|arbitrat")
    for f in REPORTS + CODE:
        p = R.C.REPO / f
        if not p.exists():
            continue
        for i, ln in enumerate(p.read_text().splitlines(), 1):
            if pat.search(ln) and re.search(r"(?i)usbl|> ?30|offset|bad lock|arbitrat", ln):
                quotes.append({"file": f, "line": i, "text": ln.strip()[:600]})
    not_accepted = m[(m.horiz_offset_m > 30) & ~m.coreg_status.astype(str).str.contains("QGIS")][["pair_id", "leakage_unit", "horiz_offset_m", "coreg_status"]].to_dict("records")
    out = {"generated": R.utc_now(), "accepted_over_30m_with_qgis_basis": rows, "over_30m_not_under_qgis_basis": not_accepted, "record_quotes": quotes}
    R.write_json(R.REPORT_DIR / "confirmatory_review_criterion_records.json", out)
    print(json.dumps({"accepted": [(r["pair_id"], r["horiz_offset_m"]) for r in rows], "not_under_basis": len(not_accepted), "quotes": len(quotes)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
