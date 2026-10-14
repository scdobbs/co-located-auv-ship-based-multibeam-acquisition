# DIRECTIVE ACQ-R10c (acquisition repo): Phase 5 step 1 on the eight sites

**Date:** 2026-10-14
**Repo:** `co-located-auv-ship-based-multibeam-acquisition`
**Report to:** `reports_post_grl_review/ACQ-R10c/REPORT_ACQ-R10c_<date>.md`
**Report length:** at most 6 bullets, plus the site table.

## 0. Purpose and rulings

Run step 1 (fetch, grid, harmonize, co-register, datum check, k sweep, products, eligibility) on the eight Phase 5 sites with the code frozen as `phase5-acq-freeze-v3` (ACQ-R12).

**Steve's rulings (2026-10-14):**
1. **Get the data processed.** Pre-registration v3.1 (tag `phase5-prereg-v3.1`) stays the governing document. There will be no further amendments, sign-offs or dress rehearsals.
2. **The blind stays.** Steve does not see any sealed value or image until his artifact calls are committed. Nothing in your report may show him a sealed amplitude, target, s_lr, feature, prediction, G or V95 value, or image. The fields `report_p5` already writes are fine.
3. **Fix plumbing yourself.** If something fails for a reason that changes no computation, threshold, rule or site (a path, a permission, a lock that names the wrong version, a precondition line), fix it, commit it by explicit path, and continue. If the fix touches a frozen file, rewrite the freeze record with `freeze_p5.py`, tag `phase5-acq-freeze-v3.1`, and report the new freeze-record and entry-script sha256. No rehearsal. Log every such fix in one line in the report and in `CHANGE_LEDGER.md`.
4. **Stop only if** the fix would change a computation, threshold, rule or the site list, or would expose a sealed value to Steve. Then report and wait.

## 1. Run

1. `sbatch/acq_r10/step1.sbatch` as re-issued in ACQ-R12, naming v3.1 and its sign-off. Resources: 8 CPUs, 128 GB, 48 h, `serc,normal`. Commit the job script by explicit path, then submit.
2. Phase5 mode, all eight sites, one job.
3. A site failing an eligibility rule is an outcome. Record it and continue.
4. Resume through the frozen resume path after any failure that is not a computation issue (node loss, network, NCEI timeout, a plumbing fix under ruling 3).
5. A leak-check hit: stop and report the counts only.

## 2. Report

1. Job id(s), status, wall time, and the leak-check result (pass or fail and counts).
2. **Site table:** site, HR and LR cruises, coreg_pass, datum check pass or fail, k, ship cells across, hr_res, ship products usable, eligible (yes or no, with the rule that failed). Only fields `report_p5` writes.
3. The number of eligible sites, and whether the primary criterion is testable (at least 3).
4. Every plumbing fix, one line each.
5. The run record sha256, supplement sha256, and the freeze-record and entry-script sha256 the run used.
6. One `CHANGE_LEDGER.md` row; OAK `acq_archive/ACQ-R10c/` with `SHA256SUMS` verified.

## 3. Out of scope

- Any change to computations, thresholds, rules or the site list.
- Any write to the CNN repo.
- Any rehearsal.
