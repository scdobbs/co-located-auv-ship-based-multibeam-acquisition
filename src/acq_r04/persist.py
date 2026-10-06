"""ACQ-R04 §5 — persist the corpus to OAK .../auv_ship_colocated_bathy/pretrain_v1/ with a verified SHA256SUMS.

Layout (Steve's decision 2026-10-06, option B: Sherlock guidance "prefer fewer, larger files" — the block-directory
layout would have been ~608,000 small files):
  blocks/<cruise>.tar          one UNCOMPRESSED tar per cruise holding <cruise>/<block>/{grid.tif, block.json, lr.tif ->
                               grid.tif, ship_products_v2_1/*} for every block of the corpus manifest (sorted members).
                               Readable in place: GDAL/rasterio "/vsitar/<oak>/blocks/<cruise>.tar/<cruise>/<block>/grid.tif".
  meta/                        pretrain_manifest_v*.parquet (+ .json, with oak_tar / tar_member_dir / grid_vsitar columns),
                               failure_ledger_v*.csv, exclusion_v1.json, exclusion_geometries_v1.geojson, pool_v1.csv,
                               pool_ids_v1.csv, selection_v1*.csv/.json, selection_v1_1*, block_members_sha256.csv.gz
                               (sha256 of every tar member, computed from the staged files while archiving)
  fetch_manifests.tar          <cruise>/{fetch_manifest.json, SHA256SUMS} for every fetched cruise (raw swath stays on
                               scratch and can be re-fetched from these)
  run_records.tar              <cruise>/{cruise_record.json, block_ledger.csv, fetch.json, fetch_log.csv, cruise_failure*.json}
  SHA256SUMS                   sha256 of every file above, computed at the SOURCE (tars hashed as written on scratch);
                               then every OAK file is re-read and hashed; persist_verify.json records ok / mismatch / missing,
                               plus a /vsitar/ read of one grid.tif per cruise (sample) against its member sha256.
Tars are built on $GROUP_SCRATCH (pretrain_v1_tars/) and copied; OAK files are made 0444.
Usage (Slurm): python -m src.acq_r04.persist --manifest pretrain_manifest_v1.parquet
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r04.blocks import cdir_name

TARS = R.SCR / "pretrain_v1_tars"


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build_cruise_tar(cruise: str, blocks: list[str]):
    """Deterministic uncompressed tar of the manifest's blocks of one cruise; returns (tar path, member sha rows)."""
    cd = cdir_name(cruise)
    TARS.mkdir(parents=True, exist_ok=True)
    out = TARS / f"{cd}.tar"; part = out.with_suffix(".tar.part")
    rows = []
    with tarfile.open(part, "w", format=tarfile.PAX_FORMAT) as tf:
        for b in sorted(blocks):
            root = R.STAGE / cd / b
            if not (root / "block.json").exists():
                raise FileNotFoundError(f"{cruise}/{b}: block directory missing on scratch")
            for p in sorted(root.rglob("*")):
                arc = f"{cd}/{b}/{p.relative_to(root)}"
                ti = tf.gettarinfo(str(p), arcname=arc)
                ti.uid = ti.gid = 0; ti.uname = ti.gname = ""
                if p.is_symlink() or p.is_dir():
                    tf.addfile(ti); continue
                data = p.read_bytes()
                rows.append({"cruise": cruise, "block": b, "member": arc, "bytes": len(data), "sha256": sha_bytes(data)})
                tf.addfile(ti, io.BytesIO(data))
    part.rename(out)
    return out, rows


def small_tar(out: Path, items):
    """items: [(arcname, path)] -> uncompressed tar."""
    part = out.with_suffix(".tar.part")
    with tarfile.open(part, "w", format=tarfile.PAX_FORMAT) as tf:
        for arc, p in sorted(items):
            ti = tf.gettarinfo(str(p), arcname=arc); ti.uid = ti.gid = 0; ti.uname = ti.gname = ""
            with open(p, "rb") as fh:
                tf.addfile(ti, fh)
    part.rename(out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--manifest", default="pretrain_manifest_v1.parquet")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    man = pd.read_parquet(R.REPORT_DIR / a.manifest)
    C.assert_no_lockbox_cruise(man.cruise.unique().tolist())
    sel = pd.read_csv(R.REPORT_DIR / "selection_v1.csv")
    out = R.OAK_OUT; (out / "blocks").mkdir(parents=True, exist_ok=True); (out / "meta").mkdir(exist_ok=True)

    # 1. per-cruise block tars (+ member sha256)
    groups = list(man.groupby("cruise").block.apply(list).items())
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        built = list(ex.map(lambda cb: build_cruise_tar(*cb), groups))
    members = pd.DataFrame([r for _, rows in built for r in rows])
    mem_csv = TARS / "block_members_sha256.csv.gz"
    with gzip.open(mem_csv, "wt") as fh:
        members.to_csv(fh, index=False)

    # 2. bookkeeping tars
    fm, rr = [], []
    for c in sel.cruise:
        cd = cdir_name(c)
        for n in ("fetch_manifest.json", "SHA256SUMS"):
            p = R.PRETRAIN_RAW / cd / n
            if p.exists():
                fm.append((f"{cd}/{n}", p))
        lg = R.WORK_LOGS / cd
        if lg.exists():
            for p in sorted(lg.glob("*")):
                if p.is_file() and (p.name in ("cruise_record.json", "block_ledger.csv", "fetch.json", "fetch_log.csv") or p.name.startswith("cruise_failure")):
                    rr.append((f"{cd}/{p.name}", p))
    small_tar(TARS / "fetch_manifests.tar", fm); small_tar(TARS / "run_records.tar", rr)

    # 3. copy list (source, destination)
    pairs = [(t, out / "blocks" / t.name) for t, _ in built]
    pairs += [(TARS / "fetch_manifests.tar", out / "fetch_manifests.tar"), (TARS / "run_records.tar", out / "run_records.tar"),
              (mem_csv, out / "meta" / mem_csv.name), (R.CACHE / "exclusion_geometries_v1.geojson", out / "meta" / "exclusion_geometries_v1.geojson")]
    metas = sorted(R.REPORT_DIR.glob("pretrain_manifest_v*")) + sorted(R.REPORT_DIR.glob("failure_ledger_v*.csv")) + \
        sorted(R.REPORT_DIR.glob("selection_v1_1*")) + \
        [R.REPORT_DIR / n for n in ("exclusion_v1.json", "pool_v1.csv", "pool_ids_v1.csv", "selection_v1.csv", "selection_v1.json", "selection_v1_filelist.csv.gz")]
    pairs += [(p, out / "meta" / p.name) for p in metas if p.exists()]

    def put(pq):
        p, q = pq
        h = R.sha256_file(p)
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

    # 4. verify at destination: re-hash every OAK file; /vsitar/ read of one grid.tif per cruise vs its member sha256
    def ver(line):
        h, rel = line.split("  ", 1)
        q = out / rel
        if not q.exists():
            return rel, "missing"
        return rel, "ok" if R.sha256_file(q) == h else "MISMATCH"
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        vr = list(ex.map(ver, sums.read_text().splitlines()))
    bad = [r for r in vr if r[1] != "ok"]
    vsi = []
    for c, g in members[members.member.str.endswith("/grid.tif")].groupby("cruise"):
        r0 = g.iloc[0]
        tarp = out / "blocks" / f"{cdir_name(c)}.tar"
        with tarfile.open(tarp) as tf:
            got = sha_bytes(tf.extractfile(r0.member).read())
        import rasterio
        with rasterio.open(f"/vsitar/{tarp}/{r0.member}") as ds:
            shape = ds.shape
        vsi.append({"cruise": c, "member": r0.member, "sha256_ok": got == r0.sha256, "vsitar_open_shape": list(shape)})
    nbytes = sum((out / rel).stat().st_size for rel, _, _ in res)
    rep = {"generated": R.utc_now(), "destination": str(out), "layout": "per-cruise uncompressed tar (decision 2026-10-06, option B)",
           "files": len(res), "bytes": int(nbytes), "gb": round(nbytes / 1e9, 3), "cruise_tars": len(built),
           "blocks": int(len(man)), "tar_members": int(len(members)),
           "copied": sum(r[2] == "copied" for r in res), "already_present": sum(r[2] == "present" for r in res),
           "verified_ok": sum(r[1] == "ok" for r in vr), "not_ok": bad,
           "vsitar_sample": {"cruises": len(vsi), "sha_ok": sum(v["sha256_ok"] for v in vsi), "rows": vsi},
           "sha256sums_sha256": R.sha256_file(sums), "manifest": a.manifest, "code_commit": C.git_commit()}
    R.write_json(R.REPORT_DIR / "persist_verify.json", rep)
    print(json.dumps({k: v for k, v in rep.items() if k not in ("not_ok", "vsitar_sample")}, indent=1),
          "| not ok:", len(bad), "| vsitar sha ok:", rep["vsitar_sample"]["sha_ok"], "/", len(vsi))
    return 0 if not bad and all(v["sha256_ok"] for v in vsi) else 1


if __name__ == "__main__":
    sys.exit(main())
