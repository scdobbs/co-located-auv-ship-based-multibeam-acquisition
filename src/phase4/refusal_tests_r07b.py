"""ACQ-R07b Part B2 — refusal tests of sealed_step1_complete.py in phase4 mode, with the guard installed underneath.

As ACQ-R06 refusal_tests: every test calls main() in-process with dummy files; the phase4 allowance is replaced for the
suite by a function that raises (safety net), so the positive control is exactly 'every lock satisfied by dummies ->
the allowance is reached -> the safety net stops the run'.  The finished-pair tests (listed output file missing /
altered) run in rehearsal mode on a harness copy of a B1 pair, where the check lives after the allowance.
Usage: python -m src.phase4.refusal_tests_r07b   (after harness_r07b)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

from src.acq_r01 import common as C
from src.phase4 import common as P
from src.phase4 import sealed_step1 as S
from src.phase4 import sealed_step1_complete as SC
from src.phase4 import harness_r07b as H

PREREG_DUMMY = "a" * 64
SAFETY = "TEST SAFETY NET: the phase4 allowance was reached"


class SafetyStop(RuntimeError):
    pass


def _no_allowance(tokens, reason):
    raise SafetyStop(SAFETY + f" (tokens {len(tuple(tokens))}, reason {reason!r})")


def frozen_files() -> dict:
    return json.loads(P.FREEZE_RECORD.read_text())["files"]


def make_completion_record(path: Path, alter: str | None = None, drop: str | None = None) -> dict:
    files = {k: v for k, v in P.loaded_repo_files().items() if k not in frozen_files()}
    if alter:
        files[alter] = "0" * 64
    if drop:
        files.pop(drop, None)
    rec = {"files": files, "note": "dummy completion freeze record for the ACQ-R07b refusal tests"}
    path.write_text(json.dumps(rec, indent=1))
    return rec


def run_case(name, argv, expect_prefix, expect_type=S.Refusal, extra=None):
    before = C.phase4_allowance()
    try:
        SC.main(argv)
        got = {"raised": None, "message": "RETURNED WITHOUT REFUSING"}
    except BaseException as e:   # noqa: BLE001
        got = {"raised": type(e).__name__, "message": str(e)[:400]}
    after = C.phase4_allowance()
    ok = got["raised"] == expect_type.__name__ and got["message"].startswith(expect_prefix) and after == () and before == ()
    r = {"test": name, "argv": " ".join(str(x) for x in argv), "expected": f"{expect_type.__name__}: {expect_prefix}…", "raised": got["raised"], "message": got["message"],
         "allowance_after": list(after), "passed": bool(ok)}
    if extra:
        r.update(extra)
    return r


def main(argv=None):
    P.check_fixed_inputs()
    H.install_patches()                                          # report dirs (ACQ-R07b/rehearsal), stand-in relabels, listing
    tmp = Path(tempfile.mkdtemp(prefix="acq_r07b_refusal_", dir=str(P.SCRATCH_ROOT)))
    results = []
    orig_allow, orig_meta, orig_commit = C.install_phase4_allowance, SC.lockbox_dir_metadata, SC.deviation_commit
    C.install_phase4_allowance = _no_allowance
    try:
        so_ok = tmp / "signoff_ok.md"; so_ok.write_text(f"Phase 4 pre-registration signed. sha256 {PREREG_DUMMY}\n")
        so_wrong = tmp / "signoff_wrong.md"; so_wrong.write_text("sha256 " + "b" * 64 + "\n")
        fr_changed = tmp / "freeze_changed.json"
        fr = json.loads(P.FREEZE_RECORD.read_text()); fr["files"]["src/acq_r01/common.py"] = "0" * 64; fr_changed.write_text(json.dumps(fr, indent=1))
        cr_ok = tmp / "completion_ok.json"; make_completion_record(cr_ok)
        cr_alt = tmp / "completion_altered.json"; make_completion_record(cr_alt, alter="src/phase4/sealed_step1_complete.py")
        cr_unlisted = tmp / "completion_unlisted.json"; make_completion_record(cr_unlisted, drop="src/phase4/refusal_tests_r07b.py")
        prior_ok = str(SC.PRIOR_RUN_RECORD)
        prior_other = tmp / "prior_other.json"; pr = json.loads(SC.PRIOR_RUN_RECORD.read_text()); pr["note"] = "copy"; prior_other.write_text(json.dumps(pr, indent=1))
        note_ok = tmp / "DEVIATION_ok.md"; note_ok.write_text(f"deviation; prereg {SC.PREREG_SHA256}; prior run {SC.SHA_PRIOR_RUN_RECORD}\n")
        note_one = tmp / "DEVIATION_one_hash.md"; note_one.write_text(f"deviation; prereg {SC.PREREG_SHA256}\n")
        ok_commit = lambda p: {"repo": "dummy", "rel": p.name, "tracked": True, "commit": "d" * 40, "clean": True, "head_blob_sha256": P.sha256_file(p)}
        ok_meta = lambda: {pid: {"dir": f"dummy/{pid}", "mode": "0o2770", "owner": "scdobbs", "group": "oak_hilley"} for pid in C.LOCKBOX}
        bad_meta = lambda: {pid: {"dir": f"dummy/{pid}", "mode": ("0o770" if i else "0o2770"), "owner": "scdobbs", "group": "nobody"} for i, pid in enumerate(C.LOCKBOX)}
        base = ["--mode", "phase4", "--prereg-sha256", PREREG_DUMMY]
        full = lambda **kw: base + ["--signoff", str(kw.get("signoff", so_ok)), "--freeze-record", str(kw.get("freeze", P.FREEZE_RECORD)), "--completion-freeze-record", str(kw.get("comp", cr_ok)),
                                    "--prior-run-record", str(kw.get("prior", prior_ok)), "--deviation-note", str(kw.get("note", note_ok))] + list(kw.get("more", []))
        SC.lockbox_dir_metadata = ok_meta; SC.deviation_commit = ok_commit
        results.append(run_case("1 without the sign-off", full(signoff=tmp / "absent.md"), "LOCK 1 sign-off"))
        results.append(run_case("1b wrong pre-registration sha256 in the sign-off", full(signoff=so_wrong), "LOCK 1 sign-off"))
        results.append(run_case("2 changed frozen file (freeze record with another hash for src/acq_r01/common.py -> record sha256 differs)", full(freeze=fr_changed), "LOCK 2 frozen code"))
        results.append(run_case("2b frozen freeze record absent", full(freeze=tmp / "absent.json"), "LOCK 2 frozen code"))
        results.append(run_case("3 changed completion file (hash altered)", full(comp=cr_alt), "LOCK 3 completion code"))
        results.append(run_case("3b loaded completion module unlisted in both records", full(comp=cr_unlisted), "LOCK 3 completion code"))
        results.append(run_case("3c completion freeze record absent", full(comp=tmp / "absent.json"), "LOCK 3 completion code"))
        results.append(run_case("4 prior run record of another sha256", full(prior=prior_other), "LOCK 4 prior run"))
        results.append(run_case("5 without the deviation note", full(note=tmp / "absent.md"), "LOCK 5 deviation note"))
        results.append(run_case("5b deviation note missing the prior-run hash", full(note=note_one), "LOCK 5 deviation note"))
        SC.deviation_commit = orig_commit
        results.append(run_case("5c deviation note with both hashes but not committed (temp file outside any repo)", full(), "LOCK 5 deviation note"))
        # 5d lock 5 on a genuinely committed file (this repo's signed template holds both hashes): the git check must pass (unpatched)
        try:
            g5 = SC.lock_deviation_note(SC.REPORT_DIR_R07B / "DEVIATION_phase4_01_TEMPLATE.md")
            results.append({"test": "5d lock 5 passes on a committed note (acquisition repo's signed template, unpatched git check)", "argv": "", "expected": "commit returned",
                            "raised": "ok", "message": json.dumps(g5)[:300], "allowance_after": list(C.phase4_allowance()), "passed": bool(g5.get("commit")) and C.phase4_allowance() == ()})
        except BaseException as e:   # noqa: BLE001
            results.append({"test": "5d lock 5 passes on a committed note (acquisition repo's signed template, unpatched git check)", "argv": "", "expected": "commit returned",
                            "raised": type(e).__name__, "message": str(e)[:300], "allowance_after": list(C.phase4_allowance()), "passed": False})
        SC.deviation_commit = ok_commit
        results.append(run_case("6 development pair in the list", full(more=["--pairs", ",".join(P.SEALED_PAIRS) + ",FK151121__MGDS_22383"]), "pair list:"))
        results.append(run_case("6b four sealed pairs only", full(more=["--pairs", ",".join(list(P.SEALED_PAIRS)[:4])]), "LOCK 3 pair list"))
        sup = P.SUPPLEMENT_PHASE4
        if sup.exists():
            raise SystemExit(f"{sup} exists before the tests; refusing to touch it")
        try:
            pd.DataFrame({"pair_id": ["dummy"]}).to_parquet(sup, index=False)
            results.append(run_case("7 the supplement exists", full(), "LOCK 4 single run"))
        finally:
            if sup.exists():
                sup.unlink()
        crec = P.REPORT_DIR / f"step1_run_phase4_{SC.RECORD_TAG}.json"
        if crec.exists():
            raise SystemExit(f"{crec} exists before the tests; refusing to touch it")
        try:
            crec.write_text(json.dumps({"status": "complete", "note": "dummy for refusal test 7b"}))
            results.append(run_case("7b a complete completion record exists", full(), "LOCK 7 single completion"))
        finally:
            if crec.exists():
                crec.unlink()
        SC.lockbox_dir_metadata = bad_meta
        results.append(run_case("8 a lockbox directory not oak_hilley / 2770 (harness listing: nobody, 0o770)", full(), "LOCK 8 lockbox metadata"))
        SC.lockbox_dir_metadata = ok_meta
        results.append(run_case("9 positive control (all locks satisfied by dummies -> allowance reached -> safety net)", full(), SAFETY, expect_type=SafetyStop))
        # 10 finished pair: a listed output file altered / missing (rehearsal mode, harness copy of a B1 pair; the check lives after the allowance)
        src = H.ROOT / H.TAG_STOP / "harmonized" / H.ORDER[0]
        prior = str(H.REH / f"step1_run_rehearsal_{H.TAG_STOP}.json")
        for label, how in (("10 finished pair: listed output file altered (sweep_record.json)", "alter"), ("10b finished pair: listed output file missing (ship_count.tif)", "delete")):
            tag = f"refusal_r07b_{how}"
            root = H.ROOT / tag; H.rm_tree(root)
            dst = root / "harmonized" / H.ORDER[0]; dst.parent.mkdir(parents=True)
            shutil.copytree(src, dst)
            for d, dirs, files in os.walk(dst):
                os.chmod(d, 0o2770)
            target = dst / "sweep_record.json" if how == "alter" else dst / S.V21.OUT_NAME / "ship_count.tif"
            os.chmod(target, 0o644)
            if how == "alter":
                target.write_text(json.dumps({**json.loads(target.read_text()), "harness": "altered"}, indent=1))
            else:
                target.unlink()
            for p in (H.REH / f"step1_run_rehearsal_{tag}_{SC.RECORD_TAG}.json", H.REH / f"supplement_rehearsal_{tag}_{SC.RECORD_TAG}.parquet"):
                if p.exists():
                    p.chmod(0o644); p.unlink()
            argv_r = ["--mode", "rehearsal", "--run-tag", tag, "--prior-run-record", prior, "--pairs", H.ORDER[0]]
            exp = f"{H.ORDER[0]}: sweep_record.json differs" if how == "alter" else f"{H.ORDER[0]}: {S.V21.OUT_NAME}/ship_count.tif missing"
            r = run_case(label, argv_r, exp, expect_type=S.StopRun)
            r["supplement_written"] = (H.REH / f"supplement_rehearsal_{tag}_{SC.RECORD_TAG}.parquet").exists()
            rr = H.REH / f"step1_run_rehearsal_{tag}_{SC.RECORD_TAG}.json"
            r["run_record_status"] = json.loads(rr.read_text()).get("status") if rr.exists() else None
            r["passed"] = bool(r["passed"] and not r["supplement_written"] and r["run_record_status"] == "stopped (rule C4)")
            results.append(r)
            H.rm_tree(root)
    finally:
        C.install_phase4_allowance, SC.lockbox_dir_metadata, SC.deviation_commit = orig_allow, orig_meta, orig_commit
        shutil.rmtree(tmp, ignore_errors=True)
    g = __import__("src.phase4.guard_selftest", fromlist=["run"]).run(write=False)
    results.append({"test": "11 guard blocks every sealed target after the suite", "argv": "", "expected": "all blocked", "raised": f"{g['reader_checks']['n_blocked']}/{g['reader_checks']['n']} blocked",
                    "message": json.dumps(g["controls"]), "allowance_after": list(C.phase4_allowance()), "passed": bool(g["all_passed"])})
    n_ok = sum(r["passed"] for r in results)
    out = {"generated": P.utc_now(), "n_tests": len(results), "n_passed": n_ok, "all_passed": n_ok == len(results), "allowance_after_suite": list(C.phase4_allowance()),
           "guard_selftest_after": {k: v for k, v in g.items() if k in ("all_passed", "controls")}, "safety_net": "C.install_phase4_allowance replaced by a raising function for the suite; restored afterwards",
           "patched_for_dummies": ["SC.lockbox_dir_metadata (locks 8 / positive control)", "SC.deviation_commit (lock 5 content tests / positive control; unpatched for 5c)"], "tests": results, "code_commit": P.git_commit()}
    P.write_json(SC.REPORT_DIR_R07B / "refusal_tests_r07b.json", out, mode=0o644)
    for r in results:
        print(("PASS" if r["passed"] else "FAIL"), r["test"], "->", r["raised"], r["message"][:110])
    print(f"refusal tests: {n_ok}/{len(results)} passed; allowance after suite {out['allowance_after_suite']}")
    return 0 if out["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
