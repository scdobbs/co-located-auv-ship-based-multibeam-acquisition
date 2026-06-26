# Acquisition Directive v1.4 — Automated Pair Discovery (footprint spatial-join engine)

**For the same instance** that ran v1.0–v1.3. This adds a **discovery module** upstream of the existing acquisition/harmonization path. It generalizes the manual companion-lookup you've done per cruise (Tier 2/3, Marmara, Cascadia) into a single query-an-index step, so finding co-located AUV/ship pairs no longer means sifting websites.

Build it as a **new, separate module** (`src/discovery/`). It does **not** download bulk rasters and does **not** harmonize. It produces a lightweight *ranked candidate-pairs catalog* for human triage; selected pairs then flow into the validated v1.0–v1.3 download → harmonize → co-register → QA → manifest path unchanged.

---

## 1. Why

Across DISCOL, Cal DIG, Marmara, and Cascadia the bottleneck has been the same: AUV HR exists scattered across archives, a ship LR may or may not co-locate, and pairing means a spatial overlap + independence check done by hand. That is a spatial join over dataset footprints, not a browsing task. This module builds a footprint catalog once and queries it, turning opportunistic discovery into systematic coverage — including telling you which geomorphic provinces are thin so you can target gaps.

---

## 2. Scope & non-goals

**In scope:** harvest footprint + metadata catalogs via APIs; spatial-join HR×LR; score, screen for independence, rank; emit a candidate-pairs catalog + coverage summary.

**Out of scope:** no bulk raster download, no reprojection, no co-registration, no manifest writes. Discovery proposes; the existing pipeline disposes, behind the human confirm-before-download gate.

**APIs, never scraping.** All sources below expose REST/OGC services. Do not parse HTML.

---

## 3. Harvest HR candidates (AUV bathymetry grids)

Primary source **MGDS**, using the verified services:
- **ISO19115 metadata service** (all datasets) + **FileServer** (file/dataset metadata including *detailed file boundary geometries* and file identifiers for later download via FileDownloadServer).
- Filter to **device = AUV** and **data type = bathymetry grid** (GeoTIFF / netCDF / ESRI ASCII).
- Extract per dataset: DOI, title, platform (AUV model), sonar, **native resolution** (parse from metadata/description, e.g. "1-meter", "2 m"), format, **footprint geometry**, and the file IDs needed for download.
- **De-duplicate survey families.** One survey/mission spawns many DOIs (raw, processed swath, grid, sidescan, sub-bottom). Key each catalog row on the **gridded bathymetry** product per mission; record sibling DOIs in a field but don't emit them as separate HR candidates.

Fold the already-known non-MGDS HR archives into the **same schema** so the catalog is unified (these are small, register them as static/seed entries or query their APIs):
- **PANGAEA** (AUV ABYSS grids — DISCOL etc.), **USGS ScienceBase** (MBARI-donated, e.g. Cal DIG), **SEANOE** (IFREMER AsterX / Marmara). Carry each source's license (CC-BY, public-domain, CC-BY-NC-SA) as a field — they differ and it matters downstream.

---

## 4. Harvest LR candidates (independent ship multibeam footprints)

Primary source **NCEI Multibeam Bathymetry Database (MBBDB)**:
- Query the **NCEI multibeam-surveys ArcGIS REST layer** (FeatureServer/MapServer `/query`) with each HR footprint as the input geometry, `spatialRel=intersects`, `f=geojson` → returns overlapping ship-survey footprints with cruise IDs.
- **Confirm the exact layer URL at runtime** from the NCEI GIS services directory (under `gis.ngdc.noaa.gov/arcgis/rest/services`) — enumerate and identify the multibeam-surveys layer; do not hardcode a path, NCEI reorganizes them.
- For each returned cruise, pull the **Geoportal REST ISO metadata** (`ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ngdc.mgg.multibeam:<CRUISE>_Multibeam/...`): platform, sonar, dates, bounds, download links, and **whether a processed grid/BAG exists vs raw-only**.

Optional secondary LR layers (flag by provenance): **IHO DCDB** footprints (broader, includes crowdsourced — lower priority), and the **NOS hydrographic BAG footprints** layer (for shallow/coastal HR).

**Query individual cruise footprints — never pre-built composites** (GMRT, GEBCO, USGS composites). Composites are the independence trap (§6).

---

## 5. Spatial join & scoring

- Join on **actual boundary polygons**, not bounding boxes — a bbox overlap can be a swath miss. Use FileServer boundary geometries for HR and the ArcGIS footprints for LR.
- Per intersecting HR×LR pair compute: `overlap_km2`, `overlap_frac_hr`, `res_ratio` = LR_gsd / HR_gsd, depth range, terrain hint.
- **Flags:** `lr_has_processed_grid` (raw-only LR will need gridding downstream, as the Cascadia composite did via Caris); `high_ratio` (flag ≳20×, e.g. 30 m→1 m, as aggressive-for-SR); `low_overlap` (below `pair_qa.min_overlap_area_km2`).
- **Score/rank** by overlap area, sensible ratio, processed-grid availability, license permissiveness, and **province** (boost under-represented terrain classes so triage surfaces coverage gaps).

---

## 6. Independence screen (the recurring trap — enforce it)

Every prior dataset taught this lesson; bake it in:
- **Exclude composites/syntheses as LR** (GMRT, GEBCO, USGS composite grids). If a composite is the only available LR over an HR footprint, do not pair it directly — instead use the composite's **data-source polygon** (e.g. the Cascadia `*_bathy_sources_v2.shp`) to identify the underlying *independent* ship survey at that footprint, and pair against that survey.
- **Reject same-platform / self-pairs:** if the LR is the AUV regridded, or LR platform == HR platform with the same sonar, reject.
- **Same-cruise nuance (do not over-reject):** an AUV is usually flown from a ship that also runs a hull multibeam — that hull MBES *is* a valid independent LR (different sonar, surface vs near-bottom). So a same-cruise LR is allowed **only** when it's the hull sonar, not the AUV data archived under the same cruise. Distinguish them by device type, and flag for human check when ambiguous.
- Emit `independence_verdict` ∈ {`independent`, `composite_excluded`, `same_platform_reject`, `needs_check`} with a reason.

---

## 7. Output

A lightweight **candidate-pairs catalog** (GeoPackage or GeoParquet — footprints + metadata only, no bulk rasters; small enough for the repo, else scratch):

`candidate_id`, `hr_repo`, `hr_doi`, `hr_platform`, `hr_sonar`, `hr_native_res_m`, `hr_format`, `hr_file_ids`, `hr_footprint`, `hr_license`, `lr_source`, `lr_cruise_id`, `lr_platform`, `lr_sonar`, `lr_has_processed_grid`, `lr_native_res_est_m`, `lr_metadata_url`, `lr_footprint`, `overlap_km2`, `overlap_frac_hr`, `res_ratio`, `depth_min_m`, `depth_max_m`, `terrain_hint`, `independence_verdict`, `independence_reason`, `score`, `rank`, `status` (`proposed`|`human_selected`|`human_rejected`).

Plus a **coverage-by-province summary** (counts and total overlap area per terrain class, existing manifest + new candidates) so gaps are visible, and an optional candidate-footprint map for quick scanning.

---

## 8. Human gate & handoff

Discovery only proposes. The human reviews the ranked catalog, sets `status=human_selected` on chosen pairs. Selected pairs then enter the **existing v1.0–v1.3 path**: download HR (MGDS FileDownloadServer / the source archive), obtain or grid the LR, reproject (single warp, never nearest), co-register fresh, run v1.1 §A QA + overlays, write manifest rows with full provenance, run the v1.2.2 completeness + provenance audits. Confirm-before-download is preserved end to end.

The catalog schema aligns with the manifest so a selected candidate maps straight into a manifest row.

---

## 9. Operational

- REST/OGC only; polite throttling; **cache** API responses (footprint catalogs change slowly) and make harvests resumable/idempotent; log every query.
- Catalog artifacts are small — keep in the repo; if a footprint dump grows large, put it under `$DATA_ROOT` on scratch, never home.
- Confirm the NCEI ArcGIS layer URL from the live services directory before the first LR harvest (§4).

---

## 10. Validation / acceptance (ground-truth against known results)

The engine is only trustworthy if it **rediscovers the pairs you already validated by hand**. Acceptance criteria for M3:
- DISCOL, the 18 Cal DIG pairs, and the Cascadia 41.72°N pair all **appear** in the candidate catalog with correct overlap area and resolution ratio.
- Known non-pairs are correctly handled: `LuciaChica1100m` and `8mPockmarkDetail` surface as **no/low LR overlap** (not as valid pairs); the Cascadia *composite* is **excluded** as direct LR while its underlying NOAA/Nautilus ship surveys are found via the source polygon.
- The Marmara EM302 case is flagged `needs_check` (ship grid not openly in MBBDB — manual/IFREMER route), not silently dropped.

If the engine misses a known pair, it's broken — debug before trusting new proposals.

---

## 11. Hard rules

- APIs only; never scrape HTML.
- Join on real boundary polygons, not bounding boxes.
- Never pair against a composite/synthesis as LR; resolve to the independent underlying survey (§6).
- Discovery never downloads bulk rasters or writes manifest rows — it proposes; the human selects; the existing pipeline executes.
- Carry license per source; never assume CC-BY.
- Confirm the NCEI ArcGIS layer URL at runtime; don't hardcode.

---

## 12. Milestones & gate

- **M3.0 — HR harvester.** MGDS ISO/FileServer → AUV-grid catalog with footprints + native resolution; fold in PANGAEA/SEANOE/USGS seed entries. Acceptance: DISCOL, Cal DIG, and the 41.72°N Cascadia HR all present.
- **M3.1 — LR harvester.** NCEI ArcGIS + Geoportal; confirm layer URL. Acceptance: querying the 41.72°N AUV footprint returns the NOAA EM-710 / Nautilus ship surveys.
- **M3.2 — Join + score + independence screen** → candidate catalog. Acceptance: §10 ground-truth checks pass.
- **M3.3 — Coverage summary + ranked output (+ optional map).** **Pause for human triage.**
- Selected pairs hand off to the existing acquisition/harmonization path. Tier 2/Tier 3 manual work can now be driven from the catalog instead of by-hand lookups.
