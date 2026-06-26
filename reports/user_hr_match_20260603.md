# v1.2 §C — Proposed user_file → sub_pair_id mapping

Threshold: name_score ≥ 0.30 AND IoU ≥ 0.80.
Pause for human confirmation before any re-harmonization.

## Proposed mapping (sorted; ✓ = meets IoU threshold)

| sub_pair | user_file | name | IoU | user km² | CMGDS km² | ∩ km² |
|---|---|---:|---:|---:|---:|---:|
| `20180426m1_PockmarkNorthDet` | `PockmarkNorth_MAUV_Topo1m_UTM_utm.tif` ✗ | 0.79 | 0.15 | 6.08 | 0.90 | 0.90 |
| `20180426m2_Channel1000` | `ChannelSurvey_1000_Topo1m_UTM_utm.tif` ✓ | 0.33 | 1.00 | 12.90 | 12.89 | 12.88 |
| `20180427m1_Channel700` | `Channel700_2m.tif` ✓ | 1.00 | 1.00 | 9.57 | 9.57 | 9.56 |
| `20180427m2_PockmarkSouthBasinFlank` | `PockmarkSouth_MAUV_Topo1m_UTM_utm.tif` ✗ | 0.52 | 0.68 | 9.17 | 13.55 | 9.17 |
| `20180427m3_PockmarkNorth` | `PockmarkNorth_MAUV_Topo1m_UTM_utm.tif` ✓ | 1.00 | 0.93 | 6.08 | 6.11 | 5.87 |
| `20180428m1_Cable` | `CableSurvey_MAUV_Topo1m_UTM_utm.tif` ✗ | 0.33 | 0.78 | 7.63 | 7.59 | 6.68 |
| `201804_LuciaChica2m` | `LuciaChica_2008_Topo1m_UTM_utm.tif` ✓ | 0.80 | 0.84 | 73.20 | 86.62 | 72.79 |
| `20190314m4_LuciaChica970m` | `LuciaChica970_2m.tif` ✓ | 0.92 | 1.00 | 5.67 | 5.66 | 5.66 |
| `20190315m1_HeadlessCanyon` | `HeadlessCanyon_Topo1m_converted.tif` ✓ | 1.00 | 0.99 | 11.93 | 11.93 | 11.88 |
| `20190316m1_BankTop` | `BankTopEofCanyon3_2m.tif` ✗ | 0.33 | 0.00 | 14.49 | 15.13 | 0.00 |
| `20190317m1_1000mGully` | `1000mGully_Topo1m_UTMinterp_utm.tif` ✓ | 1.00 | 0.81 | 10.54 | 8.59 | 8.59 |
| `20190317m2_600mGully` | `600mGully_Topo1m_UTMinterp_utm.tif` ✓ | 1.00 | 0.96 | 13.06 | 12.55 | 12.55 |
| `20190318m2_Transect601060m` | `Transect_60_1060m_Topo1m_interp_converted.tif` ✓ | 1.00 | 0.99 | 10.87 | 10.87 | 10.82 |
| `20190510m1_BankFlankHoles` | `BankFlankHoles_MAUV_Topo1m_UTM_utm.tif` ✓ | 1.00 | 0.99 | 12.63 | 12.46 | 12.46 |
| `20190510m2_BankFlankIncipCh` | `BankFlankIncipCh_2m.tif` ✓ | 1.00 | 1.00 | 12.34 | 12.33 | 12.32 |
| `20190511m1_6thHeadlessCany` | `6thHeadlessCanyon_2m.tif` ✓ | 0.87 | 1.00 | 14.12 | 14.12 | 14.11 |
| `20190511m2_BankTopEofCanyon3` | `BankTopEofCanyon3_2m.tif` ✓ | 1.00 | 1.00 | 14.49 | 14.49 | 14.48 |

## Collisions (same user file matched by >1 sub-pair)

- `PockmarkNorth_MAUV_Topo1m_UTM_utm.tif` → ['cal_dig_morro_bay__20180426m1_PockmarkNorthDet', 'cal_dig_morro_bay__20180427m3_PockmarkNorth']
- `BankTopEofCanyon3_2m.tif` → ['cal_dig_morro_bay__20190316m1_BankTop', 'cal_dig_morro_bay__20190511m2_BankTopEofCanyon3']

## Sub-pairs with no acceptable user-file match

- `20180426m1_PockmarkNorthDet`
- `20180427m2_PockmarkSouthBasinFlank`
- `20180428m1_Cable`
- `20190316m1_BankTop`

## User files not used in proposed mapping

- `600mGully_2m.tif`
- `BankFlankIncipientChannel_Topo1m_converted.tif`
- `BankTopEastofCanyon3_Topo1m_converted.tif`
- `BasinFlank_MAUV_Topo1m_UTM_utm.tif`
- `CableSurvey_MAUV_Topo1m_UTM_utm.tif`
- `ChannelSurvey_700_Topo1m_UTM_utm.tif`
- `HeadlessCanyon_2m.tif`
- `LuciaChica1100_2m.tif`
- `LuciaChica2019_repeat_1100m_Topo1m_UTM_utm.tif`
- `LuciaChica2019_repeat_970m_Topo1m_UTM_utm.tif`
- `LuciaChica_2007_Topo1m_UTM_utm.tif`
- `LuciaChica_2009_Topo1m_UTM_utm.tif`
- `MorroBay_all_2020_interp_32m_converted.tif`
- `PockmarkSouth_MAUV_Topo1m_UTM_utm.tif`
- `Transit_frmPocN_chan_cab_UTM_utm.tif`

## Rejected sub-pairs (stay rejected per addendum §C)

- `20190318m1_LuciaChica1100m` — true geographic non-overlap with LR (M1.5 §D.4).
- `20190319m1_8mPockmarkDetail` — true geographic non-overlap with LR (M1.5 §D.4).

These do not become valid pairs even if a user file with a matching name exists; clean HR does not create LR coverage.

## Required human action

Review the table above. Confirm each ✓ row OR explicitly approve a ✗ row (below threshold). Resolve any collisions. Reply with the approved mapping; no re-harmonization (§D) happens until then.
