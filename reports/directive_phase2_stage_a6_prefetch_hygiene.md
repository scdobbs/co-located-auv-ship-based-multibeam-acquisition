# Directive — Phase 2 Stage A.6: pre-fetch hygiene (dedup + footprint census + quality tags)

**Date:** 2026-06-22 · **For:** Phase 2 Claude Code execution instance · **Sits between:** Stage A.5 (subset, done) and Stage B (fetch).

*Stage A.5 surfaced three things that should be resolved corpus-wide **before** any swath fetch, not one at a time at Stage C: (1) the bulk selection re-derived already-validated sites (MV1405 duplicates an untouchable-21 pair — and the 10 `manifest_seed_clean` are the same phenomenon), so duplicates are leaking into the fetch plan; (2) at least one footprint fell back to a bbox, which makes its subset suspect, and we don't know how many others did; (3) three thin-overlap cruises need a quality flag carried into gridding. This stage cleans all three. Non-destructive — footprint/list operations only, no swath fetched, no manifest touched.*

---

## Guardrails

- **No swath fetch** (Stage B, post-gate). This stage only builds footprints and list/geometry operations.
- **Recommendations only.** Produce a *proposed* cleaned fetch list + a dropped-duplicate list for sign-off. Execute no manifest change and re-open no validated pair — the untouchable 21 are **read-only and authoritative**.
- **True valid-data footprint, never bbox.** Where a bbox was used, say so explicitly (that's Step 4's whole point).
- **Over-include at the margin; escalate, don't absorb.**

---

## Step 1 — Footprints for all 81 clean HR

Reuse the 24 polygons from A.5; build the remaining ~57 (same decimated-read valid-polygon logic, resolved/recovered CRS). For each HR record `footprint_type ∈ {valid_polygon, bbox_fallback}` and the CRS source. This single pass feeds both the dedup (Step 2) and the census (Step 4).

---

## Step 2 — Duplicate sweep against the untouchable 21

For every Phase-2 HR, test for duplication of a manifest pair's HR by **both**:
- **id / site-name match** (catches the `tag_m127` + 9 `cal_dig_morro_bay__*` seeds and the MV1405→`PockmarkNorth` case), and
- **spatial match** — footprint IoU > 0.8, or one footprint contains ≥ 0.9 of the other (catches a same-survey re-derivation filed under a different id).

Tag each hit with the manifest row it duplicates. The 10 `manifest_seed_clean` are *expected* hits; report the **total**, which will be ≥ 10 + any MV1405-type cases not previously caught. Rule: one pair per distinct HR, and the manifest is authoritative → **recommend dropping every duplicate HR from Phase-2 processing.** (We are not re-opening validated pairs to compare LRs; that's a separate manual call if ever wanted.)

---

## Step 3 — Recompute live-HR-per-cruise → cleaned Stage-B fetch list

For each of the 55 cruises, compute `live_HR(cruise)` = served HR **minus** {dropped (`30272/20836/24425`), Step-2 duplicates, quarantined `31600`}.

- `live_HR` empty → **drop the cruise** from the fetch (this re-derives RR0916's exclusion and will catch any cruise serving *only* duplicates).
- `live_HR` reduced (multi-HR cruise losing some HR) → **re-subset** that cruise against the **live-HR footprint union only** (for the ≥10 GB targets; small cruises just keep/drop). A cruise's fetch must be justified only by HR that will actually be paired.

Emit the cleaned `stage_b_fetch_list_2026-06-22.csv`: cruise, live_HR, fetch_mode (`subset`/`whole`), intersecting files (for subset), subset_GB. Report the revised total (slightly below 147 after duplicate drops) and the corrected **new-HR count** (81 − duplicates; the true count of HR Phase 2 will actually pair).

---

## Step 4 — Bbox-footprint census

From Step 1, report `footprint_type` across all 81, and **list every cruise still in the cleaned fetch list whose live-HR footprint is `bbox_fallback`.** A subset computed against a bbox is selecting files against a rectangle, not the real footprint — unreliable. For each such cruise:
- recommend **fix-geometry-then-resubset** (re-derive the valid polygon; this overlaps the CRS-recovered and `ok_finer_verify` grids, which are likeliest to fail polygonization — cross-reference them), **or**
- if the geometry can't be recovered, **fetch whole** for that cruise (conservative) and resolve at Stage C with QGIS.

If MV1405 is the only bbox case (and it's being dropped), this census closes clean — but confirm that rather than assume it.

---

## Step 5 — Thin-overlap quality tags (carry into Stage C)

Tag cruises with `fraction_kept ≤ 0.02` **and** edge geometry — `TN299` (0.011), `NA080` (0.014), `TN399` (0.008) — as `lr_coverage_quality_watch`. These are legitimate keep-subset, but the AUV patch clips the edge of a large deep survey, where ship coverage is outer-beam (high incidence, sparse, noisy). **This is a Stage-C check, not an action:** at gridding, confirm the soundings over the HR footprint are adequate-density near-nadir coverage, not outer-swath grazing. If edge-only, the LR over the footprint may be too poor to pair regardless of ratio — a candidate Stage-C exclusion. Tag, don't drop.

---

## Step 6 — Report + revised Gate 1 + HOLD

Write `stage_a6_prefetch_hygiene_2026-06-22.md`: total duplicates (with manifest rows), the cleaned fetch list + revised budget + corrected new-HR count, the bbox census, the quality tags. Re-present **Gate 1** to Steve with the cleaned numbers (Q1 storage — even smaller; Q2 retention — unchanged, still pending, **plus the non-purge home for validated outputs**; and the A.5 per-cruise rulings, now with the duplicate drops folded in).

**HOLD.** No Stage B until Steve signs off on the cleaned fetch list, retention + output home, and the rulings.

---

## Deliverables

1. `stage_b_fetch_list_2026-06-22.csv` (cleaned, deduplicated, geometry-checked)
2. `stage_a6_prefetch_hygiene_2026-06-22.md`
3. updated footprint layer (all 81, with `footprint_type`) — Stage C reuses it
4. duplicate list (Phase-2 HR → manifest row it duplicates)

## Out of scope

Swath fetch (Stage B), gridding (Stage C), any manifest write or re-opening of the 21, the retention decision (Steve's). The `ok_finer_verify` native_res re-derivation stays Stage D — but if fixing a bbox footprint here happens to re-derive a grid's geometry, record it for Stage D rather than discarding.
