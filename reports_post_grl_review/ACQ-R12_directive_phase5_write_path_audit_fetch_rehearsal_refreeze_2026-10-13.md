# DIRECTIVE ACQ-R12 (acquisition repo): Phase 5 write-path audit and fix, in-run leak check, fetch-on rehearsal, re-freeze v3

**Date:** 2026-10-13
**Repo:** `co-located-auv-ship-based-multibeam-acquisition`
**Report to:** `reports_post_grl_review/ACQ-R12/REPORT_ACQ-R12_<date>.md`
**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.
**Report length:** at most 8 bullets, plus the write-path table and at most 3 HOLDs.

## 0. Purpose and rulings

ACQ-R10b stopped on site 1. In phase5 mode, `chain_p5.fetch_plan` (l.80 to 81) writes `fetch_plan_<pair id>.csv`
into `reports_post_grl_review/PHASE5/`, which the guard refuses for candidate tokens. The ACQ-R09 and ACQ-R11b
rehearsals ran with `fetch: False`, so the phase5 fetch path has never been exercised. The frozen leak check
(`blind_test_p5.py`) also cannot read phase5 outputs under the guard (ACQ-R10b H-3).

**Steve's rulings (2026-10-13):**
1. Audit every write and open in the phase5 path, not only the one that failed, and fix every one the guard would
   refuse.
2. Move the leak check into the run, as its last stage after the locks and the allowance.
3. Rehearse with downloads on, on a development cruise posing as a sealed site, so the true phase5 path runs end to
   end.
4. Re-freeze as v3.

**No computation changes.** Gridding, harmonizing, co-registration, the datum check and T_G, the k sweep, the
products, the usability flags, the eligibility rules, the schema and every threshold stay as frozen in v2. Only
where files are written, and the leak check, change.

**The guard is not widened.** Do not add the record directory, or any other directory outside the sealed roots, to
the allow-list for candidate tokens. Files that carry a candidate token move under the admitted roots instead.

**No sealed candidate file is opened, no Phase 5 swath is fetched, and phase5 mode is not run on a real site.**
ACQ-R10b's leftovers (the empty OAK staging directory for TN188__MGDS_18210, the NCEI listing cache) are not opened
or deleted. State in the report how the v3 code treats them on the real run.

**Challenge clause.** If any instruction here is wrong or underspecified against the code or the files, stop at
that point, give the evidence, and report it as a HOLD. Do not work around it.

## 1. Write-path audit (code reading, then confirmed by the rehearsal in §4)

1. List every place in phase5 mode that opens, creates, writes, moves or deletes a file or directory, across
   `src/phase5/` and every module it imports (the fetcher, the gridding and MB-System wrappers, the logger, the
   resume path, `report_p5`, `preserve_p5`). Include log files written by subprocesses, temporary files, caches and
   any path built from `C.REPORT_DIR` / `record_dir`.
2. For each, give file and line, the path pattern, whether it carries a candidate token in its name or content,
   whether it can hold a depth-derived value, and whether the guard admits it after the allowance in phase5 mode.
3. Every row that the guard would refuse is a defect. The ACQ-R10b row (`fetch_plan`) is the first.

## 2. Fixes (code)

1. Every defect from §1 writes under the pair's directory in the sealed OAK output root, or under the node-local
   work root if it is temporary. The record directory `PHASE5/` keeps only the files phase5 mode already writes there
   with no candidate token (the run record, the guard self-test record and anything else the contract names).
2. If a file in the record directory must refer to a site, it uses the fields `report_p5.py` already writes, not a
   new file.
3. Report the diff against tag `phase5-acq-freeze-v2`. Any change that touches a computation is a HOLD.

## 3. In-run leak check

1. Add a final stage to `sealed_step1_p5.py`, run after every site and before the run record is closed. It runs
   under the locks and the allowance already in place, and installs nothing new.
2. It scans every text, JSON, CSV, parquet text column and log file this run wrote, inside and outside the sealed
   roots, for:
   - the forbidden keys (the `common_p5` list, including `v95` and the depth-statistic keys);
   - the printed forms of each site's G value and V95, computed in memory and never written, matched as whole
     numbers (the ACQ-R11b rule).
3. It writes to the run record only pass or fail and the counts (files scanned, value hits, key hits). Any hit sets
   the run status to `stopped` with reason "leak check", and nothing is published.
4. Keep `blind_test_p5.py` for rehearsal use; record in the report which check applies to which mode.

## 4. Fetch-on rehearsal (development data only)

1. **Mock sealed site:** one development pair whose LR cruise is small enough to fetch in one job (your choice;
   report the pair, the cruise and the download size). Give it a mock token. The guard seals it exactly as phase5
   mode seals a real token: same roots, same allow-list rule, same refusal before the locks.
2. **Same code path:** run it through the phase5-mode site function with `fetch: True`, against a mock sign-off and
   pre-registration, so it differs from phase5 mode only in its inputs. State how you show that (for example, the
   mode switch, and the list of functions called against phase5 mode's list).
3. **Must hold:**
   1. the run completes with no guard refusal, traceback or new warning category;
   2. every row of the §1 table is exercised (report the opened-path log against the table, as R12c and R16c did);
      a row not exercised is listed with the reason;
   3. the fetched swath grids to the development ship grid: bit-identical, or with differences explained exactly as
      FK151121's region difference was in ACQ-R09; any other difference is a HOLD;
   4. the harmonized rasters, `coreg_pass`, the datum result, k and the products equal development (or the ACQ-R11b
      rehearsal for the same pair);
   5. the in-run leak check passes, and a planted hit (a G value written into a mock log) makes it fail with status
      `stopped`;
   6. **resume:** with two mock sites (the fetched one and one ACQ-R11b rehearsal site, no fetch), force a stop after
      the first site, then resume through the frozen resume path. The first site is reused after its sha256 check
      and not refetched.
4. Re-run the ACQ-R11b rehearsal (NA080__MGDS_31289, KM0923__MGDS_31429, the FK151121 harness, the NR07-1 control):
   all outputs bit-identical to ACQ-R11b.
5. The copy of the CNN lock accepts the new rehearsal record against the new freeze record.
6. The refusal suite (ACQ-R11b's 65) plus tests for §2 (each fixed path refused before the allowance and admitted
   after it) and §3 (the planted hit), all passing.

## 5. Capacity for the real run (metadata only)

From the ACQ-R08b metadata and the fetch planner's listing logic, without opening any sealed file: the largest
site's download, the scratch, node-local and OAK space it needs, and the wall time scaled from the §4 throughput.
State the Slurm resources the ACQ-R10c job should request, and whether any site would exceed a quota or the
node-local disk.

## 6. Freeze

1. Commit by explicit path; never `git add -A`.
2. Write `reports_post_grl_review/PHASE5/freeze_record_phase5_v3.json` (every Phase 5 script and helper, the site
   list, the calibration table, the MB-System image digest and version, the commit). Keep the v1 and v2 records.
3. Tag `phase5-acq-freeze-v3`. Report the new freeze record's sha256 and the entry script's sha256.
4. Re-issue `sbatch/acq_r10/step1.sbatch` against freeze v3 and the §5 resources (paths and resources only);
   uncommitted until ACQ-R10c.
5. One `CHANGE_LEDGER.md` row. OAK `acq_archive/ACQ-R12/` with `SHA256SUMS` verified.

## 7. Report

1. The §1 write-path table, with each defect and its fix.
2. The diff against `phase5-acq-freeze-v2`.
3. The rehearsal, resume, leak-check, CNN lock copy and refusal results.
4. The §5 capacity numbers and resources.
5. The new freeze sha256, entry script sha256 and tag.
6. **For the CNN side (read only):** the exact constants in `phase5/scripts/phase5_common.py` that must change, and
   the exact v3.2 wording, if any, for the leak check and the freeze citation.

## 8. Out of scope

- Opening any sealed candidate file; fetching any Phase 5 swath; running phase5 mode on a real site.
- Any write to the CNN repo.
- Changing any computation, threshold, rule or constant, including 3.88 and T_G.
- Widening the allow-list to any directory outside the sealed roots.
- Editing Phase 4 files, the v1 or v2 freeze records, or `src/acq_r11/`.
