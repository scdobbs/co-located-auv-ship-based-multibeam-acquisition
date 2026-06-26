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
| training | 27 |
| eval_only | 18 |
| raw_lr_to_grid | 28 |
| needs_geometry | 0 |
| needs_LR_res | 1 |
| excluded | 36 |
| **total selection** | **110** |

## By terrain (selected HR)

| tier × terrain | abyssal_plain | canyon | continental_margin | hydrothermal_vent | unknown | volcanic_or_seamount |
|---|---|---|---|---|---|---|
| **eval_only** | 0 | 0 | 11 | 0 | 0 | 7 |
| **excluded** | 2 | 2 | 15 | 1 | 2 | 14 |
| **needs_LR_res** | 0 | 0 | 0 | 0 | 0 | 1 |
| **raw_lr_to_grid** | 0 | 0 | 4 | 2 | 9 | 13 |
| **training** | 0 | 0 | 17 | 3 | 2 | 5 |

## Geographic clusters (training tier; 50 km radius)

| cluster | training HR | terrain sample |
|---|---:|---|
| cluster_000 | 9 | continental_margin |
| cluster_001 | 6 | continental_margin |
| cluster_007 | 3 | continental_margin |
| cluster_004 | 2 | unknown |
| cluster_024 | 2 | continental_margin |
| cluster_002 | 1 | volcanic_or_seamount |
| cluster_006 | 1 | continental_margin |
| cluster_012 | 1 | continental_margin |
| cluster_025 | 1 | continental_margin |
| cluster_026 | 1 | continental_margin |

## Storage projection

**Processed-grid portion (HR + processed LR):**

- HR (training): **1.32 GB**
- HR (eval-only): **2.63 GB**
- LR (training, processed grids): ~3.96 GB (27 grids × ~150 MB est.)
- LR (eval-only, processed grids): ~2.64 GB
- **Processed subtotal: ~10.54 GB** under `$DATA_ROOT` (`/scratch/groups/hilley/auv_ship_colocated_bathy/`).
- HR-side bytes are exact for MGDS (sum of `data_file_size` from cached geoms XML). Processed-LR sizes are heuristic — true sizes only known after Stage C fetches the grids.

**Raw-LR cruises (routed through Stage C gridding, per v1.5.1 §1):**

- Raw-LR cruises in selection (`raw_lr_to_grid` tier): **28**
- Raw `.all` / `.gsf` cruise files are typically 1–10 GB per cruise-day; total raw-LR ingest is plausibly **50–500 GB** depending on cruise length and sonar.
- A Stage C dry-run (NCEI MBBDB byte-size lookups for the cruise files) will produce a precise number before any raw fetch starts.
- The processed-grid subtotal above does **not** include raw-LR cruises; those are intentionally deferred for sizing.

## M5.0 pilot picks (auto, 9 HR)

| # | hr_id | tier | ratio | hr_class | hr_native_res_m | terrain | cluster |
|---:|---|---|---:|---|---:|---|---|
| 1 | `PANGAEA:tag_m127` | training | 17.5 | auv | 2.00 | hydrothermal_vent | cluster_000 |
| 2 | `MGDS:21986` | needs_LR_res | — | auv | — | volcanic_or_seamount | cluster_006 |
| 3 | `MGDS:31188` | training | 15.0 | auv | 1.00 | volcanic_or_seamount | cluster_000 |
| 4 | `MGDS:31425` | training | 17.1 | auv | 3.50 | hydrothermal_vent | cluster_000 |
| 5 | `MGDS:31600` | training | 10.2 | auv | 9.80 | continental_margin | cluster_000 |
| 6 | `MGDS:31255` | training | 18.8 | auv | 0.53 | continental_margin | cluster_001 |
| 7 | `MGDS:31811` | training | 7.5 | auv | 2.00 | volcanic_or_seamount | cluster_002 |
| 8 | `MGDS:32556` | training | 15.0 | auv | 1.00 | volcanic_or_seamount | cluster_004 |
| 9 | `MGDS:32321` | training | 15.0 | auv | 1.00 | unknown | cluster_004 |

## Read-only guarantees

- Existing `manifest/pairs.parquet` is not touched by this stage.
- DISCOL, the 18 Cal DIG sub-pairs, CCZ, TAG remain exactly as they are.
- No raster download yet; Stages B–G run only after this gate is signed off.

## What to confirm

1. Tier thresholds (train ≤25×, eval ≤40×) — accept or adjust.
2. Raw-LR cruises remain in selection and route to Stage C gridding (v1.5.1 §1) — confirm. The processed-grid subtotal is the only number sized here; raw-LR total is deferred to a Stage C dry-run.
3. Storage budget — confirm `$DATA_ROOT` can host the processed subtotal **plus** the deferred raw-LR fetch (50–500 GB plausible).
4. Pilot composition — accept or hand-edit `stage_a_selection.yaml`.
