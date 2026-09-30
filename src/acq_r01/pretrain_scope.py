"""ACQ-R01 §5 — pretraining-corpus scoping (report only; NO swath downloads).

What ship-only multibeam exists at NCEI MBBDB outside the exclusion zones?
  1. Enumerate every survey in the NCEI 'Multibeam Footprints' ArcGIS layer (raw per-cruise
     surveys; the separate 'Multibeam Products' layer = composites/products is not used).
  2. Keep ship platforms only (drop AUV/ROV/USV/glider entries by platform/instrument text).
  3. Exclusion zones: (a) every LR cruise of every corpus pair (39 incl. lockbox), of every §3
     candidate (new units + joins) - dropped by survey id; (b) the 10-km-buffered footprints of
     the 37 non-lockbox pair overlaps (OAK footprint.geojson) + §3 candidate HR footprints + the
     NCEI cruise footprints of the two lockbox LR cruises (metadata; no lockbox file opened);
     (c) composites: excluded by construction (raw-survey layer only; GMRT never enters).
  4. Volume / format / depth from a stratified sample of surveys (autoindex sizes + .inf files),
     extrapolated per instrument family.  Only small metadata files are fetched.
Usage (Slurm): python -m src.acq_r01.pretrain_scope [--sample 240]
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from shapely.geometry import shape

from src.acq_r01 import common as C
from src.discovery.raw_lr_dryrun import data_dir_from_iso, resolve_data_dir, size_cruise, _list_dir, _ROW
from src.discovery.geoportal import _GEOPORTAL_BASE

log = logging.getLogger("acq_r01.pretrain")
LAYER = "https://gis.ngdc.noaa.gov/arcgis/rest/services/multibeam_footprints/MapServer/0/query"
H = {"User-Agent": "auv-ship-acq/0.3 (Sherlock; ACQ-R01 pretraining scoping; stephencoledobbs@gmail.com)"}
CACHE = C.SCRATCH_DATA / "discovery_cache" / "acq_r01_2026-09-29"
OUT = C.REPORT_DIR / "pretrain_scope"
NON_SHIP = re.compile(r"\bAUV\b|ROV|Sentry|REMUS|HUGIN|Mapping AUV|glider|USV|Saildrone|submersible|Jason|Alvin|Dorado", re.I)
FAMILIES = [("EM122|EM120|EM124", "Kongsberg EM12x (deep)"), ("EM302|EM304|EM300", "Kongsberg EM30x"),
            ("EM710|EM712|EM1002|EM2040|EM3002|EM3000|EM1000|EM100", "Kongsberg EM7xx/EM1xxx/EM2040 (shallow)"),
            ("SeaBeam 2112|SeaBeam 2100|SeaBeam 2000|Seabeam 21|SeaBeam 3012|SeaBeam 3050|SeaBeam", "SeaBeam family"),
            ("Hydrosweep", "Atlas Hydrosweep"), ("Reson", "Reson"), ("ELAC|Elac", "ELAC"), ("", "other/unknown")]
GRIDDABLE_EXT = re.compile(r"\.all\.mb5[689]\.gz$|\.all\.gz$|\.all$|\.gsf(\.mb121)?(\.gz)?$|\.mb(41|42|56|57|58|59|88|121|183|24|21)(\.gz)?$|\.mb\d+(\.gz)?$", re.I)


def family(instr: str) -> str:
    for pat, name in FAMILIES:
        if pat and re.search(pat, instr or "", re.I):
            return name
    return "other/unknown"


def fetch_all_footprints() -> gpd.GeoDataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / "ncei_all_footprints.geojson"
    if cache.exists():
        return gpd.read_file(cache)
    feats, off, page = [], 0, 250
    while True:
        # small pages + simplified geometry (maxAllowableOffset ~0.01 deg): the full-detail
        # 2000-record page returns HTTP 500 from the NCEI server.
        p = {"where": "1=1", "outFields": "NCEI_ID,SURVEY_ID,PLATFORM,SOURCE,INSTRUMENT,SURVEY_YEAR,START_TIME,END_TIME,Version,DOWNLOAD_URL,SURVEY_AND_VERSION",
             "returnGeometry": "true", "outSR": "4326", "f": "geojson", "resultOffset": off, "resultRecordCount": page,
             "maxAllowableOffset": 0.01, "geometryPrecision": 4, "orderByFields": "OBJECTID"}
        f = None
        for attempt in range(5):
            try:
                r = requests.get(LAYER, params=p, headers=H, timeout=300)
                if r.status_code >= 500:
                    time.sleep(10 * (attempt + 1)); continue
                r.raise_for_status(); j = r.json(); f = j.get("features", []); break
            except Exception as e:
                log.warning("page offset=%d attempt %d: %s", off, attempt, e); time.sleep(10 * (attempt + 1))
        if f is None:
            raise RuntimeError(f"NCEI footprints page at offset {off} failed after retries")
        feats += f
        log.info("footprints page offset=%d n=%d", off, len(f))
        if len(f) < page:
            break
        off += page; time.sleep(0.5)
    gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    gdf.to_file(cache, driver="GeoJSON")
    return gdf


def exclusion_geometry(m: pd.DataFrame, cand: pd.DataFrame | None, ncei: gpd.GeoDataFrame):
    geoms = []
    for _, r in m.iterrows():
        if r.pair_id in C.LOCKBOX:
            continue
        geoms.append(gpd.read_file(C.pair_dir_oak(r) / "footprint.geojson").to_crs("EPSG:4326").geometry.union_all())
    n_pairs = len(geoms)
    lock = ncei[ncei.SURVEY_ID.isin(C.LOCKBOX_LR_CRUISES)]
    geoms += list(lock.geometry)
    n_cand = 0
    if cand is not None and len(cand):
        gj = gpd.GeoDataFrame(cand, geometry=gpd.points_from_xy(cand.lon, cand.lat), crs="EPSG:4326")
        # candidate HR footprints: use the gated catalog geometry where available, else a 5 km disc
        hrc = gpd.read_file(C.REPORT_DIR / "discovery_rerun" / "hr_catalog.gpkg", layer="hr").set_index("hr_id")
        for _, r in cand.iterrows():
            g = hrc.loc[r.hr_id].geometry if r.hr_id in hrc.index else None
            geoms.append(g if g is not None else gj.loc[_].geometry.buffer(0.05)); n_cand += 1
    gs = gpd.GeoSeries(geoms, crs="EPSG:4326").to_crs("EPSG:6933").buffer(10_000).to_crs("EPSG:4326")
    return gs.union_all(), {"pair_footprints": n_pairs, "lockbox_lr_cruise_footprints": int(len(lock)), "candidate_footprints": n_cand}


def sample_survey(sid: str, url_hint: str):
    """Size + format + depth for one survey from autoindex + up to 3 .inf files."""
    rec = {"survey": sid, "status": "ok", "bytes": None, "n_swath": 0, "n_files": 0, "ext_top": "", "griddable": None,
           "depth_min": None, "depth_max": None}
    try:
        cache = CACHE / "geoportal" / f"{sid}.json"
        if not cache.exists():
            r = requests.get(_GEOPORTAL_BASE + sid + "_Multibeam", params={"f": "json"}, headers=H, timeout=30)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(r.json() if r.status_code == 200 else {"_status": r.status_code}))
            time.sleep(0.3)
        iso = data_dir_from_iso(sid, CACHE / "geoportal")
        url, _ = resolve_data_dir(iso, CACHE / "ncei_dirlist") if iso else (None, "")
        if not url:
            rec["status"] = "no_data_dir"; return rec
        cs = size_cruise(sid, url, CACHE / "ncei_dirlist")
        rec["bytes"] = cs.total_bytes; rec["n_files"] = cs.n_files
        swath_ext = {e: n for e, n in cs.ext_counts.items() if GRIDDABLE_EXT.search("x" + e)}
        rec["n_swath"] = int(sum(swath_ext.values()))
        rec["ext_top"] = max(cs.ext_counts, key=cs.ext_counts.get) if cs.ext_counts else ""
        rec["griddable"] = rec["n_swath"] > 0
        # depth from .inf files (MB-System info files served under generated/)
        html = _list_dir(url, CACHE / "ncei_dirlist") or ""
        infs = [mm.group("href") for mm in _ROW.finditer(html) if mm.group("href").endswith(".inf")]
        sub = [mm.group("href") for mm in _ROW.finditer(html) if mm.group("href").endswith("/")]
        if not infs and sub:
            for s in sub[:2]:
                h2 = _list_dir(url + s, CACHE / "ncei_dirlist") or ""
                infs += [s + mm.group("href") for mm in _ROW.finditer(h2) if mm.group("href").endswith(".inf")]
        dmin, dmax = [], []
        for inf in infs[:3]:
            try:
                t = requests.get(url + inf, headers=H, timeout=30).text; time.sleep(0.2)
                mm = re.search(r"Minimum Depth:\s*([-\d.]+)\s+Maximum Depth:\s*([-\d.]+)", t)
                if mm:
                    dmin.append(abs(float(mm.group(1)))); dmax.append(abs(float(mm.group(2))))
            except Exception:
                pass
        if dmin:
            rec["depth_min"] = min(dmin); rec["depth_max"] = max(dmax)
    except Exception as e:
        rec["status"] = f"err:{type(e).__name__}"
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--sample", type=int, default=240)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    m = C.load_manifest()
    ncei = fetch_all_footprints()
    ncei["family"] = ncei.INSTRUMENT.fillna("").map(family)
    n_all = len(ncei)
    ship = ncei[~(ncei.PLATFORM.fillna("") + " " + ncei.INSTRUMENT.fillna("")).str.contains(NON_SHIP)]
    # exclusion by survey id
    excl_ids = set(map(str, m.lr_cruise))
    cand = None
    cg = C.REPORT_DIR / "discovery_rerun" / "candidates_gated.csv"
    if cg.exists():
        cand_all = pd.read_csv(cg)
        cand = cand_all[cand_all.status == "new_candidate"]
        for s in cand.lr_cruises_all.dropna():
            excl_ids |= set(str(s).split(";"))
    zone, zinfo = exclusion_geometry(m, cand, ncei)
    ship = ship.copy()
    ship["excl_id"] = ship.SURVEY_ID.isin(excl_ids)
    ship["excl_geom"] = ship.geometry.intersects(zone)
    keep = ship[~ship.excl_id & ~ship.excl_geom].copy()
    keep["centroid_lon"] = keep.geometry.centroid.x; keep["centroid_lat"] = keep.geometry.centroid.y
    from src.acq_r01.discovery_rerun import basin
    keep["basin"] = [basin(x, y) for x, y in zip(keep.centroid_lon, keep.centroid_lat)]
    # stratified sample by family
    rng = np.random.default_rng(20260929)
    parts = []
    for fam, g in keep.groupby("family"):
        n = max(3, int(round(a.sample * len(g) / len(keep))))
        parts.append(g.sample(n=min(n, len(g)), random_state=int(rng.integers(0, 2**31 - 1))))
    samp = pd.concat(parts)
    log.info("sampling %d of %d surveys", len(samp), len(keep))
    recs = [sample_survey(str(r.SURVEY_ID), str(r.DOWNLOAD_URL)) for _, r in samp.iterrows()]
    sdf = pd.DataFrame(recs).merge(samp[["SURVEY_ID", "family", "SURVEY_YEAR", "basin"]].rename(columns={"SURVEY_ID": "survey"}), on="survey")
    sdf.to_csv(OUT / "sample_surveys.csv", index=False)
    ok = sdf[sdf.status == "ok"]
    per_fam = {}
    total_est = 0.0
    for fam, g in keep.groupby("family"):
        s = ok[ok.family == fam]
        mean_b = float(s.bytes.mean()) if len(s) else float(ok.bytes.mean())
        gridd = float(s.griddable.mean()) if len(s) else None
        per_fam[fam] = {"n_surveys": int(len(g)), "n_sampled_ok": int(len(s)), "mean_gb_per_survey": round(mean_b / 1e9, 2),
                        "est_total_tb": round(mean_b * len(g) / 1e12, 2), "frac_griddable_unchanged": gridd}
        total_est += mean_b * len(g)
    depths = ok.dropna(subset=["depth_max"])
    dbins = pd.cut(depths.depth_max, [0, 200, 1000, 2000, 3000, 4000, 6000, 12000]).value_counts().sort_index()
    ext_mix = ok.ext_top.value_counts().head(12).to_dict()
    summary = {
        "ncei_footprints_total": int(n_all), "ship_only": int(len(ship)),
        "excluded_by_survey_id": int(ship.excl_id.sum()), "excluded_by_10km_zone": int((~ship.excl_id & ship.excl_geom).sum()),
        "exclusion_zone_inputs": zinfo, "remaining_cruises": int(len(keep)),
        "by_basin": keep.basin.value_counts().to_dict(), "by_family": keep.family.value_counts().to_dict(),
        "by_decade": keep.SURVEY_YEAR.floordiv(10).mul(10).value_counts().sort_index().to_dict(),
        "sample_n": int(len(sdf)), "sample_ok": int(len(ok)), "sample_status": sdf.status.value_counts().to_dict(),
        "est_total_swath_tb": round(total_est / 1e12, 1), "per_family": per_fam,
        "frac_griddable_unchanged_weighted": round(sum(per_fam[f]["n_surveys"] * (per_fam[f]["frac_griddable_unchanged"] or 0) for f in per_fam) / max(1, len(keep)), 3),
        "depth_distribution_sample(max depth m)": {str(k): int(v) for k, v in dbins.items()},
        "format_mix_sample(top ext)": ext_mix,
    }
    C.write_json(OUT / "pretrain_scope.json", summary)
    md = ["# Pretraining-corpus scoping (ACQ-R01 §5; estimate, no downloads)\n", "| quantity | value |", "|---|---|"]
    for k, v in summary.items():
        if not isinstance(v, dict):
            md.append(f"| {k} | {v} |")
    for k in ("by_basin", "by_family", "by_decade", "depth_distribution_sample(max depth m)", "format_mix_sample(top ext)", "exclusion_zone_inputs"):
        md += ["", f"**{k}**", "", "| key | n |", "|---|---|"] + [f"| {a_} | {b_} |" for a_, b_ in summary[k].items()]
    md += ["", "**per instrument family**", "", "| family | surveys | sampled | mean GB/survey | est total TB | griddable unchanged |", "|---|---|---|---|---|---|"]
    md += [f"| {f} | {v['n_surveys']} | {v['n_sampled_ok']} | {v['mean_gb_per_survey']} | {v['est_total_tb']} | {v['frac_griddable_unchanged']} |" for f, v in per_fam.items()]
    (OUT / "pretrain_scope.md").write_text("\n".join(md))
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
