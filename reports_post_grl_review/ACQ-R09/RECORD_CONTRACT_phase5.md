# RECORD CONTRACT — Phase 5 step-1 run record (ACQ-R09 §2.9; input to R16's CNN lock)

**Producer:** `src/phase5/sealed_step1_p5.py` (frozen: `reports_post_grl_review/PHASE5/freeze_record_phase5.json`, tag `phase5-acq-freeze`).
**Written by:** `write_run_record` → `<record_dir>/step1_run_<mode>_<tag>.json`, mode 0444, never overwritten.

| mode | record_dir | file name | supplement |
|---|---|---|---|
| `phase5` | `reports_post_grl_review/PHASE5/` | `step1_run_phase5_<UTC yyyymmddThhmmssZ>.json` | `manifest/pairs_phase5_sealed.parquet` |
| `rehearsal` | `reports_post_grl_review/ACQ-R09/rehearsal/` | `step1_run_rehearsal_<run-tag>.json` | `ACQ-R09/rehearsal/supplement_rehearsal_<run-tag>.parquet` |

A stopped run writes a record with `status: "stopped"` (and `error`); only a record with `status: "complete"` counts.
A later run re-uses finished sites; there is at most one complete phase5 record (lock 4).

## 1. What the CNN lock must check (parameterised copy of `phase4_common.load_acq_run_record`)

Glob `step1_run_phase5_*.json` in `reports_post_grl_review/PHASE5/`; accept the first record with

- `status == "complete"`, `mode == "phase5"`;
- `locks.lock2_freeze_record.freeze_record_sha256 == <sha256 of PHASE5/freeze_record_phase5.json>` (also at top level: `freeze_record_sha256`);
- `supplement_sha256 == sha256(manifest/pairs_phase5_sealed.parquet)`;
- the freeze record itself hashes to the cited value and lists `src/phase5/sealed_step1_p5.py` (key `files`) at the sha256 the lock pins.

Return `path, sha256, status, mode, freeze_record_sha256, supplement_sha256, code_commit, per_pair`.
Rehearsal check (ACQ-R09 §3.3.4): the same code with `phase4` → `rehearsal` in the glob and the mode test, pointed at
`ACQ-R09/rehearsal/` and the freeze record; see `ACQ-R09/rehearsal/cnn_lock_check_<tag>.json`.

## 2. Top-level keys (every complete record)

`directive, mode, run_tag, sites, site_list{path, sha256}, out_root, work_root, sealed_root, fetch, started, host, cpu_model,
code_commit, nproc, batch_files, mbsystem, sandbox, container_digest, rulings, fixed_input_sha256, guard_selftest, locks,
freeze_record_sha256, allowance, loaded_repo_files, status, supplement, supplement_sha256, supplement_schema, n_rows,
pairs_done, per_pair, ledger, wall_s, finished`.

`locks` (phase5 mode): `lock1_signoff{signoff, prereg_sha256, signoff_sha256}`, `lock2_freeze_record{freeze_record,
freeze_record_sha256, n_files, n_loaded_checked}`, `lock3_site_list{site_list, site_list_sha256, sites}`,
`lock4_single_run{supplement, complete_records_found}`, `lock2_after_run{…same as lock2…}`.
Rehearsal records carry `lock2_freeze_record` and `lock2_after_run` when run with `--freeze-record`, nothing else.

## 3. `per_pair[<pair id>]` keys

Pair id = `<ship cruise>__<hr id with ':'→'_'>` (e.g. `TN188__MGDS_18210`).

| key | type | meaning |
|---|---|---|
| `pair_id, site_name, hr_id, lr_cruise, unit, designation` | str | site identity; unit `p5u01`…`p5u08` (site-list order); designation `phase5_sealed` |
| `path` | str | harmonized directory relative to `out_root` (`harmonized/<pair id>`) |
| `out_root` | str | OAK `…/auv_ship_colocated_bathy/phase5` in phase5 mode |
| `hr_native_res_m` | float | round(\|hr.tif pixel\|, 3) |
| `lr_native_res_m` | float | round(max(beam footprint, posting), 2) (C2a) |
| `res_ratio` | float | round(lr / hr, 2) |
| `hr_res_m_unrounded` | float | \|hr.tif pixel\| |
| `beam_footprint_m, posting_m, ship_grid_cell_m` | float | spacing components |
| `values_source` | str | `C2a rule computed by this step (Phase 5)` |
| `max_recoverable_k` | int or null | frozen C2c sweep |
| `per_k` | dict {"2".."32": verdict} | sweep verdicts |
| `k_sweep_status` | str | `ok`, `no_curve`, … |
| `k_source` | str | `stage_c2c_recalibrate.sweep (this run)` (CNN `k_source_class` → `sweep`) |
| `products` | str | `built` / `unavailable` / `none` (no k: rule C3) |
| `products_reason, flags` | str / list | builder reason; contract-v2.1 flags |
| `ship_products_usable, usable_reason` | bool / str | frozen Phase 4 rule C1 |
| `coreg_pass` | bool | eligibility 1 = harmonize_new `qa_pass` (offset ≤ 30 m, overlap ≥ 1 km², ≥ 1 256-tile) |
| `qa_components` | dict of bool | `offset_within_30m, overlap_ge_1km2, tiles_gt_0, coreg_estimated` |
| `n_valid_tiles_256` | int | 256-px tiles with ≥ 50 % joint-valid cells (stride 256) |
| `k_recoverable` | bool | eligibility 2 |
| `cells_across` | float | 256 × `hr_res_m_unrounded` / `lr_native_res_m` |
| `hr_res_in_range` | bool | 0.985 ≤ `hr_res_m_unrounded` ≤ 4.99 |
| `eligible` | bool | items 1–3 all hold and `cells_across` ∈ [3.88, 51.2] |
| `eligibility_reason` | str | "" if eligible, else the failed items |
| `status` | str | `eligible (C1 set at step 1)` / `not testable` |
| `hr_grids` | dict | `n_files, n_grids_read, group_m, kept[], mosaic{kind, grids[]}` |
| `ship_swath_files` | int | swath files read (disk == fetch manifest) |
| `fetch` | dict or null | `n_ok, n_planned, complete` (phase5 mode) |
| `site_record_sha256` | str | sha256 of `<out_root>/<path>/site_record.json` |
| `reused, wall_s` | bool / float | re-used from a stopped run; wall time |

No key of `per_pair` or of a site record contains a depth statistic, amplitude or residual (checked in code by
`common_p5.forbidden_keys`).

## 4. Supplement (`manifest/pairs_phase5_sealed.parquet`)

The 64 fields of `manifest/pairs_phase4_sealed.parquet` (sha256 `6968e045…`), same names, same order, same arrow types
(including `products_v2_flags: null`), asserted in code, then six eligibility fields: `coreg_pass bool, k_recoverable bool,
cells_across double, hr_res_in_range bool, eligible bool, eligibility_reason string`.  One row per site (8).
**R16 note:** `phase4_common.load_supplement` compares `list(sup.columns)` with manifest v2.1's columns; the Phase 5 copy
must compare the first 64 columns and accept exactly these six extra ones.  Path columns (`harmonized_path*`, masks, `footprint_wkt`) are relative to OAK's root as in
the v2.1 rows (`phase5/harmonized/<pair id>/hr.tif`); rehearsal rows hold absolute scratch paths; `row_status` needs `harmonized_path_hr`, `harmonized_path_lr`,
`lr_native_res_m` (present for every site that was harmonized).  `depth_min_m`/`depth_max_m` are null (no depth statistic).

## 5. Notes for R16 (from the ACQ-R09 rehearsal)

- The extracted lock's refusal messages keep the word "phase4"; only the glob and the mode test are parameterised.
- `vertical_offset` (contract v2.1) uses its 0.5 m fallback threshold for every Phase 5 site (no CNN s_lr exists for them), as for the Phase 4 sealed pairs.
- Rehearsal record for the dress rehearsal: `ACQ-R09/rehearsal/step1_run_rehearsal_r09.json` (cites freeze record `67695831…d1d9d1`).
