"""ACQ-R04 §4.1 — exclusion recomputed a second way, at block level, from the persisted outputs only.

Different route from exclusion.py (§1, local-AEQD polygon distances) and blocks.Guard (§3.3, UTM polygon distances):
  * HR footprints are re-read from their SOURCE files (OAK footprint.geojson per manifest-v2.1 / dropped row,
    ACQ-R02 hr_footprints.gpkg for confirmatory rows and every other gpkg polygon, the NCEI footprints of the lockbox
    LR cruises, the lockbox centroids from leakage_assignment.csv) — not from exclusion_geometries_v1.geojson;
  * for every block of the corpus manifest: its polygon vertices (4 corners, from block.json bounds and CRS) and its
    centroid, to every footprint polygon's VERTICES, geodesic distance on WGS84 (pyproj.Geod.inv); no shapely buffer.
    Thresholds: 10 km (HR footprints, lockbox LR cruise footprints), 50 km (lockbox centroids).  Vertex distances are
    >= the true polygon distance, so a block that the check passes can still be close to a long footprint edge; a
    containment test (block centroid inside a footprint polygon) is recorded alongside;
  * the block's cruise id against the shared-cruise list rebuilt from manifest v2.1 + the dropped list (LR cruise of
    every row, HR cruise id where recorded), normalised (case, '/', '-', '_', spaces).
Agreement with §3.3 = the check also keeps the block.  Disagreements -> exclusion_check_disagreements_v1.csv.
Usage: python -m src.acq_r04.check_exclusion --manifest pretrain_manifest_v1.parquet
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
from shapely import make_valid
from shapely.geometry import Point

from src.acq_r04 import common as R
from src.acq_r01 import common as C

GEOD = pyproj.Geod(ellps="WGS84")


def _norm(s):
    return re.sub(r"[\s/_\-]", "", str(s)).lower()


def footprint_vertices():
    """[(name, kind, threshold_m, lon array, lat array, polygon-or-None)] from the source files."""
    m = pd.read_parquet(R.MANIFEST_V21); d = pd.read_csv(R.DROPPED_V21)
    gp = gpd.read_file(R.R02 / "verification" / "hr_footprints.gpkg").set_index("hr_id")
    out = []

    def add(name, kind, geom, thr):
        geom = make_valid(geom)
        xs, ys = [], []
        for p in getattr(geom, "geoms", [geom]):
            if p.geom_type == "Polygon":
                for ring in [p.exterior, *p.interiors]:
                    x, y = ring.xy; xs += list(x); ys += list(y)
            elif p.geom_type == "Point":
                xs.append(p.x); ys.append(p.y)
            elif hasattr(p, "geoms"):
                for q in p.geoms:
                    if q.geom_type == "Polygon":
                        x, y = q.exterior.xy; xs += list(x); ys += list(y)
        out.append((name, kind, thr, np.asarray(xs), np.asarray(ys), geom if geom.geom_type != "Point" else None))

    for r in m.itertuples():
        des = str(r.designation)
        if r.pair_id in C.LOCKBOX or des == "lockbox":
            continue
        if des.startswith("confirmatory"):
            add(r.pair_id, "confirmatory_gpkg", gp.loc["MGDS:" + r.pair_id.split("__MGDS_")[1]].geometry, R.BUFFER_M); continue
        p = C.OAK / str(r.harmonized_path).split("/lrv2_1")[0] / "footprint.geojson"
        g = gpd.read_file(p); g = g.set_crs("EPSG:4326", allow_override=True) if g.crs is None else g.to_crs("EPSG:4326")
        add(r.pair_id, "oak_footprint", g.geometry.union_all(), R.BUFFER_M)
    for r in d.itertuples():
        g = gpd.read_file(C.OAK / r.harmonized_dir / "footprint.geojson")
        g = g.set_crs("EPSG:4326", allow_override=True) if g.crs is None else g.to_crs("EPSG:4326")
        add(r.pair_id, "oak_footprint_dropped", g.geometry.union_all(), R.BUFFER_M)
    for hid, row in gp.iterrows():
        add(hid, "gpkg", row.geometry, R.BUFFER_M)
    n = gpd.read_file(R.NCEI_FP)
    for lc in C.LOCKBOX_LR_CRUISES:
        add(f"lockbox_lr:{lc}", "lockbox_lr_ncei", n[n.SURVEY_ID == lc].geometry.union_all(), R.BUFFER_M)
    la = pd.read_csv(C.REPO / "reports" / "discovery" / "leakage_assignment.csv")
    for r in la[la.pair_id.isin(C.LOCKBOX)].itertuples():
        add(f"lockbox_centroid:{r.pair_id}", "lockbox_centroid", Point(r.centroid_lon, r.centroid_lat), R.LOCKBOX_RADIUS_M)
    return out, m, d


def shared_ids(m, d):
    s = {}
    for r in m.itertuples():
        for v, src in ((r.lr_cruise, "LR"), (r.cruise_id, "HR")):
            if v is not None and str(v) not in ("None", "nan", ""):
                s.setdefault(_norm(v), []).append(f"{src}:{r.pair_id}")
    cv = pd.read_csv(R.R02 / "verification" / "candidates_verified.csv").set_index("hr_id")
    for r in d.itertuples():
        s.setdefault(_norm(r.lr_cruise), []).append(f"LR(dropped):{r.pair_id}")
        mm = re.search(r"__MGDS_(\d+)$", r.pair_id)
        if mm and f"MGDS:{mm.group(1)}" in cv.index:
            h = cv.loc[f"MGDS:{mm.group(1)}"].hr_cruise_final
            if isinstance(h, str):
                s.setdefault(_norm(h), []).append(f"HR(dropped):{r.pair_id}")
    s.setdefault(_norm("M114/1"), []).append("LR(dropped):PANGAEA_864677 = M114/1")
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--manifest", default="pretrain_manifest_v1.parquet")
    ap.add_argument("--tag", default="v1")
    a = ap.parse_args(argv)
    man = pd.read_parquet(R.REPORT_DIR / a.manifest)
    fps, m, d = footprint_vertices()
    sid = shared_ids(m, d)
    # per-footprint prefilter radius, computed once: geodesic distance from its first vertex to its farthest vertex
    spans = []
    for name, kind, thr, fx, fy, poly in fps:
        sp = 0.0
        if fx.size > 1:
            _, _, dd = GEOD.inv(np.full(fx.size, fx[0]), np.full(fy.size, fy[0]), fx, fy); sp = float(np.max(dd))
        spans.append(sp)
    rows = []
    for k, r in enumerate(man.itertuples()):
        if k % 2000 == 0:
            print(f"{R.utc_now()} block {k}/{len(man)}", flush=True)
        bj = json.loads((R.STAGE / r.cruise.replace("/", "_") / r.block / "block.json").read_text())
        e0, n0, e1, n1 = bj["bounds_block_m"]
        inv = pyproj.Transformer.from_crs(bj["crs"], "EPSG:4326", always_xy=True)
        px = [e0, e1, e1, e0, (e0 + e1) / 2]; py = [n0, n0, n1, n1, (n0 + n1) / 2]
        lon, lat = inv.transform(px, py)
        lon, lat = np.asarray(lon), np.asarray(lat)
        best = (np.inf, None, None)                  # (margin, name, distance)
        contained = []
        for (name, kind, thr, fx, fy, poly), span in zip(fps, spans):
            # coarse pre-filter (triangle inequality): centroid -> first vertex distance minus the footprint's span
            _, _, d0 = GEOD.inv(lon[4], lat[4], fx[:1], fy[:1])
            if float(d0[0]) - span > thr + 50_000.0:
                continue
            LO = np.repeat(lon, fx.size); LA = np.repeat(lat, fx.size)
            _, _, dist = GEOD.inv(LO, LA, np.tile(fx, lon.size), np.tile(fy, lat.size))
            dmin = float(np.min(dist))
            if dmin - thr < best[0]:
                best = (dmin - thr, name, dmin)
            if poly is not None and poly.contains(Point(lon[4], lat[4])):
                contained.append(name)
        hit = sid.get(_norm(r.cruise), [])
        keep = (best[0] >= 0) and not contained and not hit
        rows.append({"cruise": r.cruise, "block": r.block, "s33_guard_margin_m": bj.get("guard_margin_m"), "s33_nearest": bj.get("guard_nearest"),
                     "check_nearest": best[1], "check_min_vertex_distance_m": None if best[2] is None else round(best[2], 1),
                     "check_margin_m": None if not np.isfinite(best[0]) else round(best[0], 1), "contained_in": ";".join(contained),
                     "shared_cruise_hit": ";".join(hit), "check_keep": keep, "s33_keep": True, "agree": keep})
    df = pd.DataFrame(rows)
    df.to_csv(R.REPORT_DIR / f"exclusion_check_{a.tag}.csv", index=False)
    dis = df[~df.agree] if len(df) else df
    dis.to_csv(R.REPORT_DIR / f"exclusion_check_disagreements_{a.tag}.csv", index=False)
    summ = {"generated": R.utc_now(), "manifest": a.manifest, "manifest_sha256": R.sha256_file(R.REPORT_DIR / a.manifest),
            "blocks_checked": int(len(df)), "agree": int(df.agree.sum()) if len(df) else 0, "disagree": int(len(dis)),
            "n_footprint_sources": len(fps), "n_shared_ids": len(sid),
            "min_check_margin_m": float(df.check_margin_m.min()) if len(df) and df.check_margin_m.notna().any() else None,
            "min_s33_margin_m": float(pd.to_numeric(df.s33_guard_margin_m, errors="coerce").min()) if len(df) else None,
            "blocks_with_no_footprint_within_prefilter": int(df.check_margin_m.isna().sum()) if len(df) else 0,
            "method": "pyproj.Geod(WGS84).inv, block corners + centroid to footprint vertices; centroid-in-polygon test; shared ids from manifest v2.1 + dropped",
            "code_commit": C.git_commit()}
    R.write_json(R.REPORT_DIR / f"exclusion_check_{a.tag}.json", summ)
    print(json.dumps(summ, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
