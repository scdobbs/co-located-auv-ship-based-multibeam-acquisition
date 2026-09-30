# DIRECTIVE ACQ-R02 (Phase 1, acquisition repo): contract v2 products, corpus snapshot, PANGAEA discovery, candidate verification and acquisition

**Date:** 2026-09-30
**Author:** steering instance, for Claude Code on Sherlock (acquisition repo: `co-located-auv-ship-based-multibeam-acquisition`)
**Follows:** ACQ-R01 (`reports_post_grl_review/ACQ-R01/REPORT_ACQ-R01_2026-09-29.md`)
**Companion:** `INTERFACE_CONTRACT_v2.md`. Commit it verbatim to `reports_post_grl_review/` before any §2 code runs. The
CNN repo commits it in its next directive.
**Report to:** `reports_post_grl_review/ACQ-R02/REPORT_ACQ-R02_<date>.md` (committed, as in ACQ-R01).
**Compute:** CPU jobs as needed. Downloads are authorized under the cap in §0.

---

## 0. Purpose, rulings, standing rules

### Steve's rulings on the ACQ-R01 HOLDs (binding)

**H1.** The 11 reason-unrecorded HR enter this directive as candidates, **development-only**:
- the 8 phase-1 processed-LR pairs: MGDS:24002, 31321, 31813, 31814, 31831, 20815, 21847, 31073;
- MGDS:31291, 5174 and 24467.

Their HR was staged in phase 1, so none of them may ever be designated confirmatory, whatever unit they form. They do
**not** go through `designate_confirmatory.py`. Their designation is recorded as `development (ruling H1)`.

**H2.** Cal DIG ship-side products are accepted as `available: false`. No further acquisition for Cal DIG.

**H3.** The v1 QA gate is replaced by contract v2. Robust spread channel, registration and vertical-offset gates; see
the contract's §0 for the reasoning. No other response to the v1 flags.

### Purpose, in order

1. Build contract-v2 products for the existing corpus (§2).
2. Snapshot the corpus for off-cluster backup (§3).
3. Run PANGAEA discovery and designation, metadata only (§4).
4. Verify every candidate's footprint, independence and leakage unit (§5).
5. Acquire and harmonize the verified pairs (§6).
6. Write manifest v2 (§7).

Run the sections in this order. §4.3 (designation) must be committed before any §5 download of a §4 candidate.

### Standing rules

**Scope discipline.** Do the items below and nothing else. Record any tempting extra in one line under "Not pursued".
Do not run it. Pretraining-corpus building is **out of scope** (held by Steve).

**Challenge clause.** Report any wrong or underspecified instruction in §1 of the report, with evidence. Items that are
Steve's call become HOLDs. Where this directive's assumptions about stages, files or conventions are wrong, say so and
follow the repo.

**Lockbox.** AT42-03__MGDS_32007 and TN159__MGDS_21981. Every new script imports `src.acq_r01.common` (or an
equivalent `acq_r02` module) so the guard installs on import. The only exception is the byte-level snapshot in §3.2.
No product, download, grid or QA for these pairs. Any candidate sharing acquisition with them on any axis is excluded.

**Confirmatory seal (new).** Confirmatory units are nu01 and nu03 from ACQ-R01, plus any §4 unit designated
confirmatory. For these units:
- They may be downloaded, harmonized and QA'd for data quality: footprint, artifacts, co-registration pass/fail and
  shift.
- **No** residual amplitude statistic (HR−LR RMS, T_res, s_lr), k sweep, spectral ratio, baseline, model or target
  is computed or reported.
- Their harmonized outputs go to OAK `harmonized_confirmatory/<unit>/<pair>/`, files 0444.
- Contract products for them are built only at Phase 4.
- Add `CONFIRMATORY_UNITS` and `confirmatory_paths()` to the common module, and report them so the CNN repo can extend
  its guard to that path.

**Anti-circularity (non-negotiable).**
- HR = AUV. LR = independent surface-ship multibeam.
- No composites (GEBCO, GMRT, compilations that ingest AUV data) as LR.
- No LR synthesized from HR.
- No provider "combined" or "merged" ship+AUV grid as LR. Check the title and abstract of every provider product.

**Download cap.** Cumulative new downloads ≤ 500 GB. If the §6 plan would exceed it, stop before fetching. Report the
plan with its per-candidate volume as a HOLD.

---

## 1. (Report §1 is the bottom line; see §8.)

---

## 2. Contract-v2 products for the existing corpus

1. Extend `build_products.py` (new version, v1 code kept) to contract v2:
   - `ship_rsd` and `ship_median_regrid` as exact per-cell medians. Sort soundings by cell index. No streaming
     approximation.
   - The v2 QA, including the ±1-cell, 0.25-step shift surface written to `qa_shift_surface.csv`.
   - v2 `products.json`.
2. **Rebuild** from the raw swath already on OAK `raw_lr_swath/`, for the same 16 pairs as ACQ-R01. No re-download.
3. Write v2 unavailable `products.json` for the 18 Cal DIG pairs.
4. **Validate** all 34 against v2 with an updated `validate_contract.py`. v1 `ship_products_v1/` directories stay
   untouched.
5. **Control:** for every pair, v2 `ship_count`, `ship_sd`, `ship_xtrack_frac` and `ship_beam_angle` must equal v1
   exactly (NaN-aware). Report any difference.
6. **Report per pair:** v2 QA table (n common, median offset, robust σ, robust σ / median s_lr, argmin shift, flags).
   Also report the median over cells of `ship_rsd / ship_sd`, as a spike-dominance indicator.

---

## 3. Corpus snapshot for off-cluster backup

1. Build `corpus_snapshot_2026-09-30.tar` on OAK (`.../auv_ship_colocated_bathy/snapshots/`) containing:
   - `harmonized/` (non-lockbox pairs, including `ship_products_v1/` and `ship_products_v2/`);
   - `manifest/`;
   - `raw/` (provider grids).

   Write a file list and `SHA256SUMS` alongside it. Raw swath is excluded; it is re-fetchable from recorded URLs and
   sha256s.
2. **Lockbox archive.** Build `lockbox_snapshot_2026-09-30.tar` with a single shell `tar` command run **outside** the
   Python guard. This is a byte copy only. No file is decoded, opened by any library, or listed beyond `tar`'s own
   output. Record the exact command, the tar's sha256 and its size in the report. This is the only permitted lockbox
   access in ACQ-R02, and it exists solely so the holdout is not single-copy.
3. Do not transfer either tar off-cluster. Steve does the transfer. Report both paths, sizes and sha256s.

---

## 4. PANGAEA discovery, then designation (metadata only)

ACQ-R01 seeded PANGAEA only from manifest pairs. The richest proven source of clean pairs (DISCOL, CCZ, TAG) is
AUV bathymetry with raw ship EM12x swath published on PANGAEA, mostly GEOMAR AUV Abyss on SONNE and METEOR.

### 4.1 Harvest

Query PANGAEA (API or `pangaeapy`) for AUV bathymetry datasets. Examples include AUV Abyss, AUV SEAL and REMUS, but do
not stop at these. Collect title, DOI, cruise, bbox, resolution, depth, and whether gridded or raw data are offered.

Pair each AUV dataset with independent ship multibeam over its footprint. Raw ship swath is preferred:
- PANGAEA raw EM12x/EM710 "with links to raw data files";
- or NCEI MBBDB for the same area.

Apply the anti-circularity rules. Exclude any "combined", "merged" or "compiled" product that includes AUV data.

### 4.2 Gate and leakage

Apply the current gate, independence screen and conservative leakage policy (`stage_p2_leakage` edges):
- shared HR cruise;
- shared LR cruise;
- centroid ≤ 50 km.

Leakage is evaluated against the whole corpus, the lockbox, the ACQ-R01 candidates and the H1 set.

Candidates sharing a cruise or lying within 50 km of CCZ, DISCOL or TAG (SO242/1, SO268/1, M127) **join those
existing units**. They are development and are not designated.

Other sources (Ifremer/SISMER, NOC/BODC Autosub, JAMSTEC):
- One paragraph each on what exists and how it is accessed.
- No harvest.

### 4.3 Designation

Run `designate_confirmatory.py` **once** on the new §4 units only:
- seed **20260930**;
- same stratification and merge rules as ACQ-R01.

Commit the script version, the input list and the output assignment with sha256s **before** any §5 download of a §4
candidate. Report the table.

---

## 5. Candidate verification (footprint, independence, leakage)

**Candidates:** the 16 ACQ-R01 candidates, the 11 H1 HR, and the §4 candidates.

### 5.1 Lockbox pre-check, before any file of the candidate is opened

For every candidate, check shared HR cruise, shared LR cruise and 50-km centroid distance against both lockbox pairs.
Lockbox HR cruises are AT42-03 and AT15-36; lockbox LR cruises are AT42-03 and TN159.

**MGDS:5174 (AT42-06) must pass this before anything else.** Any candidate that fails is excluded and recorded.

### 5.2 Footprint

Download the HR grid and compute the valid-data polygon, as in stage B. Replace every bbox footprint.

Candidates with no real overlap with their LR are dropped as false pairs and recorded.

### 5.3 Shared-HR-survey axis

MGDS no longer returns cruise ids. Read the HR cruise and survey identity from the HR files' own metadata (grid
headers, netCDF attributes, dataset landing pages). Apply the axis.

### 5.4 Re-run leakage assignment with real footprints and the HR axis

Outcome rules (binding):

| event | result |
|---|---|
| a designated unit splits | each part inherits the parent's designation |
| a confirmatory unit merges with any existing, development, H1 or other confirmatory unit | its confirmatory members are **dropped**; development members continue |
| a unit fails acquisition or QA | dropped from its assigned set, never reassigned |
| two development units merge | remains development |

Report every change against the ACQ-R01 and §4.3 assignments.

---

## 6. Acquisition and harmonization of verified pairs

1. **Plan first.** Write the per-candidate fetch plan (files, mode, volume) and check it against the 500 GB cap.
2. **LR.** Fetch raw swath to OAK `raw_lr_swath/<cruise>/` (sha256, 0444, `fetch_manifest.json`, as ACQ-R01).
   - **H1 processed-LR pairs:** grid from **raw swath** with the standard stage C pipeline, not from the processed
     NCEI grids. This keeps LR provenance uniform with every other NCEI pair. Use the processed grid only as a
     cross-check (median offset and robust σ, development pairs only).
   - Legacy or unrecognised formats (SeaBeam-classic, unknown sonar) → `needs_format_review`. Dropped for this
     directive, recorded, not repaired.
3. **Grid and harmonize** with the existing stage C → C.5 → F chain, unchanged. Apply the current co-registration QA.
   - Development pairs: full standard QA, the k determination per the current standard, and contract-v2 products.
   - Confirmatory pairs: under the seal (§0). Report pass/fail, co-registration shift and valid-cell counts only.
4. **Provider pairs** (§4): as ACQ-R01 §2.2 step 6. Build from raw soundings of the same cruise or leg as the ship
   grid.

---

## 7. Manifest v2

Write `manifest/pairs_v2.parquet`. Do not overwrite `pairs.parquet`. It contains:
- the existing 39 pairs unchanged;
- the new development pairs;
- a `designation` column (`development`, `development (ruling H1)`, `confirmatory`, `lockbox`);
- a `harmonized_path` column that is authoritative per contract v2 §2.

Confirmatory pairs appear with path and designation only. No derived statistics.

Validate that every development pair's products pass contract v2.

---

## 8. Report

- **§1 Bottom line**, at most 8 points:
  - challenge findings;
  - v2 QA outcome (pairs flagged, by flag);
  - snapshot paths and hashes;
  - PANGAEA discovery counts and the designation (with hashes);
  - verification outcomes, including every designation change;
  - pairs acquired, by designation;
  - download volume and wall time;
  - manifest v2 summary.
- **Counts table** of development and confirmatory: units and pairs, before and after §5–§6.
- **HOLDs:** at most 3.
- **"Not pursued":** one line per item.
- Scripts as run are committed.

## 9. Out of scope

- Pretraining corpus building or downloads.
- Any model, baseline or target on confirmatory units.
- Modifying existing harmonized files, `lr.tif`, `pairs.parquet` or v1 products.
- Repairing legacy formats.
- Lockbox access beyond the §3.2 byte copy.
- Transferring snapshots off-cluster.
