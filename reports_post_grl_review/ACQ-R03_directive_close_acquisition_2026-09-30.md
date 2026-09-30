# DIRECTIVE ACQ-R03 (Phase 1, acquisition repo): PANGAEA fetch, contract v2.1, review packages, closing acquisition

**Date:** 2026-09-30
**Author:** steering instance, for Claude Code on Sherlock (acquisition repo)
**Follows:** ACQ-R02 (`reports_post_grl_review/ACQ-R02/REPORT_ACQ-R02_2026-09-30.md`)
**Companion:** `INTERFACE_CONTRACT_v2.1.md`. Commit it verbatim to `reports_post_grl_review/` before any §2 code runs.
**Report to:** `reports_post_grl_review/ACQ-R03/REPORT_ACQ-R03_<date>.md` (committed).
**Compute:** CPU jobs as needed. Downloads are authorized for §1 only.

---

## 0. Rulings, order, standing rules

### Steve's rulings on the ACQ-R02 HOLDs (binding)

- **H1, PANGAEA raw swath:** acquire pu00 (Venere, M112) and pu01 (Chapopote, M114/1) by footprint-subset fetch (§1).
  Steve may also supply files manually (§1.4).
- **H2, NR07-1 (MGDS:31813 / 31814):** the drop is accepted. No alternative LR search.
- **H3, confirmatory co-registration (KN182L03__MGDS_30193, SUM1004__MGDS_33090):** Steve decides by QGIS review
  under the seal, against a criterion written down before the review (§5). This directive prepares the review; it
  does not decide it.

### Order

1. §1 PANGAEA fetch. It runs in the background throughout.
2. §2 Contract v2.1.
3. §3 AT37-05 review package.
4. §4 Amundsen `lr_native` audit.
5. §5 Confirmatory review package.
6. **Stop and report.**
7. §6 Finalize. This runs only after Steve has committed `rulings_ACQ-R03.md` with his decisions on §3 and §5 and any
   §4 HOLD, and after §1 completes or is ruled on.

### Standing rules

**Scope discipline.** Do the items below and nothing else. Record any tempting extra in one line under "Not pursued".
Do not run it.

**Challenge clause.** Report any wrong or underspecified instruction in §1 of the report, with evidence. Items that are
Steve's call become HOLDs (at most 3). Where this directive's assumptions are wrong, say so and follow the repo.

**Lockbox and confirmatory seal.** As in ACQ-R02: the guard is installed on import in every script. For confirmatory
units, no residual amplitude statistic, difference map, k sweep, target or products.

**Anti-circularity.** As always. PANGAEA processed grids (for example 891656 for M112, 900987 for M114) may be used
**only** as footprint proxies. They are never LR.

---

## 1. PANGAEA raw-swath fetch (pu00 Venere, pu01 Chapopote)

The whole-cruise fetch (47.7 GB at ≈ 0.14–0.25 MB/s) is the problem. Both HR footprints are small (28.7 km² and
6.3 km²), so fetch only the files that can hold soundings under them. This is the same practice as the NCEI
nav-subset. The fetch is resumable and throttled.

**Access model.** `hs.pangaea.de` has directory listings disabled. A folder path such as `/bathy/M112/EM122/` returns
"Directory listings … are disabled by the server administrator" (confirmed by Steve, 2026-09-30). Individual files are
served at their full URLs; ACQ-R02 landed 1.2 GB this way. Therefore:
- File URLs come **only** from each dataset's tab export (`https://doi.pangaea.de/10.1594/PANGAEA.<id>?format=textfile`):
  the "URL all" column for 864677 and the "URL file" column for 892317. Parse past the `/* … */` metadata header.
- Never request, crawl, construct or truncate a directory URL. Never infer file names from a directory.
- Every URL used must end in the file name recorded in the same row. A row whose URL does not is reported and
  skipped, not repaired.
- Before the full fetch, request **one** complete selected file URL and report the HTTP status, `Content-Length`, and
  whether `Range` is honoured. This single test answers the M112 option-2 question in §1.2.

### 1.1 Current state

Inventory what the ACQ-R02 chain has landed. Keep a file only if its size equals PANGAEA's advertised size (kByte
column, ±1 kB) and `mbinfo` reads it. Cancel any still-running ACQ-R02 fetch jobs once this directive's plan is ready.

### 1.2 File selection

Buffer each HR footprint by the repo's nav-subset rule (4 km).

**M114/1 (PANGAEA 864677).** The tab export carries per-file bounds (Longitude east/west, Latitude north/south) and a
WKT ship-track geometry per file. Select files whose WKT track intersects the buffered footprint. Fall back to the
bounds only where the WKT is missing.

**M112 (PANGAEA 892317).** The tab export has file name, format, size and URL only; no per-file geometry. Derive
positions in this order and state which method was used:
  1. Look for M112 underway navigation on PANGAEA (a DSHIP or track dataset with timed positions). If one exists,
     take each file's start time from its Kongsberg file name (`NNNN_YYYYMMDD_HHMMSS_*.all`). A file spans
     [its start, the next file's start). Select files whose navigation segment intersects the buffered footprint.
  2. Otherwise, test whether `hs.pangaea.de` honours HTTP `Range`. If it does, read the first 2 MB of each `.all` and
     take positions from its position datagrams with MB-System. Select as above.
  3. Otherwise, fetch the whole cruise's `.all` files, as in ACQ-R02.

Fetch only `.all` files, never `.wcd` water-column files.

Report the selected file count and volume per cruise, against the whole-cruise figures.

### 1.3 Fetch

- One worker, polite throttle, exponential back-off on 429/503, resumable.
- Byte-exact against the advertised size, then sha256.
- Store in OAK `raw_lr_swath/<cruise>/` with files 0444 and `fetch_manifest.json`.
- Report achieved throughput and wall time.
- If throughput stays below 0.1 MB/s for 6 h, or the selected set is not complete within 48 h of wall time, stop and
  report as a HOLD with the number of files remaining.

### 1.4 Manual-ingest path

Steve may download selected files himself and place them in OAK `raw_lr_swath/_inbox/<cruise>/`.

Write `ingest_manual.py`. It accepts a file only if:
- its name is in the §1.2 selection;
- its size equals the advertised size (±1 kB);
- `mbinfo` reads it.

Accepted files are sha256'd and moved to `raw_lr_swath/<cruise>/` with files 0444, and recorded in
`fetch_manifest.json` with `"source": "manual"`. Rejects stay in the inbox and are listed in the report.

Publish the §1.2 selection as `pangaea_selection_<cruise>.csv` in the report directory, so Steve can download from it.
Each row holds:
- the file name;
- the advertised size;
- the **complete** file URL, taken verbatim from the tab export.

Also publish `pangaea_selection_<cruise>_urls.txt`, one complete URL per line, so the list can be passed straight to a
download manager or `wget -i`. A browser or tool opening a URL from these files downloads that single file. Opening
the folder part of a URL is what produces the "directory listings disabled" message.

Publish the selection files as soon as §1.2 is done, before the automated fetch starts, and say so in a short interim
note to Steve. The automated fetch and manual downloads may run at the same time. `ingest_manual.py` skips files the
automated fetch already holds, and the automated fetch skips files already ingested.

### 1.5 Grid, harmonize, products

When a cruise's selected set is complete:
- Run the standard chain (stage C → C.5 → F, with the three ACQ-R02 HR-assembly rules).
- Standard QA, k sweep, QC figure.
- Contract-v2.1 products.

Both units are **development**. If a selected subset turns out to leave HR cells uncovered (`fill_fraction_per_hr`
< 0.9), report it. Do not widen the selection without a HOLD.

---

## 2. Contract v2.1

1. Commit `INTERFACE_CONTRACT_v2.1.md` verbatim.
2. **Header check.** For the three pairs whose v2 argmin is ≥ 0.5 cell (CCZ, DISCOL, TAG), and for EW0207 and EW9801
   (which the ACQ-R02 text described as 0.5–0.75 cells off, but whose table argmins are 0.25 cells), establish from the
   original grids and the harmonization code:
   - each grid's registration (GMT node or pixel; GeoTIFF `PixelIsPoint` or `PixelIsArea`);
   - how `harmonize_pair` interpreted it;
   - the implied offset in metres, in `lr.tif` coordinates.

   Report the evidence per pair. Correct whichever ACQ-R02 statement is wrong.
3. **Frame offset.** Apply it only where the header check establishes a registration mismatch
   (`basis: grid_header_registration`). Never fit it from the QA surface.
4. **Build.** Build `ship_products_v2_1/` for the 16 existing pairs with products, plus the new development pairs.
   - `ship_products_v1/` and `ship_products_v2/` stay untouched.
   - Write v2.1 unavailable `products.json` files for Cal DIG.
5. **Validate.** Validate everything against v2.1.
6. **Control.**
   - For pairs with no frame offset, v2.1 rasters equal v2 exactly (NaN-aware).
   - For pairs with a frame offset, report the new argmin and gain. The expected argmin is within ±0.25 cell of
     (0, 0).
7. **Report** the v2.1 flag table next to the v2 flags.

---

## 3. AT37-05__MGDS_24043 review package (development pair; Steve decides)

**Question.** Are the bimodal in-cell soundings (rsd/sd 0.08, v2 median offset +46 m) an inconsistency in the ship
data, or real steep terrain (Siqueiros transform)?

### 3.1 Criterion (commit before building the package)

Keep the pair if the two depth populations co-occur within single lines and pings at a spatial pattern consistent with
slope.

Drop the pair if the populations separate by survey line, file or time, with a line-to-line depth offset in overlapping
cells that exceeds the local robust spread. Such a separation is a ship-internal inconsistency, which `lr.tif` has
averaged into the LR input.

### 3.2 Package

Written to OAK `review/acq_r03/AT37-05__MGDS_24043/`, all GeoTIFF or GeoPackage, in `lr.tif`'s CRS:
- `lr.tif` hillshade;
- HR hillshade;
- `ship_count`;
- `ship_rsd`;
- a per-cell bimodality map: the gap between two depth clusters (k-means with k = 2 on the cell's soundings, where
  count ≥ 6) and the fraction of soundings in the minor cluster;
- the sounding points of the 3 most bimodal 2 × 2 km windows, attributed with file, ping, beam and depth;
- a per-line table of the median depth difference against every overlapping line, in shared cells.

### 3.3 Report

Report the per-line offset table summary and the fraction of bimodal cells. Add one sentence on which side of the
criterion the numbers fall. **Do not drop or keep the pair**; that is Steve's call.

---

## 4. Amundsen `lr_native` audit (unit lu18)

`2009_Amundsen__MGDS_30046` (existing) records `lr_native` 16 m. `2009_Amundsen__MGDS_30047` (new) was gridded at
2.91 m (median depth 167 m, EM302, 1°).

For each pair, report:
- the median depth under its HR;
- the documented-beam-footprint value;
- the gridding cell actually used, and where it came from (the June record for 30046, `grid/2009_Amundsen.json` for
  30047);
- the C2a `lr_native` = max(footprint, posting).

If both pairs follow the same rule and the difference is explained by depth, no change; state so. If either deviates
from the standard, report it as a HOLD with the evidence. Do not regrid or modify either pair in ACQ-R03.

---

## 5. Confirmatory co-registration review package (sealed; Steve decides)

**Pairs:** KN182L03__MGDS_30193 (nu01a, 48.1 m) and SUM1004__MGDS_33090 (nu03, 46.7 m).

### 5.1 Criterion (commit before building any package)

1. Extract the recorded basis for every existing corpus pair accepted with a co-registration offset > 30 m
   (`offset>30m_USBL_QGIS_basis`): pair id, offset, the stated rationale, and any recorded review notes.
2. Write the criterion Steve applied to those pairs as `confirmatory_review_criterion.md`, quoting the records.
3. **Commit it before any confirmatory package is rendered.**
4. If the records do not state a criterion, write "no recorded criterion" and propose none. That becomes a HOLD.

### 5.2 Package, under the seal

Written to OAK `harmonized_confirmatory/<unit>/<pair>/review/` with files 0444. It contains **only**:
- HR hillshade and LR hillshade, each before and after the rigid co-registration shift;
- matched contour lines from HR and LR at a common interval;
- the shift vector and the co-registration search surface;
- the HR navigation basis, if recorded (USBL, DVL, LBL).

**Excluded:** no HR−LR difference map, no residual statistic, no amplitude, spectral or roughness quantity.

### 5.3 Report

Report the package paths only. Nothing is computed or reported beyond what the §5.2 list contains.

---

## 6. Finalize (only after `rulings_ACQ-R03.md` is committed)

1. **Apply Steve's §3 and §5 rulings.**
   - A reinstated confirmatory pair returns to its own unit under the seal (a QA ruling, not a reassignment).
   - A dropped pair goes to the dropped list.
2. **Labels.** Correct the unit geography labels and designation strings in the manifest:
   - MGDS:5174's location (the ACQ-R02 text calls it a "Necker-Ridge grid", but it is assigned to lu05, EPR 9°N);
   - the lu07 name (Necker Ridge vs Loihi / EW9801);
   - AT37-05's designation (`joins existing unit` vs new unit vu05);
   - any other label found inconsistent with leakage-unit membership.

   Report every change. Leakage-unit memberships are not changed unless a label error reveals a membership error. If it
   does, that becomes a HOLD.
3. **Manifest v2.1.** Write `manifest/pairs_v2_1.parquet`. `pairs_v2.parquet` is not modified.
   - Add pu00 and pu01 if acquired.
   - Apply the §3 and §5 outcomes and the label fixes.
   - Record the ruling source per changed row.
4. **Validate.** Every development pair's products pass v2.1.
5. **Development unit table.** For every development unit, list: pairs, tiles at ≥ 50 % joint validity, k (or no-k),
   products availability, v2.1 flags, basin and setting. Give separate counts of usable units and usable pairs
   (excluding no-k pairs).

This table closes Phase 1 acquisition.

---

## 7. Report

- **§1 Bottom line**, at most 8 points:
  - challenge findings;
  - PANGAEA fetch outcome (selection size, landed, throughput);
  - v2.1 flags before and after the frame offset;
  - the AT37-05 numbers;
  - the Amundsen audit;
  - review package paths;
  - after §6: manifest v2.1 and the development unit table.
- **HOLDs:** at most 3.
- **"Not pursued":** one line per item.
- Scripts as run are committed.

## 8. Out of scope

- New discovery, of any source.
- Alternative LR for dropped pairs.
- Regridding or modifying any existing harmonized file, `lr.tif`, `pairs.parquet` or `pairs_v2.parquet`.
- Anything on confirmatory units beyond §5.2.
- Pretraining.
- Any model or target computation.
