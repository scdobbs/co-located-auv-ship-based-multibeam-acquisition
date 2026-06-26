"""Per-pair QA stats and report-fragment writer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rioxarray  # noqa: F401
import xarray as xr

from .coregister import CoregResult


@dataclass
class PairQA:
    pair_id: str
    overlap_area_km2: float
    hr_gsd_m: float
    lr_gsd_m: float
    res_ratio: float
    coreg: CoregResult | None
    diff_median_m: float | None
    diff_mad_m: float | None
    diff_p05_m: float | None
    diff_p95_m: float | None
    n_diff_samples: int


def _open(p: Path) -> xr.DataArray:
    da = rioxarray.open_rasterio(p, masked=True)
    if da.ndim == 3 and da.sizes.get("band") == 1:
        da = da.squeeze("band", drop=True)
    return da


def compute(
    *,
    pair_id: str,
    hr_path: Path,
    lr_path: Path,
    overlap_area_km2: float,
    hr_gsd_m: float,
    lr_gsd_m: float,
    coreg: CoregResult | None,
) -> PairQA:
    hr = _open(hr_path)
    lr = _open(lr_path)
    # Sample LR at HR pixel centres for diff statistics
    xs, ys = np.meshgrid(hr.x.values, hr.y.values)
    hr_vals = hr.values
    mask = np.isfinite(hr_vals)
    xs = xs[mask]; ys = ys[mask]; HR = hr_vals[mask]
    if HR.size > 200_000:
        rng = np.random.default_rng(0)
        idx = rng.choice(HR.size, size=200_000, replace=False)
        xs, ys, HR = xs[idx], ys[idx], HR[idx]
    LRv = lr.interp(x=("p", xs), y=("p", ys), method="linear").values
    diff = LRv - HR
    diff = diff[np.isfinite(diff)]
    if diff.size:
        med = float(np.median(diff))
        mad = float(np.median(np.abs(diff - med)))
        p05, p95 = (float(x) for x in np.percentile(diff, [5, 95]))
        return PairQA(
            pair_id=pair_id,
            overlap_area_km2=overlap_area_km2,
            hr_gsd_m=hr_gsd_m,
            lr_gsd_m=lr_gsd_m,
            res_ratio=lr_gsd_m / hr_gsd_m if hr_gsd_m > 0 else float("nan"),
            coreg=coreg,
            diff_median_m=med,
            diff_mad_m=mad,
            diff_p05_m=p05,
            diff_p95_m=p95,
            n_diff_samples=int(diff.size),
        )
    return PairQA(
        pair_id=pair_id,
        overlap_area_km2=overlap_area_km2,
        hr_gsd_m=hr_gsd_m,
        lr_gsd_m=lr_gsd_m,
        res_ratio=lr_gsd_m / hr_gsd_m if hr_gsd_m > 0 else float("nan"),
        coreg=coreg,
        diff_median_m=None,
        diff_mad_m=None,
        diff_p05_m=None,
        diff_p95_m=None,
        n_diff_samples=0,
    )


def render_markdown(qa: PairQA) -> str:
    lines = [
        f"### {qa.pair_id}",
        "",
        f"- Overlap area: **{qa.overlap_area_km2:.3f} km²**",
        f"- HR GSD: {qa.hr_gsd_m:.3f} m, LR GSD: {qa.lr_gsd_m:.3f} m → res ratio ≈ **{qa.res_ratio:.1f}×**",
    ]
    if qa.coreg is not None:
        c = qa.coreg
        lines += [
            f"- Coregistration applied: dx={c.dx_m:+.2f} m, dy={c.dy_m:+.2f} m, dz={c.dz_m:+.2f} m",
            f"  - Pre-correction residual: median={c.pre_residual_median_m:+.2f} m, MAD={c.pre_residual_mad_m:.2f} m",
            f"  - Post-correction residual: median={c.post_residual_median_m:+.2f} m, MAD={c.post_residual_mad_m:.2f} m",
            f"  - Samples: {c.n_samples}",
        ]
    else:
        lines.append("- Coregistration: not required (AUV pre-corrected against ship)")
    if qa.diff_median_m is not None:
        lines += [
            f"- LR−HR over overlap: median={qa.diff_median_m:+.2f} m, "
            f"MAD={qa.diff_mad_m:.2f} m, p05={qa.diff_p05_m:+.2f} m, p95={qa.diff_p95_m:+.2f} m "
            f"(n={qa.n_diff_samples})",
        ]
    return "\n".join(lines) + "\n"
