"""Co-registration QA per v1.1 addendum.

Replaces the binary MAD gate with a morphology-aware peak-quality check:
    * gradient-magnitude NCC surface around the solved offset
    * peak-to-sidelobe ratio (PSR)
    * Hessian eigenvalue ratio (anisotropy / along-axis ridge detector)
    * peak agreement with the solved offset
    * hillshade-overlay PNG artifact per sub-pair

`evaluate(...)` runs all of the above for one already-harmonized sub-pair.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import rioxarray  # noqa: F401
import scipy.ndimage as ndi
import xarray as xr
from matplotlib.colors import LightSource
from rasterio.enums import Resampling


log = logging.getLogger(__name__)


@dataclass
class PeakStats:
    psr: float                # peak-to-sidelobe ratio
    eig_ratio: float          # larger / smaller |eigenvalue| of Hessian at peak
    peak_dx_m: float          # offset of NCC max relative to centre (i.e. relative to solved alignment)
    peak_dy_m: float
    peak_agrees: bool         # peak within ~1 LR cell of centre (0,0)
    ridge_orientation_deg: float | None  # direction of soft Hessian eigenvector when ridge-like


@dataclass
class QCResult:
    horiz_offset_m: float
    vert_offset_m: float
    peak: PeakStats
    overlay_path: Path
    ncc_surface_shape: tuple[int, int]
    ncc_max: float


# ----- raster helpers -----

def _open(path: Path) -> xr.DataArray:
    da = rioxarray.open_rasterio(path, masked=True)
    if da.ndim == 3 and da.sizes.get("band") == 1:
        da = da.squeeze("band", drop=True)
    return da


def _read_at_resolution(path: Path, target_lr_path: Path) -> xr.DataArray:
    """Read an HR raster directly at the LR's grid via ``rasterio`` windowed
    decimation (``out_shape`` + average resampling). Avoids materializing the
    full HR — critical for the 393M-pixel Transect tile which OOMs under
    rioxarray ``reproject_match``.
    """
    with rasterio.open(target_lr_path) as lr_ds:
        dst_shape = (lr_ds.height, lr_ds.width)
        dst_transform = lr_ds.transform
        dst_crs = lr_ds.crs
    with rasterio.open(path) as src:
        from rasterio.warp import reproject
        out = np.full(dst_shape, np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=np.nan,
            resampling=Resampling.average,
            num_threads=2,
        )
    # Pack into xarray with the LR coords for downstream use.
    with rasterio.open(target_lr_path) as lr_ds:
        xs = np.arange(lr_ds.width) * lr_ds.transform.a + lr_ds.transform.c + lr_ds.transform.a / 2
        ys = np.arange(lr_ds.height) * lr_ds.transform.e + lr_ds.transform.f + lr_ds.transform.e / 2
    da = xr.DataArray(out, dims=("y", "x"), coords={"y": ys, "x": xs})
    da.rio.write_crs(dst_crs, inplace=True)
    da.rio.write_transform(dst_transform, inplace=True)
    return da


def _aggregate_to(hr: xr.DataArray, lr: xr.DataArray) -> xr.DataArray:
    """Aggregate HR to LR's grid (mean), preserving NaN where no HR samples.

    Deprecated: prefer ``_read_at_resolution`` for large HR rasters.
    """
    return hr.rio.reproject_match(lr, resampling=Resampling.average)


# ----- morphology -----

def gradient_magnitude(arr: np.ndarray) -> np.ndarray:
    """Sobel gradient magnitude with NaN-safe behaviour."""
    a = np.where(np.isfinite(arr), arr, 0.0)
    valid = np.isfinite(arr)
    gx = ndi.sobel(a, axis=1)
    gy = ndi.sobel(a, axis=0)
    g = np.hypot(gx, gy)
    # Anywhere the original array was NaN OR neighbours its NaN halo we don't
    # trust the gradient. Erode the valid mask by 1 px.
    valid_strict = ndi.binary_erosion(valid, iterations=1)
    g[~valid_strict] = np.nan
    return g


def hillshade_from_dem(dem: np.ndarray, dx_m: float, dy_m: float,
                       azimuth: float = 315.0, altitude: float = 45.0) -> np.ndarray:
    """Matplotlib LightSource expects (Y, X) DEM oriented north-up. We pass
    a dx/dy that account for the raster vertical units (DEM = depth m,
    negative = deeper). LightSource normalises internally.
    """
    ls = LightSource(azdeg=azimuth, altdeg=altitude)
    out = ls.hillshade(dem, vert_exag=1.0, dx=dx_m, dy=abs(dy_m))
    return out


# ----- NCC surface around the solved offset -----

def _ncc_at_offset(a: np.ndarray, b: np.ndarray, dx_px: float, dy_px: float) -> float:
    """NCC of a (shifted by dx_px, dy_px) against b. Handles NaN by masking.

    Both inputs are gradient fields on the same grid. Shift is sub-pixel via
    bilinear interpolation. Pixel directions: dy_px row-shift, dx_px col-shift.
    """
    shifted = ndi.shift(np.where(np.isfinite(a), a, 0.0),
                        (dy_px, dx_px), order=1, cval=0.0,
                        mode="constant")
    valid_shifted = ndi.shift(np.isfinite(a).astype(np.float32),
                              (dy_px, dx_px), order=1, cval=0.0,
                              mode="constant") > 0.5
    mask = valid_shifted & np.isfinite(b)
    if mask.sum() < 100:
        return np.nan
    a_v = shifted[mask].astype(np.float64)
    b_v = b[mask].astype(np.float64)
    a_v -= a_v.mean(); b_v -= b_v.mean()
    den = a_v.std() * b_v.std()
    if den < 1e-12:
        return np.nan
    return float(np.mean(a_v * b_v) / den)


def ncc_surface_around_zero(
    hr_grad: np.ndarray,
    lr_grad: np.ndarray,
    pix_m: float,
    search_radius_m: float,
    step_m: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """NCC values for a grid of (dx, dy) test offsets centred at (0, 0)
    (i.e. centred at the already-applied solved offset). Returns the surface
    plus the offsets array used for one axis.

    Default step is ``pix_m / 4`` capped between 1 m and 4 m. Picking a step
    much finer than the LR pixel size lets us fit a 2-D Hessian even when
    the LR grid is coarse (e.g. DISCOL at 38 m → 3 m step → ~21x21 surface).
    """
    if step_m is None:
        step_m = max(1.0, min(4.0, pix_m / 4.0))
    rs = int(round(search_radius_m / step_m))
    offsets = np.arange(-rs, rs + 1) * step_m
    n = len(offsets)
    s = np.full((n, n), np.nan, dtype=np.float32)
    for i, oy in enumerate(offsets):
        for j, ox in enumerate(offsets):
            s[i, j] = _ncc_at_offset(hr_grad, lr_grad, ox / pix_m, oy / pix_m)
    return s, offsets


# ----- peak analysis -----

def _fit_hessian_2x2(z: np.ndarray) -> np.ndarray:
    """Fit a 2-D quadratic z = a + b*x + c*y + d*x^2 + e*y^2 + f*x*y to a
    small patch and return the Hessian [[2d, f], [f, 2e]]."""
    h, w = z.shape
    xs = np.arange(w) - w // 2
    ys = np.arange(h) - h // 2
    X, Y = np.meshgrid(xs, ys)
    finite = np.isfinite(z)
    A = np.column_stack([
        np.ones(z.size), X.ravel(), Y.ravel(),
        (X**2).ravel(), (Y**2).ravel(), (X * Y).ravel(),
    ])
    b = z.ravel()
    A = A[finite.ravel()]; b = b[finite.ravel()]
    if A.shape[0] < 6:
        return np.array([[np.nan, np.nan], [np.nan, np.nan]])
    coef, *_ = np.linalg.lstsq(A, b, rcond=None)
    _, _, _, d, e, f = coef
    return np.array([[2 * d, f], [f, 2 * e]])


def analyse_peak(ncc: np.ndarray, offsets: np.ndarray,
                 lr_cell_m: float,
                 patch_size: int = 5) -> PeakStats:
    """PSR + Hessian eig ratio at the NCC max, plus peak-agreement check."""
    finite = np.isfinite(ncc)
    if not finite.any():
        return PeakStats(np.nan, np.nan, 0.0, 0.0, False, None)
    masked = np.where(finite, ncc, -np.inf)
    pi, pj = np.unravel_index(np.argmax(masked), masked.shape)
    peak = float(masked[pi, pj])

    # PSR: peak / std of NCC outside ~1 LR cell radius around the peak.
    # Convert the LR cell size to NCC-grid cells via the local offset step.
    step_m = float(offsets[1] - offsets[0]) if len(offsets) >= 2 else lr_cell_m
    excl_cells = max(2, int(round(lr_cell_m / step_m)))
    H, W = ncc.shape
    yy, xx = np.indices(ncc.shape)
    r = np.hypot(yy - pi, xx - pj)
    side = ncc[(r > excl_cells) & finite]
    if side.size < 10:
        psr = np.nan
    else:
        sigma = float(np.std(side))
        psr = peak / sigma if sigma > 1e-12 else np.nan

    # Peak offsets in metres (relative to the centre of the surface)
    centre_i, centre_j = H // 2, W // 2
    peak_dy = float(offsets[pi]) if pi < len(offsets) else 0.0
    peak_dx = float(offsets[pj]) if pj < len(offsets) else 0.0
    peak_agrees = (abs(peak_dy) <= lr_cell_m) and (abs(peak_dx) <= lr_cell_m)

    # Hessian at peak: fit a quadratic on a patch and read off curvature.
    half = patch_size // 2
    i0, i1 = max(0, pi - half), min(H, pi + half + 1)
    j0, j1 = max(0, pj - half), min(W, pj + half + 1)
    patch = ncc[i0:i1, j0:j1]
    eig_ratio = np.nan
    ridge_orient = None
    if patch.size >= 9 and np.isfinite(patch).sum() >= 6:
        Hess = _fit_hessian_2x2(patch)
        if np.isfinite(Hess).all():
            eigs, vecs = np.linalg.eigh(Hess)
            # We want a peak (both eigs < 0). Use magnitudes, larger/smaller.
            mags = np.abs(eigs)
            big = mags.max(); small = mags.min()
            if small > 1e-12:
                eig_ratio = float(big / small)
            else:
                eig_ratio = float("inf")
            # ridge orientation: eigenvector of the SMALLER-magnitude eigenvalue
            # (the soft axis of the peak — direction the AUV can slide)
            soft_idx = int(np.argmin(mags))
            vx, vy = vecs[:, soft_idx]
            ridge_orient = float(np.degrees(np.arctan2(vy, vx)))

    return PeakStats(
        psr=float(psr) if psr is not None else np.nan,
        eig_ratio=eig_ratio,
        peak_dx_m=peak_dx,
        peak_dy_m=peak_dy,
        peak_agrees=bool(peak_agrees),
        ridge_orientation_deg=ridge_orient,
    )


# ----- overlay PNG -----

def render_overlay_png(
    hr: xr.DataArray,
    lr: xr.DataArray,
    out_path: Path,
    sub_pair_id: str,
    horiz_offset_m: float,
    vert_offset_m: float,
    psr: float,
    eig_ratio: float,
    peak_agrees: bool,
    coreg_status: str,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # HR is at native (typically 1 m); LR at 10 m. Both clipped to overlap.
    # We want a hillshade view that lets a human read alignment of edges.
    hr_arr = np.asarray(hr.values, dtype=float)
    lr_arr = np.asarray(lr.values, dtype=float)
    hr_dx = float(abs(hr.rio.resolution()[0]))
    hr_dy = float(abs(hr.rio.resolution()[1]))
    lr_dx = float(abs(lr.rio.resolution()[0]))
    lr_dy = float(abs(lr.rio.resolution()[1]))

    hr_hs = hillshade_from_dem(np.where(np.isfinite(hr_arr), hr_arr, np.nanmedian(hr_arr)),
                               dx_m=hr_dx, dy_m=hr_dy)
    lr_hs = hillshade_from_dem(np.where(np.isfinite(lr_arr), lr_arr, np.nanmedian(lr_arr)),
                               dx_m=lr_dx, dy_m=lr_dy)

    fig, ax = plt.subplots(figsize=(9, 7))
    lb, bb, rb, tb = hr.rio.bounds()
    lb2, bb2, rb2, tb2 = lr.rio.bounds()
    extent_hr = (lb, rb, bb, tb)
    extent_lr = (lb2, rb2, bb2, tb2)
    # Ship LR first (bottom layer)
    ax.imshow(lr_hs, extent=extent_lr, cmap="gray", origin="upper", alpha=1.0)
    # AUV HR on top, semi-transparent, mask out NaN
    hr_alpha = np.where(np.isfinite(hr_arr), 0.55, 0.0)
    ax.imshow(hr_hs, extent=extent_hr, cmap="gray", origin="upper", alpha=hr_alpha)
    ax.set_title(
        f"{sub_pair_id}\n"
        f"applied horiz={horiz_offset_m:.1f} m, vert={vert_offset_m:.2f} m  "
        f"PSR={psr:.2f}  eig_ratio={eig_ratio:.2f}  peak_agrees={peak_agrees}  "
        f"status={coreg_status}",
        fontsize=9,
    )
    ax.set_xlabel("Easting (m)")
    ax.set_ylabel("Northing (m)")
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def _render_ncc_heatmap(ncc: np.ndarray, offsets: np.ndarray, peak: PeakStats,
                        out_path: Path, sub_pair_id: str) -> None:
    """Diagnostic heatmap of the NCC surface, peak marked."""
    fig, ax = plt.subplots(figsize=(5, 4.5))
    extent = (offsets[0], offsets[-1], offsets[-1], offsets[0])
    im = ax.imshow(ncc, extent=extent, cmap="viridis", origin="upper")
    ax.axhline(0, color="w", lw=0.5, alpha=0.5)
    ax.axvline(0, color="w", lw=0.5, alpha=0.5)
    ax.plot(peak.peak_dx_m, peak.peak_dy_m, "rx", ms=10, mew=2)
    ax.set_xlabel("dx test (m)")
    ax.set_ylabel("dy test (m)")
    ax.set_title(
        f"{sub_pair_id}\nNCC of gradient fields  "
        f"PSR={peak.psr:.2f}  eig_ratio={peak.eig_ratio:.2f}  agrees={peak.peak_agrees}",
        fontsize=9,
    )
    fig.colorbar(im, ax=ax, label="NCC")
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ----- top-level entrypoint -----

def evaluate(
    *,
    sub_pair_id: str,
    hr_path: Path,
    lr_path: Path,
    out_overlay_path: Path,
    applied_dx_m: float,
    applied_dy_m: float,
    applied_dz_m: float,
    usbl_bound_m: float,
    mad_m: float | None,
    mad_threshold_m: float,
    min_peak_sharpness: float | None,
    peak_anisotropy_max: float | None,
) -> tuple[QCResult, str]:
    """Returns (QCResult, coreg_status).

    coreg_status follows the v1.1 §A.4 taxonomy. When the two empirical
    thresholds are unset we cannot auto_pass; the row is `needs_review`.
    """
    lr = _open(lr_path)
    # Bring HR onto LR's grid via streamed windowed read (avoids loading the
    # full HR into memory — needed for the multi-million-pixel Transect tile).
    hr_on_lr = _read_at_resolution(hr_path, lr_path)

    hr_grad = gradient_magnitude(np.asarray(hr_on_lr.values, dtype=float))
    lr_grad = gradient_magnitude(np.asarray(lr.values, dtype=float))
    lr_cell_m = float(abs(lr.rio.resolution()[0]))

    ncc, offsets = ncc_surface_around_zero(
        hr_grad, lr_grad,
        pix_m=lr_cell_m,
        search_radius_m=usbl_bound_m,
    )
    peak = analyse_peak(ncc, offsets, lr_cell_m=lr_cell_m)
    ncc_max = float(np.nanmax(ncc)) if np.isfinite(ncc).any() else float("nan")

    horiz_offset_m = float(np.hypot(applied_dx_m, applied_dy_m))
    vert_offset_m = float(abs(applied_dz_m))

    # Decide status
    if min_peak_sharpness is None or peak_anisotropy_max is None:
        status = "needs_review"  # cannot auto_pass without calibrated thresholds
    elif horiz_offset_m > usbl_bound_m:
        status = "needs_review"
    elif not peak.peak_agrees:
        status = "needs_review"
    elif not np.isfinite(peak.psr) or peak.psr < min_peak_sharpness:
        status = "needs_review"
    elif not np.isfinite(peak.eig_ratio) or peak.eig_ratio > peak_anisotropy_max:
        status = "needs_review"
    elif mad_m is not None and mad_m > mad_threshold_m:
        status = "needs_review"
    else:
        status = "auto_pass"

    # Render overlay using the LR-resolution HR (already loaded) — keeps the
    # PNG resolution at the LR scale and avoids touching the full HR raster
    # again. For sub-pairs whose HR pixel is much finer than LR this is what
    # the human reviewer wants anyway (it's the alignment of LR-scale edges).
    render_overlay_png(
        hr_on_lr, lr, out_overlay_path, sub_pair_id,
        horiz_offset_m=horiz_offset_m, vert_offset_m=vert_offset_m,
        psr=peak.psr, eig_ratio=peak.eig_ratio,
        peak_agrees=peak.peak_agrees, coreg_status=status,
    )
    # Also dump the NCC surface as a heatmap next to the overlay for review.
    _render_ncc_heatmap(
        ncc, offsets, peak,
        out_overlay_path.with_name(out_overlay_path.stem + "_ncc.png"),
        sub_pair_id,
    )

    return (
        QCResult(
            horiz_offset_m=horiz_offset_m,
            vert_offset_m=vert_offset_m,
            peak=peak,
            overlay_path=out_overlay_path,
            ncc_surface_shape=ncc.shape,
            ncc_max=ncc_max,
        ),
        status,
    )
