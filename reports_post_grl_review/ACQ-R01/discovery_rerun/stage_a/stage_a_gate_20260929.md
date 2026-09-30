# v1.5 Gate A (v1.5.1 revision) — selection sign-off (2026-09-29)

**No mass download has happened.** This summarises the projected bulk acquisition. Human sign-off is required before Stage B / C starts.

## Criteria (v1.5.1 §4 revision — ratio-only gating)

- Training tier: `5 ≤ res_ratio ≤ 25`
- Eval-only tier: `25 < res_ratio ≤ 40`
- Excluded: `res_ratio > 40` OR `< 5`
- **No processed-grid filter** (v1.5.1 §1): raw LR cruises enter Stage C gridding rather than being dropped at Gate A.
- **No platform filter at the selection gate** (v1.5.1 §4): inclusion is ratio-gated, not platform-gated. `hr_class` ∈ {auv, usv, surface_vessel} is recorded for stratification.
- Non-bathy products (sidescan / sub-bottom / magnetometer) excluded as a data-type rejection.
- Independence verdict ∈ {`independent`, `needs_check`}; no composite or same-platform LR.
- One row per distinct HR; best independent LR companion.

## HR class distribution (informational; not used as a gate)

| hr_class | count |
|---|---:|
| auv | 98 |
| usv | 0 |
| surface_vessel | 32 |

## Tier counts

| tier | HR count |
|---|---:|
| training | 27 |
| eval_only | 12 |
| raw_lr_to_grid | 23 |
| needs_geometry | 51 |
| needs_LR_res | 1 |
| excluded | 16 |
| **total selection** | **130** |

## By terrain (selected HR)

| tier × terrain | abyssal_plain | canyon | continental_margin | hydrothermal_vent | unknown | volcanic_or_seamount |
|---|---|---|---|---|---|---|
| **eval_only** | 0 | 0 | 8 | 0 | 0 | 4 |
| **excluded** | 1 | 0 | 11 | 0 | 2 | 2 |
| **needs_LR_res** | 0 | 0 | 0 | 0 | 1 | 0 |
| **needs_geometry** | 2 | 2 | 11 | 3 | 6 | 27 |
| **raw_lr_to_grid** | 0 | 0 | 10 | 2 | 3 | 8 |
| **training** | 0 | 0 | 17 | 2 | 3 | 5 |

## Geographic clusters (training tier; 50 km radius)

| cluster | training HR | terrain sample |
|---|---:|---|
| cluster_002 | 8 | continental_margin |
| cluster_000 | 5 | volcanic_or_seamount |
| cluster_018 | 4 | continental_margin |
| cluster_001 | 2 | continental_margin |
| cluster_021 | 2 | unknown |
| cluster_007 | 1 | continental_margin |
| cluster_003 | 1 | continental_margin |
| cluster_020 | 1 | continental_margin |
| cluster_022 | 1 | continental_margin |
| cluster_026 | 1 | continental_margin |
| cluster_027 | 1 | volcanic_or_seamount |

## Storage projection

**Processed-grid portion (HR + processed LR):**

- HR (training): **0.87 GB**
- HR (eval-only): **0.62 GB**
- LR (training, processed grids): ~3.96 GB (27 grids × ~150 MB est.)
- LR (eval-only, processed grids): ~1.76 GB
- **Processed subtotal: ~7.20 GB** under `$DATA_ROOT` (`/scratch/groups/hilley/auv_ship_colocated_bathy/`).
- HR-side bytes are exact for MGDS (sum of `data_file_size` from cached geoms XML). Processed-LR sizes are heuristic — true sizes only known after Stage C fetches the grids.

**Raw-LR cruises (routed through Stage C gridding, per v1.5.1 §1):**

- Raw-LR cruises in selection (`raw_lr_to_grid` tier): **23**
- Raw `.all` / `.gsf` cruise files are typically 1–10 GB per cruise-day; total raw-LR ingest is plausibly **50–500 GB** depending on cruise length and sonar.
- A Stage C dry-run (NCEI MBBDB byte-size lookups for the cruise files) will produce a precise number before any raw fetch starts.
- The processed-grid subtotal above does **not** include raw-LR cruises; those are intentionally deferred for sizing.

## M5.0 pilot picks (auto, 9 HR)

| # | hr_id | tier | ratio | hr_class | hr_native_res_m | terrain | cluster |
|---:|---|---|---:|---|---:|---|---|
| 1 | `MANIFEST:2009_Amundsen__MGDS_30046` | training | 15.0 | auv | 1.00 | continental_margin | cluster_002 |
| 2 | `MGDS:16792` | needs_geometry | 17.5 | auv | 2.00 | volcanic_or_seamount | cluster_002 |
| 3 | `MGDS:20836` | needs_LR_res | — | auv | — | unknown | cluster_007 |
| 4 | `MGDS:31429` | training | 12.5 | auv | 2.00 | volcanic_or_seamount | cluster_000 |
| 5 | `MGDS:31425` | training | 7.1 | auv | 3.50 | hydrothermal_vent | cluster_000 |
| 6 | `MGDS:21847` | training | 10.0 | auv | 5.00 | hydrothermal_vent | cluster_001 |
| 7 | `MGDS:31600` | training | 10.2 | auv | 9.80 | continental_margin | cluster_001 |
| 8 | `MGDS:31255` | training | 18.8 | auv | 0.53 | continental_margin | cluster_002 |
| 9 | `MGDS:32321` | training | 15.0 | auv | 1.00 | unknown | cluster_002 |

## Excluded — breakdown by reason (v1.5.2 §0)

| reason | count |
|---|---:|
| ratio_gt_40 (untouchable) | 15 |
| ratio_lt_5 (untouchable) | 1 |
| **total excluded** | **16** |

Ratio rejects (`ratio_gt_40` / `ratio_lt_5`) are genuine and never recovered. CRS-failure rows are the recovery target; the recovery pass writes `crs_recovered` (re-tiered above) / `crs_failed_verification` / `crs_unrecoverable` and these stay excluded for the right reasons.

## Read-only guarantees

- Existing `manifest/pairs.parquet` is not touched by this stage.
- DISCOL, the 18 Cal DIG sub-pairs, CCZ, TAG remain exactly as they are.
- No raster download yet; Stages B–G run only after this gate is signed off.

## What to confirm

1. Tier thresholds (train ≤25×, eval ≤40×) — accept or adjust.
2. Raw-LR cruises remain in selection and route to Stage C gridding (v1.5.1 §1) — confirm. The processed-grid subtotal is the only number sized here; raw-LR total is deferred to a Stage C dry-run.
3. Storage budget — confirm `$DATA_ROOT` can host the processed subtotal **plus** the deferred raw-LR fetch (50–500 GB plausible).
4. Pilot composition — accept or hand-edit `stage_a_selection.yaml`.
