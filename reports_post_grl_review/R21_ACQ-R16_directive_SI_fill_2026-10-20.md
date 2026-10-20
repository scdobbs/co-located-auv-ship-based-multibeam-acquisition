# DIRECTIVE R21 / ACQ-R16 (both repos): facts and tables to complete the Supporting Information

**Date:** 2026-10-20
**Applies to:** the acquisition repo (Part A, as ACQ-R16) and the CNN repo (Part B, as R21). Each executor does its own part only.
**Report to:**
- `reports_post_grl_review/ACQ-R16/REPORT_ACQ-R16_<date>.md` (Part A);
- `.../R21/REPORT_R21_<date>.md` (Part B).

**Deliverable:** for each item, a ready-to-paste paragraph or table in American English. Each statement cites its source as file and line, commit, or report section.

## 0. Rulings

1. **Read, don't change.** No computation, frozen script or result changes. The only new numbers are Table S3 (B5), computed from frozen held-out predictions with no refitting.
2. **Never guess.** If a fact is not in the code, configs, logs or reports, write "NOT FOUND" and list where you looked. Where the code and a report disagree, give both and say which one actually ran.
3. **Report the as-run value, not a default.** Where a value was changed by a ruling or a later freeze, give the value used for the reported results and name the freeze tag.
4. Commit only the report and the generated table files, by explicit path. No push.

## Part A: acquisition repo (ACQ-R16)

**A1. Ship gridding (Text S1.3).**
- The MB-System version and container digest used for the ship grids.
- Each processing step applied to the raw swath, in order, with the commands and flags as run: cleaning, editing, processing, ancillary files, and any filters.
- The gridding call: `mbgrid` algorithm, weighting, search radius, cell size rule, and any clipping or extension.
- Anything that differed between cruises or sonar families.

**A2. Contract v2.1 products (Text S1.3).** For each of the 14 product features: name, definition, units, lattice, and how it is aggregated to a window. Also give the exact "usable" rule (the registration test between the products and the ship grid, with its half-cell threshold and its gain criterion).

**A3. Co-registration (Text S2.1).**
- The estimator behind `estimate_rigid_xyz`: method, search window, sub-pixel refinement, and how dz is estimated.
- The HR harmonizing step: resampling method, target pixel rule, and why several pairs' as-used pixels differ from their native pixels (the Cal DIG pairs at 2 m, TN159 at 3.25 m).
- Every frozen co-registration QA threshold with its value. Include the overlap area, the joint-valid tile rule, the residual-misfit thresholds and the 30 m development bound, with how that bound was set.

**A4. k sweep (Text S3.2).**
- Candidate k values, the quantity computed for each, and the rule that selects k.
- What produces the statuses "sweep" and "no_curve".
- Which development candidates were dropped for having no k.
- If the sweep lives in the CNN repo instead, say so and point there.

**A5. Blind test 2 values (Text S5.1).** For the five eligible sites, give lr_native (m) and D₁ = ⌈lr_native / hr_res⌉ (pixels), taken from the ACQ-R13 supplement or the data record.

**A6. Per-pair Table S1.** Generate `TableS1_pairs.csv` and `TableS1_pairs.md` from the data record's `pairs.csv`, one row per pair with rasters (52 rows). Columns:
- group, unit, class, region;
- HR dataset (MGDS or PANGAEA id and DOI) and AUV platform and sonar;
- ship cruise, platform and sonar;
- hr_res (m), lr_native (m), k;
- scoring view, co-registration case;
- eligible or status, license.

Sort the rows by group, then class, then unit.

**A7. Dataset references.** Generate `dataset_references.md`, an AGU-format reference for every source dataset in `pairs.csv`: authors, year, title, "[Data set]", publisher or repository, DOI. Take each from its DataCite record (or the NCEI and USGS metadata where there is no DOI). Mark which references are new since the original submission's reference list.

## Part B: CNN repo (R21)

**B1. Target filtering (Text S3.1).**
- The window taper (type and parameters).
- The band-pass filter (Fourier mask shape, transition width, any apodization).
- How the RMS over the central 128 × 128 pixels is computed (mean removal and masking).
- The tile lattice stride.
- The tile validity rule.

**B2. Spectral extrapolation (Text S4.1).** The spectrum estimator, the band over which the power law is fitted, the fit method, and how the predicted fine-band RMS is computed from it.

**B3. GBT (Text S4.2).**
- The library and version.
- The exact feature list per group.
- The target transform.
- The nested leave-one-unit-out search: grid, inner metric, and selection rule.
- The parameters of configuration cfg 18.
- The random seeds.

**B4. CNNs (Text S4.3).**
- The architecture: encoder, decoder or head, channels, depth and parameter count.
- How FiLM is applied.
- Input normalization (confirm that no AUV statistics enter).
- Loss definitions for V0 and V1.
- Optimizer, learning rate and schedule, batch size, steps or epochs, augmentation.
- The stopping rule and its validation split.
- Seeds.
- For pretraining: architecture, masking ratio, pretext loss weights, optimizer, and the 60,000-step schedule.
- GPU type.

**B5. Table S3 (new, descriptive).** Use the frozen held-out predictions, interior tiles, and each pair's frozen view. For every development unit, and for s_lr, GBT_ship and P-V1, compute:
- Spearman ρ;
- Pearson r between log predicted and log observed amplitude;
- R² after removing the mean: within each pair, center log observed and log predicted on their pair means, then compute R² = 1 − Σ(obs_c − pred_c)² / Σ obs_c²;
- R² after removing mean and scale: standardize both within the pair, then apply the same formula. Note in the table caption that this equals 2r − 1.

Summarize multi-pair units the way the frozen evaluation does, and say how that is. Write `TableS3_unit_stats.csv` and `TableS3_unit_stats.md`.

As a check, the Spearman column must equal the frozen values; any difference stops the work.

**B6. Table S2.** Assemble `TableS2_dev_results.csv` and `TableS2_dev_results.md` from frozen outputs only (R05, R08, R08b, R09). Do not recompute anything.
- **Panel A**, interior tiles, one row per unit: class, pairs, scored tiles, view, s_lr ρ with its 95% CI, held-out GBT_ship, V2 and P-V1 ρ, spectral-extrapolation ρ, and median interior A_fine (m). The ten real-relief units come first, then the six, then EW0207.
- **Panel B:** the same rows on all tiles.
- **Panel C:** each multi-pair unit pooled across pairs versus ranked within pairs (R05 §4.2).

State the source file for every column.

**B7. Deviation note 02 (Text S6.1).** Quote its title and summarize its content in two or three sentences, with its ledger row and checksum. Also confirm the checksums and dates of notes 01, 03 and 04 as cited.

**B8. Cross-check.** Confirm or correct these numbers, which the Supporting Information already states:
- the V0 "about equal to V1" value;
- V3 0.425;
- 100 training runs and 59 GPU-hours;
- 124 GPU-hours for pretraining;
- 49,225 pretraining blocks and 60,000 steps;
- the fallback-validation differences (+0.020 and −0.002);
- the pass odds of 41%, 46% and 13%.

## Report (each part)

1. A table with one row per item (A1–A7 or B1–B8) and its status: FILLED, PARTLY FOUND or NOT FOUND.
2. The ready-to-paste text for each item, with its sources.
3. Paths and SHA-256 checksums of the generated table files.
4. Any number already in the drafts that the sources contradict.

## Out of scope

- Any rerun, refit or retraining.
- Any change to frozen code or results.
- Pushing.
