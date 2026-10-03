"""ACQ-R04 §1 (pool attributes) — advertised size, file formats and depth for every pool cruise -> pool_v1.csv.

Metadata only (no swath).  Per pool cruise (pool_ids_v1.csv from exclusion.py):
  1. Geoportal ISO record -> NCEI data directory (stage A/B machinery: raw_lr_dryrun.data_dir_from_iso,
     resolve_data_dir); the ACQ-R01 listing caches are reused (same public autoindex pages).
  2. Autoindex walk with the stage-B classification (the rules of stage_a5_subset.iter_cruise_files, re-implemented so
     that a listing failure is retried (3x) and RECORDED: iter_cruise_files skips a failed subdirectory silently).  The
     MB-System `generated/` directories (.inf/.fbt/.fnv derived files, no swath; often thousands of entries and slow to
     list) are not walked.  Any other subdirectory that cannot be listed -> crawl_status listing_incomplete (not
     selectable).  One encoding per cruise (stage_b_fetch._dedup_encoding).
  3. MB format per swath file by build_products.fmt_for (the format inference the stage-C/contract builders use);
     dominant format = the one with most advertised bytes.  Readable (§2.1) = swath files exist and the dominant
     format is inferable; only the dominant-format files are planned (advertised_bytes counts those).
  4. Depth where known: min/max depth from up to 3 MB-System .inf files in the walked listing (ACQ-R01 method; .inf
     files that live only under generated/ are not read).
Every cruise ends with a status (ok | no_iso | no_data_dir | listing_incomplete | no_swath_legacy | unknown_format | error:...); nothing is
dropped silently.  Per-cruise file lists go to the scratch cache (file list source for selection).
Usage (Slurm): python -m src.acq_r04.pool_crawl [--workers 6]
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r01.build_products import fmt_for
from src.discovery import raw_lr_dryrun as RD
from src.discovery.raw_lr_dryrun import data_dir_from_iso, resolve_data_dir
from src.discovery.stage_a5_subset import FileRec, _basekey
from urllib.parse import urljoin
from src.discovery.stage_b_fetch import _dedup_encoding
from src.discovery.geoportal import _GEOPORTAL_BASE

log = logging.getLogger("acq_r04.pool_crawl")
R01_CACHE = C.SCRATCH_DATA / "discovery_cache" / "acq_r01_2026-09-29"
GEOPORTAL = R01_CACHE / "geoportal"
DIRLIST = R01_CACHE / "ncei_dirlist"
FILELISTS = R.CACHE / "filelists_v2"
STATE = R.CACHE / "pool_crawl_state_v2"      # v1 state (first 18 cruises, silent-skip walker) is not reused


def _fmt(name):
    try:
        return fmt_for(name)
    except ValueError:
        return None


def walk(data_url: str):
    """(file records, failed subdirectory urls, skipped generated/ urls) with the stage-B classification."""
    recs, failed, skipped = [], [], []
    stack, seen = [data_url], set()
    while stack:
        url = stack.pop()
        if url in seen:
            continue
        seen.add(url)
        html = None
        for attempt in range(3):
            html = RD._list_dir(url, DIRLIST)
            if html is not None:
                break
            time.sleep(10 * (attempt + 1))
        if html is None:
            failed.append(url); continue
        for m in RD._ROW.finditer(html):
            href = m.group("href")
            if href.startswith(("/", "?", "http")):
                continue
            if href.endswith("/"):
                if href.rstrip("/").lower() == "generated":
                    skipped.append(urljoin(url, href)); continue
                stack.append(urljoin(url, href)); continue
            nb = RD._human_to_bytes(m.group("size"))
            if nb is None:
                continue
            if href.endswith(".fnv"):
                kind = "nav"
            elif RD._ext_of(href) in (".fbt", ".inf", ".fnv") or href.endswith((".fbt", ".inf")):
                kind = "ancillary"
            elif re.search(r"\.all\.gz$|\.gsf\.gz$|\.all\.mb\d+\.gz$|\.gsf\.mb\d+\.gz$|\.mb\d+\.gz$|\.mb\d+$|\.all$|\.gsf$", href):
                kind = "swath"
            else:
                kind = "ancillary"
            recs.append(FileRec(urljoin(url, href), href, nb, kind, _basekey(href)))
    return recs, failed, skipped


def crawl_one(sid: str) -> dict:
    st = STATE / f"{sid.replace('/', '_')}.json"
    if st.exists():
        return json.loads(st.read_text())
    rec = {"survey_id": sid, "crawl_status": "ok", "data_url": None, "n_swath_files": 0, "n_files_listed": 0,
           "listing_bytes": None, "swath_bytes_all": None, "advertised_bytes": None, "dominant_format": None,
           "formats": "", "ext_top": "", "depth_min_m": None, "depth_max_m": None, "depth_source": None,
           "file_list": None, "note": ""}
    try:
        p = GEOPORTAL / f"{sid}.json"
        if not p.exists():
            for attempt in range(4):
                try:
                    r = requests.get(_GEOPORTAL_BASE + sid + "_Multibeam", params={"f": "json"}, headers=R.HEADERS, timeout=60)
                    if r.status_code in (429,) or r.status_code >= 500:
                        time.sleep(10 * (attempt + 1)); continue
                    p.write_text(json.dumps(r.json() if r.status_code == 200 else {"_status": r.status_code})); break
                except Exception as e:
                    rec["note"] = f"geoportal {type(e).__name__}"; time.sleep(10 * (attempt + 1))
            time.sleep(0.3)
        iso = data_dir_from_iso(sid, GEOPORTAL)
        if not iso:
            rec["crawl_status"] = "no_iso"; return rec          # not cached: a transient Geoportal failure is retried on re-run
        url, note = resolve_data_dir(iso, DIRLIST)
        rec["note"] += note
        if not url:
            rec["crawl_status"] = "no_data_dir"; return rec     # not cached: retried on re-run
        rec["data_url"] = url
        recs, failed_dirs, skipped_dirs = walk(url)
        rec["listing_failed_dirs"] = failed_dirs; rec["generated_dirs_skipped"] = len(skipped_dirs)
        if failed_dirs:
            rec["crawl_status"] = "listing_incomplete"; rec["note"] += f" {len(failed_dirs)} subdirectory listing(s) failed after 3 tries"
            return rec            # not cached: retried on re-run
        rec["n_files_listed"] = len(recs); rec["listing_bytes"] = int(sum(x.bytes for x in recs))
        exts = collections.Counter(RD._ext_of(x.name) for x in recs)
        rec["ext_top"] = exts.most_common(1)[0][0] if exts else ""
        swath = [x for x in recs if x.kind == "swath"]
        rec["swath_bytes_all"] = int(sum(x.bytes for x in swath))
        if not swath:
            rec["crawl_status"] = "no_swath_legacy"
            rec["formats"] = ";".join(f"{e}:{n}" for e, n in exts.most_common(5)); return _save(st, rec)
        chosen = _dedup_encoding(swath)
        byfmt = collections.defaultdict(int); cnt = collections.Counter()
        for x in chosen:
            f = _fmt(x.name); byfmt[f] += x.bytes; cnt[f] += 1
        rec["formats"] = ";".join(f"mb{f}:{cnt[f]}" for f in sorted(cnt, key=lambda k: -byfmt[k]))
        dom = max(byfmt, key=byfmt.get)
        if dom is None:
            rec["crawl_status"] = "unknown_format"; return _save(st, rec)
        files = [x for x in chosen if _fmt(x.name) == dom]
        rec["dominant_format"] = int(dom); rec["n_swath_files"] = len(files)
        rec["advertised_bytes"] = int(sum(x.bytes for x in files))
        FILELISTS.mkdir(parents=True, exist_ok=True)
        fl = FILELISTS / f"{sid.replace('/', '_')}.csv"
        pd.DataFrame([{"cruise": sid, "filename": x.name, "url": x.url, "advertised": x.bytes, "kind": "swath", "mb_format": dom}
                      for x in files]).to_csv(fl, index=False)
        rec["file_list"] = str(fl)
        infs = [x for x in recs if x.name.endswith(".inf")][:3]
        dmin, dmax = [], []
        for inf in infs:
            try:
                t = requests.get(inf.url, headers=R.HEADERS, timeout=60).text; time.sleep(0.3)
                mm = re.search(r"Minimum Depth:\s*([-\d.]+)\s+Maximum Depth:\s*([-\d.]+)", t)
                if mm:
                    dmin.append(abs(float(mm.group(1)))); dmax.append(abs(float(mm.group(2))))
            except Exception:
                pass
        if dmin:
            rec["depth_min_m"] = min(dmin); rec["depth_max_m"] = max(dmax); rec["depth_source"] = f".inf x{len(dmin)}"
    except Exception as e:
        rec["crawl_status"] = f"error:{type(e).__name__}"; rec["note"] += str(e)[:200]
        return rec          # not cached: retried on re-run
    return _save(st, rec)


def _save(st, rec):
    st.parent.mkdir(parents=True, exist_ok=True)
    st.write_text(json.dumps(rec))
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    pool = pd.read_csv(R.REPORT_DIR / "pool_ids_v1.csv")
    C.assert_no_lockbox_cruise(pool.survey_id.tolist())
    t0 = time.time(); out = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for k, r in enumerate(ex.map(crawl_one, pool.survey_id), 1):
            out.append(r)
            if k % 100 == 0:
                log.info("%d/%d (%.0f s)", k, len(pool), time.time() - t0)
    cr = pd.DataFrame(out)
    df = pool.merge(cr, on="survey_id", how="left")
    df.insert(1, "readable", df.crawl_status.eq("ok") & df.dominant_format.notna())
    # depth where known: the crawl reads .inf only outside generated/; add the ACQ-R01 §5 sample's .inf depths
    smp = pd.read_csv(R.R01 / "pretrain_scope" / "sample_surveys.csv")[["survey", "depth_min", "depth_max"]].dropna()
    smp = smp.drop_duplicates("survey").set_index("survey")
    for i in df.index[df.depth_max_m.isna() & df.survey_id.isin(smp.index)]:
        sid = df.at[i, "survey_id"]
        df.at[i, "depth_min_m"] = smp.at[sid, "depth_min"]; df.at[i, "depth_max_m"] = smp.at[sid, "depth_max"]
        df.at[i, "depth_source"] = "ACQ-R01 pretrain_scope/sample_surveys.csv (.inf, up to 3 files)"
    df.to_csv(R.REPORT_DIR / "pool_v1.csv", index=False)
    summ = {"generated": R.utc_now(), "n_pool": int(len(df)), "status_counts": df.crawl_status.value_counts().to_dict(),
            "readable": int(df.readable.sum()), "readable_frac": round(float(df.readable.mean()), 4),
            "advertised_tb_readable": round(float(df.loc[df.readable, "advertised_bytes"].sum()) / 1e12, 3),
            "depth_known": int(df.depth_max_m.notna().sum()), "wall_s": round(time.time() - t0, 1),
            "listing_cache": str(DIRLIST), "geoportal_cache": str(GEOPORTAL), "code_commit": C.git_commit()}
    R.write_json(R.REPORT_DIR / "pool_crawl_summary.json", summ)
    print(json.dumps(summ, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
