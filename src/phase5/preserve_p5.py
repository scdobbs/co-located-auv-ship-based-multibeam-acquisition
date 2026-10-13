"""ACQ-R09 §4.4 — copy the Phase 5 code, the contract, the freeze record and the rehearsal records to OAK
acq_archive/ACQ-R09/ and verify a SHA256SUMS over the copies.  Nothing bulk is copied (rehearsal rasters stay on scratch).
Usage: python -m src.phase5.preserve_p5
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from src.acq_r01 import common as C
from src.phase5 import common_p5 as P

DEST = C.OAK / "acq_archive" / "ACQ-R09"


def sources() -> list:
    s = sorted((P.REPO / "src" / "phase5").glob("*.py")) + [P.SITE_LIST, P.FREEZE_RECORD, P.REPORT_DIR / "RECORD_CONTRACT_phase5.md",
                                                            P.REPORT_DIR / "PHASE5_design_spec_2026-10-13.md", P.REPORT_DIR / "refusal_tests_p5.json"]
    s += sorted(P.REHEARSAL_DIR.glob("*.json")) + sorted(P.REHEARSAL_DIR.glob("*.csv")) + sorted(P.REHEARSAL_DIR.glob("*.parquet")) + sorted(P.REHEARSAL_DIR.glob("*.md"))
    s += sorted((P.REPO / "sbatch" / "acq_r09").glob("*.sbatch"))
    return [p for p in s if p.exists()]


def main(argv=None):
    DEST.mkdir(parents=True, exist_ok=True)
    lines = []
    for p in sources():
        rel = p.relative_to(P.REPO)
        d = DEST / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.exists():
            d.chmod(0o644)
        shutil.copyfile(p, d); d.chmod(0o444)
        a, b = P.sha256_file(p), P.sha256_file(d)
        if a != b:
            raise SystemExit(f"copy mismatch {p}")
        lines.append(f"{b}  {rel}")
    sums = DEST / "SHA256SUMS"
    if sums.exists():
        sums.chmod(0o644)
    sums.write_text("\n".join(lines) + "\n"); sums.chmod(0o444)
    bad = [l for l in lines if P.sha256_file(DEST / l.split("  ", 1)[1]) != l.split("  ", 1)[0]]
    rec = {"generated": P.utc_now(), "dest": str(DEST), "n_files": len(lines), "sha256sums_sha256": P.sha256_file(sums), "verified": not bad, "bad": bad}
    P.write_json(P.REPORT_DIR / "preserve_verify.json", rec, mode=0o644)
    print(rec)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
