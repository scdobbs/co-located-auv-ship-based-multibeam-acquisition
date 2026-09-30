"""ACQ-R01 shared definitions for the acquisition repo.

Importing this module INSTALLS THE LOCKBOX GUARD (ACQ-R01 §0, equivalent to the
CNN repo's ``r03_common.install_lockbox_guard``): any attempt to open a path that
contains a lockbox pair id through ``builtins.open``, ``rasterio.open`` or
``numpy.load`` raises ``PermissionError`` before any read.

Everything else here is scope bookkeeping: which pairs / cruises ACQ-R01 §2 covers,
where OAK and scratch roots are, and the unit naming shared with the CNN repo
(copied verbatim from ``r03_common.py`` so the two repos agree on unit ids).
"""
from __future__ import annotations

import builtins
import hashlib
import json
import os
import subprocess
from pathlib import Path

# --------------------------------------------------------------------------- #
# Lockbox (permanent hold-out pairs). Never opened, gridded, downloaded or QA'd.
# --------------------------------------------------------------------------- #
LOCKBOX = ("AT42-03__MGDS_32007", "TN159__MGDS_21981")
LOCKBOX_LR_CRUISES = ("AT42-03", "TN159")

REPO = Path(__file__).resolve().parents[2]
OAK = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy")
SCRATCH_DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
RAW_SWATH_OAK = OAK / "raw_lr_swath"
REPORT_DIR = REPO / "reports_post_grl_review" / "ACQ-R01"
MANIFEST = REPO / "manifest" / "pairs.parquet"
FILE_PLAN = REPO / "reports/discovery/stage_b_file_plan_2026-06-22.csv"
FETCH_LIST = REPO / "reports/stage_b_fetch_list_2026-06-22.csv"

# MB-System (pinned; see reports/mbsystem_build_pin.txt)
MBSYSTEM_VERSION = "5.8.2beta06"
SANDBOX = "/home/groups/hilley/containers/mbsystem_sandbox"
CONTAINER_DIGEST = "sha256:106f502d9f97ee0e9f5d889726320d1ae73a95fb102069e357a0bb0b35b39668"
BIND = ["--bind", "/scratch,/home/groups,/oak"]

# --------------------------------------------------------------------------- #
# Unit naming, copied from the CNN repo's r03_common.py (R04 §0.1 decisions).
# --------------------------------------------------------------------------- #
NATIVE7 = {"NA090": ["NA090__MGDS_31212"], "NA080": ["NA080__MGDS_31290"], "TN399": ["TN399__MGDS_30373"],
           "RR1506": ["RR1506__MGDS_29779"], "AT37-13": ["AT37-13__MGDS_31199"], "FK181031": ["FK181031__MGDS_24618"],
           "TN299": ["TN299__MGDS_27339", "TN299__MGDS_31253"]}
EW0207 = {"EW0207": ["EW0207__MGDS_32556"]}
CALDIG = {"CalDIG": ["cal_dig_morro_bay__20180426m2_Channel1000", "cal_dig_morro_bay__20180427m1_Channel700",
                     "cal_dig_morro_bay__20180427m3_PockmarkNorth", "cal_dig_morro_bay__20180428m1_Cable",
                     "cal_dig_morro_bay__201804_LuciaChica2m", "cal_dig_morro_bay__20190314m4_LuciaChica970m",
                     "cal_dig_morro_bay__20190315m1_HeadlessCanyon", "cal_dig_morro_bay__20190316m1_BankTop",
                     "cal_dig_morro_bay__20190317m1_1000mGully", "cal_dig_morro_bay__20190317m2_600mGully",
                     "cal_dig_morro_bay__20190318m2_Transect601060m", "cal_dig_morro_bay__20190510m1_BankFlankHoles",
                     "cal_dig_morro_bay__20190510m2_BankFlankIncipCh", "cal_dig_morro_bay__20190511m1_6thHeadlessCany",
                     "cal_dig_morro_bay__20190511m2_BankTopEofCanyon3", "cal_dig_morro_bay__basin_flank",
                     "cal_dig_morro_bay__luciachica_2007", "cal_dig_morro_bay__pockmark_south"]}
EXPANSION7 = {"CCZ": ["ccz_so268_1"], "DISCOL": ["discol_so242_1"], "TAG": ["tag_m127"], "EW9801": ["EW9801__MGDS_31425"],
              "AR26": ["AR26__MGDS_31838"], "NA076": ["NA076__MGDS_32317"], "Amundsen": ["2009_Amundsen__MGDS_30046"]}
STOPPED_NO_K = {"KIWI10RR__MGDS_24499": "stage_c2c_sweep status=no_curve, max_recoverable_k=None",
                "TN268__MGDS_30466": "stage_c2c_sweep status=no_curve (HR superseded), max_recoverable_k=None; shares lu16 with EW0207",
                "FK181031__MGDS_24367": "stage_c2c_sweep max_recoverable_k=None (Alarcon Rise; shares lu08 with FK181031__MGDS_24618)"}
ALL15 = {**NATIVE7, **CALDIG, **EXPANSION7}
UNIT_OF = {p: u for d in (NATIVE7, EW0207, CALDIG, EXPANSION7) for u, ps in d.items() for p in ps}
PROVIDER_UNITS = ("CalDIG", "CCZ", "DISCOL", "TAG")

# --------------------------------------------------------------------------- #
# Confirmatory seal (ACQ-R02 §0): units designated confirmatory. Their harmonized outputs live
# under OAK harmonized_confirmatory/<unit>/<pair>/; no residual-amplitude statistic, k sweep,
# spectral ratio, baseline, model or target is computed on them before Phase 4.
# --------------------------------------------------------------------------- #
CONFIRMATORY_UNITS = ("nu01", "nu03",          # ACQ-R01 designation (seed 20260929): MAR mixed, Mariana abyssal
                      "pu02", "pu03")          # ACQ-R02 §4.3 PANGAEA designation (seed 20260930): Etna margin AL532, Kolumbo POS510
HARMONIZED_CONFIRMATORY = OAK / "harmonized_confirmatory"


def confirmatory_paths(units=None):
    """Directories that hold confirmatory-unit outputs (for the CNN repo's guard)."""
    units = tuple(units) if units else CONFIRMATORY_UNITS
    return [HARMONIZED_CONFIRMATORY / u for u in units]


# The 12 NCEI-swath cruises in ACQ-R01 §2.1 scope (LR ship cruise = pair_id prefix).
NCEI_CRUISES = ("RR1506", "AT37-13", "TN399", "EW9801", "FK181031", "NA090", "NA076",
                "NA080", "AR26", "TN299", "EW0207", "2009_Amundsen")

# §2.1 pairs in scope = every pair of the 15 development units + EW0207,
# minus the lockbox (not in those units anyway) and the three no-k pairs.
PAIRS_IN_SCOPE = tuple(p for p in UNIT_OF if p not in LOCKBOX and p not in STOPPED_NO_K)
assert len(PAIRS_IN_SCOPE) == 34, len(PAIRS_IN_SCOPE)
assert not any(p in LOCKBOX for p in PAIRS_IN_SCOPE)


def _check(path):
    s = os.fspath(path) if not isinstance(path, int) else ""
    for l in LOCKBOX:
        if l in str(s):
            raise PermissionError(f"LOCKBOX GUARD (ACQ-R01 §0): refusing to open {s}")
    return path


_installed = False


def install_lockbox_guard():
    global _installed
    if _installed:
        return
    _open = builtins.open

    def guarded_open(file, *a, **k):
        _check(file); return _open(file, *a, **k)
    builtins.open = guarded_open
    try:
        import rasterio
        _ro = rasterio.open

        def guarded_ro(fp, *a, **k):
            _check(fp); return _ro(fp, *a, **k)
        rasterio.open = guarded_ro
    except ImportError:
        pass
    try:
        import numpy as np
        _nl = np.load

        def guarded_nl(file, *a, **k):
            _check(file); return _nl(file, *a, **k)
        np.load = guarded_nl
    except ImportError:
        pass
    _installed = True


def assert_no_lockbox(pair_ids):
    bad = [p for p in pair_ids if p in LOCKBOX]
    if bad:
        raise PermissionError(f"LOCKBOX GUARD (ACQ-R01 §0): pair list contains {bad}")
    return list(pair_ids)


def assert_no_lockbox_cruise(cruises):
    bad = [c for c in cruises if c in LOCKBOX_LR_CRUISES]
    if bad:
        raise PermissionError(f"LOCKBOX GUARD (ACQ-R01 §0): cruise list contains lockbox LR cruises {bad}")
    return list(cruises)


def sha256_file(path, bufsize=1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def mb(args, **kw) -> subprocess.CompletedProcess:
    """Run an MB-System command inside the pinned Apptainer sandbox."""
    cmd = ["apptainer", "exec", *BIND, SANDBOX, *args]
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def mb_cmdline(args) -> str:
    return " ".join(["apptainer", "exec", *BIND, SANDBOX, *[str(a) for a in args]])


def load_manifest():
    import pandas as pd
    m = pd.read_parquet(MANIFEST)
    return m


def pair_dir_oak(row) -> Path:
    """Harmonized directory of a pair on OAK (Cal DIG pairs live in sub-dirs)."""
    return OAK / Path(row["harmonized_path_lr"]).parent


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))


install_lockbox_guard()
