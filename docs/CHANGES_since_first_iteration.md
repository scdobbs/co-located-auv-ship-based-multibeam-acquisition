# What changed since the first iteration

**Baseline ("first iteration"):** `origin/main` at `642e3db` — the directive-v1.0 pipeline (M0 scaffold, M1 vertical
slice on DISCOL and Cal DIG, `python -m src.cli ingest`, `manifest/pairs.parquet`, per-pair UTM / bilinear / MSL
harmonization, bulk rasters on scratch).
**This branch (`acq-r03-close-acquisition`):** 78 commits on top of that baseline, ending with the close of Phase 1
acquisition under the post-GRL-review directives ACQ-R01, ACQ-R02 and ACQ-R03 (2026-09-29 → 2026-10-01).

Everything below is recorded in detail in `reports_post_grl_review/ACQ-R0{1,2,3}/REPORT_*.md`; this file is the
map, not the record.

---

## 1. Where the data live now

| then | now |
|---|---|
| raw + harmonized rasters on Sherlock group **scratch** (`/scratch/groups/hilley/auv_ship_colocated_bathy`), subject to the 90-day purge (and purged on 2026-09-20) | everything durable on **Oak** `/oak/stanford/groups/hilley/auv_ship_colocated_bathy/`: `harmonized/<pair>/`, `harmonized_confirmatory/<unit>/<pair>/` (sealed), `raw_hr/`, `raw_lr_swath/<cruise>/` (immutable raw ship swath, sha256, 0444), `raw_lr_gridded/`, `manifest/`, `qc/`, `review/`, `snapshots/`. Scratch holds only working files (`acq_r03_*`). |
| `manifest/pairs.parquet` (June, 39 pairs) | `pairs.parquet` **unchanged**; `manifest/pairs_v2.parquet` (ACQ-R02, 49 rows) and **`manifest/pairs_v2_1.parquet` (ACQ-R03, 50 rows)** are the current catalogs, with `pairs_v2_dropped.csv` / `pairs_v2_1_dropped.csv` listing every pair removed and why. Consumers read `harmonized_path` (the directory holding `lr.tif`) and never derive paths from `pair_id`. |
| no per-pair ship-side products | per pair, on the `lr.tif` grid: `ship_products_v1/` (ACQ-R01), `ship_products_v2/` (ACQ-R02) and **`ship_products_v2_1/`** (ACQ-R03), each frozen by an `INTERFACE_CONTRACT_v*.md` in `reports_post_grl_review/`. |

## 2. Catalog lineage

- **v1.0 (June):** 39 harmonized pairs (21 validated + 18 Cal DIG dive patches), stages A–F of the June Phase 2 work (gridding the LR from raw ship swath with MB-System, masked co-registration, validity masks, 256-px tile counts, C2a documented-beam-footprint `lr_native`, C2c k sweep). `reports/` is no longer tracked (`238ea61`); the June stage reports stay on disk.
- **ACQ-R01 (2026-09-29):** **lockbox guard** — two permanent hold-out pairs (`AT42-03__MGDS_32007`, `TN159__MGDS_21981`) can never be opened by repo code (`src/acq_r01/common.py` patches `open`, `rasterio.open`, `numpy.load` on import); raw NCEI/PANGAEA ship swath re-fetched and persisted on Oak; **contract v1 ship products** (count, sd, cross-track fraction, beam angle) for 16 pairs, Cal DIG marked unavailable (NOS BAG mosaic, no soundings); audit reconciliation; discovery re-run and a seeded confirmatory designation.
- **ACQ-R02 (2026-09-30):** **contract v2** (adds exact per-cell medians, robust spread, an 81-shift QA surface and flags); corpus and lockbox snapshots on Oak; PANGAEA metadata discovery (4 new units); candidate verification (32 → 23) with real footprints and a leakage-unit re-run (nu01 split into nu01a/nu01b); acquisition of 18 LR cruises gridded from raw swath; 9 new development pairs and 1 confirmatory pair harmonized; **manifest v2**; 9 pairs dropped (3 false pairs, 4 QA, 2 confirmatory co-registration fails).
- **ACQ-R03 (2026-09-30 → 10-01, this branch):** see §3.

## 3. ACQ-R03 in one page

**Contract v2.1** (`INTERFACE_CONTRACT_v2.1.md`, committed verbatim before any code). The `registration_shift` gate now
fires only at ≥ 0.5 cell with a material gain; a `frame_offset` block records a header-derived registration offset
(none applied: the header check found no node/pixel mismatch anywhere, which also corrects an ACQ-R02 statement).
`ship_products_v2_1/` built for all 25 pairs with swath; v1/v2 untouched. Flags fell from 21 to 4 `registration_shift`
(CCZ, DISCOL, TAG, AT37-05). Validation: 45/45 development pairs pass.

**Infrastructure finding that changed the code.** Apptainer container starts on Sherlock normal nodes take 30–60 s
and fail or hang under concurrent starts; the June and ACQ-R02 builders counted such a failure as "no soundings",
so **NA080__MGDS_31289's v2 products silently miss two swath files** (v2.1 holds them). Every MB-System call in
`src/acq_r03/` is now bounded, retried up to 6×, and a build fails loudly on any unread file.

**PANGAEA raw-swath fetch** by footprint subset instead of whole cruise (`src/acq_r03/pangaea_select.py`,
`fetch_pangaea.py`, `ingest_manual.py`): M114/1 (Chapopote) 59 of 349 files landed at 0.8 MB/s; pu01 harmonized but
fails the 30 m co-registration bound (dropped, ruling R2). M112/1 (Venere): no per-file geometry, no navigation
dataset; positions come from 2 MB `Range` heads, throttled by the host — pending Steve's cruise report (ruling R3).

**Review packages, decided by Steve** (`rulings_ACQ-R03.md`): AT37-05 — one survey line 294 m deeper than the other
three, a ship-internal inconsistency → **dropped (R1)**; confirmatory KN182L03 and SUM1004 — sealed before/after
hillshade + contour + search-surface packages → **reinstated (R6)**. Amundsen: 30046's 16 m LR came from another
HR's grid; **regridded at its own-depth stage-C cell (4.17 m) into a versioned `lrv2_1/` directory (R5)**; both lu18
pairs are no-k. CCZ/DISCOL/TAG ship products masked as unusable (R4).

**Manifest v2.1** (`manifest/pairs_v2_1.parquet`): 50 rows; new columns `ruling_source`, `ship_products_usable`,
`ship_products_usable_reason`, `products_v2_1_flags`, `manifest_version`; label fixes (MGDS:5174 is EPR 9°N; lu07 =
TN293 sites Loihi + Necker Ridge). **Development-unit table** (`reports_post_grl_review/ACQ-R03/dev_unit_table.md`):
20 units / 45 pairs; 17 usable units / 39 usable pairs (with a recoverable k); 12 units / 17 pairs with usable ship
channels. Confirmatory holdout at the end of Phase 1: nu01a, nu01b, nu03 + the lockbox.

## 4. Code map (new since the baseline)

```
src/acq_r01/        ACQ-R01/R02: common.py (lockbox guard, Oak paths, units), fetch_swath.py, build_products.py (v1),
                    build_products_v2.py, validate_contract*.py, pangaea_discovery.py, verify_candidates.py,
                    fetch_plan.py, grid_lr.py (stage C), harmonize_new.py (C.5/F + k + QC + products), manifest_v2.py
src/acq_r03/        ACQ-R03: pangaea_select.py, m112_positions.py, fetch_pangaea.py, ingest_manual.py,
                    header_check.py, build_products_v2_1.py, validate_contract_v2_1.py, report_v2_1_table.py,
                    at37_review_package.py, confirmatory_criterion.py, confirmatory_review_package.py,
                    amundsen_audit.py, amundsen_regrid_r5.py, manifest_v2_1.py, dev_unit_table.py
sbatch/acq_r0*.sbatch   Slurm drivers for every step above
reports_post_grl_review/   directives + contracts (verbatim), rulings, per-directive reports and artifacts
manifest/pairs_v2*.parquet, pairs_v2*_dropped.csv
```

Unchanged from the first iteration: the `src/cli.py` / `src/harmonize.py` / `src/coregister.py` chain and
`config/harmonization.yaml` (the ACQ-R0x drivers call `harmonize.harmonize_pair` and `coregister.estimate_rigid_xyz`
directly), `CLAUDE.md` (directive v1.0), the Sherlock rules (bulk data never in `$HOME`; APIs, never HTML scraping;
DOIs never guessed; LR never synthesised from HR).

## 5. Standing conventions introduced after the first iteration

- **Lockbox** — never opened, gridded, downloaded or QA'd; guard installed on import of `src.acq_r01.common`.
- **Confirmatory seal** — units `nu01a`, `nu01b`, `nu03` (and the dropped `pu02`, unacquirable `pu03`) live under
  `harmonized_confirmatory/`; only pass/fail, shift and counts are recorded; products only at Phase 4.
- **Anti-circularity** — PANGAEA/NCEI processed grids are footprint proxies only, never LR; every LR is gridded from
  raw ship swath.
- **Directives are committed verbatim before their code runs; rulings likewise; every changed manifest row names its
  `ruling_source`.**
- **Dropped pairs are not rows**: they are listed in `manifest/pairs_v2*_dropped.csv` and their files stay on Oak.

## 6. Open at the tip of this branch

- pu00 (Venere, M112/1): awaiting the cruise report for the R3 time-window pre-filter
  (`reports_post_grl_review/ACQ-R03/INTERIM_NOTE_m112_cruise_report.md`); enters as manifest v2.1.1 when its chain finishes.
- Cal DIG (18 pairs) has no ship products (no swath); the three June no-k pairs carry unavailable `products.json`.
