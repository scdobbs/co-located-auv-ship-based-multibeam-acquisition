# Stage 1 staging-download report — rev 2 (2026-06-05)

*Phase 1 remediation per directive v1.5.4 rev 2. No reclassify / no gate edit / no re-tier — diagnoses only.*

## Remediation summary

### R0 — MGDS:30272 stub inspection + re-fetch

- Stub bytes (pre-delete): **0** (expected 4517897)
- Stub body (first ~400 chars, escaped newlines):

  > ``

- Re-fetch URL: `https://api.marine-geo.org/services/download/Document_Accept.php?client=DataLink&data_uid=2427151`
- Re-fetch bytes received: **278** (expected 4517897)
- Final status: **FETCH_FAILED_ESCALATE**

### R1 — MGDS:31600 quarantine + measurement

- Quarantine path: `/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600`
- Declared `hr_native_res_m`: **9.8 m**
- Measured finest cell (across all files): **2.813581300831454 m** (ratio 0.28710013273790347)
- `looks_like` verdict: **coarse_or_composite**

Per-file measurements:

| file | crs | cx_native | cy_native | mean_lat | cx_m | cy_m | finest_m | error |
|---|---|---|---|---|---|---|---|---|
| d142.v7.latlon.grd | (inferred geographic from coord ranges) [gmt_classic] | 2.776235424764257e-05 | 2.7762354247640593e-05 | 23.575000000000003 | 2.813581300831454 | 3.069794558578611 | 2.813581300831454 |  |
| d142.v7.latlon.grd.gz | (inferred geographic from coord ranges) [gmt_classic] | 2.776235424764257e-05 | 2.7762354247640593e-05 | 23.575000000000003 | 2.813581300831454 | 3.069794558578611 | 2.813581300831454 |  |
| d144.v7.latlon.grd | (inferred geographic from coord ranges) [gmt_classic] | 2.7770063871147297e-05 | 2.777006387114631e-05 | 23.46666666666667 | 2.816679665916239 | 3.0706470424881323 | 2.816679665916239 |  |
| d144.v7.latlon.grd.gz | (inferred geographic from coord ranges) [gmt_classic] | 2.7770063871147297e-05 | 2.777006387114631e-05 | 23.46666666666667 | 2.816679665916239 | 3.0706470424881323 | 2.816679665916239 |  |
| d145.v7.latlon.grd | (inferred geographic from coord ranges) [gmt_classic] | 2.776852160390823e-05 | 2.7768521603909413e-05 | 23.475 | 2.8163453699206507 | 3.0704765078306795 | 2.8163453699206507 |  |
| d145.v7.latlon.grd.gz | (inferred geographic from coord ranges) [gmt_classic] | 2.776852160390823e-05 | 2.7768521603909413e-05 | 23.475 | 2.8163453699206507 | 3.0704765078306795 | 2.8163453699206507 |  |
| d146.v7.latlon.grd | (inferred geographic from coord ranges) [gmt_classic] | 2.775464890368979e-05 | 2.7759271596714092e-05 | 23.479166666666664 | 2.8148494588673394 | 3.069453697535064 | 2.8148494588673394 |  |
| d146.v7.latlon.grd.gz | (inferred geographic from coord ranges) [gmt_classic] | 2.775464890368979e-05 | 2.7759271596714092e-05 | 23.479166666666664 | 2.8148494588673394 | 3.069453697535064 | 2.8148494588673394 |  |
| d148.v7.latlon.1sec.grd | (inferred geographic from coord ranges) [gmt_classic] | 0.0002767527675276858 | 0.00027548209366392554 | 23.483333333333334 | 28.067109411822898 | 30.461157024794904 | 28.067109411822898 |  |
| d148.v7.latlon.1sec.grd.gz | (inferred geographic from coord ranges) [gmt_classic] | 0.0002767527675276858 | 0.00027548209366392554 | 23.483333333333334 | 28.067109411822898 | 30.461157024794904 | 28.067109411822898 |  |
| d148.v7.latlon.tenthsec.grd | (inferred geographic from coord ranges) [gmt_classic] | 2.776749352091923e-05 | 2.7754648903692748e-05 | 23.483333333333334 | 2.8160631805272143 | 3.068942547876922 | 2.8160631805272143 |  |
| d148.v7.latlon.tenthsec.grd.gz | (inferred geographic from coord ranges) [gmt_classic] | 2.776749352091923e-05 | 2.7754648903692748e-05 | 23.483333333333334 | 2.8160631805272143 | 3.068942547876922 | 2.8160631805272143 |  |
| d149.v7.latlon.1sec.grd | (inferred geographic from coord ranges) [gmt_classic] | 0.0002772002772002762 | 0.0002766251728907321 | 23.483333333333334 | 28.11249397312521 | 30.58755186721981 | 28.11249397312521 |  |
| d149.v7.latlon.1sec.grd.gz | (inferred geographic from coord ranges) [gmt_classic] | 0.0002772002772002762 | 0.0002766251728907321 | 23.483333333333334 | 28.11249397312521 | 30.58755186721981 | 28.11249397312521 |  |
| d149.v7.latlon.tenthsec.grd | (inferred geographic from coord ranges) [gmt_classic] | 2.7771991946122236e-05 | 2.7766208524225917e-05 | 23.483333333333334 | 2.8165193920169185 | 3.0702207413577565 | 2.8165193920169185 |  |
| d149.v7.latlon.tenthsec.grd.gz | (inferred geographic from coord ranges) [gmt_classic] | 2.7771991946122236e-05 | 2.7766208524225917e-05 | 23.483333333333334 | 2.8165193920169185 | 3.0702207413577565 | 2.8165193920169185 |  |
| dome.v7.latlon.1sec.grd | (inferred geographic from coord ranges) [gmt_classic] | 0.0002773155851358807 | 0.0002766251728907321 | 23.483333333333334 | 28.12418802219859 | 30.58755186721981 | 28.12418802219859 |  |
| dome.v7.latlon.1sec.grd.gz | (inferred geographic from coord ranges) [gmt_classic] | 0.0002773155851358807 | 0.0002766251728907321 | 23.483333333333334 | 28.12418802219859 | 30.58755186721981 | 28.12418802219859 |  |
| dome.v7.latlon.tenthsec.grd | (inferred geographic from coord ranges) [gmt_classic] | 2.7771606309708954e-05 | 2.7766208524225917e-05 | 23.483333333333334 | 2.8164802823830692 | 3.0702207413577565 | 2.8164802823830692 |  |
| dome.v7.latlon.tenthsec.grd.gz | (inferred geographic from coord ranges) [gmt_classic] | 2.7771606309708954e-05 | 2.7766208524225917e-05 | 23.483333333333334 | 2.8164802823830692 | 3.0702207413577565 | 2.8164802823830692 |  |
| valley.latlon.grd | (inferred geographic from coord ranges) [gmt_classic] | 2.7767015368719657e-05 | 2.776492364645938e-05 | 23.475 | 2.816192604189732 | 3.0700786672835996 | 2.816192604189732 |  |
| valley.latlon.grd.gz | (inferred geographic from coord ranges) [gmt_classic] | 2.7767015368719657e-05 | 2.776492364645938e-05 | 23.475 | 2.816192604189732 | 3.0700786672835996 | 2.816192604189732 |  |

### R2 — corpus-wide cell-size sanity sweep

- HR scanned: **75**
- `ok`: **61**, `quarantined`: **0**, `flagged`: **14**
- CSV: `reports/discovery/hr_resolution_sanity.csv`

Flagged HR (non-ok, non-quarantined):

| hr_id | declared_m | measured_m | ratio | verdict | files |
|---|---:|---:|---:|---|---:|
| MGDS:20836 | — | — | — | no_grid_found | 0 |
| MGDS:21415 | 4.11695117961282 | 0.9922243485012561 | 0.24 | flag_mismatch | 24 |
| MGDS:21454 | 1.378009514248073 | 0.49551315625693043 | 0.36 | flag_mismatch | 88 |
| MGDS:21462 | 2.0192808462984058 | 0.9910175535248701 | 0.49 | flag_mismatch | 50 |
| MGDS:24425 | — | — | — | no_grid_found | 0 |
| MGDS:24467 | 0.48168361881991967 | 0.09910467494961438 | 0.21 | flag_mismatch | 44 |
| MGDS:24470 | 0.5240616408693941 | 0.09915857701475252 | 0.19 | flag_mismatch | 8 |
| MGDS:30272 | 4.0 | — | — | no_grid_found | 0 |
| MGDS:31253 | 0.6239641860455681 | 0.2478828685803217 | 0.4 | flag_mismatch | 4 |
| MGDS:31254 | 0.540975715305519 | 0.2149252268957566 | 0.4 | flag_mismatch | 4 |
| MGDS:31255 | 0.5327510583218268 | 0.2116732973254224 | 0.4 | flag_mismatch | 4 |
| MGDS:31321 | 0.5717333025035013 | 0.2478903004829613 | 0.43 | flag_mismatch | 104 |
| MGDS:31860 | 1.0915751445057353 | 0.49568091786853274 | 0.45 | flag_mismatch | 32 |
| PANGAEA:tag_m127 | 2.0 | — | — | no_grid_found | 0 |

## Verification gates (corrected)

| # | gate | result | detail |
|---|---|---|---|
| 1_hr_byte_exactness_corrected | hr_byte_exactness_corrected | PASS | every HR file with known size matches; nothing outstanding under size_mismatch_existing |
| 2_completeness_identity | completeness_identity | PASS | manifest 94; distinct HR 85/85, distinct LR 8/8 (NR07-1 deduped) |
| 3_negative_no_raw | negative_no_raw | PASS | zero .all/.gsf files in staging_phase1 or quarantine_phase1 |
| 4_manifest_readonly | manifest_readonly | PASS | rows 21/21, bytes 38986/38986, mtime 2026-06-04T19:04:13.492391+00:00 vs 2026-06-04T19:04:13.492391+00:00 |
| 5_untouchable_present | untouchable_present | PASS | DISCOL / 18 Cal DIG / CCZ / TAG all present in manifest |
| 6_cell_size_sanity | cell_size_sanity | FAIL | 13 HR with unresolved cell-size issue (non-ok and not quarantined) |

## What Phase 2 inherits

- **Clean HR count: 61** = 85 − 0 (quarantined) − 1 (FETCH_FAILED_ESCALATE) − 14 (flagged, unresolved).
- Quarantined: []
- Escalated (R0): MGDS:30272
- Flagged for assessment (non-ok, non-quarantined): ['MGDS:20836', 'MGDS:21415', 'MGDS:21454', 'MGDS:21462', 'MGDS:24425', 'MGDS:24467', 'MGDS:24470', 'MGDS:30272', 'MGDS:31253', 'MGDS:31254', 'MGDS:31255', 'MGDS:31321', 'MGDS:31860', 'PANGAEA:tag_m127']
- No exclusion / re-tier performed. The assessment instance owns eligibility decisions on quarantined + flagged HR.

## Out-of-scope (unchanged from rev 1)

**Raw-LR NOT fetched — 76 raw-LR cruises deferred to Phase 2.** **41 train/eval HR staged without LR; tier provisional pending Phase-2 ratio finalization — not reclassified here.**
