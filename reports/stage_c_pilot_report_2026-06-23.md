# Phase 2 — Stage C gridding PILOT report

**Date:** 2026-06-23 · **Author:** Claude Code execution instance (Sherlock)
**Directive:** `reports/directive_phase2_stage_c_gridding_pilot.md`
**Status:** ⛔ **HOLD for assessment review** before any full Stage C run. No re-tier, no harmonization, no manifest/OAK writes.

> **Revision note (2026-06-23):** an earlier draft measured fill/native-res over the grid **bounding box**; corrected here to the **true HR footprint polygon** (the AUV footprint is a thin strip = 7–18 % of the grid bbox). This materially raised the realized fill and lowered native-res/ratio for sparse-bbox cruises, and **moved one pair from eval into the training band** (FK181031×24367). QC overlays regenerated with the real polygon outline. Numbers below are the corrected, polygon-masked values.

**Artifacts**
- Gridded LR + QC overlays: `$DATA_ROOT/raw_lr_gridded/` (7 `.grd` + 7 `overlay_*.png`)
- `reports/discovery/stage_c_pilot_measurements.json` (carries both `fill_fraction` (polygon) and `fill_fraction_bbox`)
- `reports/mbsystem_build_pin.txt` (C0 reproducibility pin)
- Code: `src/discovery/stage_c_pilot.py` (grid), `stage_c_remeasure.py` (polygon fix)

---

## 1. Pilot set (5 cruises → 7 pairs) and corrected results

| pair | LR sonar | grid depth | HR res | achieved cell | **fill (footprint)** | lr_native | **ratio** | band | cov |
|---|---|---|---|---|---|---|---|---|---|
| FK181031 × MGDS:24367 | EM302 | ~3.8 km | 2.0 m | 43.1 m | 0.93 | 44.8 m | **22.4** | **TRAIN** | near_nadir |
| AR26 × MGDS:31838 | EM710 | ~1.6 km | 1.0 m | 29.4 | 0.83 | 32.3 | **32.3** | eval | near_nadir |
| KN210-05 × MGDS:22436 | SeaBeam 3012 | ~3.3 km | 2.0 m | 87.5 | 1.00 | 87.5 | **43.8** | exclude | near_nadir |
| TN299 × MGDS:27339 | EM302 | ~3.0 km | 1.0 m | 51.3 | 0.41 | 80.0 | **80.0** | exclude | near_nadir |
| 2009_Amundsen × MGDS:30045 | EM302 | −554 m | nan¹ | 16.0 | 0.66 | 19.6 | nan¹ | Stage D | near_nadir |
| FK181031 × MGDS:24620 | EM302 | ~3.8 km | nan¹ | 65.8 | 1.00 | 65.8 | nan¹ | Stage D | near_nadir |
| TN299 × MGDS:31256 | EM302 | ~2.1 km | nan¹ | 36.8 | 0.91 | 38.5 | nan¹ | Stage D | near_nadir |

¹ HR native res unknown in the catalog (`native_res_m` = NaN, bucket `ok`). All HR are AUV Reson 7125 (1–2 m). **3 of 7 pairs cannot be tiered until Stage D derives the HR native res** — and since 1 m vs 2 m flips a pair between exclude and train (see §2), Stage D is decisive, not cosmetic.

All 7 gridded successfully; MB-System 5.8.2beta06 (Apptainer sandbox, image `sha256:106f502d…`). Depths sane (margin/deep/Arctic).

---

## 2. ⭐ Headline — ratio = LR_native(depth) ÷ HR_native; both matter, and so does footprint-coverage density

The pilot spans **training → eval → exclude** — it is *not* "deep pairs never train." Three knobs set the band:

1. **Depth → LR native res.** Ship-MBES footprint ≈ `2·depth·tan(beam/2)`, so deep LR is coarse (TN299/KN210/FK181031 at 2–3.8 km → 45–88 m; AR26 margin → 32 m).
2. **HR native res (1 m vs 2 m) is just as decisive.** Same-depth-class pairs split on it: TN299×27339 (3.0 km, **1 m** HR) → ratio **80, exclude**; FK181031×24367 (3.8 km, **2 m** HR, dense coverage) → ratio **22, train**. A 2 m HR halves the ratio.
3. **Footprint-coverage density.** The corrected (polygon) fill is what sets native res. The bbox measurement understated coverage badly for cruises whose ship track is a thin strip aligned with the AUV footprint (FK181031×24367: bbox-fill 0.33 → footprint-fill 0.93).

**So:** deep abyssal pairs with 1 m HR exclude on ratio (TN299); deep pairs with 2 m HR + dense coverage can train (FK181031); margin pairs land mid (AR26 eval). Training is **not** margin-exclusive, but it is **selective** — it needs the depth/HR-res/coverage combination to land ≤25×. **Flag for assessment:** how many of the full corpus hit that combination determines the training-set size, and the answer hinges on the Stage-D HR-res values (3 of 7 pilot pairs are currently unknowable).

---

## 3. Estimator calibration

The physics estimate (`2·depth·tan(beam/2)`) was used as the grid cell, so achieved == estimate. The real test is **footprint fill at that cell**, now measured over the true polygon:

- **Dense (fill 0.83–1.00):** AR26, FK24367, FK24620, KN210, TN31256 — estimate matches; native ≈ cell.
- **Sparse (fill 0.41–0.66):** TN299×27339, Amundsen — realized native ~1.2–1.6× coarser (`native = cell/√fill`).

The estimate predicts the achievable cell well, **but must be paired with the polygon-fill check** — the bbox proxy is not a safe substitute (it mis-ranked FK181031×24367 by ~2×). The full run must grid-then-measure fill **inside the footprint polygon**, not the bbox.

---

## 4. Watch-cruise call — TN299

TN299 grids **near_nadir** at both HR (footprint fill 0.41 and 0.91) — **not** outer-beam grazing → **keep** on coverage. TN299×27339 still excludes on **ratio (80, deep + 1 m HR)**; ×31256 awaits Stage-D HR res. The A.6 coverage concern is **resolved/cleared**; any exclusion is a ratio matter (Stage E).

---

## 5. Processing-chain learnings (for the full-run directive)

- **`mbclean`+`mbprocess` is prohibitively slow on large cruises** — it hung the 377-file Amundsen ~3.5 h. The pilot **grids raw above a 100-file cap**; raw grids are sane (fill, depth, coverage). **Recommend grid-raw for the full run** unless a raw-vs-processed spot check on one cruise shows material differences; otherwise parallelize `mbclean` per-file and budget hours.
- **`.gz` must be decompressed first** (MB-System reads 0 records from gzip). Full run needs node-local space for the largest cruise's uncompressed swath (~60 GB / Amundsen).
- **Subset gridding validated:** the 2009_Amundsen *subset* (377/3,198 files) gridded coherent LR over the footprint (footprint fill 0.66, no hole) — A.5 subsetting is safe.
- **Measure inside the footprint polygon, not the bbox** (the correction in this report) — and the cell-estimate depth must be **footprint-local**, not the cruise-wide `mbinfo` median (which is biased by shallow transit lines).

---

## 6. Flags / open items

- **3 of 7 pairs unrankable until Stage D** (HR native res unknown: MGDS:30045, 24620, 31256). Two of these have native ~19–39 m (Amundsen 19.6 m at −554 m; TN31256 38.5 m) — at 1 m HR they'd be eval/exclude, at 2 m they could approach training. **Stage D is on the critical path to tiering.**
- **No `ok_finer_verify` HR in this pilot** — that ratio-provisionality flag wasn't exercised; the full run must carry it.
- The bbox→polygon fix changed one tier assignment; expect similar shifts across the full run, so the full run must measure on the polygon from the start.

---

## 7. Recommendation + HOLD

The chain works end-to-end and the corrected metrics are trustworthy. **HOLD for assessment** on:
1. **The ratio model (§2)** — confirm that training is selective (depth × HR-res × coverage) rather than margin-only, and that the Stage-D HR-res values gate tiering.
2. **Processing policy (§5)** — confirm grid-raw + polygon-fill measurement for the full run.
3. **TN299 keep (§4)** and the Stage-D dependency for the 3 nan-ratio pairs (§6).

No full Stage C run (the other ~31 cruises) until the next directive.

## Deliverables
1. 7 gridded LR + 7 QC overlays (real footprint polygon)
2. this report + `stage_c_pilot_measurements.json` (polygon + bbox fills)
3. `mbsystem_build_pin.txt`
4. staging_state update
