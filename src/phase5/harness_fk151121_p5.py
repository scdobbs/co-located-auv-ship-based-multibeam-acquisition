"""ACQ-R09 ruling S3 — FK151121 isolation harness (rehearsal support only; never part of a phase5 run).

FK151121's development ship grid was made by grid_lr before commit 4122090 (no grid_region patch-cluster cut: region
= the whole HR-footprint box, footprint depth over that box).  The entry script uses the current rule, so its FK151121
grid cannot equal the frozen one.  This harness runs the same Phase 5 per-site code (sealed_step1_p5.run_site) on the
mock FK151121 record with exactly one change — chain_p5.grid_ship(region_rule="whole_footprint_pre_4122090") — and
compares the outputs with the frozen development values (compare_p5).  If they are equal, the region rule is the only
cause of the rehearsal difference.
Usage: python -m src.phase5.harness_fk151121_p5 --run-tag <tag>
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.phase5 import common_p5 as P
from src.phase5 import guard_p5 as GP
from src.phase5 import chain_p5 as CH
from src.phase5 import sealed_step1_p5 as S
from src.phase5 import compare_p5 as CMP

PID = "FK151121__MGDS_22383"


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--run-tag", required=True); ap.add_argument("--nproc", type=int, default=6)
    a = ap.parse_args(argv)
    site = [s for s in P.read_site_list(P.MOCK_SITE_LIST) if s["pair_id"] == PID][0]
    cfg = dict(S.MODES["rehearsal"]); cfg["mode"] = "rehearsal"
    out_root = P.REHEARSAL_OUT / f"{a.run_tag}_fk151121_isolation"
    work_root = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_p5_harness"
    orig = CH.grid_ship
    CH.grid_ship = functools.partial(orig, region_rule="whole_footprint_pre_4122090")
    GP.install_phase5_allowance([site["token"]], cfg["sealed_root"], [out_root, work_root], reason="ACQ-R09 rehearsal (mock root, development data): FK151121 isolation harness")
    ledger = []
    try:
        rec = S.run_site(site, cfg, out_root, work_root, SimpleNamespace(nproc=a.nproc, batch_files=1), ledger)
    finally:
        GP.remove_phase5_allowance(); CH.grid_ship = orig
    e = S.per_pair_entry(rec)
    run = {"run_tag": f"{a.run_tag}_fk151121_isolation", "out_root": str(out_root), "per_pair": {PID: e}, "supplement": None}
    man = pd.read_parquet(P.REPO / "manifest" / "pairs_v2_1.parquet")
    res = {"generated": P.utc_now(), "purpose": "ruling S3 isolation: the Phase 5 per-site code with the pre-4122090 region rule for FK151121",
           "code_commit": P.git_commit(), "region_rule": "whole_footprint_pre_4122090", "per_pair": e, "ledger": ledger,
           "comparison": CMP.compare_pair(PID, run, out_root, man)}
    P.write_json(P.REHEARSAL_DIR / f"harness_fk151121_{a.run_tag}.json", res, mode=0o644)
    c = res["comparison"]
    print(f"{PID} (pre-4122090 region): region equal {c['region_equal_dev']}, ship grid equal {c['ship_grid_equal']}, rasters equal {c['all_rasters_equal']} "
          f"(within 1e-6 {c['all_rasters_within_tol']}), values equal {c['all_values_equal']} "
          f"{[k for k, v in c['values'].items() if not v['equal']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
