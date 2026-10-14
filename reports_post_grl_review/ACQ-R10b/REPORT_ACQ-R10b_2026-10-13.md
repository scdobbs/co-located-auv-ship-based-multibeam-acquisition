# REPORT ACQ-R10b — Phase 5 step 1 under v3.1 / freeze v2: STOPPED on the first site (HOLD H-1, code defect)

**Directive:** `ACQ-R10b_directive_phase5_step1_run_v3_1_2026-10-13.md`.
**Outcome:**
- **Run:** one Slurm job, 47718453, submitted once; preconditions 1–6 passed (1 by Steve's ruling, H-2) and locks 1–4 passed.
- **Stop:** on the first site, the frozen `chain_p5.fetch_plan` tried to write its plan CSV under `reports_post_grl_review/PHASE5/` with the pair id in the file name. The acquisition guard refused the write (`PermissionError`), and the run stopped.
- **Nothing produced:** no swath fetched, no grid, no harmonized site, no run record (not even a "stopped" one: the error was not a `StopRun`) and no supplement.
- **A frozen-path resume cannot pass this point.** The defect is in the frozen code, so a new freeze is needed (HOLD H-1).
- **Unchanged:** no `src/phase5/`, development-chain, freeze-record, site-list, Phase 4 or CNN file changed.

## Bullets

1. **§1.1 pre-registration and sign-off (CONFIRMED for the hashes; signed by Steve's ruling, see H-2).**
   - `R16c/PREREG_phase5_v3_1.md` hashes to `75b72eb6fae3804c7dea61aa4171744a2fcd4fbdb7c3916f3fb98f2c06f2c7b6`, and so does the copy at tag `phase5-prereg-v3.1`.
   - `R16c/SIGNOFF_phase5_prereg_v3_1.md` is committed (CNN `96c46c5`, file sha256 `b8ba209c…3a89`). Its first 64-hex string is `75b72eb6…`, and its signature and date lines are filled.
   - `phase5/scripts/phase5_common.py` hashes to `cdca2c9b…1b66` (l.47–48: freeze v2 `f5a30b87…`, step-1 sha `83af2875…`).
2. **§1.2, §1.4 (CONFIRMED).**
   - Freeze v2 hashes to `f5a30b87…9438`, and all 66 listed files match. `src/phase5/` is clean and equal to `phase5-acq-freeze-v2`.
   - Before the run there was no `step1_run_phase5_*.json`, no `manifest/pairs_phase5_sealed.parquet` and no OAK `phase5/`.
3. **§1.3 guard self-test (CONFIRMED; first step of the job).** 552 probes, all blocked:
   - 84/84 Phase 4 reader probes;
   - 228/228 Phase 5 reader probes;
   - 240/240 output, staging, gridded, work and sealed paths of the eight sites, probed with no allowance installed.

   Real-name admission passed 23/23. Record: `ACQ-R10b/guard_selftest_r10b_job47718453.json`. It was written by the job to `ACQ-R10/` as the script names it, and moved here so ACQ-R10 stays unchanged.
4. **§1.5 manual steps (CONFIRMED, from the freeze v2 code).** These are ACQ-R10's 17 rows. The changes from ACQ-R10:
   - **Co-registration review:** the ACQ-R03 QA thresholds (`qa_pass`).
   - **Row 9, gross HR/ship vertical mismatch:** the datum check, `V95_rel ≤ T_G = 0.200712` (`chain_p5.harmonize` → `vcheck_p5.gate`; `coreg_pass = qa_pass AND datum`).
   - **Row 10, ship line-to-line inconsistency:** **unchecked by Steve's ruling** (v3.1 B1). This is recorded, not a stop.
   - Rows 11 (PSR) and 15 (H1 cross-check) were never gates. Row 4 (swath count) stops the run. Every other row has its ACQ-R10 automated rule.
5. **§1.6 job script (CONFIRMED; diff below).** The `PREREG` / `SIGNOFF` values were set to v3.1.
   - The in-job precondition-1 checks also name the v3 file path, the tag `phase5-prereg-v3` and the sign-off path. Changing only the two assignments would have made the job exit at its own check, so those lines were changed to the v3.1 names as well.
   - Nothing else changed beyond ACQ-R11b's re-issue (freeze v2, tag v2).
6. **§2 run: STOPPED (HOLD H-1).** Job 47718453 ran on sh04-12n21 from 02:10:58Z to 02:12:05Z: locks 1–4, then the allowance, then site 1 (TN188__MGDS_18210). The §3.2 HR selection completed, and the fetch planner listed NCEI (metadata).
   - Traceback (redacted; it holds no number):
     ```
     sealed_step1_p5.py l.215 run_site -> CH.fetch_plan(site, sel["footprint"], cfg["record_dir"])
     chain_p5.py l.81 fetch_plan -> pd.DataFrame(plan).to_csv(Path(report_dir) / f"fetch_plan_{site['pair_id']}.csv")
     acq_r01/common.py l.200 guarded_open -> guard_p5._check_p5 -> common._check_sealed
     PermissionError: SEALED CANDIDATE GUARD (ACQ-R08b §1): refusing to open
       reports_post_grl_review/PHASE5/fetch_plan_TN188__MGDS_18210.csv (candidate MGDS_18210)
     ```
   - The admitted roots in phase5 mode are the sealed root/<token>, the OAK output root and the node-local work root, not the record directory.
   - Rehearsal mode has `fetch: False`, so neither the ACQ-R09 nor the ACQ-R11b rehearsal ever reached this line.
   - `chain_p5.fetch` passes `C.REPORT_DIR = record_dir` to the fetcher too, but its log names carry no token. They were not reached here.
7. **§3 must-hold: not reached.** There is no run record, no supplement, no site table and no CNN companion line.
   - The CNN lock dry check (§3.5) was not run: there is no record to check.
   - **The blindness test (§3.4) cannot run as frozen on a phase5 run (H-3).**
   - Log check (CONFIRMED): `logs/acq_r10_p5_47718453.out` (sha256 `0cac2948…`) and `.err` (`96c9626f…`) hold the precondition lines, the guard summary, the traceback (paths only) and `/usr/bin/time` counters. There is no `SITE` line and no depth statistic, amplitude, residual or G value. The logs are safe to open.
8. **What is left on disk, and the record.**
   - An empty `OAK …/phase5/harmonized/.staging/TN188__MGDS_18210/` (the frozen `run_site` clears and recreates a staging directory on the next run).
   - NCEI listing JSON in `$GROUP_SCRATCH/…/discovery_cache/acq_r09_phase5_fetch/` (metadata).
   - Lock 4 is clean: no complete record, no supplement.
   - **Do-not-open list: nothing.** This run wrote no raster, no depth-derived value and no residual. The HR selection lived only in the job's node-local work directory, which was wiped at job end.
   - Committed by explicit path: the directive, this report, the guard self-test record and `sbatch/acq_r10/step1.sbatch` (v3.1), plus one `CHANGE_LEDGER.md` row. There is nothing for OAK `acq_archive/ACQ-R10b/` (no supplement or record).

## §1.6 diff of `sbatch/acq_r10/step1.sbatch` (against its ACQ-R11b re-issue)

```
-R16=grl_reviews-and-prompt-reports/directives_and_reports/R16
-SIGNOFF=$CNN/$R16/SIGNOFF_phase5_prereg_v3.md
-PREREG=3df236e008466919a2b5acf94fb258a6f42abe6235a1ee1b77c0785ca8939d58
+R16=grl_reviews-and-prompt-reports/directives_and_reports/R16c
+SIGNOFF=$CNN/$R16/SIGNOFF_phase5_prereg_v3_1.md
+PREREG=75b72eb6fae3804c7dea61aa4171744a2fcd4fbdb7c3916f3fb98f2c06f2c7b6
-# §1.1 … first sha256 = v3
+# §1.1 … first sha256 = v3.1
 precondition-1 checks: $R16/PREREG_phase5_v3.md -> $R16/PREREG_phase5_v3_1.md; tag phase5-prereg-v3 -> phase5-prereg-v3.1;
                        $R16/SIGNOFF_phase5_prereg_v3.md -> $R16/SIGNOFF_phase5_prereg_v3_1.md (3 lines + the signoff_commit echo)
```

## HOLDs

- **H-1 — a code defect in the frozen phase5-only fetch path stops every site.** `chain_p5.fetch_plan` (l.80–81) writes `fetch_plan_<pair id>.csv` into the record directory `PHASE5/`, which the Phase 5 allowance does not admit for candidate tokens. A frozen resume would stop at the same line. A fix needs a code change, for example writing the plan CSV under the admitted node-local work root or the OAK output root. That means a new freeze (v3), re-tag, re-rehearsal (which should exercise the phase5 fetch path on a development cruise, for example with a phase5-like mode on the mock layout and fetch on), CNN constants l.47–48 and a v3.2 text amendment with a new sign-off. Steve to rule; this needs its own directive.
- **H-2 — the v3.1 sign-off file is formally incomplete; treated as signed by Steve's ruling (2026-10-13, in-session).**
  - Its heading and opening paragraph are still the draft's: "(DRAFT, unsigned)" / "This draft is kept under the `_DRAFT` name …".
  - Its exposure-statement box is unticked ("[ ] confirmed as written  [ ] corrected as follows:").
  - Steve ruled: the sign-off is signed, and the exposure statement is confirmed as written.
  - If a v3.2 sign-off is drafted for H-1, it should carry the corrected heading and a ticked box.
- **H-3 — the frozen blindness test cannot check a phase5 run.** `blind_test_p5.py` reads each pair's `hr.tif` / `lr.tif` / `joint_valid.tif` and text files under `<out_root>/harmonized/<pair id>/`. In phase5 mode those paths carry candidate tokens and are refused by the guard: the test installs no allowance, and installing one outside the step would mean passing a "locks passed" reason that is not true. So directive §3.4 cannot be met with the frozen v2 code. The re-freeze for H-1 should decide how the phase5 blindness check runs: inside the step after the allowance, or as a key and log check only.
