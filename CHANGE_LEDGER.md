# Change ledger

One row per change to persisted data, manifests or recorded provenance in this repository or on OAK.
Each row gives the evidence file and the commit. Created by ACQ-R04; earlier changes are recorded in each
directive's report.

| date | directive / ruling | what changed | where | evidence | commit |
|---|---|---|---|---|---|
| 2026-10-03 | ACQ-R04, steering ruling on the AR26 HOLD | AR26 fetch manifest and SHA256SUMS corrected to match disk: the em710 `9999.all.mb58.gz` entry (11,138,466 B, sha256 5b97…) was removed, because only the em122 copy (1,275 B, sha256 9119…) is on disk. It was a file-name collision across NCEI sonar subdirectories. The em710 copy has 0 soundings in the AR26__MGDS_31838 product window; its beams lie at 32.86N 79.96W. lr.tif and products were not rebuilt (not needed). Originals kept as `*.pre_acq_r04_2026-10-03`. | `$OAK/auv_ship_colocated_bathy/raw_lr_swath/AR26/{fetch_manifest.json,SHA256SUMS}` | `reports_post_grl_review/ACQ-R04/{ar26_check.json,ar26_check_mbinfo.json,ar26_manifest_correction.json}` | this commit |
