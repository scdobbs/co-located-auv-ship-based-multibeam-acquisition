"""ACQ-R04 §1 — exclusion set `exclusion_v1` and the remaining pool (cruise list; sizes come from pool_crawl.py).

Pool universe: every survey of the NCEI *Multibeam Footprints* layer (the ACQ-R01 §5 snapshot, cached on scratch;
raw per-cruise surveys only — the *Multibeam Products* layer is never queried).  The layer carries one record per
survey VERSION; a pool cruise is one SURVEY_ID (geometry = union of its version records).

Rules (a cruise is excluded if ANY holds; every rule that holds is recorded):
  1 shared_cruise  — survey id equals (after normalisation: case, '/', '-', '_', ' ' removed) any LR cruise of manifest
                     v2.1 or the dropped list, any recorded HR cruise of those rows, or any cruise of the ACQ-R02 §6/§7
                     acquisition table (report §7, acquisition_cruises.csv).
  2 spatial        — the NCEI footprint comes within the threshold of an HR footprint (10 km), of a lockbox LR cruise's
                     NCEI footprint (10 km), or of a lockbox centroid (50 km).  Distances are measured in a local
                     azimuthal-equidistant projection centred on each <= 2 deg piece of the exclusion geometry (scale
                     error < 1e-4 there); the cruise-level threshold adds the 0.01 deg simplification tolerance of the
                     cached NCEI footprints (1.113 km), see the report §1.
  3 composite      — not a raw per-cruise survey.  The pool is drawn from the raw-survey layer only (ACQ-R01 §5), so
                     nothing in it is a composite; recorded as 0 by construction, checked again in pool_crawl.py.
  4 non_ship       — AUV/ROV/towed/USV/... by the ACQ-R01 §5 platform/instrument filter.
HR footprints: development/no-k/dropped rows -> OAK harmonized footprint.geojson (gpkg polygon where absent);
confirmatory rows -> ACQ-R02 hr_footprints.gpkg polygons only; lockbox -> NCEI footprints of AT42-03 and TN159 + 50 km
around their leakage_assignment.csv centroids (no lockbox or confirmatory directory is opened).  Every other
hr_footprints.gpkg polygon (full-release footprints of ACQ-R02 pairs whose OAK footprint is the smaller HR∩LR overlap,
and HR outside manifest v2.1 / dropped: pu00, pu03, verification rejects) is added as 'extra_gpkg' (conservative;
counted separately).
Also re-runs the ACQ-R01 §5 exclusion verbatim (pretrain_scope.exclusion_geometry) to explain the difference by id.

Outputs: exclusion_v1.json, pool_ids_v1.csv (report dir); exclusion_geometries_v1.geojson (93 MB: scratch cache, sha256
in s1_hashes.json, persisted to OAK pretrain_v1/meta/).   Usage: python -m src.acq_r04.exclusion
"""
from __future__ import annotations

import json
import logging
import math
import re
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
from shapely import make_valid
from shapely.geometry import Point, box, mapping
from shapely.ops import transform as shp_transform, unary_union
from shapely.strtree import STRtree

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r01.pretrain_scope import NON_SHIP, family

log = logging.getLogger("acq_r04.exclusion")
SIMPLIFY_TOL_M = 0.01 * 111_320.0     # maxAllowableOffset of the cached NCEI footprints (ACQ-R01 fetch_all_footprints)
PIECE_DEG = 2.0


def norm_id(s) -> str:
    return re.sub(r"[\s/_\-]", "", str(s)).lower()


def pieces(geom):
    """Split a 4326 geometry into pieces no larger than PIECE_DEG x PIECE_DEG (the whole geometry is cut by a 2-deg
    grid, so a multi-part footprint with thousands of dive-patch parts stays a handful of pieces)."""
    if geom.is_empty:
        return []
    w, s, e, n = geom.bounds
    if e - w <= PIECE_DEG and n - s <= PIECE_DEG:
        return [geom]
    out = []
    for x in np.arange(math.floor(w), e, PIECE_DEG):
        for y in np.arange(math.floor(s), n, PIECE_DEG):
            q = geom.intersection(box(x, y, x + PIECE_DEG, y + PIECE_DEG))
            if not q.is_empty:
                out.append(q)
    return out


def _to_aeqd(lon0, lat0):
    t = pyproj.Transformer.from_crs("EPSG:4326", R.aeqd_crs(lon0, lat0), always_xy=True)
    return lambda g: shp_transform(t.transform, g)


def min_distances(excl_geom, thr_m, tree, part_geoms, part_owner):
    """{owner: min distance m} for every cruise part within thr_m (+ margin) of excl_geom."""
    res = {}
    for pc in pieces(excl_geom):
        c = pc.representative_point() if pc.geom_type != "Point" else pc
        lon0, lat0 = c.x, c.y
        f = _to_aeqd(lon0, lat0)
        pa = f(pc)
        reach = thr_m + 20_000.0
        dlat = reach / 111_320.0
        dlon = reach / (111_320.0 * max(0.05, math.cos(math.radians(min(89.0, max(abs(pc.bounds[1]), abs(pc.bounds[3])))))))
        w, s, e, n = pc.bounds
        win = box(w - dlon, max(-90, s - dlat), e + dlon, min(90, n + dlat))
        wins = [win]
        if win.bounds[0] < -180:
            wins.append(box(win.bounds[0] + 360, win.bounds[1], 180, win.bounds[3]))
        if win.bounds[2] > 180:
            wins.append(box(-180, win.bounds[1], win.bounds[2] - 360, win.bounds[3]))
        for wn in wins:
            for i in tree.query(wn):
                q = part_geoms[i].intersection(wn)
                if q.is_empty:
                    continue
                if wn is not win:      # shift the wrapped window back next to the piece
                    shift = 360.0 if wn.bounds[0] >= -180 and win.bounds[0] < -180 else -360.0
                    q = shp_transform(lambda x, y, z=None: (np.asarray(x) - shift, y), q)
                d = float(pa.distance(f(q)))
                o = part_owner[i]
                if d <= thr_m + 20_000.0 and d < res.get(o, float("inf")):
                    res[o] = d
    return res


def load_ncei():
    n = gpd.read_file(R.NCEI_FP)
    n["geometry"] = [make_valid(g) for g in n.geometry]
    n = n.sort_values(["SURVEY_ID", "Version"])
    rows = []
    for sid, g in n.groupby("SURVEY_ID", sort=True):
        last = g.iloc[-1]
        rows.append({"survey_id": sid, "n_records": len(g), "versions": ",".join(map(str, g.Version)),
                     "platform": last.PLATFORM, "instrument": last.INSTRUMENT, "source": last.SOURCE,
                     "year": last.SURVEY_YEAR, "ncei_id": last.NCEI_ID, "download_url": last.DOWNLOAD_URL,
                     "geometry": unary_union(list(g.geometry))})
    return gpd.GeoDataFrame(rows, crs="EPSG:4326"), len(n)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    hashes = R.check_fixed_inputs()
    m = pd.read_parquet(R.MANIFEST_V21)
    d = pd.read_csv(R.DROPPED_V21)
    cv = pd.read_csv(R.R02 / "verification" / "candidates_verified.csv")
    acq = pd.read_csv(R.R02 / "acquisition_cruises.csv")
    hrfp = gpd.read_file(R.R02 / "verification" / "hr_footprints.gpkg").set_index("hr_id")
    hrfp["geometry"] = [make_valid(g) for g in hrfp.geometry]
    la = pd.read_csv(C.REPO / "reports" / "discovery" / "leakage_assignment.csv")

    ncei, n_records = load_ncei()
    log.info("NCEI raw-survey layer: %d records, %d unique survey ids", n_records, len(ncei))

    # ---------------- rule 1: shared cruise ids ----------------
    ids = {}   # normalised id -> list of sources

    def add(i, src):
        if i is None or (isinstance(i, float) and math.isnan(i)) or str(i).strip() in ("", "None", "nan"):
            return
        ids.setdefault(norm_id(i), []).append(f"{src}:{i}")
    for _, r in m.iterrows():
        add(r.lr_cruise, f"v2.1 LR ({r.pair_id}, {r.designation})")
        add(r.cruise_id, f"v2.1 HR ({r.pair_id})")
    hr_of = {}
    for _, r in cv.iterrows():
        hr_of[str(r.hr_id)] = r.hr_cruise_final
    for _, r in d.iterrows():
        add(r.lr_cruise, f"dropped LR ({r.pair_id})")
        mm = re.search(r"__(MGDS|PANGAEA)_(\d+)$", r.pair_id)
        hid = f"{mm.group(1)}:{mm.group(2)}" if mm else None
        if hid in hr_of and isinstance(hr_of[hid], str):
            add(hr_of[hid], f"dropped HR ({r.pair_id}, candidates_verified.hr_cruise_final)")
    # the PANGAEA dropped pair's LR cruise id is the dataset id; its ship cruise is M114/1 (ACQ-R03 common.PANGAEA_UNITS)
    add("M114/1", "dropped LR (PANGAEA_864677__PANGAEA_889317 = M114/1)")
    for c in acq.cruise:
        add(c, "ACQ-R02 §7 acquisition table")
    ncei["nid"] = ncei.survey_id.map(norm_id)
    ncei_ids = set(ncei.nid)
    unmatched = sorted({s.split(":", 1)[1] for k, v in ids.items() if k not in ncei_ids for s in v})

    # ---------------- rule 2: exclusion geometries ----------------
    geoms = []   # (name, kind, geom4326, threshold_m, source)
    for _, r in m.iterrows():
        des = str(r.designation)
        if r.pair_id in C.LOCKBOX or des == "lockbox":
            continue
        if des.startswith("confirmatory"):
            hid = "MGDS:" + r.pair_id.split("__MGDS_")[1]
            geoms.append((r.pair_id, "hr_confirmatory_gpkg", hrfp.loc[hid].geometry, R.BUFFER_M, f"hr_footprints.gpkg:{hid}"))
            continue
        hp = C.OAK / str(r.harmonized_path).split("/lrv2_1")[0] / "footprint.geojson" if r.harmonized_path else None
        if hp is not None and hp.exists():
            g = gpd.read_file(hp)
            g = g.set_crs("EPSG:4326", allow_override=True) if g.crs is None else g
            geoms.append((r.pair_id, "hr_oak_footprint", make_valid(g.to_crs("EPSG:4326").geometry.union_all()), R.BUFFER_M, str(hp)))
        else:
            hid = "MGDS:" + r.pair_id.split("__MGDS_")[1]
            geoms.append((r.pair_id, "hr_gpkg_fallback", hrfp.loc[hid].geometry, R.BUFFER_M, f"hr_footprints.gpkg:{hid}"))
    for _, r in d.iterrows():
        hp = C.OAK / r.harmonized_dir / "footprint.geojson"
        if hp.exists():
            g = gpd.read_file(hp)
            g = g.set_crs("EPSG:4326", allow_override=True) if g.crs is None else g
            geoms.append((r.pair_id, "hr_oak_footprint_dropped", make_valid(g.to_crs("EPSG:4326").geometry.union_all()), R.BUFFER_M, str(hp)))
        else:
            mm = re.search(r"__(MGDS|PANGAEA)_(\d+)$", r.pair_id); hid = f"{mm.group(1)}:{mm.group(2)}"
            geoms.append((r.pair_id, "hr_gpkg_fallback_dropped", hrfp.loc[hid].geometry, R.BUFFER_M, f"hr_footprints.gpkg:{hid}"))
    # Conservative extra: EVERY hr_footprints.gpkg polygon not already used as a primary geometry.  For multi-patch HR
    # releases the OAK footprint.geojson is the harmonized HR∩LR overlap, smaller than the release; the gpkg also holds
    # HR outside manifest v2.1 / dropped (pu00, pu03, verification rejects).  Counted separately ('extra_gpkg').
    used = {s_.split(":", 1)[1] for _, k_, _, _, s_ in geoms if k_.startswith("hr_gpkg") or k_ == "hr_confirmatory_gpkg"}
    for hid, row in hrfp.iterrows():
        if hid not in used:
            geoms.append((hid, "extra_gpkg", row.geometry, R.BUFFER_M, f"hr_footprints.gpkg:{hid}"))
    for lc in C.LOCKBOX_LR_CRUISES:
        g = ncei[ncei.survey_id == lc]
        if len(g) != 1:
            raise SystemExit(f"lockbox LR cruise {lc} not unique in NCEI layer")
        geoms.append((f"lockbox_lr_cruise:{lc}", "lockbox_lr_footprint", g.geometry.iloc[0], R.BUFFER_M, "NCEI footprint (metadata)"))
    for _, r in la[la.pair_id.isin(C.LOCKBOX)].iterrows():
        geoms.append((f"lockbox_centroid:{r.pair_id}", "lockbox_centroid", Point(r.centroid_lon, r.centroid_lat), R.LOCKBOX_RADIUS_M,
                      "reports/discovery/leakage_assignment.csv"))

    # ---------------- per-cruise tests ----------------
    parts, owner = [], []
    for i, g in enumerate(ncei.geometry):
        for p in getattr(g, "geoms", [g]):
            if not p.is_empty:
                parts.append(p); owner.append(i)
    tree = STRtree(parts)
    near = {}   # cruise idx -> list of (geom name, kind, distance, threshold)
    for name, kind, g, thr, src in geoms:
        for o, dist in min_distances(g, thr + SIMPLIFY_TOL_M, tree, parts, owner).items():
            near.setdefault(o, []).append({"geometry": name, "kind": kind, "min_distance_m": round(dist, 1), "threshold_m": thr})
    text = (ncei.platform.fillna("") + " " + ncei.instrument.fillna(""))
    recs, excluded = [], []
    for i, r in ncei.iterrows():
        rules = []
        if NON_SHIP.search(text.iloc[i] or ""):
            rules.append("4_non_ship")
        if r.nid in ids:
            rules.append("1_shared_cruise")
        hits = [h for h in near.get(i, []) if h["min_distance_m"] <= h["threshold_m"] + SIMPLIFY_TOL_M]
        hits10 = [h for h in hits if h["min_distance_m"] <= h["threshold_m"]]
        if hits:
            rules.append("2_spatial")
        rec = {"survey_id": r.survey_id, "rules": rules, "shared_ids": ids.get(r.nid, []), "spatial_hits": hits,
               "spatial_only_via_tolerance": bool(hits and not hits10)}
        if rules:
            excluded.append(rec)
        recs.append(rec)
    ex_ids = {e["survey_id"] for e in excluded}
    pool = ncei[~ncei.survey_id.isin(ex_ids)].copy()
    cen = [R.spherical_centroid(g) for g in pool.geometry]
    pool["centroid_lon"] = [c[0] for c in cen]; pool["centroid_lat"] = [c[1] for c in cen]
    from src.acq_r01.discovery_rerun import basin
    pool["basin"] = [basin(x, y) for x, y in cen]
    pool["family"] = pool.instrument.fillna("").map(family)
    pool_csv = R.REPORT_DIR / "pool_ids_v1.csv"
    pool.drop(columns=["geometry", "nid"]).to_csv(pool_csv, index=False)

    # ---------------- counts ----------------
    order = ["1_shared_cruise", "2_spatial", "3_composite", "4_non_ship"]
    any_counts = {k: sum(k in e["rules"] for e in excluded) for k in order}
    first_counts = {k: sum(e["rules"] and sorted(e["rules"], key=order.index)[0] == k for e in excluded) for k in order}
    only_counts = {k: sum(e["rules"] == [k] for e in excluded) for k in order}

    # ---------------- ACQ-R01 §5 re-run (verbatim functions) for the comparison ----------------
    from src.acq_r01 import pretrain_scope as PS
    raw = gpd.read_file(R.NCEI_FP)
    ship = raw[~(raw.PLATFORM.fillna("") + " " + raw.INSTRUMENT.fillna("")).str.contains(NON_SHIP)].copy()
    m1 = C.load_manifest()
    excl1 = set(map(str, m1.lr_cruise))
    cg = pd.read_csv(R.R01 / "discovery_rerun" / "candidates_gated.csv"); cand = cg[cg.status == "new_candidate"]
    for s in cand.lr_cruises_all.dropna():
        excl1 |= set(str(s).split(";"))
    zone, zinfo = PS.exclusion_geometry(m1, cand, raw)
    ship["excl_id"] = ship.SURVEY_ID.isin(excl1); ship["excl_geom"] = ship.geometry.intersects(zone)
    keep1 = ship[~ship.excl_id & ~ship.excl_geom]
    r01_records = int(len(keep1)); r01_ids = set(keep1.SURVEY_ID)
    our = set(pool.survey_id)
    newly_excluded = sorted(r01_ids - our); newly_included = sorted(our - r01_ids)
    why_excl = {s: next((e["rules"] for e in excluded if e["survey_id"] == s), []) for s in newly_excluded}
    detail_ex = {s: {"rules": why_excl[s],
                     "shared_ids": next((e["shared_ids"] for e in excluded if e["survey_id"] == s), []),
                     "spatial_hits": [h["geometry"] for h in next((e["spatial_hits"] for e in excluded if e["survey_id"] == s), [])]}
                 for s in newly_excluded}
    detail_in = {}
    for s in newly_included:
        row = ship[ship.SURVEY_ID == s]
        detail_in[s] = {"r01_excl_by_id": bool(row.excl_id.any()), "r01_excl_by_zone": bool(row.excl_geom.any()),
                        "r01_id_source": "ACQ-R01 candidate LR cruise (candidates_gated new_candidate)" if s in excl1 and s not in set(map(str, m1.lr_cruise)) else
                        ("ACQ-R01 manifest LR" if s in excl1 else None)}

    out = {
        "generated": R.utc_now(), "code_commit": C.git_commit(), "fixed_input_sha256": hashes,
        "inputs": {"ncei_footprints_snapshot": {"path": str(R.NCEI_FP), "sha256": R.sha256_file(R.NCEI_FP), "records": n_records,
                                                "unique_survey_ids": int(len(ncei)), "layer": "NCEI Multibeam Footprints (raw surveys; ACQ-R01 §5 snapshot 2026-09-29)"},
                   "hr_footprints_gpkg": {"path": str(R.R02 / "verification" / "hr_footprints.gpkg"), "sha256": R.sha256_file(R.R02 / "verification" / "hr_footprints.gpkg")},
                   "candidates_verified": {"path": str(R.R02 / "verification" / "candidates_verified.csv"), "sha256": R.sha256_file(R.R02 / "verification" / "candidates_verified.csv")},
                   "acquisition_cruises": {"path": str(R.R02 / "acquisition_cruises.csv"), "sha256": R.sha256_file(R.R02 / "acquisition_cruises.csv")},
                   "leakage_assignment": {"path": "reports/discovery/leakage_assignment.csv", "sha256": R.sha256_file(C.REPO / "reports" / "discovery" / "leakage_assignment.csv")}},
        "method": {"distance": "minimum planar distance in a local azimuthal-equidistant projection (WGS84) centred on each <= 2 deg piece of the exclusion geometry",
                   "thresholds_m": {"hr_footprint": R.BUFFER_M, "lockbox_lr_footprint": R.BUFFER_M, "lockbox_centroid": R.LOCKBOX_RADIUS_M},
                   "cruise_level_tolerance_m": SIMPLIFY_TOL_M,
                   "tolerance_reason": "cached NCEI footprints were simplified with maxAllowableOffset 0.01 deg (ACQ-R01 fetch_all_footprints); a cruise within threshold + 1.113 km is excluded",
                   "id_normalisation": "lower-case, '/', '-', '_' and whitespace removed",
                   "rule_3_composite": "0 by construction: the pool universe is the raw per-survey Footprints layer; the Multibeam Products layer is never queried",
                   "rule_4_non_ship": NON_SHIP.pattern},
        "shared_cruise_ids": {k: v for k, v in sorted(ids.items())},
        "shared_ids_without_ncei_survey": unmatched,
        "exclusion_geometries": [{"name": n_, "kind": k_, "threshold_m": t_, "source": s_, "area_deg2": round(g_.area, 6),
                                  "bounds": [round(b, 5) for b in g_.bounds]} for n_, k_, g_, t_, s_ in geoms],
        "counts": {"ncei_records": n_records, "unique_surveys": int(len(ncei)), "excluded_total": len(excluded), "pool_cruises": int(len(pool)),
                   "by_rule_any": any_counts, "by_rule_first_in_order_1_to_4": first_counts, "by_rule_only": only_counts,
                   "excluded_only_by_extra_gpkg": sum(e["rules"] == ["2_spatial"] and all(h["kind"] == "extra_gpkg" for h in e["spatial_hits"]) for e in excluded),
                   "spatial_only_via_tolerance": sum(e["spatial_only_via_tolerance"] and e["rules"] == ["2_spatial"] for e in excluded)},
        "acq_r01_comparison": {"acq_r01_reported_remaining": 3210, "acq_r01_rerun_remaining_records": r01_records,
                               "acq_r01_rerun_remaining_unique_ids": len(r01_ids), "acq_r01_zone_inputs": zinfo,
                               "this_pool": int(len(pool)),
                               "in_acq_r01_not_in_pool": detail_ex, "in_pool_not_in_acq_r01": detail_in},
        "excluded": excluded,
    }
    R.write_json(R.REPORT_DIR / "exclusion_v1.json", out)
    # the exclusion geometries themselves (for the §3.3 block-level guard); thresholds per geometry
    gpd.GeoDataFrame([{"name": n_, "kind": k_, "threshold_m": t_, "source": s_,
                       "tolerance_m": SIMPLIFY_TOL_M if k_ == "lockbox_lr_footprint" else 0.0} for n_, k_, g_, t_, s_ in geoms],
                     geometry=[g_ for _, _, g_, _, _ in geoms], crs="EPSG:4326").to_file(R.CACHE / "exclusion_geometries_v1.geojson", driver="GeoJSON")
    print(json.dumps({k: out["counts"][k] for k in out["counts"]}, indent=1))
    print(json.dumps({k: v for k, v in out["acq_r01_comparison"].items() if not k.startswith("in_")}, indent=1),
          len(newly_excluded), len(newly_included))
    return 0


if __name__ == "__main__":
    sys.exit(main())
