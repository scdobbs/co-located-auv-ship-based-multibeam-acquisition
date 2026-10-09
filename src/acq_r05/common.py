"""ACQ-R05 shared definitions — wide-context ship grids around every development pair.

Importing installs the lockbox + confirmatory guard (src.acq_r01.common).  Everything here is scope bookkeeping:
which pairs are in scope (units-v1, 38 pairs, + EW0207), which are provider-grid vs NCEI-swath, where the context
directories go, and the refusal of sealed units (§0 item 4 / §5): the builder never runs on a lockbox or confirmatory
pair id, nor on anything under harmonized_confirmatory/.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from src.acq_r01 import common as C  # noqa: F401  (installs the guard)
from src.acq_r04 import common as R4

REPO = C.REPO
OAK = C.OAK
REPORT_DIR = REPO / "reports_post_grl_review" / "ACQ-R05"
R02 = REPO / "reports_post_grl_review" / "ACQ-R02"
R03 = REPO / "reports_post_grl_review" / "ACQ-R03"
SCR = C.SCRATCH_DATA
STAGE = SCR / "context_v1_stage"                      # per-pair staging (products builder input), node-independent
CACHE = SCR / "discovery_cache" / "acq_r05_2026-10-09"  # fresh NCEI listings for this directive
NAVCACHE = SCR / "discovery_cache" / "nav"              # .fnv nav tracks (shared with stage A.5 / ACQ-R02; tracks do not change)
CTX_GRD_OAK = OAK / "raw_lr_gridded"                    # geographic context grids persisted next to the union grids
MANIFEST_V21 = R4.MANIFEST_V21
DROPPED_V21 = R4.DROPPED_V21

CNN_REPO = Path("/home/users/scdobbs/GAN_Bathymetry_Project")
TILES_V1_1 = CNN_REPO / "grl_reviews-and-prompt-reports/directives_and_reports/R05/tiles/tiles_v1_1.parquet"
SHA_TILES_V1_1 = "8ef139867613b6c9f2eeb2e13073ee5562ecda51b3cf6f5bb7d17fd73df023dc"   # CNN R05 §6 / freeze_record.json
TILES_V1_R04 = CNN_REPO / "grl_reviews-and-prompt-reports/directives_and_reports/R04/tiles/tiles_v1.parquet"   # s_lr per tile

BUFFER_M = 5000.0        # §1.1 context buffer around the footprint
MARGIN_M = 1000.0        # stage-C mbgrid margin (region = extent ± 1 km)
DEV_FILL = -9999.0       # development warp nodata (harmonize_new / stage_f_harmonize FILL)
WINDOWS = (16, 32, 64)   # §4
GATE_SIGMA_FRAC = 0.10   # §3 gate: robust sigma of the difference > 0.10 x median s_lr
GATE_MEDIAN_M = 0.5      # §3 gate: |median difference| > 0.5 m
HEADERS = {"User-Agent": "auv-ship-acq/0.6 (Sherlock; ACQ-R05 context ship grids; stephencoledobbs@gmail.com)"}

# --------------------------------------------------------------------------- #
# Scope: units-v1 (CNN repo r04_common.UNITS, frozen at phase0-freeze) + EW0207 (scored separately)
# --------------------------------------------------------------------------- #
UNITS_V1 = {
    "lu00": ["RR1506__MGDS_29779"], "lu02": ["discol_so242_1"], "lu04": ["AT37-13__MGDS_31199"],
    "lu05": ["TN399__MGDS_30373", "TN399__MGDS_33068", "AT42-06__MGDS_5174"], "lu06": ["ccz_so268_1"],
    "lu07": ["EW9801__MGDS_31425", "KM0923__MGDS_31429"], "lu08": ["FK181031__MGDS_24618"], "lu09": ["tag_m127"],
    "lu10": ["NA090__MGDS_31212"], "lu11": ["NA076__MGDS_32317"],
    "lu12": ["cal_dig_morro_bay__20180426m2_Channel1000", "cal_dig_morro_bay__20180427m1_Channel700",
             "cal_dig_morro_bay__20180427m3_PockmarkNorth", "cal_dig_morro_bay__20180428m1_Cable",
             "cal_dig_morro_bay__201804_LuciaChica2m", "cal_dig_morro_bay__20190314m4_LuciaChica970m",
             "cal_dig_morro_bay__20190315m1_HeadlessCanyon", "cal_dig_morro_bay__20190316m1_BankTop",
             "cal_dig_morro_bay__20190317m1_1000mGully", "cal_dig_morro_bay__20190317m2_600mGully",
             "cal_dig_morro_bay__20190318m2_Transect601060m", "cal_dig_morro_bay__20190510m1_BankFlankHoles",
             "cal_dig_morro_bay__20190510m2_BankFlankIncipCh", "cal_dig_morro_bay__20190511m1_6thHeadlessCany",
             "cal_dig_morro_bay__20190511m2_BankTopEofCanyon3", "cal_dig_morro_bay__basin_flank",
             "cal_dig_morro_bay__luciachica_2007", "cal_dig_morro_bay__pockmark_south"],
    "lu13": ["NA080__MGDS_31290", "NA080__MGDS_31289"], "lu14": ["AR26__MGDS_31838"],
    "lu15": ["TN299__MGDS_27339", "TN299__MGDS_31253"], "nu00": ["FK151121__MGDS_22383"], "vu02": ["EX1402L2__MGDS_31073"]}
EW0207 = {"lu16": ["EW0207__MGDS_32556"]}
UNIT_OF = {p: u for d in (UNITS_V1, EW0207) for u, ps in d.items() for p in ps}
DEV38 = [p for ps in UNITS_V1.values() for p in ps]
PAIRS_IN_SCOPE = DEV38 + EW0207["lu16"]
assert len(DEV38) == 38 and len(UNITS_V1) == 16 and len(PAIRS_IN_SCOPE) == 39

# Sealed (§0 item 4, §5): never built here.  Confirmatory pair ids from the CNN repo's r04_common.CONFIRMATORY.
CONFIRMATORY_PAIRS = ("KN182L03__MGDS_30193", "RC2511__MGDS_32239", "SUM1004__MGDS_33090")
SEALED_PAIRS = tuple(C.LOCKBOX) + CONFIRMATORY_PAIRS

PROVIDER_PAIRS = tuple(p for p in PAIRS_IN_SCOPE if "__MGDS_" not in p)          # 21: 18 Cal DIG + discol, ccz, tag
NCEI_PAIRS = tuple(p for p in PAIRS_IN_SCOPE if "__MGDS_" in p)                  # 18
assert len(PROVIDER_PAIRS) == 21 and len(NCEI_PAIRS) == 18

# R05 (CNN repo) consumer-side override, recorded in context.json (§2.3); no rebuild of that pair's acquisition products.
CONSUMER_OVERRIDES = {"EX1402L2__MGDS_31073": {"ship_xtrack_frac": "unavailable on the consumer side (CNN R05 ruling H2 / R04 H2: all-NaN where count >= 1); the acquisition products of the pair were not rebuilt"}}

# Provider units masked by ACQ-R03 ruling R4 (ship_products_usable = false) and Cal DIG (no swath): products.json only.
PROVIDER_PRODUCT_RULING = {
    "discol_so242_1": "ACQ-R03 ruling R4: ship products masked (ship_products_usable=false); no context products",
    "ccz_so268_1": "ACQ-R03 ruling R4: ship products masked (ship_products_usable=false); no context products",
    "tag_m127": "ACQ-R03 ruling R4: ship products masked (ship_products_usable=false); no context products",
}
CALDIG_REASON = "ship LR is a processed mosaic without retrievable per-beam soundings (NOS BAG); no swath products (ACQ-R01 / contract v2.1 §5)"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(p) -> str:
    return C.sha256_file(p)


def write_json(path: Path, obj, mode=0o444) -> None:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(0o644)
    path.write_text(json.dumps(obj, indent=1, default=str))
    path.chmod(mode)


def check_fixed_inputs() -> dict:
    """§0.2: manifest v2.1 + dropped list hashes (stop if either differs) and tiles_v1_1.parquet (CNN R05 §6)."""
    got = R4.check_fixed_inputs()
    t = sha256_file(TILES_V1_1)
    if t != SHA_TILES_V1_1:
        raise SystemExit(f"FIXED INPUT CHANGED: tiles_v1_1.parquet sha256 {t} != {SHA_TILES_V1_1}")
    got["tiles_v1_1.parquet"] = t
    return got


def refuse_sealed(pair_id: str) -> str:
    """§5 guard: the builder refuses lockbox and confirmatory pair ids and any confirmatory path."""
    s = str(pair_id)
    for p in SEALED_PAIRS:
        if p in s:
            raise PermissionError(f"ACQ-R05 GUARD: refusing sealed pair {p} (lockbox / confirmatory; context grids only at Phase 4)")
    if "harmonized_confirmatory" in s.replace("\\", "/").split("/"):
        raise PermissionError(f"ACQ-R05 GUARD: refusing confirmatory path {s}")
    return s


def refuse_sealed_path(path) -> Path:
    refuse_sealed(os.fspath(path))
    return Path(path)


_MANIFEST = None


def manifest():
    global _MANIFEST
    if _MANIFEST is None:
        import pandas as pd
        _MANIFEST = pd.read_parquet(MANIFEST_V21).set_index("pair_id")
    return _MANIFEST


def row(pair_id: str):
    refuse_sealed(pair_id)
    m = manifest()
    if pair_id not in m.index:
        raise KeyError(f"{pair_id} not in manifest v2.1")
    return m.loc[pair_id]


def pair_dir(pair_id: str) -> Path:
    """Harmonized directory of the pair on OAK (resolved from the manifest's harmonized_path_lr)."""
    r = row(pair_id)
    return refuse_sealed_path(OAK / Path(r["harmonized_path_lr"]).parent)


def context_dir(pair_id: str) -> Path:
    return pair_dir(pair_id) / "context_v1"


def lr_cruise(pair_id: str) -> str:
    return str(row(pair_id)["lr_cruise"])


def is_provider(pair_id: str) -> bool:
    return pair_id in PROVIDER_PAIRS


def git_commit() -> str:
    return C.git_commit()


def chmod_ro(p: Path):
    try:
        Path(p).chmod(0o444)
    except Exception:
        pass
