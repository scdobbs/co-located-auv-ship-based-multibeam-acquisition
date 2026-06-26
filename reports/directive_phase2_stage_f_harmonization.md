# Directive — Phase 2 Stage F: harmonization + co-registration + QA (Option A corpus)

**Date:** 2026-06-23 · **For:** Phase 2 Claude Code execution instance · **After:** Stage E (Option A chosen) · **Before:** Stage G manifest append.

*Harmonize the finalized corpus under the Option A (in-distribution, margin-scoped) split. The 53 combined pairs = 21 validated (already harmonized, **untouchable**) + 32 new — so this stage harmonizes **the 32 new pairs only**. It also folds in the cleanups we've been carrying, since harmonization touches every pair anyway. Holds before Stage G writes anything to the manifest.*

**Scope confirmed by Steve:** Option A, margin-focused — the corpus is 74 % continental margin and that's the intended target (canyons, channels, gullies are the morphology of interest). The diversity limitation is recorded as a stated scope, not a blocker.

---

## Guardrails

- **Harmonize the 32 new pairs only.** The 21 validated (DISCOL, 18 Cal DIG, CCZ, TAG) are **read-only** — already harmonized, never re-processed.
- **Never nearest-neighbour resample.** Single-warp reproject to per-pair local UTM with area-weighted resampling; skip the reproject entirely if the CRS already matches.
- **Clip to the true HR∩LR data intersection**, not a bbox.
- **QGIS visual QC is the arbiter** — it overrides the metrics on any disagreement.
- **Append-only.** New harmonized products + a new dated QA report. **No manifest/OAK writes** (Stage G). Split-role metadata travels with each pair.
- **Escalate** `needs_review` and `reject` pairs — don't advance them silently.

---

## F0 — margin-stratified test-set check (tighten Option A)

Option A keeps whole leakage units on one side (verified in E), but with test = 8 on a margin-dominated corpus, the test set has to span **different margin settings** from training to measure margin generalization rather than memorization-adjacent performance.

- Confirm the 8 Option-A test pairs span distinct margin sub-types (canyon / channel / slope / gully / drift / pockmark) and aren't character-adjacent to their training neighbours.
- If the test set clusters with training, **re-draw within the leakage constraints** to stratify across margin sub-types (no shared-LR or geo_cluster may cross). Report the final test set's sub-type spread.

---

## F1 — per-pair harmonization (the 32 new)

For each new pair:
1. **Single-warp reproject** HR & LR to the pair's local UTM (area-weighted; skip if CRS matches). Never nearest.
2. **Clip** both to the HR∩LR data intersection.
3. **Fresh co-registration** (sub-pixel HR↔LR alignment).
4. **Multi-tile HR fix:** for multi-tile AUV HR, select/merge the tiles with **actual LR coverage** (the `2009_Amundsen×30045` lesson — not the largest-tile heuristic).

---

## F2 — v1.1 §A QA (per pair)

Run the established QA: offset-magnitude flag, NCC peak sharpness (PSR), anisotropy (`eig_ratio`), and a per-pair hillshade overlay. Assign `status ∈ {auto_pass, needs_review, reject}`. QGIS visual inspection is the arbiter on any metric/visual disagreement — a clean metric does not pass a bad-looking overlay, and vice versa.

---

## F3 — folded-in cleanups (do these while each pair is open)

- **Stage D native-res:** for the `ok_finer_verify` pairs that survived into the 53 (e.g. `21415`), derive and write the **sounding-density** native resolution (not grid posting). Flag if the corrected value changes the pair's k or UQ.
- **3 residual co-reg failures** (`RB1604×24756`, `TN157×21996`, `TN159×21998`): manual co-registration pass — resolve, or flag for exclusion with reason.
- Record, per pair, final native res + k + UQ (m RMS + scale) + split role + morphology.

---

## F4 — completeness, report, HOLD

- **Accounting:** the 32 new == `auto_pass` + `needs_review` + `reject`, no limbo. The 21 validated unchanged.
- Write `stage_f_harmonization_2026-06-23.md`: per-pair harmonization + QA status, the margin-stratified test set, the Stage-D native-res corrections, the residual-failure resolutions, and the final analysis-ready corpus (with split roles).
- **HOLD for assessment** review of all `needs_review` and `reject` pairs before Stage G appends to the manifest.

**Post-F note (tracked, not an action here):** per the Gate-1 retention policy, a cruise's raw becomes purge-eligible once its pair clears F QC and parameters are final — but the purge is a separate confirmed action, never automatic in this stage.

---

## Deliverables

1. harmonized 32 new pairs (`$DATA_ROOT/harmonized/…`, matching the existing structure)
2. v1.1 §A QA report + per-pair hillshade overlays
3. updated `combined_corpus.csv` (final native res / k / UQ / role / QA status)
4. `stage_f_harmonization_2026-06-23.md`
5. updated `staging_state`

## Out of scope

Manifest/OAK append (Stage G), model training, re-harmonizing the 21 (untouchable), the discovery footprint-bbox gate (next harvest). The 6 orphan `cal_dig` sub-dirs must be reconciled before Stage G (tracked).
