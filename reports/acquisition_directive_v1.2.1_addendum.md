# Acquisition Directive v1.2.1 — Addendum: Cal DIG mapping approvals, 2 m HR standardization, master QC figure

**Amends** v1.2 (user-provided Cal DIG HR). Consumes `user_hr_approved_mapping.yaml`. Cal DIG HR only; DISCOL and Cal DIG LR untouched; Tier 2 stays blocked. Extend `reharmonize-user-hr` to implement the behaviors below.

---

## 1. Mapping approvals (human-confirmed)

Source of truth is `user_hr_approved_mapping.yaml`. Summary of the four previously-unresolved sub-pairs:

- `20180428m1_Cable` → **accept** `CableSurvey_MAUV` (the 0.78 IoU was a false negative on a long thin strip; area + name match are strong).
- `20180427m2_PockmarkSouthBasinFlank` → **mosaic** `PockmarkSouth_MAUV` + `BasinFlank_MAUV` (the user export split this one CMGDS survey into its two named features).
- `20180426m1_PockmarkNorthDet` → **drop** (a detail subset wholly inside `PockmarkNorth`; keeping both leaks near-identical ground across a split). Do not fall back to CMGDS HR.
- `20190316m1_BankTop` → **use** the user-added `banktop_2m.tif`.

Also: `MorroBay_all_2020_interp_32m` was added by mistake and removed by the user — confirm it is gone and exclude it.

New BankTop file requires the full v1.2 §B treatment before use: inventory (gdalinfo), hillshade + FFT, `provenance.json` sidecar, and human artifact-free attestation. Confirm its exact filename.

---

## 2. HR standardization to 2 m (applies to every Cal DIG HR)

Target HR GSD = **2 m**, for a uniform 5× ratio against the 10 m LR. Combine the datum reprojection and the GSD change into a **single warp** to avoid compounding interpolation:

- Input finer than 2 m (the 1 m files): reproject `EPSG:32610 → EPSG:26910` at `-tr 2 2` with **`-r average`** (area-weighted downsample — correct for 2× coarsening, and avoids the grid-aligned aliasing the user flagged).
- Input already 2 m: reproject at `-tr 2 2` with **`-r cubic`** (reprojection only).
- **Never `-r near`.** Nearest-neighbor is what re-introduces the criss-cross.

Record per HR: native GSD, kernel used, and that output GSD = 2 m, in the manifest/metadata. This 2 m product is still real HR; it is unrelated to the v1.0 §1 LR-synthesis prohibition (the LR remains the real 10 m ship grid).

---

## 3. Mosaic for split exports

For any `hr` list with >1 file (currently only PockmarkSouthBasinFlank): mosaic the inputs **before** reproject/clip. After mosaicking, confirm the combined footprint reaches IoU ≥ 0.80 against the CMGDS patch and report contiguity. If the two pieces are disjoint with a large interior gap, report it and propose splitting into two pairs instead of one — do not silently emit a holed raster.

---

## 4. New pairs (LuciaChica 2007 and 2009)

The 2007/2008/2009 vintages are resurveys of a similar area with minimal mutual overlap; each contributes new ground, so they are **kept on their merits** — overlap between vintages is **not** a rejection criterion. The **only** rejection test is LR coverage, exactly as for any other pair.

These two have no CMGDS ancestor; define `pair_id`, derive the footprint from HR∩LR, and harmonize as normal. Both lie near the ~1,100 m LR coverage hole that caused the M1.5 rejections (2009 reaches −1118 m), so do not assume LR coverage: compute HR∩LR explicitly, clip to the LR-covered portion, and if the overlap is below `pair_qa.min_overlap_area_km2`, **reject** the pair (the standard rule — no appropriate LR). Report the overlap area for each. A reject here means "no LR," not "redundant data."

`LuciaChica_2008` remains the HR for the existing `201804_LuciaChica2m` pair.

---

## 5. LuciaChica overlap report (informational only — not a gate)

For your future train/test split planning, compute pairwise footprint IoU across the four LuciaChica HR footprints (2007, 2008, 2009, 2019-970 m) and include the matrix in the report. This is **purely informational**: it never rejects a pair and never blocks the run. It only tells you which patches, if any, share ground so you can keep them on the same side of a split later. No flagging, no pause on this.

---

## 6. Re-harmonization (per pair, after the above)

Reproject+resample per §2, clip to HR∩LR, **re-solve co-registration from scratch** (no CMGDS offsets), regenerate v1.1 §A metrics + overlay PNG. Clearance remains via human review of the new overlays (v1.1 thresholds still uncalibrated). Update the manifest with `hr_source_type=user_provided`, `hr_local_path`, `hr_superseded_doi`, `hr_superseded_reason`, native GSD, and resample kernel.

---

## 7. Figures for human review (deliverables)

Two figures, both for visual approval:

**(a) Artifact-inspection contact sheet** — replaces the dropped metric (§8). One tile per user-provided HR file, showing its hillshade and its FFT-of-a-flat-window side by side, labeled with the filename. This is the surface you scan to attest artifact-free (the criss-cross shows as bright spikes on the kx=0 / ky=0 FFT lines and as a diamond/grid texture in the hillshade). Output `reports/user_hr_artifact_contact_sheet.png` (paginate if needed).

**(b) Master LR-vs-HR figure** — for pair approval:
- One row per final Cal DIG pair; columns: **LR hillshade | HR hillshade**, both clipped to the shared HR∩LR footprint, same extent, illumination (az/alt), vertical exaggeration, and a shared elevation ramp per row.
- Annotate each row: `pair_id`, depth range, LR 10 m / HR 2 m / ratio 5×, co-registration residual (dx,dy,dz + MAD), terrain class, `coreg_status`.
- Include all retained pairs (the 13 + Cable + PockmarkSouthBasinFlank + BankTop + LuciaChica 2007/2009 if they survive §4). Order by terrain class.
- Output `reports/cal_dig_master_lr_vs_hr.pdf` (~6 rows/page) **and** a single contact-sheet PNG. Keep the per-pair overlay PNGs from §6.

---

## 8. Drop the `axis_excess` metric

Remove `axis_excess` from the §B inventory and from the codebase — it is non-discriminating as implemented (every file returns 10⁴–10⁶, including expected-clean files, and three strip surveys returned `nan`). Artifact-free status is determined **visually** from the §7(a) contact sheet and attested by the human in each file's `provenance.json`. Keep generating the hillshade and FFT images (they feed the contact sheet); just stop computing and stop reporting the numeric metric, and never gate on it.

---

## 9. Gate

- **M1.7 — apply approved mapping + 2 m standardization + figures.** Deliverables: BankTop inventory/attestation; re-harmonized Cal DIG at 2 m with fresh co-registration + new overlays; new-pair LR-overlap verdicts (§4); the LuciaChica overlap matrix (§5, informational); updated manifest + passing branched audit; the artifact contact sheet (§7a) and the master LR-vs-HR figure (§7b). **Pause for human approval of the figures.**
- Tier 2 remains blocked until every Cal DIG pair is `auto_pass` or human-cleared and the master figure is approved.
