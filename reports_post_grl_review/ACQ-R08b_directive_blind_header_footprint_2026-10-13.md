# DIRECTIVE ACQ-R08b (acquisition repo, CPU only): download the second-test candidates and measure header and footprint only

**Date:** 2026-10-13
**Repo:** `co-located-auv-ship-based-multibeam-acquisition`
**Report to:** `reports_post_grl_review/ACQ-R08b/REPORT_ACQ-R08b_<date>.md`
**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.
**Report length:** at most 8 bullets, plus the candidate table and at most 3 HOLDs.

## 0. Purpose and rulings

ACQ-R08 found 3 Pool A candidates in range and 11 uncertain, mostly because the catalog gives only a bounding box
or no grid resolution. This directive downloads the high-resolution grids of the candidates and measures, by
script, only what the inventory needs: resolution, extent, valid footprint, a rounded depth, and a tile count.
Nothing about the relief is computed or shown.

**Steve's rulings (2026-10-13), recorded in the report and the ledger:**

1. Downloading the candidate high-resolution grids is allowed, provided no output can bias the later test.
2. Pool B (NOS BAG) is dropped: a BAG at 4 m or finer lies in water too shallow for any ship grid to leave a fine
   band.
3. MGDS conditional terms (CC-BY-NC-SA) are accepted, as for the development corpus.
4. Escanaba Trough (MGDS:30368) stays a candidate; only its metadata has been seen.
5. Steve has not seen any Monterey Canyon AUV data (MGDS:24756); no prior exposure.

**Challenge clause.** If any instruction here is wrong or underspecified against the sources, the code or the
files, stop at that point, give the evidence, and report it as a HOLD. Do not work around it.

## 1. Blindness (the rule for this directive)

The downloaded grids become candidate sealed data for a possible second blind test. From download on:

1. Store them only under `$GROUP_SCRATCH/auv_ship_colocated_bathy/sealed_candidates_v3/<hr_id>/`, group read
   only, setgid as for the lockbox directories.
2. Add that root and every candidate id to the acquisition lockbox guard before the first download, and self-test
   the guard. Report the probe count.
3. Scripts may read: file headers (size, cell size, CRS, extent, nodata value); the validity mask (data or no
   data); and depth values only to compute one median depth per candidate, rounded to the nearest 100 m.
4. Scripts may not compute, write or print any other statistic of depth or of any derived field (no minimum,
   maximum, range, slope, roughness, spectrum or histogram); may not write any image, hillshade, plot, preview or
   thumbnail; and may not open any of these files in a viewer.
5. The executor reports only the quantities of §3. No one opens the grids.
6. The ship side: navigation and file listings only. No raw swath is downloaded or gridded in this directive.
7. Nothing from these files enters the CNN repo or any development, training or tuning step.

## 2. Candidates

Process these Pool A rows from `candidates_pool_a_in_range_and_uncertain.csv` (ACQ-R08):

- in range: MGDS:31860, MGDS:31675, MGDS:31954;
- uncertain: MGDS:30368, MGDS:18210, MGDS:31811, MGDS:24756, MGDS:22436, MGDS:21415, PANGAEA:958275,
  SEANOE DOI:10.17882/55744.

Skip MGDS:31979 (0.04 km2 ROV point file) and the two BODC BioCam records (broken footprints, implausible ship
matches); report them as not processed.

For PANGAEA:958275 (Kolumbo), first check whether its ship partner (M143 EM122) raw swath is publicly downloadable,
by file listing only. If it is restricted, do not download the high-resolution grid; report it as excluded (no
accessible independent ship data).

## 3. What to measure per candidate

| field | how |
|---|---|
| `hr_res_m`, `crs`, `extent` | from the grid header; if several grids per record, list each and use the finest native grid that covers the survey |
| `files`, `size_gb`, `sha256` | per downloaded file |
| `valid_km2` | area of the validity mask (finite and not nodata), in a local UTM projection |
| `hr_footprint` | polygon of the validity mask, simplified to 50 m, written as a vector file |
| `depth_median_100m` | median of valid depths, rounded to the nearest 100 m; the only depth value computed |
| `lr_cruise`, `lr_sonar`, `lr_year` | as in ACQ-R08; re-check by file listing that raw swath is downloadable |
| `ship_coverage` | the ship cruise's track coverage over `hr_footprint`, from navigation files or the NCEI footprint service, buffered by half the estimated swath width at `depth_median_100m` (documented method) |
| `lr_est_m` | `2 * depth_median_100m * tan(beamwidth / 2)` with the documented across-track beamwidth |
| `cells_across_est` | `256 * hr_res_m / lr_est_m` |
| `tiles_est` | number of 256-px windows at stride 128 px whose area is at least 50 % valid in `hr_footprint` intersected with `ship_coverage` (the R05 validity floor), on the grid at `hr_res_m` |
| `same_site_as` | candidates whose footprints overlap or lie within 10 km of each other (for example the two AT15-63 Galapagos records): report them as one site |
| `nearest_corpus_km` | distance from `hr_footprint` to the nearest corpus, sealed or rejected footprint |

Status, as in ACQ-R08 §3: **in range** if `ratio_est >= 4.5`, `cells_across_est` 3.88 to 51.2, `hr_res_m` 0.985 to
4.99, `tiles_est >= 300`, independent raw swath downloadable, and releasable; otherwise **outside range** with the
failed condition. Recompute the three ACQ-R08 in-range rows the same way; they may change.

## 4. Must hold

1. The guard self-test passes before the first download, and no file under `sealed_candidates_v3/` is read by any
   process outside the §3 scripts. Report the guard log.
2. The only depth-derived number in any output, log or report is `depth_median_100m`. Grep the outputs and logs
   for it and report the check.
3. No image or plot file exists anywhere under the R08b outputs. Report the check.
4. Every candidate has a final status with its reason.
5. No candidate is designated, seeded or split.

## 5. Report

1. **Candidate table:** every §3 field and the status, sorted by status then `tiles_est`. Sites merged under
   `same_site_as` are shown as one row with their records listed.
2. **Summary:** the number of distinct in-range sites, their total tiles, their settings and regions, and the
   download size of their ship raw swath (from listings) for the later acquisition step.
3. **Changes from ACQ-R08:** which candidates moved between in range, uncertain and outside range, and why.
4. **Exposure statement:** the exact list of numbers produced per candidate, for the v3 pre-registration's prior
   exposure section.

## 6. Preservation and record

Commit scripts, the footprint vectors and the report by explicit path; never `git add -A`. The grids stay on
scratch under the guarded root; their sha256 list goes to OAK `acq_archive/ACQ-R08b/` with `SHA256SUMS` verified.
Add one `CHANGE_LEDGER.md` row recording Steve's rulings and the new sealed root.

## 7. Out of scope

- Any statistic, image or view of the candidate bathymetry beyond §3.
- Downloading or gridding ship raw swath; co-registration; k sweeps; targets.
- Designating, seeding or splitting candidates; writing the v3 pre-registration.
- Pool B, the BioCam records and the ROV point file.
- Any write to the CNN repo.

## 8. Not pursued

- Legacy single-beam NOS surveys as coarse partners for BAGs.
- Re-screening the 15 outside-range Pool A rows.
