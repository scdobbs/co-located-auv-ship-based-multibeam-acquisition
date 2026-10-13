# DIRECTIVE ACQ-R08 (acquisition repo, CPU only): metadata-only inventory of candidate pairs for a second blind test

**Date:** 2026-10-12
**Repo:** `co-located-auv-ship-based-multibeam-acquisition`
**Report to:** `reports_post_grl_review/ACQ-R08/REPORT_ACQ-R08_<date>.md`
**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.
**Report length:** at most 8 bullets, plus the candidate table, the funnel table and at most 3 HOLDs.

## 0. Purpose

Phase 4 did not confirm that within-site ranking transfers to unseen sites, and the cause is unknown (R13, R14).
Steve has ruled that we look for a second set of independent pairs for a new, separately pre-registered blind test.

This directive builds an **inventory only**. It finds candidate pairs, estimates from metadata whether each would
fall inside the development range, and reports. It downloads no bathymetry, grids nothing and designates nothing.
Steve chooses the eligible set from the report. A new pre-registration (v3) is then written and signed **before
any candidate is downloaded or processed**.

**Blindness.** No one, executor or Steve, may see any image, pixel value or statistic of a candidate's bathymetry
before v3 is signed. Use catalog metadata only: titles, abstracts, DOIs, bounding boxes, stated resolution, depth
range, platform, sonar, dates, file lists and navigation footprints. Do not open, render or summarise any raster,
grid, sounding file, hillshade, preview image or thumbnail. If a quantity can only be obtained by downloading
data, record it as `needs download` and do not download.

**Challenge clause.** If any instruction here is wrong or underspecified against the sources or the repo, stop at
that point, give the evidence, and report it as a HOLD. Do not work around it.

## 1. Exclusions (applied first; report counts)

A candidate is excluded if any of these hold:

1. It is, or overlaps, any pair in manifest v2.1: the 16 development units and their 38 pairs, EW0207, the two
   lockbox pairs, the three confirmatory pairs, and every pair rejected in ACQ-R01 to ACQ-R07.
2. Its high-resolution footprint lies within 10 km of any of those footprints. Report the distance to the nearest
   one for every candidate, and flag those within 50 km.
3. It overlaps the Cal DIG area.
4. Its low-resolution side is a compilation (GMRT, GEBCO, USGS or other multi-source mosaics) rather than one
   identifiable ship cruise with raw swath available.
5. The high- and low-resolution sides come from the same cruise or share soundings.

## 2. Candidate pools

**Pool A, AUV high resolution.** AUV (or other near-bottom vehicle) bathymetry grids not in the corpus, from:
MGDS, PANGAEA, SEANOE, NCEI, USGS ScienceBase / CMGDS (including MBARI-donated surveys), and releases added since
the September discovery runs (for example AUV Sentry surveys from Schmidt Ocean or NOAA cruises). Re-run the
existing discovery engine against current catalogs where possible, rather than writing a new one.

**Pool B, surface-vessel high resolution (separate pool).** NOAA hydrographic BAG surveys gridded at 4 m or finer,
each paired with an independent ship multibeam cruise over the same seafloor from the NCEI multibeam archive
(raw swath, a different cruise, never a compilation). Pool B is a different sensor; it is reported separately and
never pooled with Pool A.

**Pool C, previously rejected pairs.** List every pair rejected in the June and September acquisition runs, with
its recorded reason. Mark each reason as still applicable or not under the current rules (for example, the old
5 to 25x ratio gate was retired). Re-screen under §3 only those whose reason no longer applies.

**Optional, Steve's holdings.** If Steve places `inputs/steve_holdings.csv` in the repo (survey name, location,
resolution, depth, releasability), screen it the same way. If absent, skip.

## 3. Eligibility estimates (metadata only)

For each candidate that survives §1, estimate and report:

| field | how |
|---|---|
| `hr_res_m` | stated grid resolution from the catalog record |
| `lr_cruise`, `sonar`, `year` | the independent ship cruise(s) over the footprint, from NCEI / MGDS metadata |
| `lr_est_m` | estimated ship grid cell: if the cruise metadata states a gridded product spacing, use it; otherwise estimate from sonar beam width and the stated depth range (footprint at mean depth), and record the method |
| `cells_across_est` | `256 * hr_res_m / lr_est_m` |
| `ratio_est` | `lr_est_m / hr_res_m` |
| `band_feasible` | whether a fine band with k of at least 2 can exist under the 0.45 cycles per px clip: true if `ratio_est >= 4.5` |
| `overlap_km2_est` | from navigation footprint against the high-resolution bounding box (bounding box only, flagged as an upper bound) |
| `tiles_est` | `overlap_km2_est / (128 * hr_res_m / 1000)^2`, rounded down |
| `depth_range_m`, `setting` | from the catalog record (region, named features, abstract keywords); no inference from data |
| `releasable` | licence permits use and redistribution of derived products |
| `size_est_gb` | download size of both sides, from file lists |

Then assign a status:

- **in range** if all hold: `band_feasible`; `cells_across_est` between 3.88 and 51.2 (the development range);
  `hr_res_m` between 1.0 and 4.99 (the development range); `tiles_est` of at least 300; independent raw ship swath
  available; releasable.
- **outside range** if any range condition fails; give which.
- **uncertain** if a needed field is `needs download` or the estimate method is weak; give which field.

The 300-tile floor is a planning number only, chosen so that after interior masking a pair is likely to keep at
least 10 tiles in 8 blocks; it is not a scoring rule.

## 4. Must hold

1. No bathymetry raster, grid, sounding file, preview or thumbnail was downloaded, opened or rendered. List every
   network request type made (catalog APIs, ISO / XML records, file listings, navigation footprints).
2. Every excluded candidate has one recorded reason from §1 or §3.
3. Every in-range candidate has a named independent ship cruise with raw swath available.
4. No candidate is designated, seeded or split. Selection is Steve's.

## 5. Report

1. **Funnel table, per pool and source:** records found; excluded by each §1 rule; screened under §3; in range;
   outside range (by failed condition); uncertain. These counts also serve the paper's data-availability paragraph.
2. **Candidate table:** every in-range and uncertain candidate with all §3 fields, sorted by pool, then by
   `tiles_est` descending. Outside-range candidates go in a separate table with the failed condition.
3. **Pool C table:** each previously rejected pair, its reason, and whether that reason still applies.
4. **Summary per pool:** how many in-range candidates, their total estimated tiles, their spread of settings and
   regions, and the total download size.
5. Name anything Steve may already have seen (for example, surveys he has worked on), so it can be stated as prior
   exposure or excluded.

## 6. Preservation and record

Commit the scripts, the metadata cache (catalog records and footprints only) and the report by explicit path;
never `git add -A`. Add one `CHANGE_LEDGER.md` row. Copy the report and the candidate tables to OAK
`acq_archive/ACQ-R08/` with `SHA256SUMS` verified.

## 7. Out of scope

- Downloading, opening, gridding or viewing any bathymetry of any candidate.
- Designating, seeding or splitting candidates; writing the v3 pre-registration.
- Any write to the CNN repo.
- Any change to manifest v2.1, the sealed supplement, or any frozen record.

## 8. Not pursued

- Legacy GMRT versions as low-resolution partners (compilations, and about 2 cells per tile at 100 to 120 m).
- Simulating old-sonar noise.
- Re-screening Cal DIG or the Amundsen pairs.
