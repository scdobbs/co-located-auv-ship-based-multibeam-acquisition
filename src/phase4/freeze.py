"""ACQ-R06 Part D — the freeze record.

Writes the sha256 of sealed_step1.py and of every repo file it imports (the loaded modules of a rehearsal run, from
its run record, cross-checked against this process's own import set), the commit, the MB-System version, the
container identifier (image digest and the sha256 of the node-local sandbox tarball) and the guard's sha256.
`--candidate` writes freeze_record_candidate.json (no tag; Part D's condition not met); without it, freeze_record.json.
Usage: python -m src.phase4.freeze --run-record reports_post_grl_review/ACQ-R06/rehearsal/step1_run_rehearsal_full.json [--candidate]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.acq_r01 import common as C
from src.phase4 import common as P
from src.phase4 import sealed_step1  # noqa: F401  (imports the whole chain so that loaded_repo_files() is complete)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-record", required=True); ap.add_argument("--candidate", action="store_true")
    a = ap.parse_args(argv)
    run = json.loads(Path(a.run_record).read_text())
    from_run = run.get("loaded_repo_files") or {}
    here = P.loaded_repo_files()
    files = dict(sorted({**here, **{k: P.sha256_file(P.REPO / k) for k in from_run}}.items()))
    stale = {k: (from_run[k][:12], files[k][:12]) for k in from_run if from_run[k] != files[k]}
    tar = C.SCRATCH_DATA / "containers" / "mbsystem_sandbox.tar"
    tar_sha = (tar.with_suffix(".tar.sha256").read_text().split()[0] if tar.with_suffix(".tar.sha256").exists() else None)
    rec = {"directive": "ACQ-R06", "generated": P.utc_now(), "status": "candidate (not tagged)" if a.candidate else "frozen",
           "entry_script": "src/phase4/sealed_step1.py", "files": files, "commit": P.git_commit(),
           "mbsystem": C.MBSYSTEM_VERSION, "container": {"image": "docker.io/mbari/mbsystem", "digest": C.CONTAINER_DIGEST,
                                                          "sandbox_canonical": C.SANDBOX_CANONICAL, "sandbox_tar": str(tar), "sandbox_tar_sha256": tar_sha},
           "guard": {"file": "src/acq_r01/common.py", "sha256": files.get("src/acq_r01/common.py")},
           "fixed_inputs": run.get("fixed_input_sha256"), "run_record": str(a.run_record), "run_record_commit": run.get("code_commit"),
           "files_changed_since_run": stale, "n_files": len(files),
           "python": sys.version.split()[0]}
    out = P.REPORT_DIR / ("freeze_record_candidate.json" if a.candidate else "freeze_record.json")
    P.write_json(out, rec, mode=0o644)
    print(f"{out}: {len(files)} files; sealed_step1.py {files['src/phase4/sealed_step1.py']}; record sha256 {P.sha256_file(out)}; changed since run: {stale}")
    return 0 if not stale else 1


if __name__ == "__main__":
    sys.exit(main())
