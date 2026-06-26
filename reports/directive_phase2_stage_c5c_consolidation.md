# Directive — Phase 2 Stage C.5c: final consolidation before Stage E

**Date:** 2026-06-23 · **For:** Phase 2 Claude Code execution instance · **After:** Stage C.5b · **Before:** Stage E re-tier.

*Close the three caveats C.5b left open so Stage E inherits a **final count and an honest UQ framing**: (A) render + rescore the 6 fixable rasters and the Arctic per-tile fix → final trainable count; (B) confirm the 6 coherence-flagged pairs carry genuine new SR signal; (C) re-express the UQ ceiling in physical units, not the misleading energy fraction. Reuse the C.5b finer-grid pipeline and recalibrated thresholds — don't re-invent the metric.*

**Confirmed and carried in:** k = 8 (k = 4 conservative); the factor convention (`target = LR/k`) replaces the ratio gate; the 5 inflated pairs are excluded false-positives; working trainable count ≈ 29; all 6 coherence flags are provenance-independent (per-cruise raw, no composites — settled).

---

## Guardrails

- **Analysis only** — reuse the C.5b AUV-native-grid pipeline + recalibrated thresholds. No re-tier, no manifest/OAK writes, no harmonization.
- **Recommendations only** on keep/exclude. Escalate; assessment rules.
- **Don't let a convenient conclusion calcify** — Track C exists because "UQ is small" (in energy) may mislead.

---

## Track A — render + rescore the fixable failures → final count

**A1** — Materialize the 6 fixable HR rasters (the C.5b format/CRS fix): `2010_Amundsen×31753`, `EW9801×31425`, `KIWI10RR×24499`, `RB1604×24756`, `TN157×21996`, `TN159×21998`. Run each through the C.5b spectral pipeline (AUV-native grid, recalibrated thresholds, per-k curve). Report verdict + max recoverable k per pair.

**A2** — `2009_Amundsen×30045` **per-tile fix** (priority — the only Arctic single-HR pair). The HR is 5 dive-tiles; the largest-tile heuristic picked one the LR subset doesn't cover. Co-register per-tile (or over the union of tiles that overlap the LR), grid, and score. Report recoverability + k. Worth the manual effort for the diversity.

**A3** — Updated **final trainable count** = 29 + (rescued from the 6 + 1). State the number Stage E inherits.

---

## Track B — confirm genuine SR signal in the 6 coherence pairs (corrected check)

*Note — corrected framing from the prior directive.* I earlier framed this as "would they score recoverable on slope alone, i.e. is recoverability propped up by coherence." That's the wrong worry: coherence *supporting* recoverability is fine — predictable structure is exactly what makes a pair trainable. The real residual risk is the **opposite end**: very high coherence can mean **HR ≈ LR** (the AUV adds little *new* structure), which drifts toward the circular / insufficient-SR-signal failure (a sub-5 "nothing to super-resolve" case, *not* hallucination). So check SR-signal *sufficiency*, not coherence-independence.

**B1** — For the 6 (`FK160407×7832`, `NA090×31212`, `TN268×30466`, + the 3 flagged only at the finer grid): report the **SR-signal magnitude** — how much *new* HR energy lives in the SR band beyond what the LR already contains — separately from the coherence value.

**B2** — Verdict per pair: `solid` (substantial new SR-band structure → keep as training, no asterisk) vs `near_circular_weak` (high coherence + little new energy → HR≈LR, insufficient SR signal → recommend eval-only or exclude).

**B3** — Independence is already settled (provenance, C.5b); this is purely SR-signal sufficiency. Recommendation only.

---

## Track C — UQ ceiling in physical units (not energy fraction)

The C.5b "0–2 % of energy above the k=8 target" reads as "uncertainty is negligible" — but red spectra concentrate energy at long wavelengths, so a 2 %-*energy* band can still hold the geomorphologically important fine features (channels, scours, vent structure). Energy fraction is the wrong yardstick for the calibrated-UQ goal that motivates the whole project.

**C1** — Per pair, express the unrecoverable band (AUV structure finer than the k=8 target) as **RMS height in metres** and a **characteristic length scale** — physical amplitude, not energy fraction.

**C2** — Where feasible, note what feature classes live in that band (sub-target channels/scarps/vents), for the UQ/diversity framing.

**C3** — Report the honest verdict: is the unrecoverable fine structure **morphologically negligible** (genuinely small in metres) or **energy-small-but-feature-relevant** (small fraction, real features)? This sets the model's UQ target framing — the project needs the physical answer, because "express ±X m of unpredictable relief at Y-m scales" is the calibrated-uncertainty deliverable, and "2 % of energy" is not.

---

## Tracked (record, not an action here)

**Discovery-engine footprint bug.** The 5 inflated false pairs (`Channel×31949`, `EX1103×{31811,18210}`, `TN365×31193`, `TN268×32556`) are the **third** appearance of bbox-as-footprint (after AT18-11 at Stage C and the pilot bbox error). The discovery engine's footprint derivation is admitting bbox-as-footprint and must be **fixed at source before any future harvest**, with a footprint-size sanity gate (an AUV footprint is km-scale; degrees-wide is inflated). Record in `staging_state` for the next discovery cycle — not actioned in this stage.

---

## Report + HOLD

Write `stage_c5c_consolidation_report_2026-06-23.md`: rendered/rescored failures + the **final trainable count** Stage E inherits; the 6 coherence-pair SR-signal verdicts; the UQ ceiling in metres/feature-scale + the honest verdict; the discovery-engine bug note.

**HOLD for assessment** — confirm the final count, k, and the UQ framing before Stage E re-tiers.

## Deliverables

1. updated `stage_c5_sr_signal_sweep.csv` (rescored failures + 6 SR-signal magnitudes + UQ-in-metres)
2. `stage_c5c_consolidation_report_2026-06-23.md`
3. updated `staging_state` (final count, discovery-engine bug recorded)

## Out of scope

Stage E re-tier, harmonization (Stage F), manifest/OAK writes, Stage-D HR-res derivation (parallel; provisional flags carry). The 6 orphan `cal_dig` sub-dirs remain a tracked pre-Stage-G item.
