"""ACQ-R09 shared definitions — Phase 5 step 1 (spec PHASE5_design_spec_2026-10-13.md) and its rehearsal.

Importing installs the acquisition guard (src.acq_r01.common: lockbox, confirmatory, sealed swath, sealed_candidates_v3
root and every ACQ-R08b candidate id).  Everything here is bookkeeping: the site list reader, the two modes, the fixed
inputs and their hashes, the eligibility constants of spec §3.3 and small helpers.  No sealed file is opened here.

Steve's rulings of 2026-10-13 (ACQ-R09, recorded in the report):
  S1  dispersed high-resolution grids: after spec rules §3.2.1-2 the kept grids go to the UNCHANGED development logic —
      src/acq_r01/grid_lr.grid_region (ship grid on the patch cluster) and src/acq_r01/harmonize_new.hr_mosaic (grids
      overlapping the ship grid; mosaic if <= 8 grids, bbox coverage >= 0.2 and <= 4e8 cells, else the grid with the
      largest overlap);
  S2  repeat surveys: two grids overlap when their validity masks share >= 50 % of the smaller grid's valid area; below
      that they are mosaicked with the rule order as priority; an undated grid counts as a tie (larger valid area decides);
  S3  the current grid_lr (grid_region) is used; FK151121's development grid predates it, so the rehearsal isolates that
      pair by re-gridding it on its recorded development region in a separate harness.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.acq_r01 import common as C  # noqa: F401  (installs the guard)

REPO = C.REPO
OAK = C.OAK
SCR = C.SCRATCH_DATA
RPG = REPO / "reports_post_grl_review"
REPORT_DIR = RPG / "ACQ-R09"
REHEARSAL_DIR = REPORT_DIR / "rehearsal"
PHASE5_DIR = RPG / "PHASE5"                                      # phase5-mode run records and the freeze record
FREEZE_RECORD = PHASE5_DIR / "freeze_record_phase5.json"
SITE_LIST = REPO / "inputs" / "phase5_sites.csv"
SITE_LIST_REL = "inputs/phase5_sites.csv"
ENTRY_REL = "src/phase5/sealed_step1_p5.py"
SUPPLEMENT_PHASE5 = REPO / "manifest" / "pairs_phase5_sealed.parquet"
SUPPLEMENT_PHASE4 = REPO / "manifest" / "pairs_phase4_sealed.parquet"         # schema reference only (never parsed for values)
SHA_SUPPLEMENT_PHASE4 = "6968e04554ddeef3c335587d602cb5fab2185db32b46cbd152475a919eb59206"

# rehearsal layout (scratch only)
SCRATCH_ROOT = SCR / "ACQ-R09"
MOCK_ROOT = SCRATCH_ROOT / "mock" / C.SEALED_CANDIDATES_V3_DIRNAME           # .../ACQ-R09/mock/sealed_candidates_v3/<id>/
MOCK_SITE_LIST = REHEARSAL_DIR / "mock_sites.csv"
REHEARSAL_OUT = SCRATCH_ROOT / "rehearsal"

# fixed inputs (read-only); a differing hash stops the run
C2C_CALIBRATION = REPO / "reports" / "discovery" / "stage_c2c_calibration.json"
CONTRACT_V21 = RPG / "INTERFACE_CONTRACT_v2.1.md"
R08B_MEASURED = RPG / "ACQ-R08b" / "candidates_measured.csv"                   # one rounded depth per site (fetch-plan buffer only)
FIXED = {
    "reports/discovery/stage_c2c_calibration.json": (C2C_CALIBRATION, "7e68bdadfcdb5dd1c5ad4040ad6a5edf5226fcd9223e6824ae1c21472c01778a"),
    "reports_post_grl_review/INTERFACE_CONTRACT_v2.1.md": (CONTRACT_V21, "0b4aadaf61fb04213ae18771d2a58532f39e9d49b5152ab64738d188a7e18fcb"),
    "manifest/pairs_phase4_sealed.parquet": (SUPPLEMENT_PHASE4, SHA_SUPPLEMENT_PHASE4),
    "reports_post_grl_review/ACQ-R08b/candidates_measured.csv": (R08B_MEASURED, "fbd2e03d9cdbe65420fbd98cb772dd1af5ef855951307e9c5b0d4c98b1607b37"),
}

# spec §3.2.1 / §3.3 constants (fixed now)
HR_MIN, HR_MAX = 0.985, 4.99                 # HR spacing range (m), resolution-group range and eligibility 3
CELLS_MIN, CELLS_MAX = 3.88, 51.2            # ship cells across a 256-px window (eligibility 3)
WIN = 256
GROUP_COVER = 0.80                           # finest group whose valid area >= 80 % of the largest group (ACQ-R08b rule)
OVERLAP_FRAC = 0.50                          # ruling S2
USBL_BOUND_M = 30.0                          # development QA (src/acq_r01/harmonize_new.py USBL_BOUND_M, ACQ-R03 R2)
MIN_OVERLAP_KM2 = 1.0                        # development QA (harmonize_pair min_overlap_area_km2 and qa_pass)
KS = (2, 4, 8, 16, 32)
FETCH_WORKERS = 6
LICENSE_MGDS = "MGDS default CC-BY-NC-SA (ACQ-R08b ruling R3)"

# Keys that must never appear in a Phase 5 record written by this code (no depth statistic, amplitude or residual).
FORBIDDEN_KEY_PARTS = ("depth", "median", "mad", "rms", "sigma", "p50", "p05", "p95", "amplitude", "residual", "mean_z", "std")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(p) -> str:
    return C.sha256_file(p)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def write_json(path: Path, obj, mode: int = 0o444) -> Path:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(0o644)
    path.write_text(json.dumps(obj, indent=1, default=str))
    path.chmod(mode)
    return path


def check_fixed_inputs() -> dict:
    got = {}
    for rel, (p, want) in FIXED.items():
        h = sha256_file(p)
        if h != want:
            raise SystemExit(f"FIXED INPUT CHANGED: {rel} sha256 {h} != {want}")
        got[rel] = h
    return got


def token(hr_id: str) -> str:
    """Directory / path token of a high-resolution record id (':' -> '_'), as ACQ-R08b named the sealed directories."""
    return str(hr_id).replace(":", "_")


def pair_id_of(site: dict) -> str:
    return f"{site['ship_cruise']}__{token(site['hr_id'])}"


def read_site_list(path) -> list:
    """Rows of a site list (columns site_name, hr_id, ship_cruise, sonar, year), in file order, each with pair_id/token/unit."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    need = ["site_name", "hr_id", "ship_cruise", "sonar", "year"]
    if not rows or list(rows[0].keys()) != need:
        raise ValueError(f"site list {path}: columns must be exactly {need}")
    out = []
    for i, r in enumerate(rows, 1):
        r = {k: str(v).strip() for k, v in r.items()}
        r["year"] = int(r["year"])
        r["token"] = token(r["hr_id"]); r["pair_id"] = pair_id_of(r); r["unit"] = f"p5u{i:02d}"
        out.append(r)
    ids = [r["hr_id"] for r in out]
    if len(set(ids)) != len(ids):
        raise ValueError(f"site list {path}: duplicate hr_id")
    return out


def depth_hint_m(hr_id: str) -> float | None:
    """ACQ-R08b's depth_median_100m for a site (public metadata; used only as the fetch-plan buffer depth, as the
    development fetch planner used a catalog depth)."""
    with open(R08B_MEASURED, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["hr_id"] == hr_id and r.get("depth_median_100m"):
                return float(r["depth_median_100m"])
    return None


def forbidden_keys(obj, path="") -> list:
    """Every key of a nested record whose name contains a forbidden part (no depth statistic, amplitude, residual)."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if any(part in kl for part in FORBIDDEN_KEY_PARTS):
                hits.append(f"{path}/{k}")
            hits += forbidden_keys(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += forbidden_keys(v, f"{path}[{i}]")
    return hits


def loaded_repo_files() -> dict:
    """Repo-relative path -> sha256 of every loaded module under <repo>/src (the chain this process imported)."""
    out = {}
    root = str(REPO / "src")
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if not f:
            continue
        try:
            fp = Path(f).resolve()
        except Exception:
            continue
        if str(fp).startswith(root) and fp.suffix == ".py":
            out[str(fp.relative_to(REPO))] = sha256_file(fp)
    return dict(sorted(out.items()))


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "unknown"


def git_commit() -> str:
    return C.git_commit()


def hostname() -> str:
    return os.uname().nodename
