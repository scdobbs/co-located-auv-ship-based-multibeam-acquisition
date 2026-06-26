# Phase 2 — Stage C.5 spectral SR-signal sweep report

**Date:** 2026-06-23 · **Author:** Claude Code execution instance (Sherlock)
**Directive:** `reports/directive_phase2_stage_c5_sr_signal_sweep.md`
**Status:** ⛔ **HOLD for assessment** — confirm the factor `k` and the factor-based tiering convention before Stage E re-tiers. Analysis only; no re-grid, no re-tier, no manifest/OAK writes.

**Artifacts**
- `reports/stage_c5_sr_signal_sweep.csv` (pair × k × slope × coherence × verdict)
- `reports/discovery/stage_c5_sweep.json`, `stage_c5_calibration.json`
- QC plots: `reports/discovery/stage_c5_qc/`
- Code: `src/discovery/stage_c5_{spectral,calibrate,sweep,plots}.py`

---

## 1. Headline — the ratio gate badly under-counts the trainable corpus

Reframing from "LR/AUV ratio" to "**recoverable SR signal at a fixed factor k above each pair's own LR**" (target = `LR_native / k`) transforms the picture:

| | ratio gate (Stage C) | **spectral reframe (this stage)** |
|---|---|---|
| trainable pairs | "2–3" | **33 of 38 valid pairs** carry recoverable SR structure **at 8×** |
| deep pairs (ratio >40) | all excluded | **24 rescued** — recoverable at 2–8× despite ratio 40–320 |

The deep abyssal seafloor is **self-similar (red-spectrum), not white roughness**, so structure finer than the ship LR is statistically predictable down to a fixed factor — even where the absolute LR/AUV ratio is huge. **No pair scored `roughness_only`** at k≤8: the "hallucination zone" doesn't bite this corpus at these factors. The non-recoverable cases are independence flags (3) and degenerate grids (2), not roughness.

---

## 2. S0 — metric calibration (passed)

The metric is anchored on known references before judging the corpus, on two calibrated axes:
- **slope** of the HR PSD in the SR band: red/power-law (≤ −1.33) = self-similar, predictable; flat (≥ −1.08) = white roughness (hallucination).
- **edge coherence** (LR↔HR at the band edge): low = independent acquisitions (valid); ≥ 0.137 = HR structure already in the LR (circular/leaked → not a valid SR pair).

| reference | result | required |
|---|---|---|
| 21 validated pairs (DISCOL/CalDIG/CCZ/TAG) | **21/21 `recoverable_signal`** | HIGH ✓ |
| synthetic white-roughness (LR + uncorrelated noise) | `roughness_only` | LOW ✓ |
| synthetic circular (HR ≡ upsampled LR) | `circular_leak` | LOW ✓ |

Calibration separates known-recoverable from **both** unrecoverable references → the metric is fit to judge the corpus. (An earlier fraction-of-energy + raw-coherence formulation failed its own sanity check and was rejected — the "don't trust a metric blindly" guardrail working as intended.)

---

## 3. S1/S2 — per-pair sweep + corpus distribution

50 (cruise × HR) pairs swept; **38 produced valid spectra** (12 co-registration failures, §6). Distribution over the 38:

| k (factor above LR) | recoverable_signal | circular_leak | no_spectrum |
|---|---|---|---|
| 2× | 33 | 3 | 2 |
| 4× | 33 | 3 | 2 |
| 8× | 33 | 3 | 2 |

**The same 33 pairs hold recoverable signal at every factor up to 8×** (max_recoverable_k = 8 for all 33). No `roughness_only` and no `marginal` — the seafloor structure is cleanly red through the SR band. **Recommended k: 8×** (the largest tested; the knee is ≥8 since 87 % still hold and none degrade to roughness — higher factors are untested and a candidate for a follow-up sweep). `k=4` is the conservative default if a margin is wanted.

---

## 4. S3 — reframed corpus accounting

- **New trainable count: 33** (recoverable_signal at k=8) — replaces the misleading "2–3 training pairs". The full per-pair/per-k table is in `stage_c5_sr_signal_sweep.csv`.
- **Deep-pair rescue (24):** pairs the ratio gate excluded at >40× that are spectrally recoverable — e.g. `TN159` (ratio 320 → recoverable to 8×), `NA076` (222 → 8×), `RR1506` (135 → 8×), `SKQ201705S` (87 → 8×). A 300 m→37 m (8×) task is recoverable even though 300 m→2 m is hallucination.
- **Validation/UQ ceiling:** the full 1–2 m AUV is retained as the ultra-high-res validation target, **not** the training target. *Caveat:* the per-pair "energy above the target band" came out ~0 because the analysis grid (LR/16) is Nyquist-limited at the k=8 target — quantifying the UQ ceiling needs a second pass on a finer (AUV-native) grid. Flagged as follow-up; it does not affect the recoverability result.

---

## 5. Flags (escalate)

- **3 `circular_leak` pairs** — `FK160407×MGDS:7832`, `NA090×MGDS:31212`, `TN268×MGDS:30466`: high LR↔HR edge coherence = the AUV structure appears already present in the ship LR. In an *independent* corpus this should not happen — **recommend an independence re-check** (is the LR genuinely a separate acquisition, or did a composite/processed product leak the AUV in?). This is the anti-circularity guardrail catching candidates.
- **2 `no_spectrum`** — `2010_Amundsen×{31755,30270}`: the Stage-C "suspect-overfine shallow" pairs (degenerate native res); spectrally degenerate too. Consistent with their Stage-C flag; exclude.

---

## 6. Co-registration failures (12) — follow-up, not blocking

- **5 `hr_unreadable`** (HR raster couldn't be materialized even with GMT-convert + catalog-CRS): `2010_Amundsen×31753`, `EW9801×31425`, `KIWI10RR×24499`, `RB1604×24756`, `TN268×32556`.
- **7 `empty/no_data_overlap`**: `Channel×31949`, `EX1103×{31811,18210}`, `TN157×21996`, `TN159×21998`, `TN365×31193`, `2009_Amundsen×30045`. Some are inflated-footprint or genuine no-overlap (possible false pairs).

These need a per-HR raster/CRS fix (the same A.6 CRS fragility); they do not change the §1 finding. The sweep already fixed the bulk by materializing HR to GeoTIFF with the catalog CRS and windowing on the **HR∩LR∩footprint** data intersection (not the inflated footprint).

---

## 7. Recommendation + HOLD

**HOLD for assessment** before Stage E:
1. **Confirm the factor-based tiering convention** (target = LR/k) replaces the ratio gate, and **confirm k = 8** (or k = 4 conservative).
2. **Confirm the reframed trainable count (33)** and the deep-pair rescues feed Stage E's split.
3. **Rule on the 3 circular_leak pairs** (independence re-check) and exclude the 2 degenerate Amundsen pairs.
4. Follow-ups (not blocking): fix the 12 co-registration failures; quantify the UQ ceiling on a finer grid.

## Deliverables
1. `stage_c5_sr_signal_sweep.csv` + `stage_c5_sweep.json`
2. this report + `stage_c5_calibration.json`
3. spectral QC plots (`reports/discovery/stage_c5_qc/`)
4. updated `staging_state`
