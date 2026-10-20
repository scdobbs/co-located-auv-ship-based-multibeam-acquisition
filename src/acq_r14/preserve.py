"""ACQ-R14 step 6: preserve to OAK acq_archive/ACQ-R14/ (directive section 6).
  --package : copy the package (large; run inside the build job) to OAK_DEST/package/, verify its SHA256SUMS there.
  --repo    : copy the repo artifacts (report, inventory, audit, fixes, checks, build results, code, job script) and write the
              archive-level SHA256SUMS over everything under OAK_DEST (package/ included), verify, preserve_verify.json.

    python -B -m src.acq_r14.preserve --package | --repo
"""
from __future__ import annotations
import argparse, os, shutil, stat
from pathlib import Path
from . import common as C

REPO_ARTIFACTS = ["reports_post_grl_review/ACQ-R14", "src/acq_r14", "sbatch/acq_r14", "CHANGE_LEDGER.md"]
SKIP = {"license_cache", "job_", "__pycache__", ".tmp"}


def _copy(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        os.chmod(dst, stat.S_IWUSR | stat.S_IRUSR)
    shutil.copyfile(src, dst)
    h_src, h_dst = C.sha256(src), C.sha256(dst)
    if h_src != h_dst:
        raise RuntimeError(f"copy mismatch {src} -> {dst}")
    os.chmod(dst, 0o444)
    return h_dst


def package():
    n, tot = 0, 0
    for p in sorted(C.PKG.rglob("*")):
        if p.is_file():
            rel = p.relative_to(C.PKG)
            dst = C.OAK_DEST / "package" / rel
            if dst.exists() and dst.stat().st_size == p.stat().st_size and C.sha256(dst) == C.sha256(p):
                continue
            _copy(p, dst)
            n += 1
            tot += p.stat().st_size
    # verify SHA256SUMS at the destination
    bad = []
    lines = (C.OAK_DEST / "package" / "SHA256SUMS").read_text().splitlines()
    for line in lines:
        h, rel = line.split("  ", 1)
        if C.sha256(C.OAK_DEST / "package" / rel) != h:
            bad.append(rel)
    C.jdump({"generated": C.utcnow(), "dest": str(C.OAK_DEST / "package"), "n_copied": n, "bytes_copied": tot, "n_in_sha256sums": len(lines), "bad": bad, "verified": not bad},
            C.RPT / "preserve_package_verify.json")
    C.log(f"preserve --package: {n} files copied ({tot / 1e9:.2f} GB); SHA256SUMS at OAK verified={not bad} ({len(lines)} lines)")
    if bad:
        raise SystemExit(1)


def repo():
    copied = {}
    for a in REPO_ARTIFACTS:
        src = C.REPO / a
        files = [src] if src.is_file() else [p for p in src.rglob("*") if p.is_file()]
        for p in files:
            rel = p.relative_to(C.REPO)
            if any(s in str(rel) for s in SKIP):
                continue
            copied[str(rel)] = _copy(p, C.OAK_DEST / rel)
    # package files: reuse the package's own SHA256SUMS (verified at OAK by `--package` inside the job) rather than re-hashing
    # 1.7 GB on a login node; the package SHA256SUMS file itself and every repo artifact are hashed here.
    pkg_sums = C.OAK_DEST / "package" / "SHA256SUMS"
    lines = [f"{h}  package/{rel}" for h, rel in (l.split("  ", 1) for l in pkg_sums.read_text().splitlines())] if pkg_sums.exists() else []
    if pkg_sums.exists():
        lines.append(f"{C.sha256(pkg_sums)}  package/SHA256SUMS")
    for p in sorted(C.OAK_DEST.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS" and "package/" not in str(p.relative_to(C.OAK_DEST)) + "/":
            lines.append(f"{C.sha256(p)}  {p.relative_to(C.OAK_DEST)}")
    sums = C.OAK_DEST / "SHA256SUMS"
    if sums.exists():
        os.chmod(sums, 0o644)
    sums.write_text("\n".join(lines) + "\n")
    bad = [rel for h, rel in (l.split("  ", 1) for l in lines) if not rel.startswith("package/") and C.sha256(C.OAK_DEST / rel) != h]
    missing = [rel for h, rel in (l.split("  ", 1) for l in lines) if not (C.OAK_DEST / rel).exists()]
    bad += missing
    os.chmod(sums, 0o444)
    ver = {"generated": C.utcnow(), "dest": str(C.OAK_DEST), "n_files": len(lines), "sha256sums_sha256": C.sha256(sums), "verified": not bad, "bad": bad,
           "package_sha256sums_sha256": C.sha256(C.OAK_DEST / "package" / "SHA256SUMS") if (C.OAK_DEST / "package" / "SHA256SUMS").exists() else None}
    C.jdump(ver, C.RPT / "preserve_verify.json")
    _copy(C.RPT / "preserve_verify.json", C.OAK_DEST / "reports_post_grl_review/ACQ-R14/preserve_verify.json")
    C.log(f"preserve --repo: {len(copied)} repo files; archive SHA256SUMS {len(lines)} lines, verified={not bad}, sha256 {ver['sha256sums_sha256']}")
    if bad:
        raise SystemExit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", action="store_true")
    ap.add_argument("--repo", action="store_true")
    a = ap.parse_args()
    C.OAK_DEST.mkdir(parents=True, exist_ok=True)
    if a.package:
        package()
    if a.repo:
        repo()


if __name__ == "__main__":
    main()
