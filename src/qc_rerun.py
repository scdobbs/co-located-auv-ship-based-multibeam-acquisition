"""v1.1 addendum re-run: morphology-aware coregistration QA over the
already-harmonized Tier-1 output. No re-download, no re-solve.

Walks every manifest row, parses the applied (dx, dy, dz) from the notes
(DISCOL = (0, 0, 0); Cal DIG sub-pairs from the prior coreg block), runs
src.qc.evaluate, and upserts the row with the new columns populated.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import qc
from .config import Config
from .manifest import COLUMNS, ManifestRow, load as load_manifest, upsert


log = logging.getLogger(__name__)


_COREG_RE = re.compile(
    r"Coreg: dx=([+-][\d.]+) m, dy=([+-][\d.]+) m, dz=([+-][\d.]+) m;\s*"
    r"post-residual MAD=([\d.]+) m"
)


@dataclass
class RowResult:
    pair_id: str
    coreg_status: str
    horiz_offset_m: float
    vert_offset_m: float
    psr: float
    eig_ratio: float
    peak_agrees: bool
    peak_dx_m: float
    peak_dy_m: float
    ridge_orientation_deg: float | None
    overlay_path: Path
    ncc_max: float


def _extract_applied(notes: str) -> tuple[float, float, float, float | None]:
    """Return (dx, dy, dz, mad) parsed from the notes; defaults to zeros."""
    m = _COREG_RE.search(notes or "")
    if not m:
        return (0.0, 0.0, 0.0, None)
    dx, dy, dz, mad = m.groups()
    return (float(dx), float(dy), float(dz), float(mad))


def _row_to_kwargs(row: pd.Series) -> dict:
    """Re-pack a manifest row dict for ManifestRow construction. Pulls all
    declared dataclass fields out of the parquet row, ignoring extras."""
    return {
        "pair_id": row["pair_id"],
        "site_name": row["site_name"], "region": row["region"],
        "cruise_id": row["cruise_id"], "vessel": row["vessel"],
        "hr_platform": row["hr_platform"], "hr_sonar": row["hr_sonar"],
        "hr_doi": row["hr_doi"], "hr_native_res_m": float(row["hr_native_res_m"]),
        "lr_platform": row["lr_platform"], "lr_sonar": row["lr_sonar"],
        "lr_doi": row["lr_doi"], "lr_native_res_m": float(row["lr_native_res_m"]),
        "res_ratio": float(row["res_ratio"]),
        "depth_min_m": float(row["depth_min_m"]),
        "depth_max_m": float(row["depth_max_m"]),
        "terrain_class": row["terrain_class"],
        "native_crs_hr": row["native_crs_hr"], "native_crs_lr": row["native_crs_lr"],
        "target_crs": row["target_crs"],
        "vertical_datum": row["vertical_datum"],
        "footprint_wkt": row["footprint_wkt"],
        "license": row["license"],
        "acquisition_date": row["acquisition_date"],
        "verification_status": row["verification_status"],
        "raw_path_hr": row["raw_path_hr"], "raw_path_lr": row["raw_path_lr"],
        "harmonized_path_hr": row["harmonized_path_hr"],
        "harmonized_path_lr": row["harmonized_path_lr"],
        "checksum_hr": row["checksum_hr"], "checksum_lr": row["checksum_lr"],
        "notes": row["notes"],
    }


def rerun(cfg: Config) -> list[RowResult]:
    df = load_manifest()
    if df.empty:
        log.warning("manifest is empty; nothing to rerun")
        return []

    usbl = float(cfg.coregistration["usbl_bound_m"])
    mad_thr = float(cfg.coregistration["acceptance_threshold_m"])
    min_psr = cfg.coregistration.get("min_peak_sharpness")
    max_eig = cfg.coregistration.get("peak_anisotropy_max")

    results: list[RowResult] = []
    for _, row in df.iterrows():
        pair_id = row["pair_id"]
        hr_path = Path(row["harmonized_path_hr"])
        lr_path = Path(row["harmonized_path_lr"])
        if not (hr_path.exists() and lr_path.exists()):
            log.warning("[%s] missing harmonized rasters; skipping", pair_id)
            continue

        dx, dy, dz, applied_mad = _extract_applied(row["notes"])
        # DISCOL has no coreg block; treat the sub-pair as evaluated at the
        # upstream-corrected position (0, 0, 0).
        overlay_dir = hr_path.parent / "qc"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        overlay_path = overlay_dir / f"{pair_id}_overlay.png"

        log.info("[%s] evaluating", pair_id)
        result, status = qc.evaluate(
            sub_pair_id=pair_id,
            hr_path=hr_path, lr_path=lr_path,
            out_overlay_path=overlay_path,
            applied_dx_m=dx, applied_dy_m=dy, applied_dz_m=dz,
            usbl_bound_m=usbl,
            mad_m=applied_mad,
            mad_threshold_m=mad_thr,
            min_peak_sharpness=min_psr,
            peak_anisotropy_max=max_eig,
        )

        # Build the augmented manifest row
        kwargs = _row_to_kwargs(row)
        notes = row["notes"] or ""
        # Append ridge orientation if the peak was anisotropic enough to record
        new_notes = notes
        if result.peak.ridge_orientation_deg is not None and np.isfinite(result.peak.eig_ratio) and result.peak.eig_ratio > 5:
            new_notes = f"{notes} NCC peak ridge orient ~{result.peak.ridge_orientation_deg:+.0f} deg (eig_ratio={result.peak.eig_ratio:.1f}).".strip()
        kwargs["notes"] = new_notes
        kwargs["horiz_offset_m"] = result.horiz_offset_m
        kwargs["vert_offset_m"] = result.vert_offset_m
        kwargs["coreg_peak_psr"] = result.peak.psr
        kwargs["coreg_peak_eig_ratio"] = result.peak.eig_ratio
        kwargs["coreg_peak_agrees"] = result.peak.peak_agrees
        kwargs["coreg_status"] = status
        kwargs["qc_artifact_path"] = str(overlay_path)
        upsert(ManifestRow(**kwargs))

        results.append(RowResult(
            pair_id=pair_id, coreg_status=status,
            horiz_offset_m=result.horiz_offset_m,
            vert_offset_m=result.vert_offset_m,
            psr=result.peak.psr, eig_ratio=result.peak.eig_ratio,
            peak_agrees=result.peak.peak_agrees,
            peak_dx_m=result.peak.peak_dx_m, peak_dy_m=result.peak.peak_dy_m,
            ridge_orientation_deg=result.peak.ridge_orientation_deg,
            overlay_path=overlay_path,
            ncc_max=result.ncc_max,
        ))

    return results
