# Stage 1 staging-download report — rev 2 (2026-06-05)

*Phase 1 remediation per directive v1.5.4 rev 2. No reclassify / no gate edit / no re-tier — diagnoses only.*

## Remediation summary

### R0 — MGDS:30272 stub inspection + re-fetch

- Stub bytes (pre-delete): **278** (expected 4517897)
- Stub body (first ~400 chars, escaped newlines):

  > `<!DOCTYPE html>\n<html>\n<head>\n	<title>Marine Geoscience Data System - Download Error</title>\n</head>\n<body>\n	<div id="wrapper">\n		<div id="content">\n			<h3>Download Error</h3><div>An error has occurred.</div>			<div style="clear:both"></div>\n	    </div>\n	</div>\n</body>\n</html>\n`

- Re-fetch URL: `https://api.marine-geo.org/services/download/Document_Accept.php?client=DataLink&data_uid=2427151`
- Re-fetch bytes received: **278** (expected 4517897)
- Final status: **FETCH_FAILED_ESCALATE**

### R1 — MGDS:31600 quarantine + measurement

- Quarantine path: `/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600`
- Declared `hr_native_res_m`: **9.8 m**
- Measured finest cell (across all files): **None m** (ratio None)
- `looks_like` verdict: **unknown**

Per-file measurements:

| file | crs | cx_native | cy_native | mean_lat | cx_m | cy_m | finest_m | error |
|---|---|---|---|---|---|---|---|---|
| d142.v7.latlon.grd.gz | — | None | None | None | None | None | None | '/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600/d142.v7.latlon.grd' not recognized as being in a supported file format. |
| d144.v7.latlon.grd.gz | — | None | None | None | None | None | None | '/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600/d144.v7.latlon.grd' not recognized as being in a supported file format. |
| d145.v7.latlon.grd.gz | — | None | None | None | None | None | None | '/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600/d145.v7.latlon.grd' not recognized as being in a supported file format. |
| d146.v7.latlon.grd.gz | — | None | None | None | None | None | None | '/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600/d146.v7.latlon.grd' not recognized as being in a supported file format. |
| d148.v7.latlon.1sec.grd.gz | — | None | None | None | None | None | None | '/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600/d148.v7.latlon.1sec.grd' not recognized as being in a supported file format. |
| d148.v7.latlon.tenthsec.grd.gz | — | None | None | None | None | None | None | '/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600/d148.v7.latlon.tenthsec.grd' not recognized as being in a supported file format. |
| d149.v7.latlon.1sec.grd.gz | — | None | None | None | None | None | None | '/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600/d149.v7.latlon.1sec.grd' not recognized as being in a supported file format. |
| d149.v7.latlon.tenthsec.grd.gz | — | None | None | None | None | None | None | '/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600/d149.v7.latlon.tenthsec.grd' not recognized as being in a supported file format. |
| dome.v7.latlon.1sec.grd.gz | — | None | None | None | None | None | None | '/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600/dome.v7.latlon.1sec.grd' not recognized as being in a supported file format. |
| dome.v7.latlon.tenthsec.grd.gz | — | None | None | None | None | None | None | '/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600/dome.v7.latlon.tenthsec.grd' not recognized as being in a supported file format. |
| valley.latlon.grd.gz | — | None | None | None | None | None | None | '/scratch/groups/hilley/auv_ship_colocated_bathy/quarantine_phase1/MGDS_31600/valley.latlon.grd' not recognized as being in a supported file format. |

### R2 — corpus-wide cell-size sanity sweep

- HR scanned: **75**
- `ok`: **41**, `quarantined`: **0**, `flagged`: **34**
- CSV: `reports/discovery/hr_resolution_sanity.csv`

Flagged HR (non-ok, non-quarantined):

| hr_id | declared_m | measured_m | ratio | verdict | files |
|---|---:|---:|---:|---|---:|
| MGDS:17700 | 2.560451774672397 | — | — | no_grid_found | 16 |
| MGDS:20811 | 0.9408837055641691 | — | — | no_grid_found | 17 |
| MGDS:20836 | — | — | — | no_grid_found | 0 |
| MGDS:21415 | 4.11695117961282 | 0.992322062788762 | 0.24 | flag_mismatch | 12 |
| MGDS:21454 | 1.378009514248073 | — | — | no_grid_found | 44 |
| MGDS:21462 | 2.0192808462984058 | — | — | no_grid_found | 25 |
| MGDS:21847 | 4.998603595627189 | 47.741642966716306 | 9.55 | flag_mismatch | 2 |
| MGDS:22436 | 1.9997336226821447 | — | — | no_grid_found | 7 |
| MGDS:24002 | 1.9993171815656368 | 0.0029232953533981786 | 0.0 | flag_mismatch | 3 |
| MGDS:24425 | — | — | — | no_grid_found | 0 |
| MGDS:24467 | 0.48168361881991967 | — | — | no_grid_found | 22 |
| MGDS:24470 | 0.5240616408693941 | 0.09915857701467676 | 0.19 | flag_mismatch | 4 |
| MGDS:30272 | 4.0 | — | — | no_grid_found | 0 |
| MGDS:30373 | 0.9999320427000511 | — | — | no_grid_found | 1 |
| MGDS:31059 | 0.9997773041860054 | — | — | no_grid_found | 11 |
| MGDS:31073 | 0.9995097628190012 | 48.96035322817098 | 48.98 | flag_mismatch | 42 |
| MGDS:31181 | 0.9998706244687567 | — | — | no_grid_found | 16 |
| MGDS:31188 | 0.9982742766536704 | — | — | no_grid_found | 14 |
| MGDS:31199 | 1.0000388800550242 | — | — | no_grid_found | 21 |
| MGDS:31212 | 0.9992157608026287 | — | — | no_grid_found | 4 |
| MGDS:31253 | 0.6239641860455681 | — | — | no_grid_found | 2 |
| MGDS:31254 | 0.540975715305519 | 0.21492522689575388 | 0.4 | flag_mismatch | 2 |
| MGDS:31255 | 0.5327510583218268 | 0.2116732973254224 | 0.4 | flag_mismatch | 2 |
| MGDS:31321 | 0.5717333025035013 | 79.44763853448933 | 138.96 | flag_mismatch | 53 |
| MGDS:31675 | 0.9991914031958038 | — | — | no_grid_found | 25 |
| MGDS:31811 | 1.999070653630909 | — | — | no_grid_found | 11 |
| MGDS:31813 | 0.8690544770855743 | 99.27871055379427 | 114.24 | flag_mismatch | 47 |
| MGDS:31824 | 0.9996536170385556 | — | — | no_grid_found | 11 |
| MGDS:31831 | 0.9990943799759235 | 225.38444030006954 | 225.59 | flag_mismatch | 9 |
| MGDS:31838 | 0.9990278981460045 | — | — | no_grid_found | 2 |
| MGDS:31860 | 1.0915751445057353 | 3.055749229059561 | 2.8 | flag_mismatch | 16 |
| MGDS:5174 | 4.988858284029265 | — | — | no_grid_found | 4 |
| MGDS:7832 | 1.642800881132585 | — | — | no_grid_found | 7 |
| PANGAEA:tag_m127 | 2.0 | 97.52966970155735 | 48.76 | flag_mismatch | 1 |

## Verification gates (corrected)

| # | gate | result | detail |
|---|---|---|---|
| 1_hr_byte_exactness_corrected | hr_byte_exactness_corrected | PASS | every HR file with known size matches; nothing outstanding under size_mismatch_existing |
| 2_completeness_identity | completeness_identity | PASS | manifest 94; distinct HR 85/85, distinct LR 8/8 (NR07-1 deduped) |
| 3_negative_no_raw | negative_no_raw | PASS | zero .all/.gsf files in staging_phase1 or quarantine_phase1 |
| 4_manifest_readonly | manifest_readonly | PASS | rows 21/21, bytes 38986/38986, mtime 2026-06-04T19:04:13.492391+00:00 vs 2026-06-04T19:04:13.492391+00:00 |
| 5_untouchable_present | untouchable_present | PASS | DISCOL / 18 Cal DIG / CCZ / TAG all present in manifest |
| 6_cell_size_sanity | cell_size_sanity | FAIL | 33 HR with unresolved cell-size issue (non-ok and not quarantined) |

## What Phase 2 inherits

- **Clean HR count: 41** = 85 − 0 (quarantined) − 1 (FETCH_FAILED_ESCALATE) − 34 (flagged, unresolved).
- Quarantined: []
- Escalated (R0): MGDS:30272
- Flagged for assessment (non-ok, non-quarantined): ['MGDS:17700', 'MGDS:20811', 'MGDS:20836', 'MGDS:21415', 'MGDS:21454', 'MGDS:21462', 'MGDS:21847', 'MGDS:22436', 'MGDS:24002', 'MGDS:24425', 'MGDS:24467', 'MGDS:24470', 'MGDS:30272', 'MGDS:30373', 'MGDS:31059', 'MGDS:31073', 'MGDS:31181', 'MGDS:31188', 'MGDS:31199', 'MGDS:31212', 'MGDS:31253', 'MGDS:31254', 'MGDS:31255', 'MGDS:31321', 'MGDS:31675', 'MGDS:31811', 'MGDS:31813', 'MGDS:31824', 'MGDS:31831', 'MGDS:31838', 'MGDS:31860', 'MGDS:5174', 'MGDS:7832', 'PANGAEA:tag_m127']
- No exclusion / re-tier performed. The assessment instance owns eligibility decisions on quarantined + flagged HR.

## Out-of-scope (unchanged from rev 1)

**Raw-LR NOT fetched — 76 raw-LR cruises deferred to Phase 2.** **41 train/eval HR staged without LR; tier provisional pending Phase-2 ratio finalization — not reclassified here.**
