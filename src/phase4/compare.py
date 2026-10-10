"""ACQ-R06 Part B2 — compare the rehearsal outputs with manifest v2.1 and the existing files on OAK.

Per rehearsal pair: hr/lr native spacings and k / status vs the manifest row; the seven product rasters vs the pair's
ship_products_v2_1/ (NaN pattern identical, max |difference| <= 1e-6); products.json QA numbers and flags; the swath
file list read vs the recorded one; the supplement row vs the manifest row, column by column.
Usage: python -m src.phase4.compare --run-tag full
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

from src.acq_r01 import common as C
from src.acq_r01.build_products_v2 import RASTERS_V2
from src.phase4 import common as P

QA_NUM = ("n_common_cells", "median_offset_m", "rms_m", "robust_sigma_m", "rms_over_median_s_lr", "robust_sigma_over_median_s_lr",
          "sigma0_m", "sigma_argmin_m", "gain_m")
TOL = 1e-6


def _isnan(x):
    return x is None or (isinstance(x, float) and math.isnan(x))


def _eq(a, b):
    if _isnan(a) and _isnan(b):
        return True
    if _isnan(a) or _isnan(b):
        return False
    if isinstance(a, (int, float, np.integer, np.floating)) and isinstance(b, (int, float, np.integer, np.floating)):
        return abs(float(a) - float(b)) <= TOL
    return a == b


def _ndp(x: float) -> int:
    s = repr(float(x))
    return len(s.split(".")[1]) if "." in s else 0


def spacing_cmp(name, computed, manifest_value):
    """Identical at the manifest's recorded precision (June rows hold 1 dp, ACQ-R02 rows 2–3 dp)?"""
    if _isnan(manifest_value):
        return {"quantity": name, "computed": computed, "manifest": None, "identical": None, "diff": None}
    nd = _ndp(manifest_value)
    ident = round(float(computed), nd) == round(float(manifest_value), nd) and abs(float(computed) - float(manifest_value)) < 0.5 * 10 ** (-nd) + 1e-9
    return {"quantity": name, "computed": computed, "manifest": float(manifest_value), "identical": bool(ident), "diff": round(float(computed) - float(manifest_value), 4), "manifest_ndp": nd}


def raster_cmp(new: Path, old: Path) -> dict:
    with rasterio.open(new) as a, rasterio.open(old) as b:
        if (a.height, a.width) != (b.height, b.width) or a.crs != b.crs or a.transform != b.transform:
            return {"identical_grid": False, "nan_identical": False, "max_abs_diff": None, "note": f"grid differs: {a.shape} vs {b.shape}"}
        x = a.read(1).astype("float64"); y = b.read(1).astype("float64")
    nx, ny = np.isnan(x), np.isnan(y)
    nan_same = bool(np.array_equal(nx, ny)); both = ~nx & ~ny
    d = float(np.max(np.abs(x[both] - y[both]))) if both.any() else 0.0
    return {"identical_grid": True, "nan_identical": nan_same, "n_nan_mismatch": int((nx != ny).sum()), "max_abs_diff": d, "within_1e-6": bool(nan_same and d <= TOL),
            "bit_identical": bool(np.array_equal(x, y, equal_nan=True))}


def compare_pair(pid: str, out_root: Path, m: pd.DataFrame, sup: pd.DataFrame) -> dict:
    row = m.loc[pid]; rel = str(row["harmonized_path"])
    od = out_root / rel; rec = json.loads((od / "step1_record.json").read_text())
    c2a, sw, pr = rec["c2a"], rec["sweep"], rec.get("products")
    res = {"pair_id": pid, "unit": row.get("leakage_unit"), "designation": row.get("designation"), "wall_s": rec.get("wall_s"), "cpu_model": rec.get("cpu_model"), "host": rec.get("host")}
    res["spacings"] = [spacing_cmp("hr_native_res_m", c2a["hr_native_res_m"], row["hr_native_res_m"]), spacing_cmp("lr_native_res_m", c2a["lr_native_res_m"], row["lr_native_res_m"])]
    res["c2a"] = {k: c2a[k] for k in ("beam_footprint_m", "posting_m", "depth_m", "depth_basis", "beamwidth_deg", "beamwidth_key", "sonar", "sonar_source")}
    k_new = sw.get("max_recoverable_k"); k_old = row.get("max_recoverable_k")
    res["k"] = {"computed": k_new, "manifest": None if _isnan(k_old) else int(k_old), "identical": (_isnan(k_old) and k_new is None) or (not _isnan(k_old) and k_new is not None and int(k_old) == int(k_new)),
                "status_computed": sw.get("status"), "status_manifest": row.get("k_sweep_status"), "status_identical": sw.get("status") == row.get("k_sweep_status"),
                "k_source": sw.get("k_source"), "per_k": sw.get("per_k")}
    # products
    old = C.OAK / rel / "ship_products_v2_1"; new = od / "ship_products_v2_1"
    if pr is None:
        res["products"] = {"built": False, "note": "no k: nothing built (rule C3)", "existing_products_on_oak": old.exists(), "comparison": "reports no k" }
    elif not pr.get("available"):
        res["products"] = {"built": False, "note": f"unavailable: {pr.get('reason') or pr.get('unavailable_reason')}", "existing_products_on_oak": old.exists()}
    else:
        rc = {}
        for name in RASTERS_V2:
            po, pn = old / f"{name}.tif", new / f"{name}.tif"
            rc[name] = raster_cmp(pn, po) if (po.exists() and pn.exists()) else {"note": f"missing: existing={po.exists()} rehearsal={pn.exists()}"}
        pj_old = json.loads((old / "products.json").read_text()); pj_new = json.loads((new / "products.json").read_text())
        qo, qn = pj_old["qa_vs_lr_tif"], pj_new["qa_vs_lr_tif"]
        qa = {k: {"existing": qo.get(k), "rehearsal": qn.get(k), "within_1e-6": _eq(qo.get(k), qn.get(k))} for k in QA_NUM}
        qa["shift_argmin_cells"] = {"existing": qo.get("shift_argmin_cells"), "rehearsal": qn.get("shift_argmin_cells"), "within_1e-6": qo.get("shift_argmin_cells") == qn.get("shift_argmin_cells")}
        fo = sorted(qo.get("flags") or []); fn = sorted(qn.get("flags") or [])
        files_old = {f["name"] for f in pj_old["source"]["files"]}; files_new = {f["name"] for f in pj_new["source"]["files"]}
        res["products"] = {"built": True, "rasters": rc, "all_rasters_nan_identical": all(v.get("nan_identical") for v in rc.values()),
                           "all_rasters_within_1e-6": all(v.get("within_1e-6") for v in rc.values()), "max_abs_diff_over_rasters": max((v.get("max_abs_diff") or 0.0) for v in rc.values()),
                           "all_rasters_bit_identical": all(v.get("bit_identical") for v in rc.values()),
                           "qa": qa, "qa_all_within_1e-6": all(v["within_1e-6"] for v in qa.values()), "flags_existing": fo, "flags_rehearsal": fn, "flags_identical": fo == fn,
                           "s_lr_source_existing": qo.get("s_lr_source"), "s_lr_source_rehearsal": qn.get("s_lr_source"),
                           "files": {"n_existing": len(files_old), "n_rehearsal": len(files_new), "same": files_old == files_new, "lost": sorted(files_old - files_new), "added": sorted(files_new - files_old),
                                     "n_read_rc0": pr.get("n_files_rc0"), "n_listed": pr.get("n_files_listed")},
                           "mb_format": {"existing": pj_old["source"]["mb_format"], "rehearsal": pj_new["source"]["mb_format"]},
                           "beam_angle_method": {"existing": pj_old.get("beam_angle_method"), "rehearsal": pj_new.get("beam_angle_method")},
                           "wall_s_products": pr.get("wall_s"), "nproc": pr.get("nproc"), "batch_files": pr.get("batch_files")}
    # supplement row vs manifest row
    srow = sup.set_index("pair_id").loc[pid]
    cols = []
    for c in m.columns:
        a, b = row.get(c), srow.get(c)
        same = _eq(a, b) if not isinstance(a, (list, np.ndarray)) else str(a) == str(b)
        cols.append({"column": c, "identical": bool(same), "manifest": None if _isnan(a) else (str(a)[:80] if not isinstance(a, (int, float, bool, np.integer, np.floating)) else a),
                     "supplement": None if _isnan(b) else (str(b)[:80] if not isinstance(b, (int, float, bool, np.integer, np.floating)) else b)})
    res["row"] = {"n_columns": len(cols), "n_identical": sum(c["identical"] for c in cols), "differing": [c for c in cols if not c["identical"]], "filled_columns": rec.get("row_filled_columns")}
    res["usable"] = {"computed": rec["usable"], "reason": rec["usable_reason"], "manifest": row.get("ship_products_usable"), "identical": bool(rec["usable"]) == bool(row.get("ship_products_usable"))}
    res["mismatch_k_or_lr_native"] = bool((not res["spacings"][1]["identical"]) or (not res["k"]["identical"]))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--run-tag", default="full")
    a = ap.parse_args(argv)
    P.check_fixed_inputs()
    run = json.loads((P.REHEARSAL_DIR / f"step1_run_rehearsal_{a.run_tag}.json").read_text())
    out_root = Path(run["out_root"]); m = P.manifest().set_index("pair_id")
    sup = pd.read_parquet(run["supplement"])
    pairs = run["pairs_done"]
    res = [compare_pair(p, out_root, m, sup) for p in pairs]
    summ = {"generated": P.utc_now(), "run_tag": a.run_tag, "run_record": str(P.REHEARSAL_DIR / f"step1_run_rehearsal_{a.run_tag}.json"), "n_pairs": len(res),
            "n_hr_identical": sum(r["spacings"][0]["identical"] for r in res), "n_lr_identical": sum(r["spacings"][1]["identical"] for r in res),
            "n_k_identical": sum(r["k"]["identical"] for r in res), "n_status_identical": sum(r["k"]["status_identical"] for r in res),
            "mismatches": [r["pair_id"] for r in res if r["mismatch_k_or_lr_native"]],
            "n_products_built": sum(1 for r in res if r["products"].get("built")), "n_products_rasters_within_1e-6": sum(1 for r in res if r["products"].get("all_rasters_within_1e-6")),
            "n_products_bit_identical": sum(1 for r in res if r["products"].get("all_rasters_bit_identical")),
            "n_products_qa_within_1e-6": sum(1 for r in res if r["products"].get("qa_all_within_1e-6")), "n_products_flags_identical": sum(1 for r in res if r["products"].get("flags_identical")),
            "n_products_files_same": sum(1 for r in res if r["products"].get("files", {}).get("same")),
            "products_not_matching": [r["pair_id"] for r in res if r["products"].get("built") and not (r["products"].get("all_rasters_within_1e-6") and r["products"].get("qa_all_within_1e-6") and r["products"].get("flags_identical") and r["products"].get("files", {}).get("same"))],
            "n_usable_identical": sum(r["usable"]["identical"] for r in res), "supplement_sha256": run.get("supplement_sha256"), "cpu_models": sorted({r["cpu_model"] for r in res}),
            "wall_s_total": run.get("wall_s"), "pairs": res, "code_commit": P.git_commit()}
    P.write_json(P.REHEARSAL_DIR / f"compare_{a.run_tag}.json", summ, mode=0o644)
    for r in res:
        s = r["spacings"]; pr = r["products"]
        print(f"{r['pair_id']:28s} hr {s[0]['computed']}/{s[0]['manifest']} {'=' if s[0]['identical'] else 'X'}  lr {s[1]['computed']}/{s[1]['manifest']} {'=' if s[1]['identical'] else 'X'}  "
              f"k {r['k']['computed']}/{r['k']['manifest']} {'=' if r['k']['identical'] else 'X'} {r['k']['status_computed']}/{r['k']['status_manifest']}  "
              f"products {'built' if pr.get('built') else 'none'} rasters<=1e-6 {pr.get('all_rasters_within_1e-6')} bit {pr.get('all_rasters_bit_identical')} qa {pr.get('qa_all_within_1e-6')} flags {pr.get('flags_identical')} files {pr.get('files', {}).get('same')} "
              f"usable {r['usable']['computed']}/{r['usable']['manifest']}  wall {r['wall_s']} s")
    print(json.dumps({k: v for k, v in summ.items() if k not in ("pairs",)}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
