"""Phase 2 — leakage_unit / geo_cluster assignment for the canonical 39 pairs.

Read-only. Computes, for the current manifest, a leakage-safe grouping so a
downstream train/val/test split never puts two views of the same seafloor on
opposite sides. Two pairs share a leakage_unit if EITHER:
  - their footprint centroids are within R_KM (default 50 km) of each other
    (geo_cluster — spatial proximity), OR
  - they share an LR source (same cruise_id) — the same ship grid feeding both.

geo_cluster   = connected components under spatial proximity only.
leakage_unit  = connected components under spatial proximity UNION shared-LR.

Stable, deterministic IDs (sorted by representative centroid). Writes an
assignment table; writes NO manifest (that is stage_p2_phase2).
"""
from __future__ import annotations
import json, logging, math
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


class UF:
    def __init__(self, n): self.p = list(range(n))
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b): self.p[self.find(a)] = self.find(b)


def _centroid_4326(fp):
    """fp may be a path to a geojson, or a WKT string. Return (lon, lat)."""
    if isinstance(fp, str) and Path(fp).exists():
        g = gpd.read_file(fp)
        if g.crs is not None and str(g.crs).lower() != "epsg:4326":
            g = g.to_crs(4326)
        c = g.union_all().centroid
        return (c.x, c.y)
    # fall back: treat as WKT
    from shapely import wkt
    try:
        geom = wkt.loads(fp)
        c = geom.centroid
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
    """Stable component labels: order components by their min (lat,lon) member."""
    comp = {}
    for i in range(n):
        comp.setdefault(uf.find(i), []).append(i)
    def keyfn(members):
        pts = [cents[i] for i in members if None not in cents[i]]
        if not pts:
            return (9e9, 9e9)
        return (round(min(p[1] for p in pts), 4), round(min(p[0] for p in pts), 4))
    ordered = sorted(comp.values(), key=keyfn)
    label = {}
    for k, members in enumerate(ordered):
        lbl = f"{prefix}{k:02d}"
        for i in members:
            label[i] = lbl
    return label


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    m = pd.read_parquet(CANON)
    n = len(m)
    pair_ids = m["pair_id"].tolist()
    lr_src = [str(m.iloc[i].get("cruise_id") or m.iloc[i].get("lr_doi") or pair_ids[i])
              for i in range(n)]
    cents = [_centroid_4326(m.iloc[i]["footprint_wkt"]) for i in range(n)]
    nbad = sum(1 for c in cents if None in c)
    if nbad:
        log.warning("%d/%d pairs have no resolvable centroid", nbad, n)

    # geo_cluster: spatial proximity only
    uf_geo = UF(n)
    for i in range(n):
        for j in range(i + 1, n):
            d = _haversine_km(cents[i], cents[j])
            if d is not None and d <= R_KM:
                uf_geo.union(i, j)
    geo_label = _label_components(uf_geo, n, cents, "gc")

    # leakage_unit: spatial proximity UNION shared-LR
    uf_leak = UF(n)
    for i in range(n):
        for j in range(i + 1, n):
            d = _haversine_km(cents[i], cents[j])
            if d is not None and d <= R_KM:
                uf_leak.union(i, j)
    from collections import defaultdict
    bylr = defaultdict(list)
    for i, s in enumerate(lr_src):
        bylr[s].append(i)
    for idxs in bylr.values():
        for k in range(1, len(idxs)):
            uf_leak.union(idxs[0], idxs[k])
    leak_label = _label_components(uf_leak, n, cents, "lu")

    rows = []
    for i in range(n):
        rows.append({"pair_id": pair_ids[i], "geo_cluster": geo_label[i],
                     "leakage_unit": leak_label[i], "lr_source": lr_src[i],
                     "centroid_lon": None if cents[i][0] is None else round(cents[i][0], 5),
                     "centroid_lat": None if cents[i][1] is None else round(cents[i][1], 5)})
    df = pd.DataFrame(rows).sort_values(["leakage_unit", "pair_id"]).reset_index(drop=True)
    df.to_csv(OUT_CSV, index=False)

    # units table
    units = []
    for lu, g in df.groupby("leakage_unit"):
        units.append({"leakage_unit": lu, "n_pairs": len(g),
                      "geo_clusters": ";".join(sorted(g.geo_cluster.unique())),
                      "lr_sources": ";".join(sorted(g.lr_source.unique())),
                      "members": ";".join(g.pair_id)})
    udf = pd.DataFrame(units).sort_values("n_pairs", ascending=False).reset_index(drop=True)
    udf.to_csv(OUT_UNITS, index=False)

    multi = udf[udf.n_pairs > 1]
    summary = {"n_pairs": n, "R_KM": R_KM,
               "n_geo_clusters": df.geo_cluster.nunique(),
               "n_leakage_units": df.leakage_unit.nunique(),
               "n_multi_pair_units": int(len(multi)),
               "multi_pair_units": multi.to_dict("records"),
               "csv": str(OUT_CSV), "units_csv": str(OUT_UNITS)}
    OUT_JSON.write_text(json.dumps(summary, indent=2, default=str))

    log.info("=== Phase 2 leakage: %d pairs -> %d geo_clusters, %d leakage_units ===",
             n, summary["n_geo_clusters"], summary["n_leakage_units"])
    log.info("multi-pair leakage units (%d):", len(multi))
    for _, r in multi.iterrows():
        log.info("  %s (n=%d): %s", r["leakage_unit"], r["n_pairs"], r["members"])
    log.info("wrote %s, %s", OUT_CSV, OUT_UNITS)


if __name__ == "__main__":
    main()
