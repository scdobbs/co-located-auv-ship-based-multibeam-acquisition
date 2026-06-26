# Co-located corpus RE-AUDIT — R0–R5 report (reader proof + disposition)

**Date:** 2026-06-26 · **Directive:** `reports/directive_phase2_colocated_reaudit_v1.md`
**Author:** Claude Code execution instance (Sherlock), fresh reader built from scratch.
**Status:** ⛔ **HOLD.** R0 gate **passed** (corrected reader proven). **But it returns a finding that contradicts the directive's central hypothesis — escalating before R2/R3/R6.** No manifest/OAK writes, no exclusions executed, 21 read-only.

**Code:** `src/discovery/stage_reaudit_r0.py` (reader + inventory + PNG evidence), `stage_reaudit_r5.py`.
**Artifacts:** `reports/discovery/stage_reaudit_r0.json`, `stage_reaudit_r5_validated21.json`; PNG evidence `$DATA_ROOT/qc_plots/r0_evidence/*.png` (11 pairs).

---

## 0. Headline — the "+255" is NOT a misread of real depth. It is RGB.

The assessment directive's strong hypothesis was: *band 1 is float elevation; an auxiliary band is a 255 mask; the assessment read the wrong band.* **That is not what the data shows.** Anchored to the actual file structure and to the ship LR (external truth, not self-consistency):

- **9 of the 32 new pairs have an HR source that is a 3-band uint8 RGB *visualization render*** (color slope/hillshade images — filenames like `AxialSRift_MAUV_ver2025_Topo1m_slope...`, `..._Topo1m_slope...`). **There is no float elevation band to read.** `materialize_hr` did `ds.read(1)` = the **red channel** (0–255); the "+255" is a saturated red pixel (0xFF), not a clamp.
- A Mapbox/terrarium **Terrain-RGB decode** of these tiles yields ~+1.6 × 10⁶ m — `plausible=False` for all 9. The RGB is a colormap render, not a packed-float encoding. **No reader can recover depth from them.**
- The directive's "known-bad" control **`TN299×31256` is structurally identical to the other 8** (3-band uint8 RGB). The expected "positive discriminator" (real-grid-we-misread vs figure) instead shows **all 9 are on the figure/visualization side.**
- **Where did Steve's "QGIS-verified negative depths" come from?** Almost certainly from **my prior Stage-F-repair output.** My repair aligned the RGB red channel to the LR datum, producing a near-flat plateau at the ship's depth (EW0207: a uniform ≈ −2400 m field — see `qc_plots/r0_evidence/EW0207__MGDS_32558.png`, panel 2 is flat yellow while the real LR in panel 3 has structure). In the QGIS Value Tool that flat plateau reads as "realistic negative depths." **My earlier repair manufactured the very appearance that motivated this re-audit.** I flag that plainly.

**Consequence:** the 9 RGB pairs **cannot "return to advancing"** — there is no HR bathymetry. They were all already non-advancing in the prior stage, so the **advancing set is unchanged (9 real pairs).** The reader bug did not promote or corrupt any advancing pair.

---

## R0 — corrected reader, PROVEN (the gate)

**Band semantics, per source (`gdalinfo`-equivalent via rasterio/netCDF4):**
- **GMT `.grd`** (e.g. `sentry*.grd`, `lau*_bathy.abe*.grd`): rasterio can't open these; read via `gmt_grd` → single float band, real bathymetry. **10 pairs.**
- **float `.tif`** (e.g. `*_elv_*.tif`, Sentry topo): single float band. **13 pairs.**
- **3-band uint8 RGB `.tif`** (`colorinterp=[red,green,blue]`): visualization render, **no elevation. 9 pairs.**

**Corrected reader:** detect 3-band uint8 → reject as non-elevation; else materialize via `gmt_grd`/float read, `masked=True`, NoData→NaN. (Also handles positive-down depth sign, see FK160407.)

**Proof against external truth** — the corrected reader reproduces real depths that match the ship LR and the prior (band-1-correct) values for the real pairs, and renders the co-located morphology (see `AT37-13` PNG: HR source, harmonized HR, and ship LR all show the same −1500…−2000 m seafloor):

| pair | old reader (band1) | corrected reader p50 | ship LR p50 | external check |
|---|---:|---:|---:|---|
| AT37-13×31199 (.grd) | +6285 (=255-relative? no — fill-leak, see R4) | **−1645.5** | −1648 (joint) | ✅ matches LR & QGIS |
| AT42-03×32007 (.grd) | +7047 | **−1445.8** | −1448 | ✅ |
| KN204-01×31675 (.grd) | n/a | **−1584.5** | −1538 (joint) | ✅ |
| NA080×31290 (float) | −3309 | **−3308.9** | −3316 | ✅ (was already right) |
| **EW0207×32558 (RGB)** | **+255** | **NO ELEVATION** | −2309 | ✅ source is RGB render |
| **FK171110×24485 (RGB)** | **+255** | **NO ELEVATION** | −2520 | ✅ source is RGB |
| **TN299×31256 (RGB, control)** | **+255** | **NO ELEVATION** | −1087 | ✅ figure/render confirmed |

Gate verdict: **the reader is proven on the 23 real pairs and correctly identifies the 9 RGB pairs as non-elevation.** PNG evidence rendered for 11 representative pairs.

---

## R1 — re-derived disposition for all 32 (through the proven reader)

For the **23 real-elevation pairs, band 1 *is* the float elevation**, so the prior Stage-F/F.5 disposition (which read band 1) used the correct data and **stands** — re-confirmed here: corrected p50 ≈ prior HR_orig ≈ LR. For the **9 RGB pairs the prior numbers were red-channel artifacts** → disposition replaced with a **reader-independent** exclusion.

**Advancing (9 — unchanged, all real elevation, depth-sane vs LR):**
`AT37-13×31199`, `AT42-03×32007`, `EW9801×31425`, `NA080×31290`, `NA090×31212` (eval), `RR1506×29779`, `TN268×30466`, `TN399×30373`, `FK181031×24367`.

**Real-elevation, non-advancing (14 — QGIS-arbitrate / proper re-coreg; NOT reader-limited):**
`FK006B×20811`, `KN204-01×31675`, `MGLN06MV×17700` (~900 m HR↔LR offset — investigate), `SKQ×31255`, `SKQ×31254`, `TN159×21981` (eval), `TN268×30219`, `AR26×31838`, `KN210-05×22436`, `TN299×27339`, `KIWI10RR×24499` (weak), `RC2511×32240` (0 tiles), `TN268×24470` (0 tiles), `FK160407×7832` (real positive-down `.grd`, needs sign flip; 0 tiles).

**RGB visualization → EXCLUDE (9 — reader-independent reason: HR source is a render, no elevation band, Terrain-RGB decode fails):**

| pair | source file (render) | prior f5_bucket | new status |
|---|---|---|---|
| EW0207×32558 | AxialSRift_MAUV…_slope | inflated_exclude | **exclude_no_elevation** |
| EW9904×30217 | AxialSummit_MAUV…Topo | inflated_exclude | **exclude_no_elevation** |
| FK171110×24485 | Sentry458-FK171110-1m (RGB) | coreg_fail | **exclude_no_elevation** |
| NA076×32321 | SantaMonica…_slope | coreg_fail | **exclude_no_elevation** |
| RC2511×32241 | EMARK_massif_MAUV…_slope | coreg_fail | **exclude_no_elevation** |
| TN383×29694 | AxialSeamountMAUV1m…_slope | coreg_fail | **exclude_no_elevation** |
| TN299×31256 | pythia_auv_s19b_gcs (figure) | coreg_fail | **exclude_no_elevation (confirmed figure)** |
| FK181031×24620 | GOCPescaderoBasin…_slope | coreg_fail | **exclude_no_elevation** |
| 2009_Amundsen×30045 | Scar_w_Headwall_715 (RGB) | coreg_fail | **exclude_no_elevation** ⚠️ diversity-critical Arctic pair lost |

**Net:** the corrected reader **confirms the prior 9-pair advancing set** and converts the 9 "+255"/raw_datum_broken flags into a clean `exclude_no_elevation`. The directive's expectation that "+255 pairs return to advancing" does not hold — they have no bathymetry.

---

## R4 — fill-leak vs band-bug map (the directive's a/b/c/d)

Two *different* phenomena, kept separate:

- **(a) reader bug on real-depth data (real depth misread as +255): EMPTY.** This is the central correction. No pair is "real bathymetry that we misread as 255." Every "+255" pair is genuinely RGB.
- **(b) real `−9999+dz` fill-leak / datum, real elevation:** the Group-A real pairs whose Stage-F coreg sampled `−9999` fill — **AT37-13, AT42-03** (directive-endorsed; repaired to correct LR-matching depth ✅), plus the smaller real fill-leaks on other real pairs (EW9801, NA090, RR1506, TN268×30219, SKQ×2, TN159, AR26, KN210, FK006B, MGLN06MV). The Stage-F repair was *correct* for these (band 1 = real elevation).
- **(c) RGB source AND a spurious Stage-F dz applied (my repair shifted a render):** EW0207, EW9904, FK171110, NA076, RC2511×32241, TN383, TN299×31256, FK181031×24620. The "datum" is meaningless; the repair cosmetically aligned RGB to LR. **Recommend restore from `hr_preF5repair.tif` or exclude (see below).**
- **(d) neither (clean real, dz≈0):** NA080, TN268×30466, FK181031×24367, TN299×27339, etc.

---

## R5 — validated-21 spot-check (corrected reader): ALL CLEAN

All 21 are **single-band float32** (0 multi-band RGB), at physically correct site depths, 0 positive cells, 0 cells < −8000:
discol −4147, ccz −4098, tag −3462; cal_dig sub-pairs −443 … −990 m. The calibration anchor is sound through the corrected reader (not just the code-path argument).

---

## Action items / escalation (HOLD)

1. **Confirm the RGB finding.** The 9 pairs are visualization renders, not bathymetry — they cannot be SR HR. Review the `qc_plots/r0_evidence/*.png` (esp. EW0207, NA076, AT37-13 for contrast). **This supersedes the directive's "+255 = misread float" premise.**
2. **My prior repair created the misleading "depths."** The 8 RGB pairs I rewrote (category c) hold a fake LR-aligned plateau in `hr.tif`; `hr_preF5repair.tif` is retained. **Recommend: mark exclude_no_elevation and restore the 8 backups (or delete the fake hr.tif).** Not executed (HOLD).
3. **`2009_Amundsen×30045` loss is diversity-relevant** (the only Arctic/abyssal-shelf pair) — flagged in prior stages as diversity-critical. It is RGB; no recovery. Note for the validation-set diversity discussion.
4. **`MGLN06MV×17700`** real elevation but ~900 m HR↔LR vertical offset — investigate (datum/sign) at QGIS arbitration.
5. **HOLD R2 (multi-grid clip audit), R3 (full 32 QC figures), R6 (combined manifest)** until the above is confirmed. Rationale: the corpus composition just changed materially (9 confirmed excludes), and the 14 real non-advancing pairs need the QGIS arbitration that was already pending from F.5. Building the combined manifest now would bake in unconfirmed assumptions. The R0 evidence PNGs + this disposition are the adjudication material for that decision. **Ready to run R2/R3/R6 immediately on your go.**

## Deliverables produced
1. R0 reader-proof table (old→corrected→external check) + source inventory `stage_reaudit_r0.json` + 11 evidence PNGs. ✅
2. Re-derived disposition for all 32 (old→new→reason). ✅
3. Fill-leak vs band-bug map (R4). ✅
4. Validated-21 spot-check (R5). ✅
5. `combined_corpus.csv` updated: `+255`/`raw_datum_broken` flags **retracted**; added `source_type`, `has_float_elevation`, `reaudit_disposition`. ✅
6. **Deferred (HOLD):** R2 clip/tiler audit, R3 full QC figures, R6 combined manifest — pending confirmation of the RGB finding.

**On skepticism:** every key claim here is anchored externally — the file dtype/colorinterp (`gdalinfo`), the Terrain-RGB decode test, the ship-LR depths, the corrected reader reproducing co-located morphology, and Steve's QGIS (now explained as a view of my repaired output). The prior "+255 = broken raw datum" and the directive's "+255 = misread float" were both internally plausible and both wrong; this report does not ask you to trust a table — it points at the PNGs and the byte-level file structure.
