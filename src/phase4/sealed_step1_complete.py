"""ACQ-R07b Part A — completion of Phase 4 step 1 after the ACQ-R07 stop, without recomputing anything the frozen
step finished.

The frozen step (src/phase4/sealed_step1.py, ACQ-R06b freeze record) is imported and its functions are called
unchanged: lock_signoff, lock_pair_list, lock_single_run, pair_dir_of, fetch_trigger, preflight_swath, run_pair (the
whole per-pair chain, write_outputs included), usable_rule, supplement_row and write_run_record.  Two things the
frozen main() does inline are reproduced here as thin wrappers (reported under the challenge clause): the supplement
writer (main() lines 616-622) and the freeze-record file check (lock_freeze_record also requires every loaded module
to be in that one record, which the completion module cannot satisfy).

Per run, in this order:
  0. fixed inputs, guard self-test;
  1. phase4 mode: locks 1-8 (sign-off, frozen code, completion code, prior run record, deviation note, pair list,
     single completion, lockbox directory metadata), then the phase4 allowance;
  2. the prior (stopped) run record decides which pairs are finished: a pair is finished iff its output directory
     holds step1_record.json, and that set must equal the pairs with ledger entries in the prior record; the rest
     are pending (ACQ-R07: KN182L03, RC2511, SUM1004, AT42-03 finished; TN159 pending);
  3. finished pairs (A2): read step1_record.json and sweep_record.json, verify the sha256 of every file the record
     lists, cross-check spacings / k / status / per-k verdicts / k source / product status against the prior record's
     per_pair and ledger entries, derive ship_products_usable with the frozen usable_rule (from products.json only for
     a pair the prior record's per_pair lacks), rebuild the row with the frozen supplement_row.  Any mismatch or
     missing file stops the run (rule C4) before anything is written.  No grid or product raster is opened.
  4. pending pairs (A3): the frozen run_pair, exactly as the frozen main() calls it (fetch, prior values, products,
     write path; rules C1-C4 unchanged).  A stop is a stop: nothing is written to the supplement.
  5. the supplement (A4) with the frozen row writer's output and the frozen main()'s writer lines, and the completion
     run record in the frozen format plus the citations the CNN step-2 lock reads.

Modes (as frozen: pair list, guard allow-list, output root):
  --mode rehearsal --run-tag <tag> --prior-run-record <stopped rehearsal record> [--pairs ...]
  --mode phase4 --signoff <file> --prereg-sha256 <hex> [--freeze-record ...] [--completion-freeze-record ...]
                [--prior-run-record ...] [--deviation-note ...]
"""
from __future__ import annotations

import argparse
import grp
import json
import logging
import os
import pwd
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.acq_r01 import common as C
from src.phase4 import common as P
from src.phase4 import sealed_step1 as S
from src.phase4 import guard_selftest as G

log = logging.getLogger("acq_r07b.complete")

REPORT_DIR_R07B = P.REPO / "reports_post_grl_review" / "ACQ-R07b"
COMPLETION_FREEZE_RECORD = REPORT_DIR_R07B / "completion_freeze_record.json"
SHA_FREEZE_RECORD = "331c94f01d7d1a2e52fb969c5fb1872aae2cd2ed249a3757b99e9d217b3ac0cb"          # ACQ-R06b freeze record
PRIOR_RUN_RECORD = P.REPORT_DIR / "step1_run_phase4_run.json"                                    # ACQ-R07 (stopped)
SHA_PRIOR_RUN_RECORD = "7cc5b46d437a72976027f8e7ca9b0f31a8b9eeb5161928c67fce41f87127ce2b"
PRIOR_STOP_DIR = "harmonized/AT42-03__MGDS_32007"
PRIOR_STOP_TEXT = "directory mode not restored"
PREREG_SHA256 = "9795db3b22d6c54f7a85618dbaccafa054e88487b33236a7b2083ecb8c605979"
CNN_REPO = Path("/home/users/scdobbs/GAN_Bathymetry_Project")
DEVIATION_NOTE = CNN_REPO / "grl_reviews-and-prompt-reports" / "directives_and_reports" / "R11" / "DEVIATION_phase4_01.md"
COMPLETION_RECORD_TAG = "completion"
LOCKBOX_GROUP = "oak_hilley"
LOCKBOX_MODE = "0o2770"
MODES = S.MODES                                     # the frozen table: pair list, allow-list, output root, supplement
RECORD_TAG = "completion"

Refusal, StopRun = S.Refusal, S.StopRun


# --------------------------------------------------------------------------- #
# locks (phase4 mode), in order, before the allowance
# --------------------------------------------------------------------------- #
def lock_frozen_code(freeze_record) -> dict:
    """Lock 2: the 21 files of the ACQ-R06b freeze record at their recorded sha256 and the record at its sha256.
    (The frozen lock_freeze_record additionally requires every loaded module to be in that one record; the
    completion module is not, so the file loop is reproduced here — challenge clause.)"""
    p = Path(freeze_record)
    if not p.exists():
        raise Refusal(f"LOCK 2 frozen code: {p} does not exist")
    h = P.sha256_file(p)
    if h != SHA_FREEZE_RECORD:
        raise Refusal(f"LOCK 2 frozen code: {p.name} sha256 {h} != {SHA_FREEZE_RECORD}")
    files = json.loads(p.read_text()).get("files") or {}
    bad = []
    for rel, sha in files.items():
        fp = C.REPO / rel
        got = P.sha256_file(fp) if fp.exists() else "MISSING"
        if got != sha:
            bad.append((rel, sha[:12], got[:12]))
    if bad:
        raise Refusal(f"LOCK 2 frozen code: {len(bad)} file(s) differ from {p.name}: {bad[:5]}")
    return {"freeze_record": str(p), "freeze_record_sha256": h, "n_files": len(files), "files": files}


def lock_completion_code(completion_record, frozen_files: dict) -> dict:
    """Lock 3: the completion freeze record exists, every file it lists matches, and every repo module this process
    has loaded is listed in one of the two records."""
    p = Path(completion_record)
    if not p.exists():
        raise Refusal(f"LOCK 3 completion code: {p} does not exist")
    rec = json.loads(p.read_text()); files = rec.get("files") or {}
    me = "src/phase4/sealed_step1_complete.py"
    if me not in files:
        raise Refusal(f"LOCK 3 completion code: {p.name} has no entry for {me}")
    bad = []
    for rel, sha in files.items():
        fp = C.REPO / rel
        got = P.sha256_file(fp) if fp.exists() else "MISSING"
        if got != sha:
            bad.append((rel, sha[:12], got[:12]))
    if bad:
        raise Refusal(f"LOCK 3 completion code: {len(bad)} file(s) differ from {p.name}: {bad[:5]}")
    loaded = P.loaded_repo_files()
    extra = sorted(set(loaded) - set(files) - set(frozen_files))
    if extra:
        raise Refusal(f"LOCK 3 completion code: loaded repo modules in neither freeze record: {extra}")
    return {"completion_freeze_record": str(p), "completion_freeze_record_sha256": P.sha256_file(p), "n_files": len(files), "n_loaded_checked": len(loaded)}


def read_prior_run_record(path) -> dict:
    p = Path(path)
    if not p.exists():
        raise Refusal(f"LOCK 4 prior run: {p} does not exist")
    rec = json.loads(p.read_text())
    rec["_path"] = str(p); rec["_sha256"] = P.sha256_file(p)
    return rec


def lock_prior_run(prior: dict) -> dict:
    """Lock 4: the ACQ-R07 run record at its sha256, status stopped (rule C4), stop message naming the AT42-03
    directory and the mode restore (the setgid bit: before 0o2770, after 0o770)."""
    if prior["_sha256"] != SHA_PRIOR_RUN_RECORD:
        raise Refusal(f"LOCK 4 prior run: {Path(prior['_path']).name} sha256 {prior['_sha256']} != {SHA_PRIOR_RUN_RECORD}")
    if prior.get("status") != "stopped (rule C4)":
        raise Refusal(f"LOCK 4 prior run: status {prior.get('status')!r} != 'stopped (rule C4)'")
    err = str(prior.get("error") or "")
    if PRIOR_STOP_DIR not in err or PRIOR_STOP_TEXT not in err or "0o2770" not in err or "0o770" not in err:
        raise Refusal(f"LOCK 4 prior run: stop message does not name {PRIOR_STOP_DIR} and the setgid restore: {err[:200]}")
    return {"prior_run_record": prior["_path"], "prior_run_record_sha256": prior["_sha256"], "status": prior["status"], "error": err,
            "pairs_done": prior.get("pairs_done"), "job_host": prior.get("host"), "started": prior.get("started")}


def deviation_commit(path: Path) -> dict:
    """The note's git state in the repository that holds it: tracked, clean, and the HEAD blob equal to the file."""
    def git(*args):
        r = subprocess.run(["git", *args], cwd=str(path.parent), capture_output=True, text=True)
        return r.returncode, r.stdout.strip()
    rc, top = git("rev-parse", "--show-toplevel")
    if rc != 0:
        return {"tracked": False, "reason": "not inside a git repository"}
    rel = str(path.resolve().relative_to(Path(top).resolve()))
    rc_t, _ = git("ls-files", "--error-unmatch", rel)
    _, commit = git("log", "-1", "--format=%H", "--", rel)
    _, status = git("status", "--short", "--", rel)
    blob = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=top, capture_output=True)
    blob_sha = P.sha256_bytes(blob.stdout) if blob.returncode == 0 else None
    return {"repo": top, "rel": rel, "tracked": rc_t == 0, "commit": commit or None, "clean": status == "", "head_blob_sha256": blob_sha}


def lock_deviation_note(note) -> dict:
    """Lock 5: DEVIATION_phase4_01.md committed in the CNN repo at the R11 path, holding both hashes."""
    p = Path(note)
    if not p.exists():
        raise Refusal(f"LOCK 5 deviation note: {p} does not exist")
    txt = p.read_text(errors="replace").lower()
    missing = [h for h in (PREREG_SHA256, SHA_PRIOR_RUN_RECORD) if h not in txt]
    if missing:
        raise Refusal(f"LOCK 5 deviation note: {p.name} lacks {missing}")
    sha = P.sha256_file(p)
    g = deviation_commit(p)
    if not (g.get("tracked") and g.get("commit") and g.get("clean") and g.get("head_blob_sha256") == sha):
        raise Refusal(f"LOCK 5 deviation note: {p} is not committed (tracked {g.get('tracked')}, commit {g.get('commit')}, clean {g.get('clean')}, head blob == file {g.get('head_blob_sha256') == sha})")
    return {"deviation_note": str(p), "sha256": sha, "commit": g["commit"], "repo": g.get("repo")}


def lock_single_completion(supplement, record_path: Path) -> dict:
    """Lock 7: the supplement does not exist (frozen lock_single_run) and no complete completion record exists."""
    out = S.lock_single_run(supplement)
    if record_path.exists():
        st = json.loads(record_path.read_text()).get("status")
        if st == "complete":
            raise Refusal(f"LOCK 7 single completion: {record_path} exists with status complete (sha256 {P.sha256_file(record_path)})")
        out["prior_completion_record"] = {"path": str(record_path), "status": st}
    out["completion_record"] = str(record_path)
    return out


def dir_metadata(d: Path) -> dict:
    st = os.stat(d)
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    return {"dir": str(d), "mode": oct(st.st_mode & 0o7777), "owner": owner, "group": group}


def lockbox_dir_metadata() -> dict:
    """Metadata (os.stat only; nothing opened or listed) of the two lockbox directories on OAK."""
    m = P.manifest().set_index("pair_id")
    return {pid: dir_metadata(S.pair_dir_of(m.loc[pid])) for pid in C.LOCKBOX}


def lock_lockbox_metadata() -> dict:
    """Lock 8: both lockbox directories have group oak_hilley and mode 2770 (ruling R2 applied)."""
    md = lockbox_dir_metadata()
    bad = {k: v for k, v in md.items() if v["group"] != LOCKBOX_GROUP or v["mode"] != LOCKBOX_MODE}
    if bad:
        raise Refusal(f"LOCK 8 lockbox metadata: expected group {LOCKBOX_GROUP} mode {LOCKBOX_MODE}; got {bad}")
    return md


def enforce_locks(a, pairs, cfg, record_path: Path) -> tuple:
    rec = {}
    rec["lock1_signoff"] = S.lock_signoff(a.signoff, a.prereg_sha256)
    l2 = lock_frozen_code(a.freeze_record or P.FREEZE_RECORD); rec["lock2_frozen_code"] = {k: v for k, v in l2.items() if k != "files"}
    rec["lock3_completion_code"] = lock_completion_code(a.completion_freeze_record or COMPLETION_FREEZE_RECORD, l2["files"])
    prior = read_prior_run_record(a.prior_run_record or PRIOR_RUN_RECORD)
    rec["lock4_prior_run"] = lock_prior_run(prior)
    rec["lock5_deviation_note"] = lock_deviation_note(a.deviation_note or DEVIATION_NOTE)
    rec["lock6_pair_list"] = S.lock_pair_list(pairs, a.run_tag)
    rec["lock7_single_completion"] = lock_single_completion(cfg["supplement"], record_path)
    rec["lock8_lockbox_metadata"] = lock_lockbox_metadata()
    return rec, prior


# --------------------------------------------------------------------------- #
# the finished pairs (A2)
# --------------------------------------------------------------------------- #
def split_pairs(pairs, prior: dict, out_root: Path) -> tuple:
    """finished = pairs whose output directory holds step1_record.json; must equal the pairs with ledger entries in
    the prior record; the rest are pending."""
    m = P.manifest().set_index("pair_id")
    finished, pending = [], []
    for pid in pairs:
        out_dir = out_root / str(m.loc[pid]["harmonized_path"])
        (finished if (out_dir / "step1_record.json").exists() else pending).append(pid)
    in_ledger = []
    for e in prior.get("ledger") or []:
        if e["pair_id"] in pairs and e["pair_id"] not in in_ledger:
            in_ledger.append(e["pair_id"])
    if set(finished) != set(in_ledger):
        raise StopRun(f"finished pairs (step1_record.json present) {sorted(finished)} != pairs with ledger entries in the prior run record {sorted(in_ledger)} (rule C4)")
    done = [p for p in (prior.get("pairs_done") or []) if p in pairs]          # restricted to this run's pair list, as in_ledger is
    if not set(done) <= set(finished):
        raise StopRun(f"prior pairs_done {done} not all finished on disk (rule C4)")
    return finished, pending


def expected_ledger(rec: dict) -> dict:
    """The ledger strings the frozen run_pair writes for a pair, rebuilt from its step1 record (same f-strings)."""
    exp = {}
    c2a, sw, pr, f = rec["c2a"], rec["sweep"], rec.get("products"), rec.get("fetch")
    if "sonar" in c2a:
        exp["c2a"] = ("computed", c2a["sonar_source"]); exp["sweep"] = (sw.get("status"), f"k={sw.get('max_recoverable_k')}")
    else:
        exp["c2a"] = ("prior values kept (no C2a)", c2a["source"]); exp["sweep"] = ("not run (prior k kept)", f"k={sw.get('max_recoverable_k')} from {sw['k_source']}")
    if f:
        exp["fetch"] = ("complete" if f["complete"] else "incomplete", f"{f['n_ok']} of {f['n_planned']} files (rc {f['rc']})")
    if sw.get("max_recoverable_k") is None:
        exp["products"] = ("not built", f"no k (k_sweep_status {sw.get('status')}; rule C3)")
    elif f is not None and not f["complete"]:
        exp["products"] = ("unavailable", f["reason"])
    else:
        exp["products"] = ("built" if pr["available"] else "unavailable", pr.get("reason") or pr.get("unavailable_reason") or f"{pr['n_files_read']} files read; flags {pr['flags']}")
    return exp


SUMMARY_KEYS = ("hr_native_res_m", "lr_native_res_m", "values_source", "max_recoverable_k", "k_sweep_status", "k_source", "per_k", "products", "flags", "ship_products_usable")


def crosscheck(pid: str, rec: dict, prior: dict) -> dict:
    """A2: the record's quantities against the prior run record's per_pair entry (if any) and ledger entries."""
    out = {"per_pair_present": pid in (prior.get("per_pair") or {}), "per_pair": {}, "ledger": {}, "equal": True}
    s = rec.get("summary") or {}
    if out["per_pair_present"]:
        pp = prior["per_pair"][pid]
        for k in SUMMARY_KEYS:
            eq = pp.get(k) == s.get(k)
            out["per_pair"][k] = {"record": s.get(k), "prior": pp.get(k), "equal": eq}
            out["equal"] &= eq
    exp = expected_ledger(rec)
    got = {e["item"]: (e["status"], e["reason"]) for e in (prior.get("ledger") or []) if e["pair_id"] == pid}
    for item, want in exp.items():
        if item in got:
            eq = tuple(got[item]) == tuple(want)
            out["ledger"][item] = {"record": list(want), "prior": list(got[item]), "equal": eq}
            out["equal"] &= eq
        else:
            out["ledger"][item] = {"record": list(want), "prior": None, "equal": None}
    return out


def verify_finished(pid: str, out_dir: Path, prior: dict, read_products_json: bool) -> tuple:
    """Read the two records, verify every listed file's sha256, cross-check, derive usability.  Returns (row-ready
    record, verification dict).  Stops on any mismatch or missing file."""
    rp, sp = out_dir / "step1_record.json", out_dir / "sweep_record.json"
    for p in (rp, sp):
        if not p.exists():
            raise StopRun(f"{pid}: {p} is missing (rule C4)")
    rec = json.loads(rp.read_text()); sweep = json.loads(sp.read_text())
    ver = {"pair_id": pid, "out_dir": str(out_dir), "step1_record_sha256": P.sha256_file(rp), "sweep_record_sha256": P.sha256_file(sp), "files": {}, "n_files_listed": 0, "n_files_ok": 0}
    if rec.get("pair_id") != pid:
        raise StopRun(f"{pid}: step1_record.json names {rec.get('pair_id')} (rule C4)")
    if rec.get("sweep") != sweep:
        raise StopRun(f"{pid}: sweep_record.json differs from the sweep in step1_record.json (rule C4)")
    listed = (rec.get("write_path") or {}).get("files") or {}
    ver["n_files_listed"] = len(listed)
    for rel, sha in listed.items():
        fp = out_dir / rel
        got = P.sha256_file(fp) if fp.exists() else "MISSING"
        ver["files"][rel] = {"recorded": sha, "got": got, "equal": got == sha}
        if got != sha:
            raise StopRun(f"{pid}: {rel} {'missing' if got == 'MISSING' else 'altered'} (recorded {sha[:12]}, got {got[:12]}) (rule C4)")
        ver["n_files_ok"] += 1
    # the fetcher's side-files (a pair the step fetched): name + sha256, recorded, not opened
    side = {}
    if rec.get("fetch"):
        stem = Path(rec["fetch"]["plan_csv"]).stem
        for name in (f"fetch_swath_log_{stem}.csv", f"fetch_swath_summary_{stem}.json"):
            fp = out_dir / name
            side[name] = P.sha256_file(fp) if fp.exists() else "absent"
    ver["fetcher_side_files"] = side
    ver["crosscheck"] = crosscheck(pid, rec, prior)
    if not ver["crosscheck"]["equal"]:
        raise StopRun(f"{pid}: record differs from the prior run record: {json.dumps({k: v for k, v in ver['crosscheck'].items() if k != 'equal'}, default=str)[:400]} (rule C4)")
    # usability (rule C1, frozen usable_rule)
    pr = rec.get("products")
    if pr is None:
        prod_for_rule, src = None, "no products (record)"
    elif read_products_json:
        pj = json.loads((out_dir / S.V21.OUT_NAME / "products.json").read_text())
        prod_for_rule = {"available": bool(pj.get("available")) and all(pj["available"].values()), "flags": list((pj.get("qa_vs_lr_tif") or {}).get("flags") or []),
                         "unavailable_reason": pj.get("unavailable_reason"), "reason": pr.get("reason")}
        src = f"{S.V21.OUT_NAME}/products.json (available flags, qa_vs_lr_tif.flags)"
    else:
        prod_for_rule, src = pr, "step1_record.json products (available, flags)"
    usable, reason = S.usable_rule(prod_for_rule)
    ver["usable"] = {"derived": usable, "reason": reason, "source": src, "record_usable": rec.get("usable"), "record_reason": rec.get("usable_reason"),
                     "equal_to_record": (usable == rec.get("usable") and reason == rec.get("usable_reason")) if "usable" in rec else None}
    if ver["usable"]["equal_to_record"] is False:
        raise StopRun(f"{pid}: usability {usable} ({reason}) != record {rec.get('usable')} ({rec.get('usable_reason')}) (rule C4)")
    rec["usable"], rec["usable_reason"] = usable, reason
    # directory-mode history: record (before, opened), the prior stop message, now
    wp = rec.get("write_path") or {}
    err = str(prior.get("error") or "")
    hist = {"record_before": wp.get("mode_before"), "record_opened": wp.get("mode_opened"), "record_after": wp.get("mode_after"),
            "stop_after": (err.split("after ")[1].split(")")[0] if (str(out_dir) in err and "after " in err) else None),
            "now": dir_metadata(out_dir)}
    ver["mode_history"] = hist
    return rec, ver


# --------------------------------------------------------------------------- #
# supplement (A4): the frozen main()'s writer lines (616-622), reproduced — challenge clause
# --------------------------------------------------------------------------- #
def write_supplement(rows, sp: Path) -> pd.DataFrame:
    cols = list(P.manifest().columns)
    sup = pd.DataFrame(rows)[cols]
    sp.parent.mkdir(parents=True, exist_ok=True)
    if sp.exists():
        sp.chmod(0o644)
    sup.to_parquet(sp, index=False); sp.chmod(0o444)
    return sup


def provenance(pid: str, finished: bool, prior: dict, rec_sha: str | None) -> str:
    if finished:
        return (f"provenance (ACQ-R07b): step-1 quantities from the stopped run record {Path(prior['_path']).name} (sha256 {prior['_sha256'][:16]}…, "
                f"host {prior.get('host')}); row rebuilt by sealed_step1_complete.py from the pair's step1_record.json (sha256 {rec_sha[:16]}…); nothing recomputed")
    return "provenance (ACQ-R07b): computed by the completion run (sealed_step1_complete.py calling the frozen per-pair code unchanged)"


# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", required=True, choices=S.MODE_CHOICES)
    ap.add_argument("--pairs", default=None); ap.add_argument("--run-tag", default="")
    ap.add_argument("--nproc", type=int, default=6); ap.add_argument("--batch-files", type=int, default=1)
    ap.add_argument("--signoff", default=None); ap.add_argument("--prereg-sha256", default=None); ap.add_argument("--freeze-record", default=None)
    ap.add_argument("--completion-freeze-record", default=None); ap.add_argument("--prior-run-record", default=None); ap.add_argument("--deviation-note", default=None)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    t_run = time.time()
    cfg = dict(MODES[a.mode]); cfg["mode"] = a.mode
    pairs = [p.strip() for p in a.pairs.split(",") if p.strip()] if a.pairs else list(cfg["pairs"])
    bad = [p for p in pairs if p not in cfg["pairs"]]
    if bad:
        raise Refusal(f"pair list: {bad} not in the {a.mode} pair list {list(cfg['pairs'])}")
    out_root = cfg["out_root"] / a.run_tag if a.run_tag else cfg["out_root"]
    rec_tag = f"{a.run_tag}_{RECORD_TAG}" if a.run_tag else RECORD_TAG
    rec_ns = SimpleNamespace(run_tag=rec_tag)
    record_path = (P.REHEARSAL_DIR if a.mode == "rehearsal" else P.REPORT_DIR) / f"step1_run_{a.mode}_{rec_tag}.json"
    sp = Path(cfg["supplement"]) if not a.run_tag else Path(cfg["supplement"]).with_name(Path(cfg["supplement"]).stem + f"_{rec_tag}.parquet")
    run = {"directive": "ACQ-R07b", "entry": "src/phase4/sealed_step1_complete.py", "mode": a.mode, "run_tag": a.run_tag, "record_tag": rec_tag, "pairs": pairs, "out_root": str(out_root),
           "started": P.utc_now(), "host": P.hostname(), "cpu_model": P.cpu_model(), "code_commit": P.git_commit(), "nproc": a.nproc, "batch_files": a.batch_files,
           "mbsystem": C.MBSYSTEM_VERSION, "sandbox": C.SANDBOX, "container_digest": C.CONTAINER_DIGEST}
    run["fixed_input_sha256"] = P.check_fixed_inputs()
    guard = G.run(write=False); run["guard_selftest"] = {k: v for k, v in guard.items() if k != "reader_checks"}
    run["guard_selftest"]["reader_checks"] = {"n": guard["reader_checks"]["n"], "n_blocked": guard["reader_checks"]["n_blocked"]}
    if not guard["all_passed"]:
        raise Refusal("guard self-test failed: " + json.dumps(run["guard_selftest"], default=str)[:300])
    if a.mode == "phase4":                                   # the locks, then the allowance
        run["locks"], prior = enforce_locks(a, pairs, cfg, record_path)
        run["freeze_record_sha256"] = run["locks"]["lock2_frozen_code"]["freeze_record_sha256"]
        run["completion_freeze_record_sha256"] = run["locks"]["lock3_completion_code"]["completion_freeze_record_sha256"]
        run["prior_run_record_sha256"] = prior["_sha256"]; run["prior_run_record"] = prior["_path"]
        run["deviation_note"] = run["locks"]["lock5_deviation_note"]
        run["allowance"] = list(C.install_phase4_allowance(cfg["allow"], reason="ACQ-R06 phase4 locks passed: sign-off, frozen code, completion code, prior run, deviation note, pair list, single completion, lockbox metadata (ACQ-R07b completion)"))
    else:
        if not a.prior_run_record:
            raise Refusal("rehearsal mode: --prior-run-record (the stopped rehearsal run record) is required")
        prior = read_prior_run_record(a.prior_run_record)
        run["prior_run_record_sha256"] = prior["_sha256"]; run["prior_run_record"] = prior["_path"]
        run["freeze_record_sha256"] = P.sha256_file(P.FREEZE_RECORD)
        run["completion_freeze_record_sha256"] = P.sha256_file(COMPLETION_FREEZE_RECORD) if COMPLETION_FREEZE_RECORD.exists() else None
        if sp.exists():
            raise Refusal(f"rehearsal: supplement {sp} already exists")
    run["prior_run"] = {"status": prior.get("status"), "error": prior.get("error"), "pairs_done": prior.get("pairs_done"), "host": prior.get("host"), "started": prior.get("started")}
    m = P.manifest().set_index("pair_id")
    rows, recs, ledger, verification = [], {}, [], {}
    try:
        finished, pending = split_pairs(pairs, prior, out_root)
        run["finished_pairs"], run["pending_pairs"] = finished, pending
        # A2 — the finished pairs, from their records
        row_of = {}
        for pid in finished:
            out_dir = out_root / str(m.loc[pid]["harmonized_path"])
            rec, ver = verify_finished(pid, out_dir, prior, read_products_json=pid not in (prior.get("per_pair") or {}))
            verification[pid] = ver
            ledger.append({"pair_id": pid, "item": "record", "status": "read", "reason": f"step1_record.json {ver['step1_record_sha256'][:12]}, sweep_record.json {ver['sweep_record_sha256'][:12]}"})
            ledger.append({"pair_id": pid, "item": "files", "status": "verified", "reason": f"{ver['n_files_ok']} of {ver['n_files_listed']} listed files at their sha256"})
            ledger.append({"pair_id": pid, "item": "crosscheck", "status": "equal", "reason": f"per_pair {'present' if ver['crosscheck']['per_pair_present'] else 'absent'}; ledger items {sorted(ver['crosscheck']['ledger'])}"})
            ledger.append({"pair_id": pid, "item": "usable", "status": str(ver["usable"]["derived"]), "reason": f"{ver['usable']['reason']} [from {ver['usable']['source']}]"})
            r = S.supplement_row(m.loc[pid], rec, cfg["mode"])
            r["notes"] = (str(r.get("notes") or "") + " | " + provenance(pid, True, prior, ver["step1_record_sha256"])).strip(" |")
            row_of[pid] = r
            s = dict(rec.get("summary") or {}); s["provenance"] = "record (not recomputed)"; s["write_path"] = {k: (rec.get("write_path") or {}).get(k) for k in ("mode_before", "mode_opened", "mode_after", "restored")}
            s["mode_history"] = ver["mode_history"]; s["ship_products_usable"] = rec["usable"]; s["usable_reason"] = rec["usable_reason"]
            recs[pid] = s
            ledger.append({"pair_id": pid, "item": "row", "status": "rebuilt", "reason": "frozen supplement_row on the record; provenance appended to notes"})
        # A3 — the pending pairs, by the frozen per-pair code
        run["fetch_trigger"] = {c: sorted(v) for c, v in S.fetch_trigger(pairs).items()}
        run["swath_preflight"] = S.preflight_swath(pending, run["fetch_trigger"])
        for pid in pending:
            r, rec = S.run_pair(pid, cfg, out_root, a.nproc, a.batch_files, ledger)
            r["notes"] = (str(r.get("notes") or "") + " | " + provenance(pid, False, prior, None)).strip(" |")
            row_of[pid] = r
            s = dict(rec["summary"]); s["provenance"] = "computed by the completion run"; recs[pid] = s
        rows = [row_of[pid] for pid in pairs]
    except StopRun as e:
        run.update({"status": "stopped (rule C4)", "error": str(e), "ledger": ledger, "pairs_done": list(recs), "per_pair": recs, "verification": verification, "wall_s": round(time.time() - t_run, 1)})
        S.write_run_record(run, cfg, rec_ns)
        log.error("STOP (rule C4): %s", e)
        raise
    run["loaded_repo_files"] = P.loaded_repo_files()
    if a.mode == "phase4":                                   # re-verify both records after the run (lazy imports)
        l2 = lock_frozen_code(a.freeze_record or P.FREEZE_RECORD)
        run["locks"]["lock2_after_run"] = {k: v for k, v in l2.items() if k != "files"}
        run["locks"]["lock3_after_run"] = lock_completion_code(a.completion_freeze_record or COMPLETION_FREEZE_RECORD, l2["files"])
    sup = write_supplement(rows, sp)
    ids = list(sup["pair_id"])
    if a.mode == "phase4" and (sorted(ids) != sorted(P.SEALED_PAIRS) or len(ids) != 5):
        raise StopRun(f"supplement ids {ids} != the five sealed pairs")
    run.update({"status": "complete", "supplement": str(sp), "supplement_sha256": P.sha256_file(sp), "n_rows": len(sup), "supplement_pair_ids": ids, "pairs_done": list(recs),
                "per_pair": recs, "verification": verification, "ledger": ledger, "wall_s": round(time.time() - t_run, 1), "finished": P.utc_now()})
    p = S.write_run_record(run, cfg, rec_ns)
    for pid, s in recs.items():
        print(f"{pid:30s} hr {s['hr_native_res_m']:>7} m  lr {s['lr_native_res_m']:>7} m  k {str(s['max_recoverable_k']):>4}  {str(s['k_sweep_status']):10s} "
              f"products {s['products']:11s} flags {s['flags']}  usable {s['ship_products_usable']}  [{s['provenance']}]")
    print(f"supplement {sp} ({len(sup)} rows, sha256 {run['supplement_sha256'][:16]}…); run record {p}; wall {run['wall_s']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
