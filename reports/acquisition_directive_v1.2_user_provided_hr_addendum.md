# Acquisition Directive v1.2 — Addendum: User-provided Cal DIG HR (artifact remediation)

**Amends** Acquisition Directive v1.0 + v1.1. Changes the **HR source of record for Cal DIG only**. DISCOL is untouched. The Cal DIG **LR** (ship, `10.5066/P9QQZ27U`) is unchanged. Tier 2 remains blocked.

---

## Why

The CMGDS-distributed Cal DIG AUV GeoTIFFs (`10.5066/P97QM7NF`) carry a grid-aligned criss-cross artifact baked into the source — consistent with a nearest-neighbor geographic→UTM reprojection performed upstream during their production. This is **ingrained in the released files, not introduced by our pipeline**, and it would be learned by a super-resolution model as false high-frequency texture and would contaminate the radial power-spectrum evaluation. Artifact-free local copies of the same AUV surveys are available and will replace the CMGDS HR.

Artifact-free local HR is provided at:
`$DATA_ROOT/user-provided-cal-dig/` (i.e. `/scratch/groups/hilley/auv_ship_colocated_bathy/user-provided-cal-dig/`)

File names are preserved as descriptive titles but **lack the date/dive prefix** of the existing sub-pair IDs and may differ slightly in wording.

---

## A. Source-of-record change

- Cal DIG HR := the matched user-provided file (§C). The CMGDS release `10.5066/P97QM7NF` is **demoted to `superseded_artifact`**, recorded in the manifest with the reason ("baked-in NN reprojection criss-cross"), and **retained on disk, not deleted** — it is needed for the footprint-matching check in §C and to keep the artifact finding reproducible.
- No change to LR, to DISCOL, or to the harmonization config except the reprojection fixes in §D.

---

## B. Inventory + artifact verification of the user-provided files

Before matching, for every file in `$DATA_ROOT/user-provided-cal-dig/`:

1. `gdalinfo`: record CRS, datum, cell size, extent, nodata. Confirm it is an HR AUV grid (~1–2 m) in a sane CRS.
2. **Confirm artifact-free** (this is the whole point of the swap — verify, don't assume): render a hillshade, and run a 2-D FFT on a flat sub-region. The grid-axis spectral spikes that characterize the CMGDS artifact must be **absent**. If a user-provided file shows the artifact, **flag it and do not use it** — stop and report rather than silently replacing one artifact source with another.
3. Compute and store a checksum and a `<file>.provenance.json` sidecar (source = user_provided, attested artifact-free = pending human confirmation).

Report the inventory (file, CRS, res, artifact-check result) before proceeding.

---

## C. Match user-provided files → existing sub-pairs

Fuzzy name match alone is insufficient and there are known title collisions (two `PockmarkNorth*` surveys; multiple `Bank*`, `Channel*`, `Gully*`, `LuciaChica*` patches). Use a two-stage match:

1. **Name normalization + fuzzy score.** Strip the date/dive prefix from each existing sub-pair ID (e.g. `20180426m1_PockmarkNorthDet` → `PockmarkNorthDet`), normalize case/punctuation/abbreviations on both sides, and compute a similarity score against each user-provided basename.
2. **Mandatory spatial confirmation.** For each candidate name match, require that the user-provided file's footprint overlaps the footprint of the **CMGDS HR patch it would replace** by a high fraction (propose ≥ 0.8 IoU; confirm threshold). The clean file should occupy nearly the same ground as the artifact-laden one. A name match that fails spatial overlap is **rejected as a mismatch**, not accepted.

Then:
- Present the full proposed mapping for **human confirmation before any harmonization**: `user_file → sub_pair_id`, with name-similarity score and footprint-IoU vs the old CMGDS HR. Do not auto-accept any pair below the IoU threshold or where two sub-pairs tie on name.
- Report **unmatched user files**, **sub-pairs with no user file**, and **ambiguous/colliding** matches separately. Do not guess on collisions.
- **Rejected sub-pairs stay rejected.** `20190318m1_LuciaChica1100m` and `20190319m1_8mPockmarkDetail` were rejected for true non-overlap with LR coverage (§D.4 of M1.5). A clean HR does not create LR coverage, so they remain `reject` even if a user-provided file matches their name.

---

## D. Re-harmonize Cal DIG from the new HR

These are different rasters; nothing from the CMGDS harmonization carries over.

1. **Reprojection (with the fixes the artifact investigation surfaced):**
   - Pass the configured `resample_kernel` through to the actual reprojection call — verify it is not silently defaulting to nearest. Use **cubic** (or bilinear) for the HR DEM; never nearest.
   - **Skip reprojection entirely when the file's native CRS already equals the target** (EPSG:26910). Resampling an already-correctly-projected DEM only degrades it.
2. Clip to the HR∩LR overlap; write `footprint.geojson`.
3. **Re-solve co-registration from scratch** against the LR — do **not** reuse the CMGDS dx/dy/dz. Apply the §A (v1.1) QA: recompute `horiz_offset_m`, `vert_offset_m`, PSR, eig_ratio, `peak_agrees`, MAD; regenerate the hillshade-overlay PNG per sub-pair.
4. **Clearance path:** the v1.1 empirical thresholds remain uncalibrated/inconclusive, so clearance is via human review of the **new** overlays (the prior visual sign-off was on the CMGDS patches and does not transfer). Compute the metrics for the record, but a sub-pair becomes usable on explicit human clearance of its new overlay, per the v1.1 hard rule.

Write harmonized rasters to `$DATA_ROOT/harmonized/cal_dig_morro_bay/<sub_pair>/` as before; the prior CMGDS-derived harmonized outputs are overwritten only after the new mapping is human-confirmed (keep them until then).

---

## E. Provenance + audit amendments

- **Manifest fields (Cal DIG rows):** set `hr_source_type = user_provided`, `hr_local_path = <path>`, `hr_superseded_doi = 10.5066/P97QM7NF`, `hr_superseded_reason = "baked-in NN reprojection artifact"`. Keep the LR DOI as-is.
- **Audit branch for user-provided HR.** The §E (v1.1) provenance audit asserts the HR DOI matches the manifest — that cannot apply to user-provided data. Add a branch: when `hr_source_type == user_provided`, assert instead that (a) the local path exists with a recorded checksum, (b) a `provenance.json` sidecar is present, and (c) a human has attested the file is artifact-free (§B). DOI-match remains required for the LR and for all DISCOL/PANGAEA rows.
- **Attribution unchanged in substance:** the underlying data remain the MBARI/USGS Cal DIG AUV surveys; "user_provided" denotes a cleaner local rendering of the same surveys, not a different dataset. Record this in the row notes.

---

## F. Scope guard + hard rules (additions)

- Only the Cal DIG HR changes. Do not touch DISCOL, the Cal DIG LR, or Tier 2.
- Never accept a name match without spatial confirmation (§C.2). Collisions and sub-threshold matches go to human review.
- If any user-provided file shows the criss-cross artifact (§B.2), stop and report — do not substitute it.
- Do not delete the CMGDS HR; mark it superseded and retain it.
- Do not reuse CMGDS co-registration offsets for the user-provided HR — re-solve.

---

## G. Gate

- **M1.6 — Cal DIG HR remediation.** Deliverables: user-file inventory + artifact-check results (§B); proposed `user_file → sub_pair` mapping with name score and footprint IoU (§C); after human confirmation, re-harmonized Cal DIG with fresh co-registration metrics and new overlay PNGs (§D); updated manifest + provenance audit pass (§E). **Pause for human review of the mapping before overwriting, and of the new overlays before clearance.**
- **Tier 2 stays blocked** until every Cal DIG sub-pair is re-harmonized from artifact-free HR and is `auto_pass` or explicitly human-cleared.
