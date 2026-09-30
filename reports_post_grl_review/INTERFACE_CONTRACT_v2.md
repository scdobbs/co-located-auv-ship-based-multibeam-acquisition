# INTERFACE CONTRACT v2: ship-side products per co-located pair

**Date:** 2026-09-30
**Supersedes:** `INTERFACE_CONTRACT_v1.md` (2026-09-29). v1 products stay on disk, unmodified and deprecated. They are not deleted.
**Applies to:** the acquisition repo (producer) and the CNN repo (consumer).
**Status:** frozen at v2 when both ACQ-R02 and the CNN repo's next directive have committed it verbatim, with a ledger row in each repo.

## 0. What changed from v1, and why

1. **Robust spread channel added (`ship_rsd`).** Products are built from raw soundings, the same mode `lr.tif` was gridded
   from. Raw blunders dominate `ship_sd` on some pairs. For example, FK181031 has an RMS of 21.5 m against a MAD of
   1.2 m versus `lr.tif`. A MAD-based spread measures sub-cell relief and sounding noise without being controlled by
   spikes.
2. **QA redefined.** v1 gated on RMS / median s_lr > 0.10 of the raw per-cell mean against `lr.tif`. That compares a
   box mean with a footprint-weighted `mbgrid` surface. Those two legitimately differ on rough terrain by a sizeable
   fraction of s_lr, even on robust statistics, so the v1 gate measured gridding differences rather than product
   errors. The question the QA must answer is whether the products are **registered** to the `lr.tif` cells and share
   its **vertical datum**. v2 gates on exactly those two things and reports agreement statistics without gating on
   them.
3. **Path resolved from the manifest.** Some pairs (Cal DIG) are not stored at `harmonized/<pair_id>/`.

## 1. Principle (unchanged)

Every pair gets the same ship-side products, built by the same code, on the **same grid as the pair's harmonized
`lr.tif`** (same CRS, transform, shape, cell). Existing harmonized files are **not modified**. `lr.tif` remains the model
input. The products are additional channels and features.

All products are ship-only. No HR-derived quantity may enter any product. Soundings are **raw** (the mode stage C
gridded).

## 2. Location

`<directory containing the pair's lr.tif, as given by the manifest>/ship_products_v2/`

Consumers resolve the directory from the manifest's harmonized path, never from `pair_id`.

## 3. Per-pair products

| file | content | units | dtype / nodata | condition |
|---|---|---|---|---|
| `ship_count.tif` | number of soundings per cell | count | float32 / NaN | NaN where 0 |
| `ship_sd.tif` | standard deviation of soundings in the cell | m | float32 / NaN | count ≥ 2 |
| `ship_rsd.tif` | 1.4826 × median(\|z − median(z)\|) of soundings in the cell | m | float32 / NaN | count ≥ 3 |
| `ship_xtrack_frac.tif` | mean over soundings in the cell of \|acrosstrack distance\| / (swath half-width of that ping) | 0–1 | float32 / NaN | count ≥ 1 |
| `ship_beam_angle.tif` | mean over soundings in the cell of \|beam angle from vertical\| | degrees | float32 / NaN | count ≥ 1 |
| `ship_mean_regrid.tif` | mean depth of the soundings, **QA only**, never a model input | m (positive-up, as `lr.tif`) | float32 / NaN | count ≥ 1 |
| `ship_median_regrid.tif` | median depth of the soundings, **QA only**, never a model input | m (positive-up) | float32 / NaN | count ≥ 1 |
| `products.json` | provenance and QA; schema in §5 | — | — | — |

Definitions are unchanged from v1 for count, sd, xtrack_frac and beam_angle:

- Half-width per ping = max \|acrosstrack\| among that ping's valid beams.
- Beam angle comes from the format's launch angle where it is carried for ≥ 99 % of beams. Otherwise it is geometric,
  atan(\|acrosstrack\| / \|depth\|). The method used is recorded per pair.

`ship_rsd` and `ship_median_regrid` are exact per-cell medians, not approximations.

## 4. QA against `lr.tif`

All QA uses `ship_median_regrid` (m) against `lr.tif` on common valid cells.

**Gates** (a pair's QA `flags` list is empty only if all pass):

| flag | test |
|---|---|
| `insufficient_overlap` | fewer than 500 common cells |
| `vertical_offset` | \|median(m − lr)\| > max(0.5 m, 0.05 × median s_lr) |
| `registration_shift` | Shift m by (dx, dy) ∈ {−1.00, −0.75, …, +1.00}² cells (bilinear resampling). Compute the robust σ (1.4826 × MAD) of (shifted m − lr) at each shift. The flag is set if the minimising shift is not (0, 0). The full shift surface and its argmin are recorded. |

**Reported, not gated:** n common cells, median offset, RMS, robust σ, RMS / median s_lr, robust σ / median s_lr, and
the argmin shift. The s_lr source is recorded as in v1.

## 5. `products.json` schema (v2)

```json
{
  "contract_version": 2,
  "pair_id": "...",
  "lr_tif_path": "...",
  "available": {"ship_count": true, "ship_sd": true, "ship_rsd": true,
                "ship_xtrack_frac": true, "ship_beam_angle": true},
  "unavailable_reason": null,
  "source": {"kind": "ncei_swath | provider_swath | none",
             "files": [{"name": "...", "url": "...", "sha256": "..."}],
             "mb_format": 58, "processing_mode": "raw"},
  "beam_angle_method": "launch_angle | geometric",
  "software": {"mbsystem": "5.8.2beta06", "container": "...", "code_commit": "..."},
  "commands": ["exact command lines as run"],
  "grid": {"crs": "...", "transform": [...], "shape": [ny, nx], "matches_lr_tif": true},
  "qa_vs_lr_tif": {"n_common_cells": 0, "median_offset_m": 0.0, "rms_m": 0.0, "robust_sigma_m": 0.0,
                   "rms_over_median_s_lr": 0.0, "robust_sigma_over_median_s_lr": 0.0,
                   "s_lr_source": "...",
                   "shift_argmin_cells": [0.0, 0.0], "shift_surface_file": "qa_shift_surface.csv",
                   "flags": []},
  "created": "ISO-8601"
}
```

**Pairs without swath** (for example, Cal DIG: USGS mosaic of NOS BAG surveys, no per-beam soundings):

- Write `products.json` with every `available` flag false and `unavailable_reason` filled.
- Write **no** rasters.
- Consumers treat such pairs as missing these channels. They are never zero-filled.

## 6. Consumer rules (CNN repo)

- Validate every pair against this contract before use: schema, grid identity with `lr.tif`, NaN convention and count
  conditions.
- Use a product as a feature or channel only when its `available` flag is true **and** QA `flags` is empty. Using a
  flagged pair's products requires steering sign-off, recorded in the ledger.
- Report per-unit availability wherever such a feature is used.
- Missing channels are represented by an explicit availability mask, never by fill values.
- `ship_mean_regrid` and `ship_median_regrid` are never inputs.

## 7. Lockbox and confirmatory units

The 2 permanent-holdout pairs (AT42-03__MGDS_32007, TN159__MGDS_21981) and every pair in a **confirmatory** unit get
their products built with the frozen code **only at Phase 4**, not before.
