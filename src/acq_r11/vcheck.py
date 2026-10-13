"""ACQ-R11 §1 — the vertical-consistency statistic (automated replacement for the development QC-figure / QGIS review
of gross HR-ship vertical mismatch and of ship line-to-line inconsistency; ACQ-R10 H-1, Steve's ruling option A).

Fixed before any calibration value was computed (ACQ-R11 §1), on the harmonized pair AFTER co-registration and the
rigid dz (hr.tif as chain_p5.harmonize writes it):
  1. on the harmonized LR grid (lr.tif), the HR field block-averaged to the LR cells with the chain's averaging kernel
     (rasterio reproject, Resampling.average, as harmonize_new.lr_real_on_hr moves masks between the two grids), and the
     joint-valid mask carried to the LR cells the same way: an LR cell is joint-valid when >= 0.5 of the joint_valid.tif
     cells inside it are joint-valid (the chain's majority rule), and both HR_lr and LR are finite there;
  2. r = HR_lr - LR on joint-valid LR cells, m = median(r);
  3. V95 = 95th percentile of |r - m| (metres); V95_rel = V95 / |median LR over the joint-valid LR cells|.
The gate is V95_rel <= common_p5.VCHECK_T.

Blindness: `statistic` returns numbers to its caller only.  The Phase 5 chain calls `gate`, which keeps the boolean
and drops every number; nothing here writes, prints or logs.  Only the development calibration (src/acq_r11/) reports
values, and only for development and known-bad pairs.
"""
from __future__ import annotations

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling

FILL = -9999.0
JOINT_FRAC = 0.5


def _read_nan(ds) -> np.ndarray:
    a = ds.read(1, masked=True).astype("float64").filled(np.nan)
    a[np.isclose(a, FILL, atol=1e-3)] = np.nan
    return a


def statistic(hr_tif, lr_tif, joint_tif) -> dict:
    """{'n': joint-valid LR cells, 'v95': metres, 'v95_rel': dimensionless} or {'n': 0} when no cell is joint-valid."""
    with rasterio.open(str(lr_tif)) as ds:
        lr = _read_nan(ds); l_tr, l_crs, shape = ds.transform, ds.crs, (ds.height, ds.width)
    hr_lr = np.full(shape, np.nan, "float64")
    with rasterio.open(str(hr_tif)) as ds:
        hr = _read_nan(ds)
        reproject(hr, hr_lr, src_transform=ds.transform, src_crs=ds.crs, dst_transform=l_tr, dst_crs=l_crs,
                  src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.average)
    del hr
    frac = np.zeros(shape, "float32")
    with rasterio.open(str(joint_tif)) as ds:
        j = (ds.read(1) == 1).astype("float32")
        reproject(j, frac, src_transform=ds.transform, src_crs=ds.crs, dst_transform=l_tr, dst_crs=l_crs,
                  src_nodata=None, dst_nodata=0.0, resampling=Resampling.average)
    del j
    ok = (frac >= JOINT_FRAC) & np.isfinite(hr_lr) & np.isfinite(lr)
    n = int(ok.sum())
    if n == 0:
        return {"n": 0}
    r = hr_lr[ok] - lr[ok]
    m = float(np.median(r))
    v95 = float(np.percentile(np.abs(r - m), 95))
    lr_med = abs(float(np.median(lr[ok])))
    return {"n": n, "v95": v95, "v95_rel": (v95 / lr_med) if lr_med > 0 else float("inf"), "lr_med_abs": lr_med}


def gate(hr_tif, lr_tif, joint_tif, threshold: float) -> dict:
    """The Phase 5 gate: only booleans leave this function (no number of the statistic is returned)."""
    try:
        s = statistic(hr_tif, lr_tif, joint_tif)
    except Exception as e:                                   # message only; no value of the statistic exists yet
        return {"vertical_consistent": False, "computed": False, "why": f"not computable: {type(e).__name__}"}
    if not s.get("n"):
        return {"vertical_consistent": False, "computed": False, "why": "not computable: no joint-valid LR cell"}
    ok = bool(np.isfinite(s["v95_rel"]) and s["v95_rel"] <= threshold)
    del s
    return {"vertical_consistent": ok, "computed": True, "why": "" if ok else "above the calibrated bound"}
