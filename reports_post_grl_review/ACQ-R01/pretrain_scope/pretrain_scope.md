# Pretraining-corpus scoping (ACQ-R01 §5; estimate, no downloads)

| quantity | value |
|---|---|
| ncei_footprints_total | 3885 |
| ship_only | 3884 |
| excluded_by_survey_id | 262 |
| excluded_by_10km_zone | 412 |
| remaining_cruises | 3210 |
| sample_n | 244 |
| sample_ok | 236 |
| est_total_swath_tb | 25.3 |
| frac_griddable_unchanged_weighted | 0.925 |

**by_basin**

| key | n |
|---|---|
| Pacific | 1642 |
| Atlantic | 976 |
| Gulf of Mexico/Caribbean | 243 |
| Indian | 167 |
| Southern | 87 |
| Arctic | 75 |
| Mediterranean | 20 |

**by_family**

| key | n |
|---|---|
| Kongsberg EM12x (deep) | 972 |
| SeaBeam family | 848 |
| Kongsberg EM30x | 554 |
| Reson | 323 |
| Kongsberg EM7xx/EM1xxx/EM2040 (shallow) | 196 |
| other/unknown | 166 |
| Atlas Hydrosweep | 141 |
| ELAC | 10 |

**by_decade**

| key | n |
|---|---|
| 1980.0 | 269 |
| 1990.0 | 417 |
| 2000.0 | 1031 |
| 2010.0 | 1287 |
| 2020.0 | 204 |

**depth_distribution_sample(max depth m)**

| key | n |
|---|---|
| (0, 200] | 10 |
| (200, 1000] | 16 |
| (1000, 2000] | 15 |
| (2000, 3000] | 18 |
| (3000, 4000] | 15 |
| (4000, 6000] | 32 |
| (6000, 12000] | 8 |

**format_mix_sample(top ext)**

| key | n |
|---|---|
| .all.mb58.gz | 73 |
| .mb56.gz | 25 |
| .gsf.mb121.gz | 21 |
| .inf | 20 |
| .mb41.gz | 17 |
| .fnv | 12 |
| .mb84.gz | 11 |
| .mb94.gz | 10 |
| .mb21.gz | 8 |
| .mb58.gz | 4 |
| .mb121.gz | 4 |
| .fbt | 3 |

**exclusion_zone_inputs**

| key | n |
|---|---|
| pair_footprints | 37 |
| lockbox_lr_cruise_footprints | 2 |
| candidate_footprints | 16 |

**per instrument family**

| family | surveys | sampled | mean GB/survey | est total TB | griddable unchanged |
|---|---|---|---|---|---|
| Atlas Hydrosweep | 141 | 11 | 0.41 | 0.06 | 0.9090909090909091 |
| ELAC | 10 | 3 | 0.81 | 0.01 | 1.0 |
| Kongsberg EM12x (deep) | 972 | 75 | 8.01 | 7.78 | 1.0 |
| Kongsberg EM30x | 554 | 37 | 10.47 | 5.8 | 1.0 |
| Kongsberg EM7xx/EM1xxx/EM2040 (shallow) | 196 | 15 | 10.65 | 2.09 | 1.0 |
| Reson | 323 | 21 | 24.46 | 7.9 | 1.0 |
| SeaBeam family | 848 | 63 | 1.11 | 0.94 | 0.7301587301587301 |
| other/unknown | 166 | 11 | 4.48 | 0.74 | 1.0 |