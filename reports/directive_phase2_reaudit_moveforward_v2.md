# Directive — RE-AUDIT move-forward: RGB discard confirmed, R2/R3/R6 released v2

**Date:** 2026-06-26
**From:** Assessment instance · **To:** Claude Code (Sherlock)
**Builds on:** `directive_phase2_colocated_reaudit_v1.md` (R0–R5 accepted). This releases the HOLD on R2/R3/R6 with scoping, and records the RGB decision + a recovery path.

---

## 0. Decisions recorded (Steve-confirmed)

- **The 9 RGB-`uint8` HR sources are visualization renders, not bathymetry — DISCARD as HR.** Confirmed by Steve's independent inspection. Principled basis: an 8-bit slope/hillshade render is a non-invertible, colormap-quantized transform of elevation; metric depth and meter-scale calibrated UQ cannot be recovered from it, even where morphology looks real. Disposition `exclude_no_elevation` stands as **reader-independent** and permanent for these files.
- **R0 reader proof accepted.** The 3-band-uint8 vs single-band-float discriminator is byte-level and robust; the advancing 9 were never touched by the reader bug; the validated 21 are clean single-band float (R5). The 23 real pairs' band-1 disposition stands because the bug was multi-band-specific.
- **Correction to the report's narrative (on the record):** the RGB→elevation transform does **not** produce a uniform flat plain — it recreates **structured morphology where data exist** (resembling the high-res imagery), flat only in nodata gaps, with absolute values off from LR. Steve was not misled by a flat artifact; he saw real-looking terrain with an invalid datum. This makes these renders *more* deceptive, not less — see §3.

---

## 1. Corpus standing after re-audit (honest)

- **21 validated** (clean) + **9 new advancing** (real elevation, depth-sane vs LR) = **30 confirmed**.
- **14 real non-advancing** → QGIS arbitration pool. Of these, **3 have 0 real tiles** (`RC2511×32240`, `TN268×24470`, `FK160407×7832`) → genuine drops regardless of arbitration. **11 real candidates** remain for Steve to adjudicate from the QC plots.
- **9 RGB** → discarded.
- **Realistic landing: 30 + whatever of the 11 survive QGIS ≈ low-to-mid 30s.** Do not anchor tighter until R3 plots are reviewed.

---

## 2. Released tasks

### R3 — QC plots for **all 23 real pairs** (FIRST; this is the adjudication material) ⛔ precedes R6 append
Generate one figure per real pair (9 advancing + 14 non-advancing), per the v1 R3 spec:
1. HR & LR hillshade side by side.
2. HR & LR depth on a **shared color scale**.
3. **HR−LR difference** over joint footprint, diverging cmap at 0, median residual annotated.
4. Overlaid value histograms, sign-explicit, p1/p50/p99 marked.
5. Footprint/clip panel: LR extent + HR valid polygon(s), each sub-grid outlined/labeled, joint-valid shaded.
6. Reader banner: source_type, band read, dtype, NoData, CRS, native res, joint_fraction, n_tiles, dz applied, `reader_proof ✓`.
Order: advancing first, then non-advancing by tile count. Write to `$DATA_ROOT/qc_plots/reaudit_real23/`, list paths. **Purpose: Steve adjudicates the 14 (esp. `MGLN06MV×17700`'s ~900 m offset, the eval pair `TN159×21981`) without opening QGIS.** Do not pre-exclude the 14 — present them.

### R2 — clip + multi-grid audit (per v1 ruling: per-sub-grid pairs, shared leakage_unit, no union offset)
Enumerate multi-grid sites among the **23 real** pairs; confirm LR clipped to true HR valid footprint per sub-grid; show a worked example proving the tiler emits tiles only on `joint_valid`, drops no sub-grid, blends none. **Note `FK181031`:** `×24367` (real, advancing) and `×24620` (RGB, excluded) are the same cruise but different products — keep them distinct, do not treat as sub-grids of one site.

### R6 — proposed combined manifest (BUILD, do not append) ⛔ HOLD append for Steve
Assemble proposed `manifest/pairs.parquet` = **21 validated + 9 advancing + QGIS-arbitrated survivors of the 11**. Per-sub-grid, shared leakage units, dedup vs the 21 and the 6 orphan `cal_dig` sub-dirs. Report the proposed pair list + counts. **No write to `pairs.parquet` or OAK** until Steve signs off from the R3 plots.

---

## 3. Carry-overs / recovery (new)

### C1 — RE-HARVEST the float sources for the discarded RGB sites (recovery, not loss) — HIGH VALUE
The 9 renders were derived **from real AUV float grids that likely still exist at source.** We harvested the wrong product. **Action (separate harvest task):** for each discarded RGB pair, query the source (MGDS / data provider) for the underlying **float** bathymetry product and re-stage if found. **Prioritize by diversity value:** the Axial Seamount pairs (`EW0207`, `EW9904`, `TN383` — mid-ocean-ridge volcanic) and `2009_Amundsen×30045` (the only Arctic shelf-slope pair, 586 m). The corpus is 74% continental margin; these are precisely the under-represented morphologies, so recovering their float sources is the strongest available lever against the corpus's known diversity limitation. Report what float sources exist before assuming permanent loss.

### C2 — Discovery filter (fix at source, like the bbox gate)
Add a harvest-time HR rejection: **3-band uint8 / `colorinterp ∈ {red,green,blue}` ⇒ reject as visualization render**, plus a Terrain-RGB decode plausibility check. These renders pass a visual/morphology look and a depth-*range* sanity check (they resemble real terrain), so the filter must be **byte-level**, not visual. Prevents rediscovery.

### C3 — Clean up the 8 fake-repaired `hr.tif` (low stakes, but don't leave traps)
The 8 category-(c) RGB pairs whose `hr.tif` was rewritten to a fake LR-aligned surface: mark `exclude_no_elevation` and **restore from `hr_preF5repair.tif`** (or clearly quarantine the fake `hr.tif`) so no downstream step can mistake a cosmetically-aligned render for HR. Append-only: retain backups, don't delete provenance.

### C4 — `FK160407×7832` positive-down `.grd` sign flip — note only; 0 tiles ⇒ genuine drop regardless. No effort.

---

## 4. Frozen / unchanged
21 read-only; no `pairs.parquet`/OAK write until Steve signs off the R3 plots; `hr_preF5repair.tif` retained.

## 5. Deliverables
1. R3 QC figures for all 23 real pairs (paths listed).
2. R2 multi-grid enumeration + clip/tiler worked example.
3. R6 proposed combined manifest (counts + pair list), held for sign-off.
4. C1 re-harvest scan: which discarded RGB sites have a retrievable float source.
5. Dated report (append-only); `combined_corpus.csv` already updated (RGB flags retracted, `exclude_no_elevation` applied).

**Skepticism note:** R3 is the verification that the 23 "real" classification holds *visually*, not just by dtype — it must run and be reviewed before any manifest append. Anchor the report to the plots and the LR depths, not to internal tables.
