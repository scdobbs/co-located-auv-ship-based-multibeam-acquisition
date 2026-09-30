# ACQ-R03 §4 — Amundsen lr_native audit (lu18)

| item | 2009_Amundsen__MGDS_30046 (June) | 2009_Amundsen__MGDS_30047 (ACQ-R02) |
|---|---|---|
| median depth under HR (joint cells, now) | -238.8 m (June record 238.8 m) | -222.7 m (grid footprint depth 166.8 m; harmonized-LR median used for lr_native 279 m) |
| documented beam footprint (EM302, 1°) | 4.2 m at 238.8 m | 2.91 m at 166.8 m; 4.87 m at 279 m (used); 3.89 m at the HR median |
| gridding cell used | 16.0 m — June pilot grid `2009_Amundsen__MGDS_30045.grd`, cell = footprint at the 915.5 m median depth of the MGDS:30045 footprint bbox; 30046 harmonized against it (C1 phase 1) | 2.91 m — `grid/2009_Amundsen.json`, footprint at 166.8 m (soundings in the 30047 bbox) |
| C2a lr_native = max(footprint, posting) | max(4.2, 16.0) = 16.0 m (case B_regrid; June ruling: keep posting, no regrid) | max(4.87, 2.92) = 4.87 m |

**Verdict.** Both pairs record lr_native = max(footprint, posting) (C2a). The difference (16 m vs 4.87 m) is NOT explained by depth: both HR sit at 220–240 m (footprints 3.9–4.2 m). 30046's posting (16 m) comes from a grid whose cell was set by the 915 m median depth of the MGDS:30045 footprint bbox, i.e. the stage-C cell rule applied to a different, deeper HR; the pair was never gridded at its own footprint depth (Steve's June C2a case-B ruling: lr_native = 16 m posting, no regrid). 30047's posting (2.91 m) follows the standard rule at its own footprint depth (166.8 m), and its lr_native (4.87 m) uses the footprint at the harmonized-LR median depth (279 m), not the HR median (223 m) or the grid depth (167 m): a third depth definition inside one pair.

**HOLD H-A (§4): 2009_Amundsen__MGDS_30046's 16 m posting deviates from the standard stage-C cell (its own-footprint cell would be ≈ 4.2 m); the two lu18 pairs therefore carry lr_native 16 m and 4.87 m over the same shelf at the same depth. Steve's call: keep the June ruling (16 m, no regrid) or regrid 30046 at its own footprint depth in a later directive. Nothing modified here.**
