# INTERFACE CONTRACT v2.1: ship-side products per co-located pair

**Date:** 2026-09-30
**Supersedes:** `INTERFACE_CONTRACT_v2.md`. The v1 and v2 product directories stay on disk, unmodified and deprecated.
**Applies to:** the acquisition repo (producer) and the CNN repo (consumer).
**Status:** frozen at v2.1 when ACQ-R03 has committed it verbatim, with a ledger row. The CNN repo commits it in its next
directive.

## 0. What changed from v2, and why

1. **`registration_shift` gate tightened.** In v2 the flag fired whenever the minimising shift was not (0, 0). In
   ACQ-R02 it fired on 13 of 16 pairs, most of them one 0.25-cell step from (0, 0) with centimetre-level gains. At that
   scale the difference comes from comparing a box median with an `mbgrid` footprint-weighted surface; it is not
   misregistration. v2.1 flags only a shift of **at least half a cell** with a material gain (§4).
2. **Frame offset for grids with a known registration error.** Some provider grids have a documented half-cell
   registration difference. One example is a node-registered GMT grid warped as pixel-is-area; ACQ-R03 §2 checks
   whether this applies to CCZ, DISCOL and TAG. The pair's HR was co-registered to `lr.tif`, so the pair is internally
   consistent. Only the ship products, binned at the soundings' true positions, sit half a cell off.

   Where the offset is **derived from grid headers** (not fitted from the QA surface), soundings are binned in
   `lr.tif`'s effective frame. That means soundings are shifted by the derived offset before binning. `lr.tif` is not
   modified.
3. Directory name `ship_products_v2_1/`.

## 1. Principle (unchanged)

Every pair gets the same ship-side products, built by the same code, on the **same grid as the pair's harmonized
`lr.tif`** (same CRS, transform, shape, cell). Existing harmonized files are **not modified**. `lr.tif` remains the model
input. The products are additional channels and features.

All products are ship-only. No HR-derived quantity may enter any product. Soundings are **raw** (the mode stage C
gridded).

## 2. Location

`<directory containing the pair's lr.tif, as given by the manifest's harmonized_path>/ship_products_v2_1/`

Consumers resolve the directory from the manifest, never from `pair_id`.

## 3. Per-pair products (unchanged from v2)

| file | content | units | dtype / nodata | condition |
|---|---|---|---|---|
| `ship_count.tif` | number of soundings per cell | count | float32 / NaN | NaN where 0 |
| `ship_sd.tif` | standard deviation of soundings in the cell | m | float32 / NaN | count ≥ 2 |
| `ship_rsd.tif` | 1.4826 × median(\|z − median(z)\|) of soundings in the cell | m | float32 / NaN | count ≥ 3 |
| `ship_xtrack_frac.tif` | mean over soundings in the cell of \|acrosstrack\| / (swath half-width of that ping) | 0–1 | float32 / NaN | count ≥ 1 |
| `ship_beam_angle.tif` | mean over soundings in the cell of \|beam angle from vertical\| | degrees | float32 / NaN | count ≥ 1 |
| `ship_mean_regrid.tif` | mean depth, **QA only**, never a model input | m (positive-up) | float32 / NaN | count ≥ 1 |
| `ship_median_regrid.tif` | median depth, **QA only**, never a model input | m (positive-up) | float32 / NaN | count ≥ 1 |
| `products.json` | provenance and QA; schema in §5 | — | — | — |

Definitions are as in v2:

- Half-width per ping = max \|acrosstrack\| among that ping's valid beams.
- Beam angle comes from the format's launch angle where it is carried for ≥ 99 % of beams. Otherwise it is geometric.
  The method is recorded per pair.
- Per-cell medians are exact.

## 4. QA against `lr.tif`

All QA uses `ship_median_regrid` (m) against `lr.tif` on common valid cells. The shift surface is computed as in v2:
shifts (dx, dy) ∈ {−1.00, −0.75, …, +1.00}² cells, bilinear resampling, robust σ (1.4826 × MAD) of (shifted m − lr).
Here σ₀ is the robust σ at (0, 0), and gain = σ₀ − σ at the argmin.

**Gates** (the pair's `flags` list is empty only if all pass):

| flag | test |
|---|---|
| `insufficient_overlap` | fewer than 500 common cells |
| `vertical_offset` | \|median(m − lr)\| > max(0.5 m, 0.05 × median s_lr) |
| `registration_shift` | max(\|dx\|, \|dy\|) at the argmin ≥ 0.50 cell **and** gain ≥ max(0.10 m, 0.05 × σ₀) |

**Reported, not gated:** n common cells, median offset, RMS, σ₀, σ at the argmin, gain, the argmin, robust σ / median
s_lr, and RMS / median s_lr.

**Frame offset.** When `frame_offset` is applied (§0.2), QA is computed after binning in the offset frame. The expected
result is an argmin within ±0.25 cell of (0, 0). If it is not, the flag stands, and the pair is reported.

## 5. `products.json` schema (v2.1)

As v2, with `"contract_version": "2.1"`, plus:

```json
"frame_offset": {"applied": false, "dx_m": 0.0, "dy_m": 0.0,
                 "basis": "none | grid_header_registration",
                 "evidence": "header fields and values that establish the offset"},
"qa_vs_lr_tif": { "...": "as v2",
                  "sigma0_m": 0.0, "sigma_argmin_m": 0.0, "gain_m": 0.0 }
```

The `frame_offset` rules:

- It may be applied only with `basis: grid_header_registration`.
- It is never fitted from the QA shift surface.
- It is recorded even when not applied (`applied: false`).

**Pairs without swath** (Cal DIG) are unchanged from v2: every `available` flag is false, `unavailable_reason` is
filled, no rasters are written, and consumers never zero-fill.

## 6. Consumer rules (CNN repo)

- Validate every pair against this contract before use: schema, grid identity with `lr.tif`, NaN convention and count
  conditions.
- Use a product as a feature or channel only when its `available` flag is true **and** QA `flags` is empty. Using a
  flagged pair's products requires steering sign-off, recorded in the ledger.
- Report per-unit availability wherever such a feature is used.
- Missing channels are represented by an explicit availability mask, never by fill values.
- `ship_mean_regrid` and `ship_median_regrid` are never inputs.

## 7. Lockbox and confirmatory units (unchanged)

The 2 lockbox pairs and every pair in a **confirmatory** unit get their products built with the frozen code **only at
Phase 4**.
