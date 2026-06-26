# Manifest completeness gate (M1 + M2) — report

**Date:** 2026-06-26 · **Directive:** `reports/directive_phase2_manifest_completeness_gate_v1.md`
**Status:** ✅ M1 complete (16/16 on every canonical field the 21 carry, with one documented exception). M2 reclasses flagged, **not** committed. ⛔ **Canonical append still HELD** — unblocks on Steve's M2 confirmation. `pairs.parquet`/OAK untouched; backup retained.

**Code:** `src/discovery/stage_m1_manifest_complete.py` · **Evidence:** `reports/discovery/stage_m1_completeness_diff.json`, `stage_m1_lr_mbinfo.json` · **Staged:** `reports/discovery/staged_manifest_append.{csv,parquet}` (37 rows).

The point taken from the critique: the prior "append-ready" rows were blank on independence, ratio, QA, checksums. This pass certifies the **artifact** with a per-field completeness diff, not a prose "done".

---

## M1 — completeness diff (the evidence)

Every canonical field that the 21 carry at 21/21 is now populated 16/16 on the new rows, **except** two genuinely-undefined coregistration metrics (below). Fields blank in the canonical 21 themselves (`hr_local_path`, `hr_superseded_*` = 0/21) are left blank — that *is* parity.

| field group | new 16 | how sourced |
|---|---|---|
| `checksum_hr`, `checksum_lr` | **16/16** | sha256 of the harmonized rasters (integrity anchor) |
| `footprint_wkt` | **16/16** | **path to footprint.geojson** (the HR∩LR valid polygon) — matches the canonical-21 convention (that column stores the geojson path, not inline WKT). Inlining raw pixel-traced WKT had bloated the CSV to 4.3 MB (NA080/TN299 ≈ 2 M vertices); fixed → 57 KB. |
| `lr_platform`, `lr_sonar` | **16/16** | `mbinfo` on the NCEI raw-LR header (independence evidence) |
| `hr_sonar`, `hr_platform`, `hr_doi` | 16/16 | MGDS catalog |
| `hr_native_res_m` | 16/16 | **sounding-density** `measured_finest_cell_m` (not grid posting) |
| `lr_native_res_m`, `res_ratio` | 16/16 | corpus / ratio = lr/hr |
| `native_crs_hr`, `native_crs_lr`, `target_crs` | 16/16 | catalog CRS / NCEI lon-lat / per-pair UTM |
| `raw_path_hr/lr`, `harmonized_path_hr/lr` | 16/16 | filesystem |
| `horiz_offset_m`, `vert_offset_m`, `coreg_status`, `qc_artifact_path` | 16/16 | F.5 masked re-coreg + R3 figure |
| `acquisition_date`, `region`, `site_name`, `cruise_id`, `vessel`, `license`, `vertical_datum`, `terrain_class`, `depth_*` | 16/16 | catalog / mbinfo / corpus |
| `coreg_peak_psr` | **13/16** | undefined for 3 no-peak pairs (documented, below) |
| `coreg_peak_eig_ratio` | **15/16** | undefined for 1 degenerate-peak pair (documented) |

**The two sub-16/16 fields are the directive's anticipated exception, not a gap.** `KN210-05×22436`, `KN204-01×31675`, `KIWI10RR×24499` have **no interior NCC peak**, so PSR is genuinely undefined; `KN204-01` additionally has an undefined eig ratio. Per the directive ("the 3 no-PSR pairs → record the QGIS-approval basis, not blank"), each carries in `coreg_status`:
> `QGIS_R3_approved; PSR=undefined (no interior peak); offset=<X> m`
Fabricating a PSR to hit 16/16 would be the wrong move; the QGIS sign-off is the recorded arbiter.

### Independence evidence now on each row (sample)
| pair | LR vessel / sonar (mbinfo) | HR AUV sonar | res_ratio | acq |
|---|---|---|---:|---|
| KIWI10RR×24499 | R/V (KIWI exped.) / **SeaBeam 2100 / 1998** | Reson SeaBat 7125 (Sentry) | 106 | 1998-04-12 |
| EW9801×31425 | R/V Maurice Ewing / **Atlas Hydrosweep DS** | Reson 7125 (Sentry) | 81 | 2013-03-16 |
| FK181031×24367 | R/V Falkor / **Kongsberg EM302** | MBARI AUV | 22.6 | 2018-11-22 |
| TN159×21981 | R/V Thompson / **Simrad EM (.all) / 2003** | Reson (Atlantis AT15-36) | 320 | 2003-07-29 |
| AT37-13×31199 | R/V Atlantis / Kongsberg EM (.all) | Reson SeaBat 7150 | 47 | 2017-05-20 |

Each row now substantiates anti-circularity on its own: a real, dated, single-cruise ship multibeam (distinct sonar) vs the AUV — exactly the bar the directive set (the KIWI10RR SeaBeam-2100/1998 example).

---

## M2 — terrain reclassifications: **proposed, awaiting Steve (not committed)**

`terrain_class` left at the original value; the 7 proposals live in `terrain_class_proposed` with a `terrain_proposed_basis` citing the HR AUV region + DOI:

| pair | original | proposed | basis |
|---|---|---|---|
| EW9801×31425 | hydrothermal_vent | volcanic | Loihi submarine volcano (HR TN293) |
| TN399×30373 | continental_margin | **volcanic** | EPR 9°N mid-ocean-ridge axis |
| FK181031×24367 | continental_margin | **volcanic** | Alarcón Rise spreading center |
| RR1506×29779 | continental_margin | **seamount** | Kermadec Arc |
| TN268×30466 | hydrothermal_vent | volcanic | Axial Seamount caldera |
| TN299×27339 | continental_margin | **volcanic** | Gorda Ridge |
| KN210-05×22436 | continental_margin | hydrothermal_vent | Mid-Atlantic Ridge |

**Implication (surfaced):** four pairs labeled `continental_margin` are actually MOR/volcanic/seamount. The corpus is **more morphologically diverse than the prior "74% continental margin"** characterization, which was partly a labeling artifact of naming pairs by the LR ship cruise. This improves the known diversity gap and changes which pairs count as channelized/structured for any future D8-loss scoping.

---

## M3 — leakage note for C1 re-harvest (forward, non-blocking)
Recorded: when the Amundsen/Axial floats re-harvest, any that co-locate an existing manifest pair (esp. **Axial float vs `TN268×30466`**, and the other Axial render-sites) must inherit the **same `leakage_unit` as the existing pair over that seafloor** before appending. Flag at re-harvest.

---

## Append unblocks when
- M1 diff clean ✅ (16/16 on every populated canonical field; the 3+1 undefined-PSR/eig cells documented via `coreg_status` per the directive's own carve-out).
- **Steve confirms the M2 terrain reclasses** (per-pair). ⛔ pending.

On confirmation I will: apply confirmed terrain reclasses, write `pairs.parquet` (append-only, the 21 preserved verbatim), sync OAK, and byte/dedup/checksum-verify. The Amundsen/Axial re-harvest pairs append later as separate candidates (independence + reader proof + leakage assignment each).

## Deliverables
1. 16 rows at canonical parity — `staged_manifest_append.csv` (37 total). ✅
2. Completeness diff `stage_m1_completeness_diff.json` (per-field 21/21 vs 16/16). ✅
3. LR independence evidence `stage_m1_lr_mbinfo.json` (per-cruise mbinfo). ✅
4. M2 proposals in `terrain_class_proposed` (+ basis), not committed. ✅
5. This report. Canonical `pairs.parquet` untouched; `pairs.parquet.bak_preappend` retained.

**Skepticism note:** the evidence here is the completeness diff and the per-cruise `mbinfo` records (e.g. SeaBeam-2100/1998 for KIWI10RR), not a "complete" assertion. The one field group that isn't 16/16 is called out explicitly as a physically-undefined metric with the QGIS arbiter recorded in its place — verified in the staged rows, not summarized.
