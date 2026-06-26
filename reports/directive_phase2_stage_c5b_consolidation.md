# Directive — Phase 2 Stage C.5b: consolidation (finer-grid re-run + independence re-check + failure triage)

**Date:** 2026-06-23 · **For:** Phase 2 Claude Code execution instance · **After:** Stage C.5 sweep · **Before:** Stage E re-tier.

*The C.5 reframe is validated and the corpus is far healthier than the ratio gate suggested — but three things must be resolved before "33 trainable" feeds the split. (A) The k-distribution was identical at 2×/4×/8× because the LR/16 analysis grid was Nyquist-limited at the 8× target — so **8× was never independently measured**, and the UQ ceiling came out spuriously ~0. (B) Three `circular_leak` pairs need an independence check — the anti-circularity guardrail firing. (C) Twelve co-registration failures conflate fixable-CRS with false pairs. This stage produces a **confirmed trainable count at a confirmed k**.*

**Working decision carried in:** k = 4 is the defensible floor until the re-run shows whether 8× is real. Analysis only — no re-tier executed.

---

## Guardrails

- **Analysis only.** "Re-grid" here means the *spectral analysis grid*, not the LR products. No re-tier, no manifest/OAK writes, no harmonization.
- **Re-calibrate on the finer grid — don't assume the LR/16 thresholds transfer.** Slope/coherence cut-points may shift with grid resolution; the metric is only trustworthy if it re-separates the known references at the new resolution.
- **QC plots are the arbiter** — the per-k recoverable-energy *curves* are the thing to eyeball; a flat curve and a declining curve mean very different things.
- **Recommendations only** on exclusions (the 3 leaks, the false pairs). Escalate; Steve/assessment rule.

---

## Track A — finer-grid spectral re-run (make k a real measurement)

**A1 — analysis grid at AUV-native resolution.** For each valid pair, put HR at its native cell and LR upsampled to the same grid, over the **HR∩LR∩footprint data intersection** (not the inflated footprint). This represents the full band from LR down to AUV, so any k *and* the UQ ceiling above any k are genuinely resolvable — unlike the LR/16 grid that capped at 8×. (For `ok_finer_verify`/NaN-res HR, use the A.6-measured cell as the grid resolution; flag provisional.)

**A2 — re-calibrate.** Re-run S0 (21 validated pairs + synthetic white-roughness + synthetic circular) at the finer resolution; re-derive the slope and edge-coherence thresholds. Confirm the metric still separates known-recoverable from both unrecoverable references. **If it doesn't separate at the finer grid, STOP** — the result isn't trustworthy.

**A3 — per-pair recoverable-energy *curve* (not a binary).** Report recoverable signal as a function of k across {2, 4, 8, 16, … up to the AUV-native limit}. The decisive question: does recoverable signal **decline with k** (real factor-dependence → locates an honest knee) or **stay flat and high** (genuinely self-similar red structure → 8×+ really does hold)? Either answer is informative — but the original flat 33/33/33 was at least partly a grid artifact, so this is the test of whether the invariance survives once k is actually resolved. Also report whether the metric tracks *factor-specific recoverable energy* vs merely "is this red-spectrum at all" (if every natural grid passes identically, the metric is keying on redness, not recoverability — flag that).

**A4 — UQ ceiling (now measurable).** Per pair, the AUV energy *above* the chosen-k target band = the unrecoverable structure / per-pair uncertainty target. On the finer grid this should be non-zero (the ~0 in C.5 was the Nyquist artifact). This is what the model must express as uncertainty rather than fabricate.

**A5 — confirmed k.** From the curves, the defensible k is the knee where recoverable signal is still strong and structured. Report it (may be 4, 8, or higher) as a recommendation; assessment confirms.

---

## Track B — independence re-check (the 3 `circular_leak` pairs)

For `FK160407×MGDS:7832`, `NA090×MGDS:31212`, `TN268×MGDS:30466`:

**B1** — trace the **LR provenance**. Is the ship LR a genuinely independent single-cruise raw acquisition, or a composite/processed product that could have ingested the AUV (the GEBCO/GMRT/USGS-composite circularity)? Check the NCEI source lineage: per-cruise raw vs compilation.

**B2** — verdict per pair: `independent` (high edge-coherence is real co-located structure — keep, but note why coherence is high) vs `leaked` (composite or AUV-ingesting → **exclude**, anti-circularity).

**B3** — **don't assume isolated.** If a leak traces to a discovery-screen gap (a composite that should have been caught), check whether other corpus pairs draw on the same LR source. A hole that admitted three may have admitted more.

Recommendation only — exclude pending ruling (same posture as `31600`).

---

## Track C — failure triage (the 12 co-registration failures)

Split the 12 into two piles — they are not one bucket:

- **Fixable CRS/raster** (the A.6 CRS fragility — `hr_unreadable`, GMT-convert, catalog-CRS): fix and re-run through Track A. The 5 `hr_unreadable` (`2010_Amundsen×31753`, `EW9801×31425`, `KIWI10RR×24499`, `RB1604×24756`, `TN268×32556`) get the materialization fix; if HR still won't render, flag manual.
- **False pairs** (inflated-footprint / genuine no-overlap — the AT18-11 / 2°-footprint pattern): **exclude.** Apply the **footprint-size sanity check** — an AUV footprint is km-scale; a degrees-wide footprint is inflated geometry, not a co-registration bug. For the 7 `empty/no_overlap`, distinguish CRS-misalignment-masquerading-as-no-overlap (fix) from genuine no-overlap (exclude).
- **Priority:** `2009_Amundsen×30045` — our one Arctic single-HR pair, diversity-critical. Determine specifically whether it's a fixable CRS issue or a genuine no-overlap, and report which.

---

## Report + HOLD

Write `stage_c5b_consolidation_report_2026-06-23.md`:
- re-calibration result at the finer grid;
- per-pair recoverable-energy curves + the **confirmed k** (and whether the flat distribution survived);
- UQ ceiling per pair (now non-zero);
- independence verdicts on the 3 leaks;
- failure triage table (fixed-and-rescored vs excluded-false-pair, with `2009_Amundsen×30045` called out);
- the **confirmed trainable count at the confirmed k** = 33 − leaks − false-pairs + rescued-failures.

**HOLD for assessment** — confirm k and the final trainable count and the factor-based convention before Stage E re-tiers on them.

---

## Deliverables

1. updated `stage_c5_sr_signal_sweep.csv` (per-k recoverable-energy curves)
2. `stage_c5b_consolidation_report_2026-06-23.md` + re-calibration record
3. independence findings (3 pairs) + failure triage table (12 pairs)
4. QC plots — the per-k curves especially
5. updated `staging_state`

## Out of scope

Stage E re-tier, harmonization (Stage F), manifest/OAK writes, Stage-D HR-res derivation (parallel — still feeds the target band; provisional flags carry). The contamination asymmetry holds downstream. The 6 orphan `cal_dig` sub-dirs remain a tracked pre-Stage-G item.
