"""ACQ-R14 (2026-10-20): public data release of the processed co-located ship/AUV corpus.

Constants, paths and small helpers shared by the ACQ-R14 modules. This package imports nothing from
src.acq_r01 / src.acq_r08: both blind tests are scored and the directive (section 5.4) releases the
blind-test pairs, whose ids those modules refuse in paths at import time.
"""
from __future__ import annotations
import hashlib, json, os, time
from datetime import datetime, timezone
from pathlib import Path

DIRECTIVE_ID = "ACQ-R14"
RELEASE_VERSION = "1.0.0"
PAPER_ID = "2026GL125574"
CODE_RECORDS = {"ml_code": "10.5281/zenodo.21300922", "acquisition_code": "10.5281/zenodo.21300925"}

REPO = Path(__file__).resolve().parents[2]
OAK = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy")
ARCH = OAK / "grl_review_archive"                       # CNN-repo frozen outputs preserved on OAK
CNN = Path("/home/users/scdobbs/GAN_Bathymetry_Project/grl_reviews-and-prompt-reports/directives_and_reports")
WORK = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/release_acq_r14")   # build area (purged scratch; not the archive)
STAGE = WORK / "stage"                                   # per-pair unzipped COGs + pair.json, before zipping
PKG = WORK / "package"                                   # the Zenodo-ready package (one zip per pair + corpus-level files)
RPT = REPO / "reports_post_grl_review" / DIRECTIVE_ID
OAK_DEST = OAK / "acq_archive" / DIRECTIVE_ID
INVENTORY = RPT / "inventory.json"
LICENSE_AUDIT = RPT / "license_audit.json"
FIXES = RPT / "plumbing_fixes.jsonl"
ZENODO_MAX_FILES, ZENODO_MAX_GB = 100, 50.0

# ---- scope (copied verbatim from src/acq_r05/common.py and the CNN repo r04_common / r08b_common; not imported) ----
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
DEV_PAIRS = [p for ps in UNITS_V1.values() for p in ps] + EW0207["lu16"]          # 39 = 38 units-v1 pairs + EW0207
TEN = ("lu00", "lu04", "lu05", "lu07", "lu08", "lu09", "lu13", "lu14", "lu15", "nu00")   # real-relief units (R08b)
SIX = ("lu02", "lu06", "lu10", "lu11", "lu12", "vu02")                                   # low-amplitude, artifact-affected
assert len(DEV_PAIRS) == 39 and len(UNITS_V1) == 16

CONFIRMATORY = {"KN182L03__MGDS_30193": "nu01a", "RC2511__MGDS_32239": "nu01b", "SUM1004__MGDS_33090": "nu03"}
LOCKBOX = {"AT42-03__MGDS_32007": "lu03", "TN159__MGDS_21981": "lu17"}
PHASE5 = ["TN188__MGDS_18210", "Escanaba__MGDS_30368", "Monterey__MGDS_24756", "KN161L04__MGDS_22436",
          "MV1209__MGDS_21415", "KN173L02__MGDS_31675", "MV1003__MGDS_31860", "AT26-24__MGDS_31954"]

# Pairs that are catalogued in the release manifest without rasters (directive section 1), with the recorded reason.
EXCLUDED = {
    "AT37-05__MGDS_24043": ("dropped", "ship_internal_inconsistency: 294 m line-to-line offset in the ship swath (rulings_ACQ-R03 R1)"),
    "PANGAEA_864677__PANGAEA_889317": ("dropped", "Chapopote (pu01, M114/1): co-registration failed, offset 53.83 m, dz 42.54 m, 1 tile at k=2 (rulings_ACQ-R03 R2)"),
    "PANGAEA_892317__PANGAEA_884112": ("never_acquired", "Venere (pu00, M112/1): ship raw-swath selection never completed (PANGAEA file-host throttling; ACQ-R03 HOLD H-C); pair never harmonized"),
    "2009_Amundsen__MGDS_30046": ("no_k", "Amundsen (lu18): no recoverable k at the stage-C cell (rulings_ACQ-R03 R5); never scored"),
    "2009_Amundsen__MGDS_30047": ("no_k", "Amundsen (lu18): no recoverable k (rulings_ACQ-R03 R5); never scored"),
    "PANGAEA_958275": ("restricted", "Kolumbo (pu03, POS510): every ship partner (M143/M215/MSM132 raw) is access-restricted on PANGAEA (HTTP 401); excluded before the second blind test (ACQ-R08b)"),
    "FK181031__MGDS_24367": ("no_k", "no recoverable k (June no-k stop); superseded in its unit by FK181031__MGDS_24618"),
    "KIWI10RR__MGDS_24499": ("no_k", "no recoverable k (no_curve); not in units-v1"),
    "TN268__MGDS_30466": ("no_k", "no recoverable k (no_curve); superseded by EW0207__MGDS_32556 (same HR grid)"),
    "EX1202L2__MGDS_20815": ("no_k", "no recoverable k (no_curve); not in units-v1"),
    "EX0909__MGDS_24002": ("dropped", "no_lr_soundings_under_hr (ACQ-R02)"),
    "EX1202L3__MGDS_31321": ("dropped", "no_lr_soundings_under_hr (ACQ-R02)"),
    "EX1206__MGDS_31831": ("dropped", "no_lr_soundings_under_hr (ACQ-R02)"),
    "FK171110__MGDS_24424": ("dropped", "zero_valid_tiles_256 (ACQ-R02)"),
    "NR07-1__MGDS_31813": ("dropped", "coreg_fail offset=41.57 m dz=223.23 m MAD=265.355 m (ACQ-R02)"),
    "NR07-1__MGDS_31814": ("dropped", "coreg_fail offset=50.86 m dz=409.5 m MAD=377.818 m (ACQ-R02)"),
    "lostcity2005__MGDS_21847": ("dropped", "coreg_fail offset=50.98 m dz=6.7 m MAD=7.725 m (ACQ-R02)"),
}

T_G = 0.200712            # ACQ-R11b calibrated datum bound (G = V95_rel)
MIN_TILES, B_MIN_DEFAULT = 10, 8   # frozen scoring constants (CNN phase4_common.py:48)

HEADERS = {"User-Agent": "auv-ship-acq/0.7 (Sherlock; ACQ-R14 public data release; stephencoledobbs@gmail.com)"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(path: Path, bufsize: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def jload(p: Path):
    with open(p) as f:
        return json.load(f)


def jdump(obj, p: Path, indent=1):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=indent, default=_default)
    os.replace(tmp, p)


def _default(o):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def fix(stage: str, pair: str | None, message: str) -> None:
    """Directive section 0, ruling 3: every plumbing fix is logged in one line and the work carries on."""
    RPT.mkdir(parents=True, exist_ok=True)
    rec = {"time": utcnow(), "stage": stage, "pair": pair, "fix": message}
    with open(FIXES, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"[fix] {stage} {pair or '-'}: {message}", flush=True)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def nan_to_none(v):
    import math
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    return v


def epsg_int(crs_text) -> int | None:
    if crs_text is None:
        return None
    s = str(crs_text).strip().upper()
    if s.startswith("EPSG:"):
        try:
            return int(s[5:])
        except ValueError:
            return None
    return None
