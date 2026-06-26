# Phase 2 — Stage E: corpus finalization + leakage-safe split design

**Date:** 2026-06-23 · **Author:** Claude Code execution instance (Sherlock)
**Directive:** `reports/directive_phase2_stage_e_corpus_splits.md`
**Status:** ⛔ **HOLD for Steve** to choose the split *philosophy* before Stage F. Design only — proposes splits, picks none; no harmonization, no manifest writes.

**Artifacts**
- `reports/combined_corpus.csv` (53 disjoint pairs: role, k, UQ, morphology, depth, geo_cluster, LR source)
- `reports/discovery/leakage_units.csv` (24 atomic units + members)
- `reports/discovery/proposed_splits.json` (Options A/B/C + coverage + leakage verification)
- Code: `src/discovery/stage_e_splits.py`

---

## 1. E1 — final disjoint combined corpus: **53 pairs**

| | |
|---|---|
| New (C.5c) | 32 |
| Validated (DISCOL, 18 Cal DIG, CCZ, TAG) | 21 |
| **Spatial dups (IoU > 0.8 / containment ≥ 0.9)** | **0** |
| **Final disjoint combined corpus** | **53** |

A.6's dedup held all the way through Stage C — **no seed site re-entered**; the new 32 and the 21 are fully disjoint by both id and footprint. The honest headline is **53**, not "30 + 21 assumed disjoint."

## 2. E2 — roles (factor convention, k = 8)

**51 `train_eligible` + 2 `eval_only`.** The 2 eval-only are the C.5c `near_circular_weak` pairs (`NA090×MGDS:31212`, `TN159×MGDS:21981` — HR ≈ LR, insufficient new SR signal). Per pair, `combined_corpus.csv` records max-k, **UQ (m RMS + scale)**, morphology, depth, geo_cluster, LR source. No ratio bands (superseded).

*Nuance:* `eval_only` is a per-pair training-exclusion, orthogonal to the split side. `TN159×21981` shares the TN159 LR with the *solid* `TN159×21986`, so they are one leakage unit and cannot be separated — wherever that unit lands, `21981` is simply excluded from training.

## 3. E3 — leakage graph (the hard constraints)

**24 atomic leakage units** = connected components of (geo_cluster@50 km ∪ shared-LR). Largest unit sizes: **18, 6, 4, 2, 2, 2** — the rest are singletons.

- **The 18-pair unit is all of Cal DIG (Morro Bay)** — bound by a **shared "Cal DIG I" mosaic LR** *and* 50 km co-location. It is genuinely indivisible (this is the `cluster_000` analog). **Cal DIG is 34 % of the corpus and goes wholly to one split side** — the central split-design tension.
- The 15 multi-HR cruises (`TN268`→5, `2010_Amundsen`, `TN159`→3, etc.) form the smaller units (6/4/2) — pairs sharing an LR survey are kept together (LR leakage).
- No 50 km cluster bundles obviously-distinct features beyond what shared-LR already binds; the dominant constraint is shared-LR, not geographic proximity.

## 4. E4 — diversity (the part that matters more than headcount)

| morphology | n | note |
|---|---|---|
| continental_margin | **39 (74 %)** | incl. the 18-pair Cal DIG block + the deep-slope rescues |
| hydrothermal_vent | 8 | the main structured non-margin class |
| abyssal_plain | 2 | DISCOL + 1 |
| shelf_slope | 2 | |
| seamount | 1 | too thin to both train and test |
| nodule_plain | 1 | CCZ — too thin |

**The corpus is heavily continental-margin-dominated (74 %).** The directive's worry was an abyssal self-similar skew from the 24 deep rescues; in practice those rescues are mostly **deep-slope/rise (2.5–3.5 km), classified margin** — so the skew is toward *continental margin*, not abyssal plain. **Flags:**
- **Margin over-representation** (Cal DIG + deep-slope) — the training distribution may over-represent margin terrain.
- **Vents (8)** are the only substantial structured-terrain class; **abyssal / nodule / seamount / arctic are 1–2 each** — too thin to both train and test. A model needing to generalize to channels/dunes/vents has thin support outside vents.
- 24 of 53 are deep-rescue pairs (recovered from the ratio gate) — these *add* deep-slope coverage but reinforce the margin skew.

## 5. E5 — proposed splits (all leakage-safe; **pick none — Steve's call**)

All three assign **whole leakage units to one side** (verified: no shared-LR survey and no geo_cluster crosses a boundary).

### Option A — in-distribution (~70/15/15)
- **train 37 / val 8 / test 8.** Test spans margin(4)/vent(2)/seamount/abyssal; both eval-only in val/test.
- **Claim:** in-distribution SR performance; spends the corpus efficiently. The default if the goal is "does the model super-resolve real co-located pairs."

### Option B — generalization (hold out all vents as test)
- **train 44 / test 9** (test = 8 vents + 1 margin).
- **Claim:** generalization to the *structured vent terrain* the model most needs. **Sacrifice:** no vent in training and no in-distribution vent eval (only 8 vents exist) — a strong claim bought with the scarcest structured class.

### Option C — held-out by depth (train < 2.5 km, test ≥ 2.5 km)
- **train 43 / test 10** (test = deep: abyssal/nodule/seamount/deep-margin).
- **Claim:** depth/factor *extrapolation* (shallow→deep). Aligns with the deep-rescue question — can a margin-trained model handle abyssal factors. Both eval-only fall in train (they're shallow).

| | sizes | tests | main cost |
|---|---|---|---|
| A in-distribution | 37/8/8 | in-distribution SR | none (efficient) |
| B hold-out vents | 44/—/9 | generalize to vents | no vent training/eval |
| C by depth | 43/—/10 | depth extrapolation | deep terrain untrained |

---

## 6. Recommendation + HOLD

**HOLD for Steve** to choose the split philosophy — it determines what the eval *means*:
- **A** if the claim is in-distribution SR on real pairs;
- **B** if the claim is generalization to structured (vent) terrain — the strongest scientific claim, at the cost of the scarce vent class;
- **C** if the claim is depth/factor extrapolation (the deep-rescue question).

Whichever is chosen, the **margin-dominance and thin structured classes (§4)** are the real limitation — flag for the SR effort that the validation set is margin-heavy and vent-light. Tracked carry-overs unchanged (3 co-reg failures, per-tile multi-tile-HR fix, discovery footprint-bbox gate, 6 orphan cal_dig sub-dirs before Stage G).

## Deliverables
1. `combined_corpus.csv` (53), `leakage_units.csv` (24), `proposed_splits.json` (A/B/C)
2. this report
3. updated `staging_state`
