"""ACQ-R06 §F — copy the rehearsal outputs to OAK acq_r06_rehearsal/ with SHA256SUMS verified at the destination.

Copies <scratch root>/<run tag>/ (per-pair step1_record.json, sweep_record.json, ship_products_v2_1/) and the ACQ-R06
report-directory records (rehearsal/, guard_selftest.json, refusal_tests.json, sealed_records.json, c1_check.*,
freeze_record*.json).  Nothing under OAK harmonized/ is touched.  Usage: python -m src.phase4.preserve --run-tag full
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from src.acq_r01 import common as C
from src.phase4 import common as P

DEST = C.OAK / "acq_r06_rehearsal"


def copy_tree(src: Path, dst: Path, sums: dict, prefix: str):
    for p in sorted(src.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(src); q = dst / rel
        q.parent.mkdir(parents=True, exist_ok=True)
        if q.exists():
            q.chmod(0o644)
        shutil.copyfile(p, q); q.chmod(0o444)
        sums[f"{prefix}/{rel}"] = P.sha256_file(p)


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--run-tag", default="full")
    a = ap.parse_args(argv)
    run = json.loads((P.REHEARSAL_DIR / f"step1_run_rehearsal_{a.run_tag}.json").read_text())
    src_root = Path(run["out_root"])
    if not str(src_root).startswith(str(P.SCRATCH_ROOT)):
        raise SystemExit(f"refusing: {src_root} is not under the rehearsal scratch root")
    for p in src_root.rglob("*"):
        C._check_sealed(p)                                      # belt and braces: nothing sealed can be in the rehearsal tree
    DEST.mkdir(exist_ok=True)
    sums = {}
    copy_tree(src_root, DEST / "rehearsal_outputs" / a.run_tag, sums, f"rehearsal_outputs/{a.run_tag}")
    rec_dir = DEST / "records"
    for p in sorted(P.REPORT_DIR.glob("*")):
        if p.is_file() and (p.suffix in (".json", ".csv", ".txt", ".md")):
            q = rec_dir / p.name; q.parent.mkdir(parents=True, exist_ok=True)
            if q.exists():
                q.chmod(0o644)
            shutil.copyfile(p, q); q.chmod(0o444); sums[f"records/{p.name}"] = P.sha256_file(p)
    copy_tree(P.REHEARSAL_DIR, rec_dir / "rehearsal", sums, "records/rehearsal")
    for sub in ("tables",):
        if (P.REPORT_DIR / sub).exists():
            copy_tree(P.REPORT_DIR / sub, rec_dir / sub, sums, f"records/{sub}")
    sp = DEST / "SHA256SUMS"
    if sp.exists():
        sp.chmod(0o644)
    sp.write_text("".join(f"{v}  {k}\n" for k, v in sorted(sums.items()))); sp.chmod(0o444)
    bad = []
    for rel, want in sums.items():
        got = P.sha256_file(DEST / rel)
        if got != want:
            bad.append(rel)
    out = {"generated": P.utc_now(), "destination": str(DEST), "n_files": len(sums), "n_bad": len(bad), "bad": bad, "sha256sums": str(sp),
           "sha256sums_sha256": P.sha256_file(sp), "bytes": int(sum((DEST / r).stat().st_size for r in sums)), "code_commit": P.git_commit()}
    P.write_json(P.REPORT_DIR / "preserve_verify.json", out, mode=0o644)
    print(json.dumps(out, indent=1))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
