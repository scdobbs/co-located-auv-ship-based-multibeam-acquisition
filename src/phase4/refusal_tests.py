"""ACQ-R06 Part A — refusal tests of sealed_step1.py in phase4 mode, with the guard installed underneath.

Every test calls sealed_step1.main() in-process with dummy files and records the exception raised.  Safety net: the
phase4 allowance (src.acq_r01.common.install_phase4_allowance) is replaced for the duration of the tests by a function
that raises; if a lock failed to refuse, the run would stop there, before any sealed read.  The positive control is
exactly that: with every lock satisfiable the script must reach the allowance and stop on the safety net.
Usage: python -m src.phase4.refusal_tests
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

from src.acq_r01 import common as C
from src.phase4 import common as P
from src.phase4 import sealed_step1 as S

PREREG_DUMMY = "a" * 64                                  # the "tagged pre-registration" sha256 of the tests
SAFETY = "TEST SAFETY NET: the phase4 allowance was reached"


class SafetyStop(RuntimeError):
    pass


def _no_allowance(tokens, reason):
    raise SafetyStop(SAFETY + f" (tokens {len(tuple(tokens))}, reason {reason!r})")


def make_freeze_record(path: Path, alter: str | None = None, drop: str | None = None) -> dict:
    files = P.loaded_repo_files()
    if alter:
        files[alter] = "0" * 64
    if drop:
        files.pop(drop)
    rec = {"files": files, "commit": P.git_commit(), "note": "dummy freeze record for the ACQ-R06 refusal tests"}
    path.write_text(json.dumps(rec, indent=1))
    return rec


def run_case(name, argv, expect_prefix, expect_type=S.Refusal):
    """Run main(argv); the case passes if the expected exception type is raised with the expected message prefix."""
    before = C.phase4_allowance()
    try:
        S.main(argv)
        got = {"raised": None, "message": "RETURNED WITHOUT REFUSING"}
    except BaseException as e:   # noqa: BLE001  (every outcome is recorded)
        got = {"raised": type(e).__name__, "message": str(e)[:400]}
    after = C.phase4_allowance()
    ok = got["raised"] == expect_type.__name__ and got["message"].startswith(expect_prefix) and after == () and before == ()
    return {"test": name, "argv": " ".join(argv), "expected": f"{expect_type.__name__}: {expect_prefix}…", "raised": got["raised"],
            "message": got["message"], "allowance_after": list(after), "passed": bool(ok)}


def main(argv=None):
    P.check_fixed_inputs()
    tmp = Path(tempfile.mkdtemp(prefix="acq_r06_refusal_", dir=str(P.SCRATCH_ROOT if P.SCRATCH_ROOT.exists() else "/tmp")))
    results = []
    orig_allow = C.install_phase4_allowance
    C.install_phase4_allowance = _no_allowance          # safety net for the whole suite
    try:
        signoff_ok = tmp / "signoff_ok.md"; signoff_ok.write_text(f"Phase 4 pre-registration signed. sha256 {PREREG_DUMMY}\n")
        signoff_wrong = tmp / "signoff_wrong.md"; signoff_wrong.write_text("Phase 4 pre-registration signed. sha256 " + "b" * 64 + "\n")
        fr_ok = tmp / "freeze_ok.json"; make_freeze_record(fr_ok)
        fr_changed = tmp / "freeze_changed.json"; make_freeze_record(fr_changed, alter="src/acq_r01/common.py")
        fr_missing = tmp / "freeze_missing_entry.json"; make_freeze_record(fr_missing, drop="src/discovery/stage_c2c_recalibrate.py")
        five = ",".join(P.SEALED_PAIRS)
        base = ["--mode", "phase4", "--prereg-sha256", PREREG_DUMMY]
        # 1 without the sign-off
        results.append(run_case("1 no sign-off file", base + ["--signoff", str(tmp / "absent.md"), "--freeze-record", str(fr_ok)], "LOCK 1 sign-off"))
        results.append(run_case("1b sign-off arguments absent", ["--mode", "phase4", "--freeze-record", str(fr_ok)], "LOCK 1 sign-off"))
        # 2 wrong pre-registration hash
        results.append(run_case("2 wrong pre-registration sha256", base + ["--signoff", str(signoff_wrong), "--freeze-record", str(fr_ok)], "LOCK 1 sign-off"))
        # 3 changed code file / module not in the record / record absent
        results.append(run_case("3 changed code file (src/acq_r01/common.py hash differs)", base + ["--signoff", str(signoff_ok), "--freeze-record", str(fr_changed)], "LOCK 2 freeze record"))
        results.append(run_case("3b loaded module absent from the freeze record", base + ["--signoff", str(signoff_ok), "--freeze-record", str(fr_missing)], "LOCK 2 freeze record"))
        results.append(run_case("3c freeze record file absent", base + ["--signoff", str(signoff_ok), "--freeze-record", str(tmp / "absent.json")], "LOCK 2 freeze record"))
        # 4 a development pair in the list
        results.append(run_case("4 development pair in the list", base + ["--signoff", str(signoff_ok), "--freeze-record", str(fr_ok), "--pairs", five + ",FK151121__MGDS_22383"], "pair list:"))
        results.append(run_case("4b development pair instead of a sealed pair", base + ["--signoff", str(signoff_ok), "--freeze-record", str(fr_ok), "--pairs", ",".join(list(P.SEALED_PAIRS)[:4]) + ",FK151121__MGDS_22383"], "pair list:"))
        # 5 a missing sealed pair
        results.append(run_case("5 missing sealed pair (four of five)", base + ["--signoff", str(signoff_ok), "--freeze-record", str(fr_ok), "--pairs", ",".join(list(P.SEALED_PAIRS)[:4])], "LOCK 3 pair list"))
        results.append(run_case("5b --run-tag given in phase4 mode", base + ["--signoff", str(signoff_ok), "--freeze-record", str(fr_ok), "--run-tag", "x"], "LOCK 3 pair list"))
        # 6 the supplement exists (dummy file at the real path, removed afterwards)
        sup = P.SUPPLEMENT_PHASE4
        if sup.exists():
            raise SystemExit(f"{sup} exists before the tests; refusing to touch it")
        try:
            pd.DataFrame({"pair_id": ["dummy"]}).to_parquet(sup, index=False)
            results.append(run_case("6 supplement already exists", base + ["--signoff", str(signoff_ok), "--freeze-record", str(fr_ok)], "LOCK 4 single run"))
        finally:
            if sup.exists():
                sup.unlink()
        # 7 positive control: every lock satisfiable -> the script reaches the allowance and stops on the safety net
        results.append(run_case("7 positive control (all locks pass -> allowance reached -> safety net)", base + ["--signoff", str(signoff_ok), "--freeze-record", str(fr_ok)], SAFETY, expect_type=SafetyStop))
        # 10 (ACQ-R06b) the fetch trigger set is not exactly {AT42-03, TN159}: harness listing in which AT42-03 is present
        real_listing = P.oak_swath_listing
        P.oak_swath_listing = lambda: real_listing() | {"AT42-03"}
        try:
            results.append(run_case("10 fetch trigger set != {AT42-03, TN159} (harness listing holds AT42-03)", base + ["--signoff", str(signoff_ok), "--freeze-record", str(fr_ok)], "LOCK 5 fetch trigger"))
        finally:
            P.oak_swath_listing = real_listing
        # 11 (ACQ-R06b) a confirmatory cruise directory count differs from its fetch manifest (harness counts; the allowance
        #    replaced by a recording no-op so that the preflight runs on canned numbers; run_pair fenced by the safety net)
        real_cnt, real_man, real_run = S.swath_count_on_disk, S.manifest_swath_count, S.run_pair
        C.install_phase4_allowance = lambda tokens, reason: ()
        S.swath_count_on_disk = lambda d: 27; S.manifest_swath_count = lambda d: 28
        S.run_pair = lambda *a_, **k_: (_ for _ in ()).throw(SafetyStop(SAFETY + " (run_pair)"))
        try:
            results.append(run_case("11 confirmatory cruise directory count != fetch manifest (harness 27 vs 28)", base + ["--signoff", str(signoff_ok), "--freeze-record", str(fr_ok)],
                                    "KN182L03__MGDS_30193: KN182L03 holds 27 swath files but its fetch manifest lists 28", expect_type=S.StopRun))
        finally:
            S.swath_count_on_disk, S.manifest_swath_count, S.run_pair = real_cnt, real_man, real_run
            C.install_phase4_allowance = _no_allowance
        # 12 (ACQ-R06b) the A1 consistency check fails: harness June record with a different lr_native (rehearsal mode, RR1506 relabelled lockbox)
        old_m, old_j = P._MANIFEST, P._JUNE_SWEEP
        try:
            df = P.manifest().copy(); df.loc[df.pair_id == "RR1506__MGDS_29779", "designation"] = "lockbox"; P._MANIFEST = df
            P._JUNE_SWEEP = {**P.june_sweep_record(), "RR1506__MGDS_29779": {**P.june_sweep_record()["RR1506__MGDS_29779"], "lr_native_m": 21.0}}
            results.append(run_case("12 A1 consistency check fails (harness June record lr_native 21.0 vs manifest 20.3) -> C4 stop", ["--mode", "rehearsal", "--run-tag", "refusal12", "--pairs", "RR1506__MGDS_29779"],
                                    "RR1506__MGDS_29779: A1 consistency check failed", expect_type=S.StopRun))
            results[-1]["supplement_written"] = (P.REHEARSAL_DIR / "supplement_rehearsal_refusal12.parquet").exists()
            results[-1]["passed"] = results[-1]["passed"] and not results[-1]["supplement_written"]
        finally:
            P._MANIFEST, P._JUNE_SWEEP = old_m, old_j
    finally:
        C.install_phase4_allowance = orig_allow
        shutil.rmtree(tmp, ignore_errors=True)
    # 13 (ACQ-R06b) the guard still blocks every sealed target afterwards
    g = __import__("src.phase4.guard_selftest", fromlist=["run"]).run(write=False)
    results.append({"test": "13 guard blocks every sealed target after the suite", "argv": "", "expected": "all blocked", "raised": f"{g['reader_checks']['n_blocked']}/{g['reader_checks']['n']} blocked",
                    "message": json.dumps(g["controls"]), "allowance_after": list(C.phase4_allowance()), "passed": bool(g["all_passed"])})
    # 8 rule C2 / C4 classifier and rule C1 on synthetic inputs (the data-tied builder-failure path is not reachable on the rehearsal pairs)
    cases = [("ValueError cannot infer MB format", ValueError("cannot infer MB format for x.bin"), True),
             ("mblist non-zero rc on the file", RuntimeError("P: 2 mblist call(s) failed or timed out ([{'file': 'a', 'n_rows': 0, 'rc': 3, 'stderr': 'MBIO Error: format'}]); not writing"), True),
             ("mblist container timeout", RuntimeError("P: 1 mblist call(s) failed or timed out ([{'file': 'a', 'rc': -9, 'stderr': 'mblist/container timeout (2 x 2400 s)'}])"), False),
             ("mblist container start failure rc 255", RuntimeError("P: 1 mblist call(s) failed or timed out ([{'file': 'a', 'rc': 255, 'stderr': ''}])"), False),
             ("fetch incomplete", RuntimeError("X: fetch incomplete"), False), ("missing swath directory", FileNotFoundError("raw_lr_swath/X"), False),
             ("assertion inside the builder", AssertionError("median count != bin count"), False)]
    for name, exc, want in cases:
        got, reason = S.classify_builder_error(exc)
        results.append({"test": f"8 rule C2 classifier: {name}", "argv": "", "expected": f"data_tied={want}", "raised": f"data_tied={got}", "message": reason[:160], "allowance_after": [], "passed": got == want})
    c1_cases = [("no products (no k)", None, False), ("unavailable", {"available": False, "unavailable_reason": "no soundings"}, False),
                ("available, no flags", {"available": True, "flags": []}, True), ("available, registration_shift", {"available": True, "flags": ["registration_shift"]}, False),
                ("available, vertical_offset", {"available": True, "flags": ["vertical_offset"]}, False), ("available, insufficient_overlap", {"available": True, "flags": ["insufficient_overlap"]}, False)]
    for name, prod, want in c1_cases:
        got, reason = S.usable_rule(prod)
        results.append({"test": f"9 rule C1: {name}", "argv": "", "expected": f"usable={want}", "raised": f"usable={got}", "message": reason, "allowance_after": [], "passed": got == want})
    n_ok = sum(r["passed"] for r in results)
    out = {"generated": P.utc_now(), "n_tests": len(results), "n_passed": n_ok, "all_passed": n_ok == len(results), "allowance_after_suite": list(C.phase4_allowance()),
           "guard_selftest_after": {k: v for k, v in __import__("src.phase4.guard_selftest", fromlist=["run"]).run(write=False).items() if k in ("all_passed", "controls")},
           "safety_net": "C.install_phase4_allowance replaced by a raising function for the suite; restored afterwards", "tests": results, "code_commit": P.git_commit()}
    P.write_json(P.REPORT_DIR / "refusal_tests.json", out, mode=0o644)
    for r in results:
        print(("PASS" if r["passed"] else "FAIL"), r["test"], "->", r["raised"], r["message"][:120])
    print(f"refusal tests: {n_ok}/{len(results)} passed; allowance after suite {out['allowance_after_suite']}")
    return 0 if out["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
