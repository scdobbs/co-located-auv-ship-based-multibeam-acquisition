# Phase 2 — Stage F.5: real-data valid masks + training-sampling guarantee

**Date:** 2026-06-23 · **Author:** Claude Code execution instance (Sherlock)
**Directive:** `reports/directive_phase2_stage_f5_valid_masks.md` (rev 1)
**Status:** ⛔ **HOLD for assessment.** Two things to review before Stage G: (1) the
exclusion candidates + coreg-fail pairs (as directed), and (2) a **newly discovered
Stage F bug** — leaked nodata fill + corrupted HR vertical datum on 15–22 of the 32
pairs — that must be repaired before any pair (even the "clean" ones) advances.

**Artifacts**
- Per-pair masks: `$DATA_ROOT/harmonized/<pair>/{hr_valid,lr_valid,joint_valid}.tif` (uint8, aligned to `hr.tif`)
- `reports/discovery/valid_tiles.parquet` — the authoritative trainable-tile index (14,795 tiles / 29 pairs)
- `reports/discovery/stage_f5_results.json`; updated `reports/combined_corpus.csv` (`f5_*` columns)
- F5 re-coreg overlays: `$DATA_ROOT/harmonized/<pair>/qc/<pair>_overlay_f5.png`
- Code: `src/discovery/stage_f5_valid_masks.py`, `src/discovery/stage_f5_finalize.py`

---

## 0. The correction the directive asked for (real ∧ real, not finite ∧ finite)

The directive's key point: a `finite(hr) & finite(lr)` joint mask closes the
sub-polygon-sliver gap but **not** the inflated-footprint gap, because interpolated
fill is finite, not NaN. Implemented as `hr_real ∧ lr_real`:

- **LR real layer:** Stage C gridded the ship LR with `mbgrid … -C0` (**no gap
  interpolation**, `stage_c_full.py:189`) and Stage C's own `fill_fraction` is
  `np.isfinite` on that grid (`stage_c_full.py:211`). So `isfinite(union.grd)` **is**
  the Stage C real-sounding mask — there is no interpolated fill to strip. It is
  warped onto the HR grid by **area-resample → 0.5 majority threshold → erode 1 cell**
  (never bilinear a mask), so ship fill cannot bleed into the valid region.
- **HR real layer:** `_hr_mosaic` already drops tiles named `diff/interp/Int`; AUV
  GeoTIFFs carry no cell-level interp flag, so `hr_interp_status = tile_filtered_only`
  and the **area-plausibility gate** is what catches an interp-inflated HR.
- **`joint_valid = hr_real ∧ lr_real`** — one shared uint8 mask both rasters reference.

---

## 1. Headline buckets (F5-6 accounting: 32 == 9 + 14 + 3 + 6, no limbo)

| bucket | n | meaning |
|---|---:|---|
| `clean` | **9** | horizontal lock good on real cells (offset ≤ 30 m USBL, PSR > 0) |
| `genuine_coreg_fail` | **14** | offset > 30 m or PSR ≤ 0 on real cells → QGIS scrutinize / likely exclude |
| `inflated_exclude_candidate` | **3** | real joint area ≫ plausibility bound (interp-inflated HR / huge LR transit) |
| `weak_exclude_candidate` | **6** | real co-coverage fraction < 0.20 → overlap mostly one-sided |

Lock quality is judged on the **horizontal** §3b criteria (offset within the AUV USBL
bound + a positive NCC peak). The vertical residual MAD is **recorded but not gated**:
on a sloping margin a single rigid `dz` cannot remove the regional depth trend, so MAD
is trend-dominated (hundreds of m) even for a perfect horizontal lock.

**Trainable-tile index:** 14,795 tiles (256 px, joint-valid fraction ≥ 0.50) across 29
pairs; the 3 zero-tile pairs are exclude candidates. This parquet is the index the
loader **must** use — invalid/one-sided/fill tiles never enter it. (Down from a
fill-contaminated 17,192 before the §3 fix — i.e. ~2,400 tiles were fill artifacts.)

---

## 2. F5-2 — the two gates worked exactly as intended

The gates caught Stage F's §3a inflated-footprint pairs **by number, on real data**:

| pair | Stage F overlap km² | F5 real joint km² | frac | tiles | caught by |
|---|---:|---:|---:|---:|---|
| RC2511×32240 | 36,433 | 69.1 | **0.012** | 0 | fraction |
| TN268×24470 | 28,708 | 0.34 | **0.002** | 0 | fraction |
| FK160407×7832 | 11,980 | 6.2 | **0.001** | 0 | fraction |
| EW0207×32558 | 1,034 | **783.8** | 0.76 | 8,248 | area (>300) |
| KN210-05×22436 | 1,181 | 84.4 | **0.075** | 4 | fraction |
| EW9904×30217 | 535 | **494.1** | 0.93 | 106 | area |
| TN268×30219 | 535 | **398.1** | 0.76 | 84 | area |

The two gates are **complementary**: an interp-inflated HR or a long LR transit trips
the **area** gate even at high fraction (EW0207/EW9904/TN268×30219); a small real patch
swimming in a huge one-sided "overlap" trips the **fraction** gate (the rest). The
fraction denominator is the real-data union `|hr_valid ∪ lr_valid|` — a bounded [0,1]
one-sidedness measure (the directive's "overlap-polygon cells" intent made robust; the
literal rasterized polygon edge-mismatches the mask and can exceed 1). The literal
`joint/polygon` ratio is retained as a reference column.

---

## 3. ⚠️ DISCOVERED Stage F bug — leaked nodata fill + corrupted HR vertical datum

While building the masks, F5 uncovered a **Stage F co-registration bug** that affects
the stored `hr.tif` of most new pairs. **This is the most important finding in this stage.**

**Root cause.** Stage F's coreg step (`stage_f_harmonize.py:162-168`) opened HR with
`rioxarray.open_rasterio(hr.tif)` **without `masked=True`**, so the `-9999` fill cells
were read as ordinary values. `estimate_rigid_xyz` then sampled fill-vs-real and
real-vs-fill pairs, producing a **garbage `dz`** (e.g. +7930 m). `apply_xyz` added that
`dz` to **every** cell and re-wrote `hr.tif`, with two consequences:

1. **Leaked fill:** fill moved from `-9999` to `-9999 + dz` while the GeoTIFF nodata tag
   stayed `-9999`. `read(masked=True)` no longer masks it, so the fill leaks into every
   `isfinite`-based mask/metric (this is what produced the 401 m "SR-band RMS" in the
   first Gap-2 attempt, and inflated joint areas like KN210-05's 1,124 → 84 km²).
2. **Corrupted HR vertical datum:** the real seafloor values were shifted by the garbage
   `dz`. Verified directly — AT37-13's HR now ranges +3930…+6465 m (real margin depths
   shifted up by +7930) with fill parked at −2068.78 = −9999 + 7930.

**Scope.** **22 / 32** pairs have leaked fill; **15 / 32** have `|Stage F dz| > 50 m`
(HR vertical datum suspect), several enormous:

| pair | Stage F dz (m) | F5 re-coreg dz (m) | fill cells | F5 bucket |
|---|---:|---:|---:|---|
| NA076×32321 | −10,047 | +9,132 | 0.33 M | coreg_fail |
| AT42-03×32007 | +8,493 | −8,499 | 7.9 M | **clean** |
| AR26×31838 | +8,055 | −8,062 | 3.0 M | coreg_fail |
| AT37-13×31199 | +7,930 | −7,937 | 4.3 M | **clean** |
| TN159×21981 | +7,654 | −7,655 | 4.0 M | coreg_fail |
| KN210-05×22436 | +6,530 | −6,548 | 6.4 M | weak |
| … (15 total) | | | | |

**The F5 re-coreg `dz` ≈ −(Stage F `dz`) for every large case** — i.e. the clean,
properly-masked re-coregistration recovers the inverse of the garbage shift (plus the
true few-metre offset). **So the F5 re-coreg `dz` IS the repair value.**

### What F5 did about it
- **Masks are correct:** `_hr_real_valid` detects the leaked fill exactly
  (`value == −9999 + Stage F dz`, plus untouched −9999 and NaN) and excludes it, so
  `hr_valid`/`joint_valid`/`valid_tiles` are clean despite the corrupted `hr.tif`.
- **Did NOT silently mutate `hr.tif`** (append-only; this is a Stage F repair, not an
  F5 re-harmonization). Flagged per pair: `f5_stage_f_dz_m`, `f5_hr_vertical_suspect`,
  `f5_fill_corruption_cells` in `combined_corpus.csv`.

### Required before Stage G (escalation)
The masks make the geometry training-safe, but the **HR pixel values** of the 15
vertical-suspect pairs are off by thousands of metres. A **targeted Stage F repair** is
needed (not a full re-harmonize): for each affected pair, re-clean fill → NaN and
re-write `hr.tif` with a **properly masked** co-registration (open HR `masked=True`).
The F5 re-coreg `dz` already provides the correction. **Note this includes 2 of the 9
"clean" pairs (AT37-13, AT42-03)** — clean *horizontally*, but not advanceable until the
vertical datum is repaired.

---

## 4. F5-3 — re-coreg verdicts on real cells

The 9 `clean` pairs lock within the USBL bound on real data (offset 2.7–16.7 m,
PSR 3.5–17.5). The 14 `genuine_coreg_fail` split into:
- **offset > 30 m** (most: FK181031×24620 59.7 m, TN299×31256 53.3 m, 2009_Amundsen 148.6 m, the SKQ/Tonga pairs ~47–53 m) — a solved shift beyond the AUV USBL bound: either a real large USBL error or a bad lock; **QGIS arbitrates**.
- **PSR ≤ 0 / undefined** (FK006B −8.97, FK171110 −0.79, KN204-01 & MGLN06MV undefined) — degenerate NCC surface, no real interior peak.

Every F5 re-coreg wrote a fresh `_overlay_f5.png` (NCC heat-map + hillshade) for the
QGIS reviewer. Note the F5 re-coreg already fixed Stage F's nodata contamination, so
these offsets/PSRs are the **trustworthy** numbers (Stage F's were computed on fill-
contaminated data).

---

## 5. F5-5 — Gap-2 re-check (the 2 eval_only demotions): **both stand**

Re-measured the SR-band structural RMS on a **both-finite (joint) window**, reproducing
the C.5b method (`load_to_common` + `band_rms` over `[f_lr, min(8·f_lr, nyq)]`) on a
**fill-cleaned** HR:

| pair | HR SR-RMS (m) | LR SR-RMS (m) | excess | verdict |
|---|---:|---:|---:|---|
| NA090×31212 | 1.78 | 1.55 | 1.15 | **demotion_stands** |
| TN159×21981 | 10.24 | 9.14 | 1.12 | **demotion_stands** |

Both read HR ≈ LR in the SR band (excess < 1.3) even after one-sided fill is excluded —
consistent with the original C.5b `near_circular_weak` call (1.57/1.65 and 3.79/6.95).
The `eval_only` demotions hold; no re-flag. (Provenance-based keep verdicts for the 6
coherence-flagged pairs are unaffected by 0-fill and were never in question.)

---

## 6. Recommendation + HOLD

**HOLD for assessment before Stage G.** Review order:
1. **The Stage F vertical/fill bug (§3)** — this is blocking. Decide on the targeted
   Stage F repair (re-coreg masked + rewrite `hr.tif`, using the F5 re-coreg `dz`).
   **No pair advances until its `hr.tif` values are repaired**, including the 2
   vertically-suspect "clean" pairs.
2. **Exclude candidates (§2):** 3 inflated + 6 weak — confirm exclusion (RC2511×32240,
   TN268×24470, FK160407×7832 etc. are clearly one-sided; EW0207/EW9904/TN268×30219 are
   genuinely large — judge whether a real km-scale AUV patch exists within them).
3. **14 coreg_fail (§4):** QGIS-arbitrate large-offset vs bad-lock via the `_overlay_f5`.
4. Only pairs that are (a) not excluded, (b) clean/repaired lock, (c) vertically
   repaired, and (d) carry a written `joint_valid` mask + `valid_tiles` entries advance.

After repair, the **clean horizontal set is ~9** (7 vertically-sound now + AT37-13,
AT42-03 once repaired); the corpus's real, leakage-safe, fully-masked trainable core is
those plus whatever QGIS rescues from the 14.

**Tracked carry-overs (unchanged):** discovery footprint-bbox gate (next harvest), the 6
orphan `cal_dig` sub-dirs (before Stage G), raw purge per retention policy. **New
carry-over:** the Stage F masked-coreg repair (§3).

## Deliverables
1. per-pair `hr_valid`/`lr_valid`/`joint_valid` masks (`$DATA_ROOT/harmonized/<pair>/`)
2. `valid_tiles.parquet` (14,795 tiles / 29 pairs) + sampling rule (256 px, ≥ 0.50 joint, masked loss on `hr_valid`)
3. updated `combined_corpus.csv` (`f5_*` cols incl. vertical-suspect flags) + `stage_f5_results.json`
4. this report (incl. the Gap-2 re-check and the discovered Stage F bug)
5. updated `staging_state`

### Sampling rule (flagged modeling parameters — confirm with the training side)
- tile edge **256 HR px**; include tile iff **joint_valid fraction ≥ 0.50**; compute SR
  loss **only on `hr_valid` pixels** (per-pixel masked loss); feed LR with a validity channel.
- gate thresholds: area-plausibility **300 km²**, weak-coverage **fraction < 0.20**, LR-mask
  edge **erode 1 cell**. All flagged for confirmation, not silently chosen.
