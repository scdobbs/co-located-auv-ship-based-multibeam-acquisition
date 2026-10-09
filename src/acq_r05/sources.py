"""ACQ-R05 §2.1.1 — source files per LR cruise.

Whole-cruise fetches: the files already on OAK raw_lr_swath/<cruise>/.  Subset fetches (June A.5 nav-intersection:
FK181031, NA080, TN299, TN399; ACQ-R02 planned EX1402L2 as a subset but fetched all 311 files): every file of the cruise
with soundings inside the context extent is needed.  Which files those are cannot be known from NCEI metadata alone
(the per-0.1-degree-cell selection of ACQ-R04 needs the soundings), so:
  1. the cruise directory is listed at NCEI (fresh listing, cached under discovery_cache/acq_r05_2026-10-09/);
  2. for every swath file NOT on OAK the .fnv nav track is fetched (small) and tested against the union of the in-scope
     pairs' context mbgrid regions buffered by the swath reach max(2 km, 3 x median depth) (the products builder's
     window margin, build_products.lr_window) — the same test the stage A.5 / ACQ-R02 nav subset used, with the
     context extent instead of the HR footprint; files without a nav track are included (conservative, counted);
  3. the selected files are fetched to OAK raw_lr_swath/<cruise>/ with fetch_swath.fetch_one (byte-exact vs
     Content-Length, gzip -t, sha256, back-off), ACQ-R04 collision-safe names; fetch_manifest.json + SHA256SUMS are
     updated (originals kept as *.pre_acq_r05_2026-10-09);
  4. the coverage pass of ACQ-R04 (blocks.coverage_pass: one streamed mblist -MA -OXYZ over every file, bounded,
     retried, unreadable files ledgered) records each file's 0.1-degree sounding cells, from which every pair's exact
     file set is selected (files with a sounding in a cell the pair's mbgrid region touches).
Usage (Slurm): python -m src.acq_r05.sources --cruise TN399 [--plan-only] [--workers 6]
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import math
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
import requests
from shapely.geometry import box
from shapely.ops import transform as shp_transform, unary_union

from src.acq_r05 import common as R
from src.acq_r05 import lattice as L
from src.acq_r01 import common as C
from src.acq_r01 import fetch_swath as FS
from src.acq_r01.build_products import fmt_for, swath_files
from src.acq_r04 import blocks as B4
from src.discovery.stage_a5_subset import iter_cruise_files, prefetch_nav, parse_fnv_track

log = logging.getLogger("acq_r05.sources")
SRC_DIR = R.REPORT_DIR / "sources"
BACKUP_TAG = "pre_acq_r05_2026-10-09"
_OK = ("fetched", "fetched_unverified_len", "skip_present", "skip_present_unverified_len")


def pairs_of_cruise(cruise: str):
    return [p for p in R.NCEI_PAIRS if R.lr_cruise(p) == cruise]


def cruise_record(cruise: str) -> dict:
    """Fetch mode history + NCEI data directory of a development LR cruise."""
    C.assert_no_lockbox_cruise([cruise])
    fl = pd.read_csv(R.REPO / "reports/stage_b_fetch_list_2026-06-22.csv").set_index("cruise")
    sizes = pd.read_csv(R.REPO / "reports/discovery/stage_a_raw_lr_sizes_2026-06-22.csv").set_index("cruise")
    plan = pd.read_csv(R.R02 / "fetch_plan" / "cruise_plan.csv").set_index("cruise")
    rec = {"cruise": cruise, "oak_dir": str(C.RAW_SWATH_OAK / cruise)}
    if cruise in fl.index:
        rec.update({"origin": "June stage B (A.5 nav subset rule)", "fetch_mode": str(fl.loc[cruise, "fetch_mode"]), "whole_gb": float(fl.loc[cruise, "whole_GB"]),
                    "subset_gb": float(fl.loc[cruise, "subset_GB"]), "data_url": str(sizes.loc[cruise, "data_url"]), "n_files_ncei_june": int(sizes.loc[cruise, "n_files"])})
    elif cruise in plan.index:
        r = plan.loc[cruise]
        rec.update({"origin": "ACQ-R02 fetch plan", "fetch_mode": "subset" if str(r["mode"]).startswith("subset") else str(r["mode"]), "whole_gb": float(r["whole_gb"]),
                    "subset_gb": float(r["planned_gb"]), "data_url": str(r["data_url"]), "n_files_ncei": int(r["n_files_total"]), "n_files_planned": int(r["n_files_planned"])})
    else:
        raise KeyError(f"{cruise}: not in the June fetch list nor the ACQ-R02 plan")
    man = json.loads((C.RAW_SWATH_OAK / cruise / "fetch_manifest.json").read_text())
    rec["n_files_on_oak"] = len(swath_files(C.RAW_SWATH_OAK / cruise)); rec["n_files_manifest"] = len(man["files"])
    rec["bytes_on_oak"] = int(sum(p.stat().st_size for p in swath_files(C.RAW_SWATH_OAK / cruise)))
    # a subset fetch that took every file of the cruise is a whole cruise (EX1402L2: 311/311)
    rec["is_subset"] = rec["fetch_mode"].startswith("subset") and not (rec.get("n_files_planned") and rec["n_files_planned"] >= rec.get("n_files_ncei", 10 ** 9))
    return rec


def needed_region_4326(cruise: str) -> dict:
    """Union of the in-scope pairs' context mbgrid regions (lon/lat boxes) and the nav-test polygon (those boxes
    buffered in each pair's UTM by max(2 km, 3 x median |lr| depth))."""
    boxes, navs, per = [], [], {}
    for pid in pairs_of_cruise(cruise):
        ctx = L.context_lattice(pid); src = L.source_lattice(pid); reg = L.geo_region_for_context(ctx, src)
        lr = L.read_lr(pid); depth = float(np.nanmedian(np.abs(lr))) if np.isfinite(lr).any() else 1000.0
        reach = max(2000.0, 3.0 * depth)
        fwd = pyproj.Transformer.from_crs("EPSG:4326", ctx["crs"], always_xy=True).transform
        inv = pyproj.Transformer.from_crs(ctx["crs"], "EPSG:4326", always_xy=True).transform
        b = box(reg["w"], reg["s"], reg["e"], reg["n"]).segmentize(0.01)
        nav = shp_transform(inv, shp_transform(fwd, b).buffer(reach))
        boxes.append(b); navs.append(nav)
        per[pid] = {"region": {k: reg[k] for k in ("w", "s", "e", "n", "nx", "ny")}, "median_depth_m": depth, "nav_reach_m": reach}
    return {"pairs": per, "region_union": unary_union(boxes), "nav_union": unary_union(navs)}


def plan_subset(cruise: str, rec: dict, need: dict, workers: int = 6) -> dict:
    """List NCEI, fetch nav for files not on OAK, select files whose track intersects the nav polygon."""
    listing_cache = R.CACHE / "ncei_dirlist"; listing_cache.mkdir(parents=True, exist_ok=True)
    recs = iter_cruise_files(rec["data_url"], listing_cache)
    swath = [r for r in recs if r.kind == "swath"]; nav = {r.key: r for r in recs if r.kind == "nav"}
    if not swath:
        raise RuntimeError(f"{cruise}: NCEI listing at {rec['data_url']} has no swath files (listing cache {listing_cache})")
    on_oak = {p.name for p in swath_files(C.RAW_SWATH_OAK / cruise)}
    # ACQ-R04 collision-safe local names (same file name under several NCEI subdirectories)
    names = pd.Series([s.name for s in swath]); dup = names.duplicated(keep=False).tolist()
    local = [f"{s.url.rstrip('/').split('/')[-2]}__{s.name}" if d else s.name for s, d in zip(swath, dup)]
    missing = [(s, ln) for s, ln in zip(swath, local) if ln not in on_oak and s.name not in on_oak]
    cdir = R.NAVCACHE / cruise
    prefetch_nav([nav[s.key] for s, _ in missing if s.key in nav], cdir, workers=workers)
    poly = need["nav_union"]
    chosen, unknown, outside = [], [], []
    for s, ln in missing:
        nr = nav.get(s.key); p = cdir / nr.name if nr is not None else None
        track = parse_fnv_track(p) if p is not None and p.exists() and p.stat().st_size > 0 else None
        item = {"cruise": cruise, "filename": ln, "ncei_name": s.name, "url": s.url, "advertised": int(s.bytes), "kind": "swath"}
        if track is None:
            unknown.append(item)
        elif track.intersects(poly):
            chosen.append(item)
        else:
            outside.append(item["filename"])
    plan = {"cruise": cruise, "data_url": rec["data_url"], "n_files_ncei": len(swath), "bytes_ncei": int(sum(s.bytes for s in swath)),
            "n_on_oak": len(on_oak), "n_missing": len(missing), "n_track_intersects": len(chosen), "n_no_nav_track": len(unknown),
            "n_track_outside": len(outside), "bytes_track_intersects": int(sum(c["advertised"] for c in chosen)), "bytes_no_nav_track": int(sum(u["advertised"] for u in unknown)),
            "rule": "nav track (.fnv) intersects the union of the pairs' context mbgrid regions buffered by max(2 km, 3 x median depth); files with no nav track are included (conservative)",
            "to_fetch": chosen + unknown, "no_nav_track": [u["filename"] for u in unknown], "outside": outside, "name_collisions": sorted(set(names[dup]))}
    return plan


def fetch(cruise: str, plan: dict, workers: int = 6) -> dict:
    """Fetch the planned files to OAK (fetch_swath.fetch_one; destination common.RAW_SWATH_OAK, unchanged) and update the
    cruise's fetch manifest + SHA256SUMS (append; originals backed up)."""
    C.assert_no_lockbox_cruise([cruise])
    assert FS.C.RAW_SWATH_OAK == C.RAW_SWATH_OAK and str(C.RAW_SWATH_OAK).startswith("/oak/")
    d = C.RAW_SWATH_OAK / cruise
    items = plan["to_fetch"]
    if not items:
        return {"n_planned": 0, "n_ok": 0, "n_failed": 0, "bytes": 0, "wall_s": 0.0}
    for n in plan.get("name_collisions", []):
        if (d / n).exists():
            qd = d / "_quarantine_name_collision"; qd.mkdir(exist_ok=True); (d / n).rename(qd / n)
            log.warning("[%s] %s: ambiguous plain-named copy quarantined", cruise, n)
    t0 = time.time()
    sessions = [requests.Session() for _ in range(workers)]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(lambda ip: FS.fetch_one({k: ip[1][k] for k in ("cruise", "filename", "url", "advertised", "kind")}, sessions[ip[0] % workers]), enumerate(items)))
    df = pd.DataFrame(res); ok = df[df.status.isin(_OK)]; bad = df[~df.status.isin(_OK)]
    # manifest update (append-only; keep originals)
    mp, sp = d / "fetch_manifest.json", d / "SHA256SUMS"
    for p in (mp, sp):
        bk = p.with_name(p.name + "." + BACKUP_TAG)
        if p.exists() and not bk.exists():
            shutil.copyfile(p, bk); R.chmod_ro(bk)
    man = json.loads(mp.read_text())
    have = {f.get("filename") or f.get("name") for f in man["files"]}
    added = [{"filename": r.filename, "url": r.url, "size": int(r.received), "sha256": r.sha256, "acq_r05": "context fetch 2026-10-09 (nav-track ∩ context extent)"}
             for r in ok.itertuples() if r.filename not in have and r.sha256]
    man["files"] = man["files"] + added
    man.setdefault("acq_r05_context_fetch", []).append({"at": R.utc_now(), "n_planned": len(items), "n_ok": int(len(ok)), "n_failed": int(len(bad)), "n_added": len(added),
                                                        "failed": bad[["filename", "url", "status", "http_status"]].to_dict("records"), "plan": str(SRC_DIR / f"{cruise}_fetch_plan.json")})
    man["n_files_ok"] = len(man["files"]); man["n_files_failed"] = int(len(bad))
    R.write_json(mp, man)
    if sp.exists():
        sp.chmod(0o644)
    with sp.open("a") as f:
        for a in added:
            f.write(f"{a['sha256']}  {a['filename']}\n")
    R.chmod_ro(sp)
    rec = {"n_planned": len(items), "n_ok": int(len(ok)), "n_failed": int(len(bad)), "n_added_to_manifest": len(added), "bytes": int(ok.received.sum()),
           "wall_s": round(time.time() - t0, 1), "status_counts": df.status.value_counts().to_dict(), "workers": workers,
           "failed": bad[["filename", "url", "status", "http_status"]].to_dict("records")}
    df.to_csv(SRC_DIR / f"{cruise}_fetch_log.csv", index=False)
    return rec


def coverage(cruise: str, wd: Path) -> dict:
    """ACQ-R04 coverage pass over every swath file of the cruise on OAK -> per-file sounding cells."""
    raw = C.RAW_SWATH_OAK / cruise
    files = swath_files(raw); names = [p.name for p in files]
    fmt = fmt_for(names[0])
    mixed = sorted({fmt_for(n) for n in names})
    if len(mixed) > 1:
        raise RuntimeError(f"{cruise}: mixed MB formats {mixed}")
    wd.mkdir(parents=True, exist_ok=True)
    t = time.time(); loc = B4.decompress(raw, names, wd, workers=4); dec_s = time.time() - t
    gz_of = dict(zip(loc, names))
    t = time.time(); cov, cmds = B4.coverage_pass(wd, loc, fmt); cov_s = time.time() - t
    per = {}
    for ln, f in cov.files.items():
        per[gz_of.get(ln, ln)] = {"n": int(f["n"]), "bounds": f.get("bounds"), "polar": int(f.get("polar", 0)),
                                  "cells": sorted(int(c) for c in f.get("cells", set()))}
    rec = {"cruise": cruise, "mb_format": fmt, "n_files": len(names), "soundings": int(sum(f["n"] for f in per.values())),
           "files_without_soundings": sorted(n for n, f in per.items() if f["n"] == 0),
           "unreadable_files": [{**u, "file": gz_of.get(u["file"], u["file"])} for u in cov.unreadable],
           "unparsed_lines_dropped": int(cov.unparsed), "polar_soundings_dropped": int(cov.polar),
           "decompress_s": round(dec_s, 1), "coverage_s": round(cov_s, 1), "commands": cmds, "files": per, "generated": R.utc_now(), "code_commit": R.git_commit()}
    return rec


def cells_of_region(w, s, e, n):
    lon_r = range(int(math.floor(w * 10)), int(math.floor(e * 10)) + 1); lat_r = range(int(math.floor(s * 10)), int(math.floor(n * 10)) + 1)
    return {ix * 10000 + iy for ix in lon_r for iy in lat_r}


def select_files(cov: dict, region: dict) -> list[str]:
    """Files with a sounding in a 0.1-degree cell the mbgrid region touches (exact superset; ACQ-R04 files_for_block rule)."""
    want = cells_of_region(region["w"], region["s"], region["e"], region["n"])
    return sorted(n for n, f in cov["files"].items() if f["n"] > 0 and not want.isdisjoint(f["cells"]))


def load_coverage(cruise: str) -> dict:
    p = SRC_DIR / f"{cruise}_coverage.json"
    if not p.exists():
        raise FileNotFoundError(f"{p}: run `python -m src.acq_r05.sources --cruise {cruise}` first")
    return json.loads(p.read_text())


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cruise", required=True); ap.add_argument("--plan-only", action="store_true"); ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--skip-coverage", action="store_true"); ap.add_argument("--force-coverage", action="store_true")
    a = ap.parse_args(argv)
    if a.workers > 6:
        raise SystemExit("NCEI etiquette: <= 6 workers")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    cruise = a.cruise; t0 = time.time()
    rec = cruise_record(cruise); rec["pairs"] = pairs_of_cruise(cruise); rec["started"] = R.utc_now(); rec["host"] = os.uname().nodename
    need = needed_region_4326(cruise)
    rec["need"] = {"pairs": need["pairs"], "region_union_bounds": list(need["region_union"].bounds), "nav_union_bounds": list(need["nav_union"].bounds)}
    if rec["is_subset"]:
        plan = plan_subset(cruise, rec, need, a.workers)
        R.write_json(SRC_DIR / f"{cruise}_fetch_plan.json", {**plan, "generated": R.utc_now()}, mode=0o644)
        rec["plan"] = {k: v for k, v in plan.items() if k not in ("to_fetch", "outside", "no_nav_track")}
        log.info("[%s] subset: %d NCEI files, %d on OAK, %d missing -> %d track-intersect (%.2f GB) + %d no-nav (%.2f GB), %d outside", cruise, plan["n_files_ncei"], plan["n_on_oak"],
                 plan["n_missing"], plan["n_track_intersects"], plan["bytes_track_intersects"] / 1e9, plan["n_no_nav_track"], plan["bytes_no_nav_track"] / 1e9, plan["n_track_outside"])
        if not a.plan_only:
            rec["fetch"] = fetch(cruise, plan, a.workers)
            if rec["fetch"]["n_failed"]:
                log.error("[%s] %d fetch failures: %s", cruise, rec["fetch"]["n_failed"], rec["fetch"]["failed"][:5])
    else:
        rec["plan"] = {"note": "whole cruise on OAK; nothing to fetch"}
    if not a.plan_only and not a.skip_coverage:
        cp = SRC_DIR / f"{cruise}_coverage.json"
        if cp.exists() and not a.force_coverage and rec.get("fetch", {}).get("n_ok", 0) == 0 and json.loads(cp.read_text())["n_files"] == rec["n_files_on_oak"]:
            rec["coverage"] = {"note": "reused existing coverage (file set unchanged)"}
        else:
            wd = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r05_sources" / cruise
            cov = coverage(cruise, wd)
            R.write_json(cp, cov, mode=0o644)
            rec["coverage"] = {k: v for k, v in cov.items() if k not in ("files", "commands")}
            shutil.rmtree(wd, ignore_errors=True)
        cov = json.loads((SRC_DIR / f"{cruise}_coverage.json").read_text())
        rec["selection"] = {pid: {"n_files": len(select_files(cov, need["pairs"][pid]["region"]))} for pid in rec["pairs"]}
    rec["wall_s"] = round(time.time() - t0, 1); rec["finished"] = R.utc_now(); rec["code_commit"] = R.git_commit()
    R.write_json(SRC_DIR / f"{cruise}_sources.json", rec, mode=0o644)
    print(json.dumps({k: v for k, v in rec.items() if k != "need"}, indent=1, default=str))
    return 1 if rec.get("fetch", {}).get("n_failed") else 0


if __name__ == "__main__":
    sys.exit(main())
