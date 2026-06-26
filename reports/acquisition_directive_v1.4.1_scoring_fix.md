# Acquisition Directive v1.4.1 — Fix: HR footprint geometry, de-dup, scoring

**Amends** v1.4 (pair-discovery engine). The M3 catalog **cannot be triaged as-is** — not because the pairs are fabricated, but because the HR geometry is wrong, which makes every overlap-based metric and the ranking unreliable. This supersedes the earlier scoring-only draft of v1.4.1: the footprint fix comes **first**, because nothing downstream means anything until it lands. All work here is **read-only / re-rank only** against the manifest and harmonized data — do not modify, re-run, or delete any existing pair (DISCOL, the 18 Cal DIG, CCZ, TAG stay exactly as they are).

---

## What the M3 catalog actually shows (evidence)

Inspecting `candidate_pairs` (3,033 rows, 156 distinct HR):

- **HR footprints are inflated coarse envelopes, not true grid extents.** Backing out HR area from `overlap_km2 / overlap_frac_hr`: `MGDS:32556/57/58` are 1 m MBARI-AUV grids with **~1,310 km²** footprints; `30217/18/19` are 1 m Sentry grids at **522.7 km²** (identical to six decimals across siblings and across different cruises — the overlap is HR-area-limited, i.e. a giant box sitting inside a giant cruise). A near-bottom AUV grid is single-digit-to-tens of km². **71 of 156 HR exceed 60 km²** of implied footprint. This makes `overlap_frac_hr ≈ 1.0` everywhere and is meaningless — so it cannot be the ranking signal until fixed.
- **Survey families not de-duplicated.** `32556/57/58` (consecutive DOIs, same platform, same 0.998 m resolution, near-identical footprint) are chunks of one survey; same for the Sentry and MBARI-Mapping-AUV trios. v1.4 §3's "one row per gridded product per mission" did not fire.
- **Massive join fan-out.** Median 14, up to 100 ship cruises per HR. The "first 25 rows" resolve to ~3 AUV surveys, all at Axial Seamount, each split into sibling rows and fanned across ~50 ridge cruises.
- **`res_ratio` blank for all 3,033 rows** (`lr_native_res_est_m` 0/3033) — the GSD enrichment never ran, so the score still leans on raw overlap area.
- **Non-AUV contamination.** Surface vessels are in the AUV HR set: R/V Zephyr (4.1 m, 97 cruise hits), R/V Falkor, R/V Atlantis, R/V Thomas G. Thompson, R/V Rachel Carson.

Fix order below is deliberate: geometry → de-dup → platform filter → enrichment → re-score.

---

## 1. True HR footprint geometry (root fix — do this first)

Replace the inflated envelope with the **actual data-coverage extent** of each HR grid:
- Prefer the real coverage polygon if the source exposes one; otherwise **compute the true extent from the grid's valid-data mask** (non-nodata cells) at catalog time, not the metadata bounding box / multi-dive hull.
- Recompute `overlap_km2`, `overlap_frac_hr`, and the HR area from the corrected geometry.
- **Implausibility flag:** flag any HR whose footprint area is inconsistent with a near-bottom survey at its resolution (propose: AUV-class platform with footprint > ~60 km² → `footprint_suspect`). Flagged HR are held out of the ranked triage tier until their geometry is confirmed, not silently dropped.

Until this is done, treat `overlap_frac_hr` as unreliable — it is currently an artifact of coarse boxes.

---

## 2. De-duplicate survey families

Collapse sibling rows to **one HR per survey/mission**. Detection signature: same platform + same native resolution + consecutive/related DOIs + (after §1) near-identical true footprint. Key the surviving row on the gridded-bathymetry product; record sibling DOIs and file IDs in a field. Expect the HR count to drop materially below 156.

---

## 3. Tighten the AUV platform filter

The harvest is catching surface vessels. Exclude HR whose platform is a research vessel / hull / USV rather than a near-bottom AUV (R/V Zephyr, R/V Falkor (too), R/V Atlantis, R/V Thomas G. Thompson, R/V Rachel Carson, and `NotApplicable`). Keep genuine AUV platforms (MBARI Mapping AUV, Sentry, ABE, REMUS, AUV ABYSS). Where platform is ambiguous, use resolution as a secondary signal (a 4 m "AUV" grid is suspect) and flag rather than auto-keep. Note R/V Rachel Carson is MBARI's *host* vessel — the AUV grids from its cruises are labelled by the AUV, so don't exclude the AUV grids, only any hull-MBES grid mislabelled as AUV HR.

---

## 4. Populate `res_ratio` (enrichment, no longer optional)

Fill `lr_native_res_est_m` per NCEI cruise via Geoportal ISO metadata; where absent, estimate from sonar + depth and mark `lr_res_source=estimated`. Compute `res_ratio = LR_gsd / HR_gsd`. Flag `high_ratio` (>~30×) and `ratio_too_low` (~1×, not really super-resolution).

---

## 5. Re-score and collapse fan-out for triage

- Score on **corrected** `overlap_frac_hr` (now meaningful) + `res_ratio` in the useful band (~5–25×) + license + province-gap boost. Raw overlap area is a weak tiebreaker only; add `area_implausible` as an **informational** flag (not an auto-demotion — you confirmed in QGIS the real overlaps are legitimate where geometry is correct).
- **Collapse fan-out for the triage view:** group candidates by HR and surface the **single best LR per HR** in the ranked tier (keep the full HR×LR set in the catalog, but the triage list should read as distinct AUV sites, not one site × 50 cruises). Optionally cap rows-per-HR in the top tier.

---

## 6. Acceptance

- HR footprints reflect true data extent; no 1 m AUV grid reports a 500–1,300 km² footprint; `footprint_suspect` flags the inflated remainder.
- Family siblings collapsed to one HR per survey.
- Surface-vessel entries removed from the AUV HR set.
- `res_ratio` populated (or explicitly estimated/unavailable) for every candidate.
- The ranked triage list shows **distinct AUV sites**, not the same Axial survey repeated; the Axial MBARI-AUV / Sentry surveys appear **once each** with their best independent ridge-cruise LR and a sane ratio — your first volcanic/seamount province batch.
- **Pause for human triage.** No downloads, no manifest writes; read-only/append-only preserved.

---

## Hard rules (unchanged)

- Read-only / append-only against all existing work; discovery never edits or deletes a manifest row, harmonized product, or prior pair.
- APIs only; join on true coverage polygons, not bounding boxes or envelopes.
- Never pair against a composite as LR; resolve to the independent underlying survey.
- Discovery proposes; human selects; the existing v1.0–v1.3 pipeline executes behind the confirm-before-download gate.
