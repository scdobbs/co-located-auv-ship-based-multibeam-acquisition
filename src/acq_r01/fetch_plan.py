"""ACQ-R02 §6.1 — per-candidate LR fetch plan (files, mode, volume) and the 500 GB cap check.

For every verified candidate (verification/candidates_verified.csv, status == verified) and its
best real-overlap LR cruise:
  * NCEI cruise: Geoportal ISO -> data directory -> autoindex listing (stage A/B machinery, cached).
    Whole cruise if < 10 GB; else nav-subset exactly as stage A.5: fetch every swath file's .fnv,
    keep files whose track intersects the HR footprint buffered by max(2 x depth, 1 km).
    No recognised swath file (legacy SeaBeam-classic etc.) -> needs_format_review (dropped, recorded).
  * PANGAEA raw dataset: the dataset's tab export (per-file position, size, URL); whole if < 10 GB,
    else files whose start position lies within 40 km of the buffered HR footprint.
Outputs: reports_post_grl_review/ACQ-R02/fetch_plan/{file_plan.csv, cruise_plan.csv, fetch_plan.md}
The plan is NOT executed here.  Cumulative volume > 500 GB -> the plan is a HOLD.
"""
from __future__ import annotations

import io
import json
import logging
import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import Point
from shapely.ops import unary_union

from src.acq_r01 import common as C
from src.discovery.raw_lr_dryrun import data_dir_from_iso, resolve_data_dir
from src.discovery.stage_a5_subset import iter_cruise_files, prefetch_nav, parse_fnv_track, buffer_4326
from src.discovery.geoportal import _GEOPORTAL_BASE

log = logging.getLogger("acq_r02.plan")
R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"
OUT = R02 / "fetch_plan"
CACHE = C.SCRATCH_DATA / "discovery_cache" / "acq_r02_fetch"
H = {"User-Agent": "auv-ship-acq/0.4 (Sherlock; ACQ-R02 fetch plan; stephencoledobbs@gmail.com)"}
CAP_GB = 500.0
WHOLE_GB = 10.0
PANGAEA_SUBSET_KM = 40.0


def geoportal_iso(cruise: str) -> str | None:
    d = CACHE / "geoportal"; d.mkdir(parents=True, exist_ok=True)
    p = d / f"{cruise}.json"
    if not p.exists():
        try:
            r = requests.get(_GEOPORTAL_BASE + cruise + "_Multibeam", params={"f": "json"}, headers=H, timeout=60)
            p.write_text(json.dumps(r.json() if r.status_code == 200 else {"_status": r.status_code}))
        except Exception as e:
            p.write_text(json.dumps({"_error": str(e)[:100]}))
    return data_dir_from_iso(cruise, d)


def plan_ncei(cruise: str, hr_geoms: list, depth_m: float) -> tuple[list[dict], dict]:
    iso = geoportal_iso(cruise)
    url, note = resolve_data_dir(iso, CACHE / "dirlist") if iso else (None, "no ISO data dir")
    if not url:
        return [], {"cruise": cruise, "status": "no_data_dir", "note": note}
    recs = iter_cruise_files(url, CACHE / "dirlist")
    swath = [r for r in recs if r.kind == "swath"]
    nav = {r.key: r for r in recs if r.kind == "nav"}
    if not swath:
        exts = pd.Series([r.name.rsplit(".", 1)[-1] for r in recs if r.kind != "nav"]).value_counts().head(5).to_dict()
        return [], {"cruise": cruise, "status": "needs_format_review", "note": f"no recognised swath files; exts {exts}", "data_url": url}
    whole_gb = sum(r.bytes for r in swath) / 1e9
    fmt = pd.Series([r.name.split(".")[-2] if r.name.endswith(".gz") else r.name.split(".")[-1] for r in swath]).value_counts().index[0]
    if whole_gb < WHOLE_GB:
        chosen, mode = swath, "whole"
    else:
        fp_union = unary_union(hr_geoms)
        buf, buf_km = buffer_4326(fp_union, depth_m)
        cdir = CACHE / "nav" / cruise
        prefetch_nav([nav[s.key] for s in swath if s.key in nav], cdir, workers=6)
        chosen = []
        for s in swath:
            nr = nav.get(s.key); track = parse_fnv_track(cdir / nr.name) if nr is not None and (cdir / nr.name).exists() else None
            if track is None or track.intersects(buf):
                chosen.append(s)
        mode = f"subset (nav ∩ footprint buffered {buf_km:.1f} km)"
    plan = [{"cruise": cruise, "filename": s.name, "url": s.url, "advertised": s.bytes, "kind": "swath", "mode": mode} for s in chosen]
    return plan, {"cruise": cruise, "status": "planned", "source": "NCEI", "data_url": url, "n_files_total": len(swath), "n_files_planned": len(chosen),
                  "whole_gb": round(whole_gb, 2), "planned_gb": round(sum(s.bytes for s in chosen) / 1e9, 2), "mode": mode, "format_hint": fmt, "note": note}


def plan_pangaea(dataset_id: str, hr_geoms: list, depth_m: float) -> tuple[list[dict], dict]:
    r = requests.get(f"https://doi.pangaea.de/10.1594/PANGAEA.{dataset_id}?format=textfile", headers=H, timeout=120)
    lines = r.text.splitlines()
    try:
        s = [i for i, l in enumerate(lines) if l.startswith("*/")][0] + 1
    except IndexError:
        return [], {"cruise": f"PANGAEA:{dataset_id}", "status": "no_file_table", "note": r.text[:100]}
    df = pd.read_csv(io.StringIO("\n".join(lines[s:])), sep="\t")
    ucol = next((c for c in df.columns if "URL raw" in c), None) or next((c for c in df.columns if "URL" in c), None)
    if ucol is None:
        return [], {"cruise": f"PANGAEA:{dataset_id}", "status": "no_raw_urls", "note": str(list(df.columns))[:150]}
    df = df[df[ucol].notna()]
    size = (df["File size [kByte]"] * 1024).round().astype("int64") if "File size [kByte]" in df else pd.Series([0] * len(df))
    whole_gb = float(size.sum()) / 1e9
    if whole_gb < WHOLE_GB or not {"Latitude", "Longitude"} <= set(df.columns):
        keep = np.ones(len(df), bool); mode = "whole" if whole_gb < WHOLE_GB else "whole (no per-file position)"
    else:
        fp_union = unary_union(hr_geoms); buf, buf_km = buffer_4326(fp_union, depth_m)
        c = buf.centroid
        keep = np.array([hav_km_pt(lo, la, c.x, c.y) <= PANGAEA_SUBSET_KM + buf_km for lo, la in zip(df.Longitude, df.Latitude)])
        mode = f"subset (file start within {PANGAEA_SUBSET_KM:.0f} km + buffer of footprint)"
    sub = df[keep]
    plan = [{"cruise": f"PANGAEA_{dataset_id}", "filename": u.rsplit("/", 1)[-1], "url": u, "advertised": int(b), "kind": "swath", "mode": mode}
            for u, b in zip(sub[ucol], size[keep])]
    return plan, {"cruise": f"PANGAEA_{dataset_id}", "status": "planned", "source": "PANGAEA", "n_files_total": int(len(df)), "n_files_planned": int(len(sub)),
                  "whole_gb": round(whole_gb, 2), "planned_gb": round(float(size[keep].sum()) / 1e9, 2), "mode": mode, "format_hint": str(df["File format"].iloc[0]) if "File format" in df else ""}


def hav_km_pt(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(math.radians, (lon1, lat1, lon2, lat2))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    v = pd.read_csv(R02 / "verification" / "candidates_verified.csv")
    v = v[v.status == "verified"]
    fps = gpd.read_file(R02 / "verification" / "hr_footprints.gpkg").set_index("hr_id")
    ua = json.loads((R02 / "verification" / "units_after.json").read_text())
    desig = {}
    for u in ua["units"]:
        desig.update(u["designations"])
    v = v[[not str(desig.get(h, "")).startswith("dropped") for h in v.hr_id]]
    already = {p.name for p in C.RAW_SWATH_OAK.iterdir() if p.is_dir()} if C.RAW_SWATH_OAK.exists() else set()
    plans, cruises = [], []
    for cr, g in v.groupby("lr_best_real"):
        geoms = [fps.loc[h].geometry for h in g.hr_id if h in fps.index]
        depth = float(np.nanmean([abs(x) for x in pd.concat([g.get("depth_max_m", pd.Series(dtype=float))]).dropna()])) if "depth_max_m" in g else float("nan")
        if not math.isfinite(depth):
            depth = 2000.0
        if str(cr) in already or str(cr).replace("PANGAEA:", "PANGAEA_") in already:
            cruises.append({"cruise": cr, "status": "already_on_oak", "hr": ";".join(g.hr_id), "planned_gb": 0.0}); continue
        try:
            if str(cr).startswith("PANGAEA:"):
                p, s = plan_pangaea(str(cr).split(":")[1], geoms, depth)
            else:
                p, s = plan_ncei(str(cr), geoms, depth)
        except Exception as e:
            p, s = [], {"cruise": cr, "status": f"error:{type(e).__name__}", "note": str(e)[:120]}
        s["hr"] = ";".join(g.hr_id); s["designations"] = ";".join(sorted({str(desig.get(h, "")) for h in g.hr_id}))
        plans += p; cruises.append(s)
        log.info("%s: %s", cr, s)
    fp = pd.DataFrame(plans); cp = pd.DataFrame(cruises)
    fp.to_csv(OUT / "file_plan.csv", index=False); cp.to_csv(OUT / "cruise_plan.csv", index=False)
    total = float(fp.advertised.sum()) / 1e9 if len(fp) else 0.0
    summary = {"n_cruises": int(len(cp)), "n_planned": int((cp.status == "planned").sum()), "needs_format_review": cp[cp.status == "needs_format_review"].cruise.tolist(),
               "failed": cp[cp.status.str.startswith(("error", "no_"))].cruise.tolist(), "total_gb": round(total, 2), "cap_gb": CAP_GB, "within_cap": total <= CAP_GB,
               "n_files": int(len(fp))}
    C.write_json(OUT / "fetch_plan_summary.json", summary)
    md = ["# Fetch plan (ACQ-R02 §6.1)\n", json.dumps(summary, indent=1), "", "| LR cruise | source | status | HR served | designations | files total → planned | whole GB | planned GB | mode | note |", "|---|---|---|---|---|---|---|---|---|---|"]
    md += [f"| {r.cruise} | {r.get('source', '')} | {r.status} | {r.get('hr', '')} | {r.get('designations', '')} | {r.get('n_files_total', '')} → {r.get('n_files_planned', '')} | {r.get('whole_gb', '')} | {r.get('planned_gb', '')} | {r.get('mode', '')} | {str(r.get('note', ''))[:80]} |" for _, r in cp.iterrows()]
    (OUT / "fetch_plan.md").write_text("\n".join(md)); print("\n".join(md))
    return 0 if summary["within_cap"] else 3


if __name__ == "__main__":
    sys.exit(main())
