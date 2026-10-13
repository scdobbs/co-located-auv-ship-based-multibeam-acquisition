"""ACQ-R08b §6 — the candidate grids stay on scratch under the guarded root; their sha256 list, the report, the candidate
table, the footprint vectors and the evidence files go to OAK acq_archive/ACQ-R08b/ with a verified SHA256SUMS."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from src.acq_r08b import common as K
from src.acq_r01 import common as C

DEST = C.OAK / "acq_archive" / "ACQ-R08b"
PATTERNS = ["REPORT_ACQ-R08b_*.md", "SHA256SUMS_candidates", "download_manifest.json", "candidates_measured.json", "candidates_measured.csv", "candidate_table.csv",
            "must_hold_checks.json", "guard_selftest.json", "guard_log.jsonl", "network_log.jsonl", "run_jobs.json", "footprints/*.geojson", "logs/*"]


def main(argv=None):
    DEST.mkdir(parents=True, exist_ok=True)
    files = [f for pat in PATTERNS for f in sorted(K.OUT.glob(pat)) if f.is_file() and not f.name.endswith(".draft.md")]
    copied, skipped = [], []
    for f in files:
        rel = f.relative_to(K.OUT); dst = DEST / rel
        if dst.exists():
            skipped.append(str(rel)); continue
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(f, dst); dst.chmod(0o444); copied.append(str(rel))
    lines = [f"{C.sha256_file(f)}  {f.relative_to(DEST)}" for f in sorted(DEST.rglob('*')) if f.is_file() and f.name != "SHA256SUMS"]
    sums = DEST / "SHA256SUMS"
    if sums.exists():
        sums.chmod(0o644)
    sums.write_text("\n".join(lines) + "\n"); sums.chmod(0o444)
    v = subprocess.run(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=DEST, capture_output=True, text=True)
    rec = {"dest": str(DEST), "copied": copied, "skipped_existing": skipped, "n_files": len(lines), "sha256sum_check_rc": v.returncode, "stderr": v.stderr[-300:],
           "sha256sums_sha256": C.sha256_file(sums), "verified_at": K.now_iso()}
    K.write_json(K.OUT / "preserve_verify.json", rec); print(json.dumps(rec, indent=1))
    return v.returncode


if __name__ == "__main__":
    sys.exit(main())
