"""ACQ-R01 §1.3 — corpus reconciliation: every HR the June stage-A gate called acquirable vs
the current 39-pair / 19-unit manifest, with the recorded exclusion reason (or "reason unrecorded").

Sources (all persisted in reports/ or manifest/; nothing recomputed from rasters):
  stage_a_selection.gpkg (v1.5.2 gate, 110 HR; acquirable = training | eval_only | raw_lr_to_grid)
  staging_state_20260605.json (phase-1 quarantine/escalation, truly-processed pairs)
  stage_a6_duplicates / stage_b_fetch_list / stage_b_fetch_report (dedup, dropped cruises, legacy formats)
  stage_c_full (gridding failures), stage_c5b_sweep.json (overlap / recoverable-k), stage_c5c report (false pairs)
  combined_corpus.csv (stage E corpus + F5 buckets + re-audit dispositions)
  stage_append_exclusions_2026-06-26.csv, staging_state stage_reaudit / provenance / c1 sections
  manifest/pairs.parquet (39 pairs, hr_superseded_doi)
Output: reports_post_grl_review/ACQ-R01/corpus_reconciliation.{csv,md}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.acq_r01 import common as C

R = C.REPO / "reports"
D = R / "discovery"


def main():
    sel = gpd.read_file(D / "stage_a_selection.gpkg")
    st = json.loads((D / "staging_state_20260605.json").read_text())
    m = C.load_manifest()
    dup = pd.read_csv(D / "stage_a6_duplicates_2026-06-22.csv").set_index("hr_id")
    fl = pd.read_csv(R / "stage_b_fetch_list_2026-06-22.csv")
    c5b = {f"{r['hr_id']}": r for r in json.loads((D / "stage_c5b_sweep.json").read_text())}
    cc = pd.read_csv(R / "combined_corpus.csv")
    app_excl = pd.read_csv(D / "stage_append_exclusions_2026-06-26.csv").set_index("pair_id")

    # --- corpus HR ids -------------------------------------------------------------
    corpus = {}
    for _, r in m.iterrows():
        pid = r.pair_id
        if "__MGDS_" in pid:
            uid = pid.split("__MGDS_")[1]
            corpus[f"MGDS:{uid}"] = pid
        elif pid == "tag_m127":
            corpus["PANGAEA:tag_m127"] = pid
        else:
            corpus[f"MANIFEST:{pid}"] = pid
    # HR grids that entered the corpus under another pair id
    corpus["MGDS:32556"] = "EW0207__MGDS_32556 (NRift) + supersedes HR of TN268__MGDS_30466 (SRift ver2025)"
    corpus["MGDS:30046"] = "2009_Amundsen__MGDS_30046 (C1 float recovery)"
    corpus["MGDS:24618"] = "FK181031__MGDS_24618 (C1 float recovery)"
    corpus["MGDS:32317"] = "NA076__MGDS_32317 (C1 float recovery)"
    corpus["MGDS:31253"] = "TN299__MGDS_31253 (C1 float recovery; catalog listed it under TN313)"
    unit_of = dict(zip(m.pair_id, m.leakage_unit))

    legacy = {"AII8L11", "EW9914", "RC2901", "PASC04WT", "PASC02WT", "RP11SU81", "TUNE04WT"}
    kept_cruises = {}
    for _, r in fl.iterrows():
        for h in str(r.live_HR).split(";"):
            if h and h != "nan":
                kept_cruises.setdefault(h, []).append((r.cruise, r.fetch_mode))
    dropped_cruises = set(fl[fl.fetch_mode == "DROP"].cruise)
    cc_by_hr = {r.hr_id: r for _, r in cc.iterrows() if isinstance(r.hr_id, str)}
    truly_processed = {p["hr_id"]: p["lr_id"] for p in st["truly_processed_pairs"]}
    rgb_companion = {"MGDS:32558": "MGDS:32556", "MGDS:30217": "MGDS:32556", "MGDS:29694": "MGDS:32556",
                     "MGDS:30045": "MGDS:30046", "MGDS:32321": "MGDS:32317", "MGDS:24620": "MGDS:24618",
                     "MGDS:24485": "MGDS:24499", "MGDS:32241": "MGDS:32240", "MGDS:31256": "MGDS:31253"}
    r3_declined = {"MGDS:30219", "MGDS:31254", "MGDS:31255", "MGDS:17700"}
    zero_tile = {"MGDS:32240", "MGDS:24470", "MGDS:7832"}
    c5c_false = {"MGDS:31949", "MGDS:31811", "MGDS:18210", "MGDS:31193"}
    c5c_no_spectrum = {"MGDS:31755", "MGDS:30270"}
    c5c_coreg_fail = {"MGDS:24756", "MGDS:21996", "MGDS:21998"}
    stage_c_fail = {"MGDS:21462": "AT18-11 gridding failed: HR footprint (2 deg wide, inflated) has no ship coverage -> false pair (stage C full report §4)",
                    "MGDS:21454": "AT18-11 gridding failed: HR footprint (2 deg wide, inflated) has no ship coverage -> false pair (stage C full report §4)",
                    "MGDS:24489": "TN234 EM300 vendor files read 0 good beams -> LR has no usable bathymetry (stage C full report §4)"}

    rows = []
    acq = sel[sel.tier.isin(["training", "eval_only", "raw_lr_to_grid"])]
    for _, s in acq.sort_values(["tier", "hr_id"]).iterrows():
        h = s.hr_id
        rec = {"hr_id": h, "gate_tier_2026-06-05": s.tier, "gate_lr": s.lr_cruise_id, "gate_res_ratio": s.res_ratio,
               "hr_title": (s.hr_title or "")[:90], "in_corpus_as": "", "leakage_unit": "", "fate": "", "reason_source": ""}
        pid = corpus.get(h)
        if pid:
            rec["in_corpus_as"] = pid
            key = pid.split(" ")[0]
            rec["leakage_unit"] = unit_of.get(key, "")
            rec["fate"] = "in corpus"
            rec["reason_source"] = "manifest/pairs.parquet"
        elif h in dup.index:
            rec["fate"] = f"duplicate of validated pair {dup.loc[h, 'duplicate_of']} (already in corpus)"
            rec["reason_source"] = "stage_a6_duplicates_2026-06-22.csv"
            rec["in_corpus_as"] = dup.loc[h, "duplicate_of"]; rec["leakage_unit"] = unit_of.get(dup.loc[h, "duplicate_of"], "")
        elif h == "MGDS:31600":
            rec["fate"] = "quarantined: declared 9.8 m grid measures 2.8 m cells -> coarse_or_composite (phase 1 rev2)"; rec["reason_source"] = "staging_state.phase1_rev2"
        elif h == "MGDS:30272":
            rec["fate"] = "dropped: MGDS download returns an HTML error page on both endpoints (phase 1 rev3 escalated recover_or_drop)"; rec["reason_source"] = "staging_state.phase1_rev3"
        elif h in ("MGDS:20836", "MGDS:24425"):
            rec["fate"] = "dropped: the MGDS 'grid' file is a PDF, not bathymetry (phase 1 rev3 escalated recover_or_drop)"; rec["reason_source"] = "staging_state.phase1_rev3"
        elif h in stage_c_fail:
            rec["fate"] = stage_c_fail[h]; rec["reason_source"] = "stage_c_full_report_2026-06-23.md"
        elif h in kept_cruises and all(c in legacy for c, _ in kept_cruises[h]):
            rec["fate"] = f"not fetched: only LR cruise ({kept_cruises[h][0][0]}) is a legacy SeaBeam-classic format the swath classifier does not recognise (stage B needs_format_review); no later ruling recorded"
            rec["reason_source"] = "stage_b_fetch_report_2026-06-22.md"
        elif h in truly_processed:
            rec["fate"] = (f"REASON UNRECORDED: phase-1 'truly processed LR' pair (LR {truly_processed[h]} processed grid staged); "
                           "stage A dry-run said these skip gridding and go to Stage F directly, but Stage F only harmonized the 32 C.5c pairs; never harmonized, never ruled on")
            rec["reason_source"] = "stage_a_gate1_raw_lr_dryrun_20260622.md §truly_processed vs stage_f_harmonization_2026-06-23.md"
        elif h in c5c_false:
            rec["fate"] = "excluded: inflated (degree-wide bbox) HR footprint -> false pair, no real HR/LR overlap (C.5b Track C; discovery footprint-bbox bug)"; rec["reason_source"] = "stage_c5b_consolidation_report_2026-06-23.md"
        elif h in c5c_no_spectrum:
            rec["fate"] = "excluded: degenerate shallow 2010_Amundsen pair, no spectrum / not recoverable at any k (C.5/C.5b)"; rec["reason_source"] = "stage_c5b_sweep.json"
        elif h in c5c_coreg_fail:
            rec["fate"] = "excluded: residual co-registration failure (LR coverage / CRS edge case), recommended manual pass, never done (C.5c)"; rec["reason_source"] = "stage_c5c_consolidation_report_2026-06-23.md"
        elif h in cc_by_hr:
            r = cc_by_hr[h]; disp = r.reaudit_disposition
            if disp == "exclude_no_elevation":
                comp = rgb_companion.get(h, "")
                comp_pid = corpus.get(comp, "")
                if comp_pid:
                    rec["fate"] = f"excluded: HR source is a 3-band RGB render (no elevation band); float companion {comp} acquired instead as {comp_pid}"
                else:
                    extra = " (companion had 0 valid tiles after F5 masks -> R6 zero-tile drop)" if comp in zero_tile else ""
                    rec["fate"] = f"excluded: HR source is a 3-band RGB render (no elevation band); float companion {comp} not in corpus{extra}"
                rec["reason_source"] = "stage_reaudit_report_2026-06-26.md + stage_reaudit_c1_float_recovery.csv"
            elif h in r3_declined:
                rec["fate"] = "declined by Steve at the R3 QC adjudication (2026-06-26)"; rec["reason_source"] = "stage_provenance_gate_report_2026-06-26.md"
            elif h in zero_tile:
                rec["fate"] = f"excluded: 0 valid tiles after F5 real-data masks (f5_bucket={r.f5_bucket}) -> R6 zero-tile drop"; rec["reason_source"] = "stage_reaudit_moveforward_report_2026-06-26.md"
            elif r.pair_id in app_excl.index:
                rec["fate"] = f"dropped at manifest append: {app_excl.loc[r.pair_id, 'reason_detail']} ({app_excl.loc[r.pair_id, 'exclusion_reason']}; not data-quality, eligible for manual re-coreg)"
                rec["reason_source"] = "stage_append_exclusions_2026-06-26.csv"
            else:
                rec["fate"] = f"REASON UNRECORDED: in stage-E corpus (f5_bucket={r.f5_bucket}, reaudit={disp}) but not in manifest and no exclusion record found"
                rec["reason_source"] = "combined_corpus.csv"
        elif h in c5b:
            r = c5b[h]
            if r["status"] in ("empty_overlap", "no_data_overlap"):
                rec["fate"] = f"excluded: HR and gridded LR have no real data overlap on the AUV-native grid (C.5b status={r['status']})"; rec["reason_source"] = "stage_c5b_sweep.json"
            elif r.get("max_recoverable_k") is None:
                rec["fate"] = "excluded: no recoverable SR signal at any k on the AUV-native grid (C.5b max_recoverable_k=null)"; rec["reason_source"] = "stage_c5b_sweep.json"
            else:
                rec["fate"] = f"REASON UNRECORDED: C.5b scored it recoverable (max_k={r.get('max_recoverable_k')}) but it is absent from the stage-E corpus and from every exclusion record"
                rec["reason_source"] = "stage_c5b_sweep.json vs combined_corpus.csv"
        elif h in kept_cruises:
            rec["fate"] = f"REASON UNRECORDED: LR cruise fetched ({kept_cruises[h][0][0]}) but the HR never appears in stage C/C.5 results"
            rec["reason_source"] = "stage_b_fetch_list_2026-06-22.csv"
        elif s.lr_cruise_id in dropped_cruises:
            rec["fate"] = f"not fetched: LR cruise {s.lr_cruise_id} dropped at A.6 (served only dead/duplicate/quarantined HR)"; rec["reason_source"] = "stage_a6_prefetch_hygiene_2026-06-22.md"
        else:
            rec["fate"] = "REASON UNRECORDED"; rec["reason_source"] = ""
        rows.append(rec)
    df = pd.DataFrame(rows)
    # special case: 2010_Amundsen 31753 (C1 re-harvest drop)
    df.loc[df.hr_id == "MGDS:31753", ["fate", "reason_source"]] = [
        "excluded: float re-harvest has 0 joint cells with the 2009_Amundsen LR (false co-location by footprint; C1 step 2 L2)",
        "stage_c1_reharvest_step2_rulings_2026-06-26.md"]
    C.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(C.REPORT_DIR / "corpus_reconciliation.csv", index=False)
    excl = sel[sel.tier == "excluded"][["hr_id", "tier_reason"]]
    summary = {"gate_acquirable_hr": int(len(acq)), "gate_tier_counts": acq.tier.value_counts().to_dict(),
               "in_corpus": int((df.fate == "in corpus").sum()),
               "duplicate_of_validated": int(df.fate.str.startswith("duplicate").sum()),
               "reason_unrecorded": int(df.fate.str.startswith("REASON UNRECORDED").sum()),
               "gate_excluded_hr": int(len(excl)), "manifest_pairs": int(len(m)), "leakage_units": int(m.leakage_unit.nunique())}
    md = [f"# Corpus reconciliation (ACQ-R01 §1.3)\n", f"Gate: `stage_a_selection.gpkg` (2026-06-05 v3). Acquirable HR = {summary['gate_acquirable_hr']} "
          f"({summary['gate_tier_counts']}); the directive's '~73' = 85 minus the 10 manifest-seed duplicates, 1 quarantined and 1 escalated HR. "
          f"Manifest today: {summary['manifest_pairs']} pairs / {summary['leakage_units']} leakage units.\n",
          f"In corpus: {summary['in_corpus']} · duplicates of validated pairs: {summary['duplicate_of_validated']} · **reason unrecorded: {summary['reason_unrecorded']}**\n",
          "| hr_id | gate tier | gate LR | ratio | in corpus as | unit | fate | source |", "|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        rr = "" if pd.isna(r.gate_res_ratio) else f"{r.gate_res_ratio:.1f}"
        md.append(f"| {r.hr_id} | {r['gate_tier_2026-06-05']} | {r.gate_lr} | {rr} | {r.in_corpus_as} | {r.leakage_unit} | {r.fate} | {r.reason_source} |")
    md += ["", f"## Gate-excluded HR ({len(excl)}; recorded at the gate)", "", "| hr_id | tier_reason |", "|---|---|"]
    md += [f"| {r.hr_id} | {r.tier_reason} |" for _, r in excl.iterrows()]
    (C.REPORT_DIR / "corpus_reconciliation.md").write_text("\n".join(md))
    C.write_json(C.REPORT_DIR / "corpus_reconciliation_summary.json", summary)
    print(json.dumps(summary, indent=1))
    print(df[df.fate.str.startswith("REASON UNRECORDED")][["hr_id", "gate_tier_2026-06-05", "gate_lr", "fate"]].to_string())


if __name__ == "__main__":
    main()
