"""ACQ-R07b Part B1 — stopped-then-completed against uninterrupted, on development stand-ins, scratch only.

Stand-ins (directive B1.1): TN399, FK151121, KM0923 take the confirmatory roles; RR1506 and EW9801 take the lockbox
roles, relabelled `lockbox` in an in-process manifest copy (never written), EW9801 'absent' from the OAK listing so the
frozen step fetches it from the June plan into the scratch root's raw_lr_swath/.  The frozen step processes the five
in the order of --pairs (recorded).
  1. uninterrupted: the frozen sealed_step1 in rehearsal mode on the five (run tag r07b_ref) — reference;
  2. stopped: a fresh root (r07b_stop); os.chmod on the fourth pair's directory drops the setgid bit (as observed on
     OAK: a directory whose group is not one of the caller's) -> the frozen write path stops under C4 after that
     pair's outputs, with the ACQ-R07 message form;
  3. metadata fix: that directory chmod 2770 (ruling R2's analogue);
  4. completion: sealed_step1_complete in rehearsal mode on the r07b_stop root;
  5. the four checks of B1 "must hold".
Report-dir redirection: P.REHEARSAL_DIR and the frozen MODES['rehearsal']['supplement'] point at ACQ-R07b/rehearsal/
(module attributes set in this process; no frozen file edited).  Usage (Slurm): python -m src.phase4.harness_r07b
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import stat as statmod
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src.acq_r01 import common as C
from src.phase4 import common as P
from src.phase4 import sealed_step1 as S
from src.phase4 import sealed_step1_complete as SC

R07B = SC.REPORT_DIR_R07B
REH = R07B / "rehearsal"
ROOT = P.SCRATCH_ROOT
ORDER = ["TN399__MGDS_33068", "FK151121__MGDS_22383", "KM0923__MGDS_31429", "RR1506__MGDS_29779", "EW9801__MGDS_31425"]
LOCKBOX_STANDINS = ("RR1506__MGDS_29779", "EW9801__MGDS_31425")
FETCH_STANDIN = "EW9801"
INJECT_PAIR = ORDER[3]                                   # the fourth processed pair (AT42-03's role)
TAG_REF, TAG_STOP = "r07b_ref", "r07b_stop"
STOP_FORM = re.compile(r"directory mode not restored \(before 0o2770, after 0o770\) \(rule C4\)$")
VOLATILE_KEYS = {"created", "wall_s", "started", "finished", "host", "cpu_model", "staged_dir", "write_path", "mode_history", "generated", "fetched_at",
                 "row_filled_columns", "out_dir", "cruise_dir", "plan_csv", "lr_tif_path", "lr_tif_source", "commands", "notes", "provenance", "wall"}
SUMMARY_KEYS = SC.SUMMARY_KEYS + ("designation", "fetch", "products_reason")


def install_patches():
    """ACQ-R06b harness mechanisms: report dirs, manifest relabel (in process), the fetch stand-in absent from the listing."""
    REH.mkdir(parents=True, exist_ok=True)
    P.REHEARSAL_DIR = REH
    S.MODES["rehearsal"]["supplement"] = REH / "supplement_rehearsal.parquet"
    df = P.manifest().copy()
    for pid in LOCKBOX_STANDINS:
        df.loc[df.pair_id == pid, "designation"] = P.PRIOR_VALUE_DESIGNATION
    P._MANIFEST = df
    real_listing = P.oak_swath_listing
    P.oak_swath_listing = lambda: real_listing() - {FETCH_STANDIN}
    return {"REHEARSAL_DIR": str(REH), "supplement": str(S.MODES["rehearsal"]["supplement"]), "relabelled_lockbox": list(LOCKBOX_STANDINS), "listing_minus": [FETCH_STANDIN]}


def rm_tree(path: Path):
    if not path.exists():
        return
    for d, dirs, files in os.walk(path):
        os.chmod(d, 0o775)
    shutil.rmtree(path)


def frozen_run(tag: str, nproc: int, batch_files: int, inject_dir: Path | None = None) -> dict:
    root = ROOT / tag
    rm_tree(root)
    for p in (REH / f"step1_run_rehearsal_{tag}.json", REH / f"supplement_rehearsal_{tag}.parquet"):
        if p.exists():
            p.chmod(0o644); p.unlink()
    argv = ["--mode", "rehearsal", "--run-tag", tag, "--pairs", ",".join(ORDER), "--nproc", str(nproc), "--batch-files", str(batch_files)]
    real_chmod = os.chmod; calls = []

    def dropping(path, mode, *a, **k):
        if inject_dir is not None and Path(path) == inject_dir:
            calls.append({"requested": oct(mode), "applied": oct(mode & ~statmod.S_ISGID)})
            mode = mode & ~statmod.S_ISGID                 # what the kernel does for a directory of a foreign group
        return real_chmod(path, mode, *a, **k)
    if inject_dir is not None:
        os.chmod = dropping
    t0 = time.time()
    try:
        rc = S.main(argv); res = {"returned": rc, "stopped": None}
    except S.StopRun as e:
        res = {"returned": None, "stopped": str(e)}
    finally:
        os.chmod = real_chmod
    res.update({"tag": tag, "root": str(root), "argv": " ".join(argv), "wall_s": round(time.time() - t0, 1), "injected_chmod_calls": calls,
                "run_record": str(REH / f"step1_run_rehearsal_{tag}.json"), "supplement_exists": (REH / f"supplement_rehearsal_{tag}.parquet").exists()})
    return res


def outputs_of(root: Path, pid: str) -> dict:
    d = root / "harmonized" / pid
    if not d.exists():
        return {}
    return {str(p.relative_to(d)): p for p in sorted(d.rglob("*")) if p.is_file()}


def _strip(obj, roots):
    if isinstance(obj, dict):
        return {k: _strip(v, roots) for k, v in obj.items() if k not in VOLATILE_KEYS and not k.endswith("_s")}
    if isinstance(obj, list):
        return [_strip(v, roots) for v in obj]
    if isinstance(obj, str):
        for r in roots:
            obj = obj.replace(r, "<ROOT>")
        return obj
    if isinstance(obj, float) and math.isnan(obj):
        return "nan"
    return obj


def _json_diff(a, b, path="") -> list:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}: {'missing in ref' if k not in a else 'missing in completed'}")
            else:
                out += _json_diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: list length {len(a)} vs {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _json_diff(x, y, f"{path}[{i}]")]
    if isinstance(a, float) and isinstance(b, float):
        return [] if (abs(a - b) <= 1e-9) else [f"{path}: {a} vs {b}"]
    return [] if a == b else [f"{path}: {str(a)[:60]} vs {str(b)[:60]}"]


def compare_outputs(ref_root: Path, new_root: Path, pid: str) -> dict:
    a, b = outputs_of(ref_root, pid), outputs_of(new_root, pid)
    res = {"pair_id": pid, "n_files_ref": len(a), "n_files_completed": len(b), "same_names": set(a) == set(b), "byte_identical": [], "semantic_equal": [], "differing": {}}
    roots = [str(ref_root), str(new_root)]
    for rel in sorted(set(a) & set(b)):
        pa, pb = a[rel], b[rel]
        if pa.suffix in (".tif", ".csv") and not pa.name.startswith("fetch_swath_log"):
            if P.sha256_file(pa) == P.sha256_file(pb):
                res["byte_identical"].append(rel)
            else:
                res["differing"][rel] = "bytes differ"
        elif pa.name.startswith("fetch_swath_log"):
            ta = pd.read_csv(pa)[["filename", "sha256", "status", "received"]].sort_values("filename").reset_index(drop=True)
            tb = pd.read_csv(pb)[["filename", "sha256", "status", "received"]].sort_values("filename").reset_index(drop=True)
            if ta.equals(tb):
                res["semantic_equal"].append(rel)
            else:
                res["differing"][rel] = "fetch log rows (filename, sha256, status, received) differ"
        elif pa.suffix == ".json":
            ja, jb = _strip(json.loads(pa.read_text()), roots), _strip(json.loads(pb.read_text()), roots)
            d = _json_diff(ja, jb)
            if d:
                res["differing"][rel] = d[:12]
            else:
                res["semantic_equal"].append(rel)
        else:
            res["differing"][rel] = "unexpected file type"
    res["pass"] = bool(res["same_names"] and not res["differing"])
    return res


def compare_supplements(ref: Path, comp: Path) -> dict:
    a = pd.read_parquet(ref).set_index("pair_id"); b = pd.read_parquet(comp).set_index("pair_id")
    out = {"ref": str(ref), "completed": str(comp), "same_columns": list(a.columns) == list(b.columns), "same_ids": sorted(a.index) == sorted(b.index), "order_ref": list(a.index), "order_completed": list(b.index), "rows": {}}
    allowed = {"notes"}
    for pid in a.index:
        diff = []
        for c in a.columns:
            x, y = a.loc[pid, c], b.loc[pid, c]
            eq = (x == y) or (isinstance(x, float) and isinstance(y, float) and (math.isnan(x) and math.isnan(y) or abs(x - y) <= 1e-9))
            if not bool(eq):
                diff.append(c)
        out["rows"][pid] = {"differing": diff, "unexplained": [c for c in diff if c not in allowed]}
    out["differing_union"] = sorted({c for r in out["rows"].values() for c in r["differing"]})
    out["pass"] = bool(out["same_columns"] and out["same_ids"] and all(not r["unexplained"] for r in out["rows"].values()))
    out["allowed_differences"] = sorted(allowed)
    return out


def compare_per_pair(ref: dict, comp: dict) -> dict:
    out = {"keys": list(SUMMARY_KEYS), "excluded": ["wall_s", "write_path", "provenance", "mode_history", "usable_reason"], "pairs": {}}
    for pid in ref["per_pair"]:
        ra, rb = ref["per_pair"][pid], comp["per_pair"].get(pid, {})
        d = {k: {"ref": ra.get(k), "completed": rb.get(k)} for k in SUMMARY_KEYS if ra.get(k) != rb.get(k)}
        out["pairs"][pid] = {"equal": not d, "differing": d}
    out["pass"] = bool(set(ref["per_pair"]) == set(comp["per_pair"]) and all(v["equal"] for v in out["pairs"].values()))
    return out


def not_recomputed(comp: dict, finished: list) -> dict:
    forbidden = {"c2a", "sweep", "fetch", "products", "write"}
    out = {"finished": finished, "pairs": {}}
    for pid in finished:
        items = [e["item"] for e in comp["ledger"] if e["pair_id"] == pid]
        out["pairs"][pid] = {"ledger_items": items, "forbidden_present": sorted(set(items) & forbidden), "provenance": comp["per_pair"][pid].get("provenance")}
    out["pass"] = all(not v["forbidden_present"] and v["provenance"] == "record (not recomputed)" for v in out["pairs"].values()) and set(comp.get("finished_pairs") or []) == set(finished)
    return out


def main(argv=None):
    nproc = int(os.environ.get("NPROC", "6")); bf = int(os.environ.get("BATCH_FILES", "1"))
    P.check_fixed_inputs()
    t0 = time.time()
    rec = {"generated": P.utc_now(), "host": P.hostname(), "cpu_model": P.cpu_model(), "code_commit": P.git_commit(), "order": ORDER, "inject_pair": INJECT_PAIR, "nproc": nproc, "batch_files": bf}
    rec["patches"] = install_patches()
    # 1 uninterrupted
    rec["ref"] = frozen_run(TAG_REF, nproc, bf)
    ref_run = json.loads(Path(rec["ref"]["run_record"]).read_text())
    seen = []
    for e in ref_run["ledger"]:
        if e["pair_id"] not in seen:
            seen.append(e["pair_id"])
    rec["processing_order"] = seen
    rec["ref"]["pass"] = bool(rec["ref"]["returned"] == 0 and ref_run["status"] == "complete" and seen == ORDER and ref_run["n_rows"] == 5)
    # 2 stopped (the fourth pair's directory loses its setgid bit on every chmod)
    inject_dir = ROOT / TAG_STOP / "harmonized" / INJECT_PAIR
    rec["stop"] = frozen_run(TAG_STOP, nproc, bf, inject_dir=inject_dir)
    stop_run = json.loads(Path(rec["stop"]["run_record"]).read_text())
    outs = {pid: sorted(outputs_of(ROOT / TAG_STOP, pid)) for pid in ORDER}
    rec["stop"].update({"status": stop_run["status"], "error": stop_run.get("error"), "pairs_done": stop_run.get("pairs_done"), "outputs_present": {k: len(v) for k, v in outs.items()},
                        "inject_dir_mode_after_stop": SC.dir_metadata(inject_dir)["mode"], "message_form_as_acq_r07": bool(STOP_FORM.search(str(rec["stop"]["stopped"])))})
    rec["stop"]["pass"] = bool(rec["stop"]["stopped"] and rec["stop"]["message_form_as_acq_r07"] and str(inject_dir) in rec["stop"]["stopped"] and stop_run["status"] == "stopped (rule C4)"
                               and stop_run["pairs_done"] == ORDER[:3] and outs[INJECT_PAIR] and not outs[ORDER[4]] and not rec["stop"]["supplement_exists"]
                               and rec["stop"]["inject_dir_mode_after_stop"] == "0o770" and all(len(outs[p]) == len(outputs_of(ROOT / TAG_REF, p)) for p in ORDER[:4]))
    # 3 metadata fix (R2's analogue)
    before = SC.dir_metadata(inject_dir); os.chmod(inject_dir, 0o2770); after = SC.dir_metadata(inject_dir)
    rec["fix"] = {"dir": str(inject_dir), "before": before, "after": after, "pass": after["mode"] == "0o2770"}
    # 4 completion (a previous harness run's completion outputs for this tag are removed first; the completion refuses an existing supplement)
    for p in (REH / f"step1_run_rehearsal_{TAG_STOP}_{SC.RECORD_TAG}.json", REH / f"supplement_rehearsal_{TAG_STOP}_{SC.RECORD_TAG}.parquet"):
        if p.exists():
            p.chmod(0o644); p.unlink()
    t1 = time.time()
    argv_c = ["--mode", "rehearsal", "--run-tag", TAG_STOP, "--prior-run-record", rec["stop"]["run_record"], "--pairs", ",".join(ORDER), "--nproc", str(nproc), "--batch-files", str(bf)]
    try:
        rc = SC.main(argv_c); comp_res = {"returned": rc, "stopped": None}
    except S.StopRun as e:
        comp_res = {"returned": None, "stopped": str(e)}
    comp_path = REH / f"step1_run_rehearsal_{TAG_STOP}_{SC.RECORD_TAG}.json"
    comp = json.loads(comp_path.read_text())
    comp_res.update({"argv": " ".join(argv_c), "wall_s": round(time.time() - t1, 1), "run_record": str(comp_path), "status": comp["status"], "supplement": comp.get("supplement"),
                     "finished_pairs": comp.get("finished_pairs"), "pending_pairs": comp.get("pending_pairs"), "n_rows": comp.get("n_rows"), "error": comp.get("error")})
    rec["completion"] = comp_res
    # 5 must hold
    checks = {}
    if comp["status"] == "complete":
        checks["supplement"] = compare_supplements(Path(ref_run["supplement"]), Path(comp["supplement"]))
        checks["per_pair"] = compare_per_pair(ref_run, comp)
        checks["outputs"] = {pid: compare_outputs(ROOT / TAG_REF, ROOT / TAG_STOP, pid) for pid in ORDER}
        checks["outputs_pass"] = all(v["pass"] for v in checks["outputs"].values())
        checks["not_recomputed"] = not_recomputed(comp, ORDER[:4])
        checks["all_pass"] = bool(checks["supplement"]["pass"] and checks["per_pair"]["pass"] and checks["outputs_pass"] and checks["not_recomputed"]["pass"])
    else:
        checks["all_pass"] = False
    rec["checks"] = checks
    # scratch fetches: delete the fetched swath (.gz) of both roots, as ACQ-R06b did; everything else stays for the refusal tests / inspection
    n, size = 0, 0
    for tag in (TAG_REF, TAG_STOP):
        sw = ROOT / tag / "raw_lr_swath"
        for p in sw.rglob("*.gz") if sw.exists() else []:
            n += 1; size += p.stat().st_size
        if sw.exists():
            rm_tree(sw)
    rec["scratch_fetch_deleted"] = {"n_gz_files": n, "bytes": size}
    rec["all_passed"] = bool(rec["ref"]["pass"] and rec["stop"]["pass"] and rec["fix"]["pass"] and comp["status"] == "complete" and checks["all_pass"])
    rec["wall_s"] = round(time.time() - t0, 1)
    P.write_json(R07B / "harness_r07b.json", rec, mode=0o644)
    print("B1:", {"ref": rec["ref"]["pass"], "stop": rec["stop"]["pass"], "fix": rec["fix"]["pass"], "completion": comp["status"], "checks": {k: (v.get("pass") if isinstance(v, dict) else v) for k, v in checks.items()}}, "all_passed", rec["all_passed"], "wall", rec["wall_s"])
    return 0 if rec["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
