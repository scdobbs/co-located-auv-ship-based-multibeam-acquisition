"""ACQ-R06 shared definitions — Phase 4 step 1 (the sealed chain) and its rehearsal.

Importing installs the lockbox + confirmatory + sealed-swath guard (src.acq_r01.common).  Everything here is scope
bookkeeping: the five sealed pairs (named so that sealed_step1.py can refuse everything else in phase4 mode), the
ten rehearsal pairs, the fixed inputs and their hashes, the output roots, and small helpers.  No sealed file is
opened by anything in this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.acq_r01 import common as C  # noqa: F401  (installs the guard)
from src.acq_r04 import common as R4

REPO = C.REPO
OAK = C.OAK
SCR = C.SCRATCH_DATA
REPORT_DIR = REPO / "reports_post_grl_review" / "ACQ-R06"
REHEARSAL_DIR = REPORT_DIR / "rehearsal"
R02 = REPO / "reports_post_grl_review" / "ACQ-R02"
R03 = REPO / "reports_post_grl_review" / "ACQ-R03"

# §0.2 fixed inputs (read-only); the run stops if any hash differs.
MANIFEST_V21 = R4.MANIFEST_V21
DROPPED_V21 = R4.DROPPED_V21
CONTRACT_V21 = REPO / "reports_post_grl_review" / "INTERFACE_CONTRACT_v2.1.md"
SHA_CONTRACT_V21 = "0b4aadaf61fb04213ae18771d2a58532f39e9d49b5152ab64738d188a7e18fcb"
C2C_CALIBRATION = REPO / "reports" / "discovery" / "stage_c2c_calibration.json"   # thresholds the ACQ-R02 chain hands to the sweep
JUNE_C2C_SWEEP = REPO / "reports" / "discovery" / "stage_c2c_sweep.json"           # June sweep record (k of the June pairs)
JUNE_C2A_RECORD = REPO / "reports" / "discovery" / "stage_c2a_documented_native.json"
JUNE_FILE_PLAN = REPO / "reports" / "discovery" / "stage_b_file_plan_2026-06-22.csv"
JUNE_FETCH_LIST = REPO / "reports" / "stage_b_fetch_list_2026-06-22.csv"

SCRATCH_ROOT = SCR / "phase4_rehearsal"                       # rehearsal outputs (never OAK)
FREEZE_RECORD = REPORT_DIR / "freeze_record.json"
SUPPLEMENT_PHASE4 = REPO / "manifest" / "pairs_phase4_sealed.parquet"
SUPPLEMENT_REHEARSAL = REHEARSAL_DIR / "supplement_rehearsal.parquet"

# §0.3 — the five sealed pairs, named here only so that the script can refuse everything else.
SEALED5 = {
    "KN182L03__MGDS_30193": {"set": "confirmatory", "unit": "nu01a"},
    "RC2511__MGDS_32239": {"set": "confirmatory", "unit": "nu01b"},
    "SUM1004__MGDS_33090": {"set": "confirmatory", "unit": "nu03"},
    "AT42-03__MGDS_32007": {"set": "lockbox", "unit": "lu03"},
    "TN159__MGDS_21981": {"set": "lockbox", "unit": "lu17"},
}
SEALED_PAIRS = tuple(SEALED5)
SEALED_LR_CRUISE = {p: p.split("__MGDS_")[0] for p in SEALED5}
assert set(SEALED_LR_CRUISE.values()) == set(C.SEALED_LR_CRUISES), (SEALED_LR_CRUISE, C.SEALED_LR_CRUISES)
assert set(p for p, v in SEALED5.items() if v["set"] == "lockbox") == set(C.LOCKBOX)

# Part B1 — the ten rehearsal pairs (development), smallest product job first.
REHEARSAL10 = ["TN399__MGDS_33068", "AT42-06__MGDS_5174", "EW9801__MGDS_31425", "NA076__MGDS_32317", "EX1402L2__MGDS_31073",
               "FK151121__MGDS_22383", "KM0923__MGDS_31429", "RR1506__MGDS_29779", "EX1202L2__MGDS_20815", "2009_Amundsen__MGDS_30047"]
assert not any(p in SEALED5 for p in REHEARSAL10)

# Part A step 3: pairs whose k is fixed by a prior record and never re-swept by this step (the two lockbox pairs).
PRIOR_K_PAIRS = tuple(C.LOCKBOX)

# Part C1: the contract-v2.1 flags that make ship products unusable.
CONTRACT_V21_FLAGS = ("registration_shift", "vertical_offset", "insufficient_overlap")
KS = (2, 4, 8, 16, 32)


def sealed_allow_tokens() -> tuple:
    """The guard allow-list of phase4 mode: the five pair ids, the confirmatory tree, the sealed cruises' swath."""
    return tuple(SEALED_PAIRS) + ("harmonized_confirmatory",) + tuple(f"raw_lr_swath/{c}" for c in C.SEALED_LR_CRUISES)


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
    """§0.2: manifest v2.1, its dropped list and contract v2.1; stop if any differs."""
    got = R4.check_fixed_inputs()
    c = sha256_file(CONTRACT_V21)
    if c != SHA_CONTRACT_V21:
        raise SystemExit(f"FIXED INPUT CHANGED: INTERFACE_CONTRACT_v2.1.md sha256 {c} != {SHA_CONTRACT_V21}")
    got["INTERFACE_CONTRACT_v2.1.md"] = c
    return got


_MANIFEST = None


def manifest():
    global _MANIFEST
    if _MANIFEST is None:
        import pandas as pd
        _MANIFEST = pd.read_parquet(MANIFEST_V21)
    return _MANIFEST


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "unknown"


def loaded_repo_files() -> dict:
    """Repo-relative path -> sha256 of every loaded module whose file lives under <repo>/src (the chain this process
    imported).  Used by the freeze record (Part D) and by lock 2 of phase4 mode."""
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


def git_commit() -> str:
    return C.git_commit()


def hostname() -> str:
    return os.uname().nodename
