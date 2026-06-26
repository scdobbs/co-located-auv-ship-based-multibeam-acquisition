"""Update combined_corpus.csv with re-audit results + retract +255/raw_datum_broken.
Also append a stage_reaudit block to staging_state. Small text artifacts only."""
from __future__ import annotations
import json, logging
from pathlib import Path
import pandas as pd

log = logging.getLogger("reaudit_corpus")
REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "reports/combined_corpus.csv"
R0 = REPO / "reports/discovery/stage_reaudit_r0.json"
STAGING = REPO / "reports/discovery/staging_state_20260605.json"

RGB_EXCLUDE = {"EW0207__MGDS_32558", "EW9904__MGDS_30217", "FK171110__MGDS_24485",
               "NA076__MGDS_32321", "RC2511__MGDS_32241", "TN383__MGDS_29694",
               "TN299__MGDS_31256", "FK181031__MGDS_24620", "2009_Amundsen__MGDS_30045"}
ADVANCING = {"AT37-13__MGDS_31199", "AT42-03__MGDS_32007", "EW9801__MGDS_31425",
             "NA080__MGDS_31290", "NA090__MGDS_31212", "RR1506__MGDS_29779",
             "TN268__MGDS_30466", "TN399__MGDS_30373", "FK181031__MGDS_24367"}


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    r0 = {o["pair_id"]: o for o in json.loads(R0.read_text())}
    c = pd.read_csv(CORPUS)
    st, hf, disp, retr = [], [], [], []
    for pid in c["pair_id"]:
        o = r0.get(pid)
        if o is None:                       # the 21 validated
            st.append(""); hf.append(""); disp.append("validated_21"); retr.append("")
            continue
        st.append(o.get("selected_type"))
        hf.append(bool(o.get("has_float_elevation_source")))
        if pid in RGB_EXCLUDE:
            disp.append("exclude_no_elevation")
        elif pid in ADVANCING:
            disp.append("advancing")
        else:
            disp.append("real_nonadvancing_qgis")
        retr.append(True)                   # +255/raw_datum_broken retracted for all new pairs
    c["source_type"] = st
    c["has_float_elevation"] = hf
    c["reaudit_disposition"] = disp
    c["reaudit_retracts_plus255_flag"] = retr
    # neutralize the now-retracted prior flag without deleting the column (audit trail)
    if "raw_datum_broken" in c.columns:
        c["raw_datum_broken_RETRACTED"] = c["raw_datum_broken"]
        c["raw_datum_broken"] = ""
    c.to_csv(CORPUS, index=False)
    from collections import Counter
    log.info("disposition: %s", dict(Counter(disp)))

    ss = json.loads(STAGING.read_text())
    ss["stage_reaudit"] = {
        "generated": "2026-06-26",
        "directive": "reports/directive_phase2_colocated_reaudit_v1.md",
        "report": "reports/stage_reaudit_report_2026-06-26.md",
        "headline": "The '+255' is RGB, not a misread of float elevation. 9/32 new pairs have a 3-band uint8 RGB visualization HR source (slope/hillshade renders) with NO elevation band; Terrain-RGB decode fails. Directive premise (band-1-float-misread) falsified for these.",
        "reader_proof": "corrected reader (gmt_grd/.grd + float .tif; reject 3-band uint8 RGB) reproduces real depths matching ship LR & QGIS on the 23 real pairs; 11 evidence PNGs in $DATA_ROOT/qc_plots/r0_evidence/",
        "rgb_exclude_no_elevation": sorted(RGB_EXCLUDE),
        "advancing_unchanged": sorted(ADVANCING),
        "real_nonadvancing_qgis": [p for p, d in zip(c["pair_id"], disp) if d == "real_nonadvancing_qgis"],
        "selected_type_counts": dict(Counter(st_ for st_ in st if st_)),
        "validated_21": "R5: all 21 single-band float32, correct site depths, 0 RGB",
        "my_prior_repair_caveat": "8 RGB pairs were cosmetically 'repaired' (RGB red channel aligned to LR -> fake plateau depths); hr_preF5repair.tif retained; recommend restore-or-exclude (NOT executed, HOLD)",
        "deferred_HOLD": ["R2 multi-grid clip audit", "R3 full QC figures", "R6 combined manifest"],
        "status": "HOLD for assessment; premise shift escalated",
    }
    STAGING.write_text(json.dumps(ss, indent=1, default=str))
    log.info("updated corpus (%d cols) + staging_state", len(c.columns))


if __name__ == "__main__":
    main()
