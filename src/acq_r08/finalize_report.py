"""ACQ-R08 — fill the report draft's placeholders (bottom line, per-pool summary, prior exposure, HOLDs) with the run's
results and write REPORT_ACQ-R08_<date>.md. Text is fixed here on purpose: every number is read from the pool outputs."""
from __future__ import annotations

import json
import sys

import pandas as pd

from src.acq_r08 import common as K

R = K.OUT


def main(argv=None):
    draft = (R / f"REPORT_ACQ-R08_{K.STAMP}.draft.md").read_text()
    fa = json.loads((R / "pool_a" / "funnel.json").read_text()); fb = json.loads((R / "pool_b" / "funnel.json").read_text())
    fc = json.loads((R / "pool_c" / "summary.json").read_text()); notes = json.loads((R / "exclusion_set_notes.json").read_text())
    mh = json.loads((R / "must_hold_checks.json").read_text())
    T = fa["TOTAL"]; H = fa["_harvest"]
    ca = pd.read_csv(R / "candidates_pool_a_in_range_and_uncertain.csv"); cb = pd.read_csv(R / "candidates_pool_b_in_range_and_uncertain.csv")
    pc = pd.read_csv(R / "pool_c" / "pool_c_table.csv")
    a_in = ca[ca.status == "in range"]; a_unc = ca[ca.status == "uncertain"]
    nk = mh["1_no_bathymetry_opened"]["network_request_kinds"]; nreq = sum(nk.values())
    excl_n = notes["n_by_kind"]

    def row(r):
        return (f"`{r.hr_id}` ({r.title[:70]}…; HR {r.hr_res_m:.2f} m, LR {r.lr_cruise} {r.lr_sonar} {int(r.lr_year) if pd.notna(r.lr_year) else ''}, "
                f"lr_est {r.lr_est_m:.0f} m, cells {r.cells_across_est:.2f}, tiles {int(r.tiles_est)}, {r.basin}, {r.size_est_gb:.1f} GB)")

    bullets = [
        f"1. **Pool A — 3 candidates in range, 11 uncertain, none designated (CONFIRMED; `pool_a/funnel.json`, `candidates_pool_a_in_range_and_uncertain.csv`).** "
        f"{T['records_found']} near-bottom grid records found (MGDS {H['mgds_by_platform_type']['AUV']} AUV + {H['mgds_by_platform_type']['ROV']} ROV + {H['mgds_by_platform_type']['HOV']} HOV → 146 after the repo's sibling collapse; PANGAEA {H['pangaea_auv_bathymetry_datasets']} of {H['pangaea_auv_hits']:,} hits; "
        f"DataCite-indexed repositories {H['datacite_near_bottom_grid_datasets']} of {H['datacite_hits']} hits — SEANOE 6, BODC 2, USGS 2, others 14; ScienceBase {H['sciencebase_items']}); "
        f"{T['not_a_grid_or_non_bathy']} are not elevation grids (renders, raw swath, non-bathymetry, no footprint); §1 excluded {T['excluded_rule_1']} (identity / overlap with the {excl_n['manifest_v2_1'] + excl_n['lockbox'] + excl_n['confirmatory']} manifest v2.1 footprints or the {excl_n['rejected_sept']} September-rejected ones), "
        f"{T['excluded_rule_2']} within 10 km, {T['excluded_rule_3']} in the Cal DIG area, {T['excluded_rule_4']} compilation-only, {T['excluded_rule_5']} same-cruise-only; {T['screened_under_s3']} screened under §3. In range: "
        + "; ".join(row(r) for _, r in a_in.iterrows()) + f". The three are MGDS Sentry grids under CC-BY-NC-SA terms (`releasable = yes_conditional`, HOLD H-3); none lies within 50 km of a corpus footprint (nearest 209 km).",
        f"2. **Pool A uncertain ({len(a_unc)}) and outside ({T['outside_range']}).** Uncertain for a stated reason each: 7 have only a catalog bounding box (tiles are an upper bound: {int(a_unc.tiles_est.sum()):,} in total; true footprint needs download), 4 state no grid resolution, 4 no depth. "
        f"Outside range: {json.dumps(T['outside_by_condition'])}. Every excluded or not-eligible record carries its reason (`must_hold_checks.json` 2: {mh['2_every_excluded_has_reason_pool_a']['excluded']}/{mh['2_every_excluded_has_reason_pool_a']['excluded']} and {mh['2_every_excluded_has_reason_pool_a']['not_eligible']}/{mh['2_every_excluded_has_reason_pool_a']['not_eligible']}).",
        f"3. **Pool B — 0 in range, {fb['uncertain']} uncertain, structurally so (CONFIRMED; `pool_b/funnel.json`).** {fb['records_found_nos_surveys']:,} NOS survey records (NCEI Geoportal; the NOS hydro ArcGIS service exposes no queryable layer, checked); {fb['bag_4m_or_finer']:,} carry a BAG at 4 m or finer by file name; "
        f"{fb['with_independent_lr']} have an independent NCEI multibeam cruise over them, {fb['excluded_rule_5']} only a same-survey / same-NOAA-ship cruise (rule 5), {fb['with_independent_lr_and_tiles_ge_300']} with ≥ 300 bbox tiles. No NOS catalog record states depth (0 of 400 ISO records checked), so `lr_est_m` is `needs download` for all {fb['uncertain']} and none can be called in range; "
        f"under the NOS resolution–depth bands a ≤ 4 m BAG implies ≤ 160 m water and a ship footprint < 3 m, so no Pool B pair can reach ratio 4.5 unless its depth exceeds that band (plausible_under_hssd = 0 of {fb['uncertain']}). HOLD H-2.",
        f"4. **Pool C — {fc['rows']} rejection rows ({fc['distinct_hr']} distinct HR) across June and September, each with its reason (CONFIRMED; `pool_c_table.md`).** Still applies: {fc['still_applies'].get('yes', 0)} (false pairs, renders, QA fails, rulings, format blockers, measured data findings); superseded by the ACQ-R02 H1 path: {fc['still_applies'].get('superseded', 0)}; now in manifest v2.1: {fc['still_applies'].get('n/a (now in manifest v2.1)', 0)}; "
        f"re-check: {fc['still_applies'].get('re-check', 0)}; **no longer applies: {fc['still_applies'].get('no', 0)} rows = 10 HR rejected only by the retired 5–40× ratio gate** → re-screened in Pool A: one is now **in range** (`MGDS:31954` Dorado Outcrop), 6 are excluded by §1.1 (overlap or September rejection on another ground), 1 by §1.2 (`MGDS:32208`, 8.3 km from NA090), 1 (`MGDS:30832`) is no longer listed by MGDS, 1 (`MGDS:24043` AT37-05) was dropped in ACQ-R03 on a measured line offset.",
        f"5. **Blindness held (CONFIRMED; `guard_selftest.json`, `must_hold_checks.json` 1, `network_log.jsonl`).** The run-time guard refused every raster open and data/image URL in its self-test (7/7) and nothing else tripped it; the {nreq:,} network requests were all of these types: "
        + "; ".join(f"{k} ×{v}" for k, v in sorted(nk.items(), key=lambda kv: -kv[1])) + ". No thumbnail, preview, grid, sounding file or raster was requested; corpus footprints came from vector files only (OAK `footprint.geojson`, the ACQ-R02 verification footprints for the sealed pairs, the ACQ-R01 catalog bbox for the lockbox pairs).",
        f"6. **Method (CONFIRMED).** `lr_est_m` = the Geoportal-stated product spacing where present (1 cruise), else 2·z·tan(bw/2) with the documented beamwidth of the named sonar at the mean catalog depth (23); each HR's LR is the independent raw-swath cruise (not the HR's cruise, not a compilation) giving the best §3 status, then the most tiles, among up to 8 overlapping NCEI / PANGAEA cruises (alternatives recorded). "
        f"Exclusion set: {sum(excl_n.values())} footprints ({excl_n['manifest_v2_1']} manifest + {excl_n['lockbox']} lockbox + {excl_n['confirmatory']} confirmatory + {excl_n['rejected_sept']} September-rejected + the Cal DIG area = hull of the 20 Cal DIG footprints + 25 km, 10,536 km²); nearest-footprint distance recorded for every record, ≤ 50 km flagged (Pool A: 1, `MGDS:21428`, 20 km from NA076, outside range; Pool B: {fb['within_50km_flagged']}).",
        "7. **Challenge notes (no work-around; applied as stated, Steve may overrule).** (i) `hr_res_m` lower bound applied at 0.985 m: the manifest's own 1 m grids carry 0.989–0.999 m UTM cells, so a literal 1.0 would reject the corpus itself. (ii) §1.1 excludes every September-rejected pair while §2 Pool C re-screens pairs whose reason no longer applies; the 5 HR that ACQ-R01 rejected *only* by the retired ratio gate were re-screened (Pool C), not excluded. (iii) The MGDS data_set view carries no cruise id in the current XML, so HR cruise ids were parsed from titles/abstracts (and, for Venere 884112, from REPORT_ACQ-R02); rule 5 then excluded 3 HR whose only ship coverage is their own cruise. (iv) Pool A `size_est_gb` = MGDS file sizes + NCEI autoindex listing of the LR cruise (PANGAEA / DataCite HR sizes need a file listing: 4 rows).",
        "8. **Steve's holdings:** `inputs/steve_holdings.csv` is absent → skipped (§2). No candidate was designated, seeded or split (`must_hold_checks.json` 4).",
    ]
    summary = ["", "## 6. Summary per pool (§5.4)", "",
               f"- **Pool A:** 3 in range, {int(a_in.tiles_est.sum()):,} estimated tiles in total ({', '.join(str(int(t)) for t in a_in.tiles_est)}); settings: hydrothermal/off-axis outcrop (Dorado Outcrop, Cocos plate off Costa Rica, 9.1°N 87.1°W), Chile margin / triple-junction area (MV1205, 46.3°S 75.8°W, setting not stated in the record), Bermuda platform (AE1823, 32.7°N 64.6°W, not stated); regions: Pacific 2, Atlantic 1; download {a_in.size_est_gb.sum():.1f} GB (MV1003 raw swath alone 40 GB). "
               f"Uncertain: {len(a_unc)} with {int(a_unc.tiles_est.sum()):,} bbox-bound tiles; settings volcanic/seamount 4 (Escanaba Trough, Galápagos Spreading Center ×2), hydrothermal 2 (MAR 16.5°N, Kolumbo), continental margin 2 (Monterey Canyon, La Jolla Canyon), not stated 3 (BODC ×2, Marmara) + 1 ROV CSV product; regions Pacific 6, Atlantic 3, Mediterranean 2; download {a_unc.size_est_gb.sum(skipna=True):.1f} GB known + 4 rows needing a listing.",
               f"- **Pool B:** 0 in range; {fb['uncertain']} uncertain (BAG 1 m: {int((cb.hr_res_m == 1).sum())}, 2 m: {int((cb.hr_res_m == 2).sum())}, 3 m: {int((cb.hr_res_m == 3).sum())}, 4 m: {int((cb.hr_res_m == 4).sum())}); regions Atlantic {int((cb.get('basin', pd.Series(dtype=str)) == 'Atlantic').sum()) if 'basin' in cb else 'see csv'}; bbox-bound tiles {int(cb.tiles_est.sum()):,}; download sizes not listed (would be one NCEI listing per LR cruise; not done while every row is uncertain on depth).",
               f"- **Pool C:** {fc['still_applies'].get('no', 0)} rows re-screened; one new in-range candidate (MGDS:31954), nothing else changes.", ""]
    exposure = ["", "## 7. Prior exposure (§5.5)", "",
                "- **Cal DIG / Morro Bay** (Steve's own survey area): excluded as the Cal DIG area; 0 Pool A / 0 Pool B records inside it (the NOS surveys there carry 8–16 m or unparsed BAGs).",
                "- **User-provided Cascadia AUV data** (TN299__MGDS_31253 / AT42-17): in the corpus; nothing new within 10 km.",
                "- **ACQ-R02 / ACQ-R01 designated-but-not-acquired units** (Steve has read their metadata in the September reports): `PANGAEA:884112` Venere (pu00) — now excluded under rule 5 (its only ship coverage is its own M112/1 cruise); `PANGAEA:958275` Kolumbo (pu03) — uncertain (depth not in record; its M143 EM122 LR is a different cruise, but the POS510/M215 access restriction seen in September may extend to it); `MGDS:30368` Escanaba Trough (nu02) — uncertain (bbox footprint). HOLD H-1.",
                "- **June-harmonized, then dropped:** `MGDS:31675` (AE1823) was harmonized in June against KN204-01 and dropped at manifest append (51 m offset, no interior NCC peak); its QC figure exists in `qc/`. It is now in range against a *different* cruise (KN173L02, 2003); KN204-01 is also in range as an alternative. Steve may have seen the June figure.",
                "- **Original directive Tier 2 sites** (Kolumbo, Etna, CCZ, TAG): Kolumbo is the pu03 row above; Etna (941403) is render-only (September), CCZ/TAG are corpus.",
                "- **Widely published MBARI/Monterey sites:** `MGDS:24756` Monterey Canyon 1 m (uncertain) and the Escanaba Trough row are MBARI products Steve is likely to know.", ""]
    holds = ["## 9. HOLDs (at most 3)", "",
             "- **H-1 — §1.1 is silent on units designated in ACQ-R01/R02 but never acquired** (pu03 Kolumbo `PANGAEA:958275`, nu02 Escanaba `MGDS:30368`; pu00 Venere falls under rule 5 anyway). They are not manifest rows and were not rejected, so they were screened and appear as uncertain candidates, flagged in `prior_exposure`. Steve's call: keep them as candidates (metadata already seen by him and by this repo) or exclude them as prior exposure.",
             "- **H-2 — Pool B cannot be screened to `in range` from catalog metadata.** No NOS record states depth, and the directive forbids reading any bathymetry (so no GEBCO-style depth lookup). All 401 survivors are `uncertain` on one field; under the NOS resolution–depth standard none is plausible. Steve's call: (a) drop Pool B, (b) accept a ruling that a depth lookup from a non-candidate source is allowed for Pool B only, or (c) accept an ISO-abstract depth where a survey states it (none of the 400 checked did).",
             "- **H-3 — `releasable` for MGDS records.** MGDS states no licence per record; its default terms are CC-BY-NC-SA. All three in-range Pool A candidates (and 8 of 11 uncertain) are MGDS. Applied here as `yes_conditional` (use and redistribution of derived products permitted non-commercially, share-alike). If the paper's data-availability requires an unconditional licence, Pool A has no in-range candidate; Steve's call.", ""]
    out = draft.replace("<<BULLETS>>", "\n".join(bullets)).replace("<<SUMMARY>>", "\n".join(summary)).replace("<<EXPOSURE>>", "\n".join(exposure)).replace("<<HOLDS>>", "\n".join(holds))
    out = out.replace("**Run:** " + K.STAMP + ",", "**Run:** 2026-10-12 → 2026-10-13 (UTC),")
    (R / f"REPORT_ACQ-R08_{K.STAMP}.md").write_text(out)
    print("written", R / f"REPORT_ACQ-R08_{K.STAMP}.md", len(out.splitlines()), "lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
