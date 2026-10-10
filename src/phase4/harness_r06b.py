"""ACQ-R06b Part B2–B4 — harness rehearsals of the fetch path, the prior-value path and the write path.

B2  fetch EW9801 (June plan) into a scratch root with the unchanged fetcher; compare names and sha256 with the OAK copy;
    the failure branch: EW9801 relabelled lockbox in an in-process manifest copy, one file withheld (404 URL), the step
    writes the pair's products as unavailable with the A2 reason and continues with the next pair; the trigger rule
    against the real OAK listing (rehearsal pair list, whole manifest); scratch fetches deleted afterwards.
B3  RR1506 relabelled lockbox in an in-process manifest copy: prior values from the row and the June record, no sweep;
    the A1 consistency check on the two lockbox pairs from records only.
B4  a scratch copy of FK151121__MGDS_22383 with the modes found (dir 2770, files 0444): the A3 sequence writes the
    products (bit-identical to ACQ-R06), pre-existing files untouched, directory mode restored; the same with a
    directory that lacks owner write (0550); the failure branch with os.chmod blocked -> rule C4 stop.
Nothing under OAK is written; the manifest copies live in the process only.  Usage (Slurm): python -m src.phase4.harness_r06b
"""
from __future__ import annotations

import json
import os
import shutil
import stat as statmod
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

from src.acq_r01 import common as C
from src.acq_r01.build_products_v2 import RASTERS_V2
from src.phase4 import common as P
from src.phase4 import sealed_step1 as S

ROOT = P.SCRATCH_ROOT / "r06b_harness"
FK = "FK151121__MGDS_22383"
R06_FULL = P.SCRATCH_ROOT / "full"                      # ACQ-R06 rehearsal outputs (scratch; also on OAK acq_r06_rehearsal/)


def cfg_rehearsal(out_root: Path) -> dict:
    cfg = dict(S.MODES["rehearsal"]); cfg["mode"] = "rehearsal"; cfg["out_root"] = out_root
    return cfg


def with_manifest(mod):
    """Run with an in-process manifest copy modified by `mod(df)`; restore afterwards.  The copy is never written."""
    class _Ctx:
        def __enter__(self):
            self.old = P._MANIFEST
            df = P.manifest().copy(); mod(df); P._MANIFEST = df
            return df

        def __exit__(self, *a):
            P._MANIFEST = self.old
    return _Ctx()


def b2_fetch() -> dict:
    out = {}
    root = ROOT / "b2"; swath_root = root / "raw_lr_swath"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    # the trigger rule against the real OAK listing
    out["trigger_rehearsal_pairs"] = {c: sorted(v) for c, v in S.fetch_trigger(P.REHEARSAL10).items()}
    m = P.manifest()
    listing = P.oak_swath_listing(); plan = P.june_plan_cruises()
    out["trigger_whole_manifest_lockbox_rule"] = {c: sorted(v) for c, v in S.fetch_trigger(list(m.pair_id)).items()}
    out["absent_from_oak_and_in_june_plan_any_designation"] = sorted({str(c) for c in m.lr_cruise.dropna() if c not in listing and c in plan})
    out["triggered_phase4_list_records_only"] = {c: sorted(v) for c, v in S.fetch_trigger(list(P.SEALED_PAIRS)).items()}
    # the fetch itself
    f = S.fetch_cruise("EW9801", swath_root, root / "fetch_logs", P.JUNE_FILE_PLAN, S.FETCH_WORKERS)
    out["fetch"] = f
    oak = C.RAW_SWATH_OAK / "EW9801"
    oak_files = {p.name: P.sha256_file(p) for p in oak.iterdir() if p.is_file() and p.name.endswith(".gz")}
    new = {p.name: P.sha256_file(p) for p in (swath_root / "EW9801").iterdir() if p.is_file() and p.name.endswith(".gz")}
    out["compare"] = {"n_oak": len(oak_files), "n_fetched": len(new), "same_names": set(oak_files) == set(new),
                      "n_byte_identical": sum(1 for k in new if oak_files.get(k) == new[k]), "differing": sorted(k for k in new if oak_files.get(k) != new[k]),
                      "modes_0444": all((swath_root / "EW9801" / k).stat().st_mode & 0o777 == 0o444 for k in new),
                      "manifest_sha_matches_oak_manifest": None}
    fm_new = json.loads((swath_root / "EW9801" / "fetch_manifest.json").read_text()); fm_oak = json.loads((oak / "fetch_manifest.json").read_text())
    sha_new = {x["filename"]: x["sha256"] for x in fm_new["files"]}; sha_oak = {(x.get("filename") or x.get("name")): x["sha256"] for x in fm_oak["files"]}
    out["compare"]["manifest_sha_matches_oak_manifest"] = sha_new == sha_oak
    out["compare"]["sha256sums_present"] = (swath_root / "EW9801" / "SHA256SUMS").exists()
    out["b2_pass"] = bool(out["compare"]["same_names"] and out["compare"]["n_byte_identical"] == 25 and f["complete"] and out["compare"]["manifest_sha_matches_oak_manifest"])
    # failure branch: EW9801 relabelled lockbox, swath root absent, one file withheld (404 URL), then the run continues (TN399)
    plan_df = pd.read_csv(P.JUNE_FILE_PLAN)
    sel = plan_df[(plan_df.cruise == "EW9801") & (plan_df.kind == "swath")].copy()
    i0 = sel.index[0]; plan_df.loc[i0, "url"] = plan_df.loc[i0, "url"] + ".withheld_by_harness"
    plan_bad = root / "plan_one_withheld.csv"; plan_df.to_csv(plan_bad, index=False)
    root_f = root / "failure"; (root_f).mkdir()
    old_plan, old_listing = P.JUNE_FILE_PLAN, P.oak_swath_listing
    P.JUNE_FILE_PLAN = plan_bad
    P.oak_swath_listing = lambda: old_listing() - {"EW9801"}        # the cruise directory 'absent' for the trigger
    ledger = []; recs = []
    try:
        with with_manifest(lambda df: df.loc[df.pair_id == "EW9801__MGDS_31425", "designation"].__setitem__(slice(None), "lockbox") or None):
            def mod(df):
                df.loc[df.pair_id == "EW9801__MGDS_31425", "designation"] = "lockbox"
            P._MANIFEST = None; df = P.manifest().copy(); mod(df); P._MANIFEST = df
            cfg = cfg_rehearsal(root_f)
            stage = root_f / "stage"
            for pid in ("EW9801__MGDS_31425", "TN399__MGDS_33068"):
                r, rec = S.run_pair(pid, cfg, root_f, 4, 1, ledger, stage_root=stage)
                recs.append(rec["summary"])
    finally:
        P.JUNE_FILE_PLAN, P.oak_swath_listing = old_plan, old_listing; P._MANIFEST = None
    s0, s1 = recs[0], recs[1]
    out["failure_branch"] = {"pairs_run": [s["pair_id"] for s in recs], "ew9801": {k: s0[k] for k in ("values_source", "max_recoverable_k", "k_source", "fetch", "products", "products_reason", "ship_products_usable")},
                             "tn399_continued": {k: s1[k] for k in ("products", "max_recoverable_k", "ship_products_usable")}, "ledger": ledger,
                             "products_json_reason": json.loads((root_f / "harmonized" / "EW9801__MGDS_31425" / "ship_products_v2_1" / "products.json").read_text())["unavailable_reason"]}
    out["failure_branch"]["pass"] = bool(s0["products"] == "unavailable" and str(s0["products_reason"]).startswith("lockbox fetch incomplete (24 of 25 files)") and s0["ship_products_usable"] is False
                                         and s0["values_source"].startswith("manifest v2.1 row") and s1["products"] == "built")
    # delete the scratch fetches (§E)
    n_del = sum(1 for p in root.rglob("*.gz")); size = sum(p.stat().st_size for p in root.rglob("*.gz"))
    shutil.rmtree(swath_root); shutil.rmtree(root_f / "raw_lr_swath", ignore_errors=True)
    out["scratch_fetch_deleted"] = {"n_gz_files": n_del, "bytes": size, "remaining_gz": sum(1 for p in root.rglob("*.gz"))}
    return out


def b3_prior_values() -> dict:
    out = {}
    root = ROOT / "b3"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    ledger = []
    old = P._MANIFEST
    try:
        df = P.manifest().copy(); df.loc[df.pair_id == "RR1506__MGDS_29779", "designation"] = "lockbox"; P._MANIFEST = df
        r, rec = S.run_pair("RR1506__MGDS_29779", cfg_rehearsal(root), root, 4, 1, ledger, stage_root=root / "stage")
    finally:
        P._MANIFEST = old
    j = P.june_sweep_record()["RR1506__MGDS_29779"]; row = P.manifest().set_index("pair_id").loc["RR1506__MGDS_29779"]
    out["rr1506"] = {"hr_native_res_m": rec["c2a"]["hr_native_res_m"], "lr_native_res_m": rec["c2a"]["lr_native_res_m"], "values_source": rec["c2a"]["source"],
                     "max_recoverable_k": rec["sweep"]["max_recoverable_k"], "per_k": rec["sweep"]["per_k"], "k_source": rec["sweep"]["k_source"], "swept": rec["sweep"]["swept"],
                     "consistency_check": rec["c2a"]["consistency_check"], "row_hr": float(row["hr_native_res_m"]), "row_lr": float(row["lr_native_res_m"]), "row_k": float(row["max_recoverable_k"]),
                     "june_k": j["max_recoverable_k"], "june_per_k": j["per_k"], "products": rec["summary"]["products"], "ledger": ledger}
    out["rr1506"]["pass"] = bool(rec["c2a"]["hr_native_res_m"] == 0.992 and rec["c2a"]["lr_native_res_m"] == 20.3 and rec["sweep"]["max_recoverable_k"] == 8
                                 and rec["sweep"]["per_k"] == j["per_k"] and rec["sweep"]["swept"] is False and r["max_recoverable_k"] == 8.0)
    # A1 consistency check on the two lockbox pairs, records only
    m = P.manifest().set_index("pair_id"); cc = {}
    for pid in C.LOCKBOX:
        row = m.loc[pid]; jj = P.june_sweep_record().get(pid, {})
        lr = float(row["lr_native_res_m"]); jl = jj.get("lr_native_m"); nd = S._ndp(lr)
        cc[pid] = {"manifest_lr_native_res_m": lr, "june_sweep_lr_native_m": jl, "precision_dp": nd, "equal": jl is not None and round(float(jl), nd) == round(lr, nd),
                   "manifest_hr_native_res_m": float(row["hr_native_res_m"]), "june_k": jj.get("max_recoverable_k"), "june_per_k": jj.get("per_k"), "designation": row["designation"]}
    out["lockbox_consistency"] = cc; out["lockbox_consistency_pass"] = all(v["equal"] for v in cc.values())
    # a different lr_native in the June record -> C4 stop before any write (refusal test 12 material)
    oldj = P._JUNE_SWEEP
    try:
        P._JUNE_SWEEP = {**P.june_sweep_record(), "RR1506__MGDS_29779": {**P.june_sweep_record()["RR1506__MGDS_29779"], "lr_native_m": 21.0}}
        df = P.manifest().copy(); df.loc[df.pair_id == "RR1506__MGDS_29779", "designation"] = "lockbox"; P._MANIFEST = df
        root2 = root / "inconsistent"; root2.mkdir()
        try:
            S.run_pair("RR1506__MGDS_29779", cfg_rehearsal(root2), root2, 4, 1, [], stage_root=root2 / "stage"); res = "NOT STOPPED"
        except S.StopRun as e:
            res = f"StopRun: {str(e)[:200]}"
        out["inconsistent_record_stop"] = {"result": res, "pass": res.startswith("StopRun") and "consistency check failed" in res,
                                           "outputs_written": sorted(str(p.relative_to(root2)) for p in root2.rglob("*") if p.is_file())}
    finally:
        P._JUNE_SWEEP = oldj; P._MANIFEST = old
    return out


def _copy_pair(dst: Path, dir_mode: int) -> dict:
    src = C.OAK / "harmonized" / FK
    if dst.exists():
        os.chmod(dst, 0o770); shutil.rmtree(dst)
    dst.mkdir(parents=True)
    modes = {}
    for name in ("hr.tif", "lr.tif", "hr_valid.tif", "lr_valid.tif", "joint_valid.tif", "footprint.geojson"):
        shutil.copyfile(src / name, dst / name); os.chmod(dst / name, 0o444); modes[name] = {"sha256": P.sha256_file(dst / name), "mode": "0o444"}
    os.chmod(dst, dir_mode)
    return modes


def _compare_products(dst: Path) -> dict:
    ref = R06_FULL / "harmonized" / FK / "ship_products_v2_1"
    if not ref.exists():
        ref = P.OAK_R06_REHEARSAL / "rehearsal_outputs" / "full" / "harmonized" / FK / "ship_products_v2_1"
    out = {}
    for name in RASTERS_V2:
        with rasterio.open(dst / "ship_products_v2_1" / f"{name}.tif") as a, rasterio.open(ref / f"{name}.tif") as b:
            out[name] = bool(np.array_equal(a.read(1), b.read(1), equal_nan=True) and a.transform == b.transform and a.crs == b.crs)
    out["reference"] = str(ref)
    return out


def b4_write_path() -> dict:
    out = {}
    for label, dir_mode in (("as_found_2770", 0o2770), ("no_owner_write_0550", 0o550)):
        root = ROOT / "b4" / label; dst = root / "harmonized" / FK
        pre = _copy_pair(dst, dir_mode)
        mode_set = oct(dst.stat().st_mode & 0o7777)
        ledger = []
        r, rec = S.run_pair(FK, cfg_rehearsal(root), root, 4, 1, ledger, stage_root=root / "stage")
        post = {name: {"sha256": P.sha256_file(dst / name), "mode": oct((dst / name).stat().st_mode & 0o777)} for name in pre}
        wp = rec["write_path"]
        res = {"dir_mode_set": mode_set, "write_path": {k: wp[k] for k in ("mode_before", "mode_opened", "mode_after", "restored")},
               "dir_mode_now": oct(dst.stat().st_mode & 0o7777), "pre_existing_unchanged": all(pre[n]["sha256"] == post[n]["sha256"] and post[n]["mode"] == "0o444" for n in pre),
               "pre_existing": post, "products_bit_identical_to_r06": _compare_products(dst),
               "new_modes": {p.name: oct(p.stat().st_mode & 0o7777) for p in sorted((dst / "ship_products_v2_1").iterdir())} | {"ship_products_v2_1": oct((dst / "ship_products_v2_1").stat().st_mode & 0o7777),
                             "step1_record.json": oct((dst / "step1_record.json").stat().st_mode & 0o777), "sweep_record.json": oct((dst / "sweep_record.json").stat().st_mode & 0o777)},
               "summary": {k: rec["summary"][k] for k in ("lr_native_res_m", "max_recoverable_k", "products", "flags", "ship_products_usable")}}
        res["pass"] = bool(res["pre_existing_unchanged"] and res["dir_mode_now"] == mode_set and wp["restored"] and all(v for k, v in res["products_bit_identical_to_r06"].items() if k != "reference")
                           and all(v == "0o444" for k, v in res["new_modes"].items() if k != "ship_products_v2_1") and res["new_modes"]["ship_products_v2_1"] == "0o555")
        out[label] = res
    # failure branch: os.chmod blocked -> C4 stop before the supplement
    root = ROOT / "b4" / "blocked"; dst = root / "harmonized" / FK
    _copy_pair(dst, 0o2770)
    real_chmod = os.chmod

    def blocked(path, mode, *a, **k):
        if Path(path) == dst:
            raise PermissionError(f"harness: write blocked on {path}")
        return real_chmod(path, mode, *a, **k)
    os.chmod = blocked
    try:
        S.run_pair(FK, cfg_rehearsal(root), root, 4, 1, [], stage_root=root / "stage"); res = "NOT STOPPED"
    except PermissionError as e:
        res = f"PermissionError (inside the A3 sequence): {e}"
    except S.StopRun as e:
        res = f"StopRun: {str(e)[:200]}"
    finally:
        os.chmod = real_chmod
    out["blocked"] = {"result": res, "outputs_in_pair_dir": sorted(p.name for p in dst.iterdir()), "pass": res.startswith(("StopRun", "PermissionError"))}
    return out


def main(argv=None):
    P.check_fixed_inputs()
    t0 = time.time()
    rec = {"generated": P.utc_now(), "host": P.hostname(), "root": str(ROOT), "code_commit": P.git_commit()}
    rec["b3"] = b3_prior_values(); print("B3", json.dumps({k: v for k, v in rec["b3"].items() if k != "rr1506"}, default=str)[:600], "RR1506 pass", rec["b3"]["rr1506"]["pass"])
    rec["b4"] = b4_write_path(); print("B4", {k: v.get("pass") for k, v in rec["b4"].items()})
    rec["b2"] = b2_fetch(); print("B2", rec["b2"]["b2_pass"], rec["b2"]["failure_branch"]["pass"], rec["b2"]["trigger_rehearsal_pairs"], rec["b2"]["trigger_whole_manifest_lockbox_rule"])
    rec["all_passed"] = bool(rec["b3"]["rr1506"]["pass"] and rec["b3"]["lockbox_consistency_pass"] and rec["b3"]["inconsistent_record_stop"]["pass"]
                             and all(v.get("pass") for v in rec["b4"].values()) and rec["b2"]["b2_pass"] and rec["b2"]["failure_branch"]["pass"])
    rec["wall_s"] = round(time.time() - t0, 1)
    P.write_json(P.REPORT_DIR / "harness_r06b.json", rec, mode=0o644)
    print("harness all_passed:", rec["all_passed"], "wall", rec["wall_s"])
    return 0 if rec["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
