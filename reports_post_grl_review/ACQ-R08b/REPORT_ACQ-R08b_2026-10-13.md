# REPORT ACQ-R08b — second-test candidates downloaded; header, footprint, one rounded depth and tile count measured

**Directive:** `ACQ-R08b_directive_blind_header_footprint_2026-10-13.md`. **Run:** 2026-10-13, jobs in `run_jobs.json`. **Code:** `src/acq_r08b/` (`common` = guard allowance, self-test, write guard, network log; `download.py`, `measure.py`, `report.py`, `preserve.py`); guard extension in `src/acq_r01/common.py` (`sealed_candidates_v3` root + every candidate id refused by every patched reader; a named allowance for the §3 scripts only).
**Sealed root:** `/scratch/groups/hilley/auv_ship_colocated_bathy/sealed_candidates_v3` (directories 2750 setgid, files 0440; group `hilley` read only). **Evidence:** `guard_selftest.json`, `guard_log.jsonl`, `network_log.jsonl`, `download_manifest.json`, `SHA256SUMS_candidates`, `candidates_measured.json/.csv`, `candidate_table.csv`, `footprints/`, `must_hold_checks.json`.
**Steve's rulings (2026-10-13, recorded):** R1 downloading the candidate high-resolution grids is allowed, provided no output can bias the later test; R2 Pool B (NOS BAG) is dropped; R3 MGDS conditional terms (CC-BY-NC-SA) are accepted, as for the development corpus; R4 Escanaba Trough (MGDS:30368) stays a candidate; only its metadata has been seen; R5 Steve has not seen any Monterey Canyon AUV data (MGDS:24756); no prior exposure.
**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.

## 1. Bottom line

1. **9 of the 10 downloaded candidates are in range, forming 8 distinct sites; Kolumbo was not downloaded (CONFIRMED; `candidates_measured.csv`, `candidate_table.csv`).** Downloaded: 10 candidates, 1.74 GB, 123 files, sha256 in `SHA256SUMS_candidates`, sealed under `sealed_candidates_v3/` (dirs 2750 setgid, files 0440). In range: `MGDS:31860` (450 tiles, 2900 m, LR MV1003 Simrad EM122 2010, cells 5.05); `MGDS:31675` (527 tiles, 1600 m, LR KN173L02 SeaBeam 2112 2003, cells 4.58); `MGDS:31954` (331 tiles, 3100 m, LR AT26-24 Kongsberg EM122 2014, cells 4.75); `MGDS:30368` (3,918 tiles, 3300 m, LR Escanaba Simrad EM300 1998, cells 5.1); `MGDS:18210+MGDS:31811` (4,714 tiles, 1700 m, LR TN188 Simrad EM300 2005, cells 8.65); `MGDS:24756` (1,611 tiles, 1400 m, LR Monterey Simrad EM300 1998, cells 10.47); `MGDS:22436` (1,351 tiles, 3400 m, LR KN161L04 SeaBeam 2112 2000, cells 4.32); `MGDS:21415` (1,211 tiles, 600 m, LR MV1209 Kongsberg EM122 2012, cells 24.47). Outside range: `SEANOE:55744` (tiles_est 0 < 300). Excluded: `PANGAEA:958275` (every ship partner is restricted (HTTP 401 on the dataset file listing): no accessible ind…).
2. **Changes from ACQ-R08 (§5.3).** Moved into range: `MGDS:30368`, `MGDS:18210`, `MGDS:31811`, `MGDS:24756`, `MGDS:22436`, `MGDS:21415` — their catalog bounding boxes had made tiles and footprints upper bounds, and the measured footprints, depths and navigation coverage resolve them; the three ACQ-R08 in-range rows stay in range with fewer tiles than estimated (MGDS:31860 450, MGDS:31675 527, MGDS:31954 331) because the true validity masks are smaller than the catalog boxes and repeat epochs / grid versions are counted once. `SEANOE:55744` (Marmara) moved to outside range: its only accessible ship partner (M51/4, Hydrosweep DS-2, 2001) has no track within half a swath of the AUV footprint (per-file start positions from the PANGAEA listing). `PANGAEA:958275` (Kolumbo) is excluded: all five ship partners answer HTTP 401 on the file listing (§2 rule), nothing downloaded.
3. **Blindness (CONFIRMED; `guard_selftest.json`, `guard_log.jsonl`, `must_hold_checks.json`).** Guard self-test before the first download: 222 probes (37 sealed targets × 6 readers), 222 blocked, control file opened, no allowance installed; the §3 scripts then installed the named allowance (6 events logged). The sealed root and every candidate id are refused by every patched reader in every other process (this also seals the September copies `raw_hr/MGDS_30368` and `raw_hr/PANGAEA_958275` on OAK). Forbidden-statistic grep over 33 output/log files: 0 hits; image/plot files under the outputs: 0; every candidate has a status and reason; nothing designated.
4. **What was measured, and how (CONFIRMED; `candidates_measured.json`).** Per grid: header only (size, cell size, CRS, extent, nodata); validity mask from finite-and-not-nodata cells (|z| < 20 km); `hr_footprint` = union of the masks of the chosen resolution group, block-pooled to ≈ 50 m and simplified 50 m in local UTM; `valid_km2` = that union's area (sum over grids is reported separately, repeat epochs and versions counted once); `depth_median_100m` = the median of |z| over the chosen grids rounded to 100 m — the only depth-derived number; companion products (backscatter, amplitude, sidescan, count/sd, slope/shade, difference and interpolated grids) skipped by name; grids coarser than 5 m bundled with a record (La Jolla's 15 m regional grid) treated as context, the finest ≤ 5 m group covering ≥ 80 % of the largest ≤ 5 m group used.
5. **Ship side (CONFIRMED by listing).** Raw swath and `.fnv` navigation exist on NCEI for every NCEI cruise used (counts and GB in the table); coverage = per-file navigation tracks buffered by half the nominal swath width (3.5 × depth for Kongsberg EM12x/30x/EM300, 3.0 × for SeaBeam 2100/2112/2000, 2.0 × for Hydrosweep DS; documented in `common.SWATH_FACTOR`), intersected with the footprint; where the primary cruise gives < 300 tiles the ACQ-R08 alternatives are tried in order and the table's `lr_cruises_tried` records each attempt (every in-range row below used its primary cruise). `tiles_est` = 256-px windows at stride 128 with ≥ 50 % of cells inside footprint ∩ coverage on a raster at `hr_res_m` in local UTM.
6. **Same site (§3).** `MGDS:18210` and `MGDS:31811` (both AT15-63, Galápagos Spreading Center, 1 m and 2 m products) overlap and are one site; all other in-range candidates are > 10 km apart (nearest corpus footprint ≥ 106 km for every in-range row).
7. **Ship raw-swath volume for the later acquisition step (§5.2):** MV1003 37.44 GB, KN173L02 0.7 GB, AT26-24 1.34 GB, Escanaba 0.44 GB, TN188 3.89 GB, EW0004 0.18 GB, Monterey 9.33 GB, KN161L04 1.24 GB, MV1209 6.64 GB → 61.2 GB in total across the in-range sites.
8. **Challenge notes (applied as stated).** (i) `valid_km2` is reported as the union of the chosen grids' masks (the directive's 'area of the validity mask'), with the per-grid sum alongside; (ii) the finest-grid rule needed a cap at 5 m to ignore the regional ship grid bundled in the La Jolla record; (iii) Marmara's HR grid was downloaded (its ship partner listing answered 200) before coverage showed no overlap; it stays sealed. No HOLD raised.

## 2. Candidate table (§5.1; sites merged under `same_site_as`; sorted by status then `tiles_est`)

| status | hr_id | title | hr_res_m | crs | n_files | size_gb | valid_km2 | depth_median_100m | lr_cruise | lr_sonar | lr_year | lr_raw_downloadable | lr_swath_gb | ship_coverage_km2 | ship_coverage_fraction | lr_est_m | cells_across_est | ratio_est | tiles_est | same_site_as | nearest_corpus_ref | nearest_corpus_km | releasable | status_reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| in range | MGDS:30368 | Escanaba Trough (Gorda Ridge) AUV near-bottom processed swa… | 1.15 | ["OGC:CRS84"] | 2 | 0.1 | 84.44 | 3300 | Escanaba | Simrad EM300 | 1998 | True | 0.44 | 84.44 | 1 | 57.6 | 5.1 | 50.19 | 3918 |  | TN299__MGDS_27339 | 182.9 | yes_conditional |  |
| in range | MGDS:18210 + MGDS:31811 | Processed Near-bottom Grids (NetCDF:GMT format) derived fro… | 1 | ["EPSG:4326"] | 17 | 0.26 | 129.58 | 1700 | TN188 | Simrad EM300 | 2005 | True | 3.89 | 64.71 | 0.85 | 29.67 | 8.65 | 29.6 | 4714 | MGDS:31811 | AT42-03__MGDS_32007 | 1028.8 | yes_conditional | MGDS:18210: in range / MGDS:31811: in range |
| in range | MGDS:24756 | High-resolution (1m) bathymetric data from Monterey Canyon,… | 1 | ["EPSG:32610"] | 21 | 0.44 | 27.02 | 1400 | Monterey | Simrad EM300 | 1998 | True | 9.33 | 27.02 | 1 | 24.44 | 10.47 | 24.44 | 1611 |  | cal_dig_morro_bay__201804_LuciaChica2m | 106.1 | yes_conditional |  |
| in range | MGDS:22436 | Processed Sentry AUV bathymetry data from the Mid-Atlantic … | 2 | ["EPSG:4326"] | 7 | 0.08 | 90.61 | 3400 | KN161L04 | SeaBeam 2112 | 2000 | True | 1.24 | 90.61 | 1 | 118.69 | 4.32 | 59.25 | 1351 |  | MGDS:30198 | 301.7 | yes_conditional |  |
| in range | MGDS:21415 | Processed Near-bottom Bathymetry, Acoustic Backscatter, and… | 1 | ["EPSG:4326"] | 12 | 0.44 | 24.37 | 600 | MV1209 | Kongsberg EM122 | 2012 | True | 6.64 | 19.96 | 0.82 | 10.47 | 24.47 | 10.46 | 1211 |  | NA076__MGDS_32317 | 145.6 | yes_conditional |  |
| in range | MGDS:31675 | Processed Gridded Near-Bottom AUV Bathymetry Data acquired … | 1 | ["EPSG:4326"] | 25 | 0.13 | 9.16 | 1600 | KN173L02 | SeaBeam 2112 | 2003 | True | 0.7 | 8.98 | 0.98 | 55.86 | 4.58 | 55.85 | 527 |  | AR26__MGDS_31838 | 986.8 | yes_conditional |  |
| in range | MGDS:31860 | Processed Gridded Near-Bottom Bathymetry Data acquired duri… | 1 | ["EPSG:4326"] | 17 | 0.04 | 7.15 | 2900 | MV1003 | Simrad EM122 | 2010 | True | 37.44 | 7.15 | 1 | 50.62 | 5.05 | 50.68 | 450 |  | discol_so242_1 | 4544.1 | yes_conditional |  |
| in range | MGDS:31954 | Processed Gridded Near-Bottom AUV Bathymetry Data from the … | 1 | ["EPSG:4326"] | 10 | 0.05 | 5.58 | 3100 | AT26-24 | Kongsberg EM122 | 2014 | True | 1.34 | 5.58 | 1 | 54.11 | 4.75 | 53.94 | 331 |  | AT37-13__MGDS_31199 | 209.2 | yes_conditional |  |
| outside range | SEANOE:55744 |  | 2 | ["PROJCS[\"unnamed\",GEOGCS[\"WGS 84\",DATUM[\"WGS_1984\",S… | 1 | 0.18 | 98.91 | 700 | PANGAEA:975981 (M51/4 Hydrosweep DS-2) | Hydrosweep DS-2 |  | True |  | 0 | 0 | 28.1 | 18.22 | 14.05 | 0 |  | PANGAEA:941403 | 1112.9 | yes_conditional | tiles_est 0 < 300 |
| excluded | PANGAEA:958275 |  |  |  |  |  |  |  | PANGAEA:895437 (M143 EM122) |  |  |  |  |  |  |  |  |  |  |  |  |  |  | every ship partner is restricted (HTTP 401 on the dataset f… |

Not processed (directive §2): `MGDS:31979` — ROV point file, 0.04 km² (directive §2); `DOI:10.5285/31b8167c-4d8d-07f0-e063-7086abc03df1` — BODC BioCam record: broken footprint, implausible ship match (directive §2); `DOI:10.5285/31c95277-80ab-34ff-e063-7086abc04e84` — BODC BioCam record: broken footprint, implausible ship match (directive §2).

## 3. Summary (§5.2)

- **Distinct in-range sites: 8**, total `tiles_est` 14,113 (per site: MGDS:31860 450, MGDS:31675 527, MGDS:31954 331, MGDS:30368 3,918, MGDS:18210+MGDS:31811 4,714, MGDS:24756 1,611, MGDS:22436 1,351, MGDS:21415 1,211).
- **Settings and regions:** MGDS:31860 — Chile margin / triple-junction area (46.3°S), Sentry; MGDS:31675 — Bermuda platform (32.7°N), Sentry; MGDS:31954 — Dorado Outcrop, Cocos plate (9.1°N), Sentry; MGDS:30368 — Escanaba Trough, Gorda Ridge (41°N), AUV; MGDS:18210+MGDS:31811 — Galápagos Spreading Center (2.3°N), near-bottom multibeam; MGDS:24756 — Monterey Canyon (36.7°N), MBARI Mapping AUV, repeat surveys; MGDS:22436 — Mid-Atlantic Ridge 16.5°N, Sentry; MGDS:21415 — La Jolla Canyon (32.8°N), near-bottom. Basins: Pacific 6, Atlantic 2.
- **Ship raw swath to fetch later:** MV1003 37.44 GB, KN173L02 0.7 GB, AT26-24 1.34 GB, Escanaba 0.44 GB, TN188 3.89 GB, EW0004 0.18 GB, Monterey 9.33 GB, KN161L04 1.24 GB, MV1209 6.64 GB; total 61.2 GB (from NCEI listings; nothing fetched).
- **Downloaded HR volume:** 1.74 GB in 10 sealed directories; Kolumbo not downloaded.

## 4. Changes from ACQ-R08 (§5.3)

- `MGDS:30368`: uncertain → **in range** (all conditions hold)
- `MGDS:18210`: uncertain → **in range** (all conditions hold)
- `MGDS:24756`: uncertain → **in range** (all conditions hold)
- `MGDS:22436`: uncertain → **in range** (all conditions hold)
- `MGDS:21415`: uncertain → **in range** (all conditions hold)
- `MGDS:31811`: uncertain → **in range** (all conditions hold)
- `SEANOE:55744`: uncertain → **outside range** (tiles_est 0 < 300)
- `PANGAEA:958275`: uncertain → **excluded** (every ship partner is restricted (HTTP 401 on the dataset file listing): no accessible independent ship data → grid not downloaded (directive §2))

## 5. Exposure statement (§5.4) — the exact numbers produced per candidate

For every downloaded candidate the scripts wrote, and the executor saw, only: file names, sizes and sha256; grid width/height, cell size (native and metres), CRS, extent, nodata value and dtype per grid; the number of bathymetry grids and companion files skipped; `valid_km2`; the footprint polygon (block-pooled to ≈ 50 m, simplified 50 m) and its area; `depth_median_100m` (one integer, nearest 100 m); the ship cruise id, sonar, year, swath file count and size from listings; navigation-track counts, the half-swath buffer, ship-coverage polygon, area and fraction; `lr_est_m`, `cells_across_est`, `ratio_est`, `tiles_est`; `same_site_as`; nearest corpus footprint and distance; status and reason. No other depth-derived number exists in any output or log (check §6.2).

Per candidate:

- `MGDS:31860`: 17 files / 0.04 GB; 16 bathymetry grids (groups {"4.09": {"n_grids": 1, "valid_km2": 0.15}, "1.0": {"n_grids": 10, "valid_km2": 13.105}, "1.2": {"n_grids": 4, "valid_km2": 8.648}, "0.5": {"n_grids": 1, "valid_km2": 0.267}}); hr_res_m 0.9988; CRS ['EPSG:4326']; extent [-75.8319, -46.28808, -75.7892, -46.2155]; valid_km2 7.149; footprint 7.149 km²; depth_median_100m 2900; LR MV1003 (Simrad EM122, 2010; 905 swath files, 37.44 GB); coverage {"n_nav_files": 905, "n_tracks_in_aoi": 212, "method": "NCEI .fnv navigation tracks (per swath file) buffered by half the nominal swath width in local UTM", "half_swath_m": 5075.0, "coverage_km2": 7.149, "coverage_fraction": 1.0}; lr_est_m 50.62; cells 5.05; ratio 50.68; tiles_est 450; same_site_as —; nearest discol_so242_1 4544.1 km.
- `MGDS:31675`: 25 files / 0.134 GB; 25 bathymetry grids (groups {"1.0": {"n_grids": 13, "valid_km2": 23.576}, "1.09": {"n_grids": 12, "valid_km2": 19.295}}); hr_res_m 1.0002; CRS ['EPSG:4326']; extent [-64.58873, 32.70059, -64.5222, 32.73696]; valid_km2 9.159; footprint 9.159 km²; depth_median_100m 1600; LR KN173L02 (SeaBeam 2112, 2003; 22 swath files, 0.7 GB); coverage {"n_nav_files": 22, "n_tracks_in_aoi": 2, "method": "NCEI .fnv navigation tracks (per swath file) buffered by half the nominal swath width in local UTM", "half_swath_m": 2400.0, "coverage_km2": 8.981, "coverage_fraction": 0.981}; lr_est_m 55.86; cells 4.58; ratio 55.85; tiles_est 527; same_site_as —; nearest AR26__MGDS_31838 986.8 km.
- `MGDS:31954`: 10 files / 0.054 GB; 10 bathymetry grids (groups {"1.0": {"n_grids": 9, "valid_km2": 12.03}, "1.01": {"n_grids": 1, "valid_km2": 4.925}}); hr_res_m 1.0032; CRS ['EPSG:4326']; extent [-87.11276, 9.07017, -87.08229, 9.09632]; valid_km2 5.584; footprint 5.584 km²; depth_median_100m 3100; LR AT26-24 (Kongsberg EM122, 2014; 70 swath files, 1.34 GB); coverage {"n_nav_files": 70, "n_tracks_in_aoi": 35, "method": "NCEI .fnv navigation tracks (per swath file) buffered by half the nominal swath width in local UTM", "half_swath_m": 5425.0, "coverage_km2": 5.584, "coverage_fraction": 1.0}; lr_est_m 54.11; cells 4.75; ratio 53.94; tiles_est 331; same_site_as —; nearest AT37-13__MGDS_31199 209.2 km.
- `MGDS:30368`: 2 files / 0.102 GB; 2 bathymetry grids (groups {"1.15": {"n_grids": 2, "valid_km2": 79.652}}); hr_res_m 1.1477; CRS ['OGC:CRS84']; extent [-127.57511, 40.69307, -127.45118, 41.06768]; valid_km2 84.435; footprint 84.435 km²; depth_median_100m 3300; LR Escanaba (Simrad EM300, 1998; 32 swath files, 0.44 GB); coverage {"n_nav_files": 32, "n_tracks_in_aoi": 24, "method": "NCEI .fnv navigation tracks (per swath file) buffered by half the nominal swath width in local UTM", "half_swath_m": 5775.0, "coverage_km2": 84.435, "coverage_fraction": 1.0}; lr_est_m 57.6; cells 5.1; ratio 50.19; tiles_est 3918; same_site_as —; nearest TN299__MGDS_27339 182.9 km.
- `MGDS:18210`: 17 files / 0.232 GB; 17 bathymetry grids (groups {"1.0": {"n_grids": 17, "valid_km2": 80.057}}); hr_res_m 1.0025; CRS ['EPSG:4326']; extent [-95.0596, 2.07621, -91.82968, 2.6419]; valid_km2 75.786; footprint 75.786 km²; depth_median_100m 1700; LR TN188 (Simrad EM300, 2005; 1069 swath files, 3.89 GB); coverage {"n_nav_files": 1069, "n_tracks_in_aoi": 168, "method": "NCEI .fnv navigation tracks (per swath file) buffered by half the nominal swath width in local UTM", "half_swath_m": 2975.0, "coverage_km2": 64.711, "coverage_fraction": 0.854}; lr_est_m 29.67; cells 8.65; ratio 29.6; tiles_est 3917; same_site_as MGDS:31811; nearest AT42-03__MGDS_32007 1028.8 km.
- `MGDS:31811`: 11 files / 0.031 GB; 11 bathymetry grids (groups {"2.0": {"n_grids": 11, "valid_km2": 57.615}}); hr_res_m 2.0042; CRS ['EPSG:4326']; extent [-95.0606, 2.07576, -91.82913, 2.6421]; valid_km2 53.798; footprint 53.798 km²; depth_median_100m 2700; LR EW0004 (Atlas Hydrosweep DS, 2000; 41 swath files, 0.18 GB); coverage {"n_nav_files": 41, "n_tracks_in_aoi": 16, "method": "NCEI .fnv navigation tracks (per swath file) buffered by half the nominal swath width in local UTM", "half_swath_m": 2700.0, "coverage_km2": 53.798, "coverage_fraction": 1.0}; lr_est_m 108.4; cells 4.73; ratio 54.09; tiles_est 797; same_site_as MGDS:18210; nearest AT42-03__MGDS_32007 1028.7 km.
- `MGDS:24756`: 21 files / 0.444 GB; 12 bathymetry grids (groups {"1.0": {"n_grids": 12, "valid_km2": 125.598}}); hr_res_m 1.0; CRS ['EPSG:32610']; extent [-122.10612, 36.68939, -121.81673, 36.80763]; valid_km2 27.021; footprint 27.021 km²; depth_median_100m 1400; LR Monterey (Simrad EM300, 1998; 577 swath files, 9.33 GB); coverage {"n_nav_files": 577, "n_tracks_in_aoi": 238, "method": "NCEI .fnv navigation tracks (per swath file) buffered by half the nominal swath width in local UTM", "half_swath_m": 2450.0, "coverage_km2": 27.021, "coverage_fraction": 1.0}; lr_est_m 24.44; cells 10.47; ratio 24.44; tiles_est 1611; same_site_as —; nearest cal_dig_morro_bay__201804_LuciaChica2m 106.1 km.
- `MGDS:22436`: 7 files / 0.083 GB; 6 bathymetry grids (groups {"2.0": {"n_grids": 6, "valid_km2": 84.692}}); hr_res_m 2.0033; CRS ['EPSG:4326']; extent [-46.7216, 16.37543, -46.44775, 16.73504]; valid_km2 90.606; footprint 90.606 km²; depth_median_100m 3400; LR KN161L04 (SeaBeam 2112, 2000; 627 swath files, 1.24 GB); coverage {"n_nav_files": 627, "n_tracks_in_aoi": 37, "method": "NCEI .fnv navigation tracks (per swath file) buffered by half the nominal swath width in local UTM", "half_swath_m": 5100.0, "coverage_km2": 90.606, "coverage_fraction": 1.0}; lr_est_m 118.69; cells 4.32; ratio 59.25; tiles_est 1351; same_site_as —; nearest MGDS:30198 301.7 km.
- `MGDS:21415`: 12 files / 0.437 GB; 5 bathymetry grids (groups {"1.0": {"n_grids": 1, "valid_km2": 22.556}, "15.01": {"n_grids": 2, "valid_km2": 2188.503}, "1.09": {"n_grids": 2, "valid_km2": 22.698}}); hr_res_m 1.0006; CRS ['EPSG:4326']; extent [-117.44474, 32.85813, -117.28548, 32.93388]; valid_km2 24.373; footprint 24.373 km²; depth_median_100m 600; LR MV1209 (Kongsberg EM122, 2012; 268 swath files, 6.64 GB); coverage {"n_nav_files": 268, "n_tracks_in_aoi": 211, "method": "NCEI .fnv navigation tracks (per swath file) buffered by half the nominal swath width in local UTM", "half_swath_m": 1050.0, "coverage_km2": 19.961, "coverage_fraction": 0.819}; lr_est_m 10.47; cells 24.47; ratio 10.46; tiles_est 1211; same_site_as —; nearest NA076__MGDS_32317 145.6 km.
- `PANGAEA:958275`: nothing downloaded; ship-partner access checks only (HTTP status per PANGAEA dataset listing).
- `SEANOE:55744`: 1 files / 0.179 GB; 14 bathymetry grids (groups {"2.0": {"n_grids": 14, "valid_km2": 191.322}}); hr_res_m 2.0; CRS ['PROJCS["unnamed",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4326"]],PROJECTION["Mercator_2SP"],PARAMETER["standard_parallel_1",40],PARAMETER["central_meridian",0],PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Easting",EAST],AXIS["Northing",NORTH]]']; extent [27.46883, 40.7046, 29.14116, 40.88602]; valid_km2 98.913; footprint 98.913 km²; depth_median_100m 700; LR PANGAEA:975981 (M51/4 Hydrosweep DS-2) (Hydrosweep DS-2, ; 1 swath files, None GB); coverage {"n_nav_files": 52, "n_tracks_in_aoi": 5, "method": "PANGAEA tab-export per-file start positions joined into track segments (\u2264 20 km), buffered by half the nominal swath width", "half_swath_m": 700.0, "coverage_km2": 0.0, "coverage_fraction": 0.0}; lr_est_m 28.1; cells 18.22; ratio 14.05; tiles_est 0; same_site_as —; nearest PANGAEA:941403 1112.9 km.

## 6. Must hold (§4)

```
{
 "1_guard": {
  "selftest_probes": 222,
  "selftest_blocked": 222,
  "all_blocked": true,
  "control_opened": true,
  "selftest_before_allowance": true,
  "allowances": [
   {
    "t": "2026-10-13T15:50:50+00:00",
    "event": "allowance_installed",
    "script": "download.py",
    "tokens": [
     "sealed_candidates_v3"
    ],
    "pid": 22261
   },
   {
    "t": "2026-10-13T15:53:59+00:00",
    "event": "allowance_installed",
    "script": "measure.py",
    "tokens": [
     "sealed_candidates_v3"
    ],
    "pid": 22825
   },
   {
    "t": "2026-10-13T16:03:25+00:00",
    "event": "allowance_installed",
    "script": "measure.py",
    "tokens": [
     "sealed_candidates_v3"
    ],
    "pid": 24670
   },
   {
    "t": "2026-10-13T16:31:21+00:00",
    "event": "allowance_installed",
    "script": "measure.py",
    "tokens": [
     "sealed_candidates_v3"
    ],
    "pid": 29213
   },
   {
    "t": "2026-10-13T16:41:22+00:00",
    "event": "allowance_installed",
    "script": "measure.py",
    "tokens": [
     "sealed_candidates_v3"
    ],
    "pid": 7118
   },
   {
    "t": "2026-10-13T16:49:23+00:00",
    "event": "allowance_installed",
    "script": "measure.py",
    "tokens": [
     "sealed_candidates_v3"
    ],
    "pid": 11062
   }
  ],
  "guard_log_events": {
   "selftest": 1,
   "allowance_installed": 6
  }
 },
 "2_only_depth_median_100m": {
  "files_scanned": 33,
  "n_hits": 0,
  "depth_numbers_per_candidate": {
   "MGDS:31860": 2900,
   "MGDS:31675": 1600,
   "MGDS:31954": 3100,
   "MGDS:30368": 3300,
   "MGDS:18210": 1700,
   "MGDS:31811": 2700,
   "MGDS:24756": 1400,
   "MGDS:22436": 3400,
   "MGDS:21415": 600,
   "PANGAEA:958275": null,
   "SEANOE:55744": 700
  }
 },
 "3_no_images": {
  "files_under_outputs": 35,
  "image_or_plot_files": []
 },
 "4_all_have_status": true,
 "5_no_designation": {
  "designation_files": [],
  "seed": null,
  "split": null
 }
}
```

Network requests by kind: NCEI file listing (autoindex) ×110; PANGAEA dataset metadata / file listing ×8; SEANOE landing page / data file ×2; NCEI Geoportal record ×1.

## 7. HOLDs

None. Two judgment calls are recorded as challenge notes in §1.8 for Steve to overrule if wanted: the 5 m cap in the finest-grid rule, and the download of the Marmara grid before its coverage was known.

## 8. Not pursued

- Legacy single-beam NOS surveys as coarse partners; re-screening the 15 outside-range Pool A rows (directive §8).
- Any statistic, image or view of the candidate bathymetry beyond §3; downloading or gridding ship swath; co-registration; designation (§7).
