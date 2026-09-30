"""ACQ-R01 §2.2 step 1 — re-fetch the raw NCEI swath for the 12 in-scope cruises to OAK.

Fetches exactly the swath files listed in the persisted stage-B fetch plan
(``reports/discovery/stage_b_file_plan_2026-06-22.csv``; the same whole/subset
file subset stage C gridded from), byte-exact against HEAD Content-Length, gzip-tested,
sha256'd, and stored permanently under ``$OAK/auv_ship_colocated_bathy/raw_lr_swath/<cruise>/``.
Idempotent: files already present with the right size are skipped (and re-hashed).

Nav sidecars (.fnv) are NOT fetched: stage C never used them (MB-System regenerates nav),
and most were 0-byte at NCEI.

Usage (inside a Slurm job):
  python -m src.acq_r01.fetch_swath [--cruises A,B] [--workers 6] [--plan-only]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from src.acq_r01 import common as C

log = logging.getLogger("acq_r01.fetch")
_HEADERS = {"User-Agent": "auv-ship-acq/0.3 (Sherlock; ACQ-R01 raw swath re-fetch; "
                          "stephencoledobbs@gmail.com)"}
_RETRIES = 6
_THROTTLE = 0.1          # overridden by --throttle (PANGAEA hs server rate-limits: use >= 1.5 s, 1 worker)


def _backoff(r, attempt):
    """Sleep politely on 429 / 5xx: honour Retry-After, else exponential (5 s .. 120 s)."""
    ra = None
    try:
        ra = float(r.headers.get("Retry-After", "")) if r is not None else None
    except ValueError:
        ra = None
    time.sleep(min(120.0, ra if ra else 5.0 * (2 ** attempt)))


def _head_len(url, sess):
    status = "no_attempt"
    for attempt in range(_RETRIES):
        try:
            r = sess.head(url, headers=_HEADERS, timeout=60, allow_redirects=True)
            status = str(r.status_code)
            if r.status_code == 200 and "Content-Length" in r.headers:
                return int(r.headers["Content-Length"]), status
            if r.status_code == 429 or r.status_code >= 500:
                _backoff(r, attempt); continue
            return None, status
        except requests.Timeout:
            status = "timeout"; time.sleep(2 ** attempt)
        except Exception:
            status = "conn_err"; time.sleep(2 ** attempt)
    return None, status


def _gzip_ok(path: Path) -> bool:
    if not path.name.endswith(".gz"):
        return True
    return subprocess.run(["gzip", "-t", str(path)], capture_output=True).returncode == 0


def fetch_one(rec: dict, sess: requests.Session) -> dict:
    out_dir = C.RAW_SWATH_OAK / rec["cruise"]
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / rec["filename"]
    clen, http = _head_len(rec["url"], sess)
    r = {**rec, "head_content_length": clen, "http_status": http, "status": "", "received": 0,
         "sha256": "", "gzip_ok": None}
    if out.exists() and clen is not None and out.stat().st_size == clen:
        r["status"] = "skip_present"
    elif out.exists() and clen is None and out.stat().st_size > 0:
        r["status"] = "skip_present_unverified_len"
    elif clen is None and http != "200":
        r["status"] = "failed_head"; return r
    elif clen is None:
        # HEAD 200 without Content-Length (2 EX1202L2 files): fetch and accept a non-empty body
        clen = -1
    else:
        if out.exists():
            out.unlink()                       # size mismatch: re-fetch
        for attempt in range(_RETRIES):
            try:
                with sess.get(rec["url"], headers=_HEADERS, timeout=600, stream=True) as g:
                    r["http_status"] = str(g.status_code)
                    if g.status_code == 429 or g.status_code >= 500:
                        _backoff(g, attempt); continue
                    if g.status_code != 200:
                        r["status"] = "failed_get"; return r
                    tmp = out.with_suffix(out.suffix + ".part")
                    n = 0
                    with tmp.open("wb") as fh:
                        for chunk in g.iter_content(chunk_size=1 << 20):
                            fh.write(chunk); n += len(chunk)
                if n == clen or (clen == -1 and n > 0):
                    tmp.rename(out); r["status"] = "fetched" if clen != -1 else "fetched_unverified_len"; break
                tmp.unlink(missing_ok=True); time.sleep(2 ** attempt)
            except requests.Timeout:
                r["http_status"] = "timeout"; time.sleep(2 ** attempt)
            except Exception as e:
                r["http_status"] = f"err:{type(e).__name__}"; time.sleep(2 ** attempt)
        if not r["status"].startswith("fetched"):
            r["status"] = "failed_get"; return r
        time.sleep(_THROTTLE)
    r["received"] = out.stat().st_size
    r["gzip_ok"] = _gzip_ok(out)
    if not r["gzip_ok"]:
        r["status"] = "corrupt_content"; return r
    r["sha256"] = C.sha256_file(out)
    try:
        out.chmod(0o444)
    except Exception:
        pass
    return r


# PANGAEA raw-swath datasets for the provider-grid units (ACQ-R01 §2.2 step 6).
# dataset id -> (cruise_dir on OAK, event filter or None, pair_id)
PANGAEA_RAW = {
    "859528": {"cruise_dir": "SO242_1_EM122", "event": None, "pair": "discol_so242_1",
               "note": "Swath sonar multibeam EM122 bathymetry during SONNE cruise SO242/1 with links to raw data files (all 69 files; whole cruise < 10 GB, A.6 'small cruise -> whole' rule)"},
    "899408": {"cruise_dir": "M127_EM122", "event": None, "pair": "tag_m127",
               "note": "Raw multibeam EM122 data and data products: METEOR cruise M127 (TAG) - the raw .all files of the dataset the 30 m LR grid itself belongs to"},
    "919755": {"cruise_dir": "SO268_1_EM122", "event": "SO268/1-track", "pair": "ccz_so268_1",
               "note": "Swath sonar multibeam EM122 bathymetry raw data during SONNE cruises SO268/1 and SO268/2, German License Area; SO268/1-track files only (the 50 m LR grid 915764 is 'collected during SO268/1')"},
}


def pangaea_plan(dataset_id: str) -> pd.DataFrame:
    """Per-file plan from a PANGAEA 'with links to raw data files' dataset (tab export)."""
    import io
    info = PANGAEA_RAW[dataset_id]
    url = f"https://doi.pangaea.de/10.1594/PANGAEA.{dataset_id}?format=textfile"
    r = requests.get(url, headers=_HEADERS, timeout=120); r.raise_for_status()
    lines = r.text.splitlines()
    s = [i for i, l in enumerate(lines) if l.startswith("*/")][0] + 1
    C.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (C.REPORT_DIR / f"pangaea_{dataset_id}_filelist.tab").write_text(r.text)
    df = pd.read_csv(io.StringIO("\n".join(lines[s:])), sep="\t")
    df = df[df["URL raw"].notna()]
    if info["event"] is not None and "Event" in df:
        df = df[df["Event"] == info["event"]]
    out = pd.DataFrame({"cruise": info["cruise_dir"], "filename": df["URL raw"].str.rsplit("/", n=1).str[-1],
                        "url": df["URL raw"], "advertised": (df["File size [kByte]"] * 1024).round().astype("int64"),
                        "kind": "swath"})
    return out.reset_index(drop=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cruises", default=",".join(C.NCEI_CRUISES))
    ap.add_argument("--pangaea", default=None, help="comma list of PANGAEA dataset ids (859528,899408,919755)")
    ap.add_argument("--plan-csv", default=None, help="generic per-file plan (cruise,filename,url,advertised,kind) e.g. ACQ-R02 fetch_plan/file_plan.csv")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--throttle", type=float, default=None, help="seconds between requests per worker")
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    global _THROTTLE
    if a.throttle is not None:
        _THROTTLE = a.throttle
    if a.plan_csv:
        plan = pd.read_csv(a.plan_csv)
        plan = plan[plan.kind == "swath"]
        if a.cruises and a.cruises != ",".join(C.NCEI_CRUISES):
            plan = plan[plan.cruise.isin(a.cruises.split(","))]
        cruises = sorted(plan.cruise.unique())
        C.assert_no_lockbox_cruise(cruises)
        suffix = "_" + Path(a.plan_csv).stem
    elif a.pangaea:
        plan = pd.concat([pangaea_plan(d) for d in a.pangaea.split(",")], ignore_index=True)
        cruises = sorted(plan.cruise.unique())
        suffix = "_pangaea"
    else:
        cruises = [c for c in a.cruises.split(",") if c]
        C.assert_no_lockbox_cruise(cruises)
        plan = pd.read_csv(C.FILE_PLAN)
        plan = plan[(plan.kind == "swath") & (plan.cruise.isin(cruises))]
        suffix = ""
    if plan.empty:
        # cruise already on OAK (fetch plan status already_on_oak) or nothing planned: nothing to do
        have = [c for c in (a.cruises or "").split(",") if c and (C.RAW_SWATH_OAK / c / "fetch_manifest.json").exists()]
        log.info("plan is empty for %s; already on OAK: %s", a.cruises, have)
        return 0 if have else 1
    log.info("plan: %d swath files, %.2f GB advertised, cruises=%s",
             len(plan), plan.advertised.sum() / 1e9, cruises)
    C.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if a.plan_only:
        print(plan.groupby("cruise").agg(n=("filename", "count"), GB=("advertised", lambda s: s.sum() / 1e9)))
        return 0
    t0 = time.time()
    recs = plan.to_dict("records")
    sessions = [requests.Session() for _ in range(a.workers)]
    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for k, r in enumerate(ex.map(lambda ip: fetch_one(ip[1], sessions[ip[0] % a.workers]), enumerate(recs)), 1):
            results.append(r)
            if k % 100 == 0 or k == len(recs):
                log.info("  %d/%d done (%.1f GB so far, %.0f s)", k, len(recs),
                         sum(x["received"] for x in results) / 1e9, time.time() - t0)
    wall = time.time() - t0
    df = pd.DataFrame(results)
    log_csv = C.REPORT_DIR / f"fetch_swath_log{suffix}.csv"
    df.to_csv(log_csv, index=False)
    # per-cruise SHA256SUMS + fetch manifest on OAK
    summary = {}
    for cr, g in df.groupby("cruise"):
        ok = g[g.status.isin(["fetched", "fetched_unverified_len", "skip_present", "skip_present_unverified_len"])]
        bad = g[~g.status.isin(["fetched", "fetched_unverified_len", "skip_present", "skip_present_unverified_len"])]
        d = C.RAW_SWATH_OAK / cr
        with (d / "SHA256SUMS").open("w") as f:
            for _, r in ok.iterrows():
                f.write(f"{r.sha256}  {r.filename}\n")
        src_note = ("PANGAEA (hs.pangaea.de): " + "; ".join(f"10.1594/PANGAEA.{k} {v['note']}" for k, v in PANGAEA_RAW.items() if v["cruise_dir"] == cr)
                    if a.pangaea else ("PANGAEA (hs.pangaea.de)" if cr.startswith("PANGAEA_") else "NCEI MBBDB (data.ngdc.noaa.gov)"))
        man = {"cruise": cr, "source": src_note, "plan": ("pangaea tab export" if a.pangaea else (a.plan_csv or str(C.FILE_PLAN))),
               "fetched_at": datetime.now(timezone.utc).isoformat(), "n_files_planned": int(len(g)),
               "n_files_ok": int(len(ok)), "n_files_failed": int(len(bad)),
               "bytes_ok": int(ok.received.sum()), "failed": bad[["filename", "url", "status", "http_status"]].to_dict("records"),
               "files": ok[["filename", "url", "received", "sha256"]].rename(columns={"received": "size"}).to_dict("records")}
        (d / "fetch_manifest.json").write_text(json.dumps(man, indent=1))
        summary[cr] = {"n_planned": int(len(g)), "n_ok": int(len(ok)), "n_failed": int(len(bad)),
                       "gb": round(ok.received.sum() / 1e9, 3), "complete": bool(len(bad) == 0)}
    tot = {"cruises": summary, "total_gb": round(df.received.sum() / 1e9, 3), "wall_s": round(wall, 1),
           "status_counts": df.status.value_counts().to_dict(), "generated": datetime.now(timezone.utc).isoformat()}
    C.write_json(C.REPORT_DIR / f"fetch_swath_summary{suffix}.json", tot)
    print(json.dumps(tot, indent=1))
    return 0 if all(v["complete"] for v in summary.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
