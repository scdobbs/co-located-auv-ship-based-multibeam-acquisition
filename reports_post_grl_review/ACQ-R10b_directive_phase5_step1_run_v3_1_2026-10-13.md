# DIRECTIVE ACQ-R10b (acquisition repo): Phase 5 step 1 on the eight sealed sites, under v3.1 and freeze v2

**Date:** 2026-10-13
**Repo:** `co-located-auv-ship-based-multibeam-acquisition`
**Report to:** `reports_post_grl_review/ACQ-R10b/REPORT_ACQ-R10b_<date>.md`
**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.
**Report length:** at most 8 bullets, plus the site table and at most 3 HOLDs.

## 0. Purpose and what changed from ACQ-R10

Run the frozen Phase 5 step-1 code (`src/phase5/sealed_step1_p5.py`, sha256
`83af2875e53a28ef9b01c95a7b533ef7befd7a00625dfa6b0fe87178a2accc47`; tag `phase5-acq-freeze-v2`; freeze record
`reports_post_grl_review/PHASE5/freeze_record_phase5_v2.json`, sha256
`f5a30b87c05a90bb9155f37bbdf61de6d20fa55423d97662e59ff42b02809438`) in phase5 mode on the eight sites of
`inputs/phase5_sites.csv`, under signed pre-registration v3.1 (`R16c/PREREG_phase5_v3_1.md` in the CNN repo, sha256
`75b72eb6fae3804c7dea61aa4171744a2fcd4fbdb7c3916f3fb98f2c06f2c7b6`, tag `phase5-prereg-v3.1`).

ACQ-R10 stopped at its precondition §1.5 before any fetch. Its report stays as it is. This directive is ACQ-R10 with
only these changes: v3.1 and its sign-off in place of v3; freeze v2 in place of freeze v1; and §1.5 updated for
Steve's rulings on ACQ-R10 H-1 (the datum check, ACQ-R11b) and ACQ-R11b H-1 (ship line-to-line inconsistency is
unchecked, as v3.1 B1 states).

**Blindness.** Steve stays blind to every candidate amplitude, depth statistic, target, feature and image until his
artifact calls are committed (v3.1 B3). The report carries only the fields `src/phase5/report_p5.py` writes: status,
eligibility fields, spacings, cells across, k, product status and usability, file counts and sha256. No QC figure,
hillshade, preview or plot is made. No person views any candidate data, and co-registration and datum pass or fail
are decided by the automated thresholds only.

**No code change.** Nothing under `src/phase5/` or the development chain is edited. Any stop is a HOLD.

**Challenge clause.** If any instruction here is wrong or underspecified against the code or the files, stop at
that point, give the evidence, and report it as a HOLD. Do not work around it.

## 1. Preconditions (read only; any failure stops the directive)

1. In the CNN repo (read only): `R16c/PREREG_phase5_v3_1.md` hashes to `75b72eb6…` and equals the file at tag
   `phase5-prereg-v3.1`; `R16c/SIGNOFF_phase5_prereg_v3_1.md` is committed, signed, and its first 64-hex string is
   `75b72eb6…`; `phase5/scripts/phase5_common.py` hashes to
   `cdca2c9b699f8a06eb29bc095d3c3636304cabfb941c88a22fdae8b555df1b66`.
2. In this repo: the freeze record hashes to `f5a30b87…`; every file it lists hashes as listed; `src/phase5/` is
   clean in git and equal to tag `phase5-acq-freeze-v2`.
3. The acquisition guard self-test passes before any other step (report the probe count), with
   `sealed_candidates_v3` and the Phase 5 output roots sealed.
4. `reports_post_grl_review/PHASE5/` holds no `step1_run_phase5_*.json` in phase5 mode;
   `manifest/pairs_phase5_sealed.parquet` does not exist.
5. **Manual steps.** Restate ACQ-R10's list of development-chain steps that a person decided or edited, with the
   automated rule Phase 5 uses for each, from the freeze v2 code. Expected:
   - co-registration review: the ACQ-R03 QA thresholds;
   - gross HR/ship vertical mismatch (row 9): the datum check, T_G = 0.200712 (ACQ-R11b);
   - ship line-to-line inconsistency (row 10): **unchecked by Steve's ruling**, stated in v3.1 B1. This is not a
     stop. Record it in the report.

   Any other step with no automated equivalent stops the directive as a HOLD.
6. `sbatch/acq_r10/step1.sbatch` (re-issued in ACQ-R11b) names freeze v2 and tag `phase5-acq-freeze-v2`. Set its
   `PREREG` and `SIGNOFF` lines to the v3.1 paths and sha256, and change nothing else. Report the diff.

## 2. Run

1. Submit `sealed_step1_p5.py --mode phase5 --signoff <CNN repo>/…/R16c/SIGNOFF_phase5_prereg_v3_1.md
   --prereg-sha256 75b72eb6…` as one Slurm job, with resources sized from the ACQ-R09 / ACQ-R11b rehearsals (the
   MV1003 fetch is about 37 GB).
2. It fetches the eight ship cruises' raw swath (about 61 GB; MV1003 subset by the development planner), grids it,
   builds the high-resolution mosaics by the frozen rules, harmonizes, co-registers, applies the datum check, runs
   the k sweep, builds the v2.1 products and usability flags, and writes the eligibility columns, the supplement
   `manifest/pairs_phase5_sealed.parquet` and the run record `reports_post_grl_review/PHASE5/step1_run_phase5_*.json`.
3. **If the job stops:** report the stop as a HOLD with the traceback (redacted of any depth-derived number). A
   resume is allowed only through the frozen resume path (finished sites reused after an sha256 check), with no code
   change, and only after Steve's ruling.

## 3. Must hold

1. Every lock passes. The run record carries every key of `RECORD_CONTRACT_phase5.md`, status `complete`, mode
   `phase5`, and cites freeze v2 and the supplement by sha256.
2. Every site has a final status: eligible, or not testable with its `eligibility_reason`
   ("co-registration:" and/or "vertical datum:" parts, or the other frozen reasons).
3. The supplement's first 64 columns equal the Phase 4 supplement's names, order and arrow types, plus the six
   eligibility columns.
4. No output, log or report contains a depth statistic, amplitude, residual, V95 / V95_rel / G value or image. Run
   the ACQ-R11b blindness test (`blind_test_p5.py`) on this run's outputs and logs, and report its result.
5. **CNN lock dry check:** in a fresh `python -B` process with the R09 guard installed and self-tested first, import
   the CNN `phase5_common` (v3.1 constants, `cdca2c9b…`) unchanged and call its acquisition-record lock against the
   real run record and freeze v2, with absolute paths, and nothing else. It must accept the record. Report `git status`
   of the CNN `phase5/` directory before and after; it must be unchanged, with no bytecode written.

## 4. Report

1. **Site table:** one row per site with only the `report_p5.py` fields.
2. **Counts:** eligible sites; not-testable sites and reasons. State whether the eligible count is at least 3 (the
   v3.1 pooled primary needs 3).
3. **Companion line for the CNN `CHANGE_LEDGER.md`:** the supplement's path and full sha256, and the run record's
   path and full sha256. R17 adds it.
4. **Do-not-open list for Steve:** every path this run wrote that holds a raster, a depth-derived value or a
   co-registration residual, and the job's `.out` and `.err` logs if the chain prints any such number.

## 5. Preservation and record

Commit the run record, the supplement, the sbatch file, the report and the report tables by explicit path; never
`git add -A`. One `CHANGE_LEDGER.md` row. Copy the supplement, the run record and the per-site records to OAK
`acq_archive/ACQ-R10b/` with `SHA256SUMS` verified. Large rasters stay under the guarded roots; their sha256 lists go
to OAK.

## 6. Out of scope

- Any edit to `src/phase5/`, the development chain, either freeze record, the site list or any Phase 4 file.
- Any write to the CNN repo, including bytecode.
- Any view, plot or statistic of candidate data beyond §4.1.
- Building targets, tiles, features or pages (R17).

## 7. Not pursued

- Re-screening sites that end not testable.
- Adding or replacing sites.
- A ship line-to-line check (unchecked by ruling).
