# Directive — Co-located corpus RE-AUDIT (reader correctness + combined manifest) v1

**Date:** 2026-06-26
**From:** Assessment instance · **To:** Claude Code (Sherlock)
**Supersedes:** `directive_phase2_stage_f_repair_review_v1.md` and `directive_phase2_read_path_bug_v1.md` (both retired into this).
**Status:** ⛔ HOLD all manifest/OAK writes, all exclusions, all Stage G. Append-only; the 21 validated remain read-only. This directive re-derives disposition for the whole corpus from a **proven** reader. Nothing prior is trusted as input.

---

## 0. Why we are re-auditing (read before anything)

Two distinct problems are now established:

1. **Stage F datum bug (real).** Unmasked HR open let `−9999` fill be sampled as elevation, producing garbage rigid `dz` added to every cell. Genuinely happened to a subset (the `−9999+dz` fill-leak). AT37-13×31199 and AT42-03×32007 recovered to correct LR-matching depths — treat this as a **real, separate phenomenon**.

2. **Assessment-reader bug (newly found, via Steve's QGIS).** The "+255 m clamp" verdict is **wrong**. Steve confirmed with the QGIS Value Tool that these grids hold **real, negative, realistic depths**; the renderer shows a true elevation range. Our assessment script manufactured `+255` (= 0xFF). Only `TN299×31256` is genuinely bad (an ingested figure/PDF, not bathymetry). The strong hypothesis: these HR GeoTIFFs are **multi-band** (band 1 = float elevation; an auxiliary band = valid-mask/alpha = 255), and the assessment read the **wrong band**; the `254.995–255.004` spread is a 255/0 mask smeared by the Stage F bilinear warp.

**The consequence that governs this re-audit:** the same reader produced `f5_stage_f_dz_m`, `f5_recoreg_dz_m`, `repair_dz_applied`, `hr_orig_p50_m`, and every disposition. **All of it is unproven until reproduced through a corrected reader.** The prior repair report was internally self-consistent and still wrong because it validated arithmetic against its own misread input. **Internal consistency is not evidence here. External ground truth (Steve's QGIS-verified pixels) is.**

**Target corpus:** combine the **21 validated** + the new set (≤31: 32 minus `TN299×31256`, minus any pair with genuinely zero real tiles). Final count is whatever the corrected reader yields — do not anchor to 9, and do not anchor to any prior number.

---

## 1. Governing principles for this pass

- **Prove the reader against Steve's eyes, not against itself.** No downstream number is computed until R0 passes.
- **Keep the two phenomena separate.** Do not assume every anomaly was the band bug. The fill-leak (AT37-13/AT42-03) is real; preserve that finding. A pair can have *both* a correct reader result *and* a real processing issue.
- **Per-statistic honesty over heterogeneous populations.** No global median over a mixed population (mask+data, or multi-sub-grid). This is the root pattern behind both bugs.
- **QC plots must expose the failures that bit us**, not flatter the data. A hillshade looks identical under an 8 km datum shift — design panels that don't.
- Append-only; 21 read-only; escalate, don't absorb.

---

## 2. Tasks

### R0 — Fix and PROVE the reader  ⛔ GATE (nothing past this until it passes)
1. `gdalinfo -stats` on a representative spread of new HR (incl. all five former "+255": `FK171110×24485`, `RC2511×32241`, `2009_Amundsen×30045`, `EW0207×32558`, plus `TN299×31256` as the known-bad control). Report **per band**: dtype, color interpretation, NoData, scale/offset, min/max/mean. Identify the **elevation band** explicitly and the band semantics.
2. Implement the corrected reader: select the elevation band by semantics (not positional assumption), `masked=True`, apply scale/offset if present, NoData→NaN.
3. **Proof of correctness (the gate):** on ≥3 pairs Steve verified good in the Value Tool, show side by side: **old reader → ~+255**, **new reader → real negative depths**, and new-reader p50/min/max **matching the QGIS renderer statistics** for those pairs. Show that `TN299×31256` is structurally different (RGB/byte / no elevation band) — a *positive discriminator* between "real grid we misread" and "actually a figure."
4. Do **not** proceed to R1+ until this table is produced and the new reader reproduces the QGIS-verified values.

### R1 — Re-derive disposition for all 32 (through the proven reader)
For every new pair: true HR p50, HR↔LR vertical offset = robust `median(HR−LR)` over **joint real cells only**, NCC/PSR co-reg, joint area/fraction, n_valid_tiles. Re-bucket. Expect most "+255" and several `coreg_fail` to return to advancing/eval. Genuine drops allowed only with a stated, reader-independent reason (e.g. `TN299` = figure; `RC2511×32240`/`TN268×24470` = zero real tiles). Produce a before/after disposition table (old flag → new flag → reason).

### R2 — Clip + multi-grid slicing audit (first-class test, per Steve's requirement)
- Enumerate **multi-grid sites** in the new set (one HR site = several disjoint AUV grids over one LR). Report how many sites, how many sub-grids each.
- **Ruling (assessment):** carry each HR sub-grid as **its own pair** against its own LR clip; sub-grids of a site **share one `leakage_unit`/`geo_cluster`**. Do **not** clip LR to the union for assessment, and never compute a single offset/dz across sub-grids.
- **Test the clip directly:** confirm LR is clipped to the **true HR valid footprint** (real-data polygon, not bbox) per sub-grid; confirm the tiler emits tiles only on `joint_valid` and **drops no sub-grid and blends none**. Show a worked example on a multi-grid site: tiles land inside each sub-grid, none in the gaps.

### R3 — QC plots (one figure per pair; multi-grid sites also get a site-level figure)
Each figure must contain:
1. HR hillshade and LR hillshade side by side (morphology / co-location).
2. HR and LR depth on a **shared color scale** (a datum offset shows as a color mismatch).
3. **HR−LR difference** over the joint footprint, diverging cmap centered at 0, median residual annotated (co-reg + datum in one panel — the one that would have caught Stage F).
4. **Overlaid value histograms**, sign-explicit, p1/p50/p99 marked (the one that would have caught +255).
5. **Footprint/clip panel:** LR extent with HR valid polygon(s) overlaid, each sub-grid outlined and labeled, joint-valid region shaded.
6. **Reader banner (text):** band index/semantics read, dtype, NoData, CRS, native res, joint_fraction, n_tiles, dz applied (if any), and `reader_proof: ✓` status.
Generate for **all** pairs (advancing + non-advancing), ordered disposition-then-tile-count, so Steve can adjudicate borderline pairs without opening QGIS. Write to `$DATA_ROOT/qc_plots/` and list paths in the report.

### R4 — Disentangle the genuine fill-leak from the band bug
Confirm, through the corrected reader, that AT37-13×31199 and AT42-03×32007 had a **real** `−9999+dz` fill-leak (not a band misread) and that the repaired HR sits at correct absolute depth matching LR. Report which pairs had (a) only a reader bug, (b) only a real fill-leak/datum issue, (c) both, (d) neither. This is the map that tells us what was ever actually wrong.

### R5 — Validated-21 spot-check through the corrected reader
For all 21 (read-only, OAK): `gdalinfo` band structure + corrected-reader p50 + out-of-bounds cell counts. Confirm none carry the multi-band misread and all sit at physically correct site depths. (Cheap insurance on the calibration anchor; the reader question is reopened, so the prior code-path argument is necessary but no longer sufficient.)

### R6 — Assemble the combined corpus (HOLD append for Steve)
Build the proposed **combined manifest = 21 validated + new advancing/eval** (per-sub-grid, shared leakage units, dedup vs the 21 and the 6 orphan `cal_dig` sub-dirs). Report the proposed pair list and counts. **Do not write to `manifest/pairs.parquet` or OAK** — present for Steve's sign-off via the QC plots.

---

## 3. Assessment rulings recorded here
- Multi-grid: **per-sub-grid pairs**, shared leakage unit, no union offset. (R2)
- The 21: **spot-check through corrected reader**, do not skip. (R5)
- `TN299×31256`: **excluded** (confirmed figure), used as the reader's negative control. (R0)

## 4. Frozen / unchanged
No manifest writes, no OAK writes, no Stage G, no exclusions executed, 21 read-only, pre-repair `hr_preF5repair.tif` retained.

## 5. Deliverables
1. R0 reader-proof table (old vs new vs QGIS-verified) — the gate.
2. Re-derived disposition table for all 32 (old→new→reason).
3. Multi-grid enumeration + clip/tiler worked example.
4. QC figures for all pairs + multi-grid site figures, paths listed.
5. Fill-leak vs band-bug map (R4).
6. Validated-21 spot-check table (R5).
7. Proposed combined manifest (counts + pair list), held for sign-off.
8. This stage's dated report (append-only) + updated `combined_corpus.csv` with corrected columns and a note that prior `+255`/`raw_datum_broken` flags are retracted.

---

**On skepticism (for the next report):** the failure mode here was a self-consistent verdict on a misread input. Do not hand back another internally-consistent table. Anchor every key number to something external — Steve's QGIS values, the renderer's statistics, physically expected site depths — and show that anchor in the report.
