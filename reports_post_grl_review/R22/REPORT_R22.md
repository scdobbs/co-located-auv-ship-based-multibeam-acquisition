# REPORT R22 — per-unit 95 % bootstrap CIs for SI Table S2, Panels A and B (descriptive, no new test)

**Directive:** R22 (Steve, 2026-10-20). **Rulings applied:** the frozen scoring code was reused unchanged and no frozen output was modified; the point estimates were checked against Table S2 before reporting; outputs written to `reports_post_grl_review/R22/` and committed by explicit path, not pushed. Job 48704708 (normal partition, 4 CPUs, 574 s). The generator script is `/scratch/users/scdobbs/tmp_r16/make_r22.py` (not committed, as instructed; its logic is described below and is 90 lines calling the frozen functions).

## Method

- **Data (frozen, read only):** the R08b master tile table `grl_review_archive/R08b/scores/master_tile.parquet` (23,438 development tiles; held-out `ref_s_lr`, `GBT_ship_A_fine`, `V2_seedavg`, `P-V1_seedavg`; target `A_fine`; flag `interior_D1`) and `master_tile_EW0207.parquet` (2,716 tiles), joined on `tile_id` with the R08 wide-window table `R08/wide_window/rows_W64.parquet` for `shat_fine_W64`. Tile coordinates r0, c0 are parsed from `tile_id`.
- **Panels:** A = tiles with `interior_D1`; B = all tiles. Predictors: s_lr, GBT_ship, V2 (seed-averaged), P-V1 (seed-averaged); Panel B adds the spectral extrapolation on the 64-cell window.
- **Pair eligibility:** `eval_v1_1.eligible_pairs` (frozen, tag `phase0-freeze`): a pair is eligible for a predictor when at least 10 tiles of the panel have a finite target and a finite prediction. The `pairs` and `tiles` columns below count eligible pairs and their tiles for s_lr; the csv carries them per predictor. This is why lu05 shows 1 eligible pair on interior tiles (TN399 (MGDS 33068) and AT42-06 have fewer than 10 interior tiles) and lu12 shows 17 (luciachica_2007), while Table S2's "scored tiles" counts interior tiles over all pairs (5,021 and 1,863).
- **Point estimate:** within-pair Spearman ρ (`eval_v1_1.rho`), unit value = median over eligible pairs, as in Table S2.
- **Bootstrap (frozen `phase4_score.blocks_of` and `resample_rhos`):** blocks are 4 × 4 tiles, block = (r0 // 512, c0 // 512); one `numpy.random.default_rng(20261009)` per (unit, predictor, panel); eligible pairs taken in ascending pair-id order, and for each pair 2,000 resamples of its blocks with replacement (same number of blocks), drawn in sequence from that generator, exactly as `phase4_score.pooled_row` does for units; the unit value of resample r is the median over the pairs of their resample-r ρ; the CI is the 2.5th and 97.5th percentiles of the defined resamples; a CI is estimable when at most 5 % of resamples are undefined (`UNDEF_MAX_FRAC`). No resample was undefined for any row.
- **Check:** every point estimate was compared with the value in Table S2 (R08b `per_unit_ten.md` / `per_unit_six.md` "all / D1", R08b `EW0207.md`, R08 `wide_per_unit.md`): 154 of 155 rows agree to the two decimals of those tables; the one non-match is a value Table S2 did not have (below). lu06 agrees: on interior tiles s_lr +0.60 (CI [+0.42, +0.74]), on all tiles +0.32 ([+0.14, +0.45]). The lower value in Table S3 (+0.325) is that pair's frozen fallback view (A_fine_int on all tiles with a defined interior target), not the interior-D1 subset; both are frozen values and neither was changed.

## Mismatches and additions (reported, nothing overwritten)

- **EW0207 spectral extrapolation, Panel B:** Table S2 had NOT FOUND (no frozen per-unit value for EW0207). Computed from the frozen per-tile `shat_fine_W64` values (2,707 tiles): **+0.32 [+0.23, +0.41]**. Flagged in the csv as `matches_table_S2 = False`, `table_S2_value = NOT IN TABLE`.
- **EW0207 V2:** Table S2 reports the seed-20261002 model (+0.478 interior, +0.498 all) because the frozen `EW0207.md` table lists no seed average. The frozen master table does carry `V2_seedavg` for EW0207: +0.51 [+0.43, +0.57] interior and +0.52 [+0.46, +0.58] all. Both are in the csv (`V2` = seed average, `V2_seed20261002`); the table below uses the seed average for consistency with the other units, and Table S2's EW0207 V2 cell should be updated or footnoted by Steve, not by this report.
- lu14 has no interior tiles: Panel A left blank (`rho` NaN, `n_tiles` 0).

## Table S2 with 95 % CIs, "ρ [lo, hi]"

### Panel A: interior tiles (D1)

| unit | class | pairs | tiles | s_lr | GBT_ship | V2 | P-V1 |
|---|---|---|---|---|---|---|---|
| lu00 | real-relief | 1 | 2157 | +0.51 [+0.39, +0.61] | +0.54 [+0.43, +0.64] | +0.53 [+0.43, +0.63] | +0.59 [+0.49, +0.67] |
| lu04 | real-relief | 1 | 86 | +0.38 [+0.20, +0.59] | +0.32 [+0.14, +0.54] | +0.37 [+0.17, +0.58] | +0.36 [+0.18, +0.59] |
| lu05 | real-relief | 1 | 5019 | +0.18 [+0.12, +0.25] | +0.22 [+0.16, +0.27] | +0.19 [+0.13, +0.25] | +0.25 [+0.19, +0.30] |
| lu07 | real-relief | 2 | 79 | +0.49 [+0.01, +0.60] | +0.54 [+0.09, +0.64] | +0.39 [+0.02, +0.61] | +0.56 [+0.22, +0.64] |
| lu08 | real-relief | 1 | 969 | +0.63 [+0.52, +0.72] | +0.53 [+0.41, +0.62] | +0.64 [+0.54, +0.72] | +0.58 [+0.46, +0.67] |
| lu09 | real-relief | 1 | 631 | −0.09 [−0.25, +0.10] | +0.10 [−0.05, +0.24] | −0.03 [−0.19, +0.16] | +0.19 [+0.07, +0.31] |
| lu13 | real-relief | 2 | 4844 | +0.59 [+0.51, +0.66] | +0.51 [+0.44, +0.57] | +0.70 [+0.66, +0.74] | +0.59 [+0.54, +0.64] |
| lu14 | real-relief | 0 | 0 | — | — | — | — |
| lu15 | real-relief | 2 | 670 | +0.17 [+0.04, +0.29] | +0.24 [+0.12, +0.35] | +0.23 [+0.11, +0.33] | +0.25 [+0.13, +0.36] |
| nu00 | real-relief | 1 | 523 | +0.39 [+0.27, +0.51] | +0.37 [+0.22, +0.50] | +0.50 [+0.40, +0.60] | +0.33 [+0.20, +0.46] |
| lu02 | artifact-affected | 1 | 214 | +0.59 [+0.27, +0.83] | +0.51 [+0.29, +0.69] | +0.56 [+0.27, +0.78] | +0.08 [−0.21, +0.34] |
| lu06 | artifact-affected | 1 | 44 | +0.60 [+0.42, +0.74] | +0.64 [+0.35, +0.79] | +0.62 [+0.44, +0.77] | +0.59 [+0.40, +0.74] |
| lu10 | artifact-affected | 1 | 119 | +0.34 [+0.07, +0.56] | +0.17 [−0.08, +0.39] | +0.31 [+0.03, +0.55] | −0.09 [−0.34, +0.23] |
| lu11 | artifact-affected | 1 | 118 | −0.01 [−0.33, +0.33] | +0.25 [+0.01, +0.42] | +0.37 [+0.17, +0.55] | +0.03 [−0.24, +0.29] |
| lu12 | artifact-affected | 17 | 1857 | +0.55 [+0.38, +0.62] | +0.53 [+0.41, +0.61] | +0.53 [+0.41, +0.60] | +0.62 [+0.49, +0.65] |
| vu02 | artifact-affected | 1 | 57 | +0.65 [+0.28, +0.84] | +0.69 [+0.43, +0.84] | +0.13 [−0.19, +0.49] | +0.66 [+0.30, +0.81] |
| lu16 | EW0207 | 1 | 1621 | +0.51 [+0.44, +0.58] | +0.48 [+0.40, +0.54] | +0.51 [+0.43, +0.57] | +0.53 [+0.46, +0.60] |

### Panel B: all tiles

| unit | class | pairs | tiles | s_lr | GBT_ship | V2 | P-V1 | spectral (64-cell) |
|---|---|---|---|---|---|---|---|---|
| lu00 | real-relief | 1 | 2591 | +0.55 [+0.44, +0.64] | +0.56 [+0.46, +0.65] | +0.55 [+0.45, +0.64] | +0.56 [+0.46, +0.64] | +0.01 [−0.10, +0.12] |
| lu04 | real-relief | 1 | 184 | +0.50 [+0.33, +0.62] | +0.53 [+0.38, +0.64] | +0.55 [+0.41, +0.65] | +0.56 [+0.44, +0.65] | +0.18 [−0.06, +0.37] |
| lu05 | real-relief | 3 | 6458 | +0.27 [−0.06, +0.40] | +0.28 [+0.02, +0.35] | +0.26 [+0.21, +0.37] | +0.30 [+0.22, +0.48] | −0.02 [−0.26, +0.17] |
| lu07 | real-relief | 2 | 351 | +0.54 [+0.39, +0.66] | +0.47 [+0.31, +0.60] | +0.55 [+0.41, +0.66] | +0.56 [+0.43, +0.67] | +0.35 [+0.17, +0.50] |
| lu08 | real-relief | 1 | 1252 | +0.65 [+0.56, +0.73] | +0.57 [+0.48, +0.66] | +0.64 [+0.55, +0.72] | +0.61 [+0.52, +0.69] | −0.37 [−0.51, −0.21] |
| lu09 | real-relief | 1 | 772 | +0.05 [−0.10, +0.20] | +0.18 [+0.06, +0.29] | +0.10 [−0.05, +0.25] | +0.27 [+0.17, +0.36] | +0.36 [+0.22, +0.48] |
| lu13 | real-relief | 2 | 6413 | +0.54 [+0.47, +0.59] | +0.49 [+0.43, +0.54] | +0.67 [+0.63, +0.70] | +0.57 [+0.53, +0.61] | −0.13 [−0.21, −0.06] |
| lu14 | real-relief | 1 | 52 | +0.81 [+0.77, +0.89] | +0.66 [+0.51, +0.77] | +0.77 [+0.71, +0.87] | +0.68 [+0.49, +0.84] | +0.11 [−0.33, +0.41] |
| lu15 | real-relief | 2 | 1278 | +0.25 [+0.15, +0.35] | +0.36 [+0.26, +0.45] | +0.35 [+0.26, +0.43] | +0.34 [+0.23, +0.42] | +0.07 [−0.03, +0.18] |
| nu00 | real-relief | 1 | 732 | +0.40 [+0.27, +0.51] | +0.36 [+0.22, +0.49] | +0.52 [+0.42, +0.61] | +0.29 [+0.17, +0.41] | −0.03 [−0.15, +0.09] |
| lu02 | artifact-affected | 1 | 300 | +0.62 [+0.40, +0.78] | +0.71 [+0.52, +0.81] | +0.73 [+0.53, +0.85] | +0.34 [+0.18, +0.51] | −0.50 [−0.63, −0.27] |
| lu06 | artifact-affected | 1 | 69 | +0.32 [+0.14, +0.45] | +0.82 [+0.71, +0.88] | +0.81 [+0.70, +0.88] | +0.85 [+0.72, +0.91] | +0.25 [−0.04, +0.52] |
| lu10 | artifact-affected | 1 | 174 | +0.43 [+0.13, +0.63] | +0.27 [+0.06, +0.48] | +0.43 [+0.12, +0.62] | +0.14 [−0.08, +0.38] | +0.39 [+0.15, +0.57] |
| lu11 | artifact-affected | 1 | 206 | −0.08 [−0.28, +0.14] | +0.27 [+0.12, +0.43] | +0.47 [+0.30, +0.60] | +0.30 [+0.12, +0.46] | +0.19 [+0.04, +0.38] |
| lu12 | artifact-affected | 18 | 2497 | +0.34 [+0.23, +0.44] | +0.60 [+0.54, +0.66] | +0.61 [+0.54, +0.65] | +0.58 [+0.53, +0.65] | −0.30 [−0.37, −0.20] |
| vu02 | artifact-affected | 1 | 109 | +0.57 [+0.30, +0.71] | +0.73 [+0.61, +0.78] | +0.26 [−0.01, +0.47] | +0.60 [+0.39, +0.70] | +0.25 [+0.01, +0.50] |
| lu16 | EW0207 | 1 | 2716 | +0.55 [+0.49, +0.61] | +0.47 [+0.40, +0.53] | +0.52 [+0.46, +0.58] | +0.56 [+0.50, +0.62] | +0.32 [+0.23, +0.41] |

Caption to add to Table S2: "95 % intervals are block bootstraps (4 × 4-tile blocks resampled within each pair, 2,000 resamples, seed 20261009; the unit value of each resample is the median over its eligible pairs), the same procedure as the blind-test scoring; they describe sampling variation within a unit and are not a test."

## Files

| file | sha256 |
|---|---|
| `reports_post_grl_review/R22/table_S2_unit_CIs.csv` (155 rows: unit, panel, predictor, rho, ci_lo, ci_hi, n_tiles, n_pairs, estimable, frac_undefined, table_S2_value, matches_table_S2) | `852796216e70408fab87763c3e34ec03ce4938db4e9fd33e48a042a150a15a17` |
| `reports_post_grl_review/R22/mismatches.csv` (the one row above) | see `sha256sum` |
