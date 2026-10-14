# DIRECTIVE ACQ-R13 (acquisition repo): Phase 5 local co-registration and step-1 rerun for affected sites

**Date:** 2026-10-14
**Repo:** `co-located-auv-ship-based-multibeam-acquisition`
**Report to:** `reports_post_grl_review/ACQ-R13/REPORT_ACQ-R13_<date>.md`
**Report length:** at most 6 bullets, plus the site table.

## 0. Purpose and rulings

In ACQ-R10c, four sites (TN188__MGDS_18210, Escanaba__MGDS_30368, KN161L04__MGDS_22436, MV1003__MGDS_31860) failed co-registration only because the rigid shift exceeded the 30 m development bound. MV1209__MGDS_21415 failed the vertical-datum check. On a steep site, a horizontal misfit that one rigid shift cannot remove shows up as vertical residual, so the datum failure may have the same cause.

**Steve's ruling (2026-10-14):** poor processing must not exclude good data. The 30 m bound is replaced by a direct test of whether the co-registration is right, and sites whose navigation drifts get local shifts. Sites that then pass every other frozen rule are **eligible** for the primary test. Steve stays blind: he sees no offsets, residuals, G values or images, only booleans and counts.

Earlier rulings still apply: v3.1 governs, no sign-offs, no dress rehearsals, fix plumbing yourself and log it in one line.

**Stop only if** the work would change any threshold other than the 30 m bound, change the site list, or expose a sealed value to Steve.

## 1. The method (applies to all eight sites)

1. **Global shift:** keep the frozen co-registration's rigid shift.
2. **Quadrant shifts:** split each site's HR/ship overlap into 2 x 2 quadrants and estimate a rigid shift in each with the same frozen method. A quadrant with too little overlap for the frozen QA is merged with its neighbour along the longer side.
3. **Rigid case:** if every quadrant shift agrees with the global shift to within one ship grid cell, use the global shift.
4. **Drift case:** otherwise, use each quadrant's own shift for that quadrant. Each quadrant must pass the frozen co-registration QA thresholds (all except the 30 m bound). A tile is assigned to the quadrant containing it; a tile crossing a quadrant boundary is dropped.
5. **Pass:** `coreg_pass` is true if the rigid case holds, or the drift case holds with every used quadrant passing QA, and the frozen vertical-datum check (T_G = 0.200712, unchanged) passes on the shifted data.
6. After the new shifts, rerun harmonize, the datum check, the k sweep, the products and eligibility with every frozen rule and threshold unchanged.

## 2. Quick check on development (minutes, not a rehearsal)

Apply §1.2 to three development pairs already on disk, including NA080__MGDS_31289 and KM0923__MGDS_31429. Their quadrant shifts should agree with the global shift within one ship cell (rigid case), so their results do not change. If any does not, report it and stop: the tolerance is wrong.

## 3. Run

1. Implement §1 as the smallest change to the frozen step-1 code. Commit by explicit path, rewrite the freeze record with `freeze_p5.py`, and tag `phase5-acq-freeze-v4`.
2. Rerun step 1 in phase5 mode on all eight sites. The swaths are already on OAK; reuse them through the frozen resume and fetch path, and fetch nothing new.
3. A site failing a rule is an outcome. Resume after any failure that is not a computation issue.
4. A leak-check hit: stop and report the counts only.

## 4. Report

1. Job id, status, wall time, and the leak-check result.
2. **Site table:** site; rigid or drift case; quadrants used (count); tiles dropped at quadrant boundaries (count); coreg_pass; datum check pass or fail; k; ship cells across; hr_res; ship products usable; eligible (yes or no, with the rule that failed). Booleans and counts only, no offsets or residuals.
3. The §2 check result, as booleans.
4. The number of eligible sites, and whether the primary criterion is testable (at least 3).
5. Every plumbing fix, one line each.
6. Hashes: freeze record v4, entry script, run record, supplement. One `CHANGE_LEDGER.md` row; OAK `acq_archive/ACQ-R13/` with `SHA256SUMS` verified.

## 5. Out of scope

- Any threshold change other than replacing the 30 m bound; any change to T_G, 3.88, the k rules or the site list.
- AUV re-navigation (`mbnavadjust` or similar).
- Any write to the CNN repo.
