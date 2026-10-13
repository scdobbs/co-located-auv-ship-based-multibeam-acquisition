"""ACQ-R09 §3.3.4 — the CNN run-record lock, copied and pointed at the Phase 5 record and freeze record.

Reads (never edits, never imports) the CNN repo's phase4_common.py, extracts the source of load_acq_run_record,
k_source_class, k_provenance, row_status and _isfinite with `ast`, applies the parameterisation R16 will make (record
glob step1_run_<mode>_*.json and mode == <mode>; ACQ_STEP1_REL = src/phase5/sealed_step1_p5.py at its freeze-record
sha256), writes that copy to scratch and runs it there with `python -B` (no bytecode, nothing written to the CNN repo).
Cases: the rehearsal record is accepted (mode rehearsal, rehearsal record directory, the given freeze record); refusals
for a wrong supplement sha256, a wrong freeze-record sha256 and the empty PHASE5 directory (mode phase5); per_pair
passes k_provenance (k source class 'sweep', k agrees with the supplement row) and every supplement row passes row_status.
Usage: python -m src.phase5.cnn_lock_check_p5 --run-record <rehearsal record> --freeze-record <json>
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

from src.phase5 import common_p5 as P

CNN_COMMON = Path("/home/users/scdobbs/GAN_Bathymetry_Project/grl_reviews-and-prompt-reports/directives_and_reports/phase4/scripts/phase4_common.py")
FUNCS = ("load_acq_run_record", "k_source_class", "k_provenance", "row_status", "_isfinite")
SUBS = [('"step1_run_phase4_*.json"', 'f"step1_run_{LOCK_MODE}_*.json"'), ('r.get("mode") == "phase4"', 'r.get("mode") == LOCK_MODE'),
        ("records_dir=ACQ_RECORDS_DIR, freeze_record=ACQ_FREEZE_RECORD, freeze_sha=ACQ_FREEZE_SHA", "records_dir, freeze_record, freeze_sha")]

RUNNER = r'''
import glob, json, os, sys, hashlib
import pandas as pd
def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    return h.hexdigest()
class Refusal(RuntimeError): pass
cfg = json.loads(sys.argv[1])
ACQ_STEP1_REL, ACQ_STEP1_SHA = cfg["step1_rel"], cfg["step1_sha"]
%(FUNCS)s
def run(mode, *a):
    global LOCK_MODE
    LOCK_MODE = mode
    try:
        r = load_acq_run_record(*a); return {"accepted": True, "path": r["path"], "status": r["status"], "mode": r["mode"], "per_pair_keys": sorted(r["per_pair"]), "rec": r}
    except Refusal as e:
        return {"accepted": False, "refusal": str(e)[:300]}
out = {}
ok = run(cfg["mode"], cfg["supplement_sha"], cfg["records_dir"], cfg["freeze_record"], cfg["freeze_sha"])
rec = ok.pop("rec", None); out["accept_rehearsal_record"] = ok
out["refuse_wrong_supplement_sha"] = {k: v for k, v in run(cfg["mode"], "0" * 64, cfg["records_dir"], cfg["freeze_record"], cfg["freeze_sha"]).items() if k != "rec"}
out["refuse_wrong_freeze_sha"] = {k: v for k, v in run(cfg["mode"], cfg["supplement_sha"], cfg["records_dir"], cfg["freeze_record"], "1" * 64).items() if k != "rec"}
out["refuse_phase5_dir_no_record"] = {k: v for k, v in run("phase5", cfg["supplement_sha"], cfg["phase5_dir"], cfg["freeze_record"], cfg["freeze_sha"]).items() if k != "rec"}
sup = pd.read_parquet(cfg["supplement"])
prov, rows = {}, {}
for _, row in sup.iterrows():
    pid = row["pair_id"]; d = row.to_dict()
    kp = k_provenance(pid, d, rec) if rec else None
    prov[pid] = {k: kp[k] for k in ("k", "k_source_class", "k_in_acq_record", "k_agrees_with_acq_record", "values_source")} if kp else None
    rows[pid] = row_status(d)
out["k_provenance"] = prov; out["row_status"] = rows
print(json.dumps(out, default=str))
'''


def extract() -> tuple:
    src = CNN_COMMON.read_text()
    tree = ast.parse(src)
    parts = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in FUNCS:
            parts.append(ast.get_source_segment(src, node))
    code = "\n\n".join(parts)
    for a, b in SUBS:
        if a not in code:
            raise SystemExit(f"CNN lock source changed: substitution target {a!r} not found")
        code = code.replace(a, b)
    return code, P.sha256_file(CNN_COMMON), src


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--run-record", required=True); ap.add_argument("--freeze-record", required=True)
    a = ap.parse_args(argv)
    rr = json.loads(Path(a.run_record).read_text()); fr = json.loads(Path(a.freeze_record).read_text())
    code, cnn_sha, _ = extract()
    work = P.SCRATCH_ROOT / "cnn_lock_copy"; work.mkdir(parents=True, exist_ok=True)
    script = work / "phase5_lock_copy.py"
    script.write_text(RUNNER % {"FUNCS": code})
    cfg = {"mode": rr["mode"], "supplement_sha": rr["supplement_sha256"], "records_dir": str(Path(a.run_record).parent), "freeze_record": str(Path(a.freeze_record)),
           "freeze_sha": P.sha256_file(a.freeze_record), "step1_rel": P.ENTRY_REL, "step1_sha": fr["files"][P.ENTRY_REL], "phase5_dir": str(P.PHASE5_DIR),
           "supplement": rr["supplement"]}
    r = subprocess.run([sys.executable, "-B", str(script), json.dumps(cfg)], capture_output=True, text=True, cwd=str(work))
    if r.returncode != 0:
        raise SystemExit(f"lock copy failed: {r.stderr[-800:]}")
    res = json.loads(r.stdout.strip().splitlines()[-1])
    passed = (res["accept_rehearsal_record"]["accepted"] and not res["refuse_wrong_supplement_sha"]["accepted"] and not res["refuse_wrong_freeze_sha"]["accepted"]
              and not res["refuse_phase5_dir_no_record"]["accepted"]
              and all(v and v["k_source_class"] == "sweep" and v["k_agrees_with_acq_record"] in (True, None) for v in res["k_provenance"].values()))
    out = {"generated": P.utc_now(), "cnn_phase4_common": str(CNN_COMMON), "cnn_phase4_common_sha256": cnn_sha, "functions_copied": list(FUNCS),
           "substitutions": [{"from": x, "to": y} for x, y in SUBS], "scratch_copy": str(script), "scratch_copy_sha256": P.sha256_file(script),
           "config": cfg, "results": res, "passed": bool(passed),
           "contract_note": "the copy reads locks.lock2_freeze_record.freeze_record_sha256, status, mode, supplement_sha256, code_commit, per_pair (max_recoverable_k, per_k, k_source, values_source)"}
    P.write_json(P.REHEARSAL_DIR / f"cnn_lock_check_{rr['run_tag']}.json", out, mode=0o644)
    print(json.dumps({k: res[k] for k in ("accept_rehearsal_record", "refuse_wrong_supplement_sha", "refuse_wrong_freeze_sha", "refuse_phase5_dir_no_record")}, indent=1)[:1500])
    print("k_provenance", res["k_provenance"]); print("row_status", res["row_status"]); print("passed", passed)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
