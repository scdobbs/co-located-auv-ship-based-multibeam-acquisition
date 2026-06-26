"""Rigid xyz coregistration of AUV (HR) to ship (LR) over the overlap.

Strategy: sample the LR raster at the HR pixel centres, compute (LR - HR)
residuals, take the robust median as dz, and use a coarse 2-D translation
search to find (dx, dy) that minimises MAD of residuals. This is sufficient
for the meter-scale offsets the Cal DIG release expects.

Per §7 (acceptance_threshold_m), we report the post-correction residual; the
caller decides accept/reject.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rioxarray  # noqa: F401
import xarray as xr
from rasterio.enums import Resampling


log = logging.getLogger(__name__)


@dataclass
class CoregResult:
    dx_m: float
    dy_m: float
    dz_m: float
    pre_residual_median_m: float
    pre_residual_mad_m: float
    post_residual_median_m: float
    post_residual_mad_m: float
    n_samples: int


def _sample(lr: xr.DataArray, hr_xs: np.ndarray, hr_ys: np.ndarray) -> np.ndarray:
    """Bilinear sample of LR at (x, y) coordinates."""
    sampled = lr.interp(x=("points", hr_xs), y=("points", hr_ys), method="linear")
    return np.asarray(sampled.values, dtype=float)


def _prepare_hr_sample(hr: xr.DataArray, n_max: int = 80_000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Subsample HR once and return (xs, ys, hr_values) for valid pixels.

    Avoids the full-extent meshgrid that triggered an OOM on the 393M-pixel
    Transect601060m tile under a 16 GB sbatch. We pull valid (row, col)
    indices from a single mask, subsample to n_max, then resolve coordinates
    from the 1-D x/y axes — never building a 2-D coordinate array.
    """
    arr = np.asarray(hr.values)
    mask = np.isfinite(arr)
    n_valid = int(mask.sum())
    if n_valid == 0:
        empty = np.array([], dtype=float)
        return empty, empty, empty
    rows, cols = np.where(mask)
    del mask
    if rows.size > n_max:
        idx = np.random.default_rng(0).choice(rows.size, size=n_max, replace=False)
        rows, cols = rows[idx], cols[idx]
    xs_axis = hr.x.values
    ys_axis = hr.y.values
    xs = xs_axis[cols]
    ys = ys_axis[rows]
    hr_vals = arr[rows, cols].astype(float)
    return xs, ys, hr_vals


def _residuals(
    xs: np.ndarray,
    ys: np.ndarray,
    hr_vals: np.ndarray,
    lr: xr.DataArray,
    dx: float,
    dy: float,
) -> np.ndarray:
    if xs.size == 0:
        return np.array([])
    lr_vals = _sample(lr, xs + dx, ys + dy)
    diff = lr_vals - hr_vals
    return diff[np.isfinite(diff)]


def _mad(x: np.ndarray) -> float:
    return float(np.median(np.abs(x - np.median(x))))


def estimate_rigid_xyz(
    hr: xr.DataArray,
    lr: xr.DataArray,
    *,
    search_radius_m: float = 30.0,
    coarse_step_m: float | None = None,
    fine_step_m: float | None = None,
    n_max_samples: int = 80_000,
) -> CoregResult:
    if str(hr.rio.crs) != str(lr.rio.crs):
        raise ValueError("HR and LR must share a CRS before coregistration")

    hr_gsd = float(abs(hr.rio.resolution()[0]))
    coarse = coarse_step_m or max(hr_gsd * 4, 2.0)
    fine = fine_step_m or max(hr_gsd, 0.5)

    # Sample HR once; the search varies only (dx, dy) into LR.
    xs, ys, hr_vals = _prepare_hr_sample(hr, n_max=n_max_samples)

    base = _residuals(xs, ys, hr_vals, lr, 0.0, 0.0)
    if base.size < 100:
        raise RuntimeError(f"coregistration has only {base.size} valid samples")
    pre_med = float(np.median(base))
    pre_mad = _mad(base)

    def score(dx: float, dy: float) -> tuple[float, float, int]:
        r = _residuals(xs, ys, hr_vals, lr, dx, dy)
        if r.size == 0:
            return (np.inf, np.inf, 0)
        return (_mad(r - np.median(r)), float(np.median(r)), int(r.size))

    coarse_grid = np.arange(-search_radius_m, search_radius_m + coarse, coarse)
    best = (pre_mad, 0.0, 0.0, pre_med)
    for dx in coarse_grid:
        for dy in coarse_grid:
            mad, med, _ = score(dx, dy)
            if mad < best[0]:
                best = (mad, float(dx), float(dy), med)

    cx, cy = best[1], best[2]
    fine_grid = np.arange(-coarse, coarse + fine, fine)
    for dx in fine_grid:
        for dy in fine_grid:
            mad, med, _ = score(cx + dx, cy + dy)
            if mad < best[0]:
                best = (mad, float(cx + dx), float(cy + dy), med)

    final_dx, final_dy = best[1], best[2]
    post = _residuals(xs, ys, hr_vals, lr, final_dx, final_dy)
    dz = float(np.median(post))
    post_centred = post - dz
    return CoregResult(
        dx_m=final_dx,
        dy_m=final_dy,
        dz_m=dz,
        pre_residual_median_m=pre_med,
        pre_residual_mad_m=pre_mad,
        post_residual_median_m=float(np.median(post_centred)),
        post_residual_mad_m=_mad(post_centred),
        n_samples=int(post.size),
    )


def apply_xyz(da: xr.DataArray, dx_m: float, dy_m: float, dz_m: float) -> xr.DataArray:
    """Translate the raster horizontally and shift values by dz."""
    out = da.assign_coords(x=da.x + dx_m, y=da.y + dy_m)
    out = out + dz_m
    # rioxarray loses CRS on arithmetic; rewrite it.
    out.rio.write_crs(da.rio.crs, inplace=True)
    nodata = da.rio.nodata
    if nodata is not None:
        out.rio.write_nodata(nodata, inplace=True)
    return out
