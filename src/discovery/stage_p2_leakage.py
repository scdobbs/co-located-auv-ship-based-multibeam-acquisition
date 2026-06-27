"""Phase 2 L-FIX — leakage_unit / geo_cluster on the CORRECT axes (+ lr_cruise).

Read-only. Recomputes the leakage grouping after the v1 bug: v1 used `cruise_id`
as the "shared-LR" axis, but `cruise_id` is the HR AUV cruise; the LR ship cruise
lives in `lr_doi` ("... cruise <X>") and in the pair_id prefix. v1 therefore
wrongly split TN299 (×27339/×31253, both LR cruise TN299) and FK181031
(×24367/×24618, both LR cruise FK181031), and merged Axial via shared HR (not LR).

Policy = CONSERVATIVE (Steve's call): shared acquisition on EITHER side (HR AUV
survey OR LR ship cruise) is one unit at ANY distance; plus geo proximity ≤50 km.

leakage_unit = connected components under the UNION of three edges:
  (1) centroid proximity ≤ R_KM,
  (2) shared HR AUV survey  = `cruise_id`,
  (3) shared LR ship cruise = `lr_cruise` (parsed from lr_doi / pair_id prefix).
geo_cluster  = connected components under edge (1) only.

Writes assignment + units tables (with the policy recorded). Writes NO manifest.
"""
from __future__ import annotations
import json, logging, math, re
from pathlib import Path

import geopandas as gpd
import pandas as pd

log = logging.getLogger("p2leak")
REPO = Path(__file__).resolve().parents[2]
CANON = REPO / "manifest/pairs.parquet"
OUT_CSV = REPO / "reports/discovery/leakage_assignment.csv"
OUT_UNITS = REPO / "reports/discovery/leakage_units_canonical.csv"
OUT_JSON = REPO / "reports/discovery/stage_p2_leakage.json"
R_KM = 50.0
POLICY = "conservative: shared HR survey (cruise_id) OR shared LR cruise (lr_cruise) OR centroid<=50km"


class UF:
    def __init__(self, n): self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b): self.p[self.find(a)] = self.find(b)


def lr_cruise_of(row):
    """LR ship cruise: parse 'cruise <X>' from lr_doi; else pair_id prefix
    (which is <LR_ship_cruise>__MGDS_<HR_uid>); else cruise_id."""
    doi = str(row.get("lr_doi") or "")
    m = re.search(r"cruise\s+([A-Za-z0-9_\-./]+)\s*$", doi)
    if m:
        return m.group(1)
    pid = str(row.get("pair_id") or "")
    if "__MGDS_" in pid:
        return pid.split("__MGDS_", 1)[0]
    return str(row.get("cruise_id") or pid)


def _centroid_4326(fp):
    if isinstance(fp, str) and Path(fp).exists():
        g = gpd.read_file(fp)
        if g.crs is not None and str(g.crs).lower() != "epsg:4326":
            g = g.to_crs(4326)
        c = g.union_all().centroid
        return (c.x, c.y)
    from shapely import wkt
    try:
        c = wkt.loads(fp).centroid
        return (c.x, c.y)
    except Exception:
        return (None, None)


def _haversine_km(a, b):
    if None in a or None in b:
        return None
    R = 6371.0
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = math.radians(b[0] - a[0])
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


def _label_components(uf, n, cents, prefix):
    comp = {}
    for i in range(n):
        comp.setdefault(uf.find(i), []).append(i)
    def keyfn(members):
        pts = [cents[i] for i in members if None not in cents[i]]
        if not pts:
            return (9e9, 9e9)
        return (round(min(p[1] for p in pts), 4), round(min(p[0] for p in pts), 4))
    label = {}
    for k, members in enumerate(sorted(comp.values(), key=keyfn)):
        for i in members:
            label[i] = f"{prefix}{k:02d}"
    return label


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    m = pd.read_parquet(CANON)
    n = len(m)
    pair_ids = m["pair_id"].tolist()
    hr_cruise = [str(m.iloc[i].get("cruise_id") or pair_ids[i]) for i in range(n)]
    lr_cruise = [lr_cruise_of(m.iloc[i]) for i in range(n)]
    cents = [_centroid_4326(m.iloc[i]["footprint_wkt"]) for i in range(n)]
    nbad = sum(1 for c in cents if None in c)
    if nbad:
        log.warning("%d/%d pairs have no resolvable centroid", nbad, n)

    from collections import defaultdict

    def proximity_edges(uf):
        for i in range(n):
            for j in range(i + 1, n):
                d = _haversine_km(cents[i], cents[j])
                if d is not None and d <= R_KM:
                    uf.union(i, j)

    def shared_key_edges(uf, keys):
        by = defaultdict(list)
        for i, k in enumerate(keys):
            if k and str(k).lower() not in ("nan", "none", ""):
                by[k].append(i)
        for idxs in by.values():
            for t in range(1, len(idxs)):
                uf.union(idxs[0], idxs[t])

    # geo_cluster: proximity only
    uf_geo = UF(n); proximity_edges(uf_geo)
    geo_label = _label_components(uf_geo, n, cents, "gc")

    # leakage_unit: proximity UNION shared HR survey UNION shared LR cruise
    uf_leak = UF(n)
    proximity_edges(uf_leak)
    shared_key_edges(uf_leak, hr_cruise)   # shared HR AUV survey
    shared_key_edges(uf_leak, lr_cruise)   # shared LR ship cruise
    leak_label = _label_components(uf_leak, n, cents, "lu")

    rows = []
    for i in range(n):
        rows.append({"pair_id": pair_ids[i], "geo_cluster": geo_label[i],
                     "leakage_unit": leak_label[i], "hr_cruise": hr_cruise[i],
                     "lr_cruise": lr_cruise[i],
                     "centroid_lon": None if cents[i][0] is None else round(cents[i][0], 5),
                     "centroid_lat": None if cents[i][1] is None else round(cents[i][1], 5),
                     "policy": POLICY})
    df = pd.DataFrame(rows).sort_values(["leakage_unit", "pair_id"]).reset_index(drop=True)
    df.to_csv(OUT_CSV, index=False)

    units = []
    for lu, g in df.groupby("leakage_unit"):
        edges = []
        if g.geo_cluster.nunique() < len(g):
            edges.append("geo<=50km")
        if g.hr_cruise.duplicated().any():
            edges.append("shared_hr_survey")
        if g.lr_cruise.duplicated().any():
            edges.append("shared_lr_cruise")
        units.append({"leakage_unit": lu, "n_pairs": len(g),
                      "merge_reason": ";".join(edges) if len(g) > 1 else "singleton",
                      "hr_cruises": ";".join(sorted(g.hr_cruise.unique())),
                      "lr_cruises": ";".join(sorted(g.lr_cruise.unique())),
                      "members": ";".join(g.pair_id)})
    udf = pd.DataFrame(units).sort_values("n_pairs", ascending=False).reset_index(drop=True)
    udf.to_csv(OUT_UNITS, index=False)

    multi = udf[udf.n_pairs > 1]
    summary = {"n_pairs": n, "R_KM": R_KM, "policy": POLICY,
               "n_geo_clusters": int(df.geo_cluster.nunique()),
               "n_leakage_units": int(df.leakage_unit.nunique()),
               "n_multi_pair_units": int(len(multi)),
               "multi_pair_units": multi.to_dict("records"),
               "csv": str(OUT_CSV), "units_csv": str(OUT_UNITS)}
    OUT_JSON.write_text(json.dumps(summary, indent=2, default=str))

    log.info("=== L-FIX leakage: %d pairs -> %d geo_clusters, %d leakage_units (policy=%s) ===",
             n, summary["n_geo_clusters"], summary["n_leakage_units"], "conservative")
    log.info("multi-pair leakage units (%d):", len(multi))
    for _, r in multi.iterrows():
        log.info("  %s n=%d [%s]: %s", r["leakage_unit"], r["n_pairs"], r["merge_reason"], r["members"])
    log.info("wrote %s, %s", OUT_CSV, OUT_UNITS)


if __name__ == "__main__":
    main()
