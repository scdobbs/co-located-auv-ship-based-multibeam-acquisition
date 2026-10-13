# DIRECTIVE ACQ-R11 (acquisition repo, CPU only): automated vertical-consistency check, re-rehearsal, re-freeze

**Date:** 2026-10-13
**Repo:** `co-located-auv-ship-based-multibeam-acquisition`
**Report to:** `reports_post_grl_review/ACQ-R11/REPORT_ACQ-R11_<date>.md`
**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.
**Report length:** at most 8 bullets, plus the calibration table and at most 3 HOLDs.

## 0. Purpose and rulings

ACQ-R10 stopped at precondition §1.5 (H-1): two development QA steps were decided by people viewing data (gross
HR/ship vertical mismatch, rows 9; ship line-to-line inconsistency, row 10) and have no automated equivalent in the
frozen Phase 5 code.

**Steve's rulings (2026-10-13):** H-1 option (A): add one automated check, calibrated on development data only, and
re-freeze. ACQ-R09 H-1 / ACQ-R10 H-2: keep the 3.88 cells-across bound as written.

**No sealed candidate file is opened, no Phase 5 swath is fetched, and phase5 mode is not run.** Development and
known-bad pairs are not sealed; their values may be reported.

**Challenge clause.** If any instruction here is wrong or underspecified against the code or the files, stop at
that point, give the evidence, and report it as a HOLD. Do not work around it.

## 1. The statistic (fixed before any calibration value is computed)

After co-registration and the rigid dz, exactly as `chain_p5.harmonize` applies them:

1. On the harmonized LR grid, take the HR field block-averaged to the LR cells by the chain's own resampling
   (`hr` already aligned to `lr`), and the joint-valid mask.
2. Residual `r = HR_lr - LR` on joint-valid cells; `m = median(r)`.
3. `V95 = 95th percentile of |r - m|` (metres), and `V95_rel = V95 / |median LR depth over the joint mask|`.

`V95_rel` is the gate. It catches both a datum or sign blunder and a line-to-line offset, which inflate the residual
spread. Report `V95` beside it for development and known-bad pairs.

## 2. Calibration (development and known-bad pairs only)

1. **Accepted set:** the 38 manifest v2.1 development pairs and EW0207, from their frozen harmonized files (read
   only).
2. **Known-bad set:** AT37-05 (ruling R1), NR07-1 (ACQ-R02 H2) and MGLN06MV (re-audit 2026-06-26), from whatever
   harmonized or gridded files exist. If a pair's files no longer exist and cannot be rebuilt from raw already on disk
   without a network fetch, report it COULD NOT CHECK.
3. **Threshold rule (fixed now):** `T = 2 x max(V95_rel over the accepted set)`.
   - **Separation must hold:** every available known-bad pair has `V95_rel > T`. If any known-bad pair is at or
     below `T`, or no known-bad pair is available, stop and report a HOLD with the table. Do not adjust the rule.
   - Report the accepted set's distribution (min, median, max) and every pair's value.

## 3. Code change (new freeze; Phase 4 files and ACQ-R09 files untouched)

1. Add the statistic and gate to the Phase 5 chain as a new function, used after co-registration.
2. **Fold it into `coreg_pass`:** `coreg_pass = qa_pass AND (V95_rel <= T)`, with `eligibility_reason` naming which
   part failed ("co-registration" or "vertical consistency"). The supplement schema stays 64 + 6 columns, unchanged,
   so the CNN Phase 5 scripts need no change.
3. **Blindness:** in phase5 mode, `V95`, `V95_rel` and `r` are never written, printed or logged; only the boolean and
   the reason. Extend the code's no-depth-statistic key check and add a test that phase5-mode outputs and logs contain
   neither value.
4. `T` is a constant in the code with its calibration provenance (the calibration table's sha256) in a comment.

## 4. Re-rehearsal (development data only)

1. Rerun the ACQ-R09 rehearsal (NA080__MGDS_31289, KM0923__MGDS_31429, the FK151121 harness and the mock repeat
   record): outputs bit-identical to ACQ-R09, with `coreg_pass` true for the three real pairs.
2. **Positive control:** a mock sealed-style site built from one available known-bad pair: `coreg_pass` false,
   `eligible` false, reason "vertical consistency", and no `V95` value in any output or log.
3. The copy of the CNN lock (as ACQ-R09 §3.3.4) accepts the new rehearsal record against the new freeze record.
4. The ACQ-R09 refusal and guard suite (60 tests) plus the new blindness test, all passing.

## 5. Freeze

1. Commit by explicit path; never `git add -A`.
2. Write `reports_post_grl_review/PHASE5/freeze_record_phase5_v2.json` (every Phase 5 script, helper, the site list,
   the calibration table, MB-System image digest and version, the commit). Keep `freeze_record_phase5.json` as it
   is.
3. Tag `phase5-acq-freeze-v2`. Report the new freeze record's sha256: the v3.1 amendment will cite it.
4. Re-issue the prepared `sbatch/acq_r10/step1.sbatch` against the new freeze (paths only), uncommitted until
   ACQ-R10 is re-run.
5. One `CHANGE_LEDGER.md` row. OAK `acq_archive/ACQ-R11/` with `SHA256SUMS` verified.

## 6. Report

1. The calibration table (every pair's `V95`, `V95_rel`, median depth), `T`, and the separation result.
2. The diff of the Phase 5 code against tag `phase5-acq-freeze`.
3. Rehearsal, positive control, CNN lock copy and refusal results.
4. The new freeze record sha256 and tag.
5. **For the CNN side:** whether `phase5_common.py` reads the acquisition freeze sha256 from a constant or from the
   pre-registration text (file and line, read only). This decides whether v3.1 needs only a text amendment or also a
   CNN script change.

## 7. Out of scope

- Opening any sealed candidate file; fetching Phase 5 swath; running phase5 mode.
- Any write to the CNN repo.
- Changing any other threshold, rule or constant, including 3.88.
- Editing Phase 4 files or the ACQ-R09 freeze record.
