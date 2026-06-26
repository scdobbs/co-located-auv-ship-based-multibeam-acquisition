# RE-AUDIT move-forward — R2 / R3 / R6 + carry-overs C1–C4

**Date:** 2026-06-26 · **Directive:** `reports/directive_phase2_reaudit_moveforward_v2.md`
**Builds on:** `stage_reaudit_report_2026-06-26.md` (R0–R5, accepted).
**Status:** ⛔ **HOLD manifest append for Steve.** Proposed manifest BUILT (non-canonical), QC plots generated, recovery scan done. No write to `manifest/pairs.parquet` or OAK; 21 read-only.

**Code:** `src/discovery/stage_reaudit_{r3,r2r6}.py`, `hr_format_gate.py` (+ wired into `stage_c5_sweep.staged_hr_raster` & `stage_f_harmonize._hr_mosaic`).
**Artifacts:**
- R3 figures: `$DATA_ROOT/qc_plots/reaudit_real23/*.png` (23) + `R2_worked_example_TN268_tiler.png`; index `reports/discovery/stage_reaudit_r3_figures.json`
- R2: `reports/discovery/stage_reaudit_r2_multigrid.json`
- R6: `reports/discovery/proposed_combined_manifest.{csv,parquet}` (NON-canonical)
- C1: `reports/discovery/stage_reaudit_c1_float_recovery.{json,csv}`

---

## R3 — QC figures for all 23 real pairs (the adjudication material)

One 6-panel figure per real pair (9 advancing + 14 non-advancing), ordered advancing-then-tilecount. Each has: HR/LR hillshade, HR/LR depth on a **shared color scale**, HR−LR diff (diverging@0, median annotated), overlaid sign-explicit histograms (p1/p50/p99), a footprint/clip composite (HR-blue / LR-orange / joint-green), and a reader banner (`source_type`, dtype, NoData, CRS, joint_fraction, n_tiles, dz, reader_proof).

Verified the figures expose the failures that motivated this:
- **Advancing pairs read true:** e.g. `AT37-13` — HR and LR hillshades show the same canyon morphology, depths overlap (~−1.6 km), diff ≈ 0. The dtype "real" classification holds **visually**, not just by byte structure.
- **The flagged offset is obvious:** `MGLN06MV×17700` — on the shared scale HR sits ~−2600 m vs LR ~−1700 m (clear color mismatch), two separated histogram peaks, ~−900 m median diff. Steve can adjudicate this (and `TN159×21981`, etc.) from the plot without QGIS.

**For Steve's adjudication of the 14:** 3 have 0 valid tiles (`RC2511×32240`, `TN268×24470`, `FK160407×7832`) → drop regardless. The other **11** are the live candidates; their figures are in the folder, named `real_nonadvancing_qgis__*.png`.

---

## R2 — multi-grid clip + tiler audit

**Multi-grid sites among the 23 real pairs:** `SKQ201705S` (2 sub-grids: ×31254, ×31255) and `TN268` (3 sub-grids: ×30219, ×30466, ×24470). Confirmed against the v1 ruling:
- **Per-sub-grid pairs:** each sub-grid is its own `pair_id` with its own `hr.tif`, `joint_valid.tif`, and tile rows. ✅
- **Shared single leakage_unit:** SKQ → lu 27, TN268 → lu 22 (one unit per site). ✅
- **No union offset:** each sub-grid carries its own co-registration (per-pair dz). ✅
- **Clip = true HR valid footprint per sub-grid:** `joint_valid = hr_real ∧ lr_real` per pair (F.5), not bbox. ✅
- **Tiler emits only on joint_valid:** all 14,795 tiles have `joint_valid_fraction ≥ 0.50` (min = 0.50). ✅ No blending (tiles carry per-pair CRS coords in separate grids). Zero-tile sub-grids (`TN268×24470`) are correctly absent — genuine no-overlap, not an erroneous drop.

**Worked example** (`R2_worked_example_TN268_tiler.png`): `TN268×30466`'s 825 tiles overlaid on its `joint_valid` mask — every tile sits inside the green valid region, none in gaps.

**Per directive note:** `FK181031×24367` (real, advancing) and `FK181031×24620` (RGB, excluded) are the **same cruise, different products** — kept distinct, not treated as sub-grids of one site. ✅

---

## R6 — proposed combined manifest (BUILT, append HELD)

`reports/discovery/proposed_combined_manifest.csv` (canonical 21-pair schema):

| group | n | verification_status |
|---|---:|---|
| validated (the 21) | 21 | `verified_validated_21` |
| new advancing (real, depth-sane) | 9 | `advancing` |
| QGIS candidates (11 of 14; 3 zero-tile dropped) | 11 | `pending_qgis_arbitration` |
| **proposed total** | **41** | (30 confirmed + 11 provisional) |

Per-sub-grid; shared leakage units carried; deduped on `pair_id` (no spatial dups vs the 21; the 6 orphan `cal_dig` sub-dirs are not among the new pairs). **`manifest/pairs.parquet` and OAK were NOT touched.** Final corpus = 30 + whatever of the 11 survive Steve's R3 review (realistic low-to-mid 30s, as the directive framed).

---

## Carry-overs

### C1 — float-source re-harvest scan: **9/9 RGB sites have a retrievable float grid** (recovery, not loss)
MGDS tags all 9 discarded products `general_type = "Image Geo"` (their titles say "GeoTIFF **images**", "slope-shaded", "color ramps of Figure 2"). The cached MGDS AUV-bathymetry catalog (179 datasets; 93 `Grid`) contains a **float-grid companion** (netCDF / ESRI-ASCII) for every one — map in `stage_reaudit_c1_float_recovery.csv`:

| RGB pair | site (diversity) | float-grid uid(s) | status |
|---|---|---|---|
| EW0207, EW9904, TN383 | **Axial Seamount (MOR volcanic — under-represented)** | 32556 netCDF (`10.60521/332556`), 32557 ASCII, 30218 | **NEW, high priority** |
| 2009_Amundsen | **Beaufort Sea (only Arctic pair)** | 31753 netCDF (`10.60521/331753`), 30046 | **NEW, top priority** |
| NA076 | Santa Monica Mound | 32319, 32317 | NEW |
| FK181031×24620 | Pescadero Basin | 24618 netCDF, 24619 ASCII | NEW |
| FK171110×24485 | Tonga | 24499 | float **already in corpus** (as `KIWI10RR×24499`) |
| RC2511×32241 | MAR (EMARK) | 32240 | float **already in corpus** (`RC2511×32240`, 0 tiles) |
| TN299×31256 | Cascadia Pythia (confirmed figure) | 31253 netCDF; 31254/31255 | 31254/31255 **already in corpus** (as `SKQ`); 31253 new |

**Recommendation:** a separate harvest task should pull the Grid-type uids (prioritize Axial 32556/32557 and Amundsen 31753/30046 — exactly the under-represented MOR-volcanic and Arctic morphologies). **Note a labeling discrepancy surfaced:** corpus cruise labels `KIWI10RR×24499` (=FK171110 grid) and `SKQ×31254/31255` (=AT42-17/Cascadia Pythia grids) are MGDS mislabels — the float data is real and present, but the cruise names are wrong; worth correcting before manifest finalize.

### C2 — byte-level RGB-render rejection added (prevents rediscovery)
New `src/discovery/hr_format_gate.py`: `is_rgb_visualization()` (3-band uint8 / `colorinterp ∈ {red,green,blue}` ⇒ render), `is_float_elevation()`, `pick_elevation_tile()`. Wired into `staged_hr_raster` (now prefers a float-elevation tile, skips RGB — which also **fixes the original selection bug** for any future pair that has both a render and a grid) and `_hr_mosaic` (drops RGB tiles). Tested: RGB tile → rejected; `.grd`/`_elv_` float → accepted; EW0207 (all-RGB) → `pick_elevation_tile` returns None; SKQ → picks the `_elv_` float. **Cheaper metadata signal also available:** MGDS `general_type == "Image Geo"` flags these at catalog time — recommend adding that to the harvest filter too.

### C3 — 8 fake-repaired RGB `hr.tif` quarantined + restored ✅
The 8 category-(c) files whose `hr.tif` I had rewritten to a fake LR-aligned surface: the fake is preserved as `hr_FAKErepair_quarantine.tif` and `hr.tif` restored from `hr_preF5repair.tif`. Backups retained (append-only). All 8 are `exclude_no_elevation`, so no downstream step can mistake a cosmetic render for HR.

### C4 — `FK160407×7832` positive-down `.grd` (sign flip); 0 tiles ⇒ genuine drop. Noted, no effort.

---

## Deliverables
1. R3 QC figures (23) + worked example — paths in `stage_reaudit_r3_figures.json`. ✅
2. R2 multi-grid enumeration + clip/tiler worked example. ✅
3. R6 proposed combined manifest (41: 21+9+11) — held for sign-off. ✅
4. C1 float-recovery scan (9/9 retrievable). ✅
5. C2 discovery filter (code). ✅  C3 cleanup ✅.  C4 noted.
6. This report; `combined_corpus.csv` carries the reaudit columns (RGB flags retracted).

## HOLD — for Steve
1. **Review the 11 `real_nonadvancing_qgis` R3 figures** → decide which advance (esp. `MGLN06MV` ~900 m offset, eval `TN159`).
2. **Approve the proposed manifest** (then I append to `pairs.parquet` + sync OAK — not before).
3. **Greenlight the C1 float re-harvest** (Axial + Amundsen first) — the strongest available lever on the corpus's margin-heavy diversity gap.
4. Optional: correct the `KIWI10RR`/`SKQ` cruise mislabels before finalize.

**Skepticism note:** R3 is anchored to the plots (shared-scale depth + diff + histogram, not an internal table) and the LR depths; C1 is anchored to the MGDS catalog's own `general_type` and the existence of named netCDF/ASCII grid datasets with DOIs. The "real 23" classification now holds both byte-level (dtype) and visually (R3).
