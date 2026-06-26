# v1.5 Gate A (v1.5.1 revision) — selection sign-off (2026-06-04)

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
| auv | 92 |
| usv | 0 |
| surface_vessel | 18 |

## Tier counts

| tier | HR count |
|---|---:|
| training | 26 |
| eval_only | 15 |
| needs_geometry | 37 |
| needs_LR_res | 17 |
| excluded | 15 |
| **total selection** | **110** |

## By terrain (selected HR)

| tier × terrain | abyssal_plain | canyon | continental_margin | hydrothermal_vent | unknown | volcanic_or_seamount |
|---|---|---|---|---|---|---|
| **eval_only** | 0 | 0 | 8 | 0 | 1 | 6 |
| **excluded** | 1 | 0 | 9 | 0 | 1 | 4 |
| **needs_LR_res** | 0 | 0 | 5 | 2 | 4 | 6 |
| **needs_geometry** | 1 | 2 | 8 | 1 | 5 | 20 |
| **training** | 0 | 0 | 17 | 3 | 2 | 4 |

## Geographic clusters (training tier; 50 km radius)

| cluster | training HR | terrain sample |
|---|---:|---|
| cluster_000 | 9 | continental_margin |
| cluster_001 | 6 | continental_margin |
| cluster_006 | 3 | continental_margin |
| cluster_013 | 2 | continental_margin |
| cluster_004 | 1 | unknown |
| cluster_002 | 1 | volcanic_or_seamount |
| cluster_005 | 1 | continental_margin |
| cluster_024 | 1 | continental_margin |
| cluster_025 | 1 | continental_margin |
| cluster_027 | 1 | unknown |

## Storage projection (rough; LR estimated at ~150 MB per processed grid)

- HR (training): **1.01 GB**
- HR (eval-only): **1.92 GB**
- LR (training): ~3.81 GB (26 grids × ~150 MB)
- LR (eval-only): ~2.20 GB
- **Projected total: ~8.94 GB** under `$DATA_ROOT` (`/scratch/groups/hilley/auv_ship_colocated_bathy/`).
- HR-side estimate is exact for MGDS records (sum of `data_file_size` from cached geoms XML). LR sizes are heuristic — true sizes only known after Stage C fetches the processed grids.
- Raw-LR cruise files are not fetched (per v1.5 decision: processed-grid-only selection at Gate A).

## M5.0 pilot picks (auto, 9 HR)

| # | hr_id | tier | ratio | hr_class | hr_native_res_m | terrain | cluster |
|---:|---|---|---:|---|---:|---|---|
| 1 | `PANGAEA:tag_m127` | training | 17.5 | auv | 2.00 | hydrothermal_vent | cluster_000 |
| 2 | `MGDS:30219` | needs_geometry | 15.0 | auv | 1.00 | volcanic_or_seamount | cluster_003 |
| 3 | `MGDS:31430` | needs_LR_res | — | auv | — | volcanic_or_seamount | cluster_006 |
| 4 | `MGDS:31188` | training | 15.0 | auv | 1.00 | volcanic_or_seamount | cluster_000 |
| 5 | `MGDS:31425` | training | 17.1 | auv | 3.50 | hydrothermal_vent | cluster_000 |
| 6 | `MGDS:31600` | training | 10.2 | auv | 9.80 | continental_margin | cluster_000 |
| 7 | `MGDS:31255` | training | 18.8 | auv | 0.53 | continental_margin | cluster_001 |
| 8 | `MGDS:31811` | training | 7.5 | auv | 2.00 | volcanic_or_seamount | cluster_002 |
| 9 | `MGDS:32321` | training | 15.0 | auv | 1.00 | unknown | cluster_004 |

## Read-only guarantees

- Existing `manifest/pairs.parquet` is not touched by this stage.
- DISCOL, the 18 Cal DIG sub-pairs, CCZ, TAG remain exactly as they are.
- No raster download yet; Stages B–G run only after this gate is signed off.

## What to confirm

1. Tier thresholds (train ≤25×, eval ≤40×) — accept or adjust.
2. Processed-grid-only LR policy at Gate A — accept or expand.
3. Storage budget — confirm `$DATA_ROOT` can host ~projected total.
4. Pilot composition — accept or hand-edit `stage_a_selection.yaml`.
