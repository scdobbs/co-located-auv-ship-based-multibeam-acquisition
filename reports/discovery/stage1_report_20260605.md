# Stage 1 staging-download report (2026-06-05)

*Phase 1 of directive v1.5.4 rev 1. No raw-LR fetched. No manifest writes. Read-only against `pairs.parquet`.*

## Counts

- Manifest rows: **94** (85 HR + 9 LR_processed)
- Log entries: **772** (HR rows expand per-file)
  - fetched: 761
  - skipped_present: 10
  - failed: 0
  - size_mismatch_existing: 1
  - unexpected_raw_skipped: 0
- Bytes fetched this run: **25.87 GB**

## Verification gates

| # | gate | result | detail |
|---|---|---|---|
| 1_hr_byte_exactness | hr_byte_exactness | PASS | all fetched HR rows with known expected size match exactly |
| 2_completeness_identity | completeness_identity | PASS | manifest 94; distinct HR logged 85/85, distinct LR logged 8/9 |
| 3_negative_no_raw | negative_no_raw | PASS | zero .all/.gsf files under staging_phase1 |
| 4_manifest_readonly | manifest_readonly | PASS | rows 21/21, bytes 38986/38986, mtime 2026-06-04T19:04:13.492391+00:00 vs 2026-06-04T19:04:13.492391+00:00 |
| 5_untouchable_present | untouchable_present | PASS | DISCOL / 18 Cal DIG / CCZ / TAG all present in manifest |

## Out-of-scope (deferred to Phase 2)

**Raw-LR NOT fetched — 76 raw-LR cruises (41 train/eval companions + 35 raw_lr_to_grid) deferred to Phase 2.**

**41 train/eval HR staged without LR; tier provisional pending Phase-2 ratio finalization — not reclassified here.**

## Staging layout

- Root: `/scratch/groups/hilley/auv_ship_colocated_bathy/staging_phase1`
- Per-HR directory: `<root>/<hr_id_safe>/<files...>` (HR files at root; matching processed LR under `lr/`).
