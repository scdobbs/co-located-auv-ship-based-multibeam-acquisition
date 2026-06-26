# Phase 2 — Stage A.5 nav-first footprint subsetting + revised Gate 1

**Date:** 2026-06-22
**Author:** Claude Code execution instance (Sherlock)
**Directive:** `reports/directive_phase2_stage_a5_footprint_subset.md`
**Status:** ⛔ **HOLD at Gate 1.** Recommendations only — no exclusions executed, no swath fetched. Awaiting Steve.

**Artifacts**
- `reports/stage_a5_footprint_subset_2026-06-22.csv` — per-cruise verdicts + subset sizes.
- `reports/stage_a5_footprint_subset_2026-06-22.json` — full breakdown + revised budget.
- `reports/discovery/stage_a5_hr_footprints_2026-06-22.gpkg` — **24 buffered HR footprint polygons** (EPSG:4326) — reuse in Stage C's independence/footprint review.
- Cached nav: `$DATA_ROOT/discovery_cache/nav/<cruise>/` (~11.9k `.fnv`, idempotent).
- Code: `src/discovery/stage_a5_subset.py`; job `sbatch/stage_a5_subset.sbatch` (ran on `normal`, ~22 min).

---

## 1. Headline — the 865 GB collapses to ~147 GB

| Component | GB |
|---|---|
| Stage-A baseline (whole-cruise fetch) | **865.15** |
| 41 small cruises (<10 GB) — fetch whole | 88.34 |
| 14 large cruises — **subset to intersecting files only** | 58.41 |
| **Revised fetch total** | **146.75** |
| **Saved by subsetting + 1 exclusion** | **718.40 (83 %)** |

**The two Amundsen cruises are real pairs, not transit false-pairs** (§3) — but their swath tracks cross the AUV footprints in only ~10 % of files, so subsetting cuts them from **500 GB → 45 GB** without losing the overlap. That is the evidence-based answer to the Stage-A §3 escalation: **keep-subset, do not exclude.**

---

## 2. Method (per directive)

- **Target set:** 14 cruises with whole_GB ≥ 10 (the 2 Amundsen >100 GB + 12 in 10–100 GB). The 41 small cruises fetch whole — subsetting overhead isn't worth it.
- **Footprints:** for every served HR, the **true valid-data polygon** was polygonised from the staged grid (decimated read, reusing the validated `stage_b._valid_polygon_from_raster` logic) — **not** a bbox — using the HR catalog's resolved/recovered CRS where the raster lacked one. Per-cruise the served-HR footprints were **unioned** and **buffered outward by `max(2×depth, 1 km)`** (computed in local UTM) to capture ship-swath coverage around the patch. 24 footprints persisted; buffers ran **1.0–6.7 km** (deep cruises like TN365/NA080/TN299 hit the `2×depth` term at ~3,000 m+).
- **Nav-only fetch:** the `.fnv` for every swath file was fetched (1:1 swath↔nav, confirmed) — **no swath bulk fetch**. Empty `.fnv` fragments (`n_nav_missing`, ≤35/cruise) were **conservatively kept** (over-include at the margin).
- **Per-file intersection:** each swath file's nav track (lon/lat) tested against its cruise's buffered footprint union; `subset_GB` = Σ intersecting swath bytes from the Stage-A size table.

---

## 3. ⭐ Amundsen ruling — with evidence

| Cruise | whole GB | files intersect | subset GB | verdict |
|---|---|---|---|---|
| `2009_Amundsen` (HR `MGDS:30045`) | 253.68 | **377 / 3198** (9.8 %) | 24.75 | **KEEP-SUBSET** |
| `2010_Amundsen` (HR `30270, 31753, 31755`; `30272` dropped) | 246.83 | **111 / 3022** (8.2 %) | 20.14 | **KEEP-SUBSET** |

Both cruises' tracks **do cross** the AUV footprints (hundreds of swath files intersect) — so these are **genuine co-located pairs**, not the bbox-overlap artifacts feared in Stage A. The 500 GB scare was an artifact of fetching *whole* transit surveys; subsetting to the overlapping lines keeps the science at **45 GB combined**. `2010_Amundsen`'s dropped HR `MGDS:30272` was correctly excluded from its footprint, leaving 3 live HR.

---

## 4. Per-cruise verdicts (all 14)

| Cruise | whole GB | subset GB | frac kept | files ∩ / total | buffer km | verdict | flag |
|---|---|---|---|---|---|---|---|
| 2009_Amundsen | 253.68 | 24.75 | 0.098 | 377/3198 | 1.0 | keep_subset | |
| 2010_Amundsen | 246.83 | 20.14 | 0.082 | 111/3022 | 1.0 | keep_subset | 30272 dropped |
| TN313 | 47.47 | 2.20 | 0.046 | 36/407 | 3.1 | keep_subset | |
| TN299 | 38.17 | 0.41 | 0.011 | 12/658 | 6.1 | keep_subset | thin |
| NA080 | 35.38 | 0.49 | 0.014 | 51/1033 | 6.6 | keep_subset | thin |
| **MV1405** | 35.09 | 0.03 | 0.001 | **1/1090** | 1.7 | keep_subset | ⚠️ **bbox + dup, see §5** |
| TN399 | 20.63 | 0.16 | 0.008 | 10/923 | 5.2 | keep_subset | thin |
| FK171110 | 20.04 | 2.24 | 0.112 | 40/324 | 1.0 | keep_subset | |
| RB1604 | 19.15 | 1.15 | 0.060 | 7/75 | 1.0 | keep_subset | |
| TN365 | 17.01 | 1.34 | 0.079 | 34/410 | 6.7 | keep_subset | |
| **RR0916** | 12.32 | 0.00 | 0.000 | 0/0 | – | **EXCLUDE** | ⚠️ dead HR, see §5 |
| FK181031 | 10.80 | 2.85 | 0.264 | 50/176 | 4.8 | keep_subset | |
| TN268 | 10.14 | 1.69 | 0.167 | 87/229 | 4.6 | keep_subset | |
| TN383 | 10.09 | 0.95 | 0.094 | 28/237 | 1.0 | keep_subset | |

No cruise came back `transit_no_overlap` or `needs_manual_nav`.

---

## 5. Escalations (flag, not absorb)

1. **`RR0916` → recommend EXCLUDE (no valid HR).** Its only served HR, `MGDS:24425`, is the **dropped PDF-only** entry (the staged dir holds `sentry*.grd.pdf`, no grid). With no AUV raster there is no footprint to pair against. Closed unless the underlying grid is recovered.

2. **`MV1405` → recommend DROP / human review (three independent reasons):**
   - **Duplicate of an existing pair.** Its HR `cal_dig_morro_bay__20180427m3_PockmarkNorth` is **already one of the untouchable 21 manifest rows** (it has a processed Cal DIG LR). MV1405 is a re-derived companion that **dedup at Stage G would reject** anyway.
   - **Footprint unreliable** (`footprint_bbox_flag=True`): the staged Cal DIG HR did not yield a valid-data polygon, so a metadata **bbox** was used — exactly the geometry the directive says not to trust.
   - **Overlap negligible:** only **1 / 1090** files intersect (0.03 GB). Not a credible independent pair.

3. **Thin-overlap cruises (`TN299`, `NA080`, `TN399`):** legitimate keep-subset, but the AUV patch only clips the edge of a large deep survey (frac kept ≤1.4 %, 10–51 files). Flagged so Stage C confirms the clipped overlap is real seafloor coverage, not a track tangent. The generous `2×depth` buffer (6+ km) means these are *not* under-buffered.

---

## 6. Ancillary accounting (directive Step 6 — correction)

- **`.fbt` is OUTSIDE the 865 GB.** The Stage-A fetch estimate counted **swath only** (`.all.mb*.gz` / `.mbNNN`); `.fbt` (25.5 GB) and `.fnv` (2.2 GB) were classified ancillary and **excluded**. So 865 GB = pure swath, and the revised 146.75 GB is likewise swath-only.
- **Corrected fetch-lean figure:** skipping regenerable ancillary saves `.fbt` (25.5) + `.fnv` (2.2) = **~27.7 GB**, *not* the ~123 GB cited in the Stage-A report. That 123 GB was the mirror−fetch gap, most of which is duplicate-encoding dedup the fetch estimate already excludes. (Our plan fetches swath-only regardless, so ancillary is simply not fetched — MB-System regenerates `.fbt`/`.fnv` from the raw, and we fetch the small `.fnv` only for the kept files at grid time.)

---

## 7. ⛔ Revised Gate 1 — for Steve

### Q1 — Storage (now far smaller; confirm it fits)
Revised raw fetch ≈ **147 GB** (was 865). `$DATA_ROOT` is on `GROUP_SCRATCH` (`/scratch/groups/hilley`), at **2.8 TB / 100 TB (2 %)**, **1.7 M / 20 M inodes**. 147 GB adds ~0.15 %. Fits trivially. *(Capacity was never the real constraint; the subset mostly de-risks gridding effort and confirms the pairs are real.)*

### Q2 — Retention (unchanged, still pending)
Purge vs keep raw `.all`/`.gsf` after gridding + QC. **Note:** scratch is 90-day-purge — **validated outputs (gridded LR, harmonized pairs, manifest) need a non-purge home** (`$GROUP_HOME` or `$OAK`); confirm that destination as part of this decision.

### NEW — per-cruise rulings to confirm
- **Amundsen ×2 → KEEP-SUBSET** (real pairs; 500 → 45 GB). *Recommended.*
- **RR0916 → EXCLUDE** (dead HR). *Recommended.*
- **MV1405 → DROP** (duplicate of an existing manifest pair + unreliable bbox footprint + 1-file overlap). *Recommended.*
- **Remaining 11 large cruises → KEEP-SUBSET**; 41 small cruises → fetch whole.

---

## 8. On Gate-1 sign-off
Stage B fetches **only** the intersecting swath files per the subset table (+ their `.fnv`), byte-verified, idempotent → Stage C MB-System gridding pilot (assessment review before all). The persisted footprint polygons carry forward to Stage C's independence/footprint check.

**Holding here for Steve's Q1 + Q2 + the four rulings above.**
