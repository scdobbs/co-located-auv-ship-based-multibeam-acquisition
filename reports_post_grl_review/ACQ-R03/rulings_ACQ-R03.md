# RULINGS ACQ-R03 (Steve, 2026-10-01)

**Applies to:** `reports_post_grl_review/ACQ-R03/REPORT_ACQ-R03_2026-09-30.md`
**Effect:** authorizes ACQ-R03 §6 (finalize). Commit this file verbatim to `reports_post_grl_review/ACQ-R03/` before §6
runs. Every manifest row changed under a ruling records `ruling_source = "rulings_ACQ-R03 R<n>"`.

All standing rules of ACQ-R03 still apply: scope discipline, challenge clause, the lockbox guard, the confirmatory
seal and anti-circularity.

---

## R1. AT37-05__MGDS_24043: drop

Line `0009_20161106_011723` is ≈ 294 m deeper than lines 0000/0005/0006 over ≈ 4,500 shared cells, 85–88× the local
robust spread. That is a ship-internal inconsistency averaged into `lr.tif`, on the drop side of the committed
criterion (`at37_05_review_criterion.md`).

- Add the pair to the dropped list with reason `ship_internal_inconsistency`.
- vu05 had no other member, so the unit is removed.

## R2. pu01, PANGAEA_864677__PANGAEA_889317 (Chapopote): drop

It fails the 30 m co-registration bound (53.8 m; dz +42.5 m), and even if kept it would be 1 tile at k = 2 with a 10 m
HR grid.

- Add the pair to the dropped list with reason `coreg_fail`.
- No QGIS arbitration.
- Files on OAK stay where they are, unmodified.

## R3. pu00, PANGAEA_892317 (Venere, M112/1): continue, with a time-window pre-filter

Keep job 46140636 (or its successor) running. Add this pre-filter to the M112 selection.

1. **Source.** Use the M112 cruise report (Bohrmann 2015, METEOR-Berichte M112, doi:10.2312/cr_m112), specifically its
   station list and daily narrative. From it, determine every UTC time window in which METEOR was operating in the
   Venere working area: EM122 surveys there, and AUV deployments or recoveries there, because the EM122 recorded
   continuously.
   - If the report cannot be reached from the cluster, say so in an interim note. Steve will supply it.
2. **Windows.** Widen each window to whole UTC days, plus one day on each side. Record the windows and the report
   pages they come from.
3. **Pre-filter.** Take the `.all` files whose file-name start time falls inside a window. Fetch `Range` heads for those
   files **first**, positions take priority, and apply the existing segment ∩ 4 km-buffered-footprint test to them.
4. **Selection.** The pre-filtered, position-tested files are the pu00 selection. This replaces the earlier rule that
   every file must have a position before any selection is made.
   - The 68 heads already on disk are used as they are.
   - Heads for files outside the windows are **not** required.
   - Record the limitation in the report: a file outside the windows that crosses the footprint is not examined.
5. **Coverage check.** After gridding, if `fill_fraction_per_hr` < 0.9, widen each window by one more day on each side
   and repeat steps 3–4, once only. If coverage is still below 0.9 after that, stop and report it as a HOLD.
6. **After the pre-filter.** Fetch, grid, harmonize, QA, k sweep and v2.1 products follow ACQ-R03 §1.3–§1.5. pu00 is
   **development**.
   - If it passes QA, it enters manifest v2.1.
   - If it fails QA, it is dropped (no reassignment).
   - If it is not complete when the rest of §6 is done, write manifest v2.1 without it and add pu00 as v2.1.1 once its
     chain finishes. Do not hold the rest of §6 waiting for it.
7. **Manual path.** Steve may still download files himself; the manual-ingest path (§1.4) stays open. Publish the
   pre-filtered selection as `pangaea_selection_PANGAEA_892317.csv` and `_urls.txt` as soon as it exists.

## R4. CCZ, DISCOL, TAG ship products: masked (unavailable for use)

Their v2.1 `registration_shift` flags stand: argmins of roughly (−½, +½) cell, with no header basis for a frame
offset. Under contract v2.1 §6 the consumer may not use flagged products without steering sign-off, and **no sign-off
is given**.

- Record this in manifest v2.1: column `ship_products_usable = false`, reason
  `registration_shift_unresolved (rulings R4)`, for `ccz_so268_1`, `discol_so242_1` and `tag_m127`.
- The rasters stay on disk, unmodified. The pairs themselves (HR/LR) remain development pairs and are unaffected.
- Also mark AT37-05 `ship_products_usable = false`. It is moot, since the pair is dropped under R1.
- EW0207 is reported separately, as before; its `vertical_offset` flag is recorded as it stands.

## R5. Amundsen `lr_native` (unit lu18): apply the stage-C standard to 30046

The steering instance is ruling here, by Steve's delegation.

`2009_Amundsen__MGDS_30046`'s 16 m posting came from a different HR's grid (MGDS:30045, 915 m). At its own depth
(≈ 239 m) the stage-C cell is ≈ 4.2 m. A 16 m LR represents the ship as coarser than its documented capability at that
depth, which inflates apparent unresolved relief. The standard is applied, not the June posting.

1. In §6, regrid 30046's LR from the raw swath already on OAK (`raw_lr_swath/2009_Amundsen/`), using the stage-C rule
   at the **median depth under its own HR footprint**. Use the same standard as 30047, with the depth definition used
   for `lr_native` stated explicitly and applied identically to both pairs.
2. Write the result as a new versioned LR in the pair's harmonized directory (`lr_v2_1.tif` plus masks). The June
   `lr.tif` is **not** modified or deleted.
3. Re-run co-registration QA, the C2a `lr_native` rule and the k sweep on the new LR. Build v2.1 products on the new
   grid in `ship_products_v2_1_lrv2_1/`.
4. Manifest v2.1 points 30046 at the new LR (`harmonized_lr = lr_v2_1.tif`, `ruling_source R5`). If 30047's
   `lr_native` changes under the unified depth definition, update and record it the same way.
5. If either pair is then no-k, it is recorded as no-k and excluded from usable counts, as for any no-k pair. lu18
   remains a unit in the table. The likely outcome is that the Amundsen shelf pairs drop out of the usable set; that
   is accepted.

## R6. Confirmatory co-registration: reinstate both

Steve has reviewed both packages in QGIS against `confirmatory_review_criterion.md` and signs off on both.

- **KN182L03__MGDS_30193 (nu01a)** is reinstated.
- **SUM1004__MGDS_33090 (nu03)** is reinstated.

Both return to their units under the seal. This is a QA ruling, not a reassignment, and their designation stays
`confirmatory`.

- No residual, amplitude, target or product computation.
- Manifest v2.1 lists them with path and designation only.

The confirmatory holdout at the end of Phase 1 is therefore **nu01a, nu01b (RC2511) and nu03**, plus the lockbox.

---

## Labels (ACQ-R03 report §8): apply as proposed

- MGDS:5174 → EPR 9°N.
- lu07 → "TN293 sites (Loihi; Necker Ridge)".
- AT37-05 designation → moot (R1).
- Fill the empty `site_name` / `region` / `terrain_class` / `geo_cluster` fields on the ACQ-R02 rows from the
  verification table.
- Memberships are unchanged.

## §6 deliverable

As directed:
- `manifest/pairs_v2_1.parquet`, with `ruling_source` and the `ship_products_usable` column from R4;
- validation;
- the development-unit table, with separate counts of usable units and usable pairs.

In the table, mark ship-product usability per unit, so the counts with and without usable ship channels are both
visible.
