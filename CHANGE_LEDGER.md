# Change ledger

One row per change to persisted data, manifests or recorded provenance in this repository or on OAK.
Each row gives the evidence file and the commit. Created by ACQ-R04; earlier changes are recorded in each
directive's report.

| date | directive / ruling | what changed | where | evidence | commit |
|---|---|---|---|---|---|
| 2026-10-03 | ACQ-R04, steering ruling on the AR26 HOLD | AR26 fetch manifest and SHA256SUMS corrected to match disk: the em710 `9999.all.mb58.gz` entry (11,138,466 B, sha256 5b97…) was removed, because only the em122 copy (1,275 B, sha256 9119…) is on disk. It was a file-name collision across NCEI sonar subdirectories. The em710 copy has 0 soundings in the AR26__MGDS_31838 product window; its beams lie at 32.86N 79.96W. lr.tif and products were not rebuilt (not needed). Originals kept as `*.pre_acq_r04_2026-10-03`. | `$OAK/auv_ship_colocated_bathy/raw_lr_swath/AR26/{fetch_manifest.json,SHA256SUMS}` | `reports_post_grl_review/ACQ-R04/{ar26_check.json,ar26_check_mbinfo.json,ar26_manifest_correction.json}` | this commit |
| 2026-10-07 | ACQ-R04 (directive 2026-10-02 + rulings 2026-10-03..06) | New ship-only pretraining corpus: 51,322 blocks from 255 NCEI cruises (selection_v1.1, 310 cruises), gridded with the development chain, contract-v2.1 products (unchanged builder). Persisted as one tar per cruise; SHA256SUMS re-verified on OAK (271/271). Lockbox guard extended to `harmonized_confirmatory/` and to GDAL/OGR/parquet readers (`src/acq_r01/common.py`); MB-System sandbox now staged to node-local disk (`ACQ_MB_SANDBOX`); `C.mb` kills the whole process group on timeout. No change to manifest v2.1, the dropped list, the contract or the development products. | `$OAK/auv_ship_colocated_bathy/pretrain_v1/`; `src/acq_r01/common.py` | `reports_post_grl_review/ACQ-R04/REPORT_ACQ-R04_2026-10-07.md`, `persist_verify.json`, `exclusion_check_v1.json`, `repro_check_v1.json` | this commit |
