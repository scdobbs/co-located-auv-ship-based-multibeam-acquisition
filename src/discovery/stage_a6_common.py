"""Shared constants/loaders for Stage A.6 pre-fetch hygiene."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / "reports/discovery/staging_state_20260605.json"
SANITY = REPO / "reports/discovery/hr_resolution_sanity.csv"
MANIFEST = REPO / "manifest/pairs.parquet"
STAGE_A_JSON = REPO / "reports/discovery/stage_a_raw_lr_sizes_2026-06-22.json"
STAGE_A5_JSON = REPO / "reports/stage_a5_footprint_subset_2026-06-22.json"

# HR that are dropped/quarantined and never pairable (handoff §4 open items).
DROPPED_HR = {"MGDS:30272", "MGDS:20836", "MGDS:24425"}
QUARANTINED_HR = {"MGDS:31600"}

# Thin-overlap cruises flagged in Stage A.5 (fraction_kept <= 0.02, edge geom).
THIN_OVERLAP = {"TN299", "NA080", "TN399"}


def clean_hr_buckets() -> dict[str, str]:
    """hr_id -> bucket for the 81 clean HR (ok | ok_finer_verify | manifest_seed_clean)."""
    san = pd.read_csv(SANITY)
    keep = {"ok", "ok_finer_verify", "manifest_seed_clean"}
    sub = san[san["resolution"].isin(keep)]
    return dict(zip(sub["hr_id"], sub["resolution"]))


NONSEED = "nonseed"


def served_by_cruise() -> dict[str, list[str]]:
    """cruise_id -> served HR (from the 76 raw-LR references)."""
    st = json.loads(STATE.read_text())
    refs = st["raw_lr_in_training_eval"] + st["DEFER_PHASE_2_raw_lr_to_grid"]
    out: dict[str, list[str]] = {}
    for r in refs:
        out.setdefault(r["lr_id"].split(":", 1)[1], []).append(r["hr_id"])
    return out


def seed_ids() -> set[str]:
    st = json.loads(STATE.read_text())
    return set(st["phase1_rev2"]["manifest_seed_clean_ids"])
