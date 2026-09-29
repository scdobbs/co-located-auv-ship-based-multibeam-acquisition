# Corpus reconciliation (ACQ-R01 §1.3)

Gate: `stage_a_selection.gpkg` (2026-06-05 v3). Acquirable HR = 85 ({'raw_lr_to_grid': 35, 'training': 31, 'eval_only': 19}); the directive's '~73' = 85 minus the 10 manifest-seed duplicates, 1 quarantined and 1 escalated HR. Manifest today: 39 pairs / 19 leakage units.

In corpus: 25 · duplicates of validated pairs: 0 · **reason unrecorded: 11**

| hr_id | gate tier | gate LR | ratio | in corpus as | unit | fate | source |
|---|---|---|---|---|---|---|---|
| MANIFEST:cal_dig_morro_bay__20190317m2_600mGully | eval_only | EX1101 | 35.0 | cal_dig_morro_bay__20190317m2_600mGully | lu12 | in corpus | manifest/pairs.parquet |
| MGDS:21454 | eval_only | AT18-11 | 36.3 |  |  | AT18-11 gridding failed: HR footprint (2 deg wide, inflated) has no ship coverage -> false pair (stage C full report §4) | stage_c_full_report_2026-06-23.md |
| MGDS:24002 | eval_only | EX0909 | 30.0 |  |  | REASON UNRECORDED: phase-1 'truly processed LR' pair (LR NCEI_MBBDB:EX0909 processed grid staged); stage A dry-run said these skip gridding and go to Stage F directly, but Stage F only harmonized the 32 C.5c pairs; never harmonized, never ruled on | stage_a_gate1_raw_lr_dryrun_20260622.md §truly_processed vs stage_f_harmonization_2026-06-23.md |
| MGDS:24367 | eval_only | FK181031 | 30.0 | FK181031__MGDS_24367 | lu08 | in corpus | manifest/pairs.parquet |
| MGDS:24467 | eval_only | TN313 | 31.1 |  |  | REASON UNRECORDED: LR cruise fetched (TN313) but the HR never appears in stage C/C.5 results | stage_b_fetch_list_2026-06-22.csv |
| MGDS:24470 | eval_only | TN268 | 28.6 |  |  | excluded: 0 valid tiles after F5 real-data masks (f5_bucket=weak_exclude_candidate) -> R6 zero-tile drop | stage_reaudit_moveforward_report_2026-06-26.md |
| MGDS:29779 | eval_only | RR1506 | 25.0 | RR1506__MGDS_29779 | lu00 | in corpus | manifest/pairs.parquet |
| MGDS:30373 | eval_only | TN399 | 35.0 | TN399__MGDS_30373 | lu05 | in corpus | manifest/pairs.parquet |
| MGDS:31181 | eval_only | TN399 | 35.0 |  |  | excluded: HR and gridded LR have no real data overlap on the AUV-native grid (C.5b status=empty_overlap) | stage_c5b_sweep.json |
| MGDS:31193 | eval_only | TN365 | 32.5 |  |  | excluded: inflated (degree-wide bbox) HR footprint -> false pair, no real HR/LR overlap (C.5b Track C; discovery footprint-bbox bug) | stage_c5b_consolidation_report_2026-06-23.md |
| MGDS:31212 | eval_only | NA090 | 35.0 | NA090__MGDS_31212 | lu10 | in corpus | manifest/pairs.parquet |
| MGDS:31290 | eval_only | NA080 | 35.0 | NA080__MGDS_31290 | lu13 | in corpus | manifest/pairs.parquet |
| MGDS:31321 | eval_only | EX1202L3 | 26.2 |  |  | REASON UNRECORDED: phase-1 'truly processed LR' pair (LR NCEI_MBBDB:EX1202L3 processed grid staged); stage A dry-run said these skip gridding and go to Stage F directly, but Stage F only harmonized the 32 C.5c pairs; never harmonized, never ruled on | stage_a_gate1_raw_lr_dryrun_20260622.md §truly_processed vs stage_f_harmonization_2026-06-23.md |
| MGDS:31753 | eval_only | 2010_Amundsen | 30.1 |  |  | excluded: float re-harvest has 0 joint cells with the 2009_Amundsen LR (false co-location by footprint; C1 step 2 L2) | stage_c1_reharvest_step2_rulings_2026-06-26.md |
| MGDS:31813 | eval_only | NR07-1 | 28.8 |  |  | REASON UNRECORDED: phase-1 'truly processed LR' pair (LR NCEI_MBBDB:NR07-1 processed grid staged); stage A dry-run said these skip gridding and go to Stage F directly, but Stage F only harmonized the 32 C.5c pairs; never harmonized, never ruled on | stage_a_gate1_raw_lr_dryrun_20260622.md §truly_processed vs stage_f_harmonization_2026-06-23.md |
| MGDS:31814 | eval_only | NR07-1 | 28.2 |  |  | REASON UNRECORDED: phase-1 'truly processed LR' pair (LR NCEI_MBBDB:NR07-1 processed grid staged); stage A dry-run said these skip gridding and go to Stage F directly, but Stage F only harmonized the 32 C.5c pairs; never harmonized, never ruled on | stage_a_gate1_raw_lr_dryrun_20260622.md §truly_processed vs stage_f_harmonization_2026-06-23.md |
| MGDS:31831 | eval_only | EX1206 | 35.0 |  |  | REASON UNRECORDED: phase-1 'truly processed LR' pair (LR NCEI_MBBDB:EX1206 processed grid staged); stage A dry-run said these skip gridding and go to Stage F directly, but Stage F only harmonized the 32 C.5c pairs; never harmonized, never ruled on | stage_a_gate1_raw_lr_dryrun_20260622.md §truly_processed vs stage_f_harmonization_2026-06-23.md |
| MGDS:32007 | eval_only | AT42-03 | 25.0 | AT42-03__MGDS_32007 | lu03 | in corpus | manifest/pairs.parquet |
| MGDS:7832 | eval_only | FK160407 | 36.5 |  |  | excluded: 0 valid tiles after F5 real-data masks (f5_bucket=weak_exclude_candidate) -> R6 zero-tile drop | stage_reaudit_moveforward_report_2026-06-26.md |
| MANIFEST:cal_dig_morro_bay__201804_LuciaChica2m | raw_lr_to_grid | KIWI01RR |  | cal_dig_morro_bay__201804_LuciaChica2m | lu12 | in corpus | manifest/pairs.parquet |
| MANIFEST:cal_dig_morro_bay__20190314m4_LuciaChica970m | raw_lr_to_grid | EW0407 |  | cal_dig_morro_bay__20190314m4_LuciaChica970m | lu12 | in corpus | manifest/pairs.parquet |
| MANIFEST:cal_dig_morro_bay__20190511m1_6thHeadlessCany | raw_lr_to_grid | RNDB18WT |  | cal_dig_morro_bay__20190511m1_6thHeadlessCany | lu12 | in corpus | manifest/pairs.parquet |
| MGDS:20836 | raw_lr_to_grid | FK006B |  |  |  | dropped: the MGDS 'grid' file is a PDF, not bathymetry (phase 1 rev3 escalated recover_or_drop) | staging_state.phase1_rev3 |
| MGDS:21981 | raw_lr_to_grid | TN159 |  | TN159__MGDS_21981 | lu17 | in corpus | manifest/pairs.parquet |
| MGDS:21986 | raw_lr_to_grid | TN159 |  |  |  | excluded: no recoverable SR signal at any k on the AUV-native grid (C.5b max_recoverable_k=null) | stage_c5b_sweep.json |
| MGDS:21996 | raw_lr_to_grid | TN157 |  |  |  | excluded: residual co-registration failure (LR coverage / CRS edge case), recommended manual pass, never done (C.5c) | stage_c5c_consolidation_report_2026-06-23.md |
| MGDS:21998 | raw_lr_to_grid | TN159 |  |  |  | excluded: residual co-registration failure (LR coverage / CRS edge case), recommended manual pass, never done (C.5c) | stage_c5c_consolidation_report_2026-06-23.md |
| MGDS:22436 | raw_lr_to_grid | KN210-05 |  |  |  | dropped at manifest append: 151 m offset, no interior NCC peak (unconfirmed_coregistration_eligible_for_manual_recoreg; not data-quality, eligible for manual re-coreg) | stage_append_exclusions_2026-06-26.csv |
| MGDS:24425 | raw_lr_to_grid | RR0916 |  |  |  | dropped: the MGDS 'grid' file is a PDF, not bathymetry (phase 1 rev3 escalated recover_or_drop) | staging_state.phase1_rev3 |
| MGDS:24485 | raw_lr_to_grid | FK171110 |  |  |  | excluded: HR source is a 3-band RGB render (no elevation band); float companion MGDS:24499 acquired instead as KIWI10RR__MGDS_24499 | stage_reaudit_report_2026-06-26.md + stage_reaudit_c1_float_recovery.csv |
| MGDS:24489 | raw_lr_to_grid | TN234 |  |  |  | TN234 EM300 vendor files read 0 good beams -> LR has no usable bathymetry (stage C full report §4) | stage_c_full_report_2026-06-23.md |
| MGDS:24499 | raw_lr_to_grid | KIWI10RR |  | KIWI10RR__MGDS_24499 | lu01 | in corpus | manifest/pairs.parquet |
| MGDS:24620 | raw_lr_to_grid | FK181031 |  |  |  | excluded: HR source is a 3-band RGB render (no elevation band); float companion MGDS:24618 acquired instead as FK181031__MGDS_24618 (C1 float recovery) | stage_reaudit_report_2026-06-26.md + stage_reaudit_c1_float_recovery.csv |
| MGDS:27340 | raw_lr_to_grid | RP11SU81 |  |  |  | not fetched: only LR cruise (RP11SU81) is a legacy SeaBeam-classic format the swath classifier does not recognise (stage B needs_format_review); no later ruling recorded | stage_b_fetch_report_2026-06-22.md |
| MGDS:29694 | raw_lr_to_grid | TN383 |  |  |  | excluded: HR source is a 3-band RGB render (no elevation band); float companion MGDS:32556 acquired instead as EW0207__MGDS_32556 (NRift) + supersedes HR of TN268__MGDS_30466 (SRift ver2025) | stage_reaudit_report_2026-06-26.md + stage_reaudit_c1_float_recovery.csv |
| MGDS:30045 | raw_lr_to_grid | 2009_Amundsen |  |  |  | excluded: HR source is a 3-band RGB render (no elevation band); float companion MGDS:30046 acquired instead as 2009_Amundsen__MGDS_30046 (C1 float recovery) | stage_reaudit_report_2026-06-26.md + stage_reaudit_c1_float_recovery.csv |
| MGDS:30217 | raw_lr_to_grid | EW9904 |  |  |  | excluded: HR source is a 3-band RGB render (no elevation band); float companion MGDS:32556 acquired instead as EW0207__MGDS_32556 (NRift) + supersedes HR of TN268__MGDS_30466 (SRift ver2025) | stage_reaudit_report_2026-06-26.md + stage_reaudit_c1_float_recovery.csv |
| MGDS:30270 | raw_lr_to_grid | 2010_Amundsen |  |  |  | excluded: degenerate shallow 2010_Amundsen pair, no spectrum / not recoverable at any k (C.5/C.5b) | stage_c5b_sweep.json |
| MGDS:30369 | raw_lr_to_grid | Escanaba |  |  |  | excluded: HR and gridded LR have no real data overlap on the AUV-native grid (C.5b status=empty_overlap) | stage_c5b_sweep.json |
| MGDS:30467 | raw_lr_to_grid | RP11SU81 |  |  |  | not fetched: only LR cruise (RP11SU81) is a legacy SeaBeam-classic format the swath classifier does not recognise (stage B needs_format_review); no later ruling recorded | stage_b_fetch_report_2026-06-22.md |
| MGDS:31059 | raw_lr_to_grid | PASC02WT |  |  |  | not fetched: only LR cruise (PASC02WT) is a legacy SeaBeam-classic format the swath classifier does not recognise (stage B needs_format_review); no later ruling recorded | stage_b_fetch_report_2026-06-22.md |
| MGDS:31256 | raw_lr_to_grid | TN299 |  |  |  | excluded: HR source is a 3-band RGB render (no elevation band); float companion MGDS:31253 acquired instead as TN299__MGDS_31253 (C1 float recovery; catalog listed it under TN313) | stage_reaudit_report_2026-06-26.md + stage_reaudit_c1_float_recovery.csv |
| MGDS:31291 | raw_lr_to_grid | NA080 |  |  |  | REASON UNRECORDED: C.5b scored it recoverable (max_k=16) but it is absent from the stage-E corpus and from every exclusion record | stage_c5b_sweep.json vs combined_corpus.csv |
| MGDS:31427 | raw_lr_to_grid | TUNE04WT |  |  |  | not fetched: only LR cruise (TUNE04WT) is a legacy SeaBeam-classic format the swath classifier does not recognise (stage B needs_format_review); no later ruling recorded | stage_b_fetch_report_2026-06-22.md |
| MGDS:31430 | raw_lr_to_grid | AII8L11 |  |  |  | not fetched: only LR cruise (AII8L11) is a legacy SeaBeam-classic format the swath classifier does not recognise (stage B needs_format_review); no later ruling recorded | stage_b_fetch_report_2026-06-22.md |
| MGDS:31675 | raw_lr_to_grid | KN204-01 |  |  |  | dropped at manifest append: 51 m offset, no interior NCC peak (unconfirmed_coregistration_eligible_for_manual_recoreg; not data-quality, eligible for manual re-coreg) | stage_append_exclusions_2026-06-26.csv |
| MGDS:31755 | raw_lr_to_grid | 2010_Amundsen |  |  |  | excluded: degenerate shallow 2010_Amundsen pair, no spectrum / not recoverable at any k (C.5/C.5b) | stage_c5b_sweep.json |
| MGDS:31824 | raw_lr_to_grid | PASC04WT |  |  |  | not fetched: only LR cruise (PASC04WT) is a legacy SeaBeam-classic format the swath classifier does not recognise (stage B needs_format_review); no later ruling recorded | stage_b_fetch_report_2026-06-22.md |
| MGDS:31860 | raw_lr_to_grid | RC2901 |  |  |  | not fetched: only LR cruise (RC2901) is a legacy SeaBeam-classic format the swath classifier does not recognise (stage B needs_format_review); no later ruling recorded | stage_b_fetch_report_2026-06-22.md |
| MGDS:31949 | raw_lr_to_grid | Channel |  |  |  | excluded: inflated (degree-wide bbox) HR footprint -> false pair, no real HR/LR overlap (C.5b Track C; discovery footprint-bbox bug) | stage_c5b_consolidation_report_2026-06-23.md |
| MGDS:32240 | raw_lr_to_grid | RC2511 |  |  |  | excluded: 0 valid tiles after F5 real-data masks (f5_bucket=weak_exclude_candidate) -> R6 zero-tile drop | stage_reaudit_moveforward_report_2026-06-26.md |
| MGDS:32241 | raw_lr_to_grid | RC2511 |  |  |  | excluded: HR source is a 3-band RGB render (no elevation band); float companion MGDS:32240 not in corpus (companion had 0 valid tiles after F5 masks -> R6 zero-tile drop) | stage_reaudit_report_2026-06-26.md + stage_reaudit_c1_float_recovery.csv |
| MGDS:32558 | raw_lr_to_grid | EW0207 |  |  |  | excluded: HR source is a 3-band RGB render (no elevation band); float companion MGDS:32556 acquired instead as EW0207__MGDS_32556 (NRift) + supersedes HR of TN268__MGDS_30466 (SRift ver2025) | stage_reaudit_report_2026-06-26.md + stage_reaudit_c1_float_recovery.csv |
| MGDS:7833 | raw_lr_to_grid | EW9914 |  |  |  | not fetched: only LR cruise (EW9914) is a legacy SeaBeam-classic format the swath classifier does not recognise (stage B needs_format_review); no later ruling recorded | stage_b_fetch_report_2026-06-22.md |
| MANIFEST:cal_dig_morro_bay__20180427m1_Channel700 | training | NA073 | 17.5 | cal_dig_morro_bay__20180427m1_Channel700 | lu12 | in corpus | manifest/pairs.parquet |
| MANIFEST:cal_dig_morro_bay__20180427m3_PockmarkNorth | training | MV1405 | 25.0 | cal_dig_morro_bay__20180427m3_PockmarkNorth | lu12 | in corpus | manifest/pairs.parquet |
| MANIFEST:cal_dig_morro_bay__20190317m1_1000mGully | training | SR1903 | 25.0 | cal_dig_morro_bay__20190317m1_1000mGully | lu12 | in corpus | manifest/pairs.parquet |
| MANIFEST:cal_dig_morro_bay__20190510m2_BankFlankIncipCh | training | SR1903 | 12.5 | cal_dig_morro_bay__20190510m2_BankFlankIncipCh | lu12 | in corpus | manifest/pairs.parquet |
| MANIFEST:cal_dig_morro_bay__20190511m2_BankTopEofCanyon3 | training | DRFT01RR | 25.0 | cal_dig_morro_bay__20190511m2_BankTopEofCanyon3 | lu12 | in corpus | manifest/pairs.parquet |
| MGDS:17700 | training | MGLN06MV | 19.5 |  |  | declined by Steve at the R3 QC adjudication (2026-06-26) | stage_provenance_gate_report_2026-06-26.md |
| MGDS:18210 | training | EX1103 | 15.0 |  |  | excluded: inflated (degree-wide bbox) HR footprint -> false pair, no real HR/LR overlap (C.5b Track C; discovery footprint-bbox bug) | stage_c5b_consolidation_report_2026-06-23.md |
| MGDS:20811 | training | FK006B | 15.9 |  |  | dropped at manifest append: PSR=-8.97, degenerate peak (unconfirmed_coregistration_eligible_for_manual_recoreg; not data-quality, eligible for manual re-coreg) | stage_append_exclusions_2026-06-26.csv |
| MGDS:20815 | training | EX1202L2 | 18.8 |  |  | REASON UNRECORDED: phase-1 'truly processed LR' pair (LR NCEI_MBBDB:EX1202L2 processed grid staged); stage A dry-run said these skip gridding and go to Stage F directly, but Stage F only harmonized the 32 C.5c pairs; never harmonized, never ruled on | stage_a_gate1_raw_lr_dryrun_20260622.md §truly_processed vs stage_f_harmonization_2026-06-23.md |
| MGDS:21415 | training | MV1209 | 6.1 |  |  | excluded: HR and gridded LR have no real data overlap on the AUV-native grid (C.5b status=empty_overlap) | stage_c5b_sweep.json |
| MGDS:21462 | training | AT18-11 | 24.8 |  |  | AT18-11 gridding failed: HR footprint (2 deg wide, inflated) has no ship coverage -> false pair (stage C full report §4) | stage_c_full_report_2026-06-23.md |
| MGDS:21847 | training | lostcity2005 | 10.0 |  |  | REASON UNRECORDED: phase-1 'truly processed LR' pair (LR NCEI_MBBDB:lostcity2005 processed grid staged); stage A dry-run said these skip gridding and go to Stage F directly, but Stage F only harmonized the 32 C.5c pairs; never harmonized, never ruled on | stage_a_gate1_raw_lr_dryrun_20260622.md §truly_processed vs stage_f_harmonization_2026-06-23.md |
| MGDS:24756 | training | RB1604 | 25.0 |  |  | excluded: residual co-registration failure (LR coverage / CRS edge case), recommended manual pass, never done (C.5c) | stage_c5c_consolidation_report_2026-06-23.md |
| MGDS:27339 | training | TN299 | 15.0 | TN299__MGDS_27339 | lu15 | in corpus | manifest/pairs.parquet |
| MGDS:30219 | training | TN268 | 15.0 |  |  | declined by Steve at the R3 QC adjudication (2026-06-26) | stage_provenance_gate_report_2026-06-26.md |
| MGDS:30272 | training | 2010_Amundsen | 15.0 |  |  | dropped: MGDS download returns an HTML error page on both endpoints (phase 1 rev3 escalated recover_or_drop) | staging_state.phase1_rev3 |
| MGDS:30466 | training | TN268 | 15.0 | TN268__MGDS_30466 | lu16 | in corpus | manifest/pairs.parquet |
| MGDS:31073 | training | EX1402L2 | 15.0 |  |  | REASON UNRECORDED: phase-1 'truly processed LR' pair (LR NCEI_MBBDB:EX1402L2 processed grid staged); stage A dry-run said these skip gridding and go to Stage F directly, but Stage F only harmonized the 32 C.5c pairs; never harmonized, never ruled on | stage_a_gate1_raw_lr_dryrun_20260622.md §truly_processed vs stage_f_harmonization_2026-06-23.md |
| MGDS:31188 | training | TN268 | 15.0 |  |  | excluded: HR and gridded LR have no real data overlap on the AUV-native grid (C.5b status=empty_overlap) | stage_c5b_sweep.json |
| MGDS:31199 | training | AT37-13 | 25.0 | AT37-13__MGDS_31199 | lu04 | in corpus | manifest/pairs.parquet |
| MGDS:31253 | training | TN313 | 24.0 | TN299__MGDS_31253 (C1 float recovery; catalog listed it under TN313) | lu15 | in corpus | manifest/pairs.parquet |
| MGDS:31254 | training | SKQ201705S | 18.5 |  |  | declined by Steve at the R3 QC adjudication (2026-06-26) | stage_provenance_gate_report_2026-06-26.md |
| MGDS:31255 | training | SKQ201705S | 18.8 |  |  | declined by Steve at the R3 QC adjudication (2026-06-26) | stage_provenance_gate_report_2026-06-26.md |
| MGDS:31425 | training | EW9801 | 17.1 | EW9801__MGDS_31425 | lu07 | in corpus | manifest/pairs.parquet |
| MGDS:31600 | training | KN180L02 | 10.2 |  |  | quarantined: declared 9.8 m grid measures 2.8 m cells -> coarse_or_composite (phase 1 rev2) | staging_state.phase1_rev2 |
| MGDS:31811 | training | EX1103 | 7.5 |  |  | excluded: inflated (degree-wide bbox) HR footprint -> false pair, no real HR/LR overlap (C.5b Track C; discovery footprint-bbox bug) | stage_c5b_consolidation_report_2026-06-23.md |
| MGDS:31838 | training | AR26 | 20.0 | AR26__MGDS_31838 | lu14 | in corpus | manifest/pairs.parquet |
| MGDS:32321 | training | NA076 | 15.0 |  |  | excluded: HR source is a 3-band RGB render (no elevation band); float companion MGDS:32317 acquired instead as NA076__MGDS_32317 (C1 float recovery) | stage_reaudit_report_2026-06-26.md + stage_reaudit_c1_float_recovery.csv |
| MGDS:32556 | training | TN268 | 15.0 | EW0207__MGDS_32556 (NRift) + supersedes HR of TN268__MGDS_30466 (SRift ver2025) | lu16 | in corpus | manifest/pairs.parquet |
| MGDS:5174 | training | AT42-06 | 10.0 |  |  | REASON UNRECORDED: C.5b scored it recoverable (max_k=2) but it is absent from the stage-E corpus and from every exclusion record | stage_c5b_sweep.json vs combined_corpus.csv |
| PANGAEA:tag_m127 | training | EX2206 | 17.5 | tag_m127 | lu09 | in corpus | manifest/pairs.parquet |

## Gate-excluded HR (25; recorded at the gate)

| hr_id | tier_reason |
|---|---|
| MGDS:16792 | CRS recovery: inferred CRS failed verification against MGDS ISO bbox — recovered extent landed outside the stated geographic region |
| MGDS:22383 | ratio 60.0 > 40.0 (super-resolution not meaningful) |
| MGDS:24043 | ratio 50.0 > 40.0 (super-resolution not meaningful) |
| MGDS:32208 | ratio 50.0 > 40.0 (super-resolution not meaningful) |
| MGDS:24424 | ratio 100.0 > 40.0 (super-resolution not meaningful) |
| MGDS:30832 | ratio 60.0 > 40.0 (super-resolution not meaningful) |
| MGDS:24618 | ratio 60.0 > 40.0 (super-resolution not meaningful) |
| MGDS:30198 | ratio 100.0 > 40.0 (super-resolution not meaningful) |
| MGDS:22384 | CRS recovery: grid header ranges fit neither geographic nor UTM pattern cleanly, or no ISO bbox available to verify any inferred CRS — recovery declined |
| MGDS:30193 | ratio 100.0 > 40.0 (super-resolution not meaningful) |
| MGDS:31203 | ratio 50.0 > 40.0 (super-resolution not meaningful) |
| MGDS:30085 | ratio 100.0 > 40.0 (super-resolution not meaningful) |
| MGDS:30092 | ratio 100.0 > 40.0 (super-resolution not meaningful) |
| MGDS:30046 | ratio 60.2 > 40.0 (super-resolution not meaningful) |
| MGDS:31954 | ratio 50.0 > 40.0 (super-resolution not meaningful) |
| MGDS:24449 | CRS recovery: grid header ranges fit neither geographic nor UTM pattern cleanly, or no ISO bbox available to verify any inferred CRS — recovery declined |
| MANIFEST:cal_dig_morro_bay__20190318m2_Transect601060m | ratio 58.3 > 40.0 (super-resolution not meaningful) |
| MANIFEST:cal_dig_morro_bay__pockmark_south | ratio 50.0 > 40.0 (super-resolution not meaningful) |
| MANIFEST:cal_dig_morro_bay__luciachica_2007 | ratio 60.0 > 40.0 (super-resolution not meaningful) |
| MANIFEST:cal_dig_morro_bay__basin_flank | ratio 50.0 > 40.0 (super-resolution not meaningful) |
| MANIFEST:cal_dig_morro_bay__20190315m1_HeadlessCanyon | ratio 49.1 > 40.0 (super-resolution not meaningful) |
| MANIFEST:cal_dig_morro_bay__20180426m2_Channel1000 | ratio 60.0 > 40.0 (super-resolution not meaningful) |
| MANIFEST:cal_dig_morro_bay__20190316m1_BankTop | ratio 50.0 > 40.0 (super-resolution not meaningful) |
| MANIFEST:cal_dig_morro_bay__20180428m1_Cable | ratio 50.0 > 40.0 (super-resolution not meaningful) |
| MANIFEST:cal_dig_morro_bay__20190510m1_BankFlankHoles | ratio 50.0 > 40.0 (super-resolution not meaningful) |