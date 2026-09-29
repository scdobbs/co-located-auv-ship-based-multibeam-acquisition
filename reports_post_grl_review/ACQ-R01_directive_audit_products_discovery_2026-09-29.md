# DIRECTIVE ACQ-R01 (Phase 0/1, acquisition repo): audit, ship-side products, discovery counts, confirmatory designation

**Date:** 2026-09-29
**Author:** steering instance, for Claude Code on Sherlock (acquisition repo: `co-located-auv-ship-based-multibeam-acquisition`)
**Companion:** R04 (CNN repo) runs in parallel. `INTERFACE_CONTRACT_v1.md` governs §2.
**Report to:** follow this repo's existing report convention. If there is none, use `directives_and_reports/ACQ-R01/REPORT_ACQ-R01_<date>.md`.
**Series:** ACQ-R*, which is distinct from the CNN repo's R-series.
**Compute:** CPU jobs as needed. Downloads are authorized (§2.3).

---

## 0. Purpose

Four jobs, in order:

1. Audit this repo's current state.
2. Build the interface-contract ship products for every existing non-lockbox pair, and persist raw swath to OAK.
3. Re-run discovery and the gate to produce **counts only**, with no acquisition of new pairs.
4. Designate new candidate leakage units as development or confirmatory, before any of their data is examined.

**Scope discipline.** Do the items below and nothing else. Record any tempting extra in one line under "Not pursued".
Do not run it.

**Challenge clause.** Report any wrong or underspecified instruction in §1 of the report, with evidence. Items that are
Steve's call become HOLDs. The steering instance knows this repo less well than the CNN repo. Where the directive's
assumptions about stage names, files or conventions are wrong, say so and follow the repo.

**Lockbox.** AT42-03__MGDS_32007 and TN159__MGDS_21981. Install a path guard equivalent to the CNN repo's
`r03_common.install_lockbox_guard()` in every new script. No product, download, grid or QA for these two pairs in
ACQ-R01. Any manifest-wide loop skips them explicitly.

**Anti-circularity (non-negotiable, as always).**
- HR = AUV. LR = independent surface-ship multibeam.
- No composites (GEBCO, GMRT, USGS compilations that ingest AUV data) as LR.
- No LR synthesized from HR.

---

## 1. Audit (report only)

1. **Stage map.** Every pipeline stage as the repo actually runs it (discovery → gate → fetch → grid → harmonize →
   QA/co-registration → manifest), with its entry script, inputs, outputs and output location (OAK or scratch).
2. **Storage state.** What exists on OAK vs scratch today. What was purged: R03 found `raw_lr/` and `raw_lr_gridded/`
   empty. What is recoverable from persisted URLs or plans.
3. **Corpus reconciliation.** The current 39-pair / 19-leakage-unit corpus (plus the lockbox) against the last gate
   run. An earlier gate reported about 73 acquirable HR (27 training + 18 eval-only + 28 raw_lr_to_grid).
   - List every candidate that is **not** in the corpus, with its recorded exclusion reason.
   - Mark a candidate "reason unrecorded" where there is none.
4. **Leakage-unit code.** Confirm it implements the conservative policy (shared acquisition on either the HR or LR
   side → same unit, including the LR-cruise axis), and name the function.

---

## 2. Interface-contract ship products (`INTERFACE_CONTRACT_v1.md`)

### 2.1 Pairs in scope

All pairs of the 15 development units plus EW0207, excluding the lockbox and the three no-k pairs (KIWI10RR, TN268,
FK181031__MGDS_24367). That is 12 NCEI-swath cruises (Amundsen included) plus the provider-grid units (Cal DIG, CCZ,
DISCOL, TAG).

### 2.2 Build

For each NCEI cruise:

1. **Fetch** the swath files listed in the persisted fetch plan (`stage_b_file_plan_*.csv`) for that cruise, exactly as
   the original stage-C run used them (same file subset, same `whole` / `subset` mode). Verify sizes and record sha256.
   Store the raw swath permanently on **OAK** (`.../auv_ship_colocated_bathy/raw_lr_swath/<cruise>/`), not scratch.
2. **Extract soundings** with MB-System 5.8.2beta06 (same Apptainer sandbox) using `mblist`: longitude, latitude,
   depth, acrosstrack distance, beam angle, and ping identity. Before use, **verify the `-O` field codes against the
   installed `mblist` man page**, and record the exact command in `products.json`.
   - Swath half-width per ping = max |acrosstrack distance| among that ping's valid beams.
   - Use the same processing mode (raw or cleaned) the original gridding used. State it.
3. **Bin** soundings onto the pair's harmonized `lr.tif` grid: its CRS, transform and shape. Transform coordinates
   with the same CRS machinery stage F used. Per cell, compute count, mean depth (sign convention as `lr.tif`), SD
   (count ≥ 2), mean |acrosstrack|/half-width, and mean |beam angle|.
   - This deliberately does **not** use `mbgrid`. `mbgrid`'s interpolation and footprint weighting are what made
     R03's pilot grid differ from `lr.tif` by 1.13 m RMS. Direct binning on the target grid gives products that are
     cell-exact.
4. **QA against `lr.tif`.** Compute RMS, median offset, MAD and RMS / median s_lr for `ship_mean_regrid` vs `lr.tif`
   on common cells.
   - Flag `exceeds_0.10` where RMS / median s_lr > 0.10. Do not fix, re-grid or tune.
   - A flagged pair keeps its products. The flag travels in `products.json`, and the CNN repo decides.
5. **Write** the rasters and `products.json` per the contract. Validate them with the contract's schema; the CNN repo
   commits the validator, but you may copy it.

For the provider-grid units (Cal DIG, CCZ, DISCOL, TAG):

6. **Check whether raw soundings exist** for the provider grids (for example, PANGAEA raw EM122 for SO242/SO268/M127;
   USGS Cal DIG I source data).
   - If they exist and correspond to the provider grid's survey, fetch and build as above.
   - Otherwise write `products.json` with `available: false` and the reason.

   Report which case applied per unit.

### 2.3 Downloads

Authorized as needed for §2, including Amundsen (≈ 27 GB). Report the total volume and wall time.

### 2.4 Beam-geometry test (the one analysis in this directive)

**Question:** does the resolved-band tilt (the per-tile plane term) follow cross-track position? If it does, that is
ship refraction or outer-beam error. If it does not, the misfit's origin is not attributable to the ship this way.

**Inputs (read-only):**
- R03 per-tile table: `/scratch/users/scdobbs/grl_review/R03/s3/s3_pertile.parquet`, or its OAK archive copy once
  R04 §6 has run;
- tile footprints from R02/R03.

**Method:** for the native NCEI units only (NA090, NA080, TN399, RR1506, AT37-13, FK181031, TN299, EW0207):

1. Per tile: plane² = T_res² − T_res_lp².
2. Per tile: mean `ship_xtrack_frac` and mean `ship_beam_angle` over the tile's LR cells.
3. Within-unit Spearman ρ of log plane with mean xtrack_frac, and a partial ρ given log slope (R02 bicubic tile slope)
   and log s_lr. The same for log T_res_lp.
4. Report per unit and the median over units, with a bootstrap-over-units CI (2,000 resamples).

No interpretation beyond one sentence.

---

## 3. Discovery re-run: counts only, no acquisition

1. Re-run discovery and the gate with the **current** QA standard, independence screening and conservative
   leakage-unit policy. Do not fetch HR or LR for any new candidate beyond the metadata the gate needs.
2. Report:
   - candidate pairs by tier;
   - new leakage units under the conservative policy;
   - for each new unit: ocean basin, setting / terrain class (as discovery metadata records it), depth range, ship
     cruise(s), HR source, estimated data volume, and expected `lr_native` and k where the gate can estimate them;
   - candidates that would join an **existing** unit (shared acquisition): list them. They are neither new
     development nor confirmatory units;
   - any candidate sharing acquisition with a lockbox pair: list it and exclude it from §4.

---

## 4. Confirmatory designation (run once, before any new data is examined)

1. Write `designate_confirmatory.py`:
   - input: the §3 new-leakage-unit list with metadata only;
   - stratification: by setting class; if a stratum has one unit, merge strata by basin and state the merge;
   - within each stratum, assign units 50/50 to `development` / `confirmatory` with **seed 20260929**; odd counts put
     the extra unit in `confirmatory`.
2. **Run it once.** Commit the script, its input list (sha256) and the output assignment (sha256) **before** any
   later acquisition. Report the assignment table.
3. **Rules that bind all later work:**
   - A unit that later fails acquisition or QA is **dropped from its assigned set**, never reassigned.
   - Acquisition QA may inspect HR for data quality (co-registration, artifacts). No model, baseline or target value
     is computed on a confirmatory unit until Phase 4.
   - Units added by any later discovery run go through the same script with a new seed, recorded.

---

## 5. Pretraining-corpus scoping (report only; building is ACQ-R02)

Estimate what ship-only multibeam exists at NCEI (MBBDB) for self-supervised pretraining. Exclusion zones:

- every development, confirmatory, candidate and lockbox unit's footprint (HR and LR), buffered by 10 km;
- GMRT and every other composite.

Report the number of cruises, the swath volume, depth distribution, basin distribution and format mix. Say what
fraction our pipeline can grid unchanged. No downloads for §5.

---

## 6. Report

- **§1 Bottom line**, at most 8 points:
  - challenge findings;
  - audit headline;
  - products built / unavailable per unit, with QA flags;
  - raw swath now on OAK (volume);
  - beam-geometry test result;
  - discovery counts (new units by setting);
  - confirmatory assignment (committed hashes);
  - pretraining-corpus scale.
- **HOLDs:** at most 3.
- **"Not pursued":** one line per item.
- Scripts as run are committed.

## 7. Out of scope

- Acquiring new pairs (that is ACQ-R02, after this report).
- Changing any existing harmonized file or `lr.tif`.
- Any model or target computation on new units.
- Lockbox access.
- Pretraining downloads.
