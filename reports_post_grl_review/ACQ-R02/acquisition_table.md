## LR cruises fetched / gridded

| cruise | files | GB | complete | fmt | sonar | bw° | depth m | cell m | region | wall s |
|---|---|---|---|---|---|---|---|---|---|---|
| 2009_Amundsen | 377 | 26.58 | True | 58 | Kongsberg EM302 | 1.0 | 166.8 | 2.91 | patch cluster: 5 of 29 parts within 5 km of the part with th | 2250.5 |
| AT37-05 | 274 | 5.65 | True | 58 | Kongsberg EM122 | 1.0 | 3209.0 | 56.01 | whole footprint | 631.0 |
| AT42-06 | 90 | 1.93 | True | 58 | Kongsberg EM122 | 1.0 | 2515.7 | 43.91 | whole footprint | 94.4 |
| EX0909 | 368 | 5.15 | True | 162 | Simrad EM302 | 1.0 | 2000.0 | 34.91 | whole footprint | 613.7 |
| EX1202L2 | 323 | 7.21 | True | 162 | Simrad EM302 | 1.0 | 1354.0 | 23.63 | whole footprint | 825.5 |
| EX1202L3 | 279 | 7.0 | True | 163 | Simrad EM302 | 1.0 | 2000.0 | 34.91 | whole footprint | 410.6 |
| EX1206 | 614 | 15.45 | True | 162 | Kongsberg EM302 | 1.0 | 2000.0 | 34.91 | patch cluster: 36 of 47 parts within 5 km of the part with t | 1878.6 |
| EX1402L2 | 311 | 10.15 | True | 163 | Kongsberg EM302 | 1.0 | 937.7 | 16.37 | whole footprint | 2933.5 |
| FK151121 | 274 | 7.37 | True | 58 | Kongsberg EM302; EM710 | 1.0 | 3796.1 | 66.26 | whole footprint | 780.5 |
| FK171110 | 50 | 3.0 | True | 58 | Kongsberg EM302 | 1.0 | 2760.9 | 48.19 | whole footprint | 221.6 |
| KM0923 | 229 | 0.78 | True | 56 | Simrad EM120 | 1.0 | 4999.0 | 87.25 | whole footprint | 68.4 |
| KN182L03 | 28 | 1.17 | True | 41 | SeaBeam 2112 | 2.0 | 2956.9 | 103.23 | whole footprint | 85.5 |
| NA080 | 51 | 0.53 | True | 58 | Kongsberg EM302 | 1.0 | 3284.7 | 57.33 | whole footprint | 152.6 |
| NR07-1 | 58 | 0.9 | True | 56 | Simrad EM120 | 1.0 | 3008.3 | 52.51 | patch cluster: 582 of 721 parts within 5 km of the part with | 240.4 |
| RC2511 | 107 | 0.05 | True | 15 | SeaBeam | 2.0 | 3585.0 | 125.15 | whole footprint | 129.2 |
| SUM1004 | 222 | 4.68 | True | 121 | None | 1.5 | 5757.7 | 150.74 | patch cluster: 1 of 16 parts within 5 km of the part with th | 325.7 |
| TN399 | 10 | 0.17 | True | 58 | Kongsberg EM302 | 1.0 | 2547.6 | 44.46 | whole footprint | 120.7 |
| lostcity2005 | 758 | 2.42 | True | 94 | SeaBeam 2112 | 2.0 | 819.1 | 28.59 | whole footprint | 1684.5 |

## Pairs harmonized

| pair | set | unit | designation | HR res m | tiles | overlap km² | LR valid cells | joint km² | tiles≥50% | coreg off m | dz m | coreg | QA | MAD m | LR native m | k | v2 flags | v2 σ m | H1 x-check |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2009_Amundsen__MGDS_30047 | R01 | lu18 | development (joins existing unit) | 1.485 | 4 | 263.294 | 93869698 | 29.896 | 201 | 27.95 | -2.16 | pass | pass | 0.909 | 4.87 |  | registration_shift | 0.5655 |    |
| AT37-05__MGDS_24043 | R01 | vu05 | development (joins existing unit) | 1.001 | 12 | 14.679 | 14569248 | 4.261 | 71 | 18.41 | -73.9 | pass | pass | 20.773 | 55.99 | 4.0 | vertical_offset,registration_shift | 28.8933 |    |
| AT42-06__MGDS_5174 | H1 | lu05 | development (ruling H1) | 4.987 | 2 | 23.598 | 928514 | 8.267 | 4 | 11.15 | -9.63 | pass | pass | 0.877 | 44.5 | 2.0 | registration_shift | 0.9473 | no_processed_product_listed   |
| EX0909__MGDS_24002 | H1 | lu07 | development (ruling H1) | 2.054 | 2 | 95.912 | 0 | 0.0 | 0 |  |  | FAIL | fail |  | 34.91 | 4.0 | [Errno 2] No such file or directory: '/o |  | processed_product_not_a_float_grid (dtype uin   |
| EX1202L2__MGDS_20815 | H1 | vu00 | development (ruling H1) | 1.047 | 3 | 33.278 | 26222716 | 3.644 | 53 | 20.32 | -3.69 | pass | pass | 1.292 | 23.7 |  | registration_shift | 0.6358 | processed_product_not_a_float_grid (dtype uin   |
| EX1202L3__MGDS_31321 | H1 | vu00 | development (ruling H1) | 2.0 | 11 | 11.77 | 0 | 0.0 | 0 |  |  | FAIL | fail |  | 34.91 | 4.0 | [Errno 2] No such file or directory: '/o |  | processed_product_not_a_float_grid (dtype uin   |
| EX1206__MGDS_31831 | H1 | vu04 | development (ruling H1) | 1.18 | 3 | 17.351 | 0 | 0.0 | 0 |  |  | FAIL | fail |  | 34.91 | 8.0 | [Errno 13] Permission denied: '/lscratch |  | processed_product_not_a_float_grid (dtype uin   |
| EX1402L2__MGDS_31073 | H1 | vu02 | development (ruling H1) | 1.0 | 16 | 4.655 | 2890399 | 1.832 | 27 | 7.27 | -0.78 | pass | pass | 0.989 | 16.37 | 4.0 | registration_shift | 0.3644 | processed_product_not_a_float_grid (dtype uin   |
| FK151121__MGDS_22383 | R01 | nu00 | development | 1.0 | 5 | 25.515 | 25106512 | 12.117 | 184 | 9.05 | -6.22 | pass | pass | 6.087 | 65.99 | 16.0 | registration_shift | 3.2207 |    |
| FK171110__MGDS_24424 | R01 | lu01 | development (joins existing unit) | 1.001 | 2 | 11.831 | 11794167 | 0.012 | 0 | 6.43 | -22.54 | pass | fail | 5.684 | 47.92 | 16.0 |  | 1.1378 |    |
| KM0923__MGDS_31429 | R01 | lu07 | development (joins existing unit) | 2.054 | 2 | 95.912 | 17687830 | 15.517 | 57 | 13.96 | -15.72 | pass | pass | 8.162 | 86.94 | 16.0 | registration_shift | 4.7888 |    |
| KN182L03__MGDS_30193 | R01 | nu01a | confirmatory | 1.0 | 40 | 52.9 | 49930948 | 10.408 | 166 | 48.08 | -30.76 | FAIL | fail |  |  |  |  |  |    |
| NA080__MGDS_31289 | R01 | lu13 | development (joins existing unit) | 1.0 | 1 | 53.571 | 53473759 | 52.739 | 807 | 16.12 | -8.81 | pass | pass | 1.906 | 57.87 | 16.0 |  | 1.4169 |    |
| NR07-1__MGDS_31813 | H1 | vu03 | development (ruling H1) | 1.503 | 5 | 11.212 | 3716911 | 0.996 | 4 | 41.57 | 223.23 | FAIL | fail | 265.355 | 56.06 | 8.0 | registration_shift | 3.2864 | processed_product_is_xyz_points_not_gridded   |
| NR07-1__MGDS_31814 | H1 | vu03 | development (ruling H1) | 1.516 | 4 | 32.862 | 10579395 | 2.101 | 6 | 50.86 | 409.5 | FAIL | fail | 377.818 | 52.45 | 8.0 | registration_shift | 3.0956 | processed_product_is_xyz_points_not_gridded   |
| RC2511__MGDS_32239 | R01 | nu01b | confirmatory | 1.037 | 3 | 184.922 | 114085120 | 55.007 | 800 | 25.16 | 0.02 | pass | pass |  |  |  |  |  |    |
| SUM1004__MGDS_33090 | R01 | nu03 | confirmatory | 1.0 | 1 | 186.252 | 169995076 | 5.175 | 80 | 46.7 | -11.56 | FAIL | fail |  |  |  |  |  |    |
| TN399__MGDS_33068 | R01 | lu05 | development (joins existing unit) | 1.0 | 48 | 15.437 | 15119540 | 3.088 | 46 | 8.01 | 0.44 | pass | pass | 0.764 | 44.22 | 16.0 | registration_shift | 0.6287 |    |
| lostcity2005__MGDS_21847 | H1 | vu01 | development (ruling H1) | 4.997 | 1 | 6.434 | 168736 | 2.716 | 2 | 50.98 | 6.7 | FAIL | fail | 7.725 | 33.91 | 2.0 | registration_shift | 5.116 | insufficient_common_cells (0)   |