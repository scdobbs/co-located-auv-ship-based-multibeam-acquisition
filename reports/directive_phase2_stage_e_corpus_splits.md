# Directive — Phase 2 Stage E: corpus finalization + leakage-safe split design

**Date:** 2026-06-23 · **For:** Phase 2 Claude Code execution instance · **After:** Stage C.5c · **Before:** Stage F harmonization.

*Produce the final, deduplicated combined corpus and a set of leakage-safe split designs for Steve to choose from. The factor convention (`target = LR/k`, k=8) replaces the ratio gate. This stage assigns roles and **proposes** splits with their trade-offs — it does **not** pick the split philosophy (that's Steve's call, because it determines what the eval means) and writes no harmonized products or manifest rows.*

---

## Guardrails

- **Design/analysis only.** No harmonization (Stage F), no manifest/OAK writes (Stage G), no training. Splits are proposals; the philosophy choice is held for Steve.
- **The 21 validated pairs are read-only.** Reference them for the combined corpus and leakage graph; never modify them.
- **Recommendations only** on roles and splits. Escalate; assessment/Steve rule.

---

## E1 — dedup reconciliation (front-of-stage; establish the true combined count)

Combined pool = **30 solid + 2 eval-only** (new, from C.5c) + **21 existing validated** (DISCOL, 18 Cal DIG, CCZ, TAG).

Verify disjointness between the new pairs and the 21 by **both** id/site-name and **spatial** match (footprint IoU > 0.8, or containment ≥ 0.9) — confirm A.6's dedup held all the way through Stage C and no seed site re-entered (the MV1405 pattern). Report any overlap (expect ~0 if A.6 held), then produce the **final disjoint combined corpus** and its true count. This is the honest "~50" headline — not 30 + 21 assumed disjoint.

---

## E2 — role assignment under the factor convention

Per pair, assign `role ∈ {train_eligible, eval_only}`:
- The 2 `near_circular_weak` pairs (`NA090×31212`, `TN159×21981`) → `eval_only` (insufficient SR signal).
- The 21 existing keep their established roles.
- All others with `recoverable_signal` → `train_eligible`.

Record per pair: max recoverable k, **UQ target (m RMS + scale)**, morphology class, depth, `geo_cluster`, LR source/cruise. No ratio bands (superseded by the factor convention).

---

## E3 — leakage graph (the hard split constraints)

- **geo_cluster:** map every combined pair to a cluster (recompute/confirm). Flag clusters where the 50 km radius may bundle *distinct* features (the standing caveat) — these may need manual subdivision.
- **shared-LR couples:** build the LR-sharing graph — the 15 multi-HR cruises (`TN268`→5, `2010_Amundsen`, `TN159`→3, `NR07-1`→{31813,31814}, etc.) plus any LR shared across the 21. Pairs sharing an LR survey **must stay on the same split side** (LR leakage).
- **Atomic leakage units** = connected components of (`geo_cluster` ∪ `shared-LR`). These are indivisible — a unit goes wholly to one split side. Report the units and their sizes; a few large units on a ~50-pair corpus is the central split-design tension.

---

## E4 — diversity characterization (input to the philosophy choice)

Tag each pair by morphology (continental_margin / abyssal_plain / hydrothermal_vent / nodule_plain / arctic_shelf / seamount), depth, factor, UQ. Report the corpus distribution across **morphology × geography × factor**, and flag concentrations explicitly:
- the `cluster_000` concentration;
- the **abyssal self-similar skew** from the 24 deep rescues — the training distribution may over-represent cleanly-red abyssal terrain and under-represent the structured morphology (channels, dunes, vents) the model most needs to generalize to. This is the diversity question, and it matters more than the headcount.

Note which morphologies are too thin to both train *and* test (a class with 2 pairs can't be split).

---

## E5 — proposed splits (2–3 options; HOLD — do not pick)

Build splits that satisfy E3 (whole leakage-units on one side) and report what each spans (E4). Propose:

- **Option A — in-distribution** (leakage-safe random, morphology-stratified, ~70/15/15): tests in-distribution SR; spends the corpus efficiently.
- **Option B — generalization** (hold out a whole morphology class or region as test): measures generalization to unseen terrain — the stronger scientific claim, but it spends scarce pairs and leaves a held-out morphology untrained. Note exactly what's sacrificed.
- **Option C — held-out by factor/depth** (if the distribution supports it): train on one factor/depth range, test extrapolation to another.

For each option report: split sizes, per-split morphology/geography/factor coverage, **leakage-safety verification** (no shared-LR survey and no geo_cluster crosses a split boundary), and the scientific claim it supports. **Present all; pick none** — the philosophy is Steve's decision.

---

## E6 — report + HOLD

Write `stage_e_corpus_and_splits_2026-06-23.md`: final disjoint count, role assignment, leakage units, diversity characterization (with the abyssal-skew + cluster_000 flags), and the 2–3 proposed splits with trade-offs.

**HOLD for Steve** to choose the split philosophy before Stage F harmonizes the finalized corpus.

---

## Deliverables

1. `combined_corpus.csv` (final disjoint pairs: role, k, UQ, morphology, depth, geo_cluster, LR source)
2. `leakage_units.csv` (atomic units + members)
3. `proposed_splits.json` (Options A/B/C with coverage + leakage verification)
4. `stage_e_corpus_and_splits_2026-06-23.md`
5. updated `staging_state`

## Out of scope

Harmonization (Stage F), manifest/OAK append (Stage G), model training, Stage-D HR-res derivation (parallel — refines the factor/UQ for `ok_finer_verify` pairs but doesn't gate the split, which is grid-based; carry provisional flags). Tracked carry-overs: the 3 residual co-reg failures (manual pass), the per-tile-LR-coverage fix for multi-tile HR, the discovery-engine footprint-bbox gate before next harvest, and the 6 orphan `cal_dig` sub-dirs before Stage G.
