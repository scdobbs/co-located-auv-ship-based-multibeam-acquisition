# Phase 2 — Stage C full gridding run report

**Date:** 2026-06-23 · **Author:** Claude Code execution instance (Sherlock)
**Directive:** `reports/directive_phase2_stage_c_full_gridding.md`
**Status:** ⛔ **HOLD for assessment** before Stage E (re-tier) / Stage F (harmonize). LR native res is definitive; **provisional ratios are informational only** — no tiering done here.

**Artifacts**
- Gridded LR + QC overlays (real footprint polygon): `$DATA_ROOT/raw_lr_gridded/` (43 union grids + 50 overlays incl. pilot)
- `reports/discovery/stage_c_full_measurements.json` (per-pair, polygon-masked; native-res method per pair)
- `reports/discovery/stage_c_processing_policy.md` (C-full-0 spot check)
- Code: `src/discovery/stage_c_full.py`; sbatch `stage_c_array` / `stage_c_refix`

---

## 1. Headline

| | |
|---|---|
| Cruises gridded | **33** (the remaining swath-complete set) |
| Pairs (cruise × HR) | **45** → **43 gridded, 2 failed** |
| **Provisional bands** (informational) | **exclude(>40): 34 · eval(25–40): 4 · train(5–25): 2 · sub-5: 3** |
| Coverage | 41 near_nadir · 2 outer_beam_grazing |
| QC | 39 pass · 6 reject (fill < 0.3 or implausible) |
| LR native res | 1.9–317 m (median **71 m**) |

**The pilot's signal holds at scale: real co-located *training* pairs are rare.** 34 of 43 gridded pairs exclude on ratio — deep abyssal ship-MBES (70–300 m) against 1–2 m AUV HR. Only **2 training-band pairs** in the full run (plus 1 in the pilot). This is the central Stage-C finding for the project: the deep majority of the corpus is eval/excluded; training pairs need the shallow-or-coarse-HR combination. **The exact count is not final until Stage D supplies authoritative HR res and Stage E tiers.**

---

## 2. Processing policy (C-full-0) — grid raw

Spot check on FK006B (194 files, EM302/EM710): `mbclean`+`mbprocess` changed the gridded LR by **0.0 %** (max Δ 0.0 m, identical fill) while running **4.5× slower** (26 vs 6 min). At LR cell sizes the Gaussian-weighted `mbgrid` averages out per-sounding outliers. **Decision: grid raw** (both directive fallback conditions met). Detail in `stage_c_processing_policy.md`. Legacy/noisy cruises flagged for visual QC.

---

## 3. Per-pair results (summary)

Full table in `stage_c_full_measurements.json`. Method split: **27 pairs** used the `cell/√fill` proxy; **16 pairs** (near a tier edge) used the **true sounding-density** derivation (`mblist`), which materially corrects over-posted grids — e.g. RB1604 proxy ~29 m → sounding-density **101 m** (sparse footprint coverage → exclude, not eval).

**Training-band pairs (provisional, 5–25×):**
- `AT42-06 × MGDS:5174` — ratio **8.9** (HR ~5 m ABE; LR 44 m; fill 0.98). Clean train candidate.
- `MV1209 × MGDS:21415` — ratio **9.7**, **but** fill **0.24** (qc reject) **and** `ok_finer_verify` HR → **double-flagged** (see §5). Not a safe train pair as-is.

(With the pilot's `FK181031 × 24367` (22.4), that's 3 training-band pairs found so far — all needing Stage-D confirmation.)

---

## 4. Failures + candidate excludes (escalate, not executed)

**2 gridding failures:**
- `AT18-11` — good data (~−122.9°) but its HR footprints (−120.6 to −118.6°, a suspiciously **2°-wide** AUV footprint) don't overlap the ship coverage → **likely false pair** (bbox overlap, no real LR over the footprint). The whole-cruise fetch had no nav-subset filter to catch this. Recommend exclude + re-examine the inflated 21462/21454 footprints.
- `TN234` — EM300 vendor files read **0 good beams** (`mblist` empty) → **LR has no usable bathymetry**. Recommend exclude.

**34 candidate excludes** (ratio > 40 or outer-beam grazing) — safe to exclude now regardless of HR res (raw cell already coarse). **2 outer_beam_grazing** + **4 fill < 0.3** flagged for visual QC.

---

## 5. Skeptical sanity sweep (C-full-3) — flags a per-pair check would miss

- **3 `2010_Amundsen` pairs have implausible native res (~2 m, ratio < 1).** Their footprints sit on shallow Arctic shelf (~150 m), so the footprint-size cell estimate (1.85 m) is *finer than the real ship sounding spacing*; the `cell/√fill` proxy then over-reports resolution. Ratio < 1 (LR finer than AUV HR) is physically impossible. **Flagged `native_res_suspect`; they exclude regardless (<5×).** *Process lesson:* the sounding-density derivation should run for **all** shallow pairs (where the cell estimate is very fine), not only near tier edges — recommend that for any re-grid.
- **`MV1209 × 21415` is the contamination-risk pair:** train-band ratio (9.7) but fill 0.24 and `ok_finer_verify` HR. A Stage-D *coarsening* of its HR res would only raise the ratio (out of training) — safe direction — but the poor fill makes it a weak pair regardless.
- **Corrupt footprints fixed:** 3 HR (MGDS:5174, 21998, 7833) had mixed-CRS geometry in the A.6 gpkg (projected coords leaked into the 4326 layer); the driver now falls back to the verified-clean HR-catalog geometry. **`stage_a6_hr_footprints` should be repaired at source before Stage F.** (7833 belongs to a legacy-excluded cruise.)

---

## 6. Carry-forward to Stage D / E — the contamination asymmetry

The dangerous error is **over-coarse HR** (HR res too large → ratio understated → a pair wrongly enters training). So:
- **Stage D must justify any HR res coarser than its grid posting** with sounding-density/spectral evidence; any pair that moves **into** training on a Stage-D coarsening gets extra scrutiny.
- Over-fine HR only over-excludes (safe) — e.g. the `ok_finer_verify` pairs and 31256's over-posted 0.2 m.
- **`hr_res` here = the A.6-measured grid cell** (`hr_resolution_sanity.csv`), an informational triage value — **not** authoritative. Stage D's sounding-density HR res governs tiering.

---

## 7. Recommendation + HOLD

The chain ran at scale; LR native res is in hand for 43 pairs. **HOLD for assessment** on:
1. The **rarity of training pairs** (§1) — confirm the implication for the SR validation set size.
2. **Failures/excludes** (§4): exclude AT18-11 (false pair) + TN234 (no soundings); rule on the 34 ratio-excludes and the grazing/low-fill pairs.
3. **Sanity flags** (§5): the 3 suspect-overfine Amundsen pairs; repair the 3 corrupt A.6 footprints at source; the MV1209×21415 double-flag.
4. **Stage D** is on the critical path to real tiering (Stage E).

No re-tier, harmonization, or manifest/OAK writes until the next directives.

## Deliverables
1. 43 gridded LR + QC overlays (`$DATA_ROOT/raw_lr_gridded/`)
2. this report + `stage_c_full_measurements.json`
3. `stage_c_processing_policy.md` (C-full-0)
4. updated `staging_state`
