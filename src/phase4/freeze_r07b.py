"""ACQ-R07b Part D — the completion freeze record: the sha256 of the completion script, the harness and the refusal
tests, and of every repo file the B1 completion process loaded that is not in the ACQ-R06b freeze record.
Usage: python -m src.phase4.freeze_r07b [--run-record reports_post_grl_review/ACQ-R07b/rehearsal/step1_run_rehearsal_r07b_stop_completion.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.phase4 import common as P
from src.phase4 import sealed_step1_complete as SC

ALWAYS = ("src/phase4/sealed_step1_complete.py", "src/phase4/harness_r07b.py", "src/phase4/refusal_tests_r07b.py")


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--run-record", default=str(SC.REPORT_DIR_R07B / "rehearsal" / "step1_run_rehearsal_r07b_stop_completion.json"))
    a = ap.parse_args(argv)
    run = json.loads(Path(a.run_record).read_text())
    frozen = json.loads(P.FREEZE_RECORD.read_text())["files"]
    loaded = run.get("loaded_repo_files") or {}
    names = sorted(set(ALWAYS) | {k for k in loaded if k not in frozen})
    files = {k: P.sha256_file(P.REPO / k) for k in names}
    stale = {k: (loaded[k][:12], files[k][:12]) for k in names if k in loaded and loaded[k] != files[k]}
    rec = {"directive": "ACQ-R07b", "generated": P.utc_now(), "status": "frozen", "entry_script": "src/phase4/sealed_step1_complete.py", "files": files,
           "frozen_record": {"path": str(P.FREEZE_RECORD), "sha256": P.sha256_file(P.FREEZE_RECORD)}, "b1_completion_run_record": a.run_record,
           "loaded_not_in_frozen_record": sorted(k for k in loaded if k not in frozen), "files_changed_since_b1": stale, "commit": P.git_commit(), "python": sys.version.split()[0], "n_files": len(files)}
    out = SC.COMPLETION_FREEZE_RECORD
    P.write_json(out, rec, mode=0o644)
    print(f"{out}: {len(files)} files; completion script {files['src/phase4/sealed_step1_complete.py']}; record sha256 {P.sha256_file(out)}; changed since B1: {stale}")
    return 0 if not stale else 1


if __name__ == "__main__":
    sys.exit(main())
