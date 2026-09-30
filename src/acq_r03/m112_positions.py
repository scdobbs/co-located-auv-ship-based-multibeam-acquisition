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


def head_positions(url: str, name: str, work: Path, sess: requests.Session, throttle: float) -> dict:
    """First 2 MB of the file -> (lon, lat) of the first position datagram, plus the head's nav bbox."""
    local = work / name
    rec = {"file_name": name, "http_status": None, "head_bytes": 0, "lon": None, "lat": None, "n_nav": 0,
           "lon_min": None, "lon_max": None, "lat_min": None, "lat_max": None, "method": None, "note": ""}
    for attempt in range(6):
        try:
            with sess.get(url, headers={**R.HEADERS, "Range": f"bytes=0-{HEAD_BYTES - 1}"}, timeout=180, stream=True) as g:
                rec["http_status"] = g.status_code
                if g.status_code in (429, 503) or g.status_code >= 500:
                    time.sleep(min(120, 5 * 2 ** attempt)); continue
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
            break
        except Exception as e:
            rec["note"] = f"{type(e).__name__}"; time.sleep(min(60, 2 ** attempt))
    else:
        rec["note"] += "; gave up"; return rec
    r = R.C.mb(["mbnavlist", "-F58", "-I", local.name, "-OXY"], cwd=str(work))
    pts = []
    for ln in (r.stdout or "").splitlines():
        p = ln.split()
        if len(p) >= 2:
            try:
                lo, la = float(p[0]), float(p[1])
            except ValueError:
                continue
            if abs(lo) <= 180 and abs(la) <= 90 and (lo, la) != (0.0, 0.0):
                pts.append((lo, la))
    if pts:
        rec.update({"lon": pts[0][0], "lat": pts[0][1], "n_nav": len(pts), "method": "mbnavlist -OXY (position datagrams)",
                    "lon_min": min(p[0] for p in pts), "lon_max": max(p[0] for p in pts), "lat_min": min(p[1] for p in pts), "lat_max": max(p[1] for p in pts)})
    else:
        r2 = R.C.mb(["mbinfo", "-F58", "-I", local.name], cwd=str(work))
        out = r2.stdout or ""
        mlo = re.search(r"Minimum Longitude:\s+([-\d.]+)\s+Maximum Longitude:\s+([-\d.]+)", out)
        mla = re.search(r"Minimum Latitude:\s+([-\d.]+)\s+Maximum Latitude:\s+([-\d.]+)", out)
        if mlo and mla:
            rec.update({"lon": (float(mlo.group(1)) + float(mlo.group(2))) / 2, "lat": (float(mla.group(1)) + float(mla.group(2))) / 2,
                        "lon_min": float(mlo.group(1)), "lon_max": float(mlo.group(2)), "lat_min": float(mla.group(1)), "lat_max": float(mla.group(2)),
                        "method": "mbinfo bbox of the 2 MB head (fallback)"})
        else:
            rec["note"] += "; no navigation parsed from the head"
    try:
        local.unlink()
    except OSError:
        pass
    time.sleep(throttle)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--throttle", type=float, default=0.5); ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(argv)
    info = R.PANGAEA_UNITS[CRUISE]
    cand = pd.read_csv(R.REPORT_DIR / f"pangaea_{info['dataset']}_all_candidates.csv", parse_dates=["start_time"]).sort_values("start_time").reset_index(drop=True)
    pos_csv = R.REPORT_DIR / f"pangaea_{info['dataset']}_positions.csv"
    done = {}
    if pos_csv.exists():
        for r in csv.DictReader(pos_csv.open()):
            done[r["file_name"]] = r
    work = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r03_m112_heads"; work.mkdir(parents=True, exist_ok=True)
    sess = requests.Session(); t0 = time.time(); n_new = 0
    fields = ["file_name", "http_status", "head_bytes", "lon", "lat", "n_nav", "lon_min", "lon_max", "lat_min", "lat_max", "method", "note"]
    new_file = not pos_csv.exists()
    with pos_csv.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        if new_file:
            w.writeheader()
        for i, r in cand.iterrows():
            if r.file_name in done:
                continue
            if a.limit and n_new >= a.limit:
                break
            rec = head_positions(r.url, r.file_name, work, sess, a.throttle)
            w.writerow(rec); fh.flush(); done[r.file_name] = rec; n_new += 1
            if n_new % 50 == 0:
                print(f"  {n_new} heads read, {len(done)}/{len(cand)} known, {time.time() - t0:.0f} s", flush=True)
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
            "n_positions_parsed": int(pos.lon.notna().sum()), "n_no_position": int(pos.lon.isna().sum()),
            "position_methods": pos.method.fillna("none").value_counts().to_dict()}
    summ = publish(CRUISE, out, info, note, [], len(cand), int(cand.advertised_bytes.sum()))
    print(json.dumps({k: v for k, v in summ.items() if k != "rows_skipped_url_name_mismatch"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
