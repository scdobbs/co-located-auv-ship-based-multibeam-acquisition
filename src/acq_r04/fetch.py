"""ACQ-R04 §3.2 — fetch the selected cruises' raw NCEI swath to scratch (never OAK).

Method = ACQ-R01 fetch_swath.fetch_one, unchanged: HEAD Content-Length, byte-exact download, `gzip -t`, sha256,
back-off on 429/5xx (Retry-After or 5..120 s), idempotent (present files with the right length are skipped and
re-hashed).  Only the destination root differs: fetch_one writes under common.RAW_SWATH_OAK, which this process
points at $GROUP_SCRATCH/auv_ship_colocated_bathy/pretrain_raw/ before any call.
ONE fetch process serves all cruises, with <= 6 workers in total (NCEI etiquette, as ACQ-R01).
Per cruise: pretrain_raw/<cruise>/fetch_manifest.json (URL, size, sha256 per file; failures listed) + SHA256SUMS,
and a timing record WORK_LOGS/<cruise>/fetch.json.
Usage (Slurm): python -m src.acq_r04.fetch --cruises A,B,...  |  --first N  [--workers 6]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd
import requests

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r01 import fetch_swath as FS

log = logging.getLogger("acq_r04.fetch")
_OK = ["fetched", "fetched_unverified_len", "skip_present", "skip_present_unverified_len", "empty_file"]


def cdir_name(cruise: str) -> str:
    return cruise.replace("/", "_")


def fetch_cruise(cruise: str, plan: pd.DataFrame, workers: int) -> dict:
    C.assert_no_lockbox_cruise([cruise])
    d = R.PRETRAIN_RAW / cdir_name(cruise)
    d.mkdir(parents=True, exist_ok=True)
    # Name collisions (found 2026-10-03, AR30-01): multi-sonar cruises serve the same file name from several NCEI
    # subdirectories (e.g. MB/em710/9999.all.mb58.gz and MB/em122/9999.all.mb58.gz).  A flat raw directory would let one
    # overwrite the other.  Colliding names are stored as <parent dir>__<name>; a plain-named copy left by an earlier fetch
    # (ambiguous: either source) is moved to _quarantine_name_collision/, never used.
    dup = plan.filename.duplicated(keep=False)
    local = [f"{u.rstrip('/').split('/')[-2]}__{n}" if is_dup else n for n, u, is_dup in zip(plan.filename, plan.url, dup)]
    for n in sorted(set(plan.filename[dup])):
        if (d / n).exists():
            qd = d / "_quarantine_name_collision"; qd.mkdir(exist_ok=True)
            (d / n).rename(qd / n)
            log.warning("[%s] %s: ambiguous plain-named copy from an earlier fetch quarantined", cruise, n)
    recs = [{"cruise": cdir_name(cruise), "filename": ln, "url": r.url, "advertised": int(r.advertised), "kind": "swath"}
            for ln, r in zip(local, plan.itertuples())]
    assert len(set(r["filename"] for r in recs)) == len(recs), f"{cruise}: local file names still collide"
    t0 = time.time()
    sessions = [requests.Session() for _ in range(workers)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(lambda ip: FS.fetch_one(ip[1], sessions[ip[0] % workers]), enumerate(recs)))
    wall = time.time() - t0
    df = pd.DataFrame(res)
    ok = df[df.status.isin(_OK)]; bad = df[~df.status.isin(_OK)]
    man = {"cruise": cruise, "source": "NCEI MBBDB (data.ngdc.noaa.gov)", "plan": "reports_post_grl_review/ACQ-R04/selection_v1_filelist.csv.gz",
           "method": "src.acq_r01.fetch_swath.fetch_one (byte-exact vs Content-Length, gzip -t, sha256)",
           "fetched_at": datetime.now(timezone.utc).isoformat(), "n_files_planned": int(len(df)), "n_files_ok": int(len(ok)),
           "n_files_failed": int(len(bad)), "bytes_ok": int(ok.received.sum()),
           "failed": bad[["filename", "url", "status", "http_status"]].to_dict("records"),
           "files": ok[["filename", "url", "received", "sha256"]].rename(columns={"received": "size"}).to_dict("records")}
    for name, txt in (("fetch_manifest.json", json.dumps(man, indent=1)),
                      ("SHA256SUMS", "".join(f"{r.sha256}  {r.filename}\n" for r in ok.itertuples() if r.sha256))):
        p = d / name
        if p.exists():
            p.chmod(0o644)
        p.write_text(txt); p.chmod(0o444)
    rec = {"cruise": cruise, "n_files": int(len(df)), "n_ok": int(len(ok)), "n_failed": int(len(bad)),
           "bytes": int(ok.received.sum()), "advertised_bytes": int(plan.advertised.sum()), "fetch_wall_s": round(wall, 1),
           "status_counts": df.status.value_counts().to_dict(), "workers": workers, "finished": R.utc_now()}
    R.write_json(R.WORK_LOGS / cdir_name(cruise) / "fetch.json", rec)
    df.to_csv(R.WORK_LOGS / cdir_name(cruise) / "fetch_log.csv", index=False)
    log.info("[%s] %d/%d files, %.2f GB, %.0f s", cruise, len(ok), len(df), rec["bytes"] / 1e9, wall)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cruises", default=None); ap.add_argument("--first", type=int, default=None)
    ap.add_argument("--skip", default=None, help="comma list of cruises to skip (e.g. the pilot, already fetched)")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    if a.workers > 6:
        raise SystemExit("NCEI etiquette: <= 6 workers")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    FS.C.RAW_SWATH_OAK = R.PRETRAIN_RAW          # destination: scratch (fetch_one reads this global at call time)
    assert C.RAW_SWATH_OAK == R.PRETRAIN_RAW and "scratch" in str(R.PRETRAIN_RAW)
    sel = pd.read_csv(R.REPORT_DIR / "selection_v1.csv")
    fl = pd.read_csv(R.REPORT_DIR / "selection_v1_filelist.csv.gz")
    cruises = a.cruises.split(",") if a.cruises else sel.cruise.tolist()[: a.first]
    skip = set((a.skip or "").split(","))
    C.assert_no_lockbox_cruise(cruises)
    n_bad = 0
    for c in cruises:
        if c in skip:
            continue
        rec = fetch_cruise(c, fl[fl.cruise == c], a.workers)
        n_bad += rec["n_failed"] > 0
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
