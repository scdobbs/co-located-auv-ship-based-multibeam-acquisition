"""ACQ-R03 §1.2, M112/1 (PANGAEA 892317): per-file positions and the footprint selection.

The 892317 tab export carries no per-file geometry.  Method order (directive §1.2):
  1. M112 underway navigation on PANGAEA — searched (ES full text: "Master tracks" AND M112, DSHIP AND M112,
     M112 AND (navigation OR track ...)): no M112 master-track / DSHIP dataset exists (only photomosaics,
     the M112/POS499 grids, an MSM112 ADCP set and POS515 seismic).  Not available.
  2. `hs.pangaea.de` honours HTTP Range (tested 2026-09-30: 206 Partial Content).  Read the first 2 MB of
     each `.all` file (one Range request, verbatim file URL from the tab export) and take its start position
     from the position datagrams with MB-System (`mbnavlist`, fallback `mbinfo`).  A file spans
     [its start, the next file's start) in file-name time order; the segment start_i -> start_{i+1} is tested
     against the HR footprint buffered by 4 km.
Resumable: positions are appended to pangaea_892317_positions.csv and finished files are skipped.
Usage (job): python -m src.acq_r03.m112_positions [--throttle 0.5]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
from shapely.geometry import LineString, Point
from shapely.ops import transform as shp_transform

from src.acq_r03 import common as R
from src.acq_r03.pangaea_select import publish

CRUISE = "PANGAEA_892317"
HEAD_BYTES = 2 * 1024 * 1024
NAV_SEARCH = ['"Master tracks" AND M112', '"master track" AND METEOR AND M112', 'DSHIP AND M112',
              '"M112" AND (navigation OR track OR DSHIP OR underway OR "master track")']


class Pacer:
    """Adaptive request pacing for hs.pangaea.de: the host rate-limits small requests with 503s. Start at 3 s between
    requests; every 503 adds 3 s (cap 30 s); 20 consecutive successes remove 1 s (floor 3 s)."""
    def __init__(self, base=3.0, floor=3.0, cap=30.0):
        self.wait, self.floor, self.cap, self.ok = base, floor, cap, 0
        self.n_503 = 0

    def success(self):
        self.ok += 1
        if self.ok >= 20:
            self.wait = max(self.floor, self.wait - 1.0); self.ok = 0

    def throttled(self):
        self.n_503 += 1; self.ok = 0; self.wait = min(self.cap, self.wait + 3.0)


def fetch_head(url: str, name: str, work: Path, sess: requests.Session, pacer: Pacer) -> dict:
    """First 2 MB of the file (one Range request, verbatim URL) -> work/<name>.  On 503 the file is left for a later
    pass (status 503, head_bytes 0) after a single 30 s pause, so one slow file cannot stall the queue."""
    local = work / name
    rec = {"file_name": name, "http_status": None, "head_bytes": 0, "note": ""}
    if local.exists() and local.stat().st_size >= HEAD_BYTES:
        rec.update({"http_status": "cached", "head_bytes": local.stat().st_size}); return rec
    for attempt in range(2):
        try:
            time.sleep(pacer.wait)
            with sess.get(url, headers={**R.HEADERS, "Range": f"bytes=0-{HEAD_BYTES - 1}"}, timeout=180, stream=True) as g:
                rec["http_status"] = g.status_code
                if g.status_code in (429, 503) or g.status_code >= 500:
                    pacer.throttled(); time.sleep(30.0); continue
                if g.status_code not in (200, 206):
                    rec["note"] = f"http {g.status_code}"; return rec
                n = 0
                with local.open("wb") as fh:
                    for ch in g.iter_content(1 << 18):
                        fh.write(ch); n += len(ch)
                        if n >= HEAD_BYTES:
                            break
                rec["head_bytes"] = n
                if g.status_code == 200:
                    rec["note"] = "server ignored Range (full body, truncated locally)"
            pacer.success(); return rec
        except Exception as e:
            rec["note"] = f"{type(e).__name__}"; time.sleep(10.0)
    return rec


def positions_batch(work: Path, names: list[str]) -> dict:
    """ONE container invocation (apptainer start-up is ~30-60 s on Sherlock nodes) running mbnavlist over every head;
    files without navigation get one batched mbinfo pass.  Returns name -> position record."""
    out = {}
    lst = work / "heads.lst"; lst.write_text("".join(n + "\n" for n in names))
    script = 'while read f; do echo "## $f"; mbnavlist -F58 -I "$f" -OXY 2>/dev/null; done < heads.lst'
    r = R.C.mb(["sh", "-c", script], cwd=str(work), timeout=6 * 3600)
    cur = None; pts = {}
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("## "):
            cur = ln[3:].strip(); pts[cur] = []; continue
        p = ln.split()
        if cur and len(p) >= 2:
            try:
                lo, la = float(p[0]), float(p[1])
            except ValueError:
                continue
            if abs(lo) <= 180 and abs(la) <= 90 and (lo, la) != (0.0, 0.0):
                pts[cur].append((lo, la))
    for n in names:
        q = pts.get(n, [])
        if q:
            out[n] = {"lon": q[0][0], "lat": q[0][1], "n_nav": len(q), "method": "mbnavlist -OXY (position datagrams)",
                      "lon_min": min(a for a, _ in q), "lon_max": max(a for a, _ in q), "lat_min": min(b for _, b in q), "lat_max": max(b for _, b in q)}
    missing = [n for n in names if n not in out]
    if missing:
        lst.write_text("".join(n + "\n" for n in missing))
        script = 'while read f; do echo "## $f"; mbinfo -F58 -I "$f" 2>/dev/null | grep -E "Minimum (Longitude|Latitude)"; done < heads.lst'
        r = R.C.mb(["sh", "-c", script], cwd=str(work), timeout=3600)
        cur = None; buf = {}
        for ln in (r.stdout or "").splitlines():
            if ln.startswith("## "):
                cur = ln[3:].strip(); buf[cur] = ""; continue
            if cur:
                buf[cur] += ln + "\n"
        for n in missing:
            t = buf.get(n, "")
            mlo = re.search(r"Minimum Longitude:\s+([-\d.]+)\s+Maximum Longitude:\s+([-\d.]+)", t)
            mla = re.search(r"Minimum Latitude:\s+([-\d.]+)\s+Maximum Latitude:\s+([-\d.]+)", t)
            if mlo and mla:
                out[n] = {"lon": (float(mlo.group(1)) + float(mlo.group(2))) / 2, "lat": (float(mla.group(1)) + float(mla.group(2))) / 2, "n_nav": 0,
                          "lon_min": float(mlo.group(1)), "lon_max": float(mlo.group(2)), "lat_min": float(mla.group(1)), "lat_max": float(mla.group(2)),
                          "method": "mbinfo bbox of the 2 MB head (fallback)"}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--throttle", type=float, default=0.5, help="(unused: pacing is adaptive)"); ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--budget-hours", type=float, default=20.0)
    a = ap.parse_args(argv)
    info = R.PANGAEA_UNITS[CRUISE]
    cand = pd.read_csv(R.REPORT_DIR / f"pangaea_{info['dataset']}_all_candidates.csv", parse_dates=["start_time"]).sort_values("start_time").reset_index(drop=True)
    pos_csv = R.REPORT_DIR / f"pangaea_{info['dataset']}_positions.csv"
    done = {}
    if pos_csv.exists():
        for r in csv.DictReader(pos_csv.open()):
            done[r["file_name"]] = r
    work = R.C.SCRATCH_DATA / "acq_r03_m112_heads"; work.mkdir(parents=True, exist_ok=True)   # group scratch: survives a restart
    sess = requests.Session(); t0 = time.time(); pacer = Pacer()
    fields = ["file_name", "http_status", "head_bytes", "lon", "lat", "n_nav", "lon_min", "lon_max", "lat_min", "lat_max", "method", "note"]
    todo = [r for _, r in cand.iterrows() if r.file_name not in done][: a.limit or None]
    heads = {}
    queue = list(todo); n_pass = 0
    while queue and (time.time() - t0) / 3600 < a.budget_hours:               # phase 1: all heads, re-queuing 503s
        n_pass += 1; nxt = []
        for k, r in enumerate(queue, 1):
            h = fetch_head(r.url, r.file_name, work, sess, pacer); heads[r.file_name] = h
            if h["head_bytes"] <= 0:
                nxt.append(r)
            if k % 50 == 0:
                print(f"  pass {n_pass}: {k}/{len(queue)} tried, {sum(1 for x in heads.values() if x['head_bytes'] > 0)}/{len(todo)} heads on disk, wait {pacer.wait:.0f} s, 503s {pacer.n_503}, {time.time() - t0:.0f} s", flush=True)
        queue = nxt
        if queue:
            print(f"  pass {n_pass} done: {len(queue)} heads still missing; pausing 120 s before the next pass", flush=True); time.sleep(120)
    unresolved = [r.file_name for r in queue]
    names = [n for n, h in heads.items() if h["head_bytes"] > 0]
    print(f"  {len(names)} heads on disk; one MB-System pass ...", flush=True)
    pos = positions_batch(work, names) if names else {}              # phase 2: one container, all files
    new_file = not pos_csv.exists()
    with pos_csv.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        if new_file:
            w.writeheader()
        for n, h in heads.items():
            rec = {**{f: None for f in fields}, **h, **pos.get(n, {})}
            if n not in pos:
                rec["note"] = (rec.get("note") or "") + "; no navigation parsed from the head"
            w.writerow(rec); done[n] = rec
    for n in names:
        try:
            (work / n).unlink()
        except OSError:
            pass
    print(f"  positions: {len(done)}/{len(cand)} known, {time.time() - t0:.0f} s", flush=True)
    if unresolved:
        print(f"HOLD: {len(unresolved)} files without a head after {n_pass} passes ({(time.time() - t0) / 3600:.1f} h); selection written for the resolved files only")
    if len(done) < len(cand):
        print(f"positions incomplete: {len(done)}/{len(cand)}"); return 1
    # selection: segment [start_i, start_{i+1}) against the buffered footprint, in local UTM
    poly, epsg, area_km2, buf_km2 = R.hr_footprint_buffered(info["hr"])
    import pyproj
    tr = pyproj.Transformer.from_crs("EPSG:4326", epsg, always_xy=True).transform
    pos = pd.DataFrame([done[n] for n in cand.file_name])
    for c in ("lon", "lat", "lon_min", "lon_max", "lat_min", "lat_max"):
        pos[c] = pd.to_numeric(pos[c], errors="coerce")
    sel, dist, meth = [], [], []
    for i in range(len(pos)):
        p0 = pos.iloc[i]
        if not (pd.notna(p0.lon) and pd.notna(p0.lat)):
            sel.append(False); dist.append(None); meth.append("no_position"); continue
        nxt = None
        for j in range(i + 1, len(pos)):
            if pd.notna(pos.iloc[j].lon) and pd.notna(pos.iloc[j].lat):
                nxt = pos.iloc[j]; break
        pts = [(p0.lon, p0.lat)]
        if pd.notna(p0.lon_min):
            pts += [(p0.lon_min, p0.lat_min), (p0.lon_max, p0.lat_max)]   # the head's own nav extent
        if nxt is not None:
            pts.append((nxt.lon, nxt.lat)); meth.append("segment start_i -> start_i+1")
        else:
            meth.append("last file: head nav only")
        g = LineString([(p0.lon, p0.lat)] + ([(nxt.lon, nxt.lat)] if nxt is not None else [(p0.lon, p0.lat)])) if nxt is not None else Point(p0.lon, p0.lat)
        g = shp_transform(tr, g)
        d = float(g.distance(poly))
        sel.append(bool(d == 0.0)); dist.append(round(d, 1))
    out = cand.merge(pos, on="file_name", how="left")
    out["selected"] = sel; out["min_dist_to_buffered_footprint_m"] = dist; out["geometry_method"] = meth
    note = {"hr": info["hr"], "utm": epsg, "hr_footprint_km2": round(area_km2, 3), "buffered_km2": round(buf_km2, 3), "buffer_m": R.BUFFER_M,
            "method": "2: HTTP Range 2 MB head per .all -> first position datagram (mbnavlist); file spans [start_i, start_i+1); segment ∩ buffered footprint",
            "method_1_navigation_dataset": {"result": "not available: no M112 master-track / DSHIP / navigation dataset on PANGAEA", "queries": NAV_SEARCH},
            "range_test": "hs.pangaea.de answered 206 Partial Content to Range: bytes=0-1048575 (2026-09-30)",
            "n_positions_parsed": int(pos.lon.notna().sum()), "n_no_position": int(pos.lon.isna().sum()), "unresolved_heads": unresolved,
            "pacing": {"final_wait_s": pacer.wait, "n_503": pacer.n_503, "passes": n_pass},
            "position_methods": pos.method.fillna("none").value_counts().to_dict()}
    summ = publish(CRUISE, out, info, note, [], len(cand), int(cand.advertised_bytes.sum()))
    print(json.dumps({k: v for k, v in summ.items() if k != "rows_skipped_url_name_mismatch"}, indent=1, default=str))
    return 2 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
