# M1.5 — Co-registration QA re-run report (2026-06-03)

Implements Acquisition Directive v1.1 (co-registration QA addendum) against the already-harmonized M1 Tier-1 output. No re-download, no re-solve.

## Verdict

- Sub-pairs evaluated: **18** (1 DISCOL + 17 Cal DIG).
- Hillshade overlay artifacts: **18/18** present.
- `coreg_status` distribution: needs_review=18
- **Every sub-pair is `needs_review`** because the two empirical thresholds (`min_peak_sharpness`, `peak_anisotropy_max`) are not yet written to config — calibration (§D.2 below) was inconclusive against the addendum's labeled set, so I refuse to invent them per the directive's hard rule.
- **Tier 2 remains blocked.**

## §A — New QA metrics

For each sub-pair, we computed gradient-magnitude NCC over a ±30 m search window centred at the already-applied solved offset (which is therefore expected to peak near (0,0) for a correctly locked pair):

- `horiz_offset_m` = magnitude of the applied (dx, dy) from the original coreg solve
- `vert_offset_m` = |dz|
- `coreg_peak_psr` = peak-to-sidelobe ratio of NCC
- `coreg_peak_eig_ratio` = larger/smaller Hessian eigenvalue at peak (anisotropy)
- `coreg_peak_agrees` = NCC max sits within 1 LR cell of (0,0)

## §D.2 — Threshold calibration result

Calibration plot: `/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/reports/calibration_psr_vs_eig.png`.

Labeled set used (per addendum):
- Known-good: `20180426m1_PockmarkNorthDet`, `20180427m3_PockmarkNorth` (duplicate pockmark surveys, solved to similar offsets)
- Known-suspect: `20190315m1_HeadlessCanyon` (high offset, worst MAD, linear morphology)

Summary statistics:

| label | n | PSR (min/med/max) | eig_ratio (min/med/max) |
|---|---:|---|---|
| known_good | 2 | 2.71 / 3.80 / 4.88 | 1.34 / 3.45 / 5.57 |
| known_suspect | 1 | 5.04 / 5.04 / 5.04 | 1.15 / 1.15 / 1.15 |
| unlabeled | 14 | 1.29 / 5.12 / 7.81 | 1.01 / 1.32 / 132.10 |

**Calibration result: INCONCLUSIVE.**

- known-good PSR floor = 2.71; suspect PSR = 5.04 (inside)
- known-good eig_ratio ceiling = 5.57; suspect eig = 1.15 (inside)

_Known-good and known-suspect tiles are NOT separable by PSR or eig_ratio alone with the current NCC computation. Possible causes: (1) the duplicate pockmark surveys may share the same systematic USBL bias and so are not truly known-good in a morphology-lock sense; (2) the gradient-NCC signal is weak after HR→LR aggregation. Recommend human review of overlay PNGs to expand the labeled set._

Required human action: review the overlay PNGs (paths in the manifest) and extend or revise the labeled set, then re-run `python -m src.cli m15-report`.

## §D.3 — All Cal DIG sub-pairs (sorted by PSR ascending; weakest locks first)

| sub-pair | horiz (m) | vert (m) | PSR | eig | agrees | overlay |
|---|---:|---:|---:|---:|---:|---|
| `20190317m1_1000mGully` | 22.0 | 1.49 | 1.29 | 2.78 | ✗ | `cal_dig_morro_bay__20190317m1_1000mGully_overlay.png` |
| `20180428m1_Cable` | 50.8 | 1.54 | 2.34 | 1.21 | ✗ | `cal_dig_morro_bay__20180428m1_Cable_overlay.png` |
| `20180427m2_PockmarkSouthBasinFlank` | 4.3 | 1.65 | 2.44 | 2.79 | ✗ | `cal_dig_morro_bay__20180427m2_PockmarkSouthBasinFlank_overlay.png` |
| `20180427m3_PockmarkNorth` | 34.8 | 1.53 | 2.71 | 5.57 | ✓ | `cal_dig_morro_bay__20180427m3_PockmarkNorth_overlay.png` |
| `20180427m1_Channel700` | 10.8 | 0.80 | 2.87 | 4.08 | ✓ | `cal_dig_morro_bay__20180427m1_Channel700_overlay.png` |
| `20190317m2_600mGully` | 36.5 | 0.94 | 4.01 | 1.56 | ✓ | `cal_dig_morro_bay__20190317m2_600mGully_overlay.png` |
| `20190314m4_LuciaChica970m` | 7.8 | 2.04 | 4.49 | 132.10 | ✓ | `cal_dig_morro_bay__20190314m4_LuciaChica970m_overlay.png` |
| `20180426m2_Channel1000` | 22.4 | 1.64 | 4.66 | 1.01 | ✓ | `cal_dig_morro_bay__20180426m2_Channel1000_overlay.png` |
| `20180426m1_PockmarkNorthDet` | 32.6 | 1.71 | 4.88 | 1.34 | ✗ | `cal_dig_morro_bay__20180426m1_PockmarkNorthDet_overlay.png` |
| `20190315m1_HeadlessCanyon` | 37.7 | 2.08 | 5.04 | 1.15 | ✗ | `cal_dig_morro_bay__20190315m1_HeadlessCanyon_overlay.png` |
| `20190510m2_BankFlankIncipCh` | 43.0 | 0.26 | 5.57 | 1.02 | ✗ | `cal_dig_morro_bay__20190510m2_BankFlankIncipCh_overlay.png` |
| `20190511m1_6thHeadlessCany` | 17.9 | 1.33 | 5.67 | 1.01 | ✓ | `cal_dig_morro_bay__20190511m1_6thHeadlessCany_overlay.png` |
| `20190316m1_BankTop` | 21.8 | 0.24 | 5.79 | 1.01 | ✗ | `cal_dig_morro_bay__20190316m1_BankTop_overlay.png` |
| `201804_LuciaChica2m` | 41.8 | 2.58 | 5.92 | 8.95 | ✗ | `cal_dig_morro_bay__201804_LuciaChica2m_overlay.png` |
| `20190510m1_BankFlankHoles` | 7.0 | 1.77 | 5.94 | 1.04 | ✓ | `cal_dig_morro_bay__20190510m1_BankFlankHoles_overlay.png` |
| `20190511m2_BankTopEofCanyon3` | 10.9 | 0.11 | 6.49 | 1.05 | ✓ | `cal_dig_morro_bay__20190511m2_BankTopEofCanyon3_overlay.png` |
| `20190318m2_Transect601060m` | 35.5 | 1.85 | 7.81 | 1.43 | ✓ | `cal_dig_morro_bay__20190318m2_Transect601060m_overlay.png` |

## DISCOL (evaluated at (0,0,0) offset; AUV pre-corrected upstream)

- `coreg_status`: **needs_review**
- PSR=6.16, eig_ratio=1.67, peak_agrees=True
- Overlay: `discol_so242_1_overlay.png`

## §D.4 — Rejection re-verification

See `rejection_reverification_20260603.md` for full geometry analysis.

Both rejected AUV tiles (`20190318m1_LuciaChica1100m`, `20190319m1_8mPockmarkDetail`) sit ~6.5 km from the nearest LR-valid pixel — a real geographic hole in the Cal DIG ship multibeam coverage at ~1,100 m depth. True non-overlap, not a footprint/transform artifact. Both stay `reject`.

## §E — Fetcher hardening + non-synthesis audit

Implemented:

- `src/download.local_release_matches(local_path, expected_doi)` — reuse-local guard: a local file only substitutes for a fresh fetch when a `<file>.doi.json` sidecar carries the matching DOI. Same-name files at generic paths are not sufficient.
- `src/audit.py` + `python -m src.cli audit` — replaces the old `lr_native_res_m > hr_native_res_m` check with a provenance assertion: each manifest row's `metadata.json` must contain HR + LR entries whose DOIs match the manifest, with checksums and source URLs present, and the LR source URL must not reference the HR DOI.
- Audit result: **all 18 rows pass.**

## §F — Updated hard rules (now enforced)

- A sub-pair is usable downstream only if `coreg_status == auto_pass` OR a human has explicitly cleared it after reviewing its overlay PNG. Low MAD alone never qualifies.
- `horiz_offset_m > usbl_bound_m` (=30.0) never auto-passes — routes to `needs_review`.
- Every sub-pair (incl. DISCOL) has its hillshade-overlay artifact written.
- `min_peak_sharpness` and `peak_anisotropy_max` remain unset (`null`) in `config/harmonization.yaml`; no value will be invented.

## Gate

- **M1.5 pause.** Tier 2 stays blocked until: (a) the labeled set is revised via overlay-PNG review or the calibration metric is refined to separate the known-good and known-suspect clusters, (b) thresholds are calibrated and written to config, (c) every Cal DIG sub-pair is `auto_pass` or explicitly cleared / rejected.
