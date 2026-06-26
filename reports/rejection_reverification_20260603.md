# Rejection re-verification (M1.5 §D.4) — 2026-06-03

Two Cal DIG AUV dive-patch tiles were rejected at harmonization time as "HR and LR footprints do not intersect". The v1.1 addendum §D.4 requires that this be verified as **true geographic non-overlap** rather than a footprint or transform artifact — especially for `LuciaChica1100m` which at ~1,100 m depth sits within the documented LR depth range (100–1,600 m).

LR reference: `Cal_DIG_I_Bathymetry_10m.tif` (`10.5066/P9QQZ27U`), EPSG:26910, 11208×15184 px at 10 m, total valid coverage ≈ **8,424 km²** within a 17,000 km² bounding box (so ~50% of the bbox is nodata; the ship survey has substantial coverage holes).

## 20190318m1_LuciaChica1100m

- HR CRS: EPSG:32610 (UTM 10N / WGS84)
- HR valid coverage: 7.49 km² (5,900×4,737 px at 1.12 m)
- HR bbox in LR CRS: (599657, 3955470) — (606268, 3960778); the bbox **is inside** the LR bbox.
- HR depth range: -1,189 to -1,034 m (median -1,094 m) — within the LR's documented range.
- HR centroid (LR CRS): (603020, 3958161).
- **Distance from HR centroid to nearest LR-valid pixel: ~6.46 km.**
- LR valid ∩ HR valid area: **0.000 km²**.

The HR patch sits squarely inside the LR bbox at an in-range depth, but lies in a ~6 km hole in the actual ship-multibeam coverage. The rejection is correct — this is true geographic non-overlap, not a CRS/footprint artifact.

## 20190319m1_8mPockmarkDetail

- HR CRS: EPSG:32610
- HR valid coverage: 0.186 km² (434×432 px at 1.12 m, very small detail survey)
- HR bbox in LR CRS: (601997, 3957341) — (602483, 3957825); inside LR bbox.
- HR depth range: -1,114 to -1,100 m (median -1,105 m) — within the LR's documented range.
- HR centroid (LR CRS): (602240, 3957584).
- **Distance from HR centroid to nearest LR-valid pixel: ~6.60 km.**
- LR valid ∩ HR valid area: **0.000 km²**.

Same coverage hole as `LuciaChica1100m` — adjacent patches from the same gap region (the two centroids are ~830 m apart). Rejection is correct.

## Conclusion

Both rejections are real geographic non-overlap: the AUV dove ~6.5 km west of the western edge of the Cal DIG ship multibeam coverage in this area. They are NOT footprint, CRS, or transform artifacts. No further action is needed; both stay `reject`.
