"""ACQ-R06b B1 — compare the rerun (run tag r06b) with the ACQ-R06 rehearsal (run tag full): spacings, k, status,
per-k verdicts, product rasters (bit-identical), QA numbers and flags, supplement columns.
Usage: python -m src.phase4.compare_runs --new r06b --old full
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from src.acq_r01.build_products_v2 import RASTERS_V2
from src.phase4 import common as P

QA_KEYS = ("n_common_cells", "median_offset_m", "rms_m", "robust_sigma_m", "rms_over_median_s_lr", "robust_sigma_over_median_s_lr",
           "sigma0_m", "sigma_argmin_m", "gain_m", "shift_argmin_cells", "flags")


def _isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def _eq(a, b):
    if _isnan(a) and _isnan(b):
        return True
    if isinstance(a, (int, float, np.integer, np.floating)) and isinstance(b, (int, float, np.integer, np.floating)):
        return abs(float(a) - float(b)) <= 1e-9
    return str(a) == str(b)


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--new", default="r06b"); ap.add_argument("--old", default="full")
    a = ap.parse_args(argv)
    P.check_fixed_inputs()
    new = json.loads((P.REHEARSAL_DIR / f"step1_run_rehearsal_{a.new}.json").read_text())
    old = json.loads((P.REHEARSAL_DIR_R06 / f"step1_run_rehearsal_{a.old}.json").read_text())
    nroot, oroot = Path(new["out_root"]), Path(old["out_root"])
    if not oroot.exists():
        oroot = P.OAK_R06_REHEARSAL / "rehearsal_outputs" / a.old
    sn = pd.read_parquet(new["supplement"]).set_index("pair_id"); so = pd.read_parquet(old["supplement"]).set_index("pair_id")
    m = P.manifest().set_index("pair_id")
    res = []
    for pid in new["pairs_done"]:
        rel = str(m.loc[pid]["harmonized_path"])
        rn = json.loads((nroot / rel / "step1_record.json").read_text()); ro = json.loads((oroot / rel / "step1_record.json").read_text())
        r = {"pair_id": pid}
        r["spacings_k"] = {k: {"r06b": rn["c2a"].get(k) if k in rn["c2a"] else rn["sweep"].get(k), "r06": ro["c2a"].get(k) if k in ro["c2a"] else ro["sweep"].get(k)}
                           for k in ("hr_native_res_m", "lr_native_res_m", "max_recoverable_k", "status", "per_k")}
        for k, v in r["spacings_k"].items():
            v["equal"] = _eq(v["r06b"], v["r06"]) if k != "per_k" else (v["r06b"] == v["r06"])
        r["spacings_k_equal"] = all(v["equal"] for v in r["spacings_k"].values())
        pn, po = rn.get("products"), ro.get("products")
        if pn and pn.get("available"):
            rc = {}
            for name in RASTERS_V2:
                with rasterio.open(nroot / rel / "ship_products_v2_1" / f"{name}.tif") as x, rasterio.open(oroot / rel / "ship_products_v2_1" / f"{name}.tif") as y:
                    rc[name] = bool(np.array_equal(x.read(1), y.read(1), equal_nan=True) and x.transform == y.transform and x.crs == y.crs)
            qn, qo = pn["qa_vs_lr_tif"], po["qa_vs_lr_tif"]
            qa = {k: {"r06b": qn.get(k), "r06": qo.get(k), "equal": _eq(qn.get(k), qo.get(k)) if k not in ("shift_argmin_cells", "flags") else qn.get(k) == qo.get(k)} for k in QA_KEYS}
            r["products"] = {"built_both": bool(po and po.get("available")), "rasters_bit_identical": rc, "all_rasters_bit_identical": all(rc.values()), "qa": qa,
                             "qa_all_equal": all(v["equal"] for v in qa.values()), "files_same": set(f["name"] for f in json.loads((nroot / rel / "ship_products_v2_1" / "products.json").read_text())["source"]["files"])
                             == set(f["name"] for f in json.loads((oroot / rel / "ship_products_v2_1" / "products.json").read_text())["source"]["files"])}
        else:
            r["products"] = {"built_both": (pn is None and po is None) or (bool(pn) == bool(po)), "note": "no products in both runs" if pn is None and po is None else f"r06b {pn} / r06 {po}"}
        diff = []
        for c in sn.columns:
            x, y = sn.loc[pid, c], so.loc[pid, c]
            same = _eq(x, y) if not isinstance(x, (list, np.ndarray)) else str(x) == str(y)
            if not same:
                diff.append({"column": c, "r06b": str(x)[:160], "r06": str(y)[:160]})
        r["supplement"] = {"n_columns": len(sn.columns), "n_differing": len(diff), "differing": diff}
        r["write_path"] = rn.get("write_path", {}) and {k: rn["write_path"][k] for k in ("mode_before", "mode_opened", "mode_after", "restored")}
        r["pass"] = bool(r["spacings_k_equal"] and r["products"].get("built_both") and (r["products"].get("all_rasters_bit_identical", True)) and r["products"].get("qa_all_equal", True)
                         and r["products"].get("files_same", True))
        res.append(r)
    summ = {"generated": P.utc_now(), "new_run": a.new, "old_run": a.old, "n_pairs": len(res), "n_pass": sum(r["pass"] for r in res), "all_pass": all(r["pass"] for r in res),
            "n_spacings_k_equal": sum(r["spacings_k_equal"] for r in res), "n_products_built": sum(1 for r in res if r["products"].get("all_rasters_bit_identical") is not None),
            "n_rasters_bit_identical": sum(1 for r in res if r["products"].get("all_rasters_bit_identical")), "n_qa_equal": sum(1 for r in res if r["products"].get("qa_all_equal")),
            "differing_columns_union": sorted({d["column"] for r in res for d in r["supplement"]["differing"]}),
            "n_rows_with_differing_columns": sum(1 for r in res if r["supplement"]["n_differing"]), "wall_s_new": new["wall_s"], "wall_s_old": old["wall_s"],
            "supplement_sha256_new": new["supplement_sha256"], "supplement_sha256_old": old["supplement_sha256"], "pairs": res, "code_commit": P.git_commit()}
    P.write_json(P.REHEARSAL_DIR / f"compare_{a.new}_vs_{a.old}.json", summ, mode=0o644)
    for r in res:
        print(f"{r['pair_id']:28s} spacings/k/verdicts {r['spacings_k_equal']}  rasters {r['products'].get('all_rasters_bit_identical')}  qa {r['products'].get('qa_all_equal')}  "
              f"supplement differing {[d['column'] for d in r['supplement']['differing']]}  pass {r['pass']}")
    print(json.dumps({k: v for k, v in summ.items() if k != "pairs"}, indent=1, default=str))
    return 0 if summ["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
