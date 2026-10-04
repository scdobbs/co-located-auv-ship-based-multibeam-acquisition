"""ACQ-R04 shared paths and helpers (ship-only pretraining corpus).

Importing installs the lockbox + confirmatory guard (via src.acq_r01.common).

MB-System calls go through ``mb_bounded``: the ACQ-R03 policy (build_products_v2_1._worker) as a function —
every call has a timeout, any rc != 0 or timeout is retried up to 6 times with a growing pause (container
starts stall/fail under concurrent fuse-overlayfs mounts), and exhausting the retries RAISES (never "no
soundings").
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from src.acq_r01 import common as C  # noqa: F401  (installs the guard)

REPO = C.REPO
REPORT_DIR = REPO / "reports_post_grl_review" / "ACQ-R04"
R01 = REPO / "reports_post_grl_review" / "ACQ-R01"
R02 = REPO / "reports_post_grl_review" / "ACQ-R02"
SCR = C.SCRATCH_DATA
PRETRAIN_RAW = SCR / "pretrain_raw"                # raw swath (scratch only; re-fetchable from fetch manifests)
STAGE = SCR / "pretrain_v1_stage"                  # block directories as built, before persistence to OAK
WORK_LOGS = SCR / "pretrain_v1_logs"               # per-cruise run records (JSON), copied to the report dir
CACHE = SCR / "discovery_cache" / "acq_r04_2026-10-02"
OAK_OUT = C.OAK / "pretrain_v1"
NCEI_FP = SCR / "discovery_cache" / "acq_r01_2026-09-29" / "ncei_all_footprints.geojson"   # ACQ-R01 §5 snapshot

MANIFEST_V21 = REPO / "manifest" / "pairs_v2_1.parquet"
DROPPED_V21 = REPO / "manifest" / "pairs_v2_1_dropped.csv"
SHA_MANIFEST_V21 = "f57f3d8f98b320b136549de300ccac58787129af658a1c62296bab16b6c2ac35"
SHA_DROPPED_V21 = "1f1bb181c63df8991ddc981c731bbf048a25ec56cb33435487b356d603073dab"

HEADERS = {"User-Agent": "auv-ship-acq/0.5 (Sherlock; ACQ-R04 ship-only pretraining corpus; stephencoledobbs@gmail.com)"}

BUFFER_M = 10_000.0          # §1 rule 2 / §3.3 guard
LOCKBOX_RADIUS_M = 50_000.0  # §1 rule 2 lockbox centroids
SEED_SELECT = 20261003
SEED_SPOT = 20261004
N_SELECT = 400
FAMILY_FLOOR = 15
CAP_BYTES = 3_000_000_000_000
BLOCK_M = 10_000.0
DEPTH_MIN, DEPTH_MAX = 300.0, 6500.0
FILL_MIN = 0.50
MBGRID_FLAGS = ["-A2", "-G3", "-F1", "-C0", "-M"]   # stage-C recipe (stage_c_full / ACQ-R02 grid_lr)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(p) -> str:
    return C.sha256_file(p)


def write_json(path: Path, obj) -> None:
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str))


def check_fixed_inputs() -> dict:
    """§0.2: record both hashes; stop if either differs."""
    got = {"pairs_v2_1.parquet": sha256_file(MANIFEST_V21), "pairs_v2_1_dropped.csv": sha256_file(DROPPED_V21)}
    want = {"pairs_v2_1.parquet": SHA_MANIFEST_V21, "pairs_v2_1_dropped.csv": SHA_DROPPED_V21}
    for k in want:
        if got[k] != want[k]:
            raise SystemExit(f"FIXED INPUT CHANGED: {k} sha256 {got[k]} != {want[k]}")
    return got


class MBFailure(RuntimeError):
    pass


def mb_bounded(args, cwd, timeout=2400, attempts=6, stdout_path: Path | None = None, ok_rc=(0,)):
    """Run one MB-System command in the pinned sandbox; bounded, retried, loud.

    stdout_path: stream stdout to this file (large mblist dumps) instead of memory.
    Returns (CompletedProcess-like dict with rc/stderr/stdout, attempts used, command line)."""
    cmd = ["apptainer", "exec", *C.BIND, C.SANDBOX, *[str(a) for a in args]]
    last = None
    for attempt in range(attempts):
        fo = open(stdout_path, "wb") if stdout_path is not None else None
        p = subprocess.Popen(cmd, cwd=str(cwd), stdout=fo if fo else subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True)       # own process group: a timeout kills starter + fuse mount too
        try:
            o, e = p.communicate(timeout=timeout)
            out = None if fo else o.decode(errors="replace")
            err = e.decode(errors="replace")
            last = {"rc": p.returncode, "stderr": err[-600:], "stdout": out}
            if p.returncode in ok_rc:
                return last, attempt + 1, " ".join(cmd)
        except subprocess.TimeoutExpired:
            C.killpg_quietly(p); C.reap_bounded(p)
            last = {"rc": -9, "stderr": f"timeout after {timeout} s (process group killed)", "stdout": None}
        finally:
            if fo:
                fo.close()
        time.sleep(15 * (attempt + 1))
    raise MBFailure(f"MB-System call failed after {attempts} attempts: rc={last['rc']} stderr={last['stderr'][-300:]!r} "
                    f"(cwd={cwd}): {' '.join(map(str, args))[:300]}")


def mb_cmdline(args) -> str:
    return C.mb_cmdline(args)


# --------------------------------------------------------------------------- #
# geometry helpers (local metric projections)
# --------------------------------------------------------------------------- #
def utm_epsg(lon: float, lat: float) -> int:
    z = int((((lon + 180) % 360) // 6) + 1)
    z = min(max(z, 1), 60)
    return (32600 if lat >= 0 else 32700) + z


def aeqd_crs(lon: float, lat: float) -> str:
    return f"+proj=aeqd +lat_0={lat:.6f} +lon_0={lon:.6f} +datum=WGS84 +units=m +no_defs"


def spherical_centroid(geom):
    """Representative lon/lat of a (possibly antimeridian-split, multi-part) 4326 geometry: area-weighted mean
    of the part centroids as unit vectors (a plain 4326 centroid of a part at +179 and one at -179 is at 0)."""
    parts = list(getattr(geom, "geoms", [geom]))
    vx = vy = vz = 0.0
    for p in parts:
        if p.is_empty:
            continue
        c = p.centroid; w = max(p.area, 1e-12)
        la, lo = math.radians(c.y), math.radians(c.x)
        vx += w * math.cos(la) * math.cos(lo); vy += w * math.cos(la) * math.sin(lo); vz += w * math.sin(la)
    n = math.sqrt(vx * vx + vy * vy + vz * vz)
    if n == 0:
        return float("nan"), float("nan")
    return math.degrees(math.atan2(vy, vx)), math.degrees(math.asin(vz / n))
