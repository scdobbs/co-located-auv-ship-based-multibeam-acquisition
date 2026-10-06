"""ACQ-R04 node runner (2026-10-04 fix for container overload on shared serc nodes).

One Slurm array task = one whole node (--exclusive), processing its share of the remaining cruises PARALLEL at a time
(default 2), each as `python -m src.acq_r04.blocks --cruise X --grid-workers 2 --prod-workers 1`.  Container calls
per node are therefore bounded: PARALLEL x (2 gridding (or 1 coverage) + 1 product) = 6 at most (ACQ-R03 lesson: concurrent
apptainer starts fail/hang under fuse-overlayfs when ~8+ start at once on one node).
Share: the cruise list is split over NSLOTS by greedy longest-processing-time on advertised bytes (deterministic).
Per cruise: skipped if its cruise_record.json exists (done); otherwise any partial block directories left by the
cancelled overloaded run are MOVED (not deleted) to pretrain_v1_stage/_aborted_2026-10-04/<cruise>/, then the cruise is
run with a wall cap (CRUISE_CAP_S); a cruise exceeding it is killed as a process group and recorded in
cruise_failure.json (loud).  Writes logs/acq_r04_node_<job>_<task>_<cruise>.log.
Usage (Slurm array): python -m src.acq_r04.node_runner --list <file> --slot $SLURM_ARRAY_TASK_ID --nslots N
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r04.blocks import cdir_name

CRUISE_CAP_S = 24 * 3600
PY = "/home/users/scdobbs/bathy_diffusion_env/bin/python"
ABORTED = R.STAGE / "_aborted_2026-10-04"


def share(cruises, slot, nslots):
    sel = pd.read_csv(R.REPORT_DIR / "selection_v1.csv").set_index("cruise")
    order = sorted(cruises, key=lambda c: (-int(sel.loc[c, "advertised_bytes"]), c))
    load = [0] * nslots; out = [[] for _ in range(nslots)]
    for c in order:
        i = min(range(nslots), key=lambda k: (load[k], k))
        out[i].append(c); load[i] += int(sel.loc[c, "advertised_bytes"])
    return out[slot]


GRID_W, PROD_W = 2, 1


def run_one(c, tag):
    cd = cdir_name(c)
    if (R.WORK_LOGS / cd / "cruise_record.json").exists():
        return c, "already_done"
    st = R.STAGE / cd
    if st.exists():
        dst = ABORTED / cd
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst = ABORTED / f"{cd}__{int(time.time())}"
        st.rename(dst)
    old = R.WORK_LOGS / cd / "cruise_failure.json"
    if old.exists():
        old.rename(old.with_name(f"cruise_failure_before_node_runner_{int(time.time())}.json"))
    logp = C.REPO / "logs" / f"acq_r04_node_{tag}_{cd}.log"
    t0 = time.time()
    with open(logp, "w") as lf:
        p = subprocess.Popen([PY, "-m", "src.acq_r04.blocks", "--cruise", c, "--grid-workers", str(GRID_W), "--prod-workers", str(PROD_W)],
                             cwd=str(C.REPO), stdout=lf, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            rc = p.wait(timeout=CRUISE_CAP_S)
        except subprocess.TimeoutExpired:
            C.killpg_quietly(p); C.reap_bounded(p)
            R.write_json(R.WORK_LOGS / cd / "cruise_failure.json",
                         {"cruise": c, "error": f"CruiseWallCap: exceeded {CRUISE_CAP_S} s in node_runner; process group killed", "at": R.utc_now()})
            return c, "wall_cap"
    return c, f"rc={rc} wall={time.time() - t0:.0f}s"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True); ap.add_argument("--slot", type=int, required=True); ap.add_argument("--nslots", type=int, required=True)
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--grid-workers", type=int, default=2); ap.add_argument("--prod-workers", type=int, default=1)
    a = ap.parse_args(argv)
    global GRID_W, PROD_W
    GRID_W, PROD_W = a.grid_workers, a.prod_workers
    cruises = [l.strip() for l in open(a.list) if l.strip()]
    C.assert_no_lockbox_cruise(cruises)
    mine = share(cruises, a.slot, a.nslots)
    tag = f"{os.environ.get('SLURM_ARRAY_JOB_ID', 'x')}_{a.slot}"
    print(f"{R.utc_now()} slot {a.slot}/{a.nslots} host {os.uname().nodename}: {len(mine)} cruises: {mine}", flush=True)
    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        for c, status in ex.map(lambda c: run_one(c, tag), mine):
            print(f"{R.utc_now()} {c}: {status}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
