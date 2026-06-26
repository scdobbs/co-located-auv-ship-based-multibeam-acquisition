# Directive — Phase 2 Stage C.5: spectral SR-signal sweep (recoverable-training analysis)

**Date:** 2026-06-23 · **For:** Phase 2 Claude Code execution instance · **After:** Stage C full gridding · **Before:** Stage E re-tier.

*Background: the LR/AUV resolution ratio mis-frames an independent co-located corpus — surface-ship LR vs near-bottom AUV is intrinsically 40–300×, so the ratio gate excludes almost everything. The Seabed 2030 table is the wrong target (it equals the ship-MBES resolution, which our LR already meets). The defensible convention is a fixed super-resolution **factor above each pair's own LR**: `target = LR_native / k`, which brackets to depth automatically because LR resolution is depth-dependent. The full AUV (1–2 m) is retained as the ultra-high-res **validation/UQ ceiling**, not the training target.*

*This stage measures, per pair and per candidate factor k, whether the AUV carries **recoverable** morphological structure in the SR band (vs unpredictable fine-scale roughness — the hallucination zone). The corpus distribution then picks a defensible k. This replaces the ratio gate; it does not execute the re-tier (Stage E).*

---

## Guardrails

- **Analysis only.** Grids are in hand — **no re-gridding**. No re-tier executed, no manifest/OAK writes, no harmonization. Recommendations for assessment.
- **Calibrate against known truth; do not invent the threshold.** The metric must be anchored on known-recoverable and known-unrecoverable references before it judges the 43 (S0). An uncalibrated spectral metric is exactly the "don't trust a metric blindly" trap.
- **Spectral co-registration is an analysis artifact, not a product.** Resampling LR+HR to a common projected grid for spectra is fine here; it is *not* the Stage-F harmonization and writes no validated pair.
- **Escalate** if the calibration set doesn't score as expected — that means the metric is wrong, not the data.

---

## S0 — calibrate the metric (do this first)

Anchor the recoverable-vs-hallucination threshold on references with known answers:

- **Known-recoverable (must score HIGH):** the 21 validated pairs — DISCOL (~19×), the Cal DIG sub-pairs (~5–10×), CCZ, TAG. These are real, trainable SR pairs; the metric must register recoverable signal in their SR band.
- **Known-unrecoverable (must score LOW):**
  - a **circular** reference if recoverable — the GMRT-over-BAG case from prior work (band-energy SR-signal ratios as low as 0.007): HR ≈ LR, no *new* structure to recover.
  - a **synthetic white-roughness** HR: real LR + a fine-scale band filled with spatially-uncorrelated noise. Structure is *present* but *unpredictable* — the hallucination case. The metric must score this LOW even though raw band-energy is non-zero.

If the metric can't separate the known-recoverable from both known-unrecoverable references, **stop and report** — it isn't ready to judge the corpus.

---

## S1 — per-pair spectral measurement

For each of the 43 gridded pairs (Stage C full + pilot):

1. Resample LR and AUV-HR to a common **projected** (local UTM) grid over the HR footprint, detrended + windowed (analysis-only; spectra are robust to small co-registration offsets, but use the best available alignment).
2. Compute the **radially-averaged power spectral density** of LR and HR over the footprint.
3. For each candidate factor **k ∈ {2, 4, 8}** (target resolution = `LR_native / k`, SR band = spatial frequencies between LR's effective resolution and the target):
   - **SR-signal** — fraction of HR spectral energy lying in the SR band (how much real morphology lives at scales finer than LR but down to the target). "Is there anything to super-resolve at k?"
   - **Recoverability** — is that band-energy *structured* (red/power-law spectrum, and LR↔HR coherent near the band edge → fine structure correlates with coarse → predictable) or *flat/white* (roughness → unpredictable)? Coherence at the band edge is the most direct predictability measure.
   - **Verdict** (thresholds from S0): `recoverable_signal` / `marginal` / `roughness_only`.

Note on HR resolution: the target band uses the HR native res. For `ok_finer_verify` / NaN-catalog HR, use the A.6-measured cell and flag the pair provisional (Stage D may revise). The spectral method works on the actual grid content, so it's relatively robust to this, but carry the flag.

---

## S2 — corpus distribution → defensible k

- For each k, count pairs scoring `recoverable_signal`.
- Report the full distribution: trainable count at 2× / 4× / 8×.
- The **defensible k** is the knee — the largest factor where most pairs still hold recoverable signal and few are `roughness_only`. Report it as a recommendation; assessment/Steve confirm.
- Pairs recoverable only at 2× = weak (shallow factor); pairs holding signal at 8× = strongest training data.

---

## S3 — reframed corpus accounting (the honest training count)

- Replace the ratio-tier table with a **task-factor table**: per pair, max recoverable k + verdict.
- **New trainable count** = pairs with `recoverable_signal` at the chosen k. This is the real number that replaces the misleading "2–3 training pairs."
- **Deep-pair rescue test (done honestly):** for the 34 that excluded at >40× ratio, do any show `recoverable_signal` at 2–4×? A 300 m → 75 m (4×) task can be recoverable even though 300 m → 2 m is pure hallucination. Report which deep pairs come back, and at what k.
- **Retain the full AUV as the validation/UQ ceiling.** Quantify, per pair, the AUV energy *above* the target band — that's the unrecoverable structure, the per-pair uncertainty target the model should express rather than fabricate.

---

## S4 — QC, report, HOLD

- **Spectral QC plots**: PSD of LR vs HR with the SR band shaded, for the calibration references + a representative spread + every flagged/borderline pair. (Visual QC remains the arbiter; a number near a threshold gets eyeballed.)
- **Calibration sanity**: confirm the 21 validated pairs scored `recoverable_signal` and both references scored low. If not → metric miscalibrated → STOP.
- **Report** `stage_c5_sr_signal_report_2026-06-23.md`: calibration results, per-pair/per-k table, corpus distribution, recommended k, reframed trainable count, the deep-pair rescue result, the per-pair UQ-band quantification.
- **HOLD for assessment**: confirm k and the reframed (factor-based) tiering convention before Stage E re-tiers on it.

---

## Deliverables

1. `stage_c5_sr_signal_sweep.csv` (pair × k × SR-signal × recoverability × verdict)
2. `stage_c5_sr_signal_report_2026-06-23.md` (incl. calibration + recommended k + reframed accounting)
3. spectral QC plots (calibration refs + representative + flagged)
4. updated `staging_state`

## Out of scope

Re-gridding; executing the re-tier (Stage E consumes this); harmonization (Stage F); manifest/OAK writes; Stage-D HR-res derivation (parallel track — feeds the target band; provisional values flagged here). The contamination asymmetry still holds downstream: a Stage-D HR *coarsening* that moves a pair into a higher recoverable-k needs extra scrutiny. The 6 orphan `cal_dig` sub-dirs remain a tracked pre-Stage-G item.
