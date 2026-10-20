# Co-located ship and AUV multibeam bathymetry: acquisition and harmonization

This repository acquires, grids, harmonizes, co-registers and packages pairs of seafloor bathymetry grids in which the
same patch of seafloor was measured twice by independent instruments: a near-bottom AUV multibeam survey (1-5 m pixels)
and a hull-mounted ship multibeam survey (9-151 m native cells). It is the data side of the paper below; the analysis side
(targets, tiles, evaluation, the gradient-boosted and CNN predictors, and both blind-test scorers) lives in the companion
code record [10.5281/zenodo.21300922](https://doi.org/10.5281/zenodo.21300922), which reads this repository's manifests
and the processed grids. The processed grids themselves are published as the data record
[10.5281/zenodo.23515276](https://doi.org/10.5281/zenodo.23515276).

> Dobbs, S. C. "Ship Multibeam Roughness Ranks Unresolved Seafloor Relief at Unseen Sites: A Pre-Registered Blind Test."
> *Geophysical Research Letters*, 2026GL125574 (in revision).

## The question and the headline result

Does the roughness of an ordinary ship multibeam grid tell you where the seafloor has fine-scale relief that the ship grid
cannot resolve? For each pair, the AUV grid gives the truth: the band-passed relief at scales between the ship cell and the
AUV pixel (`A_fine`). The ship-only feature `s_lr` is the standard deviation of the ship grid in a 256-pixel window. Within
the development sites, `s_lr` ranks `A_fine` across tiles with a Spearman correlation of about 0.4. Pre-registered blind
test 2, on eight sites chosen and sealed before any ship data was examined, confirmed this: pooled rho 0.43 with a 95 %
block-bootstrap interval of 0.28 to 0.53 over the five testable sites. Blind test 1, which deliberately reached outside the
development range of ship cell sizes, was not confirmed. The acquisition chain in this repository produced every grid,
mask, co-registration and eligibility decision behind those numbers; the scoring happened in the companion repository.

## Data

The data record [10.5281/zenodo.23515276](https://doi.org/10.5281/zenodo.23515276) (CC BY-NC-SA 4.0) holds 52 pairs with
rasters: 39 development pairs (16 leakage units plus EW0207), the 5 pairs of blind test 1 and the 8 sites of blind test 2,
plus a manifest of 17 excluded pairs with their reasons. Each pair zip holds the AUV grid and the ship grid as used, the three
validity masks, the per-sounding ship product rasters where usable, and a `pair.json` with sources, licenses, citations,
co-registration result, datum statistic, k, flags and checksums. Corpus-level files give one row per pair and one row per
scored tile (with `s_lr`, `A_fine`, the held-out predictions and the exclusion flags), both pre-registrations, the committed
blind calls, the deviation notes and the frozen scoring outputs.

Raw swath is not redistributed. It comes from the NOAA NCEI Multibeam Bathymetry Database (public domain), MGDS / IEDA
(CC BY or CC BY-NC-SA per data set), PANGAEA (CC BY 4.0) and USGS (public domain); every source data set is named with its
DOI and license in `pair.json` and in the package's `SOURCE_LICENSES.csv`, and each must be cited.

## Quick start

### Environment

The results were produced on Stanford's Sherlock cluster with Python 3.12.1 and the packages pinned in `requirements.txt`.
Gridding uses MB-System 5.8.2beta06 from the `docker.io/mbari/mbsystem` image (digest
`sha256:106f502d9f97ee0e9f5d889726320d1ae73a95fb102069e357a0bb0b35b39668`) run as an Apptainer sandbox.

```bash
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# On Sherlock the interpreter needs: module load python/3.12.1 openblas/0.3.28
```

### Reproduce one pair's score from the data record

Download `discol_so242_1.zip` and `tiles.parquet` from the data record into one folder, then:

```bash
python src/acq_r14/load_pair.py <folder> discol_so242_1
```

The script opens the pair's grids, selects that pair's tile rows, applies the frozen scoring rule (interior view if at least
10 tiles in at least 8 blocks, else the fallback view on `A_fine_int`) and prints the Spearman rho of `s_lr` against the
target next to the frozen value; `match_3dp` must be `True`. It runs in about ten seconds. The same script ships in the data
record as `load_pair.py`.

### Running the acquisition chain

Every stage below is a module under `src/` with a Slurm job script under `sbatch/`. The chain reads and writes the group's
data root on Oak and scratch (paths in `src/acq_r01/common.py`); see "Paths to change" at the end.

## Pipeline map

| Stage | Entry script | Inputs | Outputs | Directive |
|---|---|---|---|---|
| Discovery (HR catalogs, LR candidates, pair gating) | `src/cli.py discover-*` with `src/discovery/{mgds,ncei,geoportal,stage_a,stage_b}.py`; rerun `src/acq_r01/discovery_rerun.py`; PANGAEA `src/acq_r01/pangaea_discovery.py`; verification `src/acq_r01/verify_candidates.py` | MGDS, NCEI, DataCite and PANGAEA services (metadata only) | `reports_post_grl_review/ACQ-R01/discovery_rerun/`, `ACQ-R02/discovery_pangaea/`, `ACQ-R02/verification/` | `reports_post_grl_review/ACQ-R01_directive_audit_products_discovery_2026-09-29.md`, `ACQ-R02_directive_verification_acquisition_2026-09-30.md` |
| Second-blind-test inventory (metadata only, sealed) | `src/acq_r08/{pool_a,pool_b,pool_c}.py`; grids downloaded and measured by `src/acq_r08b/{download,measure}.py` | MGDS, NCEI, PANGAEA, DataCite | `ACQ-R08/candidates.csv`, `ACQ-R08b/candidates_measured.csv` | `ACQ-R08_directive_second_blind_test_candidates_2026-10-12.md`, `ACQ-R08b_directive_blind_header_footprint_2026-10-13.md` |
| Fetch (raw ship swath and provider grids) | `src/acq_r01/fetch_swath.py` (NCEI), `src/acq_r03/fetch_pangaea.py` (PANGAEA), `src/pipeline.py` with `src/{download,pangaea,cmgds}.py` (DISCOL, CCZ, TAG, Cal DIG) | NCEI, PANGAEA, CMGDS file services | `<data root>/raw_lr_swath/<cruise>/` with `fetch_manifest.json`; `<data root>/raw/<site>/` | ACQ-R01, `ACQ-R03_directive_close_acquisition_2026-09-30.md` |
| Gridding (MB-System `mbgrid` in the Apptainer sandbox) | `src/acq_r01/grid_lr.py` (stage-C recipe); June runs `src/discovery/stage_c_full.py` | `raw_lr_swath/<cruise>/`, the pair footprint | `<data root>/raw_lr_gridded/<cruise>.grd`, `ACQ-R02/grid/<cruise>.json` | ACQ-R02; `reports/directive_phase2_stage_c_full_gridding.md` |
| Harmonize (reproject, clip to the HR and LR overlap, masks) | `src/acq_r01/harmonize_new.py` (uses `src/harmonize.py`); June `src/discovery/stage_f_harmonize.py`; masks `src/discovery/stage_unify_valid_masks.py` | `raw_hr/`, `raw_lr_gridded/` | `<data root>/harmonized/<pair>/{hr,lr,hr_valid,lr_valid,joint_valid}.tif`, `ACQ-R02/harmonize/<pair>.json`, `manifest/pairs_v2_1.parquet` | ACQ-R02, ACQ-R03 |
| Co-register (rigid xyz shift of the AUV grid to the ship grid; ACQ-R13 quadrant test) | `src/coregister.py` (`estimate_rigid_xyz`, `apply_xyz`), called by the harmonize scripts; local quadrant test `src/phase5/localcoreg_p5.py`; June re-co-registration `src/discovery/stage_f5_valid_masks.py` | harmonized grids and masks | shift and QA in `ACQ-R02/harmonize/<pair>.json`, `reports/discovery/stage_f5_results.json`, Phase 5 `site_record.json` | `reports/acquisition_directive_v1.1_coreg_qa_addendum.md`, `ACQ-R13_directive_phase5_local_coregistration_2026-10-14.md` |
| Datum check (G = V95_rel against the calibrated bound T_G = 0.200712) | `src/acq_r11/vcheck.py`, calibration `src/acq_r11b/calibrate_v2.py`; frozen copy `src/phase5/vcheck_p5.py` | harmonized grids and masks | `ACQ-R11b/vcheck_calibration_v2.csv`, Phase 5 `site_record.json` | `ACQ-R11_directive_vertical_consistency_check_refreeze_2026-10-13.md`, `ACQ-R11b_directive_line_and_datum_checks_refreeze_2026-10-13.md` |
| k sweep (largest recoverable super-resolution factor per pair) | `src/discovery/stage_c2c_recalibrate.py` (`sweep`) with `src/discovery/stage_c5_spectral.py` | harmonized grids, `reports/discovery/stage_c2c_calibration.json` | `max_recoverable_k` and `k_sweep_status` in the manifests; `sweep_record.json` per sealed pair | `reports/directive_phase2_c2b_recal_and_phase2_clearance_v1.md` |
| Ship products (contract v2.1 per-sounding rasters) | `src/acq_r03/build_products_v2_1.py`, validator `src/acq_r03/validate_contract_v2_1.py` | `raw_lr_swath/<cruise>/`, the pair's `lr.tif` lattice | `<pair dir>/ship_products_v2_1/` | `reports_post_grl_review/INTERFACE_CONTRACT_v2.1.md`, ACQ-R03 |
| Context ship grids (footprint + 5 km, for the CNN repo's window choice) | `src/acq_r05/build.py`, `src/acq_r05/sources.py`, `src/acq_r05/coverage.py` | `raw_lr_swath/`, the CNN repo's `tiles_v1_1.parquet` | `<pair dir>/context_v1/` | `ACQ-R05_directive_context_ship_grids_2026-10-09.md` |
| Pretraining corpus (ship-only 10 km blocks, 400 cruises) | `src/acq_r04/{selection,fetch,blocks,persist}.py` | NCEI swath (scratch only) | `<data root>/pretrain_v1/` | `ACQ-R04_directive_pretraining_corpus_2026-10-02.md` |
| Eligibility, blind test 1 (sealed step 1) | `src/phase4/sealed_step1.py`, completion `src/phase4/sealed_step1_complete.py`, citation record `src/phase4/write_citation_record.py` | sealed pairs, `reports/discovery/stage_c2c_calibration.json` | `manifest/pairs_phase4_sealed.parquet`, `reports_post_grl_review/ACQ-R06b/step1_run_phase4_*.json` | ACQ-R06, ACQ-R06b, ACQ-R07, ACQ-R07b, ACQ-R07c |
| Eligibility, blind test 2 (sealed step 1: fetch, grid, harmonize, co-register, datum, k, products, eligibility) | `src/phase5/sealed_step1_p5.py` with `src/phase5/chain_p5.py` | `inputs/phase5_sites.csv`, sealed candidate grids, `ACQ-R08b/candidates_measured.csv`, `ACQ-R11b/vcheck_calibration_v2.csv` | `<data root>/phase5_v4_1/harmonized/<site>/`, `manifest/pairs_phase5_sealed_v4_1.parquet`, `reports_post_grl_review/PHASE5/step1_run_phase5_20261014T204117Z.json` | ACQ-R09, ACQ-R10, ACQ-R10b, ACQ-R10c, ACQ-R12, ACQ-R13 |
| Data package (COGs, tables, license audit, checks, Zenodo draft) | `src/acq_r14/{inventory,license_audit,build,corpus,check,preserve,report,relicense,zenodo_upload}.py`, example `src/acq_r14/load_pair.py` | the harmonized trees above, the CNN repo's frozen tile tables and scoring outputs | the data record 10.5281/zenodo.23515276; `reports_post_grl_review/ACQ-R14/` | `ACQ-R14_directive_public_data_release_2026-10-20.md` |

Every directive and its report are under `reports_post_grl_review/` (September 2026 onward) or `reports/` (June 2026
work; kept on disk next to the data, not tracked). `CHANGE_LEDGER.md` has one row per change to persisted data, manifests
or recorded provenance.

## Frozen versions

Each tag below governs a reported result. A freeze record (sha256 of every file of the sealed chain) is committed next to
the tag; the companion repository pins the freeze record's sha256 and refuses to score a run that does not cite it.

| Tag | Date | What it froze |
|---|---|---|
| `phase0-freeze` (companion repo) | 2026-10 | the development tile table `tiles_v1_1.parquet` and the units-v1 set; this repository's `manifest/pairs_v2_1.parquet` is the manifest it reads |
| `phase4-prereg-v2.1` (companion repo) | 2026-10-12 | the blind test 1 pre-registration v2.1 |
| `phase4-acq-freeze` | 2026-10-10 | `src/phase4/sealed_step1.py` and the sealed Phase 4 chain (`reports_post_grl_review/ACQ-R06b/freeze_record.json`) |
| `phase4-acq-complete`, `phase4-acq-complete-v2` | 2026-10-11 | the completion script `src/phase4/sealed_step1_complete.py` (v2 after the lock-5 fix) that finished Phase 4 step 1 once |
| `phase5-prereg-v3.1` (companion repo) | 2026-10-13 | the blind test 2 pre-registration v3.1 |
| `phase5-acq-freeze` | 2026-10-13 | the Phase 5 step-1 chain, first freeze (`PHASE5/freeze_record_phase5.json`) |
| `phase5-acq-freeze-v2` | 2026-10-13 | adds the datum check (`freeze_record_phase5_v2.json`) |
| `phase5-acq-freeze-v3` | 2026-10-14 | write-path audit and in-run leak check (`freeze_record_phase5_v3.json`); the ACQ-R10c run |
| `phase5-acq-freeze-v4`, `-v4.1` | 2026-10-14 | local quadrant co-registration (superseded: a drift-case write bug, then a forbidden record key) |
| `phase5-acq-freeze-v4.2` | 2026-10-14 | the governing Phase 5 freeze (`PHASE5/freeze_record_phase5_v4_2.json`); job 47819657 produced the blind test 2 grids and eligibility |
| `acq-grl-revision-v2.0` | 2026-10-20 | this repository as archived for the GRL revision |

## Pre-registrations and deviations

The pre-registrations (v2.1 for blind test 1, v3.1 for blind test 2), their sign-offs, Steve's committed blind calls and the
deviation notes are committed in the companion repository and copied into the data record's `blind_tests/` folder. In this
repository:

- `reports_post_grl_review/ACQ-R07b/DEVIATION_phase4_01_TEMPLATE.md` and `_v2.md`: the deviation note for Phase 4 step 1
  (stopped on a directory-mode check and completed once by the frozen completion script); signed in the companion repository.
- Deviation 02 (the completion record's freeze-sha key name, fixed by a citation record): `reports_post_grl_review/ACQ-R07c/REPORT_ACQ-R07c_2026-10-12.md`.
- Deviations 03 and 04 (companion repository) concern the scorer; their acquisition-side evidence is `ACQ-R07b/` and `ACQ-R06b/`.
- The seven blind test 2 deviations (companion `DEVIATIONS_phase5.md`) map to this repository's ACQ-R10, R10b, R10c, R11, R11b, R12 and R13 reports, each of which records what stopped, what changed and the re-freeze.
- Rulings that changed the chain are recorded in the directive headers and in `reports_post_grl_review/ACQ-R03/rulings_ACQ-R03.md`.

## What is superseded

The repository began (June 2026) as the acquisition side of a super-resolution project: the submitted paper used a
heteroscedastic CNN (`het_production_v1`, companion repository) whose sigma product was meant to flag unresolved relief, and
trained on a synthetic-LR regime in which ship-like grids were simulated by degrading AUV grids. Those products are kept
for the record and do not support the revised paper's claims. In this repository the traces are: `CLAUDE.md` (the original
acquisition directive, now carrying a superseded banner), the June directives under `reports/`, and the k-sweep vocabulary
("recoverable super-resolution factor"), which survives only as the pair-level `k` that sets the fine band. No synthetic
LR grid was ever used as a pair's ship side.

## Hardware and runtime

Everything in this repository ran on CPU nodes of Sherlock (Slurm; `normal`, `serc` and once `bigmem`). No GPU is used.

| Stage | Resources | Approximate time |
|---|---|---|
| NCEI swath fetch (12 development cruises, 42 GB) | 4 CPU, 8 GB | 39 min |
| PANGAEA raw fetch (12 GB) | 2 CPU, 8 GB | 2 h 50 min (host-throttled) |
| Gridding, one cruise | 8 CPU, 32 GB | minutes to 5 h, depending on swath volume |
| Harmonize + co-register + QA, one pair | 8 CPU, 48 GB | seconds to minutes |
| Ship products v2.1, one pair | 8 CPU, 48 GB (Amundsen 256 GB) | 4 to 28 min |
| Context grids, 39 pairs | 4 CPU, 48 GB | seconds to minutes per pair |
| Pretraining corpus (400 cruises, 3 TB raw) | up to 32 CPU, 240 GB | 41 h wall |
| Phase 4 step 1 (5 pairs) | 8 CPU, 64 GB | 6 min + 37 s completion |
| Phase 5 step 1 (8 sites, fetch, grid, harmonize, co-register, datum, k, products) | 8 CPU, 128 GB | 37 min 51 s (job 47819657) |
| Datum calibration (38 pairs) | 4 CPU, 64 GB | 2 min |
| Data package (442 COGs, tables, checks) | 8 CPU, 32 GB; 4 CPU, 16 GB | 2 min build, 5 min checks |
| Zenodo upload (66 files, 1.7 GB) | 2 CPU, 8 GB | 6 min |

## Citation and license

Code: MIT (`LICENSE`). Cite the paper, the data record and this code record:

- Dobbs, S. C. (in revision). Ship Multibeam Roughness Ranks Unresolved Seafloor Relief at Unseen Sites: A Pre-Registered
  Blind Test. *Geophysical Research Letters*, 2026GL125574.
- Dobbs, S. C. (2026). Co-located ship and AUV multibeam bathymetry corpus: processed grids, masks, co-registration and
  tile tables (version 1.0.0) [Data set]. Zenodo. https://doi.org/10.5281/zenodo.23515276 (CC BY-NC-SA 4.0).
- Dobbs, S. C. (2026). Co-located ship and AUV multibeam bathymetry: acquisition and harmonization code (version 2.0)
  [Software]. Zenodo. https://doi.org/10.5281/zenodo.21300925 (this repository; see `CITATION.cff`).

Each source data set must also be cited (see the data record's `SOURCE_LICENSES.csv`).

## Paths to change

The code names the Sherlock layout it ran on. A user elsewhere changes: the data root and scratch root
(`src/acq_r01/common.py`: `OAK`, `SCRATCH_DATA`; `src/acq_r14/common.py`: `OAK`, `WORK`), the MB-System sandbox
(`src/acq_r01/common.py`: `SANDBOX_CANONICAL`, or the `ACQ_MB_SANDBOX` environment variable), the companion repository
path (`src/acq_r14/common.py`: `CNN`), and the interpreter in the `sbatch/` scripts (`PY=` lines).
