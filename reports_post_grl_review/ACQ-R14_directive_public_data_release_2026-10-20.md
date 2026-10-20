# DIRECTIVE ACQ-R14 (acquisition repo): public data release of the processed co-located corpus

**Date:** 2026-10-20
**Repo:** `co-located-auv-ship-based-multibeam-acquisition` (read the CNN repo for tile tables and blind-test records; write nothing there)
**Report to:** `reports_post_grl_review/ACQ-R14/REPORT_ACQ-R14_<date>.md`
**Report length:** at most 8 bullets, plus the size table and the license table.

## 0. Purpose and rulings

Build a public, citable package of the **processed** co-located ship/AUV corpus for the GRL revision (2026GL125574): the grids, masks, co-registration parameters and tile tables needed to reproduce every score in the paper. Raw swath is not included.

**Steve's rulings (2026-10-20):**
1. **What goes in:** processed grids only. No raw swath and no intermediate gridding products.
2. **Where it goes:** a Zenodo record, one record for the whole corpus, CC BY 4.0. You build and verify the package; you do **not** publish it. If Steve provides a Zenodo token, you may create an unpublished **draft** and upload to it. Publishing is Steve's action.
3. **Fix plumbing yourself:** paths, formats, missing metadata fields. Log each fix in one line and carry on. No rehearsal.
4. **Stop only if** a source dataset's license forbids redistribution, or the package exceeds 50 GB. Report and wait.

## 1. Scope (one entry per pair)

| Group | Pairs | Note |
|---|---|---|
| Development | 16 units, 38 pairs, including EW0207 | Mark the ten real-relief units and the six artifact-affected units |
| Blind test 1 | 3 confirmatory units, 2 lockbox pairs | Include KN182L03 even though it has no recoverable k |
| Blind test 2 | all 8 candidate sites | Include the 3 ineligible sites, flagged with the rule that failed |

Exclude anything with restricted source data (Kolumbo was already excluded). Rows that were dropped earlier (AT37-05, Chapopote, Venere, Amundsen) go in the manifest with their reason, without rasters.

## 2. Contents of each pair

All rasters are Cloud-Optimized GeoTIFF: float32 (uint8 for masks), DEFLATE with predictor, internal overviews, the pair's projected CRS as an EPSG code, and an explicit nodata value. Elevations are in meters, positive up, with the vertical reference stated.

1. `hr.tif`: the AUV grid as used, after harmonizing and co-registration, at native resolution.
2. `lr.tif`: the ship grid as used, at its native cell size, on the same CRS.
3. `hr_valid.tif`, `lr_valid.tif`, `joint_valid.tif`: the masks as used, including ACQ-R13 boundary zeroing.
4. `ship_products/`: the per-sounding product rasters (contract v2.1), only where usable.
5. `pair.json` (one file per pair):
   - identifiers: unit, pair, role and group;
   - source HR and LR datasets with DOI, cruise, platform, sonar and license;
   - `hr_res` and `lr_native`;
   - k and its status;
   - the co-registration result: global shift (dx, dy, dz), case (rigid or drift), per-quadrant shifts for drift sites, and the QA values;
   - the datum statistic G and its pass or fail;
   - flags, eligibility and the artifact class;
   - the sha256 of every file.

## 3. Corpus-level files

1. `pairs.parquet` and `pairs.csv`: one row per pair, carrying the `pair.json` fields that fit in a table.
2. `tiles.parquet` and `tiles.csv`: one row per scored tile, carrying:
   - the pair and tile coordinates, and the block id;
   - the interior flag and the exclusion flags (including the 22 R17 Escanaba tiles);
   - A_fine and A_fine_int;
   - s_lr;
   - the held-out GBT_ship and P-V1 predictions.

   Take these from the frozen CNN-repo outputs. Do not recompute.
3. `blind_tests/`:
   - both pre-registrations (v2.1 and v3.1);
   - Steve's two committed calls files;
   - the deviation notes;
   - the Phase 4 and Phase 5 scoring outputs (`results_D1.json`, `per_pair_D1.csv`).
4. `README.md`, covering:
   - what the corpus is;
   - the two anti-circularity rules;
   - the folder layout;
   - how to cite it, and that each source dataset must also be cited;
   - known limitations: six artifact-affected units, ship line-to-line inconsistency unchecked, and the TN159 HR pixel of 3.25 m.
5. `DATA_DICTIONARY.md`: every field, with units.
6. `CITATION.cff`, `LICENSE` (CC BY 4.0) and `SHA256SUMS`.
7. `examples/load_pair.py`: a script under 60 lines that opens one pair's grids and the tile table and reproduces that pair's s_lr ρ.

## 4. Packaging

Zenodo allows 100 files and 50 GB per record. Ship one zip per pair (`<pair>.zip`, holding its rasters and `pair.json`), and put the corpus-level files at the top level, uncompressed. Report the file count and total size.

## 5. Checks (minutes, not a rehearsal)

1. **License audit:** read each source dataset's license from its landing-page metadata. Table it in the report: dataset, DOI, license, redistribution allowed (yes or no).
2. **Reproduction:** from the packaged files only, run `load_pair.py` on three development pairs, one Phase 4 pair and one Phase 5 site. Each s_lr ρ must equal the frozen value to 3 decimals.
3. **Integrity:**
   - open every raster with GDAL and confirm it is a valid COG with the right CRS and nodata;
   - confirm every `pair.json` sha256 matches its file;
   - confirm `SHA256SUMS` verifies.
4. **Blindness:** no sealed-only material remains, since both tests are scored. Confirm that nothing in the package is under a restricted license.

## 6. Report

1. The size table: per group, number of pairs, total GB and largest zip; then the package total.
2. The license table and any pairs excluded on license.
3. The reproduction and integrity results.
4. Every plumbing fix, one line each.
5. The package path on OAK, its `SHA256SUMS` sha256, and the Zenodo draft URL if one was created.
6. A suggested Zenodo title, description (at most 200 words), keywords and related identifiers (the paper, and the two existing code records 10.5281/zenodo.21300922 and 10.5281/zenodo.21300925).

Commit by explicit path; one `CHANGE_LEDGER.md` row; OAK `acq_archive/ACQ-R14/` with `SHA256SUMS` verified.

## 7. Out of scope

- Raw swath, intermediate products, band-passed field rasters (derivable from the code) and model checkpoints.
- Publishing the Zenodo record.
- Any change to a frozen computation or value.
