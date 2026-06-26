# M1.7 — Cal DIG HR remediation + figures (2026-06-03)

Implements v1.2 + v1.2.1 addenda. DISCOL untouched. Cal DIG LR (`10.5066/P9QQZ27U`) untouched. Tier 2 still blocked pending figure approval.

## Approved mapping (v1.2.1 §1)

- HR target GSD: **2.0 m** (uniform 5× ratio against 10 m LR).
- Single warp EPSG:32610 → EPSG:26910: `average` when input < 2 m, `cubic` when input = 2 m.
- Drop list (removed from manifest, no CMGDS fallback): `cal_dig_morro_bay__20180426m1_PockmarkNorthDet` (detail subset wholly inside PockmarkNorth).
- New pairs: `cal_dig_morro_bay__luciachica_2007`, `cal_dig_morro_bay__luciachica_2009` (v1.2.1 §4 — no CMGDS ancestor).
- Stays rejected: `cal_dig_morro_bay__20190318m1_LuciaChica1100m`, `cal_dig_morro_bay__20190319m1_8mPockmarkDetail` (no LR coverage).
- Mosaic: `cal_dig_morro_bay__20180427m2_PockmarkSouthBasinFlank` combines `PockmarkSouth_MAUV` + `BasinFlank_MAUV` (user export split this CMGDS survey).

## §B sidecar attestation status

- Attested artifact-free (`true`): **0**
- Attested artifacted (`false`): **0**
- Pending (`null`): **28**

_Sidecar files live at `$DATA_ROOT/user-provided-cal-dig/*.tif.provenance.json`. Set `attested_artifact_free: true|false` for each before declaring §B complete._

## §8 — `axis_excess` metric dropped

Removed from `FileInfo`, the inventory report, and the provenance sidecar schema. The hillshade + FFT images still feed the §7(a) contact sheet (`reports/user_hr_artifact_contact_sheet_p0?.png`). Artifact-free status is human-attested visually.

## §2 — HR standardization to 2 m (single warp)

| pair | native CRS | native GSD | kernel | output |
|---|---|---:|---|---|
| `20180426m2_Channel1000` | EPSG:32610 | 1.00 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20180426m2_Channel1000/hr.tif |
| `20180427m1_Channel700` | EPSG:32610 | 2.00 m | cubic | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20180427m1_Channel700/hr.tif |
| `20180427m3_PockmarkNorth` | EPSG:32610 | 1.00 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20180427m3_PockmarkNorth/hr.tif |
| `20180428m1_Cable` | EPSG:32610 | 1.00 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20180428m1_Cable/hr.tif |
| `201804_LuciaChica2m` | EPSG:32610 | 1.00 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/201804_LuciaChica2m/hr.tif |
| `20190314m4_LuciaChica970m` | EPSG:32610 | 2.00 m | cubic | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20190314m4_LuciaChica970m/hr.tif |
| `20190315m1_HeadlessCanyon` | EPSG:32610 | 1.02 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20190315m1_HeadlessCanyon/hr.tif |
| `20190316m1_BankTop` | EPSG:32610 | 2.00 m | cubic | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20190316m1_BankTop/hr.tif |
| `20190317m1_1000mGully` | EPSG:32610 | 1.00 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20190317m1_1000mGully/hr.tif |
| `20190317m2_600mGully` | EPSG:32610 | 1.00 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20190317m2_600mGully/hr.tif |
| `20190318m2_Transect601060m` | EPSG:32610 | 1.03 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20190318m2_Transect601060m/hr.tif |
| `20190510m1_BankFlankHoles` | EPSG:32610 | 1.00 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20190510m1_BankFlankHoles/hr.tif |
| `20190510m2_BankFlankIncipCh` | EPSG:32610 | 2.00 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20190510m2_BankFlankIncipCh/hr.tif |
| `20190511m1_6thHeadlessCany` | EPSG:32610 | 2.00 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/20190511m1_6thHeadlessCany/hr.tif |
| `luciachica_2007` | EPSG:32610 | 1.00 m | average | /scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/cal_dig_morro_bay/luciachica_2007/hr.tif |

## §6 — Coregistration results (fresh; no CMGDS reuse)

| pair | overlap km² | h (m) | v (m) | PSR | eig | agrees | status |
|---|---:|---:|---:|---:|---:|---:|---|
| `20180426m2_Channel1000` | — | 21.5 | 1.66 | 5.14 | 2.98 | ✗ | needs_review |
| `20180427m1_Channel700` | — | 10.0 | 0.81 | 5.92 | 1.99 | ✓ | needs_review |
| `20180427m3_PockmarkNorth` | — | 0.0 | 1.68 | 5.94 | 3.44 | ✓ | needs_review |
| `20180428m1_Cable` | — | 56.6 | 0.40 | 5.61 | 12.62 | ✗ | needs_review |
| `201804_LuciaChica2m` | — | 34.2 | 3.27 | 5.84 | 1.35 | ✗ | needs_review |
| `20190314m4_LuciaChica970m` | — | 8.2 | 2.05 | 6.56 | 2.64 | ✓ | needs_review |
| `20190315m1_HeadlessCanyon` | — | 42.0 | 1.54 | 5.07 | 23.88 | ✗ | needs_review |
| `20190316m1_BankTop` | — | 22.8 | 0.22 | 4.96 | 2.21 | ✗ | needs_review |
| `20190317m1_1000mGully` | — | 19.7 | 1.45 | 5.21 | 2.65 | ✗ | needs_review |
| `20190317m2_600mGully` | — | 40.5 | 1.02 | 4.52 | 2.74 | ✗ | needs_review |
| `20190318m2_Transect601060m` | — | 37.9 | 1.90 | 4.25 | 1.83 | ✗ | needs_review |
| `20190510m1_BankFlankHoles` | — | 7.2 | 1.80 | 11.78 | 1.16 | ✓ | needs_review |
| `20190510m2_BankFlankIncipCh` | — | 47.4 | 0.30 | 9.91 | 4.36 | ✗ | needs_review |
| `20190511m1_6thHeadlessCany` | — | 17.1 | 1.42 | 8.11 | 1.27 | ✗ | needs_review |
| `luciachica_2007` | — | 32.1 | 2.68 | 6.64 | 6.00 | ✗ | needs_review |

## §4 — New-pair LR-overlap verdicts (LuciaChica 2007 + 2009)

- `cal_dig_morro_bay__luciachica_2007` — **needs_review** (User-provided HR (single warp to 2 m EPSG:26910 with `average` resample; native GSD 1.00 m, native CRS EPSG:32610). New pair (no CMGDS ancestor; v1.2.1 §4). Coreg: dx=+32.00 m, dy=+2.00 m, dz=-2.68 m; post-residual MAD=0.50 m.)
- `cal_dig_morro_bay__luciachica_2009` — _not in manifest (re-harmonization not run or failed)_

## §5 — LuciaChica pairwise IoU matrix (informational; not a gate)

| | 2007 | 2008 | 2009 | 2019_970m |
|---|---|---|---|---|
| 2007 | 1.00 | 0.07 | 0.02 | 0.23 |
| 2008 | 0.07 | 1.00 | 0.14 | 0.07 |
| 2009 | 0.02 | 0.14 | 1.00 | 0.00 |
| 2019_970m | 0.23 | 0.07 | 0.00 | 1.00 |

## §7 — Figures

**(a) Artifact contact sheet** — `reports/user_hr_artifact_contact_sheet_p01.png` and `_p02.png`.

**(b) Master LR-vs-HR figure** — `reports/cal_dig_master_lr_vs_hr.pdf` + `cal_dig_master_lr_vs_hr.png`.

## Audit + manifest state

- Manifest rows: **18** (17 Cal DIG, 1 DISCOL).
- Run `python -m src.cli audit` to re-verify provenance (LR DOI-match still required; user_provided HR now goes through the v1.2 §E branch).

## Gate

- **Pause:** human approval of the §7 figures + per-pair clearance via the new overlay PNGs.
- Tier 2 stays blocked until every Cal DIG pair is `auto_pass` or human-cleared AND the master figure is approved.
