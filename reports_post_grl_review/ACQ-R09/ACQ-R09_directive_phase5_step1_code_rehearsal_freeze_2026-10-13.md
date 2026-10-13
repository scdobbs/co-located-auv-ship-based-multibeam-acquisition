# DIRECTIVE ACQ-R09 (acquisition repo, CPU only): write, rehearse and freeze the Phase 5 step-1 code

**Date:** 2026-10-13
**Repo:** `co-located-auv-ship-based-multibeam-acquisition`
**Report to:** `reports_post_grl_review/ACQ-R09/REPORT_ACQ-R09_<date>.md`
**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.
**Report length:** at most 8 bullets, plus at most 3 HOLDs.
**Spec:** `PHASE5_design_spec_2026-10-13.md` (steering; Steve ruled 2026-10-13). Place it in
`reports_post_grl_review/ACQ-R09/` and commit it with this directive.

## 0. Purpose

Phase 5 is a second pre-registered blind test on eight new sites. Step 1 (acquisition) must be written, rehearsed
on development data and frozen **before** pre-registration v3 is signed, as for Phase 4 (ACQ-R06, ACQ-R06b). This
directive does that and nothing more. **No sealed candidate file is opened, and no ship swath for the eight sites
is fetched.** Step 1 itself runs later (ACQ-R10), after v3 is signed.

**Challenge clause.** If any instruction here is wrong or underspecified against the code or the files, stop at
that point, give the evidence, and report it as a HOLD. Do not work around it.

## 1. Code reading (read only; report file and line)

1. `src/phase4/sealed_step1.py` (frozen, `bd773cb7…`), the ACQ-R07b completion script and
   `src/phase4/write_citation_record.py`: every input path, every hard-coded pair id or path, every output file and
   column, every lock, and every key of the run record.
2. The development chain each stage calls: raw-swath gridding (MB-System sandbox, version and image digest),
   harmonization, co-registration and its QA thresholds (ACQ-R03), the k sweep and its verdicts, contract v2.1
   products and the usability flag.
3. The CNN lock `phase4_common.load_acq_run_record` (read only, CNN repo): the keys and values it checks and returns,
   including `per_pair` fields (ACQ-R07c §1.3). Phase 5's lock will be a parameterised copy, so the Phase 5 record
   must satisfy the same contract under Phase 5 paths.

## 2. Phase 5 step-1 code (new files; no edit to any Phase 4 file)

Write `src/phase5/sealed_step1_p5.py` and helpers in `src/phase5/`, reusing the development chain functions
unchanged. It must:

1. **Read the site list** from `inputs/phase5_sites.csv` (write it now, from spec §3.1: site name, high-resolution
   record id, ship cruise, sonar, year; one row per site; the Galápagos row names MGDS:18210 only).
2. **Locks (phase5 mode):** refuse to run unless the v3 sign-off exists and holds the v3 sha256 passed as an
   argument; refuse a second completed run; refuse any site not in the site list. Rehearsal mode runs on
   development pairs only, under a scratch root, and needs no sign-off.
3. **Guard:** run under the acquisition guard with `sealed_candidates_v3` sealed; in phase5 mode, admit only the
   eight sites' paths, after every lock has passed. Test the admission on paths under the real
   `sealed_candidates_v3/<hr_id>/` names (the Phase 4 allow-list defect).
4. **High-resolution mosaic** by the spec §3.2 rules, mechanically: resolution group; repeat-survey selection by
   acquisition date closest to the ship cruise year (ties: larger valid area); mosaic of non-overlapping grids.
   Record every grid kept or dropped and why. No statistic of depth beyond what the development chain already
   writes.
5. **Ship side:** fetch the named cruise's raw swath (phase5 mode only), grid it, build contract v2.1 products and
   the usability flag, exactly as for development pairs.
6. **Harmonize, co-register, k sweep** exactly as for development pairs.
7. **Eligibility (spec §3.3, items 1 to 3):** columns `coreg_pass`, `k_recoverable`, `cells_across`,
   `hr_res_in_range`, `eligible`, `eligibility_reason`.
8. **Supplement** `manifest/pairs_phase5_sealed.parquet`: the same 64 columns, names and dtypes as the Phase 4
   supplement, plus the eligibility columns. Assert schema equality in code.
9. **Run record**, written to `reports_post_grl_review/PHASE5/step1_run_phase5_*.json`, carrying at least: `status`, `mode`,
   `supplement_sha256`, `code_commit`, `locks.lock2_freeze_record.freeze_record_sha256`, top-level
   `freeze_record_sha256`, and `per_pair[<pair id>]` with `max_recoverable_k`, `per_k`, `k_source`,
   `values_source`, `path`, plus the eligibility fields. Write the full key list to
   `reports_post_grl_review/ACQ-R09/RECORD_CONTRACT_phase5.md`; R16 builds the CNN lock against it.
10. **Report fields** for ACQ-R10: per site only status, eligibility fields, spacings, cells across, k, product
    usability, file counts and sha256. No amplitude, statistic, image or view.

## 3. Rehearsal (development data only)

1. Build a mock layout under scratch, `.../ACQ-R09/mock/sealed_candidates_v3/<id>/`, holding copies (not links) of
   the high-resolution files of three development pairs: FK151121__MGDS_22383, NA080__MGDS_31289 and
   KM0923__MGDS_31429, with their ship raw swath taken from the existing development store (no network fetch).
   Include one mock record with two overlapping grids of different dates, to exercise the repeat-survey rule.
2. Run `sealed_step1_p5.py --mode rehearsal` on the mock site list.
3. **Must hold:**
   1. harmonized rasters, products, usability flag and k equal the frozen development values for the three pairs
      (bit-identical, or within the R10 accepted float tolerance, stated);
   2. the repeat-survey rule picks the expected grid;
   3. the supplement schema equals the Phase 4 supplement's;
   4. the run record carries every contract key; a copy of the CNN `phase4_common.load_acq_run_record` logic,
      pointed at the Phase 5 record directory and freeze record, accepts it (run in a scratch copy, never by editing
      the CNN repo);
   5. the guard refuses a mock path under `sealed_candidates_v3/` before admission, admits the mock ids after the
      locks, and still refuses a non-admitted id;
   6. phase5 mode refuses to run without a v3 sign-off.
4. A refusal test list (at least the locks of §2.2 and the guard cases of §3.3.5), all passing.

## 4. Freeze

1. Commit the Phase 5 code, the site list, the contract file, the spec and the rehearsal outputs by explicit path;
   never `git add -A`.
2. Write `reports_post_grl_review/PHASE5/freeze_record_phase5.json` listing the sha256 of every Phase 5 script,
   helper and the site list, the MB-System image digest and version, and the commit.
3. Tag `phase5-acq-freeze`. Report the freeze record's sha256: v3 will cite it.
4. One `CHANGE_LEDGER.md` row. Copy the code, contract, freeze record and rehearsal records to OAK
   `acq_archive/ACQ-R09/` with `SHA256SUMS` verified.

## 5. Out of scope

- Opening any file under `sealed_candidates_v3/` except mock copies; fetching any Phase 5 ship swath.
- Running phase5 mode.
- Editing any Phase 4 file or record, or any file in the CNN repo.
- Changing any development-chain function.

## 6. Not pursued

- Pre-registration v3 text (R16).
- Any change to the k sweep, co-registration thresholds or contract v2.1.
