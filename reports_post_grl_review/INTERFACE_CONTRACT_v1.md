# INTERFACE CONTRACT v1: ship-side products per co-located pair

**Date:** 2026-09-29
**Applies to:** the acquisition repo (producer) and the CNN repo (consumer).
**Status:** frozen at v1 when both ACQ-R01 and R04 have committed it verbatim. Any change → v2, a new file, and a ledger row in both repos.

## 1. Principle

Every pair gets the same ship-side products, built by the same code, on the **same grid as the pair's existing harmonized
`lr.tif`** (same CRS, transform, shape, cell). Existing harmonized files are **not modified**. The model input
(`lr.tif`) does not change under this contract. The new products are additional channels and features.

All products are ship-only. No HR-derived quantity may enter any product.

## 2. Per-pair products (OAK: `.../auv_ship_colocated_bathy/harmonized/<pair_id>/ship_products_v1/`)

| file | content | units | dtype / nodata |
|---|---|---|---|
| `ship_sd.tif` | standard deviation of soundings falling in each `lr.tif` cell | m | float32 / NaN |
| `ship_count.tif` | number of soundings per cell | count | float32 / NaN |
| `ship_xtrack_frac.tif` | mean over soundings in the cell of \|acrosstrack distance\| / (swath half-width of that ping) | 0–1 | float32 / NaN |
| `ship_beam_angle.tif` | mean over soundings in the cell of \|beam angle from vertical\| | degrees | float32 / NaN |
| `ship_mean_regrid.tif` | mean depth of the same soundings, **QA only**, never a model input | m (positive-up, as `lr.tif`) | float32 / NaN |
| `products.json` | provenance and QA; schema in §3 | — | — |

Cells with no soundings are NaN in every raster. `ship_sd` is NaN where count < 2.

## 3. `products.json` schema

```json
{
  "contract_version": 1,
  "pair_id": "...",
  "available": {"ship_sd": true, "ship_count": true, "ship_xtrack_frac": true, "ship_beam_angle": true},
  "unavailable_reason": null,
  "source": {"kind": "ncei_swath | provider_swath | none",
             "files": [{"name": "...", "url": "...", "sha256": "..."}],
             "mb_format": 58, "processing_mode": "raw | cleaned"},
  "software": {"mbsystem": "5.8.2beta06", "container": "...", "code_commit": "..."},
  "commands": ["exact command lines as run"],
  "grid": {"crs": "...", "transform": [...], "shape": [ny, nx], "matches_lr_tif": true},
  "qa_vs_lr_tif": {"n_common_cells": 0, "rms_m": 0.0, "median_offset_m": 0.0, "mad_m": 0.0,
                   "rms_over_median_s_lr": 0.0, "flag": "ok | exceeds_0.10"},
  "created": "ISO-8601"
}
```

Pairs without swath (provider grids with no retrievable soundings): write `products.json` with every `available` false
and `unavailable_reason` filled. Write **no** rasters. Consumers treat such pairs as missing these channels. They must
never be zero-filled.

## 4. Consumer rules (CNN repo)

- Validate every pair against this contract before use: schema, grid identity with `lr.tif`, NaN convention.
- Use any product as a feature or channel only when its `available` flag is true. Report per-unit availability
  wherever such a feature is used.
- `ship_mean_regrid.tif` is never an input.

## 5. Lockbox

The 2 permanent-holdout pairs (AT42-03__MGDS_32007, TN159__MGDS_21981) get their products built with the frozen code
**only at Phase 4**, not before.
