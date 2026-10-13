"""ACQ-R11 §2 — calibration of the vertical-consistency gate on development and known-bad pairs only.

Accepted set: the manifest v2.1 rows with designation == "development" (38; EW0207__MGDS_32556 is one of them), read
from their frozen OAK harmonized files (read only).  Known-bad set: AT37-05 (ruling R1), NR07-1 (ACQ-R02 H2; both HR
dives 31813 and 31814) and MGLN06MV (re-audit 2026-06-26) from whatever harmonized files exist on disk.
Also computed, informative only (not in T): the other development-designated v2.1 rows ("joins existing unit",
"ruling H1").  Lockbox and confirmatory rows are never opened (the acquisition guard is installed).
Rule (fixed by the directive): T = 2 x max(V95_rel over the accepted set); separation holds if every available
known-bad pair has V95_rel > T.
Usage: python -B -m src.acq_r11.calibrate_vcheck
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.acq_r01 import common as C          # installs the guard
from src.acq_r11 import vcheck as V      # statistic module (ran as src/phase5/vcheck_p5.py, sha256 5a2c65d4…, identical file)

OUT = C.REPO / "reports_post_grl_review" / "ACQ-R11"
KNOWN_BAD = [("AT37-05__MGDS_24043", "ruling R1 (ship_internal_inconsistency)"),
             ("NR07-1__MGDS_31813", "ACQ-R02 H2 (depth-incompatible)"),
             ("NR07-1__MGDS_31814", "ACQ-R02 H2 (depth-incompatible)"),
             ("MGLN06MV__MGDS_17700", "re-audit 2026-06-26 item 4 (~900 m)")]


def one(pid, d: Path, group, note=""):
    row = {"pair_id": pid, "set": group, "note": note, "dir": str(d)}
    need = [d / "hr.tif", d / "lr.tif", d / "joint_valid.tif"]
    miss = [p.name for p in need if not p.exists()]
    if miss:
        row.update({"status": "COULD NOT CHECK", "why": f"missing {miss}; no ship grid/swath on disk to rebuild without a network fetch" if group == "known_bad" else f"missing {miss}"})
        return row
    s = V.statistic(*need)
    if not s.get("n"):
        row.update({"status": "no joint-valid LR cell"}); return row
    row.update({"status": "ok", "n_lr_cells": s["n"], "V95_m": round(s["v95"], 4), "V95_rel": s["v95_rel"],
                "median_lr_depth_m": round(-s["lr_med_abs"], 2),
                "sha256_hr": C.sha256_file(need[0]), "sha256_lr": C.sha256_file(need[1]), "sha256_joint": C.sha256_file(need[2])})
    print(f"{group:10s} {pid:50s} n {s['n']:8d}  V95 {s['v95']:9.3f} m  V95_rel {s['v95_rel']:.6f}", flush=True)
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    m = pd.read_parquet(C.REPO / "manifest" / "pairs_v2_1.parquet")
    rows = []
    for _, r in m.iterrows():
        des = str(r["designation"])
        if des == "development":
            rows.append(one(r["pair_id"], C.OAK / r["harmonized_path"], "accepted"))
        elif des.startswith("development"):
            rows.append(one(r["pair_id"], C.OAK / r["harmonized_path"], "info", des))
    for pid, note in KNOWN_BAD:
        d = C.OAK / "harmonized" / pid
        if not (d / "hr.tif").exists() and (C.SCRATCH_DATA / "harmonized" / pid).is_dir():
            d = C.SCRATCH_DATA / "harmonized" / pid
        rows.append(one(pid, d, "known_bad", note))
    acc = [x for x in rows if x["set"] == "accepted" and x["status"] == "ok"]
    n_acc = sum(1 for x in rows if x["set"] == "accepted")
    vals = np.array([x["V95_rel"] for x in acc])
    T = 2.0 * float(vals.max())
    bad = [x for x in rows if x["set"] == "known_bad"]
    avail = [x for x in bad if x["status"] == "ok"]
    sep = bool(avail) and all(x["V95_rel"] > T for x in avail) and len(acc) == n_acc
    cols = ["pair_id", "set", "note", "status", "n_lr_cells", "V95_m", "V95_rel", "median_lr_depth_m", "sha256_hr", "sha256_lr", "sha256_joint", "dir", "why"]
    tab = OUT / "vcheck_calibration.csv"
    with open(tab, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for x in rows:
            w.writerow({k: (f"{x[k]:.6f}" if k == "V95_rel" and k in x else x.get(k, "")) for k in cols})
    rec = {"directive": "ACQ-R11 §2", "generated": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
           "statistic_module": "src/acq_r11/vcheck.py", "statistic_module_sha256": C.sha256_file(C.REPO / "src/acq_r11/vcheck.py"),
           "rule": "T = 2 x max(V95_rel over the accepted set); separation iff every available known-bad V95_rel > T",
           "n_accepted": n_acc, "n_accepted_ok": len(acc),
           "accepted_V95_rel": {"min": float(vals.min()), "median": float(np.median(vals)), "max": float(vals.max()),
                                "argmax": acc[int(vals.argmax())]["pair_id"]},
           "T": T, "known_bad": [{k: x.get(k) for k in ("pair_id", "status", "V95_m", "V95_rel", "why")} | {"above_T": (x["V95_rel"] > T) if x["status"] == "ok" else None} for x in bad],
           "n_known_bad_available": len(avail), "separation": sep,
           "table": str(tab.relative_to(C.REPO)), "table_sha256": C.sha256_file(tab)}
    (OUT / "vcheck_calibration.json").write_text(json.dumps(rec, indent=1, default=str))
    print(json.dumps({k: v for k, v in rec.items()}, indent=1, default=str))
    return 0 if sep else 5


if __name__ == "__main__":
    sys.exit(main())
