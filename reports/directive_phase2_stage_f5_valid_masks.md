# Directive — Phase 2 Stage F.5 (rev 1): nodata-aware valid masks + training-sampling guarantee

**Date:** 2026-06-23 · **For:** Phase 2 Claude Code execution instance · **After:** Stage F · **Before:** Stage G manifest append.

**Rev 1** folds in Code's pipeline trace, which confirmed the delivered pairs *are* guarded at the polygon level (`_valid_polygon` polygonizes non-NaN and clips to the intersection; `coregister._residuals` and `qa.compute` already filter finite-in-both) and located the two real gaps. This revision adopts Code's two proposed changes (cell-wise joint mask + joint-valid-fraction column) **with one correction**: the joint mask must be defined on **real measured data, not merely `isfinite`** — see F5-1. The 32 new pairs only; the 21 validated are untouchable.

---

## Why `isfinite ∧ isfinite` is not enough (the correction)

Code's proposed joint mask `finite(hr) & finite(lr)` closes the **sub-polygon sliver** problem (one-sided NaN within the overlap) — necessary and good. But it does **not** close Gap 1, the inflated footprints, because **interpolated AUV fill is finite, not NaN.** `_valid_polygon` already polygonizes non-NaN, so a `finite ∧ finite` mask would still pass the 36,000 km² of interpolated-fill-against-LR. The fill is real-valued; it just has no sounding behind it.

So the joint mask must be **`hr_real_data ∧ lr_real_sounding`**:
- **LR real** = the **Stage C real-sounding fill mask** (not `isfinite(lr)`) — this is the layer that already distinguishes real soundings from `mbgrid` interpolation.
- **HR real** = exclude interpolated cells. `_hr_mosaic` (stage_f_harmonize.py:75-76) already drops whole tiles named `diff/interp/Int`; extend to cell level where a count/density/interp layer exists. Where the HR product carries **no** cell-level interp flag, mark `hr_interp_status=unknown` and rely on the area-plausibility gate (F5-2) to catch inflation.

`finite ∧ finite` fixes slivers; `real ∧ real` fixes the inflated pairs. **Both are required.**

---

## Guardrails

- **32 new pairs only.** The 21 validated are read-only.
- **Real-data-aware, not just NaN-aware.** Interpolated-but-finite cells are not valid data.
- **Reuse the Stage C fill mask** as the LR real layer; confirm it warps correctly onto the harmonized grid.
- **Conservative mask warp** — never bilinear a mask. Majority/threshold resample, and **erode one cell** at validity edges so fill never bleeds into the valid region.
- **QGIS visual QC is the arbiter.** Append-only; **no manifest/OAK writes** (Stage G). Doesn't touch the 21.
- **Escalate** pairs whose true valid overlap collapses — exclusion candidates, not silent passes.

---

## F5-1 — per-pixel real-data masks (the core artifact; Code change (a), corrected)

Per pair, on the common UTM grid, write as shared mask bands/sidecars alongside `hr.tif`/`lr.tif`:
- **`hr_valid`** = HR real data (exclude NaN; exclude flagged interpolation/diff cells; `hr_interp_status` recorded where cell-level interp can't be determined).
- **`lr_valid`** = Stage C real-sounding fill mask, conservatively warped.
- **`joint_valid`** = `hr_valid ∧ lr_valid` — written as **one shared cell-wise mask** both rasters reference (Code's (a)). This is the only set of cells with both real input and real target.

## F5-2 — true valid-overlap, two quantitative gates, re-clip (Code change (b))

Add to the Stage F results, per pair (Code's (b), quantitative not eyeballed):
- **`joint_valid_area_km2`** = `joint_valid` cell count × cell area.
- **`joint_valid_fraction`** = `joint_valid` / overlap-polygon cells.

Two distinct gates:
- **Area-plausibility gate (catches the inflated 7):** a co-located AUV overlap is km²-scale. `joint_valid_area_km2` above a confirmable plausibility bound (e.g. ≫ a few hundred km²) ⇒ HR is interp-inflated ⇒ **re-clip to the real AUV data core, or exclude** if no genuine real-data overlap exists. This is the §3a fix done by number, not by eyeballing overlap km². (`2009_Amundsen×30045` re-clips to its LR-covered tiles — not excluded.)
- **Coverage-fraction gate (catches slivers / one-sided tiles):** low `joint_valid_fraction` ⇒ overlap is mostly one-sided ⇒ weak pair, flag.

Re-clip each product tight to the `joint_valid` extent.

## F5-3 — re-co-registration + re-QA on real-data cells

`coregister._residuals` and `qa.compute` already restrict to finite-in-both — but **re-run them on the `joint_valid` (real-data) mask**, not just `isfinite`, so §3b's bad locks (`KN210-05×22436` 145 m, `FK006B×20811` PSR −0.97, `FK171110×24485` PSR −18) are judged on real soundings, not interpolated fill. Verdict per pair: `clean` / `rescued` (locks once fill excluded) / `genuine_coreg_fail` (still poor → scrutinize/exclude).

## F5-4 — the training-sampling guarantee

- Emit **`valid_tiles.parquet`**: per pair, tiles whose `joint_valid` fraction ≥ a sampling threshold, fraction recorded — the **authoritative trainable-tile index the loader must use** (Code's "clean place to enforce it corpus-wide"). Invalid tiles never enter it.
- **Sampling rule** (threshold flagged as a modeling parameter to confirm): include a tile if `joint_valid` fraction ≥ ~50 %; within a tile, compute SR loss **only on `hr_valid` pixels** (per-pixel masked loss) and feed LR with a validity channel. Pixel-level masks (F5-1) make masked-loss possible; tile-level index gates selection.
- After this stage every Stage-G-bound pair carries a shared `joint_valid` mask + a valid-tile entry, so the loader cannot sample HR-or-LR fill.

## F5-5 — Gap 2: re-confirm the eval-only demotions on a joint-masked window

Code found the C.5 spectral `_prep` fills NaN→0 with no joint mask. Impact is asymmetric and **bounded**:
- **The k=8 decision is HR-only PSD (slope/recoverability) → unaffected.** Do **not** re-run the full sweep.
- **The coherence / circular-leak numbers can be biased** by 0-fill where one grid has data. The 6 leak-flagged pairs were cleared on **provenance** (per-cruise raw, no composites) — provenance is unaffected by 0-fill, so that **keep verdict stands**.
- **But** the 2 `eval_only` demotions (`NA090×31212`, `TN159×21981`) leaned on the SR-signal-magnitude check. **Re-confirm just those 2** on a `joint_valid`-masked spectral window. If they still read HR≈LR → demotion stands; if the masking changes the picture → re-flag. Scope: 2 pairs, not the corpus.

## F5-6 — completeness, report, HOLD

- Accounting: 32 == `clean` + `rescued` + `genuine_coreg_fail` + `weak/inflated_exclude_candidate`, no limbo.
- Write `stage_f5_valid_masks_2026-06-23.md`: per-pair `joint_valid_area_km2`, `joint_valid_fraction`, re-coreg verdict, mask-written confirmation, valid-tile counts, the area/fraction-gated exclusion candidates, and the 2-pair Gap-2 re-check result.
- **HOLD for QGIS review + assessment** of exclusion candidates and rescued locks before Stage G. Only pairs with real valid overlap, a clean/rescued lock, and a written `joint_valid` mask advance.

---

## Deliverables

1. per-pair `hr_valid`/`lr_valid`/shared `joint_valid` masks in `$DATA_ROOT/harmonized/<pair>/`
2. `valid_tiles.parquet` (loader's authoritative trainable-tile index) + sampling rule
3. updated `combined_corpus.csv` / Stage F results (`joint_valid_area_km2`, `joint_valid_fraction`, re-coreg verdict)
4. `stage_f5_valid_masks_2026-06-23.md` (incl. the 2-pair Gap-2 re-check)
5. updated `staging_state`

## Out of scope

Manifest/OAK append (Stage G); model training; re-processing the 21; regenerating the training repo's `hr_tiles.parquet` (consumes `valid_tiles.parquet` on the training side); re-running the full C.5 spectral sweep (only the 2-pair re-check). Discovery footprint-bbox gate (next harvest) and the 6 orphan `cal_dig` sub-dirs (before Stage G) remain tracked.
