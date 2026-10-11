# DIRECTIVE ACQ-R07 (Phase 4, step 1, acquisition repo, CPU only): run the frozen sealed step once on the five sealed pairs

**Date:** 2026-10-11
**Author:** steering instance, for Claude Code on Sherlock (acquisition repo)
**Predecessors:** ACQ-R06, ACQ-R06b (tag `phase4-acq-freeze`); CNN repo R11 (tag `phase4-prereg-v2`).
**Report to:** `reports_post_grl_review/ACQ-R07/REPORT_ACQ-R07_<date>.md`
**Compute:** CPU only. One network fetch: the two lockbox LR cruises, from the June plan.
**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK. Metres unless marked.

---

## 0. Purpose

This is **Phase 4 step 1** of `PREREG_phase4_v2.md` (sha256
`9795db3b22d6c54f7a85618dbaccafa054e88487b33236a7b2083ecb8c605979`, tag `phase4-prereg-v2`), signed by Steve on
2026-10-11. It runs the frozen `src/phase4/sealed_step1.py --mode phase4` **once**, unchanged, on the five sealed pairs.
That sets their spacings and k, builds their ship products, and writes `manifest/pairs_phase4_sealed.parquet`.

**This is the first directive that opens sealed files.** It opens them only through the frozen step, after its locks.
Nothing else in this directive opens, lists or computes on a sealed file.

**No code is written or changed in this directive.** If anything does not run as frozen, stop and report it.

**Challenge clause.** Report anything that prevents the run as written, with evidence. Items that are Steve's call
become HOLDs (at most 3).

---

## 1. Preconditions (all checked before the run; any failure stops the directive before the step is started)

1. **Sign-off.** `directives_and_reports/R11/SIGNOFF_phase4_prereg_v2.md` exists in the CNN repo and is committed. Report
   its commit, its sha256, and that it contains `9795db3b22d6c54f7a85618dbaccafa054e88487b33236a7b2083ecb8c605979`.
   Do not edit it.
2. **Pre-registration.** `directives_and_reports/R11/PREREG_phase4_v2.md` in the CNN repo hashes to that value, and the
   tag `phase4-prereg-v2` points to the commit that holds it.
3. **Frozen code.**
   - The acquisition working tree holds every file of `ACQ-R06b/freeze_record.json` at its recorded sha256.
   - `freeze_record.json` hashes to `331c94f01d7d1a2e52fb969c5fb1872aae2cd2ed249a3757b99e9d217b3ac0cb`.
   - The tag `phase4-acq-freeze` exists.

   Report `git status` for those files. Uncommitted changes elsewhere in the tree are reported, not touched.
4. **Single run.** `manifest/pairs_phase4_sealed.parquet` does not exist.
5. **Fixed inputs.** Manifest v2.1, its dropped list and contract v2.1 equal the hashes in ACQ-R06b §0.2.
6. **Guard.** The guard self-test passes (84 / 84 blocked, no allowance) immediately before the run.

## 2. The run

One Slurm CPU job, with the ACQ-R06b rehearsal's resources and the node-local MB-System sandbox:

```
python -m src.phase4.sealed_step1 --mode phase4 \
  --signoff <CNN repo>/directives_and_reports/R11/SIGNOFF_phase4_prereg_v2.md \
  --prereg-sha256 9795db3b22d6c54f7a85618dbaccafa054e88487b33236a7b2083ecb8c605979
```

- No `--run-tag` (the lock refuses one), and `--freeze-record` at its default.
- Record the exact command line, the job id, the node and its CPU model.
- The step runs its locks (sign-off, freeze record, pair list, single run, fetch trigger) and only then opens its
  allowance.

**If the step stops** (a lock refusal, or rule C4) **do not rerun it, and do not change anything.** Report:

- the stop message;
- the run record;
- what was written, and where (the step records every directory mode before and after);
- whether `manifest/pairs_phase4_sealed.parquet` exists.

Report it as a HOLD. Steve decides whether and how the step may run again.

## 3. What the report may and may not contain

The scoring is still to come, and Steve's blind artifact call comes before it. The report therefore carries only what
the pre-registration's step 1 produces, and nothing derived from the AUV grids beyond it.

**Report, per sealed pair:**

- `hr_native_res_m`, `lr_native_res_m` and `res_ratio`, with the source of each (C2a computed or June prior);
- `max_recoverable_k`, `k_sweep_status`, the per-k verdicts and the source of k;
- `cells_across = 256 × hr_native_res_m / lr_native_res_m`, against the development minimum of 3.88;
- the products: built, unavailable (with reason) or none (no k);
- the product flags and `ship_products_usable` with its reason;
- the swath files read and the files expected, with rc;
- for the lockbox pairs, the fetch result (files planned, fetched and verified, volume, sha256 manifest);
- the directory modes before, opened and after, and the files written with their sha256;
- the wall time.

**Do not report:** product QA statistics other than the flags; any sweep curve or spectral value; any HR statistic,
image, hillshade, difference, tile count or amplitude; anything about relief. Do not open the products to look at them.

**Also report:**

- the supplement's sha256 and row count, and that it holds exactly the five pre-registered ids;
- the run record's path, status and sha256, and that it cites the freeze record sha256 and the supplement sha256. The
  CNN repo's step-2 lock reads both.

## 4. After the run

1. Add a row to this repo's `CHANGE_LEDGER.md`: Phase 4 step 1 run, with the supplement and run-record sha256.
2. State in the report the line that the CNN repo's `CHANGE_LEDGER.md` must carry for its supplement lock: the
   supplement's path and sha256. Do not edit the CNN repo. The step-2 directive records it there.
3. Copy the run record, the supplement and each sealed pair's `step1_record.json` and `sweep_record.json` to OAK
   `phase4/acq_step1/`, with `SHA256SUMS` verified at the destination. The products stay in the pairs' own directories.
4. Commit the report and the ledger row.

## 5. Report

- **§1 Bottom line**, at most 8 points, each citing its source file:
  1. the preconditions;
  2. the run (command, job, node), its status, and any stop;
  3. per pair: spacings, k, k source, cells across, products and usability;
  4. the lockbox fetch;
  5. the writes into the sealed directories and the mode restoration;
  6. the supplement and run-record hashes, and the CNN ledger line;
  7. preservation;
  8. anything that did not run as frozen.
- **HOLDs:** at most 3.

## 6. Out of scope

- Running the step more than once, or with any argument other than those in §2.
- Writing or changing code, the manifest, the contract or any existing file.
- Opening, listing or computing on any sealed file outside the frozen step.
- Any statistic, image or inspection of the sealed AUV or ship grids, or of the products.
- Anything in the CNN repo other than reading the files named in §1.
- Tiles, targets, figures, predictions or scores.
- Manuscript text.
