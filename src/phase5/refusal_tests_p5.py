"""ACQ-R09 §3.3.5, §3.3.6, §3.4 — refusal tests of sealed_step1_p5.py (locks of §2.2) and of the Phase 5 guard (§2.3).

Lock tests call sealed_step1_p5.main() in-process with dummy files.  Safety net: the Phase 5 allowance is replaced by a
function that raises, so a lock that failed to refuse stops there, before any sealed read; the positive control (every
lock satisfiable) must reach exactly that point.  Lock 4 tests point the phase5 supplement / record paths at a temporary
directory for the duration of the test.  Guard tests open mock files for real (development copies) and check the real
sealed names as strings only.  Usage: python -m src.phase5.refusal_tests_p5
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from src.acq_r01 import common as C
from src.phase5 import common_p5 as P
from src.phase5 import guard_p5 as GP
from src.phase5 import sealed_step1_p5 as S

PREREG = "b" * 64
SAFETY = "TEST SAFETY NET: the Phase 5 allowance was reached"


class SafetyStop(RuntimeError):
    pass


def _no_allowance(tokens, sealed_root, roots, reason):
    raise SafetyStop(SAFETY + f" ({len(tuple(tokens))} tokens, reason {reason!r})")


def make_freeze(path: Path, alter=None, drop=None) -> None:
    files = P.loaded_repo_files()
    files[P.SITE_LIST_REL] = P.sha256_file(P.SITE_LIST)
    if alter:
        files[alter] = "0" * 64
    for d in (drop or ()):
        files.pop(d, None)
    path.write_text(json.dumps({"files": files, "note": "dummy freeze record for the ACQ-R09 refusal tests"}, indent=1))


def run_case(name, argv, expect_prefix, expect_type=S.Refusal):
    try:
        S.main(argv); got = {"raised": None, "message": "RETURNED WITHOUT REFUSING"}
    except BaseException as e:   # noqa: BLE001
        got = {"raised": type(e).__name__, "message": str(e)[:400]}
    ok = got["raised"] == expect_type.__name__ and expect_prefix in got["message"] and not GP.allowance()["tokens"]
    return {"test": name, "argv": " ".join(argv), "expected": f"{expect_type.__name__}: {expect_prefix}", **got, "allowance_after": GP.allowance()["tokens"], "passed": bool(ok)}


def lock_tests(tmp: Path) -> list:
    ids = ",".join(s["hr_id"] for s in P.read_site_list(P.SITE_LIST))
    so = tmp / "signoff.md"; so.write_text(f"v3 signed; sha256 {PREREG}\n")
    so_bad = tmp / "signoff_bad.md"; so_bad.write_text("signed, but without the hash\n")
    fr_ok = tmp / "freeze_ok.json"; make_freeze(fr_ok)
    fr_alt = tmp / "freeze_alt.json"; make_freeze(fr_alt, alter="src/phase5/chain_p5.py")
    fr_noentry = tmp / "freeze_noentry.json"; make_freeze(fr_noentry, drop=[P.ENTRY_REL])
    fr_nosites = tmp / "freeze_nosites.json"; make_freeze(fr_nosites, drop=[P.SITE_LIST_REL])
    fr_noload = tmp / "freeze_noload.json"; make_freeze(fr_noload, drop=["src/phase5/hr_select.py"])
    base = ["--mode", "phase5", "--signoff", str(so), "--prereg-sha256", PREREG, "--freeze-record", str(fr_ok)]
    other_list = tmp / "other_sites.csv"; other_list.write_text(P.SITE_LIST.read_text())
    cases = [
        ("L1a no sign-off", ["--mode", "phase5"], "LOCK 1 sign-off: --signoff and --prereg-sha256 are required"),
        ("L1b malformed sha256", ["--mode", "phase5", "--signoff", str(so), "--prereg-sha256", "xyz"], "LOCK 1 sign-off: --prereg-sha256 is not a sha256"),
        ("L1c sign-off file missing", ["--mode", "phase5", "--signoff", str(tmp / "none.md"), "--prereg-sha256", PREREG], "does not exist"),
        ("L1d sign-off without the v3 sha256", ["--mode", "phase5", "--signoff", str(so_bad), "--prereg-sha256", PREREG], "does not hold the pre-registration v3 sha256"),
        ("L2a freeze record missing", base[:-1] + [str(tmp / "nofreeze.json")], "LOCK 2 freeze record"),
        ("L2b no entry for the entry script", base[:-1] + [str(fr_noentry)], f"has no entry for {P.ENTRY_REL}"),
        ("L2c no entry for the site list", base[:-1] + [str(fr_nosites)], f"has no entry for {P.SITE_LIST_REL}"),
        ("L2d a file differs", base[:-1] + [str(fr_alt)], "file(s) differ"),
        ("L2e a loaded module is not in the record", base[:-1] + [str(fr_noload)], "loaded repo modules not in"),
        ("L3a a site not in the site list", base + ["--sites", ids + ",MGDS:31811"], "SITE LIST:"),
        ("L3b a subset of the site list", base + ["--sites", ids.split(",")[0]], "LOCK 3 site list: the run must cover exactly"),
        ("L3c another site list", base + ["--site-list", str(other_list)], "LOCK 3 site list: phase5 mode reads"),
        ("L3d a run tag", base + ["--run-tag", "x"], "LOCK 3 site list: --run-tag is not accepted"),
    ]
    out = [run_case(n, a, e) for n, a, e in cases]
    # lock 4 and the positive controls with temporary supplement / record paths
    cfg = S.MODES["phase5"]; saved = (cfg["supplement"], cfg["record_dir"])
    try:
        rd = tmp / "records"; rd.mkdir(); cfg["record_dir"] = rd; cfg["supplement"] = tmp / "pairs_phase5_sealed.parquet"
        cfg["supplement"].write_bytes(b"dummy")
        out.append(run_case("L4a supplement exists", base, "LOCK 4 single run: ", S.Refusal))
        cfg["supplement"].unlink()
        (rd / "step1_run_phase5_20261101T000000Z.json").write_text(json.dumps({"status": "complete", "mode": "phase5"}))
        out.append(run_case("L4b a complete phase5 run record exists", base, "a complete phase5 run record exists"))
        (rd / "step1_run_phase5_20261101T000000Z.json").write_text(json.dumps({"status": "stopped", "mode": "phase5"}))
        out.append(run_case("L4c only a stopped run record: not refused (reaches the allowance)", base, SAFETY, SafetyStop))
        (rd / "step1_run_phase5_20261101T000000Z.json").unlink()
        out.append(run_case("P0 positive control: every lock satisfiable", base, SAFETY, SafetyStop))
    finally:
        cfg["supplement"], cfg["record_dir"] = saved
    out.append(run_case("R1 rehearsal: site not in the mock list", ["--mode", "rehearsal", "--run-tag", "t", "--sites", "MGDS:18210"], "SITE LIST:"))
    out.append(run_case("R2 rehearsal: no run tag", ["--mode", "rehearsal"], "rehearsal: --run-tag is required"))
    return out


def guard_tests() -> list:
    import rasterio
    out = []

    def case(name, fn, want):
        try:
            fn(); got = "admitted"
        except PermissionError as e:
            got = "refused" if ("GUARD" in str(e) or "allowance refused" in str(e)) else f"PermissionError: {str(e)[:80]}"
        except Exception as e:
            got = f"admitted (then {type(e).__name__})"
        out.append({"test": name, "expected": want, "got": got, "passed": got.startswith(want)})
    mock = P.read_site_list(P.MOCK_SITE_LIST)
    toks = [s["token"] for s in mock]
    f_mock = sorted((P.MOCK_ROOT / toks[1]).glob("*.gz"))[0]           # NA080 copy
    decoy = P.MOCK_ROOT / "MGDS_99999" / "decoy.grd"
    case("G1 mock path refused before admission (builtins.open)", lambda: open(f_mock, "rb").read(4), "refused")
    case("G1b mock path refused before admission (rasterio.open)", lambda: rasterio.open(str(f_mock)), "refused")
    case("G2 allowance with a wrong reason is refused", lambda: GP.install_phase5_allowance(toks, P.MOCK_ROOT, [], reason="because"), "refused")
    C._PHASE4_ALLOW = ("ZZZ_TEST",)
    try:
        case("G3 allowance refused while a Phase 4 allowance is installed", lambda: GP.install_phase5_allowance(toks, P.MOCK_ROOT, [], reason="ACQ-R09 rehearsal (mock root, development data): test"), "refused")
    finally:
        C._PHASE4_ALLOW = ()
    GP.install_phase5_allowance(toks, P.MOCK_ROOT, [], reason="ACQ-R09 rehearsal (mock root, development data): guard test")
    try:
        case("G4 mock id admitted after the allowance (builtins.open)", lambda: open(f_mock, "rb").read(4), "admitted")
        case("G5 non-admitted mock id (decoy MGDS_99999) still refused", lambda: open(decoy, "rb").read(4), "refused")
        case("G6 real sealed site refused under the mock allowance (string)", lambda: C._check(str(C.SEALED_CANDIDATES_V3 / "MGDS_18210" / "x.grd.gz")), "refused")
        case("G7 lockbox path refused under the allowance (string)", lambda: C._check(str(C.OAK / "harmonized" / C.LOCKBOX[0] / "lr.tif")), "refused")
    finally:
        GP.remove_phase5_allowance()
    case("G8 mock path refused again after removal", lambda: open(f_mock, "rb").read(4), "refused")
    real = [s["token"] for s in P.read_site_list(P.SITE_LIST)]
    sr = GP.selftest(real, toks, P.SCRATCH_ROOT / "refusal_test_out", P.SCRATCH_ROOT / "refusal_test_work", decoy_mock=decoy)
    for r in sr["real_name_admission"] + sr["mock_admission"]:
        out.append({"test": "G9 " + r["case"], "expected": r["expected"], "got": r["got"], "passed": r["passed"], "path": r["path"]})
    out.append({"test": "G10 reader refusals before any allowance (self-test)", "expected": "all blocked", "got": f"{sr['reader_checks']['n_blocked']}/{sr['reader_checks']['n']}",
                "passed": sr["reader_checks"]["all_blocked"]})
    out.append({"test": "G11 everything refused after removal (self-test)", "expected": "all blocked", "got": str(sr["after_removal"]), "passed": sr["after_removal"]["all_blocked"]})
    return out


def check_tests() -> list:
    """ACQ-R11b: the datum check in the key check and in eligibility (pure function calls, no data)."""
    from src.phase5 import chain_p5 as CH
    out = []
    hits = P.forbidden_keys({"datum_check": {"v95": 1.0, "V95_rel": 0.1}, "ok": True})
    out.append({"test": "B1 forbidden-key check catches v95 keys", "expected": "2 hits", "got": f"{len(hits)} hits", "passed": len(hits) == 2})
    q_ok = {"coreg_estimated": True, "offset_within_30m": True, "overlap_ge_1km2": True, "tiles_gt_0": True}
    c2a = {"hr_res_m_unrounded": 1.0, "lr_native_res_m": 20.0}; sw = {"max_recoverable_k": 8, "status": "ok"}
    e1 = CH.eligibility({"qa_pass": True, "qa_components": q_ok, "datum_check": {"vertical_consistent": False, "computed": True, "why": "above the calibrated bound"}}, c2a, sw, None)
    out.append({"test": "B2 datum check fails -> not eligible, reason 'vertical datum', coreg_pass false", "expected": "vertical datum", "got": e1["eligibility_reason"],
                "passed": (not e1["eligible"]) and (not e1["coreg_pass"]) and e1["eligibility_reason"].startswith("vertical datum") and "co-registration" not in e1["eligibility_reason"]})
    e2 = CH.eligibility({"qa_pass": False, "qa_components": dict(q_ok, offset_within_30m=False), "datum_check": {"vertical_consistent": True, "computed": True, "why": ""}}, c2a, sw, None)
    out.append({"test": "B3 qa fails, datum passes -> reason 'co-registration' only", "expected": "co-registration", "got": e2["eligibility_reason"],
                "passed": (not e2["eligible"]) and e2["eligibility_reason"].startswith("co-registration") and "vertical datum" not in e2["eligibility_reason"]})
    e3 = CH.eligibility({"qa_pass": True, "qa_components": q_ok, "datum_check": {"vertical_consistent": True, "computed": True, "why": ""}}, c2a, sw, None)
    out.append({"test": "B4 both pass -> eligible, coreg_pass true", "expected": "eligible", "got": e3["status"], "passed": e3["eligible"] and e3["coreg_pass"]})
    return out


def main(argv=None):
    real_install = S.GP.install_phase5_allowance
    S.GP.install_phase5_allowance = _no_allowance
    try:
        with tempfile.TemporaryDirectory(dir=str(P.SCRATCH_ROOT)) as td:
            locks = lock_tests(Path(td))
    finally:
        S.GP.install_phase5_allowance = real_install
    guards = guard_tests() + check_tests()
    allp = all(r["passed"] for r in locks + guards)
    rec = {"generated": P.utc_now(), "code_commit": P.git_commit(), "host": P.hostname(), "n_lock_tests": len(locks), "n_guard_tests": len(guards),
           "n_passed": sum(r["passed"] for r in locks + guards), "all_passed": allp, "lock_tests": locks, "guard_tests": guards}
    P.write_json(P.REPORT_DIR / "refusal_tests_p5.json", rec, mode=0o644)
    for r in locks + guards:
        print(("PASS " if r["passed"] else "FAIL ") + r["test"] + ("" if r["passed"] else f"  -> {r.get('raised')} {r.get('message', r.get('got'))}"))
    print(f"refusal tests: {rec['n_passed']}/{len(locks) + len(guards)} passed")
    return 0 if allp else 1


if __name__ == "__main__":
    sys.exit(main())
