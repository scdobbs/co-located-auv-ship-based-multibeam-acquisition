# Phase 2 — Stage F REPAIR: masked re-coregistration + HR datum repair

**Date:** 2026-06-26 (executing the 2026-06-23 directive `reports/directive_phase2_stage_f_repair.md`)
**Author:** NEW Claude Code execution instance (fresh context, Sherlock)
**Status:** ⛔ **HOLD for assessment** before Stage G. Repairs applied (append-only); no manifest/OAK writes, no exclusions executed.

**Code:** `src/discovery/stage_f_repair.py` (`verify` / `repair` / `postcheck`), `sbatch/stage_f_repair.sbatch`
**Data artifacts:**
- `reports/discovery/stage_f_repair_verify.json` — independent pre-repair verification (all 32 + the 21 validated + mask/tile sample)
- `reports/discovery/stage_f_repair_results.json` — what was written per pair
- `reports/discovery/stage_f_repair_postcheck.json` — post-repair masked-open verification
- repaired `hr.tif` + retained `hr_preF5repair.tif` in `$DATA_ROOT/harmonized/<pair>/` (22 pairs)

All numbers below were re-derived **independently from the raw rasters** on a compute node. I did not copy the prior `dz` values; where I cite them it is to compare.

---

## 0. Bottom line

- The Stage F bug is **real and exactly as described** — independently reproduced from raw data: **15 / 32 vertical-suspect (|Stage F dz| > 50 m), 22 / 32 fill-leaked** (the same counts the F5 instance reported).
- **But the repair value is *not* simply −(Stage F dz) for every pair.** The 15 suspect pairs split into two physically distinct groups (the directive was right to warn against trusting the inversion):
  - **Group A (7):** the Stage F `dz` was genuine garbage (fill made up **> 50 %** of the grid, so the coreg median landed *in* the fill). Undoing it recovers a sane datum that already agrees with the ship LR to a few metres.
  - **Group B (8):** the Stage F `dz` was **approximately legitimate** (fill **< 50 %**, median landed in real cells). The *underlying* AUV grid has an independent, pre-existing datum problem — after undoing the bug its seafloor sits at **+70 … +255 m (positive)**, often a constant plateau. These are an inflated/coreg-fail/weak data-quality problem, not a Stage F arithmetic problem. **All 8 are already non-advancing.**
- **Repair principle (depth-sane by construction):** for each suspect pair I aligned the HR datum to the **ship LR** (the project's geo-reference) using a robust zero-horizontal-shift offset `dz_apply = −median(HR_current − LR)` over joint real cells. This is independent of the suspect horizontal search and yields `repaired ≈ LR` for every pair. I verified the LR itself sits at a physically plausible depth for each site.
- **The 9 "clean"/advancing pairs are all depth-sane after repair** (the 2 vertically-corrupted ones — AT37-13, AT42-03 — now sit at ~−1.6 / −1.5 km, matching their ship LR to < 1 m).
- **Step 4 — the 21 validated pairs did NOT go through the buggy path.** Proven from source (their code paths open HR `masked=True`) and confirmed empirically (clean nodata, plausible depths, zero corruption). **No repair to the 21; nothing touched.**
- **Step 5 — the F5 masks and tile index are sound.** Leaked fill is excluded from `joint_valid` for all 22 leaked pairs; sampled tiles reproduce their recorded fractions exactly. No rebuild needed.

---

## 1. Independent bug verification (Step / §"The bug")

`stage_f_harmonize.py:162` opens HR with `rioxarray.open_rasterio(hr.tif)` **without `masked=True`** before `estimate_rigid_xyz`, then `apply_xyz` adds the resulting `dz` to every cell and rewrites `hr.tif`. Confirmed by reading the source, and reproduced from the raw rasters:

- **Leaked fill confirmed at exactly `−9999 + dz`.** Example AT37-13: `dz_stageF = +7930.22`, so fill should sit at `−2068.78`. My raw scan found **4,300,596 cells at −2068.78** and **0 cells at −9999** — i.e. every fill cell was shifted, and the GeoTIFF nodata tag still reads `−9999`, so `read(masked=True)` would leave the leak finite. (This matches the F5 `fill_corruption_cells` count for AT37-13 to the cell.)
- **Real seafloor shifted into the physically impossible.** AT37-13 current real values: p1/p50/p99 = **+5981 / +6285 / +6439 m** (kilometres *above* sea level). Subtracting `dz_stageF` recovers p50 = **−1645 m**, matching the ship LR (−1648 m) to 6 m.
- **Counts reproduced independently:** 15 vertical-suspect, 22 fill-leaked (the other 10 pairs had `dz = 0`, so no leak and no datum shift).

**The diagnosis holds.** I did not have to stop.

### Why the dz was garbage for some pairs but not others (new, important)
`estimate_rigid_xyz` takes the **median** of `LR − HR` over all *finite* HR cells. Unmasked, those include the `−9999` fill. The median therefore lands in whichever population is the majority:

| | fill fraction | median lands in | Stage F dz | effect of undoing it |
|---|---|---|---|---|
| **Group A** | **> 50 %** | the fill | garbage (≈ `LR + 9999`) | recovers the true AUV datum |
| **Group B** | **< 50 %** | real cells | ≈ legitimate datum correction | exposes a *pre-existing* broken AUV datum |

This is why "F5 re-coreg `dz` ≈ −(Stage F `dz`)" **holds for Group A and fails for Group B** — I confirmed the relationship pair-by-pair (§2) rather than assuming it.

---

## 2. Per-pair repair `dz` — mine vs the prior report (Steps 1–2)

`my_recoreg_dz` = my own masked rigid re-coreg on joint real cells (independent reproduction of the F5 diagnostic). `dz_apply` = the value actually applied = `−median(HR_current − LR)` over joint real cells (robust zero-shift datum alignment to the ship). All depths in m, negative-down.

| pair | F5 bucket | Stage F dz | F5 dz (prior) | **my_recoreg dz** | **dz_apply (used)** | HR_orig p50 | **repaired p50** | LR p50 | group |
|---|---|---:|---:|---:|---:|---:|---:|---:|:--:|
| AT37-13×31199 | clean | +7930.22 | −7936.62 | −7936.62 | −7936.43 | −1645 | **−1652** | −1648 | A ✅ |
| AT42-03×32007 | clean | +8493.15 | −8499.05 | −8499.05 | −8498.73 | −1446 | **−1451** | −1448 | A ✅ |
| SKQ×31255 | coreg_fail | +66.59 | −70.19 | −70.19 | −69.63 | −1054 | **−1057** | −1055 | A |
| SKQ×31254 | coreg_fail | +80.11 | −83.52 | −83.52 | −82.97 | −1054 | **−1057** | −1055 | A |
| TN159×21981 | coreg_fail | +7654.44 | −7655.16 | −7655.16 | −7654.39 | −2137 | **−2137** | −2136 | A (eval) |
| AR26×31838 | coreg_fail | +8055.46 | −8061.53 | −8061.53 | −8065.89 | −1671 | **−1682** | −1659 | A |
| KN210-05×22436 | weak | +6530.11 | −6547.59 | −6547.59 | −6559.15 | −3423 | **−3452** | −3440 | A |
| EW0207×32558 | inflated | −2665.13 | +152.45 | +152.45 | +143.50 | **+255** | −2267 | −2309 | B |
| EW9904×30217 | inflated | −1973.66 | +8.42 | +8.42 | +8.63 | **+181** | −1785 | −1794 | B |
| FK171110×24485 | coreg_fail | +6724.10 | −9468.63 | −9468.63 | −9467.18 | **+255** | −2488 | −2520 | B |
| NA076×32321 | coreg_fail | −10047.23 | +9132.32 | +9132.33 | +9130.39 | **+107** | −810 | −866 | B |
| RC2511×32241 | coreg_fail | −5462.93 | +3181.32 | +3181.32 | +2968.58 | **+255** | −2239 | −2279 | B |
| TN383×29694 | coreg_fail | −1984.14 | +0.12 | +0.12 | −0.16 | **+224** | −1760 | −1781 | B |
| TN299×31256 | coreg_fail | −1306.60 | +9.51 | +9.51 | +8.05 | **+255** | −1044 | −1087 | B |
| FK181031×24620 | coreg_fail | −3842.11 | −0.38 | −0.38 | −0.39 | **+71** | −3772 | −3788 | B |

**Findings:**
1. My independent masked re-coreg **reproduces the prior F5 `dz` to ≤ 0.3 m** on every suspect pair — so the F5 *arithmetic* was correct; the prior instance's error was one of *interpretation* (the report implied a uniform `dz ≈ −(Stage F dz)` repair, which would corrupt Group B).
2. **Group A (7):** `HR_orig` already lands at a sane depth that matches LR within a few metres. The Stage F `dz` was pure garbage.
3. **Group B (8) — the key correction to the prior report:** undoing the Stage F `dz` does **NOT** give a sane datum (HR_orig is positive, +70…+255 m, frequently a constant plateau). The bug was minor here; the AUV grid itself is broken/inflated. **For these, the correct depth comes from aligning to LR, not from inverting the bug.** Every one is already inflated/coreg_fail/weak → **none advance.**
4. `dz_apply` differs from `my_recoreg_dz` only for the poor-lock pairs (e.g. RC2511×32241: applied +2968.6 → −2239 ≈ LR −2279; the searched-offset recoreg +3181 would over-shift to −2027). The zero-shift LR alignment is the more robust, depth-sane choice.

---

## 3. Absolute-depth sanity — ALL advancing pairs (Step 3)

Verified by re-opening each repaired `hr.tif` with `masked=True` (the loader's path) and comparing the masked HR median to the ship LR median over joint real cells. `resid = median(HR − LR)`. No leaked fill survives in any (`n < −8000 = 0` everywhere).

**The 9 `clean` / advancing pairs — all depth-sane:**

| pair | repaired HR p50 (m) | LR p50 (m) | resid (m) | site / morphology | verdict |
|---|---:|---:|---:|---|:--:|
| AT37-13×31199 | −1652 | −1652 | 0.0 | continental margin | ✅ (repaired) |
| AT42-03×32007 | −1451 | −1451 | −0.0 | continental margin | ✅ (repaired) |
| EW9801×31425 | −1181 | −1184 | +2.9 | vent | ✅ (fill cleaned) |
| NA080×31290 | −3309 | −3317 | +8.4 | seamount | ✅ (untouched) |
| NA090×31212 | −1852 | −1855 | +3.2 | margin (eval) | ✅ (fill cleaned) |
| RR1506×29779 | −1007 | −1014 | +7.1 | margin | ✅ (fill cleaned) |
| TN268×30466 | −2295 | −2296 | +1.5 | vent | ✅ (untouched) |
| TN399×30373 | −2561 | −2562 | +0.8 | margin | ✅ (fill cleaned) |
| FK181031×24367 | −2393 | −2400 | +7.1 | margin | ✅ (untouched) |

The two formerly-corrupted "clean" pairs (AT37-13, AT42-03) now sit at correct margin depths (~1.5–1.7 km), matching their ship LR to < 1 m. The other 7 clean pairs were already depth-sane (their `|dz| < 11 m`); I re-checked for sub-50 m hidden corruption and found none (residuals 0.8–8.4 m).

**Two non-advancing pairs carry an independent, un-repaired raw-datum problem (flag for assessment):**
- `FK160407×7832` (weak_exclude, untouched): HR is a tiny +2136 m plateau (only 1,031 real cells). `dz_stageF = 0` and no leaked fill, so the Stage F bug never touched it — the **raw AUV grid datum is broken**. 0 tiles; excluded regardless.
- `2009_Amundsen×30045` (coreg_fail, untouched): HR is a +255 m plateau (~1.2 M cells). Same situation — raw-datum/inflation problem, not a Stage F bug. Non-advancing.
- The same `+255` plateau signature appears in Group B's `HR_orig` (EW0207, FK171110, RC2511×32241, TN299×31256). **This is a distinct discovery-stage data-quality issue (broken/clamped AUV datum on certain MGDS grids) that the footprint-bbox inflation flagged the same pairs for.** It does not affect any advancing pair. Recommend it be folded into the existing inflated/weak exclusion arbitration at Stage G.

---

## 4. Step 4 (MANDATORY) — did the 21 validated pairs go through the buggy code path? **NO.**

**Source-code proof.** The unmasked-open-before-coreg pattern exists in exactly one place:
- `src/discovery/stage_f_harmonize.py:162-163` — opens HR/LR **without** `masked=True`. This module processes **only** `corpus.source == "new_c5c"` (the 32 new pairs).

Every other coregistration call site opens HR **with `masked=True`** before `estimate_rigid_xyz`:
- `src/pipeline.py:160` (`masked=True`) → built **discol_so242_1, ccz_so268_1, tag_m127**.
- `src/reharmonize_user_hr.py:398` via `_open()` (`open_rasterio(path, masked=True)`, line 123) → built **the 18 cal_dig_morro_bay sub-pairs**.

So the buggy fill-sampling could not occur for the 21 validated pairs by construction.

**Empirical confirmation** (read-only, OAK copies — not modified):

| validated pair | nodata tag | HR p50 (m) | cells < −8000 | cells > +1000 | site expectation |
|---|---|---:|---:|---:|---|
| discol_so242_1 | −9999 | −4147 | 0 | 0 | Peru Basin ~4100 m ✅ |
| ccz_so268_1 | −9999 | −4098 | 0 | 0 | CCZ ~4100 m ✅ |
| tag_m127 | −9999 | −3463 | 0 | 0 | TAG/MAR ~3600 m ✅ |
| cal_dig (4 sampled subdirs) | −9999 | −813 … −990 | 0 | 0 | Morro Bay margin ✅ |

Clean nodata, physically correct depths, **zero** corruption signature. **The 21 validated are clean; nothing was modified.** (Code-path evidence is definitive for all 21; the empirical sample spans all source types.)

---

## 5. Step 5 — re-verify the F5 masks and tile index. **SOUND.**

- **Leaked fill is excluded from `joint_valid`.** For all 22 fill-leaked pairs, `leaked_in_joint = 0` (the F5 `_hr_real_valid` detected `−9999 + dz` exactly). The only blemish: `NA076` has **77** stray `−9999` cells inside joint (of 4.5 M; 0.0017 %) — negligible, and NA076 is a non-advancing coreg_fail. After repair these are NaN anyway.
- **`valid_tiles.parquet` is correct:** 14,795 tiles / 29 pairs, `min_joint_fraction = 0.50`; every sampled tile's recomputed joint fraction equals its recorded value exactly.
- **Masks still align after repair:** the repair changed **values only**, never geometry/transform — postcheck confirms `mask_shape == hr_shape` for all 32.

No mask rebuild required.

---

## 6. What was written (append-only) and the repair rule

**Repaired (22 pairs)** — `hr.tif` rewritten as float32 with **NaN nodata**, fill (both `−9999` and leaked `−9999+dz`) → NaN, real cells shifted by `dz_apply`. Pre-repair file preserved as **`hr_preF5repair.tif`** (idempotent: re-runs skip if the backup exists).
- **15 vertical-suspect** (Group A + B above): `dz_apply = −median(HR_current − LR)` over joint real cells → datum aligned to ship LR.
- **7 small-dz fill-leaked** (EW9801, FK006B, MGLN06MV, NA090, RR1506, TN268×30219, TN399): `dz_apply = 0` — real values were already depth-sane (`|dz| < 11 m`, current ≈ LR); only the leaked fill was stripped to NaN.

**Untouched (10 pairs):** `dz = 0` and no leaked fill → the bug never affected them; their `−9999` nodata tag already masks correctly. Two of them (FK160407, 2009_Amundsen) carry the independent raw-datum problem noted in §3 but are non-advancing.

**Guardrails honored:** `masked=True` on every HR open/write; append-only (pre-repair files retained); the 21 validated read-only; no manifest/OAK writes; no Stage G; no exclusions executed.

---

## 7. Final disposition

**(a) Not excluded · (b) clean / repaired-and-depth-sane · (c) correctly masked — these ADVANCE (9):**
`AT37-13×31199` (repaired), `AT42-03×32007` (repaired), `EW9801×31425`, `NA080×31290`, `NA090×31212` (eval_only), `RR1506×29779`, `TN268×30466`, `TN399×30373`, `FK181031×24367`.

**Do NOT advance (23)** — repaired/cleaned where they had corruption, but held for the existing arbitration (out of scope here, flag only):
- **14 genuine_coreg_fail**, **3 inflated_exclude**, **6 weak_exclude** (F5 buckets). 8 of these also carry the Group-B / +255-plateau raw-datum problem (§3) → fold into the inflated/weak exclusion review.

**HOLD for assessment before Stage G.** Open items for Steve / the assessment instance:
1. Confirm the repair principle (align HR datum to ship LR) and the 9-pair advancing set.
2. The Group-B / +255-plateau **raw AUV datum** problem on 8 non-advancing pairs — confirm exclusion (it coincides with the footprint-bbox inflation flags).
3. The standing QGIS arbitration of the 14 coreg_fail via `_overlay_f5.png` (unchanged from F5).
4. Then Stage G manifest append (append-only, dedup vs the 21).

## Deliverables (this stage)
1. repaired `hr.tif` (NaN nodata) + retained `hr_preF5repair.tif` for 22 pairs ✅
2. this report ✅
3. updated `combined_corpus.csv` (repair status + depth-sanity per pair) ✅
4. updated `staging_state` ✅

## Tracked carry-overs (unchanged)
Discovery footprint-bbox gate (next harvest); 6 orphan `cal_dig` sub-dirs (before Stage G); raw purge per retention policy; the 3 inflated + 6 weak + 14 coreg_fail exclusion/arbitration candidates (Stage G prep). **New:** the Group-B raw-AUV-datum (+255 plateau) problem on 8 non-advancing pairs — arbitrate alongside the inflated/weak set.
