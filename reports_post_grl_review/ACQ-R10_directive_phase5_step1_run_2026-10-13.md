# DIRECTIVE ACQ-R10 (acquisition repo): Phase 5 step 1 on the eight sealed sites

**Date:** 2026-10-13
**Repo:** `co-located-auv-ship-based-multibeam-acquisition`
**Report to:** `reports_post_grl_review/ACQ-R10/REPORT_ACQ-R10_<date>.md`
**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.
**Report length:** at most 8 bullets, plus the site table and at most 3 HOLDs.

## 0. Purpose

Run the frozen Phase 5 step-1 code (`src/phase5/sealed_step1_p5.py`, tag `phase5-acq-freeze`, freeze record
`reports_post_grl_review/PHASE5/freeze_record_phase5.json`, sha256 `6769583198da63d874472ea5a2ca62cb26c2f9f55003eb6e97838bfebab1d9d1`)
in phase5 mode on the eight sites of `inputs/phase5_sites.csv`, under signed pre-registration v3
(`R16/PREREG_phase5_v3.md` in the CNN repo, sha256 `3df236e008466919a2b5acf94fb258a6f42abe6235a1ee1b77c0785ca8939d58`,
tag `phase5-prereg-v3`).

**Blindness.** Steve stays blind to every candidate amplitude, depth statistic, target, feature and image until his
artifact calls are committed (v3 B3). The report carries only the fields `src/phase5/report_p5.py` writes: status,
eligibility fields, spacings, cells across, k, product status and usability, file counts and sha256. No QC figure,
hillshade, preview or plot is made. No person views any candidate data, and co-registration pass or fail is decided
by the automated thresholds only.

**No code change.** Nothing under `src/phase5/` or the development chain is edited. Any stop is a HOLD.

**Challenge clause.** If any instruction here is wrong or underspecified against the code or the files, stop at
that point, give the evidence, and report it as a HOLD. Do not work around it.

## 1. Preconditions (read only; any failure stops the directive)

1. In the CNN repo (read only): `R16/PREREG_phase5_v3.md` hashes to `3df236e0…` and equals the file at tag
   `phase5-prereg-v3`; `R16/SIGNOFF_phase5_prereg_v3.md` is committed, signed, and its first 64-hex string is
   `3df236e0…`.
2. In this repo: the freeze record hashes to `67695831…`; every file it lists hashes as listed; `src/phase5/` is
   clean in git and equal to tag `phase5-acq-freeze`.
3. The acquisition guard self-test passes before any other step (report the probe count), with
   `sealed_candidates_v3` and the Phase 5 output roots sealed.
4. `reports_post_grl_review/PHASE5/` holds no `step1_run_phase5_*.json` in phase5 mode; `manifest/pairs_phase5_sealed.parquet`
   does not exist.
5. **Manual steps.** State, from the ACQ-R09 code reading, every step of the development chain that a person decided
   or edited (for example the ACQ-R03 QGIS co-registration review, ruling R6), and the automated rule Phase 5 uses
   instead. If any step has no automated equivalent in the frozen code, stop and report a HOLD.

## 2. Run

1. Submit `sealed_step1_p5.py --mode phase5 --signoff <CNN repo>/…/R16/SIGNOFF_phase5_prereg_v3.md --prereg-sha256 3df236e0…`
   as one Slurm job, with resources sized from the ACQ-R09 rehearsal (the MV1003 fetch is about 37 GB).
2. It fetches the eight ship cruises' raw swath (about 61 GB, MV1003 subset by the development planner), grids it,
   builds the high-resolution mosaics by the frozen rules, harmonizes, co-registers, runs the k sweep, builds the
   v2.1 products and usability flags, and writes the eligibility columns, the supplement
   `manifest/pairs_phase5_sealed.parquet` and the run record `reports_post_grl_review/PHASE5/step1_run_phase5_*.json`.
3. **If the job stops:** report the stop as a HOLD with the traceback (redacted of any depth-derived number). A
   resume is allowed only through the frozen resume path (finished sites reused after an sha256 check), with no code
   change, and only after Steve's ruling.

## 3. Must hold

1. Every lock passes; the run record carries every key of `RECORD_CONTRACT_phase5.md`, status `complete`, mode
   `phase5`, and cites the freeze record and the supplement by sha256.
2. Every site has a final status: eligible, or not testable with its `eligibility_reason`.
3. The supplement's first 64 columns equal the Phase 4 supplement's names, order and arrow types, plus the six
   eligibility columns.
4. No output, log or report contains a depth statistic, amplitude, residual or image. Grep the outputs and logs and
   report the check, as ACQ-R08b did.
5. **CNN lock dry check** (as ACQ-R07c §4): in a fresh `python -B` process with the R09 guard installed and
   self-tested first, import the CNN `phase5_common` unchanged and call its acquisition-record lock against the real
   record and freeze record, and nothing else. It must accept the record. Report `git status` of the CNN `phase5/`
   directory before and after; it must be unchanged, with no bytecode written.

## 4. Report

1. **Site table:** one row per site with only the `report_p5.py` fields.
2. **Counts:** eligible sites; not-testable sites and reasons.
3. **Companion line for the CNN `CHANGE_LEDGER.md`:** the supplement's path and full sha256, and the run record's
   path and full sha256. R17 adds it.
4. **Do-not-open list for Steve:** every path this run wrote that holds a raster, a depth-derived value or a
   co-registration residual, and the job's `.out` and `.err` logs if the chain prints any such number.

## 5. Preservation and record

Commit the run record, the supplement, the report and the report tables by explicit path; never `git add -A`. One
`CHANGE_LEDGER.md` row. Copy the supplement, the run record and the per-site records to OAK `acq_archive/ACQ-R10/`
with `SHA256SUMS` verified. Large rasters stay under the guarded roots; their sha256 lists go to OAK.

## 6. Out of scope

- Any edit to `src/phase5/`, the development chain, the freeze record, the site list or any Phase 4 file.
- Any write to the CNN repo, including bytecode.
- Any view, plot or statistic of candidate data beyond §4.1.
- Building targets, tiles, features or pages (R17).

## 7. Not pursued

- Re-screening sites that end not testable.
- Adding or replacing sites.
