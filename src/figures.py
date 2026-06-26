"""v1.2.1 §7 figures.

(a) artifact-inspection contact sheet — hillshade + FFT for every
    user-provided HR file, side by side, labeled with filename. Output:
    ``reports/user_hr_artifact_contact_sheet.png`` (single PNG;
    paginates to multiple PNGs only if needed).

(b) master LR-vs-HR figure — one row per final Cal DIG pair: LR hillshade |
    HR hillshade, both clipped to the shared HR∩LR footprint, with a
    shared elevation ramp per row. Output:
    ``reports/cal_dig_master_lr_vs_hr.pdf`` (multi-page) + a single
    contact-sheet PNG. Includes coregistration annotations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import rioxarray  # noqa: F401
import xarray as xr
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import LightSource
from matplotlib.image import imread


log = logging.getLogger(__name__)


# ---------- (a) artifact contact sheet ----------

def build_artifact_contact_sheet(
    qc_dir: Path,
    user_dir: Path,
    out_path: Path,
    cols: int = 2,
    tile_rows_per_page: int = 8,
) -> list[Path]:
    """Pages contain (cols) tiles per row × (tile_rows_per_page) rows. Each
    tile is the hillshade + FFT image for one file, side by side, labeled.
    """
    user_files = sorted(p for p in user_dir.glob("*.tif"))
    pages: list[Path] = []
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n = len(user_files)
    per_page = cols * tile_rows_per_page
    n_pages = max(1, (n + per_page - 1) // per_page)

    for page_idx in range(n_pages):
        chunk = user_files[page_idx * per_page : (page_idx + 1) * per_page]
        n_rows = (len(chunk) + cols - 1) // cols
        # Each "tile" occupies 2 sub-axes (hillshade + FFT).
        fig, axes = plt.subplots(
            n_rows, cols * 2,
            figsize=(cols * 2 * 3.2, n_rows * 3.0),
            squeeze=False,
        )
        for i, fp in enumerate(chunk):
            r = i // cols
            c = (i % cols) * 2
            ax_hs = axes[r][c]
            ax_fft = axes[r][c + 1]
            hs_png = qc_dir / (fp.stem + "_hillshade.png")
            fft_png = qc_dir / (fp.stem + "_fft.png")
            if hs_png.exists():
                ax_hs.imshow(imread(hs_png))
            ax_hs.set_xticks([]); ax_hs.set_yticks([])
            ax_hs.set_title(fp.name, fontsize=7)
            if fft_png.exists():
                ax_fft.imshow(imread(fft_png))
            ax_fft.set_xticks([]); ax_fft.set_yticks([])
            ax_fft.set_title("FFT (flat window)", fontsize=7)
        # Hide unused axes
        for j in range(len(chunk), n_rows * cols):
            r = j // cols
            c = (j % cols) * 2
            axes[r][c].axis("off")
            axes[r][c + 1].axis("off")
        fig.suptitle(
            f"User-provided Cal DIG HR — artifact-inspection contact sheet "
            f"(page {page_idx + 1}/{n_pages})",
            fontsize=11,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        page_path = (
            out_path if n_pages == 1
            else out_path.with_name(out_path.stem + f"_p{page_idx + 1:02d}" + out_path.suffix)
        )
        fig.savefig(page_path, dpi=140)
        plt.close(fig)
        pages.append(page_path)
    return pages


# ---------- (b) master LR-vs-HR figure ----------

def _hillshade_arr(arr: np.ndarray, dx: float, dy: float) -> np.ndarray:
    a = np.where(np.isfinite(arr), arr, np.nanmedian(arr[np.isfinite(arr)]) if np.isfinite(arr).any() else 0.0)
    ls = LightSource(azdeg=315, altdeg=45)
    return ls.hillshade(a, vert_exag=1.0, dx=dx, dy=abs(dy))


def _open(path: Path) -> xr.DataArray:
    da = rioxarray.open_rasterio(path, masked=True)
    if da.ndim == 3 and da.sizes.get("band") == 1:
        da = da.squeeze("band", drop=True)
    return da


@dataclass
class MasterRow:
    pair_id: str
    terrain_class: str
    hr_path: Path
    lr_path: Path
    depth_min: float
    depth_max: float
    coreg_status: str
    horiz_offset_m: float
    vert_offset_m: float
    mad: float | None
    psr: float
    eig_ratio: float
    native_gsd_m: float
    target_gsd_m: float
    res_ratio: float


def _row_from_manifest(row: pd.Series) -> MasterRow | None:
    hr = Path(row["harmonized_path_hr"]) if row["harmonized_path_hr"] else None
    lr = Path(row["harmonized_path_lr"]) if row["harmonized_path_lr"] else None
    if hr is None or lr is None or not hr.exists() or not lr.exists():
        return None
    # Parse MAD from notes
    import re
    m = re.search(r"MAD=([\d.]+) m", row["notes"] or "")
    mad = float(m.group(1)) if m else None
    return MasterRow(
        pair_id=row["pair_id"],
        terrain_class=row.get("terrain_class") or "unknown",
        hr_path=hr, lr_path=lr,
        depth_min=float(row.get("depth_min_m") or 0.0),
        depth_max=float(row.get("depth_max_m") or 0.0),
        coreg_status=row.get("coreg_status") or "needs_review",
        horiz_offset_m=float(row.get("horiz_offset_m") or 0.0),
        vert_offset_m=float(row.get("vert_offset_m") or 0.0),
        mad=mad,
        psr=float(row.get("coreg_peak_psr") or float("nan")),
        eig_ratio=float(row.get("coreg_peak_eig_ratio") or float("nan")),
        native_gsd_m=float(row.get("hr_native_res_m") or 0.0),
        target_gsd_m=2.0,
        res_ratio=float(row.get("res_ratio") or 5.0),
    )


def build_master_lr_vs_hr(
    df: pd.DataFrame,
    out_pdf: Path,
    out_png: Path,
    rows_per_page: int = 6,
) -> tuple[Path, Path]:
    """Generate the master figure. Includes all Cal DIG pairs (skips DISCOL).
    Ordered by terrain class.
    """
    rows: list[MasterRow] = []
    for _, r in df.iterrows():
        if not str(r["pair_id"]).startswith("cal_dig"):
            continue
        if str(r.get("coreg_status", "")) == "reject":
            continue
        mr = _row_from_manifest(r)
        if mr is not None:
            rows.append(mr)
    rows.sort(key=lambda r: (r.terrain_class, r.pair_id))

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    pages: list[plt.Figure] = []
    pdf = PdfPages(out_pdf)
    contact_axes: list[tuple[np.ndarray, np.ndarray, MasterRow]] = []

    try:
        for page_start in range(0, len(rows), rows_per_page):
            chunk = rows[page_start : page_start + rows_per_page]
            fig, axes = plt.subplots(
                len(chunk), 2, figsize=(12, 3 * len(chunk)), squeeze=False,
            )
            for i, mr in enumerate(chunk):
                hr = _open(mr.hr_path); lr = _open(mr.lr_path)
                hr_arr = np.asarray(hr.values, dtype=float)
                lr_arr = np.asarray(lr.values, dtype=float)
                hr_dx = float(abs(hr.rio.resolution()[0]))
                hr_dy = float(abs(hr.rio.resolution()[1]))
                lr_dx = float(abs(lr.rio.resolution()[0]))
                lr_dy = float(abs(lr.rio.resolution()[1]))
                lr_hs = _hillshade_arr(lr_arr, lr_dx, lr_dy)
                hr_hs = _hillshade_arr(hr_arr, hr_dx, hr_dy)
                # Shared elevation ramp per row (over the overlap region; both
                # rasters are already clipped to it)
                finite = np.concatenate([
                    hr_arr[np.isfinite(hr_arr)].ravel(),
                    lr_arr[np.isfinite(lr_arr)].ravel(),
                ])
                if finite.size:
                    vmin, vmax = np.percentile(finite, [2, 98])
                else:
                    vmin, vmax = 0, 1
                lb, bb, rb, tb = hr.rio.bounds()
                extent_hr = (lb, rb, bb, tb)
                lb2, bb2, rb2, tb2 = lr.rio.bounds()
                extent_lr = (lb2, rb2, bb2, tb2)

                axL = axes[i][0]
                axL.imshow(lr_hs, extent=extent_lr, cmap="gray", origin="upper")
                axL.imshow(np.where(np.isfinite(lr_arr), lr_arr, np.nan),
                           extent=extent_lr, cmap="cividis", origin="upper",
                           alpha=0.45, vmin=vmin, vmax=vmax)
                axL.set_title(f"LR @ 10 m", fontsize=9)
                axL.set_xticks([]); axL.set_yticks([])
                axL.set_aspect("equal")

                axR = axes[i][1]
                axR.imshow(hr_hs, extent=extent_hr, cmap="gray", origin="upper")
                axR.imshow(np.where(np.isfinite(hr_arr), hr_arr, np.nan),
                           extent=extent_hr, cmap="cividis", origin="upper",
                           alpha=0.45, vmin=vmin, vmax=vmax)
                axR.set_title(f"HR @ {mr.target_gsd_m:.0f} m (native {mr.native_gsd_m:.1f} m)", fontsize=9)
                axR.set_xticks([]); axR.set_yticks([])
                axR.set_aspect("equal")

                # Row caption to the left
                caption = (
                    f"{mr.pair_id}\n"
                    f"terrain: {mr.terrain_class}\n"
                    f"depth: {mr.depth_min:.0f} – {mr.depth_max:.0f} m\n"
                    f"ratio: {mr.res_ratio:.1f}×\n"
                    f"coreg: h={mr.horiz_offset_m:.1f} v={mr.vert_offset_m:.2f}m "
                    + (f"MAD={mr.mad:.2f}m " if mr.mad is not None else "")
                    + f"PSR={mr.psr:.1f} eig={mr.eig_ratio:.1f}\n"
                    f"status: {mr.coreg_status}"
                )
                axL.text(
                    -0.08, 0.5, caption, transform=axL.transAxes,
                    ha="right", va="center", fontsize=7,
                )
                contact_axes.append((lr_hs, hr_hs, mr))

            fig.suptitle(f"Cal DIG master LR-vs-HR — page {1 + page_start // rows_per_page}",
                         fontsize=11)
            fig.tight_layout(rect=(0.1, 0, 1, 0.97))
            pdf.savefig(fig)
            pages.append(fig)
    finally:
        pdf.close()

    # Single contact PNG: lay everything out in a tall figure
    n = len(rows)
    fig = plt.figure(figsize=(12, 3 * n))
    for i, (lr_hs, hr_hs, mr) in enumerate(contact_axes):
        ax = fig.add_subplot(n, 2, 2 * i + 1)
        ax.imshow(lr_hs, cmap="gray", origin="upper")
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(f"{mr.pair_id}  —  LR", fontsize=8)
        ax = fig.add_subplot(n, 2, 2 * i + 2)
        ax.imshow(hr_hs, cmap="gray", origin="upper")
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(f"{mr.pair_id}  —  HR (status: {mr.coreg_status})", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_png, dpi=120)
    plt.close(fig)

    for f in pages:
        plt.close(f)
    return out_pdf, out_png
