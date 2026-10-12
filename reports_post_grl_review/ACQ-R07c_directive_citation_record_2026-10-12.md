# DIRECTIVE ACQ-R07c (acquisition repo, CPU only): write a citation record that the CNN run-record lock can read

**Date:** 2026-10-12
**Repo:** `co-located-auv-ship-based-multibeam-acquisition`
**Report to:** `reports_post_grl_review/ACQ-R07c/REPORT_ACQ-R07c_<date>.md`
**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.
**Report length:** at most 6 bullets, plus at most 2 HOLDs.

## 0. Purpose

The CNN Phase 4 build (REPORT_R12, HOLD H1, job 47445500) stopped at `phase4_common.load_acq_run_record`
(`phase4_common.py:136`). That lock requires
`locks.lock2_freeze_record.freeze_record_sha256 == 331c94f01d7d1a2e52fb969c5fb1872aae2cd2ed249a3757b99e9d217b3ac0cb`.
The ACQ-R07b completion record carries the same value under `locks.lock2_frozen_code.freeze_record_sha256` and at
top level, so the lock refuses it. Status, mode and `supplement_sha256` all match.

Steve ruled option (a): add one new record, written by a new small script, that carries the citation under the
expected key. The value is correct; only the key is missing. No value is recomputed. No sealed file is opened.
`phase4_common.py`, the pre-registration and every hash-pinned script stay unchanged.

**Challenge clause.** If any instruction here is wrong or underspecified against the code or the files on disk,
stop at that point, give the evidence, and report it as a HOLD. Do not work around it.

## 1. Read the CNN lock and its consumers (read only)

The CNN repo is `<CNN repo>/grl_reviews-and-prompt-reports/directives_and_reports/`. Read only. Edit nothing.

1. Report the sha256 of `phase4/scripts/phase4_common.py` and compare it with the B6 table in
   `R11/PREREG_phase4_v2.md` (expected prefix `ef70653f`).
2. Read `load_acq_run_record` and every helper it calls. Report:
   1. the directory, glob or file pattern it reads;
   2. how it chooses when several records exist, for example the first match, exactly one match required, or order
      by name or mtime;
   3. every key and value it checks, and what it returns.
3. In all five Phase 4 scripts (`phase4_common.py`, `phase4_build.py`, `phase4_figures.py`, `phase4_predict.py`,
   `phase4_score.py`), list every field that any script reads from the record that `load_acq_run_record` returns.
   Give file and line for each.
4. Report whether importing `phase4_common` has any side effect: a write, a directory creation, a guard install, or a
   lock call at import time.

## 2. Preconditions (verify on disk before writing anything)

| item | expected |
|---|---|
| `reports_post_grl_review/ACQ-R06b/freeze_record.json` | `331c94f01d7d1a2e52fb969c5fb1872aae2cd2ed249a3757b99e9d217b3ac0cb` |
| `reports_post_grl_review/ACQ-R06b/step1_run_phase4_completion.json` | `fb1e07b24681e8b7b15dec3b232ea78266c6c7cd82ae64518e82b76ae99dcc07` |
| `manifest/pairs_phase4_sealed.parquet` | `6968e04554ddeef3c335587d602cb5fab2185db32b46cbd152475a919eb59206` (hash only; do not open or read the file) |
| stopped ACQ-R07 run record | `7cc5b46d437a72976027f8e7ca9b0f31a8b9eeb5161928c67fce41f87127ce2b` |
| completion script and completion freeze record | as recorded in REPORT_ACQ-R07b, at tag `phase4-acq-complete-v2` |
| the five Phase 4 scripts in the CNN repo | equal to the B6 table and clean in git |

Any mismatch stops the directive and is reported as a HOLD.

## 3. Write the record

1. **Name and place the file.**
   - Use the selection rule from §1.2 so that the lock selects the new record, and so that after writing exactly one
     record in the directory satisfies the lock: the new one.
   - If the lock's pattern allows it, choose a name that does not match the completion script's own
     single-completion pattern (its lock 7).
   - If the lock cannot select the new record without renaming, moving or editing an existing file, stop and report
     a HOLD.
2. **Write a new script,** `src/phase4/write_citation_record.py`. It must:
   1. re-verify every hash in §2 and refuse on any mismatch;
   2. refuse to run if the output file already exists;
   3. run under the acquisition guard, self-tested first, and open no sealed file;
   4. write one JSON record containing:
      - every top-level field and every `locks` entry of the completion record, copied verbatim (a full copy, not
        only the fields the lock checks, because §1.3 may show downstream scripts read others);
      - `locks.lock2_freeze_record.freeze_record_sha256` = `331c94f01d7d1a2e52fb969c5fb1872aae2cd2ed249a3757b99e9d217b3ac0cb`;
      - `record_type`: `"citation"`;
      - `produced_by`: `"src/phase4/write_citation_record.py"` with its git commit;
      - `cites`: the completion record's path and sha256, and the stopped ACQ-R07 record's path and sha256;
      - `purpose`: `"label correction for the CNN run-record lock (REPORT_R12 H1); no value recomputed; not a run record"`.
3. **Run it once.** Report the new record's path and sha256.
4. **Must hold:**
   1. Every field copied from the completion record is byte-equal in value to its source. Check this by loading
      both files and comparing them, and report the result.
   2. The new record differs from the completion record only by the added keys listed in §3.2.4.
   3. No existing file in `ACQ-R06b/` changed. Report its sha256 listing before and after.

## 4. Dry check of the lock only

1. In a fresh Python process started with `python -B` (no `__pycache__` may be written into the CNN repo), install
   and self-test the R09 guard first (702 / 702 probes blocked).
2. Import the CNN `phase4_common` without editing it.
3. Call `load_acq_run_record("6968e04554ddeef3c335587d602cb5fab2185db32b46cbd152475a919eb59206")` and nothing else.
4. Report:
   1. that it passes;
   2. which record path it returned;
   3. that each field from §1.3 is present in the returned record.

Call no other Phase 4 function. Report `git status` of the CNN repo's `phase4/` directory before and after this
check; the two must be identical.

## 5. After

1. Commit the script, the new record and the report by explicit path, never with `git add -A`.
2. **Permitted appends.** Only two writes to existing files are allowed:
   - one new row in this repo's `CHANGE_LEDGER.md`;
   - one new line in the OAK `phase4/acq_step1/SHA256SUMS`.
3. Copy the new record to OAK `phase4/acq_step1/` and verify `SHA256SUMS` at the destination.
4. In the report, give:
   1. the exact companion line for the CNN `grl_reviews-and-prompt-reports/CHANGE_LEDGER.md` (path and full sha256
      of the new record);
   2. a draft `DEVIATION_phase4_02.md` of at most 8 lines for Steve to sign. It states:
      - what happened;
      - that the lock now accepts a citation record written by a new script, not a record written by the frozen
        step-1 or completion code, as pre-registration §A2.2 assumed;
      - that no rule, value, pinned script or pinned hash changed.

   Do not write to the CNN repo.

## 6. Out of scope

- Editing, renaming or moving any existing file, apart from the two appends in §5.2. This includes the completion
  record, the completion script, the freeze records and `phase4_common.py`.
- Rerunning step 1 or the completion script.
- Opening, listing or computing on any sealed file or sealed directory content.
- Any write to the CNN repo, including bytecode.
- Calling any Phase 4 function other than `load_acq_run_record`.

## 7. Not pursued

- Why the ACQ-R07b completion script wrote the citation under `lock2_frozen_code`.
- Any change to the CNN lock to accept either key.
