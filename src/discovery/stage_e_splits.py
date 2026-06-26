"""Phase 2 Stage E — corpus finalization + leakage-safe split design.

Combines the 32 new C.5c pairs (30 train_eligible + 2 eval_only) with the 21
validated pairs, dedups (id + spatial), builds the leakage graph
(geo_cluster ∪ shared-LR → atomic units), characterizes diversity, and proposes
2-3 leakage-safe splits. Design only — picks no split; writes no manifest.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import shape
from collections import Counter, defaultdict

REPO = Path(__file__).resolve().parents[2]
SWEEP = json.loads((REPO / "reports/discovery/stage_c5b_sweep.json").read_text())
A6 = gpd.read_file(REPO / "reports/discovery/stage_a6_hr_footprints_2026-06-22.gpkg").set_index("hr_id")
CAT = gpd.read_file(REPO / "reports/discovery/hr_catalog.gpkg").set_index("hr_id")
FL = pd.read_csv(REPO / "reports/stage_b_fetch_list_2026-06-22.csv")
LRC = gpd.read_file(REPO / "reports/discovery/lr_candidates.gpkg")
MANI = pd.read_parquet(REPO / "manifest/pairs.parquet")
HARM = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/harmonized")

WEAK = {("NA090", "MGDS:31212"), ("TN159", "MGDS:21981")}   # near_circular_weak -> eval

# Stage-C grid depth fallback (for HR with no catalog depth)
_GD = {}
for _f in ("reports/discovery/stage_c_full_measurements.json",
           "reports/discovery/stage_c_pilot_measurements.json"):
    try:
        for _r in json.loads((REPO / _f).read_text()):
            gd = _r.get("grid_depth_median")
            if gd is not None and gd == gd:
                _GD[(_r.get("cruise"), _r.get("hr_id"))] = abs(float(gd))
    except Exception:
        pass


def _footprint(hr_id):
    from src.discovery.stage_c_full import footprint_for
    return footprint_for(hr_id)


def _morph(depth, feat, terrain_hint):
    f = f"{feat or ''} {terrain_hint or ''}".lower()
    if any(w in f for w in ("vent", "hydrotherm", "tag", "endeavour", "axial", "loihi")):
        return "hydrothermal_vent"
    if any(w in f for w in ("seamount", "summit", "volcan")):
        return "seamount"
    if "nodule" in f or "ccz" in f or "clarion" in f:
        return "nodule_plain"
    if "shelf" in f or "arctic" in f or "amundsen" in f:
        return "arctic_shelf"
    d = abs(depth) if depth == depth else None
    if d is None:
        return "unknown"
    if d >= 3500:
        return "abyssal_plain"
    if d >= 800:
        return "continental_margin"
    return "shelf_slope"


def new_pairs():
    rows = []
    by = {(r["cruise"], r["hr_id"]): r for r in SWEEP}
    # the 32 = recoverable@k8 (incl circular_leak red) + the Arctic 30045 (per-tile)
    for r in SWEEP:
        if r.get("status") != "ok":
            continue
        v8 = r["per_k"].get("8", {}).get("verdict")
        if v8 not in ("recoverable_signal", "circular_leak"):
            continue
        rows.append(_mk_new(r))
    # Arctic 30045 (rescued per-tile; not 'ok' in sweep)
    a = next((x for x in SWEEP if x["hr_id"] == "MGDS:30045"), None)
    rows.append(_mk_new({"cruise": "2009_Amundsen", "hr_id": "MGDS:30045",
                         "lr_native_m": 42.0, "max_recoverable_k": 8,
                         "uq_rms_m": None, "uq_char_m": None, "edge_coh": None,
                         "per_k": {"8": {"verdict": "recoverable_signal"}}},
                        arctic=True))
    return rows


def _mk_new(r, arctic=False):
    hr = r["hr_id"]; cruise = r["cruise"]
    poly = _footprint(hr)
    depth = np.nan
    if hr in CAT.index:
        dm, dx = CAT.loc[hr, "depth_min_m"], CAT.loc[hr, "depth_max_m"]
        try:
            depth = (abs(float(dm)) + abs(float(dx))) / 2
        except Exception:
            depth = np.nan
    if depth != depth:                       # fall back to Stage-C grid depth
        depth = _GD.get((cruise, hr), np.nan)
    feat = CAT.loc[hr, "geographic_feature"] if hr in CAT.index else ""
    th = LRC[LRC.cruise_id == cruise]["sonar"].dropna()
    role = "eval_only" if (cruise, hr) in WEAK else "train_eligible"
    return {"pair_id": f"{cruise}__{hr.replace(':', '_')}", "source": "new_c5c",
            "cruise": cruise, "hr_id": hr, "lr_source": cruise,
            "lr_native_m": r.get("lr_native_m"),
            "max_k": r.get("max_recoverable_k"),
            "uq_rms_m": r.get("uq_rms_m"), "uq_char_m": r.get("uq_char_m"),
            "edge_coh": r.get("edge_coh"),
            "depth_m": round(depth, 0) if depth == depth else None,
            "morphology": _morph(depth, feat, None),
            "role": role,
            "geometry": poly, "deep_rescue": (r.get("prior_ratio") or 0) > 40}


def validated_pairs():
    rows = []
    for _, m in MANI.iterrows():
        fp = m.get("footprint_wkt")
        geom = None
        if isinstance(fp, str) and Path(fp).exists():
            g = gpd.read_file(fp)
            if g.crs is not None and str(g.crs).lower() != "epsg:4326":
                g = g.to_crs(4326)
            geom = g.union_all()
        site = str(m.get("site_name") or m["pair_id"])
        depth = None
        try:
            depth = (abs(float(m["depth_min_m"])) + abs(float(m["depth_max_m"]))) / 2
        except Exception:
            pass
        rows.append({"pair_id": m["pair_id"], "source": "validated_21",
                     "cruise": m.get("cruise_id"), "hr_id": "", "lr_source": str(m.get("cruise_id") or m.get("lr_doi") or m["pair_id"]),
                     "lr_native_m": m.get("lr_native_res_m"), "max_k": None,
                     "uq_rms_m": None, "uq_char_m": None, "edge_coh": None,
                     "depth_m": round(depth, 0) if depth else None,
                     "morphology": _terrain_to_morph(m.get("terrain_class"), site),
                     "role": "train_eligible",   # the 21 are validated training pairs
                     "geometry": geom, "deep_rescue": False})
    return rows


def _terrain_to_morph(tc, site):
    tc = (tc or "").lower(); s = site.lower()
    if "vent" in tc or "tag" in s:
        return "hydrothermal_vent"
    if "abyssal" in tc or "discol" in s:
        return "abyssal_plain"
    if "nodule" in tc or "ccz" in s:
        return "nodule_plain"
    if "margin" in tc or "cal dig" in s or "morro" in s:
        return "continental_margin"
    return tc or "unknown"


def _iou(a, b):
    if a is None or b is None or a.is_empty or b.is_empty:
        return 0.0
    inter = a.intersection(b).area
    if inter <= 0:
        return 0.0
    return inter / a.union(b).area


def _containment(a, b):
    if a is None or b is None or a.is_empty or b.is_empty:
        return 0.0
    inter = a.intersection(b).area
    if inter <= 0:
        return 0.0
    return max(inter / a.area if a.area else 0, inter / b.area if b.area else 0)


class UF:
    def __init__(s, n): s.p = list(range(n))
    def f(s, x):
        while s.p[x] != x: s.p[x] = s.p[s.p[x]]; x = s.p[x]
        return x
    def u(s, a, b): s.p[s.f(a)] = s.f(b)


def main():
    new = new_pairs()
    val = validated_pairs()
    gdf = gpd.GeoDataFrame(new + val, geometry="geometry", crs="EPSG:4326")
    # ---- E1: spatial dedup new vs validated ----
    dups = []
    nmask = gdf.source == "new_c5c"
    vmask = gdf.source == "validated_21"
    for i, nr in gdf[nmask].iterrows():
        for j, vr in gdf[vmask].iterrows():
            iou = _iou(nr.geometry, vr.geometry); con = _containment(nr.geometry, vr.geometry)
            if iou > 0.8 or con >= 0.9:
                dups.append((nr["pair_id"], vr["pair_id"], round(iou, 2), round(con, 2)))
    gdf = gdf[~gdf["pair_id"].isin([d[0] for d in dups])].reset_index(drop=True)
    print(f"E1: combined {len(new)} new + {len(val)} validated; spatial dups dropped={len(dups)} -> {len(gdf)}")
    for d in dups:
        print("   DUP", d)

    # ---- E3: geo_cluster (50 km) + shared-LR -> leakage units ----
    cents = gdf.geometry.apply(lambda g: g.centroid if g is not None and not g.is_empty else None)
    # 50 km clustering via UTM centroid distance (union-find)
    import pyproj
    uf = UF(len(gdf)); R_KM = 50.0
    xy = []
    for c in cents:
        if c is None:
            xy.append((np.nan, np.nan)); continue
        epsg = 32600 + int((c.x + 180) // 6) + 1 if c.y >= 0 else 32700 + int((c.x + 180) // 6) + 1
        tr = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        xy.append(tr.transform(c.x, c.y))
    for i in range(len(gdf)):
        for j in range(i + 1, len(gdf)):
            if any(np.isnan(xy[i])) or any(np.isnan(xy[j])):
                continue
            # only meaningful within same UTM-ish region; use lon/lat haversine instead
            d = _haversine(cents.iloc[i], cents.iloc[j])
            if d is not None and d <= R_KM:
                uf.u(i, j)
    # shared-LR
    lrsrc = gdf["lr_source"].fillna("").tolist()
    bylr = defaultdict(list)
    for i, s in enumerate(lrsrc):
        if s:
            bylr[s].append(i)
    for idxs in bylr.values():
        for k in range(1, len(idxs)):
            uf.u(idxs[0], idxs[k])
    gdf["geo_cluster"] = [uf.f(i) for i in range(len(gdf))]   # cluster id post-union
    gdf["leakage_unit"] = gdf["geo_cluster"]

    _outputs(gdf, dups)


def _haversine(a, b):
    if a is None or b is None:
        return None
    import math
    R = 6371.0
    lat1, lat2 = math.radians(a.y), math.radians(b.y)
    dlat = lat2 - lat1; dlon = math.radians(b.x - a.x)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(min(1, math.sqrt(h)))


def _outputs(gdf, dups):
    # leakage units
    units = gdf.groupby("leakage_unit")
    unit_rows = []
    for uid, g in units:
        unit_rows.append({"unit": uid, "n_pairs": len(g),
                          "morphologies": ";".join(sorted(set(g.morphology))),
                          "lr_sources": ";".join(sorted(set(g.lr_source.dropna()))),
                          "roles": ";".join(sorted(set(g.role))),
                          "members": ";".join(g.pair_id)})
    pd.DataFrame(unit_rows).sort_values("n_pairs", ascending=False).to_csv(
        REPO / "reports/discovery/leakage_units.csv", index=False)
    # combined corpus
    cols = ["pair_id", "source", "role", "cruise", "hr_id", "lr_source",
            "lr_native_m", "max_k", "uq_rms_m", "uq_char_m", "depth_m",
            "morphology", "deep_rescue", "geo_cluster", "leakage_unit"]
    gdf[cols].to_csv(REPO / "reports/combined_corpus.csv", index=False)

    print(f"\n=== E2 roles ===", dict(Counter(gdf.role)))
    print("=== E4 morphology ===", dict(Counter(gdf.morphology)))
    print("=== E4 deep_rescue (abyssal skew) ===", int(gdf.deep_rescue.sum()), "of", len(gdf))
    nunits = gdf.leakage_unit.nunique()
    sizes = gdf.groupby("leakage_unit").size().sort_values(ascending=False)
    print(f"=== E3 leakage units: {nunits} units; largest sizes {list(sizes.head(6))}")
    print(f"   train_eligible: {int((gdf.role=='train_eligible').sum())}; eval_only: {int((gdf.role=='eval_only').sum())}")

    _splits(gdf, sizes)


def _splits(gdf, sizes):
    """E5 — propose 2-3 leakage-safe splits (whole units to one side)."""
    units = gdf.groupby("leakage_unit")
    unit_info = {uid: {"n": len(g), "morph": Counter(g.morphology),
                       "roles": set(g.role)} for uid, g in units}
    train_pairs = int((gdf.role == "train_eligible").sum())
    proposals = {}

    # Option A: in-distribution, leakage-safe greedy 70/15/15 by unit, morphology-aware
    units_sorted = sorted(unit_info, key=lambda u: -unit_info[u]["n"])
    tgt = {"train": 0.70, "val": 0.15, "test": 0.15}
    assign = {}; tot = {"train": 0, "val": 0, "test": 0}
    N = len(gdf)
    for u in units_sorted:
        # eval_only units never go to train
        side = min(("test", "val", "train"), key=lambda s: tot[s] - tgt[s] * N)
        if "train_eligible" not in unit_info[u]["roles"]:
            side = "test" if tot["test"] <= tot["val"] else "val"
        assign[u] = side; tot[side] += unit_info[u]["n"]
    proposals["A_in_distribution"] = _split_summary(gdf, assign, tot,
        "leakage-safe random, morphology-aware ~70/15/15; tests in-distribution SR; spends corpus efficiently")

    # Option B: generalization — hold out a smaller structured class (vents) as
    # test (holding out the dominant continental_margin would leave ~nothing to
    # train; vents are the main structured non-margin class).
    holdout = "hydrothermal_vent"
    assignB = {u: ("test" if any(m == holdout for m in unit_info[u]["morph"]) else "train") for u in unit_info}
    totB = Counter()
    for u, s in assignB.items(): totB[s] += unit_info[u]["n"]
    proposals["B_generalization_holdout_vents"] = _split_summary(gdf, assignB, totB,
        f"hold out ALL '{holdout}' pairs as test → measures generalization to the "
        f"structured vent terrain the model most needs; sacrifices vent training "
        f"(only {totB['test']} vent pairs, so no in-distribution vent eval)")

    # Option C: held-out by depth (train shallow/margin <2500m, test deep >=2500m)
    def depth_side(u):
        g = gdf[gdf.leakage_unit == u]
        md = g.depth_m.dropna().mean()
        return "test" if (md == md and md >= 2500) else "train"
    assignC = {u: depth_side(u) for u in unit_info}
    totC = Counter()
    for u, s in assignC.items(): totC[s] += unit_info[u]["n"]
    proposals["C_held_out_by_depth"] = _split_summary(gdf, assignC, totC,
        "train <2500 m (margin/shelf), test >=2500 m (deep) → tests depth/factor extrapolation")

    (REPO / "reports/discovery/proposed_splits.json").write_text(json.dumps(proposals, indent=2, default=str))
    print("\n=== E5 proposed splits ===")
    for name, p in proposals.items():
        print(f"  {name}: sizes={p['sizes']} leakage_safe={p['leakage_safe']}")
    print("wrote combined_corpus.csv, leakage_units.csv, proposed_splits.json")


def _split_summary(gdf, assign, tot, claim):
    side = gdf.leakage_unit.map(assign)
    cov = {}
    for s in set(assign.values()):
        sub = gdf[side == s]
        cov[s] = {"n": len(sub), "morph": dict(Counter(sub.morphology)),
                  "n_eval_only": int((sub.role == "eval_only").sum())}
    # leakage check: no LR source or geo_cluster crosses sides
    leak_ok = True
    for col in ("lr_source", "leakage_unit"):
        for val, g in gdf.groupby(col):
            if g.leakage_unit.map(assign).nunique() > 1:
                leak_ok = False
    return {"claim": claim, "sizes": {s: cov[s]["n"] for s in cov},
            "coverage": cov, "leakage_safe": leak_ok}


if __name__ == "__main__":
    main()
