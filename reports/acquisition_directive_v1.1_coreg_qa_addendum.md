# Acquisition Directive v1.1 — Addendum: Co-registration QA

**Amends** Acquisition Directive v1.0 (co-located AUV / ship-multibeam pairs). This addendum supersedes the co-registration and pair-QA portions of v1.0 §6, §7, and §8. Everything else in v1.0 stands.

**Apply this before starting Tier 2.** Tier 2 remains blocked until the re-run in §D is complete and reviewed.

---

## Why (what the M1 run revealed)

The M1 Cal DIG run passed its gate ("all MAD under 5.0 m: True"), but the gate validated the wrong quantity. MAD measures **post-alignment vertical agreement**; it does not establish that the AUV patch was shifted to the **correct horizontal position**. A rigid xyz-offset solver is **translation-ambiguous along the axis of a linear feature** — over a channel, gully, cable, or canyon it can slide the AUV strip along-axis and keep a low elevation residual the whole way. So a low MAD can co-exist with a wrong horizontal lock, which silently turns a "co-located pair" into two offset patches of seabed — injecting misregistration that the downstream model would misread as recoverable structure. That is a worse failure than the circularity this repo exists to avoid.

Evidence in the M1 output: the large applied horizontal offsets concentrate in linear/channelized surveys (Cable ~51 m, BankFlankIncipCh ~43 m, LuciaChica2m ~42 m, HeadlessCanyon ~38 m with the worst MAD at 2.87 m, 600mGully ~37 m, Transect601060m ~36 m), several exceeding the documented ~30 m USBL absolute bound. By contrast the two independent surveys of the same pockmark (`20180426m1_PockmarkNorthDet`, `20180427m3_PockmarkNorth`) solved to nearly identical offsets — strong evidence the method locks correctly when distinctive point-like morphology is present. The failure is therefore terrain-dependent and systematic, not random.

---

## A. Revised co-registration QA

Replace the binary MAD pass/fail with the following. Compute all metrics over the HR∩LR overlap, on a common grid at the LR resolution. **Alignment scoring is computed on morphology, not raw depth** — use the gradient-magnitude (or hillshade) of each surface, since alignment is driven by morphologic edges, not absolute level. (This QA resampling is for scoring only and is unrelated to the LR-synthesis prohibition in v1.0 §1; do not use it to produce any training LR.)

### A.1 Offset-magnitude flag
Compute horizontal offset magnitude `horiz_offset_m = sqrt(dx^2 + dy^2)` and vertical `vert_offset_m = |dz|`. Flag any sub-pair where `horiz_offset_m > usbl_bound_m` (config; see §B). Exceeding the USBL bound is never an auto-pass — it routes to `needs_review` (§A.4).

### A.2 Alignment-quality check (correlation peak)
Around the solved (dx, dy), evaluate the normalized cross-correlation (NCC) of the gradient fields over a search window of ±`usbl_bound_m`. From that NCC surface compute:

- **Peak agreement:** location of the NCC maximum should coincide with the solved offset (within ~1 LR cell). Disagreement → flag.
- **Peak sharpness (PSR):** peak-to-sidelobe ratio — peak height divided by the std of the NCC surface outside a small exclusion radius around the peak. A high PSR is a sharp, unambiguous lock; a low PSR is a flat or ridged surface, i.e. an ambiguous lock. Flag if `PSR < min_peak_sharpness` (config).
- **Peak anisotropy (the direct along-axis-slide diagnostic):** fit the local curvature at the peak (Hessian of the NCC surface) and take the ratio of its eigenvalues. A near-isotropic peak (ratio ≈ 1) is a true 2-D lock; a ridge (high ratio) means the solution is unconstrained along one direction — exactly the linear-feature failure. Flag if `eig_ratio > peak_anisotropy_max` (config), and record the ridge orientation in `notes`.

### A.3 Hillshade-overlay QC artifact (required, per sub-pair)
For every sub-pair — including auto-passes and including DISCOL — render and save a PNG: hillshade of the ship LR with the AUV HR hillshade overlaid semi-transparently at the solved offset, clipped to the overlap, with the overlap boundary drawn. Write to `$DATA_ROOT/harmonized/<pair_id>/qc/<sub_pair>_overlay.png` and record the path in the manifest (`qc_artifact_path`). This is the human-review surface; a sub-pair without its artifact is incomplete.

### A.4 Status taxonomy (replaces binary MAD gate)
Each sub-pair is assigned `coreg_status`:

| status | condition | usable downstream? |
|---|---|---|
| `auto_pass` | `horiz_offset_m ≤ usbl_bound_m` AND `PSR ≥ min_peak_sharpness` AND `eig_ratio ≤ peak_anisotropy_max` AND `MAD ≤ pair_qa.max_misregistration` AND peak agrees with solved offset | yes |
| `needs_review` | any single check above fails | **no — held for human QC** |
| `reject` | no footprint intersection, or human rejects after review | no |

Nothing enters the usable set on a low MAD alone. MAD is retained as one of several conditions, not the gate.

---

## B. Config additions (`config/harmonization.yaml`)

Add under `coregistration:`. Propose defaults below, but the two empirical thresholds must be **calibrated, not guessed** (see §D.2) — leave them unset and stop-and-ask if no calibrated value is present.

- `usbl_bound_m`: proposed `30` (documented Cal DIG AUV USBL absolute accuracy). Confirm.
- `min_peak_sharpness`: **unset — calibrate per §D.2.**
- `peak_anisotropy_max`: **unset — calibrate per §D.2.**
- `peak_metric`: proposed `ncc_gradient` (NCC of gradient-magnitude fields). Confirm.
- `qc.hillshade_overlay`: `true` (required; not optional).

---

## C. Manifest additions (`pairs.parquet`)

Add columns (per sub-pair): `horiz_offset_m`, `vert_offset_m`, `coreg_peak_psr`, `coreg_peak_eig_ratio`, `coreg_peak_agrees` (bool), `coreg_status` (`auto_pass`|`needs_review`|`reject`), `qc_artifact_path`. Retain existing `MAD`/offset fields.

---

## D. Re-run scope (no re-download)

### D.1 Re-evaluate the existing Tier 1 output
Re-run the QA in §A against the **already-harmonized** Cal DIG sub-pairs and DISCOL — do not re-download or re-solve unless a sub-pair is reclassified and a human asks for a re-solve. Produce the hillshade artifact for all of them, compute the new metrics, and write the new status per sub-pair.

### D.2 Calibrate the two empirical thresholds against the M1 labeled set
M1 handed us a near-labeled set: treat the duplicate pockmark surveys (`20180426m1_PockmarkNorthDet`, `20180427m3_PockmarkNorth`) and other distinct point/bank-top targets as known-good locks, and `20190315m1_HeadlessCanyon` (high offset + worst MAD, linear) as a known-suspect lock. Compute PSR and eig_ratio for all 17 sub-pairs, plot the distributions, and set `min_peak_sharpness` and `peak_anisotropy_max` to separate the known-good from the known-suspect cluster. Present the distributions and proposed thresholds for human confirmation before writing them to config.

### D.3 Priority flags for human QC
Surface these first (high offset AND/OR elevated MAD, linear morphology): `20190315m1_HeadlessCanyon` and `20190510m2_BankFlankIncipCh` (both high-offset and high-MAD), then `20180428m1_Cable`, `201804_LuciaChica2m`, `20190317m2_600mGully`, `20190318m2_Transect601060m`. The pockmark/bank-top pairs are expected `auto_pass`.

### D.4 Re-verify the two rejections
Confirm that `20190318m1_LuciaChica1100m` and `20190319m1_8mPockmarkDetail` are **true geographic non-overlap**, not a footprint/transform artifact — specifically check `LuciaChica1100m`, since the ship mosaic extends to ~1,620 m and a 1,100 m patch would be expected to fall within it. Report the overlap geometry, don't just restate "no intersection."

---

## E. Minor fixes (fold in during the re-run)

- **Reuse local Cal DIG AUV.** Raw came in at 2.0 G, suggesting the AUV HR was re-downloaded. Point the fetcher at the locally-held Morro Bay copy and skip the download when present (v1.0 §6 step 1).
- **Strengthen the non-synthesis audit.** The current audit asserts `lr_native_res_m > hr_native_res_m`, which is necessary but not sufficient. Replace with a provenance assertion: the LR raster's recorded source DOI matches the declared ship DOI in §4 and the file was fetched (checksum present in `metadata.json`). The behavior was already correct; make the audit prove it.

---

## F. Updated hard rules (amends v1.0 §8)

- A sub-pair is usable downstream only if `coreg_status == auto_pass` **or** a human has explicitly cleared it after reviewing its overlay artifact. Low MAD alone never qualifies.
- `horiz_offset_m > usbl_bound_m` never auto-passes — it is `needs_review` regardless of MAD.
- Every sub-pair (including auto-passes and DISCOL) must have its hillshade-overlay artifact written before it is considered complete.
- Empirical thresholds (`min_peak_sharpness`, `peak_anisotropy_max`) must be calibrated and human-confirmed (§D.2); do not invent them.

---

## G. Gate

- **M1.5 — Co-registration QA re-run.** Apply §A–§E to the existing Tier 1 output. Deliverables: overlay artifacts for all sub-pairs (incl. DISCOL), the calibration plot + proposed thresholds, the reclassified manifest with new columns, the rejection re-verification, and a short report listing every `needs_review` sub-pair with its offset/PSR/eig_ratio. **Pause for human review.**
- **Tier 2 stays blocked** until every Cal DIG sub-pair is `auto_pass` or explicitly cleared/rejected, and the revised gate is in place.
