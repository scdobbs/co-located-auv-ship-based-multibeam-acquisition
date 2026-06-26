# Phase 2 — Stage C.5c final consolidation report

**Date:** 2026-06-23 · **Author:** Claude Code execution instance (Sherlock)
**Directive:** `reports/directive_phase2_stage_c5c_consolidation.md`
**Status:** ⛔ **HOLD for assessment** — confirm the final count, k, and UQ framing before Stage E. Analysis only.

**Artifacts**
- `reports/stage_c5_sr_signal_sweep.csv` (rescored + per-k + UQ-in-metres), `reports/discovery/stage_c5b_sweep.json`
- Code: `src/discovery/stage_c5_{spectral,sweep}.py`

---

## 1. Headline — final count for Stage E

| | |
|---|---|
| **Recoverable structure at k=8** | **32 pairs** |
| of which `near_circular_weak` (HR≈LR → eval-only) | 2 |
| **Solid training pairs (k=8)** | **30** |
| Deep-pair rescues from the ratio gate | 24 |
| **UQ target (unrecoverable fine relief)** | **~1.0 m RMS** (median; 0.04–12.5 m) at ~4–6 m scales |

The C.5/C.5b reframe is now closed: a **factor-8× SR task above each pair's own LR** yields **30 solid training pairs + 2 eval-only**, with a *physical* uncertainty target of ~1 m of fine relief — versus the ratio gate's "2–3 training pairs."

---

## 2. Track A — render + rescore the fixable failures → final count

**A1 — the "fixable 6" were a raster-format bug, now fixed.** They are GMT-**v6 COARDS** NetCDF `.grd` (1-D x,y + 2-D z) that `is_gmt_grd` (GMT-classic only) and rasterio (no geotransform) both rejected. Added a COARDS reader + a clean GTiff profile + a "diff/interp"-grid filter (one HR was selecting a *difference* product by the largest-size heuristic). Rescored: **`EW9801×31425`, `KIWI10RR×24499`, `2010_Amundsen×31753` now score** (KIWI10RR recoverable to k=32). Three remain co-registration failures (`RB1604×24756`, `TN157×21996`, `TN159×21998`) — residual LR-coverage/CRS edge cases, recommended for a manual pass (not blocking).

**A2 — `2009_Amundsen×30045` rescued (priority Arctic pair).** Root cause confirmed: the HR is 5 dive-tiles and the largest-tile heuristic picked `Scar_w_Headwall_715.tif`, which sits where the **LR subset has no data** (lrcov = 0.00). Per-tile scoring shows **4 of the 5 tiles have full LR coverage and score `recoverable_signal` at k=8.** The only Arctic single-HR pair is **kept** (recoverable). The general fix for the full run is to select the HR tile with actual LR coverage, not the largest.

**A3 — final count: 32** = 29 (C.5b) + 2 rescored fixable + 1 Arctic; **30 solid** after the Track-B eval-only demotions.

---

## 3. Track B — SR-signal *sufficiency* of the coherence pairs (corrected check)

The real risk for a high-coherence pair is **HR ≈ LR** (the AUV adds little *new* structure → insufficient SR signal, a sub-5 "nothing to super-resolve" case — **not** hallucination). Measured the **new HR SR-band energy beyond the LR** (RMS, metres), separate from coherence:

| pair | edge coh | HR SR-RMS | LR SR-RMS | new ≈ | verdict |
|---|---|---|---|---|---|
| TN159×21986 | 0.94 | 30.1 m | 3.5 m | **29.9 m** | **solid** |
| EW9801×31425 | 0.23 | 9.9 m | 8.5 m | 5.0 m | solid |
| FK160407×7832 | 0.78 | 4.2 m | 2.7 m | 3.2 m | solid |
| RC2511×32240 | 0.17 | 3.1 m | 1.5 m | 2.7 m | solid |
| TN399×30373 | 0.82 | 1.3 m | 0.7 m | 1.1 m | solid |
| **NA090×31212** | 0.23 | 1.57 m | 1.65 m | **~0 m** | **near_circular_weak** |
| **TN159×21981** | 0.32 | 3.79 m | 6.95 m | **~0 m** | **near_circular_weak** |

**5 solid** (substantial new fine structure — note `TN159×21986`: high coherence *and* ~30 m new detail → a high-relief site, not circular). **2 near_circular_weak** (`NA090×31212`, `TN159×21981`: HR≈LR, no new SR signal) → **recommend eval-only or exclude.** The magnitude check correctly separates rich-high-coherence from HR≈LR.

---

## 4. Track C — UQ ceiling in physical units (the honest answer)

C.5b's "0–2 % of energy above the k=8 target" reads as "negligible," but red spectra concentrate energy at long wavelengths — the wrong yardstick. Expressed in **metres**:

- **Unrecoverable fine structure (finer than the k=8 target): ~1.0 m RMS** (median across 30 trainable pairs; range **0.04–12.5 m**), at characteristic scales of **~4–6 m**.
- **Verdict: energy-small-but-feature-relevant.** ~1 m of fine relief (up to ~12 m at high-relief vent/scarp sites) is **morphologically real** — sub-target channels, scours, and vent structure live in this band. It is *not* negligible.
- **UQ-target framing for the model:** "express ±~1 m of unpredictable fine relief at ~4–6 m scales" (more at rough sites) — the calibrated-uncertainty deliverable. "2 % of energy" would have mis-set this to zero.

---

## 5. Tracked — discovery-engine footprint bug (record, not actioned)

The 5 inflated false pairs (`Channel×31949`, `EX1103×{31811,18210}`, `TN365×31193`, `TN268×32556`) are the **third** appearance of bbox-as-footprint (after AT18-11 and the pilot bbox). The discovery engine's footprint derivation admits degrees-wide bbox-as-footprint; an AUV footprint is km-scale. **Recorded in `staging_state` (`DISCOVERY_ENGINE_BUG_footprint_bbox`); fix at source with a footprint-size sanity gate before any future harvest.**

---

## 6. Recommendation + HOLD

**HOLD for assessment** before Stage E:
1. **Final count: 30 solid training + 2 eval-only at k=8** (incl. the rescued Arctic `30045`). Confirm.
2. **Demote `NA090×31212` and `TN159×21981` to eval-only** (HR≈LR, insufficient SR signal).
3. **UQ target = ~1 m fine relief** (feature-relevant, not negligible) — confirm this framing for the model's calibrated uncertainty.
4. Residual: 3 co-reg failures for a manual pass; the per-tile-LR-coverage fix for multi-tile HR in the full run; the discovery footprint-gate before next harvest.

## Deliverables
1. `stage_c5_sr_signal_sweep.csv` (rescored + per-k + UQ-metres) + `stage_c5b_sweep.json`
2. this report
3. updated `staging_state` (final count + discovery-engine bug)
