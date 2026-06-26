# Phase 2 — Stage B raw-LR fetch report (2026-06-22)

Fetched the A.6 cleaned plan to `$DATA_ROOT/raw_lr/`. Swath + per-file `.fnv` only; **no `.fbt`**; one encoding per cruise; no gridding; manifest untouched; no OAK writes.

## Completeness (B3)

- Cleaned fetch list: **45 cruises** = **38 planned + fetched** + **7 escalated `needs_format_review`** (below).
- Planned files: **18448**
- Status identity holds: **True** (Σ status == planned)
- Status counts: {'fetched': 18339, 'failed': 106, 'size_mismatch_existing': 1, 'skip_present': 2}
- Cruises `complete`: **16**; `incomplete_for_grid`: **22**; `needs_format_review`: **7**
- Total received: **131.92 GB** (plan ≈ 131 GB; autoindex rounding ~1 %)

## ⚠️ needs_format_review (NOT fetched — legacy formats)

Legacy SeaBeam-classic cruises (1983–1991) whose date-named data files are not recognised by the swath classifier; `RP11SU81` carries only `.gps`/`.gps.inf` (no soundings). Budgeted at ≈0 GB in the plan. Recommend assessment rule on each (likely exclude — coarse legacy + format ambiguity) before Stage C.

- `AII8L11`: no recognised swath data (legacy format) — exts {'dir': 7, 'sc00': 6, 'noaa_inp': 5, 'sc01': 4, 'rc01': 3}
- `EW9914`: no recognised swath data (legacy format) — exts {'d336.gz': 1, 'd337.gz': 1, 'd338.gz': 1, 'd339.gz': 1, 'd340.gz': 1}
- `RC2901`: no recognised swath data (legacy format) — exts {'aac0': 31, 'rc00': 31, 'rc00.inf': 31, 'rsc0': 16, 'sc00': 16}
- `PASC04WT`: no recognised swath data (legacy format) — exts {'SBM.83apr02': 1, 'SBM.83apr03': 1, 'SBM.83apr04': 1, 'SBM.83apr05': 1, 'SBM.83apr06': 1}
- `PASC02WT`: no recognised swath data (legacy format) — exts {'SBM.83feb06': 1, 'SBM.83feb07': 1, 'SBM.83feb08': 1, 'SBM.83feb09': 1, 'SBM.83feb10': 1}
- `RP11SU81`: no recognised swath data (legacy format) — exts {'gps': 13, 'gps.inf': 13}
- `TUNE04WT`: no recognised swath data (legacy format) — exts {'SWSB.91oct07': 1, 'SWSB.91oct08': 1, 'SWSB.91oct09': 1, 'SWSB.91oct10': 1, 'SWSB.91oct11': 1}

## ⚠️ incomplete_for_grid (held from Stage C)

- `2009_Amundsen`: {'fetched': 719, 'failed': 35}
- `2010_Amundsen`: {'fetched': 206, 'failed': 16}
- `AR26`: {'fetched': 19, 'failed': 2, 'size_mismatch_existing': 1}
- `AT18-11`: {'fetched': 259, 'failed': 1}
- `AT37-13`: {'fetched': 159, 'failed': 1}
- `AT42-03`: {'fetched': 231, 'failed': 1}
- `AT42-06`: {'fetched': 179, 'failed': 1}
- `EW9801`: {'fetched': 49, 'failed': 1}
- `FK006B`: {'fetched': 373, 'failed': 15}
- `FK160407`: {'fetched': 421, 'failed': 1}
- `FK171110`: {'fetched': 78, 'failed': 2}
- `KN204-01`: {'fetched': 1068, 'failed': 2}
- `MV1209`: {'fetched': 535, 'failed': 1}
- `NA080`: {'fetched': 101, 'failed': 1}
- `NA090`: {'fetched': 93, 'failed': 1}
- `RB1604`: {'fetched': 10, 'failed': 4}
- `SKQ201705S`: {'fetched': 106, 'failed': 2}
- `TN268`: {'fetched': 173, 'failed': 1}
- `TN299`: {'fetched': 19, 'failed': 5}
- `TN313`: {'fetched': 65, 'failed': 7}
- `TN383`: {'fetched': 54, 'failed': 2}
- `TN399`: {'fetched': 16, 'failed': 4}

## Per-cruise received bytes

| cruise | GB | status |
|---|---|---|
| 2009_Amundsen | 24.97 | incomplete_for_grid |
| 2010_Amundsen | 20.35 | incomplete_for_grid |
| AR26 | 0.21 | incomplete_for_grid |
| AT18-11 | 8.08 | incomplete_for_grid |
| AT37-13 | 2.57 | incomplete_for_grid |
| AT42-03 | 4.36 | incomplete_for_grid |
| AT42-06 | 1.81 | incomplete_for_grid |
| Channel | 6.97 | complete |
| EW0207 | 1.33 | complete |
| EW9801 | 0.09 | incomplete_for_grid |
| EW9904 | 0.09 | complete |
| EX1103 | 5.00 | complete |
| Escanaba | 0.41 | complete |
| FK006B | 3.48 | incomplete_for_grid |
| FK160407 | 9.52 | incomplete_for_grid |
| FK171110 | 2.25 | incomplete_for_grid |
| FK181031 | 2.85 | complete |
| KIWI10RR | 0.91 | complete |
| KN204-01 | 3.24 | incomplete_for_grid |
| KN210-05 | 8.31 | complete |
| MGLN06MV | 0.04 | complete |
| MV1209 | 6.21 | incomplete_for_grid |
| NA076 | 2.12 | complete |
| NA080 | 0.49 | incomplete_for_grid |
| NA090 | 0.62 | incomplete_for_grid |
| RB1604 | 1.15 | incomplete_for_grid |
| RC2511 | 0.12 | complete |
| RR1506 | 3.83 | complete |
| SKQ201705S | 2.67 | incomplete_for_grid |
| TN157 | 0.20 | complete |
| TN159 | 0.81 | complete |
| TN234 | 0.05 | complete |
| TN268 | 1.70 | incomplete_for_grid |
| TN299 | 0.41 | incomplete_for_grid |
| TN313 | 2.21 | incomplete_for_grid |
| TN365 | 1.34 | complete |
| TN383 | 0.95 | incomplete_for_grid |
| TN399 | 0.16 | incomplete_for_grid |

## Notes

- MB-System not available as a Sherlock module; B2 content sanity used `gzip -t` (.gz) and `file` (uncompressed). Flag for Stage C, which needs MB-System for gridding.
- Only `complete` cruises advance to Stage C; `incomplete_for_grid` wait for assessment.
