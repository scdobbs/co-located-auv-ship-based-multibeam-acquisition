"""ACQ-R01 §4 — designate new candidate leakage units as development / confirmatory.

Run ONCE, before any new unit's data is examined.

  input  : reports_post_grl_review/ACQ-R01/discovery_rerun/new_units.json (§3 output; metadata only;
           units sharing acquisition with a lockbox pair are already excluded there)
  strata : by setting class; a stratum with a single unit is merged with the other singleton
           strata of the same basin (stated in the output); a stratum still alone is merged into
           one 'merged:all' stratum (stated).
  rule   : within each stratum, sort by unit_id, shuffle with numpy default_rng(SEED),
           first floor(n/2) -> development, the rest -> confirmatory (odd n -> extra to confirmatory).
  output : designation.csv, designation.json (with sha256 of input and output), printed table.

Binding rules (ACQ-R01 §4.3): a unit that later fails acquisition or QA is DROPPED from its set,
never reassigned; no model/baseline/target value on a confirmatory unit before Phase 4; units from a
later discovery run go through this script with a NEW seed, recorded.

Usage: python -m src.acq_r01.designate_confirmatory --seed 20260929 [--input path]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.acq_r01 import common as C


def designate(units: list[dict], seed: int):
    rng = np.random.default_rng(seed)
    by_setting = defaultdict(list)
    for u in units:
        by_setting[u["setting"]].append(u)
    strata, merges = {}, []
    singles = [u for s, us in by_setting.items() if len(us) == 1 for u in us]
    for s, us in by_setting.items():
        if len(us) > 1:
            strata[s] = us
    by_basin = defaultdict(list)
    for u in singles:
        by_basin[u["basin"]].append(u)
    leftover = []
    for b, us in by_basin.items():
        if len(us) > 1:
            strata[f"merged:{b}"] = us; merges.append(f"singleton settings {sorted({u['setting'] for u in us})} merged by basin {b}")
        else:
            leftover += us
    if leftover:
        if len(leftover) > 1 or not strata:
            strata["merged:all"] = leftover; merges.append(f"singleton units {[u['unit_id'] for u in leftover]} merged into one stratum (no basin partner)")
        else:
            # one leftover singleton: attach to the largest stratum and say so
            k = max(strata, key=lambda s: len(strata[s]))
            strata[k] = strata[k] + leftover; merges.append(f"singleton {leftover[0]['unit_id']} ({leftover[0]['setting']}, {leftover[0]['basin']}) attached to stratum {k}")
    rows = []
    for s in sorted(strata):
        us = sorted(strata[s], key=lambda u: u["unit_id"])
        order = rng.permutation(len(us))
        n_dev = len(us) // 2
        for i, j in enumerate(order):
            u = us[j]
            rows.append({"unit_id": u["unit_id"], "stratum": s, "setting": u["setting"], "basin": u["basin"],
                         "assignment": "development" if i < n_dev else "confirmatory",
                         "members": ";".join(u["members"]), "ship_cruises": ";".join(u["ship_cruises"])})
    return pd.DataFrame(rows), merges


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--input", default=str(C.REPORT_DIR / "discovery_rerun" / "new_units.json"))
    ap.add_argument("--out", default=str(C.REPORT_DIR / "designation"))
    a = ap.parse_args(argv)
    inp = json.loads(open(a.input).read())
    units = inp["units"]
    from pathlib import Path
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    df, merges = designate(units, a.seed)
    csv = out / "designation.csv"
    df.to_csv(csv, index=False)
    meta = {"seed": a.seed, "run_at": datetime.now(timezone.utc).isoformat(), "input": a.input,
            "input_sha256": C.sha256_file(a.input), "output_csv": str(csv), "output_sha256": C.sha256_file(csv),
            "n_units": len(df), "n_development": int((df.assignment == "development").sum()),
            "n_confirmatory": int((df.assignment == "confirmatory").sum()), "strata_merges": merges,
            "code_commit": C.git_commit(), "rules": ["failed unit is dropped from its set, never reassigned",
                                                     "no model/baseline/target value on confirmatory units before Phase 4",
                                                     "later discovery runs re-run this script with a new recorded seed"]}
    C.write_json(out / "designation.json", meta)
    print(df.to_string()); print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
