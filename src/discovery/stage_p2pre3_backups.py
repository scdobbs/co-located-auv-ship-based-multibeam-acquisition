"""P2-PRE-3 — durable, write-path-unreachable backups before Phase 2 OAK writes.

Establishes (and reports) immutable references the Phase-2 writer cannot reach:
  1. validated-grid sha256 anchor -> manifest/validated_grid_sha256.json (tracked, git).
  2. dated read-only OAK manifest backup: $OAK/.../manifest_backups/pairs.parquet.<date>
  3. dated read-only OAK copy of the 21 validated grids:
     $OAK/.../validated_anchor_backup_<date>/  (chmod 0444; Phase-2 writer only
     touches harmonized/<...__MGDS_...>/ so it structurally cannot reach this dir).
Off-machine immutability: pairs.parquet + this anchor + module are committed/pushed
to GitHub (separate step). All copies byte-verified.
"""
from __future__ import annotations
import json, logging, os, shutil, stat
from pathlib import Path
import pandas as pd

from src.discovery.validated_anchor import (compute_validated_grid_sha256,
                                            assert_validated_anchor, VALIDATED_PAIR_IDS)

log = logging.getLogger("p2pre3")
REPO = Path(__file__).resolve().parents[2]
DATE = "2026-06-26"
CANON = REPO / "manifest/pairs.parquet"
OAKROOT = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy")
OAK_HARM = OAKROOT / "harmonized"
SHA_JSON = REPO / "manifest/validated_grid_sha256.json"
MAN_BK_DIR = OAKROOT / "manifest_backups"
GRID_BK_DIR = OAKROOT / f"validated_anchor_backup_{DATE}"
RESULT = REPO / "reports/discovery/stage_p2pre3_result.json"


def _sha(p):
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _readonly(p):
    os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = {"date": DATE}
    # anchor check on current manifest first
    assert_validated_anchor(pd.read_parquet(CANON))
    res["anchor_check_current_manifest"] = "PASS"

    # 1. validated-grid sha256 anchor (committed)
    sha = compute_validated_grid_sha256(OAK_HARM)
    SHA_JSON.write_text(json.dumps(sha, indent=1, sort_keys=True))
    res["validated_grid_sha256"] = {"n_grids": len(sha), "file": str(SHA_JSON)}
    log.info("validated-grid sha256 anchor: %d grids -> %s", len(sha), SHA_JSON)

    # 2. dated read-only OAK manifest backup
    MAN_BK_DIR.mkdir(parents=True, exist_ok=True)
    man_bk = MAN_BK_DIR / f"pairs.parquet.{DATE}"
    if man_bk.exists():
        os.chmod(man_bk, stat.S_IRUSR | stat.S_IWUSR)
    shutil.copy2(CANON, man_bk)
    ok_man = _sha(CANON) == _sha(man_bk)
    _readonly(man_bk)
    res["oak_manifest_backup"] = {"path": str(man_bk), "byte_identical": ok_man, "mode": "0444"}
    log.info("OAK manifest backup %s byte_identical=%s (read-only)", man_bk, ok_man)

    # 3. dated read-only OAK copy of the 21 validated grids
    GRID_BK_DIR.mkdir(parents=True, exist_ok=True)
    copied, verified = 0, 0
    for pid in sorted(VALIDATED_PAIR_IDS):
        if pid.startswith("cal_dig_morro_bay__"):
            src = OAK_HARM / "cal_dig_morro_bay" / pid.split("__", 1)[1]
        else:
            src = OAK_HARM / pid
        dst = GRID_BK_DIR / pid
        dst.mkdir(parents=True, exist_ok=True)
        for side in ("hr", "lr"):
            sp = src / f"{side}.tif"
            if not sp.exists():
                continue
            dp = dst / f"{side}.tif"
            if dp.exists():
                os.chmod(dp, stat.S_IRUSR | stat.S_IWUSR)
            shutil.copy2(sp, dp)
            copied += 1
            if _sha(sp) == _sha(dp):
                verified += 1
            _readonly(dp)
    res["oak_validated_grid_backup"] = {"dir": str(GRID_BK_DIR), "grids_copied": copied,
                                        "byte_verified": verified, "all_ok": copied == verified}
    log.info("OAK validated-grid backup: %d copied, %d byte-verified -> %s (read-only)",
             copied, verified, GRID_BK_DIR)

    res["ok"] = bool(ok_man and copied == verified)
    RESULT.write_text(json.dumps(res, indent=2, default=str))
    log.info("P2-PRE-3 done: ok=%s", res["ok"])


if __name__ == "__main__":
    main()
