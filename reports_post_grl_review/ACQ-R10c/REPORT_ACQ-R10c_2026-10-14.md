# REPORT ACQ-R10c — Phase 5 step 1 on the eight sites: complete; 2 eligible

**Directive:** `ACQ-R10c_directive_phase5_step1_real_run_2026-10-14.md`. The code was frozen as `phase5-acq-freeze-v3`; the governing pre-registration is v3.1.
**Blindness:** this report carries only fields that `src/phase5/report_p5.py` writes, plus booleans. It shows no sealed amplitude, target, s_lr, feature, prediction, G or V95 value, and no image.

## Bullets

1. **Run: job 47786827, complete.**
   - Node sh03-08n56; 2026-10-14 15:26:29Z to 16:21:56Z; 55 min 39 s (step wall time 3,290 s); exit 0.
   - The in-job preconditions passed (v3.1 pre-registration and sign-off, freeze v3, no earlier record or supplement).
   - Guard self-test: 552/552 probes blocked (84 Phase 4, 228 Phase 5 reader probes, 240 output-root paths); real-name admission 23/23.
   - Locks 1–4 passed, and lock 2 passed again after the run against freeze v3.
   - All eight swath fetches were complete.
   - **In-run leak check: PASS.** 103 files and 2 in-memory texts scanned, including both job logs; 115 printed-value patterns; 0 value hits, 0 key hits.
2. **Eligible sites: 2 of 8** (Bermuda KN173L02__MGDS_31675, Dorado Outcrop AT26-24__MGDS_31954).
   - **The v3.1 pooled primary criterion needs at least 3 eligible sites, so it is not testable with this run.**
   - **Not testable: 6.**
     - Co-registration (offset above the 30 m development bound): 4 (TN188, Escanaba, KN161L04, MV1003).
     - Vertical datum: 1 (MV1209).
     - No recoverable k (sweep status `no_curve`): 1 (Monterey).
   - These are outcomes under the frozen rules (ruling 1.3); no site was re-screened or replaced.
3. **Plumbing fixes: one, before submission; none during the run.**
   - `sbatch/acq_r10/step1.sbatch` now writes its guard self-test record to `ACQ-R10c/guard_selftest_r10c.json` instead of `ACQ-R10/` (the script is not frozen; commit `2957d93`).
   - No frozen file changed, so there is no freeze v3.1 and no resume.
4. **Hashes.**

   | Item | sha256 |
   |---|---|
   | Run record `reports_post_grl_review/PHASE5/step1_run_phase5_20261014T152705Z.json` | `3009506d8eed935c3b6a0736a7fa5cd93b73fe01c1307820755a18f659387ff8` |
   | Supplement `manifest/pairs_phase5_sealed.parquet` (8 rows; 64 + 6 columns) | `255d85c879c8f3a09d2a1a53f20b928a7a0c192fcc3479cf00144d737fabf96d` |
   | Freeze record `PHASE5/freeze_record_phase5_v3.json` | `42cb8ebb65d104694c935b71627dd9f884b99a14c9474c02f87a7cc853daa85b` |
   | Entry script `src/phase5/sealed_step1_p5.py` | `f1b6ada06d97fd5782a2ac87ed78c5fa6f21702ef1e957d0b853a2fd0157f296` |

   The pre-registration sha256 checked by lock 1 was `75b72eb6…c7b6`.
5. **Do not open (Steve).** These hold rasters or depth-derived values:
   - everything under OAK `…/auv_ship_colocated_bathy/phase5/` (`harmonized/<pair>/`, `raw_lr_gridded/<pair>/`);
   - OAK `raw_lr_swath/{TN188, Escanaba, Monterey, KN161L04, MV1209, KN173L02, MV1003, AT26-24}/`;
   - the job logs `logs/acq_r10_p5_47786827.{out,err}` (SITE lines with spacings; the builder's QA log line);
   - the supplement's offset columns (`horiz_offset_m`, `vert_offset_m`), which are co-registration shifts.

   The CNN reads the supplement and the run record programmatically.
6. **Record.**
   - Committed by explicit path: the run record, the supplement, this report, `report_fields_r10c.md` (the `report_p5` output) and the guard self-test record; one `CHANGE_LEDGER.md` row.
   - OAK `acq_archive/ACQ-R10c/` holds the run record, the supplement, this report, the report fields, the guard self-test record and freeze v3, with `SHA256SUMS` verified.
   - The per-site records stay on OAK under the sealed `phase5/` root. Their sha256 values are in the run record (`per_pair[*].site_record_sha256`) and each site record lists its files' sha256.
   - **CNN companion line (R17):** supplement `manifest/pairs_phase5_sealed.parquet` sha256 `255d85c879c8f3a09d2a1a53f20b928a7a0c192fcc3479cf00144d737fabf96d`; run record `reports_post_grl_review/PHASE5/step1_run_phase5_20261014T152705Z.json` sha256 `3009506d8eed935c3b6a0736a7fa5cd93b73fe01c1307820755a18f659387ff8`.
   - Note for the CNN side (no action here): `phase5_common.py` l.47–48 still pin freeze v2, so its acquisition-record lock will refuse this record until they name freeze v3 (`42cb8ebb…`) and the entry script `f1b6ada0…`.

## Site table (report_p5 fields; datum = the boolean of the vertical-datum check)

| site | pair (LR cruise__HR id) | coreg_pass | datum check | k | ship cells across | hr_res (m) | ship products usable | eligible |
|---|---|---|---|---|---|---|---|---|
| Galápagos Spreading Center | TN188__MGDS_18210 | False | pass | 8 | 8.617 | 1.0 | True | **no** (co-registration: offset > 30 m) |
| Escanaba Trough | Escanaba__MGDS_30368 | False | pass | 16 | 5.720 | 1.28 | True | **no** (co-registration: offset > 30 m) |
| Monterey Canyon | Monterey__MGDS_24756 | True | pass | — | 8.746 | 1.0 | False | **no** (no recoverable k: sweep `no_curve`) |
| Mid-Atlantic Ridge 16.5°N | KN161L04__MGDS_22436 | False | pass | 16 | 4.438 | 2.027 | True | **no** (co-registration: offset > 30 m) |
| La Jolla Canyon | MV1209__MGDS_21415 | False | **fail** | 2 | 29.314 | 1.0 | True | **no** (vertical datum: above T_G) |
| Bermuda | KN173L02__MGDS_31675 | True | pass | 16 | 4.760 | 1.044 | True | **yes** |
| Chile margin | MV1003__MGDS_31860 | False | pass | 8 | 6.527 | 1.341 | False | **no** (co-registration: offset > 30 m) |
| Dorado Outcrop | AT26-24__MGDS_31954 | True | pass | 8 | 4.665 | 0.999 | True | **yes** |

The full `report_p5` output is in `ACQ-R10c/report_fields_r10c.md`. It adds the status, `k_recoverable`, `hr_res_in_range` (True for all eight), the spacings, product status, file counts and site-record sha256.
