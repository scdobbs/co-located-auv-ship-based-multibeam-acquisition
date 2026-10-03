"""ACQ-R04 §5 — persist the corpus to OAK .../auv_ship_colocated_bathy/pretrain_v1/ with a verified SHA256SUMS.

Copies (additions only; nothing outside pretrain_v1/ is touched):
  <cruise>/<block>/            every kept block directory of the corpus manifest (grid.tif, block.json, lr.tif symlink,
                               ship_products_v2_1/)
  fetch_manifests/<cruise>/    fetch_manifest.json + SHA256SUMS per fetched cruise (the raw swath stays on scratch and
                               can be re-fetched from these)
  run_records/<cruise>/        cruise_record.json, block_ledger.csv, fetch.json, fetch_log.csv
  meta/                        pretrain_manifest_v*.parquet (+ .json), exclusion_v1.json, exclusion_geometries_v1.geojson,
                               pool_v1.csv, pool_ids_v1.csv, selection_v1.csv/.json/_filelist.csv.gz, failure_ledger_v*.csv
SHA256SUMS (pretrain_v1/SHA256SUMS): sha256 of every regular file computed at the SOURCE, then every destination file
is re-read and hashed on OAK; persist_verify.json records matches / mismatches / missing.  Files are made 0444.
Usage (Slurm): python -m src.acq_r04.persist --manifest pretrain_manifest_v1.parquet
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r04.blocks import cdir_name


def copy_tree(src: Path, dst: Path, pairs: list):
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src); q = dst / rel
        if p.is_symlink():
            q.parent.mkdir(parents=True, exist_ok=True)
            if q.is_symlink() or q.exists():
                q.unlink()
            q.symlink_to(os.readlink(p)); continue
        if p.is_dir():
            q.mkdir(parents=True, exist_ok=True); continue
        pairs.append((p, q))


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--manifest", default="pretrain_manifest_v1.parquet")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    man = pd.read_parquet(R.REPORT_DIR / a.manifest)
    C.assert_no_lockbox_cruise(man.cruise.unique().tolist())
    sel = pd.read_csv(R.REPORT_DIR / "selection_v1.csv")
    out = R.OAK_OUT; out.mkdir(parents=True, exist_ok=True)
    pairs = []
    for c, b in zip(man.cruise, man.block):
        copy_tree(R.STAGE / cdir_name(c) / b, out / cdir_name(c) / b, pairs)
    for c in sel.cruise:
        cd = cdir_name(c)
        for n in ("fetch_manifest.json", "SHA256SUMS"):
            p = R.PRETRAIN_RAW / cd / n
            if p.exists():
                pairs.append((p, out / "fetch_manifests" / cd / n))
        for n in ("cruise_record.json", "block_ledger.csv", "fetch.json", "fetch_log.csv", "cruise_failure.json"):
            p = R.WORK_LOGS / cd / n
            if p.exists():
                pairs.append((p, out / "run_records" / cd / n))
    for p in sorted(R.REPORT_DIR.glob("pretrain_manifest_v*")) + sorted(R.REPORT_DIR.glob("failure_ledger_v*.csv")) + \
            [R.CACHE / "exclusion_geometries_v1.geojson"] + [R.REPORT_DIR / n for n in ("exclusion_v1.json", "pool_v1.csv", "pool_ids_v1.csv",
                                        "selection_v1.csv", "selection_v1.json", "selection_v1_filelist.csv.gz")]:
        pairs.append((p, out / "meta" / p.name))

    def put(pq):
        p, q = pq
        h = R.sha256_file(p)
        q.parent.mkdir(parents=True, exist_ok=True)
        if q.exists():
            if R.sha256_file(q) == h:
                return str(q.relative_to(out)), h, "present"
            q.chmod(0o644)
        shutil.copyfile(p, q); q.chmod(0o444)
        return str(q.relative_to(out)), h, "copied"
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(put, pairs))
    sums = out / "SHA256SUMS"
    if sums.exists():
        sums.chmod(0o644)
    sums.write_text("".join(f"{h}  {rel}\n" for rel, h, _ in sorted(res)))
    sums.chmod(0o444)
    # verify at destination (fresh read of every OAK file)
    def ver(line):
        h, rel = line.split("  ", 1)
        q = out / rel
        if not q.exists():
            return rel, "missing"
        return rel, "ok" if R.sha256_file(q) == h else "MISMATCH"
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        vr = list(ex.map(ver, sums.read_text().splitlines()))
    bad = [r for r in vr if r[1] != "ok"]
    nbytes = sum((out / rel).stat().st_size for rel, _, _ in res)
    links = [str(p.relative_to(out)) for p in out.rglob("lr.tif") if p.is_symlink()]
    rep = {"generated": R.utc_now(), "destination": str(out), "files": len(res), "bytes": int(nbytes), "gb": round(nbytes / 1e9, 3),
           "copied": sum(r[2] == "copied" for r in res), "already_present": sum(r[2] == "present" for r in res),
           "verified_ok": sum(r[1] == "ok" for r in vr), "not_ok": bad, "symlinks_lr_tif": len(links),
           "sha256sums_sha256": R.sha256_file(sums), "manifest": a.manifest, "code_commit": C.git_commit()}
    R.write_json(R.REPORT_DIR / "persist_verify.json", rep)
    print(json.dumps({k: v for k, v in rep.items() if k != "not_ok"}, indent=1), len(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
