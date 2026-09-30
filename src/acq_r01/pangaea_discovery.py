"""ACQ-R02 §4 — PANGAEA discovery of AUV bathymetry + independent ship multibeam (metadata only).

Harvest (PANGAEA Elasticsearch endpoint, the same service pangaeapy uses): AUV bathymetry datasets
(Abyss, SEAL, REMUS, HUGIN, Sentry, ... — title/abstract regex, not a fixed list) and ship multibeam
datasets that offer RAW swath ("with links to raw data files", "raw data", EM12x/EM7xx/EM30x/Hydrosweep).
Pair every AUV dataset with independent ship multibeam over its bbox: PANGAEA raw swath (preferred,
same cruise first) or NCEI MBBDB surveys (cached footprints from ACQ-R01 §5).  Anti-circularity:
ship candidates whose title/abstract say combined / merged / compiled / AUV are excluded as LR.

Gate + leakage: exclude AUV datasets already in the corpus (DOI), the conservative policy (shared HR
cruise, shared LR cruise, centroid <= 50 km) against the corpus (37 footprint centroids + lockbox
centroids + LR cruises), the ACQ-R01 candidates and the H1 set.  Candidates sharing a cruise with or
within 50 km of DISCOL / CCZ / TAG (SO242/1, SO268/1, M127) JOIN those units (development, not
designated).  Nothing is downloaded.

Outputs: reports_post_grl_review/ACQ-R02/discovery_pangaea/{auv_datasets,ship_datasets,candidates}.csv,
new_units.json (input for designate_confirmatory.py --seed 20260930), discovery_pangaea.md
"""
from __future__ import annotations

import json
import logging
import math
import re
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import box

from src.acq_r01 import common as C
from src.acq_r01.discovery_rerun import basin, hav_km, UF

log = logging.getLogger("acq_r02.pangaea")
ES = "https://ws.pangaea.de/es/pangaea/panmd/_search"
H = {"User-Agent": "auv-ship-acq/0.4 (Sherlock; ACQ-R02 PANGAEA discovery; stephencoledobbs@gmail.com)"}
OUT = C.REPO / "reports_post_grl_review" / "ACQ-R02" / "discovery_pangaea"
CACHE = C.SCRATCH_DATA / "discovery_cache" / "acq_r02_pangaea_v2"   # v1 cache held char-split campaign ids
R01 = C.REPO / "reports_post_grl_review" / "ACQ-R01"
R_KM = 50.0

AUV_QUERIES = ['"AUV" bathymetry', '"AUV Abyss"', '"AUV ABYSS" bathymetry', '"MARUM-SEAL"', '"AUV SEAL"', '"REMUS" bathymetry',
               '"HUGIN" bathymetry', '"Sentry" bathymetry', '"AsterX" bathymetry', '"Girona 500"', '"autonomous underwater vehicle" bathymetry',
               'AUV multibeam processed data', 'AUV "working area dataset"', '"near-bottom" bathymetry AUV', 'AUV "high resolution bathymetry"',
               '"Kongsberg EM 2040" AUV', '"SeaBat" AUV bathymetry']
SHIP_QUERIES = ['"with links to raw data files" multibeam', '"multibeam bathymetry raw data"', '"Raw multibeam" EM122', '"raw data" EM120',
                '"raw data" EM710', '"raw data" EM302', '"raw data" EM304', '"raw data" EM124', '"raw data" Hydrosweep', '"swath sonar" bathymetry raw',
                '"Multibeam bathymetry processed data" Kongsberg', '"working area dataset" EM122']
AUV_RE = re.compile(r"\b(AUV|Abyss|ABYSS|MARUM-SEAL|SEAL|REMUS|HUGIN|Sentry|AsterX|Girona|autonomous underwater)\b")
BATHY_RE = re.compile(r"bathymetr|multibeam|MBES|\bgrid", re.I)
HR_EXCL_RE = re.compile(r"sensor data|CTD|turbidity|photo|image|mosaic|video|sidescan|side-scan|ParaSound|sediment echo|water column|magnetic|flow rate|fish|calving|"
                        r"backscatter (data|processed)|navigation|track|USBL|position", re.I)
SHIP_SONAR_RE = re.compile(r"EM ?\d{3,4}|Hydrosweep|SeaBeam|multibeam|swath sonar", re.I)
RAW_RE = re.compile(r"raw data|links to raw|RAW-Data|entire dataset", re.I)
COMPOSITE_RE = re.compile(r"combined|merged|compil|GEBCO|GMRT|synthesis|integrat", re.I)
SETTING_RE = [(re.compile(r"vent|hydrothermal|black smoker|TAG|Lucky Strike|Menez|Logatchev", re.I), "hydrothermal_vent"),
              (re.compile(r"nodule|abyssal|plain|CCZ|Clarion|Peru Basin|DISCOL", re.I), "abyssal_plain"),
              (re.compile(r"seamount|volcan|caldera|ridge|rift|spreading|arc\b|Etna|Kolumbo|Santorini", re.I), "volcanic_or_seamount"),
              (re.compile(r"canyon|slope|margin|shelf|fjord|pockmark|seep|mud volcano|delta|estuar|bay\b|harbour|harbor", re.I), "continental_margin"),
              (re.compile(r"polar|Arctic|Antarctic|ice|glacier", re.I), "polar")]
DEPTH_RE = re.compile(r"(\d{3,4})\s*(?:-|–|to)\s*(\d{3,4})\s*m\b|(\d{3,4})\s*m water depth|depth of (?:about |~)?(\d{3,4})\s*m", re.I)
RES_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:m|meter|metre)s?\s*(?:resolution|grid|cell)|resolution of (\d+(?:\.\d+)?)\s*m|(\d+(?:\.\d+)?)\s*m\s+resolution", re.I)
CAMPAIGN_NORM = {"SO242/1": "SO242/1", "SO242-1": "SO242/1", "SO268/1": "SO268/1", "SO268-1": "SO268/1", "M127": "M127"}


def es_all(q: str, size: int = 500, cap: int = 10000):
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / (re.sub(r"[^A-Za-z0-9]+", "_", q)[:80] + ".json")
    if cache.exists():
        return json.loads(cache.read_text())
    hits, frm = [], 0
    while frm < cap:
        r = requests.get(ES, params={"q": q, "size": size, "from": frm}, headers=H, timeout=120)
        if r.status_code != 200:
            log.warning("ES %s from=%d -> %s", q, frm, r.status_code); break
        j = r.json(); h = j.get("hits", {}).get("hits", [])
        hits += h
        if len(h) < size:
            break
        frm += size; time.sleep(0.4)
    recs = [parse_hit(x) for x in hits]
    cache.write_text(json.dumps(recs))
    return recs


def _xml_field(xml: str, tag: str) -> str:
    m = re.search(rf"<md:{tag}>(.*?)</md:{tag}>", xml, re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _agg(v):
    """ES aggregate fields come back as a list OR a single string; never split a string into chars."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return ";".join(str(x) for x in v)


def parse_hit(h):
    s = h["_source"]; xml = s.get("xml", "")
    return {"id": str(h["_id"]), "doi": (s.get("URI") or "").replace("https://doi.org/", ""),
            "title": _xml_field(xml, "title"), "abstract": _xml_field(xml, "abstract")[:1500],
            "west": s.get("westBoundLongitude"), "east": s.get("eastBoundLongitude"), "south": s.get("southBoundLatitude"), "north": s.get("northBoundLatitude"),
            "start": s.get("minDateTime"), "campaigns": _agg(s.get("agg-campaign")), "basis": _agg(s.get("agg-basis")),
            "method": _agg(s.get("agg-method"))[:200], "n_points": s.get("nDataPoints")}


def harvest(queries, kind):
    seen, out = set(), []
    for q in queries:
        recs = es_all(q)
        for r in recs:
            if r["id"] in seen:
                continue
            seen.add(r["id"]); r["query"] = q; out.append(r)
        log.info("%s query %r -> %d (cum %d)", kind, q, len(recs), len(out))
    return pd.DataFrame(out)


def classify_auv(df):
    t = (df.title.fillna("") + " | " + df.abstract.fillna(""))
    is_auv = df.title.fillna("").str.contains(AUV_RE) | df.method.fillna("").str.contains(AUV_RE) | df.basis.fillna("").str.contains(AUV_RE)
    bathy = df.title.fillna("").str.contains(BATHY_RE)
    excl = df.title.fillna("").str.contains(HR_EXCL_RE)
    df = df[is_auv & bathy & ~excl].copy()
    df["hr_raw_only"] = df.title.str.contains(RAW_RE) & ~df.title.str.contains(r"processed|grid|raster|working area", case=False)
    df["hr_platform"] = df.title.str.extract(AUV_RE)[0]
    df["setting"] = [next((name for rx, name in SETTING_RE if rx.search(x)), "unknown") for x in t[df.index]]
    dep = t[df.index].str.extract(DEPTH_RE)
    df["depth_min_m"] = pd.to_numeric(dep[0].fillna(dep[2]).fillna(dep[3]), errors="coerce")
    df["depth_max_m"] = pd.to_numeric(dep[1].fillna(dep[2]).fillna(dep[3]), errors="coerce")
    res = t[df.index].str.extract(RES_RE)
    df["hr_res_m"] = pd.to_numeric(res[0].fillna(res[1]).fillna(res[2]), errors="coerce")
    df["title_mentions_ship"] = df.title.str.contains(r"ship|hull|RV |R/V|EM ?12\d|EM ?30\d|EM ?71\d", case=False)
    for c in ("west", "east", "south", "north"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["west", "east", "south", "north"])
    df["bbox_deg2"] = (df.east - df.west) * (df.north - df.south)
    df["lon"] = (df.west + df.east) / 2; df["lat"] = (df.south + df.north) / 2
    return df


def classify_ship(df):
    t = df.title.fillna("")
    keep = t.str.contains(SHIP_SONAR_RE) & ~t.str.contains(AUV_RE) & ~t.str.contains(COMPOSITE_RE) & ~df.abstract.fillna("").str.contains(r"\bAUV\b|autonomous underwater", case=False)
    df = df[keep].copy()
    df["lr_kind"] = np.where(df.title.str.contains(RAW_RE), "pangaea_raw_swath", "pangaea_processed_grid")
    df["sonar"] = df.title.str.extract(r"(EM ?\d{3,4}(?:\s*MK\s*II)?|Hydrosweep(?: DS(?:-2)?)?|SeaBeam ?\d*)", flags=re.I)[0].str.replace(" ", "", regex=False).str.upper()
    for c in ("west", "east", "south", "north"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["west", "east", "south", "north"])
    df["bbox_deg2"] = (df.east - df.west) * (df.north - df.south)
    return df


def corpus_context():
    m = C.load_manifest()
    cents = json.loads((R01 / "discovery_rerun" / "seed_centroids.json").read_text())
    dois = {str(d).replace("https://doi.org/", "") for d in m.hr_doi.dropna()} | {str(d) for d in m.hr_superseded_doi.dropna() if d}
    lr_cruises = {str(x) for x in m.lr_cruise} | {"SO242/1", "SO268/1", "M127"}
    hr_cruises = {str(x) for x in m.cruise_id}
    unit_of_lr = {}
    for _, r in m.iterrows():
        unit_of_lr.setdefault(str(r.lr_cruise), set()).add(r.leakage_unit)
        unit_of_lr.setdefault(str(r.cruise_id), set()).add(r.leakage_unit)
    unit_of_pair = dict(zip(m.pair_id, m.leakage_unit))
    # ACQ-R01 candidates + H1 (June catalog centroids)
    cg = pd.read_csv(R01 / "discovery_rerun" / "candidates_gated.csv")
    r01 = cg[cg.status == "new_candidate"][["hr_id", "lon", "lat", "best_lr", "lr_cruises_all"]]
    old = gpd.read_file(C.REPO / "reports/discovery/hr_catalog.gpkg", layer="hr").set_index("hr_id")
    h1 = ["MGDS:24002", "MGDS:31321", "MGDS:31813", "MGDS:31814", "MGDS:31831", "MGDS:20815", "MGDS:21847", "MGDS:31073", "MGDS:31291", "MGDS:5174", "MGDS:24467"]
    sel = gpd.read_file(C.REPO / "reports/discovery/stage_a_selection.gpkg").set_index("hr_id")
    h1rows = [{"hr_id": h, "lon": old.loc[h].geometry.centroid.x, "lat": old.loc[h].geometry.centroid.y,
               "best_lr": sel.loc[h, "lr_cruise_id"] if h in sel.index else "", "lr_cruises_all": sel.loc[h, "lr_cruise_id"] if h in sel.index else ""} for h in h1 if h in old.index]
    return m, cents, dois, lr_cruises, hr_cruises, unit_of_lr, unit_of_pair, r01, pd.DataFrame(h1rows)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    auv_raw = harvest(AUV_QUERIES, "AUV"); ship_raw = harvest(SHIP_QUERIES, "ship")
    auv = classify_auv(auv_raw); ship = classify_ship(ship_raw)
    auv.to_csv(OUT / "auv_datasets.csv", index=False); ship.to_csv(OUT / "ship_datasets.csv", index=False)
    log.info("AUV bathymetry datasets: %d (of %d hits); ship raw/processed datasets: %d (of %d)", len(auv), len(auv_raw), len(ship), len(ship_raw))
    ncei = gpd.read_file(C.SCRATCH_DATA / "discovery_cache" / "acq_r01_2026-09-29" / "ncei_all_footprints.geojson")
    ncei = ncei[~(ncei.PLATFORM.fillna("") + " " + ncei.INSTRUMENT.fillna("")).str.contains(r"\bAUV\b|ROV|Sentry|REMUS|HUGIN|glider", case=False)]
    m, cents, dois, corpus_lr, corpus_hr, unit_of_lr, unit_of_pair, r01, h1 = corpus_context()
    lock_c = {p: cents[p] for p in C.LOCKBOX if p in cents}
    rows = []
    for _, a in auv.iterrows():
        rec = {k: a[k] for k in ("id", "doi", "title", "campaigns", "basis", "hr_platform", "hr_raw_only", "setting", "depth_min_m", "depth_max_m", "hr_res_m",
                                 "bbox_deg2", "lon", "lat", "title_mentions_ship", "start")}
        rec["basin"] = basin(a.lon, a.lat)
        bb = box(a.west - 0.02, a.south - 0.02, a.east + 0.02, a.north + 0.02)
        camp = {CAMPAIGN_NORM.get(c, c) for c in str(a.campaigns).split(";") if c}
        # ship candidates: PANGAEA (bbox intersect) then NCEI (polygon intersect)
        sh = ship[(ship.west <= bb.bounds[2]) & (ship.east >= bb.bounds[0]) & (ship.south <= bb.bounds[3]) & (ship.north >= bb.bounds[1])].copy()
        sh["same_cruise"] = sh.campaigns.fillna("").apply(lambda s: bool(camp & {CAMPAIGN_NORM.get(c, c) for c in s.split(";") if c}))
        # transit-scale raw datasets (bbox > 30 deg^2) are only a plausible LR when they are the AUV's own cruise
        sh = sh[sh.same_cruise | (sh.bbox_deg2 <= 30.0)]
        sh = sh.sort_values(["same_cruise", "lr_kind", "bbox_deg2"], ascending=[False, False, True])
        nc = ncei[ncei.intersects(bb)]
        lr_opts = [f"PANGAEA:{r.id}|{r.lr_kind}|{r.sonar}|{'same_cruise' if r.same_cruise else 'other'}|{';'.join(str(r.campaigns).split(';')[:2])}" for _, r in sh.head(6).iterrows()]
        lr_opts += [f"NCEI:{r.SURVEY_ID}|ncei_raw|{r.INSTRUMENT}|{r.PLATFORM}" for _, r in nc.head(8).iterrows()]
        rec["lr_options"] = " || ".join(lr_opts); rec["n_lr_pangaea"] = int(len(sh)); rec["n_lr_ncei"] = int(len(nc))
        lr_cruises = {CAMPAIGN_NORM.get(c, c) for _, r in sh[sh.same_cruise | (sh.bbox_deg2 <= 5.0)].iterrows() for c in str(r.campaigns).split(";") if c} | set(nc.SURVEY_ID.astype(str))
        rec["lr_cruises_all"] = ";".join(sorted(lr_cruises))
        if sh.empty and nc.empty:
            rec["status"] = "no_independent_ship_lr"
        elif rec["doi"] in dois:
            rec["status"] = "in_corpus"
        elif a.hr_raw_only:
            rec["status"] = "hr_raw_only"          # AUV soundings only; would need gridding (not a grid product)
        else:
            rec["status"] = "candidate"
        best = sh.iloc[0] if not sh.empty else None
        rec["best_lr"] = (f"PANGAEA:{best.id}" if best is not None else (f"NCEI:{nc.iloc[0].SURVEY_ID}" if not nc.empty else ""))
        rec["best_lr_kind"] = (best.lr_kind if best is not None else ("ncei_raw" if not nc.empty else ""))
        rec["best_lr_sonar"] = (best.sonar if best is not None else (nc.iloc[0].INSTRUMENT if not nc.empty else ""))
        # leakage vs corpus / lockbox / R01 / H1
        joins = set()
        for cr in (camp | lr_cruises):
            joins |= unit_of_lr.get(cr, set())
        near = [pid for pid, cc in cents.items() if hav_km((a.lon, a.lat), cc) <= R_KM]
        joins |= {unit_of_pair[p] for p in near if p in unit_of_pair}
        rec["near_corpus_pairs"] = ";".join(near); rec["joins_existing_units"] = ";".join(sorted(joins))
        rec["near_r01_candidates"] = ";".join(r01[r01.apply(lambda r: hav_km((a.lon, a.lat), (r.lon, r.lat)) <= R_KM, axis=1)].hr_id) if len(r01) else ""
        rec["near_h1"] = ";".join(h1[h1.apply(lambda r: hav_km((a.lon, a.lat), (r.lon, r.lat)) <= R_KM, axis=1)].hr_id) if len(h1) else ""
        rec["shares_lockbox"] = bool((camp | lr_cruises) & set(C.LOCKBOX_LR_CRUISES) | (camp & {"AT42-03", "AT15-36"})) or any(hav_km((a.lon, a.lat), cc) <= R_KM for cc in lock_c.values())
        rows.append(rec)
    cand = pd.DataFrame(rows)
    cand.to_csv(OUT / "candidates.csv", index=False)
    new = cand[(cand.status == "candidate") & ~cand.shares_lockbox & (cand.joins_existing_units == "") & (cand.near_r01_candidates == "") & (cand.near_h1 == "")].copy()
    # units among the new candidates: shared campaign, shared LR cruise, <= 50 km
    uf = UF(list(new.id)); recs = new.to_dict("records")
    for i, x in enumerate(recs):
        for y in recs[i + 1:]:
            cx = {c for c in str(x["campaigns"]).split(";") if c}; cy = {c for c in str(y["campaigns"]).split(";") if c}
            lx = {x["best_lr"]} if x["best_lr"] else set(); ly = {y["best_lr"]} if y["best_lr"] else set()
            if (cx & cy) or (lx & ly) or hav_km((x["lon"], x["lat"]), (y["lon"], y["lat"])) <= R_KM:
                uf.union(x["id"], y["id"])
    groups = {}
    for x in recs:
        groups.setdefault(uf.find(x["id"]), []).append(x)
    units = []
    for k, (root, mem) in enumerate(sorted(groups.items(), key=lambda kv: min(mm["id"] for mm in kv[1]))):
        mem = sorted(mem, key=lambda mm: mm["id"])
        settings = sorted({mm["setting"] for mm in mem})
        units.append({"unit_id": f"pu{k:02d}", "members": [f"PANGAEA:{mm['id']}" for mm in mem], "n_candidates": len(mem),
                      "basin": mem[0]["basin"], "setting": settings[0] if len(settings) == 1 else "mixed:" + "|".join(settings),
                      "depth_min_m": min((mm["depth_min_m"] for mm in mem if pd.notna(mm["depth_min_m"])), default=None),
                      "depth_max_m": max((mm["depth_max_m"] for mm in mem if pd.notna(mm["depth_max_m"])), default=None),
                      "ship_cruises": sorted({mm["best_lr"] for mm in mem}),
                      "hr_sources": [{"hr_id": f"PANGAEA:{mm['id']}", "doi": mm["doi"], "title": mm["title"][:100], "platform": mm["hr_platform"],
                                      "campaigns": mm["campaigns"], "best_lr": mm["best_lr"], "best_lr_kind": mm["best_lr_kind"]} for mm in mem],
                      "lon": round(mem[0]["lon"], 3), "lat": round(mem[0]["lat"], 3)})
    counts = {"auv_hits": int(len(auv_raw)), "auv_bathymetry_datasets": int(len(auv)), "ship_hits": int(len(ship_raw)), "ship_datasets": int(len(ship)),
              "status_counts": cand.status.value_counts().to_dict(), "shares_lockbox": int(cand.shares_lockbox.sum()),
              "join_existing_units": int(((cand.status == "candidate") & (cand.joins_existing_units != "") & ~cand.shares_lockbox).sum()),
              "near_r01_or_h1": int(((cand.status == "candidate") & ((cand.near_r01_candidates != "") | (cand.near_h1 != "")) & (cand.joins_existing_units == "")).sum()),
              "new_units": len(units), "new_units_by_setting": pd.Series([u["setting"] for u in units]).value_counts().to_dict() if units else {},
              "new_units_by_basin": pd.Series([u["basin"] for u in units]).value_counts().to_dict() if units else {}}
    C.write_json(OUT / "new_units.json", {"generated": "2026-09-30", "source": "PANGAEA", "policy": "conservative: shared HR cruise OR shared LR cruise OR centroid<=50km", "units": units, "counts": counts})
    md = ["# PANGAEA discovery (ACQ-R02 §4, metadata only)\n", json.dumps(counts, indent=1), "",
          "| unit | n | basin | setting | depth | best LR | HR (PANGAEA id, platform, campaign) |", "|---|---|---|---|---|---|---|"]
    md += [f"| {u['unit_id']} | {u['n_candidates']} | {u['basin']} | {u['setting']} | {u['depth_min_m']}–{u['depth_max_m']} | {', '.join(u['ship_cruises'])} | " +
           "; ".join(f"{h['hr_id']} {h['platform']} {h['campaigns']}" for h in u["hr_sources"]) + " |" for u in units]
    md += ["", "## Candidates joining EXISTING units (DISCOL / CCZ / TAG / others)", "", "| id | title | campaigns | joins | near |", "|---|---|---|---|---|"]
    md += [f"| {r.id} | {r.title[:70]} | {r.campaigns} | {r.joins_existing_units} | {r.near_corpus_pairs} |" for _, r in cand[(cand.status == "candidate") & (cand.joins_existing_units != "")].iterrows()]
    md += ["", "## Candidates near ACQ-R01 / H1 candidates (handled in §5 leakage re-run)", "", "| id | title | near R01 | near H1 |", "|---|---|---|---|"]
    md += [f"| {r.id} | {r.title[:70]} | {r.near_r01_candidates} | {r.near_h1} |" for _, r in cand[(cand.status == "candidate") & (cand.joins_existing_units == "") & ((cand.near_r01_candidates != "") | (cand.near_h1 != ""))].iterrows()]
    md += ["", "## Lockbox-sharing (excluded)", "", "| id | title |", "|---|---|"] + [f"| {r.id} | {r.title[:70]} |" for _, r in cand[cand.shares_lockbox].iterrows()]
    (OUT / "discovery_pangaea.md").write_text("\n".join(md))
    print("\n".join(md[:60]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
