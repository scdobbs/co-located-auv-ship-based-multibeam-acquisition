"""ACQ-R08 §6 — copy the report, candidate tables, funnel records, Pool C table, guard/network evidence and the small
metadata-cache index to OAK acq_archive/ACQ-R08/ with a verified SHA256SUMS. Shell-level copies, 0444 targets, no overwrite."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from src.acq_r08 import common as K
from src.acq_r01 import common as C

DEST = C.OAK / "acq_archive" / "ACQ-R08"
PATTERNS = ["REPORT_ACQ-R08_*.md", "candidates_pool_*.csv", "candidates_pool_*.md", "pool_c_table.md", "must_hold_checks.json", "guard_selftest.json",
            "guard_state_pool_*.json", "network_log.jsonl", "exclusion_set_notes.json", "exclusion_footprints.gpkg", "run_jobs.json",
            "pool_a/hr_records.csv", "pool_a/candidates.csv", "pool_a/funnel.json", "pool_a/hr_footprints.gpkg", "pool_a/datacite_hits.csv",
            "pool_a/sciencebase_hits.csv", "pool_a/pangaea_auv_datasets.csv", "pool_a/pangaea_ship_datasets.csv",
            "pool_b/nos_records.csv", "pool_b/candidates.csv", "pool_b/funnel.json", "pool_b/nos_surveys.csv",
            "pool_c/pool_c_table.csv", "pool_c/summary.json", "pool_c/rescreen_ids.json"]


def main(argv=None):
    DEST.mkdir(parents=True, exist_ok=True)
    files = []
    for pat in PATTERNS:
        files += sorted(K.OUT.glob(pat))
    files = [f for f in files if f.is_file() and not f.name.endswith(".draft.md")]
    copied, skipped = [], []
    for f in files:
        rel = f.relative_to(K.OUT); dst = DEST / rel
        if dst.exists():
            skipped.append(str(rel)); continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dst); dst.chmod(0o444); copied.append(str(rel))
    lines = []
    for f in sorted(DEST.rglob("*")):
        if f.is_file() and f.name != "SHA256SUMS":
            lines.append(f"{C.sha256_file(f)}  {f.relative_to(DEST)}")
    sums = DEST / "SHA256SUMS"
    if sums.exists():
        sums.chmod(0o644)
    sums.write_text("\n".join(lines) + "\n"); sums.chmod(0o444)
    v = subprocess.run(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=DEST, capture_output=True, text=True)
    rec = {"dest": str(DEST), "copied": copied, "skipped_existing": skipped, "n_files": len(lines), "sha256sum_check_rc": v.returncode,
           "sha256sum_check_stderr": v.stderr[-500:], "sha256sums_sha256": C.sha256_file(sums), "verified_at": K.now_iso()}
    K.write_json(K.OUT / "preserve_verify.json", rec)
    print(json.dumps(rec, indent=1))
    return v.returncode


if __name__ == "__main__":
    sys.exit(main())
