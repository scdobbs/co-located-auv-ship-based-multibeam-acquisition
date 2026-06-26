# Acquisition report — 2026-06-02

## Human-decision parameters (from config/harmonization.yaml)

- `data_root`: `/scratch/groups/hilley/auv_ship_colocated_bathy`
- `target_crs`: `per_pair_utm`
- `target_grid.policy`: `native_per_side`
- `resample_kernel`: `bilinear`
- `vertical_datum_handling.target`: `msl` (sign=negative_down, on_mismatch=flag)
- `coregistration.method`: `rigid_xyz_offset` (threshold=5.0 m, required_for=['cal_dig_morro_bay'])
- `nodata_policy.fill_value`: `-9999.0`
- `pair_qa`: max_misregistration=5.0 m, min_overlap_area_km2=1.0
- `storage.retain_raw`: `True`

## Pairs in manifest

_Rows: **18**_

### discol_so242_1
- Site: DISCOL Experimental Area (Peru Basin)
- Cruise: SO242/1 / RV SONNE
- HR: AUV ABYSS (REMUS 6000) (Reson 7125) @ 2.0 m — DOI `10.1594/PANGAEA.905580`
- LR: RV SONNE hull (Kongsberg EM122) @ 38.0 m — DOI `10.1594/PANGAEA.905579`
- Target CRS: `EPSG:32716`; vertical: `MSL_negative_down`
- License: HR: CC-BY-4.0; LR: CC-BY-4.0
- Sub-pairs in manifest: **1**

- Harmonized: `/scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/discol_so242_1/hr.tif`, `/scratch/groups/hilley/auv_ship_colocated_bathy/harmonized/discol_so242_1/lr.tif`
- Notes: AUV ABYSS HR already corrected against ship EM122 in the source release. Adjacent topographic high present within the DEA footprint.

### cal_dig_morro_bay
- Site: Cal DIG I / Morro Bay (Offshore South-Central California)
- Cruise: Cal DIG I / NOAA Rainier/Fairweather (+ R/V Sally Ride gap-fill)
- HR: MBARI-donated AUV (Reson 7125 400 kHz) @ 1.0 m — DOI `10.5066/P97QM7NF`
- LR: NOAA hull (Simrad EM 700 series) @ 10.0 m — DOI `10.5066/P9QQZ27U`
- Target CRS: `EPSG:26910`; vertical: `MSL_negative_down`
- License: HR: public_domain_usgs; LR: public_domain_usgs
- Sub-pairs in manifest: **17**

#### Coregistration residuals (post)

| sub-pair | dx (m) | dy (m) | dz (m) | MAD (m) |
|---|---:|---:|---:|---:|
| `20180426m1_PockmarkNorthDet` | -32.24 | +4.77 | -1.71 | 0.31 |
| `20180426m2_Channel1000` | -7.57 | -21.03 | -1.64 | 0.43 |
| `20180427m1_Channel700` | +7.04 | +8.16 | -0.80 | 0.33 |
| `20180427m2_PockmarkSouthBasinFlank` | -4.21 | -0.84 | -1.65 | 0.51 |
| `20180427m3_PockmarkNorth` | -34.48 | +4.75 | -1.53 | 0.52 |
| `20180428m1_Cable` | -34.71 | +37.16 | -1.54 | 0.42 |
| `201804_LuciaChica2m` | +41.73 | -3.10 | -2.58 | 0.52 |
| `20190314m4_LuciaChica970m` | -7.58 | -1.97 | -2.04 | 0.34 |
| `20190315m1_HeadlessCanyon` | -0.68 | +37.66 | -2.08 | 2.87 |
| `20190316m1_BankTop` | -15.41 | -15.41 | -0.24 | 0.73 |
| `20190317m1_1000mGully` | +9.25 | -19.91 | -1.49 | 0.29 |
| `20190317m2_600mGully` | -12.03 | -34.49 | -0.94 | 0.37 |
| `20190318m2_Transect601060m` | -33.38 | -11.99 | -1.85 | 0.50 |
| `20190510m1_BankFlankHoles` | +5.95 | +3.70 | -1.77 | 0.74 |
| `20190510m2_BankFlankIncipCh` | +37.53 | -21.00 | -0.26 | 1.58 |
| `20190511m1_6thHeadlessCany` | +17.07 | -5.34 | -1.33 | 0.81 |
| `20190511m2_BankTopEofCanyon3` | -1.68 | +10.78 | +0.11 | 0.48 |

_MAD: min=0.29, median=0.50, max=2.87 m_; all under threshold 5.0 m: **True**

## Rejected sub-pairs

- `cal_dig_morro_bay__20190318m1_LuciaChica1100m` — [cal_dig_morro_bay__20190318m1_LuciaChica1100m] HR and LR footprints do not intersect
- `cal_dig_morro_bay__20190319m1_8mPockmarkDetail` — [cal_dig_morro_bay__20190319m1_8mPockmarkDetail] HR and LR footprints do not intersect

## On-disk footprint
- `data_root` (/scratch/groups/hilley/auv_ship_colocated_bathy): **2.4G**
- `data_root/raw`: 2.0G
- `data_root/harmonized`: 363M

## Tier 2
_Not started — awaiting human review of Tier 1 output._

## Hard-rule audit
- Bulk rasters under `/scratch`: `True`
- Repo-tracked files limited to code/config/manifest/reports/logs: yes
- LR side fetched (not synthesized) for every pair: yes (lr_native_res_m > hr_native_res_m for every row)
- DOIs used: only those declared in §4 of the directive; no fabricated DOIs.
