# Discovery re-run — counts only (ACQ-R01 §3)

Catalog date 2026-09-29. HR in stage-A selection: 130.

| status | n |
|---|---|
| previously_excluded | 56 |
| in_corpus | 49 |
| new_candidate | 16 |
| gate_excluded | 5 |
| render_no_elevation | 2 |
| not_auv_bathymetry | 2 |

New candidates by June gate tier: {"needs_geometry": 13, "training": 1, "eval_only": 1, "raw_lr_to_grid": 1}
New candidates by k prior (empirical, ±1 octave): {"8.0": 5, "16.0": 5, "NaN": 4, "2.0": 1, "4.0": 1}
Footprint unverified (metadata bbox, > plausible AUV area): 13
Join an existing unit (shared acquisition / ≤50 km): 9 · share acquisition with a lockbox pair: 0
**New leakage units: 4** by setting {"volcanic_or_seamount": 1, "mixed:continental_margin|volcanic_or_seamount": 1, "continental_margin": 1, "abyssal_plain": 1}; by basin {"Pacific": 3, "Atlantic": 1}

| unit | n | basin | setting | depth (m) | ship cruise(s) | HR source | est. vol GB (HR / LR raw) | lr_native doc (m) | ratio | k prior |
|---|---|---|---|---|---|---|---|---|---|---|
| nu00 | 2 | Pacific | volcanic_or_seamount | -4407.1123–-3185.042 | FK151121 | MGDS:22383 10.1594/IEDA/322383; MGDS:22384 10.1594/IEDA/322384 | 0.16 / 8.12 | [66.3, nan] | [66.3, nan] | [16.0, nan] |
| nu01 | 2 | Atlantic | mixed:continental_margin|volcanic_or_seamount | -4464.354–-998.681 | KN182L03, RC2511 | MGDS:30193 10.26022/IEDA/330193; MGDS:32239  | 0.9 / 1.56 | [112.1, 95.4] | [112.1, 121.5] | [16.0, 16.0] |
| nu02 | 1 | Pacific | continental_margin | -3367.811–-3149.308 | RP15DI86 | MGDS:30368 10.26022/IEDA/330368 | 0.1 / 0.01 | [113.8] | [114.0] | [16.0] |
| nu03 | 2 | Pacific | abyssal_plain | -5807.713–-3683.719 | SUM1004 | MGDS:33081 10.60521/333081; MGDS:33090 10.60521/333090 | 0.17 / 5.61 | [nan, nan] | [nan, nan] | [nan, nan] |

## Candidates joining an EXISTING unit (neither development nor confirmatory)

| hr_id | title | best LR | joins | near pairs |
|---|---|---|---|---|
| MGDS:31429 | Loihi Seamount (Hawaii), Shinkai Deep and FeMO hydrothermal  | KM0923 | lu07 | EW9801__MGDS_31425 |
| MGDS:16792 | Processed Near-bottom Bathymetry Grids (NetCDF:GMT format) d | FK171110 | lu01 | KIWI10RR__MGDS_24499 |
| MGDS:24424 | Processed Gridded Near-Bottom AUV Sentry Bathymetry Data fro | FK171110 | lu01 | KIWI10RR__MGDS_24499 |
| MGDS:30047 | Processed bathymetry data (ESRI ASCII grids) acquired near-b | 2009_Amundsen | lu18 | 2009_Amundsen__MGDS_30046 |
| MGDS:33027 | Near-bottom multibeam bathymetry gridded data collected by A | PASC02WT | lu05 | TN399__MGDS_30373 |
| MGDS:31289 | Near-bottom AUV multibeam bathymetry grid (netCDF format) fr | NA080 | lu13 | NA080__MGDS_31290 |
| MGDS:33068 | Processed Gridded Near-Bottom AUV Bathymetry Data (EM2040) f | TN399 | lu05 | TN399__MGDS_30373 |
| MGDS:24043 | Gridded Near-Bottom Bathymetry Data from the Siqueiros Fract | AT37-05 | lu05 |  |
| MGDS:24449 | Processed Near-Bottom AUV REMUS 600 Bathymetry Data (ASCII f | KM0303 | lu07 |  |

## Candidates sharing acquisition with a LOCKBOX pair (excluded from §4)

| hr_id | title | HR cruise | LR cruises |
|---|---|---|---|