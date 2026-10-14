# REPORT ACQ-R11b — vertical-datum check added (line check: fallback), re-rehearsed, re-frozen

**Directive:** `ACQ-R11b_directive_line_and_datum_checks_refreeze_2026-10-13.md`.
**New freeze:** `reports_post_grl_review/PHASE5/freeze_record_phase5_v2.json`
- sha256 **`f5a30b87c05a90bb9155f37bbdf61de6d20fa55423d97662e59ff42b02809438`** (66 files);
- entry script `src/phase5/sealed_step1_p5.py` sha256 **`83af2875e53a28ef9b01c95a7b533ef7befd7a00625dfa6b0fe87178a2accc47`**;
- code commit `f88e21c`; tag **`phase5-acq-freeze-v2`**.

`freeze_record_phase5.json` (`67695831…`) is kept unchanged; the v2 record cites it under `supersedes`.
**Fallback applied (§0.2 / §2.3).** Ship line-to-line inconsistency is **unchecked** for v3.1.

No sealed candidate file was opened, no Phase 5 swath was fetched, and phase5 mode was not run. No Phase 4 file, ACQ-R09 file, `src/acq_r11/` file or CNN file changed.

## Bullets

1. **Line check L: fallback (CONFIRMED).**
   - §1.2.1 needs each pair's LR grid lattice: the `mbgrid` cell, region and origin. Only **2 of 38** accepted pairs have it on disk with their raw swath:
     - FK151121__MGDS_22383 (ACQ-R02 grid record + `FK151121__union.grd` on OAK);
     - 2009_Amundsen__MGDS_30046 (R5 `lrv2_1` record + grid on OAK).
   - The other 36 are not computable:
     - **21 provider grids:** 18 Cal DIG, CCZ, DISCOL, TAG.
     - **15 June-era MGDS pairs:** their LR grids came from `stage_c_full` / the C1 reharvest. Those union grids are no longer on scratch or OAK, and the records keep only a rounded cell, no `-R`/`-E`. TN268 and KIWI10RR also have no swath on OAK.
   - 2 < 10, so §2.3 sends the directive to the pre-approved fallback, and no L or d_f was computed. Even counting NA080_31290 and TN399_30373 (their cruise has an ACQ-R02 grid, but their own `lr.tif` is from June) gives only 4.
   - Per-pair status and reason: `vcheck_calibration_v2.csv`.
2. **Datum check G (CONFIRMED).**
   - T_G = 3 × 0.066904 (2009_Amundsen__MGDS_30047) = **0.200712**.
   - NR07-1__MGDS_31813 (0.378) and NR07-1__MGDS_31814 (0.394) are above T_G. All 45 development-designated rows are below it (max 0.0669).
   - AT37-05 (0.0273) is below T_G, as expected: its fault is the unchecked line inconsistency.
   - The G values are ACQ-R11's (`src/acq_r11/vcheck.py` `5a2c65d4…`; table `b7f3732d…`, hash-checked). Table v2: `ACQ-R11b/vcheck_calibration_v2.csv` sha256 **`41973318d9ac55cffc7baa3f57a359da2538f2fd0a7a3a952d39770a14b7d8b2`**; summary `vcheck_calibration_v2.json`.
3. **Code (diff against `phase5-acq-freeze`: 9 files, +244 / −30; commits `8d795a7`, `f88e21c`).**
   - **`vcheck_p5.py`** (new): a byte copy of `src/acq_r11/vcheck.py`; `chain_p5` asserts its sha256 at import.
   - **`chain_p5.harmonize`:** after the masks, `datum_check = gate(hr, lr, joint_valid, T_G)` keeps booleans and words only.
   - **`chain_p5.eligibility`:** `coreg_pass = qa_pass AND datum_ok`, and the reasons are prefixed `co-registration:` / `vertical datum:`.
   - **`common_p5`:**
     - `T_G` with the table sha256 in a comment;
     - the table as a hash-checked fixed input;
     - `"v95"` and two more parts added to the forbidden keys;
     - run-time records moved to `ACQ-R11b/` and scratch `ACQ-R11b/` (so ACQ-R09's records stay untouched);
     - `FREEZE_RECORD` = v2.
   - **`sealed_step1_p5`:** `per_pair.vertical_datum_ok` added, and the label and rulings updated.
   - **Other files:**
     - `mock_p5`: the NR07-1 control added;
     - `freeze_p5` / `preserve_p5`: v2 and ACQ-R11b paths;
     - refusal suite: tests B1–B4 added;
     - `blind_test_p5.py` (new).
   - Supplement schema unchanged (64 + 6).
4. **Re-rehearsal (§4.1; CONFIRMED).** Final run `ACQ-R11b/rehearsal/step1_run_rehearsal_r11b.json` (sha256 `11949c48…`, job 47704841): lock 2 passed against freeze v2 before and after (66 files, 55 loaded modules); guard self-test 84/84 + 288/288 blocked.
   - **NA080__MGDS_31289, KM0923__MGDS_31429:** bit-identical to development (ship grid, hr/lr, masks, all product rasters, values; `compare_r11b.json`).
   - **FK151121:** differs on region as in ACQ-R09, and is bit-identical under the S3 harness (`harness_fk151121_r11b.json`).
   - Every raster and footprint file in all four ACQ-R09 sites has the same sha256 as the ACQ-R09 r09 run. Only run metadata differs: sandbox paths in commands, wall time, `.grd` header hashes, and the regenerated gzip of the mock repeat copy.
   - `coreg_pass` = true for NA080, KM0923, FK151121 (run and harness); repeat rule and schema pass.
5. **Positive control (§4.2; CONFIRMED).** NR07-1__MGDS_31813 → `coreg_pass` false, **not testable**, reason "co-registration: offset above the 30 m development bound; vertical datum: HR-ship vertical consistency above the calibrated bound T_G".
   - It also fails co-registration, as in development (41.6 m).
   - The datum part is shown independently by refusal test B2: datum fails with qa passing gives a "vertical datum" reason only.
   - There is no AT37-05 control (fallback).
6. **Blindness, CNN lock copy, refusal suite (§4.3–4.4; CONFIRMED).**
   - **Blindness test** `blind_test_r11b.json`: 5 pairs, 112 printed forms of V95 / V95_rel, 52 files (run record, supplement, site and product records, rehearsal records, the job's `.out`/`.err`). 0 value hits, 0 forbidden keys, and the gate returns only booleans and words.
     - The pre-run version reported 2 false value hits ("30.28" inside the UTM coordinate `526230.284…`) and 5 false key hits (the site record's file-name map, `ship_median_regrid.tif`). It now matches whole numbers only and skips that map (commit `f88e21c`, before the freeze).
   - **CNN lock copy** `cnn_lock_check_r11b.json`: accepts the r11b record against freeze v2; refuses a wrong supplement sha, a wrong freeze sha and the empty `PHASE5/`; k class `sweep` agrees for 5/5; row_status ok 5/5. The CNN `phase4/` and `phase5/` directories are unchanged in git status.
     - The job's own call failed because I passed a relative freeze path (the copy runs with its working directory on scratch). I re-ran it by hand with absolute paths, and the job script now uses them.
   - **Refusal suite** `ACQ-R11b/refusal_tests_p5.json`: **65/65**. That is 19 lock tests, plus 42 guard tests (ACQ-R09's 41 + one admission case for the added mock site), plus B1–B4.
7. **CNN side (§6.5; read only).** In `phase5/scripts/phase5_common.py`:
   - l.47: `ACQ_FREEZE_RECORD = f"{ACQ_RECORDS_DIR}/freeze_record_phase5_v2.json"` and `ACQ_FREEZE_SHA = "f5a30b87c05a90bb9155f37bbdf61de6d20fa55423d97662e59ff42b02809438"`.
   - l.48: `ACQ_STEP1_SHA = "83af2875e53a28ef9b01c95a7b533ef7befd7a00625dfa6b0fe87178a2accc47"`.
   - l.134 (code unchanged): requires v3.1's text to state the new `ACQ_FREEZE_SHA`.
   - `eligibility()` (l.155–164) needs no change: it recomputes `eligible` from `coreg_pass`, which now includes the datum check.

   **v3.1 B1 item 1 wording (PREREG l.35):** "co-registration passes the development QA thresholds (ACQ-R03: offset ≤ 30 m, overlap ≥ 1 km², ≥ 1 256-px tile with ≥ 50 % joint-valid cells) **and the vertical-datum check (ACQ-R11b): on the ship grid's joint-valid cells, the 95th percentile of |r − median r|, where r is the area-averaged high-resolution field minus the ship field after the rigid shift, divided by |median ship depth| there, is ≤ T_G = 0.200712 (calibrated on development pairs only). Ship line-to-line inconsistency is not checked.**"

   The blindness sentence (PREREG l.47) should add "and the vertical-datum check", with "only its pass/fail is recorded".
8. **Freeze and preservation (§5).**
   - Commits are by explicit path; freeze record `0572c58`; tag `phase5-acq-freeze-v2`.
   - `sbatch/acq_r10/step1.sbatch` is re-issued against freeze v2 and the new tag, and left uncommitted. Its `PREREG` / `SIGNOFF` lines still name v3 and must point to v3.1 when ACQ-R10 is re-run.
   - One `CHANGE_LEDGER.md` row.
   - OAK copy: `acq_archive/ACQ-R11b/` with `SHA256SUMS` verified (`preserve_verify.json`).
   - Rehearsal rasters stay on `$GROUP_SCRATCH/…/ACQ-R11b/` (subject to the 90-day purge).

## Calibration tables

**G (datum), T_G = 0.200712**: every row's value is in `vcheck_calibration_v2.csv` (and ACQ-R11's table).

| group | rows | G min | G max | vs T_G |
|---|---|---|---|---|
| accepted development | 38 | 0.000499 (ccz_so268_1) | 0.032748 (EW9801) | all below |
| info development | 7 | 0.001007 (TN399_33068) | 0.066904 (2009_Amundsen_30047) | all below |
| known-bad NR07-1__MGDS_31813 / _31814 | 2 | 0.378024 | 0.393518 | **above** |
| known-bad AT37-05 | 1 | 0.027343 | | below (line fault; unchecked) |
| known-bad MGLN06MV | — | COULD NOT CHECK | | no ship data on disk |

**L (line), T_L: not set (fallback).**

| L status (accepted, n = 38) | n |
|---|---|
| computable (FK151121, 2009_Amundsen_30046), not computed | 2 |
| not computable: provider grid | 21 |
| not computable: June LR lattice not recorded / grid gone (2 also without swath) | 15 |

## HOLDs

- **H-1 (carried, no action here): ship line-to-line inconsistency is unchecked in Phase 5.** This is the approved fallback. The only remaining screen is the v3 B3 blind artifact call (and the `vertical_offset` product flag, which affects usability only). If a line check is wanted later, the June LR lattices would have to be rebuilt (re-gridding 15 cruises with re-derived parameters, checked against `lr.tif`), which needs its own directive.
- **H-2: the next steps sit in the CNN repo.** That means the v3.1 amendment, the constants at l.47–48, the re-signed sign-off, then the ACQ-R10 re-run with the v3.1 sign-off.
