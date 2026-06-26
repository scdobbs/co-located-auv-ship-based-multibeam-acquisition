# Phase 2 — Stage A.6 pre-fetch hygiene (dedup + footprint census + quality tags)

**Date:** 2026-06-22
**Author:** Claude Code execution instance (Sherlock)
**Directive:** `reports/directive_phase2_stage_a6_prefetch_hygiene.md`
**Status:** ⛔ **HOLD at Gate 1.** Recommendations only — no swath fetched, manifest untouched, no validated pair re-opened.

**Artifacts**
- `reports/stage_b_fetch_list_2026-06-22.csv` — **cleaned, deduplicated fetch plan** (55 cruises → 45 kept / 10 dropped).
- `reports/discovery/stage_a6_duplicates_2026-06-22.csv` — Phase-2 HR → manifest pair it duplicates.
- `reports/discovery/stage_a6_hr_footprints_2026-06-22.gpkg` — **71 non-seed clean HR**, unbuffered valid-data polygons + `footprint_type` + `duplicate_of` (Stage C reuses).
- `reports/discovery/stage_a6_summary_2026-06-22.json`.
- Code: `src/discovery/stage_a6_footprints.py` (Slurm, 71 footprints) + `stage_a6_hygiene.py` (dedup/list/census) + `stage_a6_common.py`.

---

## 1. Headline

| | |
|---|---|
| Clean HR (Stage-1 corpus) | 81 |
| **Duplicates of the untouchable 21** | **10** (all id/seed; **0 spatial**) |
| **True new-HR count Phase 2 will pair** | **71** |
| Cruises in raw-LR plan | 55 → **45 kept / 10 dropped** |
| A.5 budget | 146.75 GB |
| **Revised fetch budget** | **130.91 GB** |
| Bbox-fallback footprints in cleaned fetch list | **0** (census closes clean) |

---

## 2. Footprints for all 81 clean HR (Step 1)

The 71 **non-seed** clean HR were polygonised from their staged grids (decimated valid-data masks, resolved/recovered CRS — same logic as A.5) in a Slurm job. The 10 `manifest_seed_clean` HR are the untouchable-21 pairs themselves, so their authoritative footprints were read from the manifest `footprint.geojson` files (reprojected to 4326) rather than recomputed.

**Result: all 71 are `valid_polygon`; 0 `bbox_fallback`, 0 failures.** The single bbox case from A.5 (MV1405's HR) was the seed `PockmarkNorth`, which is dropped as a duplicate anyway — so it does not reach the fetch list.

---

## 3. Duplicate sweep against the untouchable 21 (Step 2)

Tested every clean HR by **both** id/site-name match and spatial match (IoU > 0.8, or containment ≥ 0.9):

- **10 duplicates, all id/seed matches; 0 spatial matches.** The 10 are exactly the `manifest_seed_clean` set (the bulk selection re-derived already-validated sites): `PANGAEA:tag_m127` → pair `tag_m127`, and the 9 `MANIFEST:cal_dig_morro_bay__*` → their cal_dig pairs.
- **0 spatial duplicates** confirms there is no *different-id* re-derivation hiding in the 71 non-seed HR — the MV1405 case was already captured by id. (This is the reassurance the directive asked for: confirmed, not assumed.)

**Recommendation:** drop all 10 duplicate HR from Phase-2 processing (one pair per distinct HR; manifest is authoritative). We did **not** compare the duplicates' candidate LRs against the manifest LRs — that is a separate manual call if ever wanted.

Mapping in `stage_a6_duplicates_2026-06-22.csv`.

---

## 4. Cleaned Stage-B fetch list + revised budget (Step 3)

`live_HR(cruise) = served − {dropped 30272/20836/24425, quarantined 31600, the 10 duplicates}`.

**10 cruises drop** (their `live_HR` is empty — they served *only* dead/duplicate HR):

| Dropped cruise | whole GB | sole reason |
|---|---|---|
| MV1405 | 35.09 | dup `PockmarkNorth` (A.5 had it keep-subset at 0.03) |
| EX1101 | 5.54 | dup `600mGully` |
| NA073 | 5.35 | dup `Channel700` |
| RR0916 | 12.32 | dead HR `24425` (PDF) — re-derives A.5 exclusion |
| SR1903 | 1.28 | dup ×2 (`1000mGully`, `BankFlankIncipCh`) |
| DRFT01RR | 1.80 | dup `BankTopEofCanyon3` |
| EW0407 | 1.15 | dup `LuciaChica970m` |
| KN180L02 | 0.87 | quarantined HR `31600` |
| KIWI01RR | 0.57 | dup `LuciaChica2m` |
| RNDB18WT | ~0.06 | dup `6thHeadlessCany` |

No multi-HR cruise lost an HR while keeping another, except `2010_Amundsen` (already had `30272` excluded in A.5) and `FK006B` (loses dropped PDF `20836`, keeps live `MGDS:20811`; small → fetch whole). So **every ≥10 GB target reused its A.5 subset unchanged** — re-subsetting was not required.

**45 kept cruises:** 12 subset (≥10 GB targets) + 33 whole (small). **Revised fetch = 130.91 GB** (was 146.75). New-HR count = 81 − 10 = **71** — the true number of HR Phase 2 will actually pair (≈63 via the 45 raw cruises to grid + the ~8 non-seed HR whose processed LR is already staged).

Full plan in `stage_b_fetch_list_2026-06-22.csv` (`cruise, live_HR, fetch_mode, whole_GB, subset_GB, footprint_bbox, reason`).

---

## 5. Bbox-footprint census (Step 4)

`footprint_type` across all 81: **81 `valid_polygon`, 0 `bbox_fallback`** (the 71 computed here + 10 manifest seeds, all real polygons). **No cruise in the cleaned fetch list has a `bbox_fallback` live-HR footprint** — every subset was computed against a true valid-data polygon, not a rectangle. The census closes clean (MV1405, the only A.5 bbox, is dropped). No fix-geometry-then-resubset or conservative whole-fetch is needed on geometry grounds.

---

## 6. Thin-overlap quality tags (Step 5)

Tagged `lr_coverage_quality_watch` (carried into Stage C, not an action now): **`TN299` (frac 0.011), `NA080` (0.014), `TN399` (0.008)** — all kept as subset. The AUV patch clips the edge of a large deep survey, where ship coverage is outer-beam (high-incidence, sparse, noisy). **Stage-C check:** confirm the soundings over each HR footprint are adequate-density near-nadir coverage; if edge-only/grazing, the LR may be too poor to pair regardless of ratio — a candidate Stage-C exclusion. Tag, don't drop.

---

## 7. ⛔ Revised Gate 1 — for Steve

### Q1 — Storage (smaller again; confirm it fits)
Cleaned raw fetch ≈ **131 GB**. `$DATA_ROOT` on `GROUP_SCRATCH` is at **2.8 TB / 100 TB (2 %)**, 1.7 M / 20 M inodes — 131 GB adds ~0.13 %. Fits trivially.

### Q2 — Retention (unchanged, still pending)
Purge vs keep raw `.all`/`.gsf` after gridding + QC. **And confirm a non-purge home** for validated outputs (gridded LR, harmonized pairs, manifest) — scratch is 90-day-purge, so `$GROUP_HOME` or `$OAK` for anything we intend to keep.

### Rulings to confirm (A.5 + A.6, folded together)
- **Drop the 10 duplicate HR** (manifest authoritative). *Recommended.*
- **Drop the 10 cruises** in §4 (serve only dead/duplicate HR). *Recommended.*
- **Amundsen ×2 → KEEP-SUBSET** (real pairs; 500 → 45 GB). *Recommended.*
- **Fetch plan:** 45 cruises, 12 subset + 33 whole, **131 GB**; 71 HR to pair. *Recommended.*
- **Stage-C watch:** `TN299/NA080/TN399` coverage quality.

**HOLD.** No Stage B until Steve signs off on the cleaned fetch list, the retention policy + non-purge output home, and the rulings above.
