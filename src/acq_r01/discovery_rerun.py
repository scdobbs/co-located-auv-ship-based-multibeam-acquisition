"""ACQ-R01 §3 — discovery + gate re-run, COUNTS ONLY (no HR/LR acquisition).

Runs the repo's discovery chain exactly as it exists (v1.4/v1.5 modules, unchanged) into a
fresh cache + output directory, then applies the CURRENT standard on top:
  * HR must be an AUV bathymetry grid (platform filter), not a 3-band render (MGDS format
    'GeoTIFF (Raster)' = the 9 RGB renders of the June re-audit), not a duplicate of a corpus pair,
    not an HR already excluded with a recorded reason (corpus_reconciliation.csv);
  * LR must be an independent per-cruise NCEI raw survey (join independence screen; composites
    excluded);
  * lr_native from the documented beam footprint 2*depth*tan(bw/2) (C2a standard), ratio, and an
    empirical k prior from the 39-pair C2c sweep (k cannot be measured without grids);
  * conservative leakage-unit policy: shared HR survey OR shared LR cruise OR centroid <= 50 km
    joins the existing unit; candidates sharing acquisition with a lockbox pair are listed and
    excluded from designation.
Nothing under reports/discovery/ or manifest/ is modified.  No HR or LR file is downloaded; the only
network traffic is catalog metadata (MGDS FileServer, NCEI ArcGIS/Geoportal, NCEI autoindex sizes
for the new units' LR cruises).

Usage (Slurm): python -m src.acq_r01.discovery_rerun [--skip-harvest]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from src.acq_r01 import common as C
from src.discovery import catalog as cat, mgds, ncei, join as join_mod, rebuild, stage_a
from src.discovery.catalog import HRRecord
from src.discovery.raw_lr_dryrun import data_dir_from_iso, resolve_data_dir, size_cruise

log = logging.getLogger("acq_r01.discovery")
STAMP = "2026-09-29"
CACHE = C.SCRATCH_DATA / "discovery_cache" / f"acq_r01_{STAMP}"
OUT = C.REPORT_DIR / "discovery_rerun"
R_KM = 50.0
# Documented across-track beamwidths (deg) by LR sonar family (C2a standard, stage_c2a_documented_native).
BEAMWIDTH = [("em122", 1.0), ("em120", 1.0), ("em302", 1.0), ("em304", 1.0), ("em300", 1.0), ("em710", 1.0),
             ("em712", 1.0), ("em1002", 2.0), ("em2040", 1.0), ("em124", 1.0), ("seabeam 2100", 2.0),
             ("seabeam 2112", 2.0), ("seabeam 2000", 3.3), ("seabeam 3012", 1.5), ("seabeam 3050", 1.5),
             ("hydrosweep", 2.3), ("seabeam", 2.0), ("reson", 1.0), ("elac", 1.5)]
LOCKBOX_HR_CRUISES = {"AT42-03", "AT15-36"}     # manifest cruise_id of the two lockbox pairs
K_TABLE = {2: 2, 4: 4, 8: 8, 16: 16}


def beamwidth(sonar: str) -> float | None:
    s = (sonar or "").lower()
    for k, v in BEAMWIDTH:
        if k in s:
            return v
    return None


def basin(lon: float, lat: float) -> str:
    if lat >= 66.5:
        return "Arctic"
    if lat <= -60:
        return "Southern"
    if -6 <= lon <= 37 and 30 <= lat <= 47:
        return "Mediterranean"
    if -100 <= lon <= 20:
        return "Atlantic" if not (-100 <= lon <= -80 and 18 <= lat <= 31) else "Gulf of Mexico/Caribbean"
    if 20 < lon <= 147 and lat < 30:
        return "Indian"
    return "Pacific"


def seeds_from_manifest(m: pd.DataFrame) -> tuple[list[HRRecord], dict]:
    """Corpus seeds: one HRRecord per NON-lockbox pair, footprint from the OAK footprint.geojson
    (harmonization overlap polygon). Lockbox pairs contribute only their centroid from
    reports/discovery/leakage_assignment.csv (metadata; no lockbox file is opened)."""
    recs, cents = [], {}
    for _, r in m.iterrows():
        if r.pair_id in C.LOCKBOX:
            continue
        gj = C.pair_dir_oak(r) / "footprint.geojson"
        g = gpd.read_file(gj).to_crs("EPSG:4326")
        geom = g.geometry.union_all()
        cents[r.pair_id] = (geom.centroid.x, geom.centroid.y)
        src = "PANGAEA" if "PANGAEA" in str(r.hr_doi).upper() else ("SCIENCEBASE" if "10.5066" in str(r.hr_doi) else "MANIFEST")
        recs.append(HRRecord(hr_id=f"MANIFEST:{r.pair_id}", source=src, doi=str(r.hr_doi or ""), source_uid=r.pair_id,
                             title=f"{r.site_name} — {r.cruise_id}", platform=str(r.hr_platform or "AUV"), platform_type="AUV",
                             sonar=str(r.hr_sonar or ""), native_res_m=float(r.hr_native_res_m) if pd.notna(r.hr_native_res_m) else None,
                             native_crs=str(r.native_crs_hr or ""), format="GeoTIFF", file_ids="", license=str(r.license or "")[:60],
                             cruise_id=str(r.cruise_id or ""), start_date=str(r.acquisition_date or ""), stop_date="",
                             depth_min_m=float(r.depth_min_m) if pd.notna(r.depth_min_m) else None,
                             depth_max_m=float(r.depth_max_m) if pd.notna(r.depth_max_m) else None,
                             geographic_feature=str(r.region or ""), sibling_dois="", description=str(r.notes or "")[:200],
                             harvested_at_utc=STAMP, geometry=geom))
    la = pd.read_csv(C.REPO / "reports/discovery/leakage_assignment.csv")
    for _, r in la[la.pair_id.isin(C.LOCKBOX)].iterrows():
        cents[r.pair_id] = (float(r.centroid_lon), float(r.centroid_lat))
    return recs, cents


def harvest(m):
    OUT.mkdir(parents=True, exist_ok=True)
    seeds, cents = seeds_from_manifest(m)
    log.info("MGDS harvest -> %s", CACHE / "mgds")
    mg = mgds.harvest(CACHE / "mgds")
    cat.write_hr_catalog(mg + seeds, OUT / "hr_catalog_raw.gpkg")
    hr = rebuild.rebuild_hr(OUT / "hr_catalog_raw.gpkg", C.MANIFEST)
    hr.to_file(OUT / "hr_catalog.gpkg", driver="GPKG", layer="hr")
    log.info("HR catalog: %d MGDS + %d seeds -> %d after dedupe", len(mg), len(seeds), len(hr))
    ncei.harvest_for_hr_catalog(OUT / "hr_catalog.gpkg", CACHE / "ncei", OUT / "lr_candidates_raw.gpkg")
    lr = rebuild.rebuild_lr(OUT / "lr_candidates_raw.gpkg", hr, CACHE / "geoportal")
    lr.to_file(OUT / "lr_candidates.gpkg", driver="GPKG", layer="lr")
    join_mod.build(OUT / "hr_catalog.gpkg", OUT / "lr_candidates.gpkg", OUT / "candidate_pairs.gpkg")
    stage_a.run(OUT / "hr_catalog.gpkg", OUT / "lr_candidates.gpkg", OUT / "candidate_pairs.gpkg",
                OUT / "stage_a", CACHE / "mgds", CACHE / "ncei_products")
    C.write_json(OUT / "seed_centroids.json", cents)


class UF:
    def __init__(self, keys):
        self.p = {k: k for k in keys}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def hav_km(a, b):
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def gate(m):
    sel = gpd.read_file(OUT / "stage_a" / "stage_a_selection.gpkg")
    pairs = gpd.read_file(OUT / "candidate_pairs.gpkg", layer="pairs")
    hr = gpd.read_file(OUT / "hr_catalog.gpkg", layer="hr").set_index("hr_id")
    cents = json.loads((OUT / "seed_centroids.json").read_text())
    rec = pd.read_csv(C.REPORT_DIR / "corpus_reconciliation.csv").set_index("hr_id")
    # corpus identity
    corpus_hr = set()
    for pid in m.pair_id:
        corpus_hr.add(f"MGDS:{pid.split('__MGDS_')[1]}" if "__MGDS_" in pid else ("PANGAEA:tag_m127" if pid == "tag_m127" else f"MANIFEST:{pid}"))
    corpus_hr |= {"MGDS:32556", "MGDS:30046", "MGDS:24618", "MGDS:32317", "MGDS:31253"}
    corpus_dois = {str(d) for d in m.hr_doi.dropna()} | {str(d) for d in m.hr_superseded_doi.dropna() if d}
    unit_of = dict(zip(m.pair_id, m.leakage_unit))
    hr_cruise_units = {}; lr_cruise_units = {}
    for _, r in m.iterrows():
        hr_cruise_units.setdefault(str(r.cruise_id), set()).add(r.leakage_unit)
        lr_cruise_units.setdefault(str(r.lr_cruise), set()).add(r.leakage_unit)
    lockbox_lr = set(C.LOCKBOX_LR_CRUISES)
    # all independent LR cruises per HR (for the LR axis of the conservative policy)
    ok_v = pairs[pairs.independence_verdict.isin(["independent", "needs_check"])]
    lr_cruises_of = ok_v.groupby("hr_id").lr_cruise_id.apply(lambda s: sorted(set(map(str, s)))).to_dict()

    rows = []
    for _, s in sel.iterrows():
        h = s.hr_id
        hrow = hr.loc[h] if h in hr.index else None
        fmt = str(hrow["format"]) if hrow is not None else ""
        doi = str(s.hr_doi or "")
        r = {"hr_id": h, "hr_doi": doi, "hr_title": str(s.hr_title or "")[:100], "hr_platform": s.hr_platform,
             "hr_native_res_m": s.hr_native_res_m, "hr_format": fmt, "hr_cruise": str(hrow["cruise_id"]) if hrow is not None else "",
             "gate_tier": s.tier, "gate_tier_reason": s.tier_reason, "best_lr": s.lr_cruise_id, "lr_sonar": s.lr_sonar,
             "lr_platform": s.lr_platform, "independence": s.independence_verdict, "footprint_suspect": bool(s.footprint_suspect),
             "footprint_km2": s.hr_footprint_km2, "depth_min_m": s.depth_min_m, "depth_max_m": s.depth_max_m,
             "terrain_hint": s.terrain_hint, "overlap_km2": s.overlap_km2, "hr_bytes": s.hr_size_bytes_estimate}
        c = s.geometry.centroid; r["lon"], r["lat"] = float(c.x), float(c.y); r["basin"] = basin(c.x, c.y)
        if h.startswith("MANIFEST:") or h in corpus_hr or (doi and doi in corpus_dois):
            r["status"] = "in_corpus"; r["reason"] = "HR already in the 39-pair manifest"
        elif h in rec.index and not str(rec.loc[h, "fate"]).startswith("in corpus"):
            r["status"] = "previously_excluded"; r["reason"] = str(rec.loc[h, "fate"])[:160]
        elif fmt == "GeoTIFF (Raster)":
            r["status"] = "render_no_elevation"; r["reason"] = "MGDS 'GeoTIFF (Raster)' = image render (3-band RGB, no elevation band); float sibling must be used instead"
        elif bool(s.is_non_bathy) or str(s.hr_class) != "auv":
            r["status"] = "not_auv_bathymetry"; r["reason"] = f"hr_class={s.hr_class}, is_non_bathy={s.is_non_bathy}"
        elif s.independence_verdict not in ("independent", "needs_check"):
            r["status"] = "independence_fail"; r["reason"] = str(s.independence_reason)[:120]
        elif s.tier == "excluded":
            r["status"] = "gate_excluded"; r["reason"] = str(s.tier_reason)[:120]
        else:
            r["status"] = "new_candidate"; r["reason"] = ""
        # documented-beam-footprint lr_native, ratio, k prior
        depth = None
        if pd.notna(s.depth_min_m) and pd.notna(s.depth_max_m):
            depth = (abs(float(s.depth_min_m)) + abs(float(s.depth_max_m))) / 2
        elif pd.notna(s.depth_max_m):
            depth = abs(float(s.depth_max_m))
        bw = beamwidth(str(s.lr_sonar))
        r["lr_beamwidth_deg"] = bw
        r["lr_native_doc_m"] = round(2 * depth * math.tan(math.radians(bw / 2)), 1) if (depth and bw) else None
        hr_res = float(s.hr_native_res_m) if pd.notna(s.hr_native_res_m) else None
        r["ratio_doc"] = round(r["lr_native_doc_m"] / hr_res, 1) if (r["lr_native_doc_m"] and hr_res) else None
        if r["ratio_doc"]:
            k = 2 ** int(round(math.log2(max(r["ratio_doc"], 1e-6) / 5.0)))
            r["k_prior"] = int(min(16, max(2, k)))
        else:
            r["k_prior"] = None
        # leakage relations
        lrs = lr_cruises_of.get(h, [str(s.lr_cruise_id)])
        r["lr_cruises_all"] = ";".join(lrs)
        joins = set()
        if r["hr_cruise"] in hr_cruise_units:
            joins |= hr_cruise_units[r["hr_cruise"]]
        for cr in lrs:
            joins |= lr_cruise_units.get(cr, set())
        near = [pid for pid, cc in cents.items() if hav_km((r["lon"], r["lat"]), cc) <= R_KM]
        joins |= {unit_of[p] for p in near if p in unit_of}
        lock = bool(set(lrs) & lockbox_lr) or r["hr_cruise"] in LOCKBOX_HR_CRUISES or any(p in C.LOCKBOX for p in near)
        r["joins_existing_units"] = ";".join(sorted(joins - {None})) if joins else ""
        r["near_existing_pairs_50km"] = ";".join(near)
        r["shares_lockbox"] = lock
        rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "candidates_gated.csv", index=False)

    new = df[df.status == "new_candidate"].copy()
    new_free = new[~new.shares_lockbox & (new.joins_existing_units == "")].copy()
    # new leakage units among free candidates: shared HR cruise, shared LR cruise, <= 50 km
    uf = UF(list(new_free.hr_id))
    recs = new_free.to_dict("records")
    for i, a in enumerate(recs):
        for b in recs[i + 1:]:
            if (a["hr_cruise"] and a["hr_cruise"] == b["hr_cruise"]) or \
               set(a["lr_cruises_all"].split(";")) & set(b["lr_cruises_all"].split(";")) or \
               hav_km((a["lon"], a["lat"]), (b["lon"], b["lat"])) <= R_KM:
                uf.union(a["hr_id"], b["hr_id"])
    groups = {}
    for a in recs:
        groups.setdefault(uf.find(a["hr_id"]), []).append(a)
    # LR cruise volumes for the new units (autoindex sizes; cached)
    sizes = {}
    for members in groups.values():
        for cr in {mm["best_lr"] for mm in members}:
            if cr in sizes:
                continue
            try:
                iso = data_dir_from_iso(cr, CACHE / "geoportal")
                url, _ = resolve_data_dir(iso, CACHE / "ncei_dirlist") if iso else (None, "")
                sizes[cr] = size_cruise(cr, url, CACHE / "ncei_dirlist").total_bytes if url else None
            except Exception as e:
                log.warning("size %s: %s", cr, e); sizes[cr] = None
    units = []
    for k, (root, members) in enumerate(sorted(groups.items(), key=lambda kv: min(mm["hr_id"] for mm in kv[1]))):
        members = sorted(members, key=lambda mm: mm["hr_id"])
        settings = sorted({mm["terrain_hint"] for mm in members})
        dmin = min((mm["depth_min_m"] for mm in members if pd.notna(mm["depth_min_m"])), default=None)
        dmax = max((mm["depth_max_m"] for mm in members if pd.notna(mm["depth_max_m"])), default=None)
        lr_gb = sum((sizes.get(cr) or 0) for cr in {mm["best_lr"] for mm in members}) / 1e9
        hr_gb = sum((mm["hr_bytes"] or 0) for mm in members) / 1e9
        units.append({"unit_id": f"nu{k:02d}", "members": [mm["hr_id"] for mm in members],
                      "n_candidates": len(members), "basin": members[0]["basin"],
                      "setting": settings[0] if len(settings) == 1 else "mixed:" + "|".join(settings),
                      "depth_min_m": dmin, "depth_max_m": dmax,
                      "ship_cruises": sorted({mm["best_lr"] for mm in members}),
                      "hr_sources": [{"hr_id": mm["hr_id"], "doi": mm["hr_doi"], "title": mm["hr_title"], "platform": mm["hr_platform"],
                                      "gate_tier": mm["gate_tier"], "footprint_suspect": mm["footprint_suspect"]} for mm in members],
                      "est_volume_gb": {"hr": round(hr_gb, 2), "lr_raw_swath": round(lr_gb, 2) if lr_gb else None,
                                        "lr_cruise_sizes_gb": {cr: (round(sizes[cr] / 1e9, 2) if sizes.get(cr) else None) for cr in {mm["best_lr"] for mm in members}}},
                      "lr_native_doc_m": [mm["lr_native_doc_m"] for mm in members],
                      "ratio_doc": [mm["ratio_doc"] for mm in members], "k_prior": [mm["k_prior"] for mm in members],
                      "lon": round(members[0]["lon"], 3), "lat": round(members[0]["lat"], 3)})
    counts = {
        "hr_in_selection": int(len(df)), "status_counts": df.status.value_counts().to_dict(),
        "new_candidates_by_gate_tier": new.gate_tier.value_counts().to_dict(),
        "new_candidates_by_source_tier": {"MGDS (Tier 3 US fleet)": int(new.hr_id.str.startswith("MGDS:").sum()),
                                          "other": int((~new.hr_id.str.startswith("MGDS:")).sum())},
        "new_candidates_by_k_prior": new.k_prior.value_counts(dropna=False).to_dict(),
        "new_candidates_footprint_unverified": int(new.footprint_suspect.sum()),
        "join_existing_unit": int(((new.joins_existing_units != "") & ~new.shares_lockbox).sum()),
        "shares_lockbox": int(new.shares_lockbox.sum()),
        "new_leakage_units": len(units),
        "new_units_by_setting": pd.Series([u["setting"] for u in units]).value_counts().to_dict() if units else {},
        "new_units_by_basin": pd.Series([u["basin"] for u in units]).value_counts().to_dict() if units else {},
    }
    C.write_json(OUT / "new_units.json", {"generated": STAMP, "policy": "conservative: shared HR survey OR shared LR cruise OR centroid<=50km",
                                            "units": units, "counts": counts})
    new[(new.joins_existing_units != "") & ~new.shares_lockbox].to_csv(OUT / "joins_existing_units.csv", index=False)
    new[new.shares_lockbox].to_csv(OUT / "shares_lockbox.csv", index=False)
    md = ["# Discovery re-run — counts only (ACQ-R01 §3)\n", f"Catalog date {STAMP}. HR in stage-A selection: {counts['hr_in_selection']}.\n",
          "| status | n |", "|---|---|"] + [f"| {k} | {v} |" for k, v in counts["status_counts"].items()]
    md += ["", "New candidates by June gate tier: " + json.dumps(counts["new_candidates_by_gate_tier"]),
           "New candidates by k prior (empirical, ±1 octave): " + json.dumps(counts["new_candidates_by_k_prior"]),
           f"Footprint unverified (metadata bbox, > plausible AUV area): {counts['new_candidates_footprint_unverified']}",
           f"Join an existing unit (shared acquisition / ≤50 km): {counts['join_existing_unit']} · share acquisition with a lockbox pair: {counts['shares_lockbox']}",
           f"**New leakage units: {counts['new_leakage_units']}** by setting {json.dumps(counts['new_units_by_setting'])}; by basin {json.dumps(counts['new_units_by_basin'])}", "",
           "| unit | n | basin | setting | depth (m) | ship cruise(s) | HR source | est. vol GB (HR / LR raw) | lr_native doc (m) | ratio | k prior |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for u in units:
        md.append(f"| {u['unit_id']} | {u['n_candidates']} | {u['basin']} | {u['setting']} | {u['depth_min_m']}–{u['depth_max_m']} | {', '.join(u['ship_cruises'])} | "
                  f"{'; '.join(h['hr_id'] + ' ' + (h['doi'] or '') for h in u['hr_sources'])} | {u['est_volume_gb']['hr']} / {u['est_volume_gb']['lr_raw_swath']} | "
                  f"{u['lr_native_doc_m']} | {u['ratio_doc']} | {u['k_prior']} |")
    md += ["", "## Candidates joining an EXISTING unit (neither development nor confirmatory)", "", "| hr_id | title | best LR | joins | near pairs |", "|---|---|---|---|---|"]
    md += [f"| {r.hr_id} | {r.hr_title[:60]} | {r.best_lr} | {r.joins_existing_units} | {r.near_existing_pairs_50km} |" for _, r in new[(new.joins_existing_units != "") & ~new.shares_lockbox].iterrows()]
    md += ["", "## Candidates sharing acquisition with a LOCKBOX pair (excluded from §4)", "", "| hr_id | title | HR cruise | LR cruises |", "|---|---|---|---|"]
    md += [f"| {r.hr_id} | {r.hr_title[:60]} | {r.hr_cruise} | {r.lr_cruises_all} |" for _, r in new[new.shares_lockbox].iterrows()]
    (OUT / "discovery_counts.md").write_text("\n".join(md))
    print("\n".join(md[:20])); print(json.dumps(counts, indent=1))


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--skip-harvest", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    m = C.load_manifest()
    if not a.skip_harvest:
        harvest(m)
    gate(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
