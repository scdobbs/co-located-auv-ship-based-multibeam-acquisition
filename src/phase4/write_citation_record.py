"""ACQ-R07c — write one citation record that the CNN Phase 4 run-record lock can read.

The CNN lock (phase4_common.load_acq_run_record, B6 sha256 ef70653f…) requires the freeze-record citation at
locks.lock2_freeze_record.freeze_record_sha256.  The ACQ-R07b completion record carries the same value under
locks.lock2_frozen_code.freeze_record_sha256 (and at top level), so the lock refuses it.  This script writes a NEW
record beside it — a verbatim copy of every top-level field and every locks entry of the completion record, plus the
citation under the expected key and four labelling keys — after re-verifying every hash of ACQ-R07c §2.  No value is
recomputed; no sealed file is opened; no existing file is changed.  Refuses if the output exists.
Usage: python -m src.phase4.write_citation_record
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

from src.acq_r01 import common as C          # installs the acquisition guard
from src.phase4 import common as P
from src.phase4 import guard_selftest as G

REPO = P.REPO
R06B = P.REPORT_DIR                                                       # reports_post_grl_review/ACQ-R06b
R07C = REPO / "reports_post_grl_review" / "ACQ-R07c"
OUT = R06B / "step1_run_phase4_citation.json"                             # matches the lock's glob step1_run_phase4_*.json; sorts first; is not lock 7's file
CITATION_KEY = "lock2_freeze_record"
SHA_FREEZE = "331c94f01d7d1a2e52fb969c5fb1872aae2cd2ed249a3757b99e9d217b3ac0cb"
PINNED = {
    R06B / "freeze_record.json": SHA_FREEZE,
    R06B / "step1_run_phase4_completion.json": "fb1e07b24681e8b7b15dec3b232ea78266c6c7cd82ae64518e82b76ae99dcc07",
    P.SUPPLEMENT_PHASE4: "6968e04554ddeef3c335587d602cb5fab2185db32b46cbd152475a919eb59206",      # hash only; never parsed
    R06B / "step1_run_phase4_run.json": "7cc5b46d437a72976027f8e7ca9b0f31a8b9eeb5161928c67fce41f87127ce2b",
    REPO / "src/phase4/sealed_step1_complete.py": "860e5d598ae222db9c82f27da688dc093455adf10bef9b2502d56cb18a30e706",   # REPORT_ACQ-R07b, tag phase4-acq-complete-v2
    REPO / "reports_post_grl_review/ACQ-R07b/completion_freeze_record.json": "b581e538115dd4859cd6175a131fb4214c800d3b9a5ba6c0321d234530a58182",
}
CNN = Path("/home/users/scdobbs/GAN_Bathymetry_Project")
CNN_DR = CNN / "grl_reviews-and-prompt-reports" / "directives_and_reports"
CNN_SCRIPTS = ("phase4_common.py", "phase4_build.py", "phase4_figures.py", "phase4_predict.py", "phase4_score.py")
PREREG = CNN_DR / "R11" / "PREREG_phase4_v2.md"
ADDED_KEYS = ("record_type", "produced_by", "cites", "purpose")


class Refusal(RuntimeError):
    pass


def listing(d: Path, exclude=()) -> dict:
    return {p.name: P.sha256_file(p) for p in sorted(d.iterdir()) if p.is_file() and p.name not in exclude}


def verify_pinned() -> dict:
    out = {}
    for p, want in PINNED.items():
        got = P.sha256_file(p) if p.exists() else "MISSING"
        out[str(p.relative_to(REPO))] = {"expected": want, "got": got, "equal": got == want}
        if got != want:
            raise Refusal(f"§2 precondition: {p} sha256 {got} != {want}")
    return out


def verify_cnn_scripts() -> dict:
    text = PREREG.read_text()
    b6 = dict(re.findall(r"\| `(phase4_\w+\.py)` \| `([0-9a-f]{64})` \|", text))
    out = {}
    for s in CNN_SCRIPTS:
        p = CNN_DR / "phase4" / "scripts" / s
        got = P.sha256_file(p)
        st = subprocess.run(["git", "status", "--short", "--", str(p.relative_to(CNN))], cwd=str(CNN), capture_output=True, text=True).stdout.strip()
        out[s] = {"b6": b6.get(s), "got": got, "equal": got == b6.get(s), "git_status": st, "clean": st == ""}
        if got != b6.get(s) or st != "":
            raise Refusal(f"§2 precondition: CNN {s} sha256 {got} vs B6 {b6.get(s)}; git status {st!r}")
    return out


def main(argv=None):
    checks = {"generated": P.utc_now(), "host": P.hostname(), "git_commit": P.git_commit(), "script_sha256": P.sha256_file(Path(__file__))}
    checks["fixed_inputs"] = P.check_fixed_inputs()
    g = G.run(write=False)
    checks["guard_selftest"] = {"all_passed": g["all_passed"], "n": g["reader_checks"]["n"], "n_blocked": g["reader_checks"]["n_blocked"], "allowance": list(C.phase4_allowance())}
    if not g["all_passed"] or C.phase4_allowance():
        raise Refusal("guard self-test failed or an allowance is installed")
    checks["pinned"] = verify_pinned()
    checks["cnn_scripts"] = verify_cnn_scripts()
    if OUT.exists():
        raise Refusal(f"{OUT} already exists (sha256 {P.sha256_file(OUT)}); refusing to overwrite")
    before = listing(R06B); checks["r06b_before"] = before
    comp_path = R06B / "step1_run_phase4_completion.json"; stop_path = R06B / "step1_run_phase4_run.json"
    comp = json.loads(comp_path.read_text())
    rec = copy.deepcopy(comp)                                            # every top-level field and every locks entry, verbatim
    if CITATION_KEY in rec["locks"]:
        raise Refusal(f"completion record already holds locks.{CITATION_KEY}")
    rec["locks"][CITATION_KEY] = {"freeze_record_sha256": SHA_FREEZE}
    rec["record_type"] = "citation"
    rec["produced_by"] = {"script": "src/phase4/write_citation_record.py", "git_commit": checks["git_commit"], "script_sha256": checks["script_sha256"], "directive": "ACQ-R07c"}
    rec["cites"] = {"completion_record": {"path": str(comp_path), "sha256": P.sha256_file(comp_path)}, "stopped_run_record": {"path": str(stop_path), "sha256": P.sha256_file(stop_path)}}
    rec["purpose"] = "label correction for the CNN run-record lock (REPORT_R12 H1); no value recomputed; not a run record"
    OUT.write_text(json.dumps(rec, indent=1, default=str)); OUT.chmod(0o444)
    # must hold (§3.4)
    new = json.loads(OUT.read_text()); comp2 = json.loads(comp_path.read_text())
    top_equal = {k: new.get(k) == v for k, v in comp2.items() if k != "locks"}
    locks_equal = {k: new["locks"].get(k) == v for k, v in comp2["locks"].items()}
    extra_top = sorted(set(new) - set(comp2)); extra_locks = sorted(set(new["locks"]) - set(comp2["locks"]))
    after = listing(R06B, exclude=(OUT.name,))
    checks["must_hold"] = {"top_level_fields_equal": all(top_equal.values()), "n_top_level_compared": len(top_equal), "locks_entries_equal": all(locks_equal.values()), "n_locks_compared": len(locks_equal),
                           "added_top_level_keys": extra_top, "added_locks_keys": extra_locks, "only_expected_keys_added": extra_top == sorted(ADDED_KEYS) and extra_locks == [CITATION_KEY],
                           "citation_value": new["locks"][CITATION_KEY]["freeze_record_sha256"], "r06b_unchanged": after == before, "r06b_after": after}
    checks["output"] = {"path": str(OUT), "sha256": P.sha256_file(OUT), "mode": oct(OUT.stat().st_mode & 0o777)}
    ok = all(checks["must_hold"][k] for k in ("top_level_fields_equal", "locks_entries_equal", "only_expected_keys_added", "r06b_unchanged"))
    R07C.mkdir(parents=True, exist_ok=True)
    P.write_json(R07C / "citation_record_checks.json", checks, mode=0o644)
    print(f"{OUT} sha256 {checks['output']['sha256']}; must hold {ok}: {json.dumps({k: v for k, v in checks['must_hold'].items() if k != 'r06b_after'})}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
