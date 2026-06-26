# Phase 2 — Stage C.5b consolidation report

**Date:** 2026-06-23 · **Author:** Claude Code execution instance (Sherlock)
**Directive:** `reports/directive_phase2_stage_c5b_consolidation.md`
**Status:** ⛔ **HOLD for assessment** — confirm k and the factor-based convention before Stage E. Analysis only.

**Artifacts**
- `reports/stage_c5_sr_signal_sweep.csv` (per-k local-slope + verdict curve), `reports/discovery/stage_c5b_sweep.json`
- `reports/discovery/stage_c5b_calibration.json` (finer-grid re-calibration)
- QC plots `reports/discovery/stage_c5_qc/` incl. `corpus_perk_curve.png`
- Code: `src/discovery/stage_c5_{spectral,calibrate,sweep,plots}.py`

---

## 1. Headline — the C.5 reframe survives a proper test, with k now genuinely measured

C.5's flat 33/33/33 was partly a Nyquist artifact (the LR/16 grid capped at 8×). Re-run on an **AUV-native grid** with **factor-specific** recoverability (local spectral slope *at each k's target scale*, not "is this red anywhere") and **log-spaced** radial bins:

- **Recoverable structure stays ~flat at ~23–26 pairs from k=2 through k=16, then falls at k=32** — but the fall is dominated by each pair hitting *its own ratio/Nyquist limit* (you can't super-resolve past the AUV's resolution), not by structure turning to roughness.
- The seafloor really is **self-similar (red) through the resolvable band** — the C.5 invariance was not just an artifact.
- **But the metric now shows genuine factor-dependence** — 2 pairs flatten to `roughness_only` by k=8, marginal cases appear, and high-k truncates — so it is measuring recoverability, **not merely redness** (the directive's key worry, addressed).

**Confirmed trainable count: 29** pairs carry recoverable red SR structure at **k = 8** (24 `recoverable_signal` + 5 high-coherence-but-independent, §3); 2 are genuine roughness; **24 deep pairs (ratio 40–320) are rescued**.

---

## 2. Track A — finer-grid re-run

**A1/A2 — re-calibration on the AUV-native grid passed** (it does not assume the LR/16 thresholds transfer): 22/22 known-recoverable → `recoverable_signal`; synthetic white → `roughness_only`; synthetic circular → `circular_leak`. New thresholds: `slope_red −0.97`, `slope_white −0.80`, `coh_circular 0.136`. *(Two metric bugs were found and fixed en route: a calibration-k that wasn't resolvable for the 5× Cal DIG pairs → moved to k=2; and linear radial binning that starved low-frequency slopes → switched to log bins. Both are the "don't trust a metric blindly" guardrail working.)*

**A3 — per-k recoverable curve** (`corpus_perk_curve.png`):

| k | recoverable (red SR structure)¹ | roughness_only | NR (beyond pair ratio/Nyquist) |
|---|---|---|---|
| 2 | 32 | 0 | 2 |
| 4 | 29 | 0 | 3 |
| 8 | **29** | 2 | 3 |
| 16 | 29 | 0 | 5 |
| 32 | 20 | 1 | 13 |

¹ counts `recoverable_signal` + the high-coherence-but-**independent** pairs (§3), both of which have red SR-band structure; of 34 valid pairs.

The plateau through 16× then Nyquist-limited fall = **self-similar structure, recoverable up to each pair's own factor ceiling** (≈ its LR/AUV ratio). The metric tracks factor-specific recoverable energy (it does fail pairs at high k), not just "is it red".

**A4 — UQ ceiling (now genuinely measured, not Nyquist-zeroed).** AUV energy *above* the k=8 target band is **0–2 % of total** (median ~0). This is a *real* result, not a bug: red seafloor spectra concentrate energy at large scales, so the unrecoverable fine-scale roughness is a **small fraction** of the morphology — the per-pair uncertainty burden on the model is modest. (The C.5 ~0 was the Nyquist artifact; this ~0–2 % is the true small fraction.)

**A5 — confirmed k = 8.** Solidly inside the plateau; many pairs hold to 16×; the limit is each pair's ratio/Nyquist, not loss of structure. k=8 is the defensible recommendation (k=4 conservative; 16× available for high-ratio deep pairs).

---

## 3. Track B — independence re-check (the coherence flags are false alarms)

The 6 `circular_leak` flags (3 in C.5, 6 at the finer grid) are, **by provenance, independent pairs**:
- **All LR are NCEI MBBDB per-cruise raw acquisitions** — `FK160407` (RV Falkor), `NA090` (E/V Nautilus), `TN268` (RV Thompson) — **not composites**. No GEBCO/GMRT/USGS-compilation that could ingest the AUV.
- All HR are genuine AUV (ABE/Sentry, 1–1.6 m).

**Verdict: `independent` for all.** The high edge coherence is **real shared large-scale relief** (high-relief co-located sites where ship + AUV agree at the band edge), not data leakage. The coherence guard — calibrated on a synthetic circular (coherence ≈ 1) — **over-flags high-relief independent pairs** (their edge coherence ~0.15–0.33, far below 1). **Recommendation: keep all 6** (treat coherence as informational, not exclusionary, *because provenance already guarantees independence*). Genuine circularity is precluded by the corpus design. No shared-source screen gap (distinct cruises; TN268's other HR did not flag).

---

## 4. Track C — failure triage (12 → split)

| HR pair | footprint | verdict |
|---|---|---|
| Channel×31949 | 183×76 km | **false pair — exclude** (inflated geometry) |
| EX1103×31811 | 358×63 km | **false pair — exclude** |
| EX1103×18210 | 358×63 km | **false pair — exclude** |
| TN365×31193 | 164×74 km | **false pair — exclude** |
| TN268×32556 | 32×80 km | **false pair — exclude** |
| 2010_Amundsen×31753 | 8.5×7.3 km | fixable (HR raster format) |
| EW9801×31425 | 3.3×4.2 km | fixable |
| KIWI10RR×24499 | 9.9×24 km | fixable |
| RB1604×24756 | 26×13 km | fixable |
| TN157×21996 | 4.2×5.7 km | fixable |
| TN159×21998 | 10×23 km | fixable |
| **2009_Amundsen×30045** | 30×60 km | **REAL pair, fixable** — see below |

- **5 false pairs** (degrees-wide footprints = the AT18-11 inflated-geometry pattern, not co-registration bugs): **exclude.** These are discovery-screen bbox-overlap false positives.
- **6 fixable** (km-scale, HR raster format/CRS): need a per-HR materialization fix; not false pairs.
- **`2009_Amundsen×30045` (priority — our only Arctic single-HR pair):** **a real pair, not inflated** — it gridded cleanly in the Stage-C pilot (fill 0.46, near_nadir). The spectral co-registration fails only because the HR is 5 dive-tiles spread over the survey and the largest-tile heuristic picks one the LR subset doesn't cover. **Fixable with per-tile co-registration** — recommend the manual effort given its diversity value. Not a no-overlap exclusion.

---

## 5. Confirmed accounting (for Stage E)

Per the directive's formula: **33** (C.5 at 8×) **− 0 genuine leaks** (all 6 coherence flags are independent) **− 5 false pairs** (inflated; were already failures) **+ rescued** (fixable failures, pending raster fix) = **≈ 29 confirmed trainable at k = 8**, with 24 of them deep-pair rescues from the ratio gate. The 6 fixable failures (incl. Arctic `30045`) can add up to ~6 more once their HR rasters render.

---

## 6. Recommendation + HOLD

**HOLD for assessment** before Stage E:
1. **Confirm k = 8** and the factor-based convention (target = LR/8) replaces the ratio gate.
2. **Confirm the ~29 trainable count** (and that the 6 coherence-flagged pairs are kept as independent).
3. **Rule on the 5 inflated false pairs** (exclude) and authorize the per-tile fix for `2009_Amundsen×30045` + the 5 other fixable failures.
4. Follow-up (not blocking): UQ-ceiling is small by nature — confirm the modest-uncertainty framing is acceptable.

## Deliverables
1. `stage_c5_sr_signal_sweep.csv` (per-k curves) + `stage_c5b_sweep.json`
2. this report + `stage_c5b_calibration.json`
3. independence findings (6 pairs) + failure triage table (12)
4. QC plots incl. `corpus_perk_curve.png`
5. updated `staging_state`
