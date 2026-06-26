# Acquisition Directive v1.0 — Co-located AUV / Ship-Multibeam Bathymetry Pairs

**Repo:** `auv_ship_colocated_bathy/` (new, standalone)
**Role of this instance:** data acquisition + harmonization only. No model training, no super-resolution, no synthetic degradation.
**Storage (critical):** all downloaded and harmonized data MUST be written to Sherlock **scratch**, never the home directory — home has only ~15 GB and these rasters will blow past that. Only small text artifacts (code, config, manifest, logs, reports) may live in the repo. See §5 and §8.
**Status of DOIs below:** the AUV DOIs are fixed and verified. Two pairs are fully verified on both sides — DISCOL (Peru Basin) and Cal DIG (Morro Bay) — and are the build anchors. Other ship companions are to-be-confirmed against a known cruise. Do not invent DOIs.

This file can double as the repo's `CLAUDE.md` so a fresh instance auto-reads it on startup.

---

## 1. Why we are collecting these data (read this first)

We are building a super-resolution model (an SR U-Net with rectified flow) that generates ultra-high-resolution seafloor bathymetry from a lower-resolution input. The central data-integrity problem in that effort is **circularity**: the global low-resolution products everyone reaches for — GEBCO and GMRT — *ingest* the same high-resolution multibeam that we would want to use as ground truth. Using GEBCO/GMRT as the low-resolution (LR) input and multibeam as the high-resolution (HR) target therefore leaks the answer into the input, and any apparent success is partly an artifact of that overlap.

The separate, GEBCO/GMRT-focused repository handles the synthetic-degradation training path (degrade HR ourselves to make LR). **This repository exists to build the one thing that path cannot give us: a set of REAL, physically-independent LR/HR pairs for validation.**

The key realization is that **AUV bathymetry surveys are flown over pre-existing ship multibeam maps**, so for many AUV sites the same patch of seafloor has been measured twice by genuinely different acquisitions:

- **HR** = near-bottom AUV multibeam (typically 1–2 m grids, flown ~50–80 m off the seafloor).
- **LR** = hull-mounted ship multibeam (typically ~35–50 m grids in deep water) over the *same* footprint.

Because these are two independent measurements of the same seafloor, an (ship-LR → AUV-HR) pair is a **real** super-resolution example, not a synthetic one. This is the gold-standard test of the actual deployment pathway: feed the model the real coarse ship grid, compare its output against the real AUV truth. Our synthetic-degradation training validates only the synthetic path; these pairs validate the real one.

**Deliverable of this repo:** every co-located pair downloaded, harmonized to a common grid, and catalogued in a manifest that our downstream tiling pipeline can consume — kept entirely separate from the GEBCO/GMRT data and code.

### Critical correctness constraint
The whole value of these pairs is that the LR side is a **real ship measurement**. **Do NOT fabricate the LR by downsampling the AUV HR.** Resampling is permitted only for CRS alignment and to place HR and LR on a common grid/footprint — never to manufacture a coarse input from the fine one. If a step would require synthesizing LR from HR, stop and flag it.

---

## 2. Scope and non-goals

**In scope:** acquiring the datasets listed in §4 via each repository's API; reprojecting, clipping, and co-registering each pair; writing a provenance-rich manifest; producing a QA report.

**Out of scope (do not do here):**
- No GEBCO or GMRT data (that lives in the other repo).
- No model code, no degradation, no SR, no training.
- No open-ended dataset discovery beyond the bounded ship-companion lookups in §4 Tier 2.

---

## 3. Access methods (use APIs — do not HTML-scrape)

These are FAIR scientific repositories with stable DOIs and documented services. Scraping HTML would be fragile and unnecessary.

- **PANGAEA** — install `pangaeapy` (`pip install pangaeapy`). Use it to resolve a DOI to its metadata and file list. Note: `pangaeapy` is optimized for *tabular* datasets; the bathymetry products here are attached GeoTIFF/netCDF rasters, so use `pangaeapy` for metadata and fetch the raster files from the dataset's file URLs. All PANGAEA data here are CC-BY — preserve attribution.
- **USGS data releases** — ScienceBase REST API (`sciencebasepy`).
- **MGDS / marine-geo.org** — MGDS web services for MBARI / Sentry grids.
- **(Reference only)** GMRT GridServer and GEBCO download/OPeNDAP are *not* used in this repo.

Environment: this runs on Sherlock with real network egress and scratch storage. Throttle requests politely; PANGAEA and ScienceBase will rate-limit. Make every download resumable, checksummed, and idempotent on re-run.

---

## 4. Target datasets

### Tier 1 — verified co-located pairs (both grids public, same footprint)

These two are confirmed on both sides. Build and validate the pipeline against them before anything else.

**(1a) DISCOL Experimental Area, Peru Basin — RV SONNE cruise SO242/1 (2015), ~4,100–4,200 m, abyssal plain (with an adjacent topographic high).** This is the primary anchor.

| Component | DOI | Notes |
|---|---|---|
| AUV HR (2 m GeoTIFF) | `10.1594/PANGAEA.905580` | AUV ABYSS (REMUS 6000, Reson 7125), merged 3 dives; already corrected against the ship EM122 |
| Ship LR (38 m GeoTIFF) | `10.1594/PANGAEA.905579` | RV SONNE Kongsberg EM122, same DEA; used as the geo-reference layer |
| Ship raw EM122 | `10.1594/PANGAEA.859528` | Raw, if needed |
| Parent collection | `10.1594/PANGAEA.905616` | Acoustic + optical data series for the area |

Native LR→HR ratio ≈ 19× linear (38 m → 2 m). CRS: UTM 16S.

**(1b) Cal DIG I / Morro Bay, offshore south-central California (2016–2019), ~100–1,600 m, continental margin / shelf-slope.** USGS data releases (ScienceBase). The HR side is the Morro Bay AUV data already held locally.

| Component | DOI | Notes |
|---|---|---|
| AUV HR (~1–2 m grid) | `10.5066/P97QM7NF` | MBARI-donated AUV, Reson 7125 400 kHz, ~0.87 m footprint, 0.15 m vertical; multiple dive patches (2018–2019). **Already held locally — reuse, do not re-download if present.** |
| Ship LR (10 m GeoTIFF) | `10.5066/P9QQZ27U` | Cal DIG I multibeam mosaic, Simrad EM 700 series hull-mounted, NOAA ships Rainier/Fairweather (+ R/V Sally Ride gap-fill). UTM Zone 10, NAD83 |

Native LR→HR ratio ≈ 10× linear (10 m → ~1 m). **Co-registration caveat (must handle):** the Cal DIG AUV navigation is only partially processed (relative accuracy < 2 m, absolute ~30 m from USBL) and was *not* adjusted to the surface-ship multibeam. Co-register the AUV to the ship grid (offset correction over the overlap) before treating the pair as valid — the same correction DISCOL's AUV already had applied. Flag the residual misregistration in the manifest `notes`.

### Tier 2 — AUV grid verified; locate and confirm the ship companion before download

All AUV ABYSS, 2 m grids. For each, query PANGAEA for the **same cruise ID's** processed/gridded EM122 dataset (PANGAEA titles encode `device + platform + cruise`, e.g. *"Multibeam bathymetry processed data (Kongsberg EM122 ...) of RV ... during cruise <ID>"*). Surface the candidate ship DOI + its footprint for human confirmation. **Do not download the ship side or assert a pairing until a human confirms the DOI.**

| Site | Cruise / vessel | AUV DOI (verified) | Depth / terrain | Ship companion |
|---|---|---|---|---|
| Clarion-Clipperton Zone | SO268/1, RV SONNE (2019) | `10.1594/PANGAEA.915765` | ~4,100 m, abyssal nodule plain | locate EM122 for SO268/1 |
| TAG Hydrothermal Field, MAR | M127, RV METEOR (2016) | `10.1594/PANGAEA.899415` | ~3,600 m, slow-spreading vent field | locate EM122 for M127 |
| Kolumbo Seamount, Santorini | POS510, RV POSEIDON (2017) | `10.1594/PANGAEA.958275` | ~120–500 m, back-arc caldera | locate multibeam for POS510 |
| East Sicily / Mt Etna margin | AL532, RV ALKOR (2020) | `10.1594/PANGAEA.941403` | ~1,250–1,790 m, continental margin | locate multibeam for AL532 |

### Tier 3 — US-fleet sites (MGDS / mixed), lower priority; treat as expansion

| Site | HR | LR | Notes |
|---|---|---|---|
| Axial Seamount, Juan de Fuca Ridge | MBARI mapping AUV, 1 m (MGDS) | ship multibeam ~25 m (MGDS) | Repeat pre/post-eruption surveys; high-relief volcanic counterpart to DISCOL. Locate both via MGDS by cruise. |
| Henry Seamount, Canary Islands | MARUM AUV SEAL (locate companion) | gridded EM122 `10.1594/PANGAEA.892813` | Ship grid verified; AUV SEAL grid to be located. |

**Terrain diversity is intentional:** abyssal plain / nodule fields (DISCOL, CCZ) deliberately balance the high-relief vent/seamount/volcanic sites, so the validation set isn't dominated by one geomorphic province.

---

## 5. Output data structure

Split across two locations. **Bulk rasters live on scratch; only small text artifacts live in the repo.** The data root is a config value (`data_root`, §7) that MUST resolve to a Sherlock scratch path — e.g. `$SCRATCH/auv_ship_colocated_bathy` (personal scratch) or `$GROUP_SCRATCH/auv_ship_colocated_bathy` (group scratch). Confirm which to use before M1.

**Repo (small, version-controlled — may live in home or wherever cloned):**
```
auv_ship_colocated_bathy/
├── config/
│   └── harmonization.yaml        # all decisions live here (see §7), incl. data_root
├── src/                          # acquisition + harmonization code
├── manifest/
│   └── pairs.parquet             # small; the catalog
├── reports/
│   └── acquisition_report_<date>.md
└── logs/
```

**Scratch (`$DATA_ROOT` — all bulk binaries; never home):**
```
$DATA_ROOT/
├── raw/                          # untouched downloads, one dir per pair, immutable
│   └── <pair_id>/
│       ├── hr_<doi>.tif
│       ├── lr_<doi>.tif
│       └── metadata.json         # citation, license, native CRS, source URLs, checksums
└── harmonized/                   # common CRS + grid, clipped to shared footprint
    └── <pair_id>/
        ├── hr.tif
        ├── lr.tif
        └── footprint.geojson     # the HR∩LR overlap polygon used for clipping
```

Manifest path columns (`*_path_*`) store absolute scratch paths. Note Sherlock scratch is subject to a purge/inactivity policy and is not permanent archival — flag this when deciding raw retention (§7 `storage`); long-term archival belongs on group/Oak storage, not in scope here.


### Manifest schema (`pairs.parquet`)

`pair_id`, `site_name`, `region`, `cruise_id`, `vessel`, `hr_platform`, `hr_sonar`, `hr_doi`, `hr_native_res_m`, `lr_platform`, `lr_sonar`, `lr_doi`, `lr_native_res_m`, `res_ratio`, `depth_min_m`, `depth_max_m`, `terrain_class`, `native_crs_hr`, `native_crs_lr`, `target_crs`, `vertical_datum`, `footprint_wkt`, `license`, `acquisition_date`, `verification_status` (`verified_pair` | `ship_companion_pending`), `raw_path_hr`, `raw_path_lr`, `harmonized_path_hr`, `harmonized_path_lr`, `checksum_hr`, `checksum_lr`, `notes`.

`terrain_class` controlled vocab: `abyssal_plain`, `nodule_field`, `seamount`, `hydrothermal_vent`, `volcanic`, `continental_margin`.

---

## 6. Harmonization steps (per pair)

1. Download HR and LR via the appropriate API; write to `$DATA_ROOT/raw/<pair_id>/` on scratch; record source URLs, license, citation, and checksums in `metadata.json`. (For Cal DIG HR, reuse the locally-held copy if present rather than re-downloading.)
2. Read native CRS, resolution, units, vertical reference, and nodata value for each grid. If any is missing or ambiguous, **stop and flag** — do not assume.
3. Reproject both to `target_crs` (see §7) using the configured continuous-data resampling kernel. Never use nearest-neighbour for elevation.
4. Compute the HR∩LR overlap polygon; clip both grids to it; write `footprint.geojson`.
5. Normalize vertical reference and sign convention (elevation in metres, negative down) per config; record `vertical_datum`.
6. Write harmonized rasters and append a manifest row. Do not delete `$DATA_ROOT/raw/` automatically (see §7 storage decision).

Use `rasterio`/`rioxarray`, `xarray`, `pyproj`, `geopandas`, and GDAL. Suggested env (pin in `requirements.txt`): `pangaeapy`, `sciencebasepy`, `rasterio`, `rioxarray`, `xarray`, `geopandas`, `pyproj`, `shapely`, `pandas`, `pyarrow`.

---

## 7. Human-decision parameters — read from `config/harmonization.yaml`, do NOT invent

If the config is absent or a field is unset, **stop and ask** rather than choosing a default. Proposed defaults are suggestions for the human to confirm, not licence to proceed.

- `data_root`: the Sherlock scratch path for all bulk data (e.g. `$SCRATCH/auv_ship_colocated_bathy` or `$GROUP_SCRATCH/...`). **Required.** The agent must verify this resolves to a scratch filesystem (not home) and is writable before any download; if it points at or under home, **stop**.
- `target_crs`: proposed = per-pair local UTM (metric, low distortion). Confirm whether a single project-wide CRS is preferred instead.
- `target_grid`: proposed = keep HR at native GSD and LR at native GSD; reproject/clip only. **Confirm that LR is NOT to be downsampled from HR** (see §1 correctness constraint).
- `resample_kernel`: proposed = bilinear for reprojection of continuous bathymetry; area-weighted averaging if any genuine downsampling of real data is ever required. Confirm.
- `vertical_datum_handling`: proposed = harmonize to MSL elevation, negative down. Confirm per-dataset datum from metadata; flag mismatches rather than silently shifting. (Note Cal DIG ship grid is NAD83 / UTM 10; DISCOL is UTM 16S — datums and zones differ across pairs.)
- `coregistration`: proposed = estimate and apply a rigid horizontal+vertical offset of AUV to ship grid over the overlap (required for Cal DIG; verify residual for all pairs). Confirm method and acceptance threshold.
- `nodata_policy`: explicit fill value + mask; confirm.
- `pair_qa`: max acceptable horizontal misregistration and the overlap-area threshold below which a pair is rejected. Confirm thresholds.
- `storage`: whether `$DATA_ROOT/raw/` is retained or deleted after harmonization. Default = retain pending confirmation. Note scratch purge policy — neither raw nor harmonized data here is permanent archival.

---

## 8. Hard rules

- **All bulk data (raw + harmonized rasters) go to `$DATA_ROOT` on Sherlock scratch — never the home directory.** Home is ~15 GB; writing rasters there will fill the quota and break the run. Verify `data_root` resolves to scratch before downloading; if it resolves to or under home, stop and ask.
- Use only the DOIs in §4. **Never fabricate or guess a DOI.** For Tier 2/3 companions, present candidates for human confirmation before downloading.
- **Never synthesize the LR from the HR.** LR must be the real ship grid.
- Use repository APIs, not HTML scraping.
- Do not make vertical-datum, CRS, or resampling decisions unilaterally — read them from config; if unset, stop and ask.
- Preserve attribution: write the full citation and license into each pair's `metadata.json` (PANGAEA = CC-BY).
- Throttle requests; checksum every file; make runs resumable and idempotent.
- Log every action; write a per-run report to `reports/`.
- Escalate anything unexpected (datum mismatch, footprint disagreement, missing metadata, rate-limit failures) rather than absorbing it silently.

---

## 9. Milestones

- **M0 — Scaffold.** Create the repo tree and `src/`, `requirements.txt`, and a `harmonization.yaml` template with all §7 fields unset and clearly commented. Set up `$DATA_ROOT` on scratch and **verify it resolves to a scratch filesystem (not home) and is writable**. Do not download yet.
- **M1 — Vertical slice on the verified pairs.** First DISCOL (`905580` HR / `905579` LR) — it is already co-registered, so it isolates the reproject/clip/manifest path. Then Cal DIG (`P97QM7NF` HR / `P9QQZ27U` LR) — this additionally exercises the AUV→ship co-registration step (§7 `coregistration`). For each, write the harmonized pair + manifest row + metadata sidecars to scratch, and a short QA note (overlap area, resolution ratio, residual misregistration, difference statistics over the overlap). This proves the full pipeline, including co-registration, before scaling. **Pause for human review here.**
- **M2 — Tier 2.** For each Tier-2 AUV DOI, download HR; locate the ship companion by cruise ID; present candidate DOIs for confirmation; harmonize confirmed pairs.
- **M3 — Tier 3.** Add the MGDS/US sites (Axial, Henry) once Tiers 1–2 are complete.
- **M4 — Finalize.** Complete the manifest, write the consolidated acquisition + QA report, verify all provenance and licenses are recorded.

Start at M0 and M1. Stop and report after M1.
