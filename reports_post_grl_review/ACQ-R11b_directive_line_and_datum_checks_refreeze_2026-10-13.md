# DIRECTIVE ACQ-R11b (acquisition repo, CPU only): per-line and datum checks, re-rehearsal, re-freeze

**Date:** 2026-10-13
**Repo:** `co-located-auv-ship-based-multibeam-acquisition`
**Report to:** `reports_post_grl_review/ACQ-R11b/REPORT_ACQ-R11b_<date>.md`
**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.
**Report length:** at most 8 bullets, plus the calibration tables and at most 3 HOLDs.

## 0. Purpose and rulings

ACQ-R11 showed that the residual-spread statistic (V95_rel) separates the gross datum mismatch (NR07-1, 0.378 to
0.394) but not the ship line offset (AT37-05, 0.027, below accepted EW9801 and EW0207). A single bad line covers few
cells, and steep terrain gives good pairs a large genuine misfit.

**Steve's rulings (2026-10-13):**
1. Option (b): add a per-line check, keep a datum check, calibrate both on development data only, re-freeze.
2. **Fallback, approved in advance:** if the line check does not separate AT37-05 (§2.3), implement the datum check
   alone, freeze, and record ship line-to-line inconsistency as unchecked for v3.1. No further ruling needed.
3. Keep the 3.88 cells-across bound.

**No sealed candidate file is opened, no Phase 5 swath is fetched, and phase5 mode is not run.** Development and
known-bad pairs are not sealed; their values may be reported.

**Challenge clause.** If any instruction here is wrong or underspecified against the code or the files, stop at
that point, give the evidence, and report it as a HOLD. Do not work around it.

## 1. The statistics (fixed before any new value is computed)

Use the harmonized grids and the rigid dz exactly as `chain_p5.harmonize` applies them, and the ACQ-R11 resampling
choices (rasterio `Resampling.average` of `hr.tif` onto the `lr.tif` grid; an LR cell is joint-valid when at least
0.5 of its `joint_valid.tif` cells are valid and both values are finite). `depth` = |median LR depth over the joint
mask|.

1. **Datum check `G`:** `V95_rel` exactly as ACQ-R11 (`src/acq_r11/vcheck.py`, sha256 `5a2c65d4…2a44`, unchanged).
2. **Line check `L`:**
   1. For each ship swath file f of the pair's LR cruise that intersects the footprint, grid f alone onto the pair's
      LR grid with the chain's frozen gridding function and parameters (same cell, region, origin and per-cell rules;
      a datalist of one file).
   2. On joint-valid cells where file f has a value, `d_f = median(HR_lr - LR_f)`, after the pair's rigid dz. Keep
      files with at least 30 such cells.
   3. With at least two kept files: `L = max_f |d_f - median_f(d_f)| / depth`. With fewer than two, L is
      "not applicable" and the line check passes; record it.
   4. Pairs whose LR is a provider grid or a compilation (no per-file raw swath on disk) are "not computable" for L.

## 2. Calibration (development and known-bad pairs only)

1. **Datum threshold (rule fixed now, after ACQ-R11's table):** `T_G = 3 x max(V95_rel over all 45
   development-designated rows in vcheck_calibration.csv, accepted and info)` = 3 x 0.066904 = 0.2007. Check that
   NR07-1 (both pairs) lies above `T_G` and every development row below it; report.
2. **Line threshold (rule fixed now):** `T_L = 2 x max(L over the accepted development pairs where L is computable)`.
   Report every pair's L, n kept files, and the per-file `d_f` for AT37-05.
3. **Separation:** AT37-05 must have `L > T_L`. Also report L for NR07-1 and the seven info rows.
   - If AT37-05's raw swath is not on disk, or `L(AT37-05) <= T_L`, or fewer than 10 accepted pairs have a computable
     L: apply the fallback (§0.2): implement the datum check only.
4. Write `ACQ-R11b/vcheck_calibration_v2.csv` and `.json`; record their sha256.

## 3. Code change (new freeze; Phase 4 files, the ACQ-R09 freeze and `src/acq_r11/` untouched)

1. Add the checks to the Phase 5 chain after co-registration, as a new module in `src/phase5/` (the datum function
   copied byte for byte from `src/acq_r11/vcheck.py`, its sha256 asserted).
2. `coreg_pass = qa_pass AND (G <= T_G) AND (L <= T_L or L not applicable)`; under the fallback, without the L term.
   `eligibility_reason` names the failing part: "co-registration", "vertical datum" or "line consistency". The
   supplement schema stays 64 + 6 columns.
3. **Blindness:** in phase5 mode, G, L, `d_f` and the residual are never written, printed or logged; only the
   booleans and the reason. Extend the no-depth-statistic key check; add a test that phase5-mode outputs and logs
   contain none of them.
4. `T_G` and `T_L` are code constants with the calibration table's sha256 in a comment.

## 4. Re-rehearsal (development data only)

1. Rerun the ACQ-R09 rehearsal (NA080__MGDS_31289, KM0923__MGDS_31429, the FK151121 harness, the mock repeat
   record): every output bit-identical to ACQ-R09, with `coreg_pass` true for the three real pairs.
2. **Positive controls,** as mock sealed-style sites: NR07-1 → not testable, "vertical datum"; AT37-05 → not
   testable, "line consistency" (skip under the fallback). No G, L or `d_f` value in any output or log.
3. The copy of the CNN lock accepts the new rehearsal record against the new freeze record.
4. The ACQ-R09 refusal and guard suite plus the new blindness test, all passing.

## 5. Freeze

1. Commit by explicit path; never `git add -A`.
2. Write `reports_post_grl_review/PHASE5/freeze_record_phase5_v2.json` (every Phase 5 script and helper, the site
   list, the calibration table, the MB-System image digest and version, the commit). Keep `freeze_record_phase5.json`.
3. Tag `phase5-acq-freeze-v2`. Report the new freeze record's sha256 and the entry script's sha256.
4. Re-issue `sbatch/acq_r10/step1.sbatch` against the new freeze (paths only); uncommitted until ACQ-R10 is re-run.
5. One `CHANGE_LEDGER.md` row. OAK `acq_archive/ACQ-R11b/` with `SHA256SUMS` verified.

## 6. Report

1. Both calibration tables, `T_G`, `T_L`, the separation results, and whether the fallback applied.
2. The diff of `src/phase5/` against tag `phase5-acq-freeze`.
3. Rehearsal, positive controls, CNN lock copy and refusal results.
4. The new freeze record sha256, the entry script sha256 and the tag.
5. **For the CNN side (read only):** the exact constants and lines in `phase5/scripts/phase5_common.py` that must
   change (ACQ-R11 found l.47, l.48 and the pre-registration check at l.134), and the exact eligibility wording for
   v3.1 B1.

## 7. Out of scope

- Opening any sealed candidate file; fetching Phase 5 swath; running phase5 mode.
- Any write to the CNN repo.
- Changing any other threshold, rule or constant, including 3.88.
- Editing Phase 4 files, the ACQ-R09 freeze record or `src/acq_r11/`.
