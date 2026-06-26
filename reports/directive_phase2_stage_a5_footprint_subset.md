# Directive — Phase 2 Stage A.5: nav-first footprint subsetting for large raw-LR cruises

**Date:** 2026-06-22 · **For:** Phase 2 Claude Code execution instance · **Sits between:** Stage A (dry-run, done) and Stage B (fetch).

*The Stage-A dry-run returned 865 GB with 58 % concentrated in two Arctic Amundsen cruises. Rather than fetch whole cruises or reflexively exclude, this stage fetches **nav only** for the large cruises, intersects each cruise track with its HR footprint(s), and determines per-cruise whether to **keep-subset** (fetch only the swath files crossing the footprint) or **exclude** (transit false-pair, confirmed by evidence). It also produces the footprint geometry Stage C's independence/footprint review needs anyway. Gate 1 stays held; this refines the numbers feeding it.*

---

## Guardrails

- **NAV ONLY.** Fetch per-file nav (`.fnv`, or a nav fallback). **No swath bulk fetch** — that is Stage B, post-gate.
- **Recommendations only.** Produce per-cruise verdicts; **execute no exclusions and no fetch decisions.** Steve/assessment rule.
- **True valid-data footprint, never bbox.** Join on real polygons.
- **Over-include at the margin.** When in doubt, buffer generously and keep a file — Stage C gridding + HR∩LR clip removes excess; a missed line is unrecoverable.
- **Idempotent / cached / append-only.** Cache nav + listings; re-runs must not re-fetch.
- **Escalate, don't absorb.** Anything that can't be resolved (missing nav, ambiguous overlap) is flagged, not guessed.

---

## Step 1 — Target set

From `stage_a_raw_lr_sizes_2026-06-22.csv`, select cruises with `whole_GB ≥ THRESHOLD_GB` (default **10**; parameter, adjustable). That is the **14 large cruises** (2 over 100 GB incl. both Amundsen, 12 in 10–100 GB). The **41 cruises < 10 GB** are **not** subset — they fetch whole in Stage B (subsetting overhead isn't worth it for small cruises). List the 14 with `whole_GB` and HR served.

---

## Step 2 — Build HR footprints (per cruise)

1. For each target cruise, gather its served HR from the `n_hr_served` mapping in `staging_state` (multi-HR cruises: `TN268`→5, `2010_Amundsen`→3 live after the `30272` drop, `TN159`→3, etc.).
2. For each served HR grid (staged under `staging_phase1/`), compute the **true valid-data footprint polygon** — polygonize the non-nodata region (or a concave hull of valid cells), **not** the bbox.
3. **Union** the served-HR footprints per cruise (a cruise serving 5 HR keeps files crossing *any* of the 5).
4. Reproject footprints to a common geographic CRS for intersection. **Buffer outward** by `max(2 × local_water_depth, 1 km)` to capture LR swath coverage around the patch — a surface ship's swath covers the footprint without passing directly over it. Record the buffer used per cruise.

---

## Step 3 — Fetch nav only

For each target cruise, fetch its **per-swath-file nav** (`.fnv`) from the cached NCEI data directory, into `$DATA_ROOT/discovery_cache/nav/<cruise>/` (idempotent). Per-corpus `.fnv` is ~2.2 GB total, so nav for the 14 targets is on the order of ~1 GB — trivial against the ~450 GB it can save.

Fallbacks, in order, if `.fnv` is absent for a file/cruise: extract the track via `mbinfo`/`mblist` on the nav-bearing swath file; failing that, mark the cruise `needs_manual_nav` and skip it (do **not** guess a track). **No swath bulk fetch under any fallback.**

---

## Step 4 — Per-file intersection

For each swath file in a target cruise, parse its nav track (per-ping lon/lat) and test intersection against that cruise's buffered footprint union. Classify each file `intersecting` / `non_intersecting`. Per cruise, tally: `n_files_total`, `n_files_intersect`, `subset_GB` (sum of intersecting file sizes from the Stage-A size table), `whole_GB`, `fraction_kept`.

---

## Step 5 — Per-cruise verdict + revised budget

Assign each target cruise:
- **`transit_no_overlap`** (`n_files_intersect == 0`): recommend **EXCLUDE** — the track does not cover the footprint; false-pair confirmed by evidence, not assumption.
- **`good_overlap`** (`n_files_intersect > 0` and `subset_GB` materially < `whole_GB`): recommend **KEEP-SUBSET** — fetch only the intersecting files in Stage B.
- **`marginal`** (`subset_GB ≈ whole_GB`, footprint spans most of the cruise): recommend **KEEP-WHOLE**.

Emit `stage_a5_footprint_subset_2026-06-22.csv`: `cruise, whole_GB, subset_GB, n_files_total, n_files_intersect, fraction_kept, buffer_km, hr_served, verdict`.

**Revised budget** = Σ(`subset_GB` for keep-subset/keep-whole targets) + Σ(`whole_GB` for the 41 small cruises) + 0 for excluded. Report it against the 865 GB baseline, with the two Amundsen cruises broken out explicitly (their verdicts answer the §3 escalation from the dry-run).

---

## Step 6 — Clarify ancillary accounting (correction from review)

State plainly whether `.fbt` is **inside or outside** the 865 GB "swath + nav" figure. Correct the fetch-lean savings number: skipping regenerable ancillary is `.fbt` (25.5) + `.fnv` (2.2) = **~27.7 GB**, *not* the ~123 GB previously cited (that was the mirror−fetch gap, most of which is duplicate-encoding dedup the fetch estimate already excludes). Report the accurate swath-only vs swath+ancillary figures.

---

## Step 7 — Report and HOLD at Gate 1

Write `stage_a5_footprint_subset_report_2026-06-22.md`: target set, footprints + buffers, per-cruise verdicts, revised budget vs 865, the Amundsen rulings-with-evidence, and the ancillary correction. Re-present **Gate 1** to Steve with the revised numbers:
- **Q1 storage** — now even smaller; confirm it fits (it will).
- **Q2 retention** — purge-vs-keep, **unchanged, still pending** (and confirm validated outputs have a non-purge home, since scratch is 90-day-purge).
- **New:** the per-cruise **exclude / keep-subset** rulings, Amundsen first.

**HOLD here.** No Stage B swath fetch until Steve signs off on the revised budget, the retention policy, and the per-cruise rulings.

---

## Deliverables

1. `stage_a5_footprint_subset_2026-06-22.csv` (per-cruise verdicts + subset sizes)
2. `stage_a5_footprint_subset_report_2026-06-22.md`
3. Cached nav under `discovery_cache/nav/`
4. **HR footprint polygons** — persist them; Stage C's independence/footprint review reuses them rather than recomputing.

## Out of scope

Swath bulk fetch (Stage B), gridding (Stage C), executing any exclusion, the retention decision (Steve's), manifest writes. The 8 legacy SeaBeam cruises are all < 10 GB → not in this target set; leave them for Stage C.
