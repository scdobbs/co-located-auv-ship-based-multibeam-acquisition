"""ACQ-R09 §3.3.1-3.3.3 — rehearsal outputs against the frozen development values (development data only).

Per development pair of the rehearsal run: the ship grid (<cruise>__union.grd) against OAK raw_lr_gridded/, the region
string against the ACQ-R02 grid record; hr.tif, lr.tif, the three masks and every ship_products_v2_1 raster against OAK
harmonized/<pair>/ (CRS, transform, shape, nodata, NaN pattern, max |difference|; bit-identical or within the R10 accepted
float tolerance 1e-6 absolute, R10b H3; file sha256 equality reported separately); hr/lr native, res_ratio, k, k status,
per-k verdicts against manifest v2.1 and the ACQ-R02 harmonize record; ship_products_usable and the v2.1 flags against
manifest v2.1 / the development products.json; co-registration shift, overlap and tile count against the ACQ-R02 record.
Also: the repeat-survey pick of the mock record (§3.3.2) and the supplement schema against the Phase 4 supplement (§3.3.3).
Usage: python -m src.phase5.compare_p5 --run-record <step1_run_rehearsal_<tag>.json> [--out <json>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from src.acq_r01 import common as C
from src.phase5 import common_p5 as P

TOL = 1e-6
DEV_PAIRS = ("FK151121__MGDS_22383", "NA080__MGDS_31289", "KM0923__MGDS_31429")
R02 = P.RPG / "ACQ-R02"


def cmp_raster(a: Path, b: Path) -> dict:
    out = {"a": str(a), "b": str(b)}
    if not a.exists() or not b.exists():
        out.update({"present": [a.exists(), b.exists()], "equal": False, "within_tol": False}); return out
    with rasterio.open(a) as x, rasterio.open(b) as y:
        geo = {"crs": x.crs == y.crs, "transform": tuple(x.transform) == tuple(y.transform), "shape": x.shape == y.shape, "nodata": (x.nodata == y.nodata) or (x.nodata != x.nodata and y.nodata != y.nodata),
               "dtype": x.dtypes[0] == y.dtypes[0]}
        out["georef"] = geo
        if not geo["shape"]:
            out.update({"equal": False, "within_tol": False, "shape": [x.shape, y.shape]}); return out
        u = x.read(1).astype("float64"); v = y.read(1).astype("float64")
    if x.nodata is not None and np.isfinite(x.nodata):
        u[u == x.nodata] = np.nan
    if y.nodata is not None and np.isfinite(y.nodata):
        v[v == y.nodata] = np.nan
    nan_eq = bool(np.array_equal(np.isnan(u), np.isnan(v)))
    both = np.isfinite(u) & np.isfinite(v)
    d = float(np.max(np.abs(u[both] - v[both]))) if both.any() else 0.0
    eq = bool(np.array_equal(u, v, equal_nan=True))
    out.update({"nan_pattern_equal": nan_eq, "n_valid": int(both.sum()), "n_nan_mismatch": int((np.isnan(u) != np.isnan(v)).sum()), "max_abs_diff": d,
                "equal": eq and all(geo.values()), "within_tol": nan_eq and d <= TOL and all(geo.values()), "file_sha256_equal": P.sha256_file(a) == P.sha256_file(b)})
    return out


def compare_pair(pid: str, rec: dict, out_root: Path, man: pd.DataFrame) -> dict:
    cruise = pid.split("__")[0]
    reh = out_root / "harmonized" / pid; dev = C.OAK / "harmonized" / pid
    grid_rec = json.loads((R02 / "grid" / f"{cruise}.json").read_text())
    harm_rec = json.loads((R02 / "harmonize" / f"{pid}.json").read_text())
    srec = json.loads((reh / "site_record.json").read_text())
    res = {"pair_id": pid}
    res["ship_grid"] = cmp_raster(out_root / "raw_lr_gridded" / pid / f"{cruise}__union.grd", C.OAK / "raw_lr_gridded" / f"{cruise}__union.grd")
    res["region_equal_dev"] = srec["grid"]["region"] == grid_rec["region"]
    res["region"] = {"rehearsal": srec["grid"]["region"], "dev": grid_rec["region"], "rule": srec["grid"].get("region_rule"), "choice": srec["grid"].get("region_choice")}
    res["cell_m"] = {"rehearsal": srec["grid"]["cell_m"], "dev": grid_rec["cell_m"], "equal": srec["grid"]["cell_m"] == grid_rec["cell_m"]}
    res["n_swath_files"] = {"rehearsal": srec["grid"]["n_files"], "dev": grid_rec["n_files"], "equal": srec["grid"]["n_files"] == grid_rec["n_files"]}
    rasters = {}
    for n in ("hr.tif", "lr.tif", "hr_valid.tif", "lr_valid.tif", "joint_valid.tif"):
        rasters[n] = cmp_raster(reh / n, dev / n)
    pdir_r, pdir_d = reh / "ship_products_v2_1", dev / "ship_products_v2_1"
    if pdir_r.exists() and pdir_d.exists():
        for f in sorted(pdir_d.glob("*.tif")):
            rasters[f"ship_products_v2_1/{f.name}"] = cmp_raster(pdir_r / f.name, f)
    res["rasters"] = rasters
    m = man.set_index("pair_id").loc[pid]
    pp = rec["per_pair"][pid]
    dev_flags = json.loads((pdir_d / "products.json").read_text())["qa_vs_lr_tif"]["flags"] if (pdir_d / "products.json").exists() else None
    vals = {"hr_native_res_m": (pp["hr_native_res_m"], float(m["hr_native_res_m"])), "lr_native_res_m": (pp["lr_native_res_m"], float(m["lr_native_res_m"])),
            "res_ratio": (pp["res_ratio"], float(m["res_ratio"])), "max_recoverable_k": (pp["max_recoverable_k"], int(m["max_recoverable_k"]) if pd.notna(m["max_recoverable_k"]) else None),
            "k_sweep_status": (pp["k_sweep_status"], m["k_sweep_status"]),
            "per_k": ({str(k): v for k, v in (pp["per_k"] or {}).items()}, {str(k): v for k, v in (harm_rec["k_sweep"].get("per_k") or {}).items()}),
            "ship_products_usable": (pp["ship_products_usable"], bool(m["ship_products_usable"])), "flags": (sorted(pp["flags"] or []), sorted(dev_flags or [])),
            "coreg_dx_dy_dz": ([srec["harmonize"]["coreg"].get(k) for k in ("dx_m", "dy_m", "dz_m")], [harm_rec["coreg"].get(k) for k in ("dx_m", "dy_m", "dz_m")]),
            "overlap_km2": (srec["harmonize"].get("overlap_km2"), harm_rec.get("overlap_km2")), "n_valid_tiles_256": (srec["harmonize"].get("n_valid_tiles_256"), harm_rec.get("n_valid_tiles_256")),
            "target_crs": (srec["harmonize"].get("target_crs"), harm_rec.get("target_crs"))}
    res["values"] = {k: {"rehearsal": a, "dev": b, "equal": a == b} for k, (a, b) in vals.items()}
    res["all_rasters_equal"] = all(r.get("equal") for r in rasters.values())
    res["all_rasters_within_tol"] = all(r.get("within_tol") for r in rasters.values())
    res["all_values_equal"] = all(v["equal"] for v in res["values"].values())
    res["ship_grid_equal"] = bool(res["ship_grid"].get("equal"))
    res["eligibility"] = {k: pp[k] for k in ("coreg_pass", "k_recoverable", "cells_across", "hr_res_in_range", "eligible", "eligibility_reason")}
    return res


def repeat_check(rec: dict, out_root: Path) -> dict:
    lay = json.loads((P.REHEARSAL_DIR / "mock_layout.json").read_text())
    exp = lay["expected_repeat_rule"]
    pid = [p for p in rec["per_pair"] if "MOCK_R09repeat" in p]
    if not pid:
        return {"present": False, "passed": False}
    sel = json.loads((out_root / "harmonized" / pid[0] / "hr_selection.json").read_text())
    kept = sel["kept"]; dropped = [f for f, g in sel["grids"].items() if g.get("status") == "dropped"]
    return {"pair_id": pid[0], "expected": exp, "kept": kept, "dropped": dropped, "decisions": {f: g.get("reason") for f, g in sel["grids"].items()},
            "passed": kept == exp["kept"] and sorted(dropped) == sorted(exp["dropped"])}


def schema_check(sup: Path) -> dict:
    import pyarrow.parquet as pq
    s4 = [(f.name, str(f.type)) for f in pq.read_schema(P.SUPPLEMENT_PHASE4)]
    s5 = [(f.name, str(f.type)) for f in pq.read_schema(sup)]
    return {"phase4_n": len(s4), "phase5_n": len(s5), "first_64_equal": s5[:len(s4)] == s4, "extra": s5[len(s4):],
            "passed": s5[:len(s4)] == s4 and [n for n, _ in s5[len(s4):]] == ["coreg_pass", "k_recoverable", "cells_across", "hr_res_in_range", "eligible", "eligibility_reason"]}


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--run-record", required=True); ap.add_argument("--out", default=None)
    ap.add_argument("--pairs", default=",".join(DEV_PAIRS))
    a = ap.parse_args(argv)
    rec = json.loads(Path(a.run_record).read_text())
    out_root = Path(rec["out_root"])
    man = pd.read_parquet(P.REPO / "manifest" / "pairs_v2_1.parquet")
    pairs = [p for p in a.pairs.split(",") if p in rec["per_pair"]]
    res = {"generated": P.utc_now(), "run_record": a.run_record, "run_record_sha256": P.sha256_file(a.run_record), "tolerance_abs": TOL,
           "tolerance_basis": "R10 accepted float tolerance: 1e-6 absolute (R10b ruling H3)", "pairs": {p: compare_pair(p, rec, out_root, man) for p in pairs}}
    res["repeat_rule"] = repeat_check(rec, out_root)
    res["supplement_schema"] = schema_check(Path(rec["supplement"]))
    out = Path(a.out) if a.out else P.REHEARSAL_DIR / f"compare_{rec['run_tag']}.json"
    P.write_json(out, res, mode=0o644)
    for p, r in res["pairs"].items():
        bad_r = [k for k, v in r["rasters"].items() if not v.get("equal")]
        bad_v = [k for k, v in r["values"].items() if not v["equal"]]
        print(f"{p}: ship grid equal {r['ship_grid_equal']} (region equal {r['region_equal_dev']}); rasters equal {r['all_rasters_equal']} "
              f"(within 1e-6 {r['all_rasters_within_tol']}; not equal {bad_r}); values equal {r['all_values_equal']} (differ {bad_v})")
    print("repeat rule", res["repeat_rule"].get("passed"), res["repeat_rule"].get("kept"), "| schema", res["supplement_schema"]["passed"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
