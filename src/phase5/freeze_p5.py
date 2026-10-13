"""ACQ-R09 §4.2 — the Phase 5 freeze record (reports_post_grl_review/PHASE5/freeze_record_phase5.json).

Lists the sha256 of every Phase 5 script and helper (src/phase5/*.py), of every repo module the entry script loads
(this process's import set after importing it, plus every module a rehearsal run record lists as loaded; hashes of files
changed since that run are reported, and the final rehearsal re-verifies every hash at run time through lock 2), of the
site list, the MB-System version and container digest, the sandbox tarball sha256, and the commit.  `--candidate` writes
freeze_record_phase5_candidate.json under ACQ-R09/ instead (pre-commit rehearsal; never cited by v3).
Usage: python -m src.phase5.freeze_p5 --run-record <rehearsal record> [--candidate]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from src.acq_r01 import common as C
from src.phase5 import common_p5 as P
from src.phase5 import sealed_step1_p5  # noqa: F401  (imports the whole chain)


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--run-record", required=True); ap.add_argument("--candidate", action="store_true")
    a = ap.parse_args(argv)
    run = json.loads(Path(a.run_record).read_text())
    from_run = run.get("loaded_repo_files") or {}
    here = P.loaded_repo_files()
    p5 = {str(p.relative_to(P.REPO)): P.sha256_file(p) for p in sorted((P.REPO / "src" / "phase5").glob("*.py"))}
    files = dict(sorted({**here, **p5, **{k: P.sha256_file(P.REPO / k) for k in from_run}, P.SITE_LIST_REL: P.sha256_file(P.SITE_LIST)}.items()))
    stale = {k: (from_run[k][:12], files[k][:12]) for k in from_run if from_run[k] != files[k]}
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *files], cwd=P.REPO, capture_output=True, text=True).stdout.strip()
    tar = C.SCRATCH_DATA / "containers" / "mbsystem_sandbox.tar"
    tar_sha = tar.with_suffix(".tar.sha256").read_text().split()[0] if tar.with_suffix(".tar.sha256").exists() else None
    rec = {"directive": "ACQ-R09", "generated": P.utc_now(), "status": "candidate (not tagged)" if a.candidate else "frozen",
           "entry_script": P.ENTRY_REL, "site_list": P.SITE_LIST_REL, "files": files, "n_files": len(files), "commit": P.git_commit(),
           "uncommitted_changes_in_listed_files": dirty, "mbsystem": C.MBSYSTEM_VERSION,
           "container": {"image": "docker.io/mbari/mbsystem", "digest": C.CONTAINER_DIGEST, "sandbox_canonical": C.SANDBOX_CANONICAL,
                         "sandbox_tar": str(tar), "sandbox_tar_sha256": tar_sha},
           "guard": {"file": "src/acq_r01/common.py", "sha256": files.get("src/acq_r01/common.py"), "phase5_admission": "src/phase5/guard_p5.py"},
           "fixed_inputs": run.get("fixed_input_sha256"), "run_record": str(a.run_record), "run_record_commit": run.get("code_commit"),
           "files_changed_since_run": stale, "rulings": ["S1 development mosaic rule", "S2 overlap >= 50 % of the smaller grid; undated = tie",
                                                          "S3 current grid_lr; FK151121 isolated by harness"],
           "python": sys.version.split()[0]}
    out = (P.REPORT_DIR / "freeze_record_phase5_candidate.json") if a.candidate else P.FREEZE_RECORD
    if not a.candidate and out.exists():
        raise SystemExit(f"{out} exists; not overwritten")
    P.write_json(out, rec, mode=0o644 if a.candidate else 0o444)
    print(f"{out}: {len(files)} files; {P.ENTRY_REL} {files[P.ENTRY_REL]}; record sha256 {P.sha256_file(out)}; stale {stale}; dirty {dirty!r}")
    return 0 if (a.candidate or not dirty) else 1


if __name__ == "__main__":
    sys.exit(main())
