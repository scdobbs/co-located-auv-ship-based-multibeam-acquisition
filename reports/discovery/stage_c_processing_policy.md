# Stage C — processing-policy spot check (C-full-0)

**Date:** 2026-06-23 · Cruise: **FK006B** (194 files, Kongsberg EM302/EM710, margin ~1.6 km, HR MGDS:20811)

Gridded two ways over the HR footprint and compared:

| mode | wall time | over-footprint comparison |
|---|---|---|
| **raw** (no cleaning) | **352 s** | baseline |
| **clean** (parallel `mbclean` per-file → `mbprocess`) | **1575 s (4.5×)** | identical |

**Comparison (411,307 cells present in both):**
- `% cells changed > 5 m`: **0.0 %**
- `max |Δ depth|`: **0.0 m**
- depth range, fill: **identical** (−2026.2…−1291.2 m; 411,307 filled both)

**Decision: GRID RAW for the full run.** Both directive fallback conditions are met:
1. Cleaning changes the gridded LR **negligibly** (0.0 % cells, 0.0 m) — at LR cell sizes (tens of metres), Gaussian-weighted `mbgrid` averages many soundings per cell, so per-sounding outlier flags wash out.
2. Cleaning is **time-infeasible at scale** — 4.5× slower even with `mbclean` parallelized per-file (`mbprocess` is serial); for the 4,328-file EW0207 this would be hours per cruise.

**Caveat carried:** FK006B is modern EM302/EM710. The few noisy *legacy* cruises in the run (Atlas Hydrosweep EW0207/EW9801/EW9904, SeaBeam) could in principle benefit more from cleaning; raw grids for those are flagged for visual QC scrutiny, and a per-cruise re-clean is available if a grid shows spike artifacts. Default remains raw.
