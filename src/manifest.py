"""Manifest (pairs.parquet) schema + idempotent upsert."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


MANIFEST_PATH_DEFAULT = Path(__file__).resolve().parent.parent / "manifest" / "pairs.parquet"


COLUMNS = [
    "pair_id", "site_name", "region", "cruise_id", "vessel",
    "hr_platform", "hr_sonar", "hr_doi", "hr_native_res_m",
    "lr_platform", "lr_sonar", "lr_doi", "lr_native_res_m",
    "res_ratio", "depth_min_m", "depth_max_m", "terrain_class",
    "native_crs_hr", "native_crs_lr", "target_crs", "vertical_datum",
    "footprint_wkt", "license", "acquisition_date", "verification_status",
    "raw_path_hr", "raw_path_lr", "harmonized_path_hr", "harmonized_path_lr",
    "checksum_hr", "checksum_lr", "notes",
    # v1.1 addendum §C: coregistration QA columns
    "horiz_offset_m", "vert_offset_m",
    "coreg_peak_psr", "coreg_peak_eig_ratio", "coreg_peak_agrees",
    "coreg_status", "qc_artifact_path",
    # v1.2 addendum §E: user-provided HR provenance
    "hr_source_type", "hr_local_path",
    "hr_superseded_doi", "hr_superseded_reason",
]


@dataclass
class ManifestRow:
    pair_id: str
    site_name: str
    region: str
    cruise_id: str
    vessel: str
    hr_platform: str
    hr_sonar: str
    hr_doi: str
    hr_native_res_m: float
    lr_platform: str
    lr_sonar: str
    lr_doi: str
    lr_native_res_m: float
    res_ratio: float
    depth_min_m: float
    depth_max_m: float
    terrain_class: str
    native_crs_hr: str
    native_crs_lr: str
    target_crs: str
    vertical_datum: str
    footprint_wkt: str
    license: str
    acquisition_date: str
    verification_status: str
    raw_path_hr: str
    raw_path_lr: str
    harmonized_path_hr: str
    harmonized_path_lr: str
    checksum_hr: str
    checksum_lr: str
    notes: str = ""
    # v1.1 addendum §C
    horiz_offset_m: float = 0.0
    vert_offset_m: float = 0.0
    coreg_peak_psr: float = float("nan")
    coreg_peak_eig_ratio: float = float("nan")
    coreg_peak_agrees: bool = False
    coreg_status: str = "needs_review"
    qc_artifact_path: str = ""
    # v1.2 addendum §E — user-provided HR provenance
    hr_source_type: str = "doi"          # "doi" | "user_provided"
    hr_local_path: str = ""              # set only when hr_source_type == "user_provided"
    hr_superseded_doi: str = ""          # set when the user-provided file replaces a DOI release
    hr_superseded_reason: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("extras", None)
        return d


def load(path: Path = MANIFEST_PATH_DEFAULT) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_parquet(path)
    # Add any newly-introduced schema columns with their defaults so callers
    # don't crash on KeyError when older parquets are read after a schema bump.
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df


def upsert(row: ManifestRow, path: Path = MANIFEST_PATH_DEFAULT) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = load(path)
    df = df[df["pair_id"] != row.pair_id]  # remove any prior entry
    new = pd.DataFrame([row.to_record()], columns=COLUMNS)
    df = pd.concat([df, new], ignore_index=True)[COLUMNS]
    df.to_parquet(path, index=False)
    return path


def drop(pair_id: str, path: Path = MANIFEST_PATH_DEFAULT) -> bool:
    """Remove a pair_id from the manifest. Returns True if a row was removed."""
    path = Path(path)
    if not path.exists():
        return False
    df = load(path)
    before = len(df)
    df = df[df["pair_id"] != pair_id]
    if len(df) == before:
        return False
    df.to_parquet(path, index=False)
    return True
