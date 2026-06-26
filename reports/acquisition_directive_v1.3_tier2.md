# Acquisition Directive v1.3 — Tier 2: GEOMAR co-located AUV / ship pairs

**Extends** v1.0 §4 Tier 2. Tier 1 (DISCOL + the 18-pair Cal DIG set on user-provided HR) is validated and frozen — do not modify it. This directive adds four GEOMAR PANGAEA cruises and **reuses the Tier 1 harmonization, co-registration QA, manifest, and audit machinery unchanged**. The one genuinely new task is locating and confirming each **ship companion** by cruise ID before download.

DISCOL and all Cal DIG rows stay untouched. Append Tier 2 rows to the same `pairs.parquet`.

---

## 1. Datasets

All HR are AUV ABYSS (REMUS 6000, Reson 7125), native **2 m** grids, CC-BY, on PANGAEA. The AUV DOI is verified; the ship companion is **to be located** (§2). These deliberately broaden province coverage beyond Tier 1's Peru Basin abyssal + California margin.

| Site | Cruise / vessel | AUV DOI (verified) | Depth / terrain |
|---|---|---|---|
| Clarion-Clipperton Zone | SO268/1, RV SONNE (2019) | `10.1594/PANGAEA.915765` | ~4,100 m, abyssal nodule plain |
| TAG Hydrothermal Field, MAR | M127, RV METEOR (2016) | `10.1594/PANGAEA.899415` | ~3,600 m, slow-spreading vent field |
| Kolumbo Seamount, Santorini | POS510, RV POSEIDON (2017) | `10.1594/PANGAEA.958275` | ~120–500 m, back-arc caldera (volcanic) |
| East Sicily / Mt Etna margin | AL532, RV ALKOR (2020) | `10.1594/PANGAEA.941403` | ~1,250–1,790 m, continental margin |

---

## 2. Ship-companion lookup (the new work)

For each cruise, locate the hull-mounted multibeam companion on PANGAEA, then **stop for human confirmation before downloading it**.

- Query PANGAEA by the exact cruise ID for the processed/gridded hull multibeam. PANGAEA titles encode `device + platform + cruise` (e.g. *"Multibeam bathymetry processed/gridded (Kongsberg EM122 …) of RV … during cruise <ID>"*). Prefer a **gridded/processed** product over raw.
- Present candidate ship dataset(s) per cruise with: DOI, sonar, native GSD, footprint, and **overlap fraction with the AUV footprint**. Do not assert a pairing or download until a human approves the DOI.
- **Never fabricate or guess a DOI.** If no companion is found, flag the pair and hold it — do not substitute a global grid (no GEBCO/GMRT here).
- If a located ship grid does not overlap the AUV footprint adequately, **reject the pair** ("no LR coverage") — the same rule validated on Tier 1, not a special case.

Vessel-by-vessel expectation (so a missing companion isn't a surprise):
- **SONNE (CCZ) and METEOR (TAG)** — deep-water EM122, large well-archived programs; companion very likely present.
- **POSEIDON (Kolumbo) and ALKOR (Sicily)** — smaller vessels; the companion is less certain and, in Kolumbo's shallow caldera, may be a higher-resolution shallow-water multibeam (EM710-class) rather than EM122. Confirm what actually exists rather than assuming EM122.

---

## 3. Resolution, ratio, projection

- **HR is already native 2 m** — no downsampling. Do **not** standardize GSD across Tier 2 (that was a Cal-DIG-specific choice); keep each LR at its **native** resolution and record the per-pair ratio.
- Expect ratios to vary widely by depth: ~15–25× for the deep CCZ/TAG pairs (ship ~35–50 m), and potentially much smaller (≈5–10×) for shallow Kolumbo. This is fine and expected; just record it.
- Reproject to **per-pair local UTM** (zones differ greatly: Pacific CCZ, mid-Atlantic TAG, UTM 35N Kolumbo, UTM 33N Sicily). Single warp, never nearest; **skip reprojection when native CRS already equals the target** (the rule from the artifact fix).

---

## 4. Reuse the validated Tier 1 path (do not re-invent)

Apply, unchanged:
- **Co-registration + QA:** solve fresh per pair, compute the v1.1 §A metrics (horiz/vert offset, PSR, eig_ratio, peak_agrees, MAD), write the overlay PNG. Clearance is via human review of the overlay; the empirical thresholds remain uncalibrated, so human-clear as on Tier 1. Note GEOMAR grids are often already ship-referenced, so offsets may be small — verify a near-zero solve actually ran (the PockmarkNorth check) rather than assuming a no-op.
- **Provenance audit:** unlike the Cal DIG user-provided HR, **both sides here are PANGAEA-DOI'd**, so the standard DOI-match audit applies to HR *and* LR (no `user_provided` branch for Tier 2).
- **Completeness audit (v1.2.2 §2):** accounting identity (`rows == processed + rejected`, with reconciliation), no-stale-HR, no-error-states — run after each cruise.
- **Master figure:** extend the LR-vs-HR figure (or emit a Tier 2 sheet) over the new pairs, same format.

---

## 5. Manifest fields (per Tier 2 pair)

Populate the existing schema: `pair_id`, `site_name`, `region`, `cruise_id`, `vessel`, `hr_platform` (AUV ABYSS), `hr_sonar` (Reson 7125), `hr_doi`, `hr_native_res_m` (2.0), `lr_platform`, `lr_sonar`, `lr_doi`, `lr_native_res_m`, `res_ratio`, `overlap_km2`, `depth_min_m`, `depth_max_m`, `terrain_class` (`nodule_field` / `hydrothermal_vent` / `volcanic` / `continental_margin`), `native_crs_hr`, `native_crs_lr`, `target_crs`, `license` (CC-BY-4.0), `coreg_status`, `qc_artifact_path`. `hr_source_type = pangaea_doi`.

---

## 6. Order — vertical slice first

Do **one cruise end-to-end before the rest**: start with **CCZ / SO268-1** (RV SONNE — the deep EM122 companion is the most likely to be cleanly archived, mirroring the DISCOL setup you already validated). Locate + confirm its ship companion, harmonize, QA, overlay, audit, figure — then **pause for human review**. Only after that proceed to TAG, Kolumbo, Sicily.

---

## 7. Gate

- **Per cruise, two human pauses:** (a) confirm the ship-companion DOI **before download** (§2); (b) clear the per-pair overlays + approve the figure (§4).
- Each cruise must pass the completeness and provenance audits before its rows are considered done.
- A located-but-non-overlapping or missing companion → reject/hold the pair with the reason recorded; never backfill from a global grid.
- **M2 milestone:** CCZ vertical slice delivered and reviewed, then the remaining three cruises. Report after the CCZ slice.
