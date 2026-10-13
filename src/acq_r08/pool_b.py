"""ACQ-R08 Pool B — NOAA NOS hydrographic surveys with BAG grids at 4 m or finer, each paired with an independent NCEI
multibeam cruise (raw swath, different cruise, never a compilation). Metadata only; reported separately from Pool A.

Catalog route (the NOS hydro ArcGIS map service exposes no queryable layer, checked 2026-10-12): the NCEI Geoportal
OpenSearch index holds one record per NOS survey (id gov.noaa.nos.<range>:<H-number>) with bounding box, time period,
survey scale and the data links, whose BAG file names carry the grid resolution (e.g. ``H13384_MB_50cm_MLLW_1of1.bag``).
No NOS catalog record states the depth range, so ``depth_range_m`` is ``needs download`` for every Pool B candidate;
the NOS Hydrographic Survey Specifications' resolution–depth bands are recorded as an auxiliary plausibility column only.
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
import pandas as pd
import requests
from shapely.geometry import box

from src.acq_r08 import common as K
from src.acq_r08.pool_a import refresh_ncei_footprints, _norm
from src.discovery import geoportal

log = logging.getLogger("acq_r08.pool_b")
OUT = K.OUT / "pool_b"
OS = "https://www.ncei.noaa.gov/metadata/geoportal/opensearch"
BAG_RES_RE = re.compile(r"_(\d+(?:\.\d+)?)\s*(cm|m)_", re.I)
NOAA_SHIP_RE = re.compile(r"Rainier|Fairweather|Thomas Jefferson|Ferdinand|Hassler|Nancy Foster|Whiting|Rude|Heck|Mt\.? Mitchell|"
                          r"Davidson|Surveyor|Peirce|McArthur|Okeanos|Bay Hydro|Hydrographer", re.I)
# NOS HSSD (2022) BAG resolution → nominal depth band (m); plausibility only, never a depth estimate
HSSD = {0.5: (0, 20), 1.0: (18, 40), 2.0: (36, 80), 4.0: (72, 160), 8.0: (144, 320), 16.0: (288, 640), 32.0: (576, 1280), 64.0: (1152, 11000)}
ISO_CAP = 400


def harvest_nos() -> pd.DataFrame:
    cache = K.CACHE / "nos"; cache.mkdir(parents=True, exist_ok=True)
    rows, start, total = [], 1, None
    while True:
        p = cache / f"page_{start:06d}.json"
        if p.exists():
            j = json.loads(p.read_text())
        else:
            for attempt in range(4):
                try:
                    r = requests.get(OS, params={"q": '"NOS Hydrographic Survey"', "f": "json", "size": 100, "start": start}, headers=K.UA, timeout=120)
                    r.raise_for_status(); j = r.json(); break
                except Exception as e:
                    log.warning("OpenSearch start=%d attempt %d: %s", start, attempt, e); time.sleep(5 * (attempt + 1)); j = None
            if j is None:
                raise RuntimeError("NCEI Geoportal OpenSearch unreachable")
            p.write_text(json.dumps(j)); time.sleep(0.4)
        total = total or j.get("total")
        res = j.get("results", [])
        for it in res:
            sid = str(it.get("id", ""))
            if not sid.startswith("gov.noaa.nos"):
                continue
            s = it.get("_source", {}) or {}
            bb = it.get("bbox") or {}
            links = [l for l in (s.get("links_s") or []) if "data.ngdc.noaa.gov" in l]
            bags = [l for l in links if l.lower().endswith(".bag")]
            res_m = []
            for l in bags:
                m = BAG_RES_RE.search(l.rsplit("/", 1)[-1])
                if m:
                    v = float(m.group(1)); res_m.append(v / 100 if m.group(2).lower() == "cm" else v)
            tp = (s.get("timeperiod_nst") or [{}])[0]
            rows.append({"survey": sid.split(":")[-1], "geoportal_id": sid, "title": it.get("title", ""),
                         "xmin": bb.get("xmin"), "ymin": bb.get("ymin"), "xmax": bb.get("xmax"), "ymax": bb.get("ymax"),
                         "begin": str(tp.get("begin_dt") or "")[:10], "end": str(tp.get("end_dt") or "")[:10],
                         "scale_denominator": s.get("apiso_Denominator_i"), "n_bag": len(bags), "bag_res_m": json.dumps(sorted(set(res_m))),
                         "bag_min_res_m": min(res_m) if res_m else None, "bag_files": ";".join(x.rsplit("/", 1)[-1] for x in bags)[:400],
                         "n_links": len(links), "updated": s.get("src_lastupdate_dt")})
        if not res or (total and start + 100 > total):
            break
        start += 100
    df = pd.DataFrame(rows).drop_duplicates("survey")
    df.attrs["total_index"] = total
    return df


def iso_vessel(survey: str, geoportal_id: str) -> dict:
    """Vessel / platform text and any depth statement from the survey's ISO record (one XML fetch, cached)."""
    cache = K.CACHE / "nos_iso" / f"{survey}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    out = {"vessel": "", "depth_text": "", "status": None}
    try:
        r = requests.get(f"https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/{geoportal_id}/xml", headers=K.UA, timeout=90)
        out["status"] = r.status_code
        if r.status_code == 200:
            x = r.text
            v = re.findall(r"(?:NOAA Ship|NOAA Launch|R/V|S/V|M/V|Survey Vessel|Hydrographic Survey Launch)\s+([A-Z][A-Za-z.' -]{2,30})", x)
            out["vessel"] = "; ".join(dict.fromkeys(s.strip() for s in v))[:160]
            d = re.findall(r"[^<>]{0,60}\b(?:depths?|water depth)\b[^<>]{0,80}(?:\d+\s*(?:m|meters|metres|fathoms?))[^<>]{0,40}", x, re.I)
            out["depth_text"] = " | ".join(dict.fromkeys(re.sub(r"\s+", " ", s).strip() for s in d))[:300]
        time.sleep(0.3)
    except Exception as e:
        out["status"] = f"error {str(e)[:60]}"
    cache.parent.mkdir(parents=True, exist_ok=True); cache.write_text(json.dumps(out))
    return out


def hssd_band(res):
    if res is None:
        return None
    key = min(HSSD, key=lambda k: abs(k - res))
    return HSSD[key]


def screen(nos: pd.DataFrame, ncei: gpd.GeoDataFrame, excl: gpd.GeoDataFrame) -> pd.DataFrame:
    ships = ncei[~(ncei.PLATFORM.fillna("") + " " + ncei.INSTRUMENT.fillna("")).str.contains(r"\bAUV\b|\bROV\b|Sentry|REMUS|HUGIN|Jason|Alvin|glider", case=False)].copy()
    sidx = ships.sindex
    rows = []
    for _, h in nos.iterrows():
        rec = dict(h); rec.update({"pool": "B", "source": "NOS (NCEI Geoportal)", "hr_id": f"NOS:{h.survey}", "excluded_by": "", "exclusion_detail": "", "pool_eligible": True, "not_eligible_reason": ""})
        if h.n_bag == 0:
            rec["pool_eligible"] = False; rec["not_eligible_reason"] = "no BAG product in the record"
        elif h.bag_min_res_m is None or pd.isna(h.bag_min_res_m):
            rec["pool_eligible"] = False; rec["not_eligible_reason"] = "BAG present but resolution not in the file name"
        elif h.bag_min_res_m > 4.0:
            rec["pool_eligible"] = False; rec["not_eligible_reason"] = "BAG coarser than 4 m"
        if any(pd.isna(h[c]) for c in ("xmin", "ymin", "xmax", "ymax")):
            rec["pool_eligible"] = False; rec["not_eligible_reason"] = rec["not_eligible_reason"] or "no bounding box"
            rows.append(rec); continue
        g = box(h.xmin, h.ymin, h.xmax, h.ymax) if (h.xmin != h.xmax and h.ymin != h.ymax) else box(h.xmin - 0.002, h.ymin - 0.002, h.xmax + 0.002, h.ymax + 0.002)
        rec["hr_res_m"] = h.bag_min_res_m; rec["hr_res_source"] = "BAG file name (NCEI data link)"; rec["footprint_kind"] = "bbox (Geoportal record)"
        rec["hr_footprint_km2"] = round(K.area_km2(g), 2); rec["lon"], rec["lat"] = g.centroid.x, g.centroid.y
        rec["year"] = str(h.begin or "")[:4]; rec["setting"] = "unknown (NOS record: location only)"; rec["basin"] = K.basin(rec["lon"], rec["lat"])
        rec["license"] = "NOAA NCEI public domain"; rec["releasable"], rec["releasable_note"] = "yes", "US federal public domain"
        if not rec["pool_eligible"]:
            rows.append(rec); continue
        ref, kind, km, over = K.nearest_exclusion(g, excl)
        rec.update({"nearest_corpus_ref": ref, "nearest_corpus_kind": kind, "nearest_corpus_km": km, "overlaps_corpus": ";".join(over),
                    "within_50km": bool(km is not None and km <= K.FLAG_KM), "in_cal_dig_area": bool(excl[excl.kind == "cal_dig_area"].intersects(g).any())})
        if over:
            rec["excluded_by"] = "1"; rec["exclusion_detail"] = f"footprint overlaps {';'.join(over)[:120]}"
        elif km is not None and km < K.EXCL_KM:
            rec["excluded_by"] = "2"; rec["exclusion_detail"] = f"{km} km from {ref}"
        elif rec["in_cal_dig_area"]:
            rec["excluded_by"] = "3"; rec["exclusion_detail"] = "inside the Cal DIG area"
        if rec["excluded_by"]:
            rows.append(rec); continue
        cands = []
        y0 = int(h.begin[:4]) if str(h.begin)[:4].isdigit() else None; y1 = int(h.end[:4]) if str(h.end)[:4].isdigit() else y0
        for i in sidx.query(g, predicate="intersects"):
            s = ships.iloc[i]; ov = K.inter_km2(g, s.geometry)
            if ov <= 0:
                continue
            ly = int(s.SURVEY_YEAR) if pd.notna(s.SURVEY_YEAR) else None
            same_id = _norm(h.survey) in _norm(s.SURVEY_ID)
            noaa_same_time = bool(NOAA_SHIP_RE.search(str(s.PLATFORM))) and (ly is not None and y0 is not None and y0 - 1 <= ly <= (y1 or y0) + 1)
            cands.append({"lr_cruise": s.SURVEY_ID, "lr_platform": s.PLATFORM, "lr_sonar": s.INSTRUMENT, "lr_year": str(ly or ""), "overlap_km2": round(ov, 2),
                          "same_cruise": same_id, "possibly_same_cruise": noaa_same_time, "composite": bool(K.COMPOSITE_RE.search(f"{s.SURVEY_ID} {s.PLATFORM} {s.SOURCE}")),
                          "raw": bool(s.DOWNLOAD_URL)})
        rec["n_lr_options"] = len(cands)
        indep = sorted([c for c in cands if not c["same_cruise"] and not c["possibly_same_cruise"] and not c["composite"] and c["raw"]], key=lambda c: -c["overlap_km2"])
        if not cands:
            rec["lr_cruise"] = ""; rec["lr_note"] = "no NCEI multibeam cruise over the survey"
        elif not indep:
            rec["excluded_by"] = "5"; rec["exclusion_detail"] = "every overlapping multibeam cruise is the same survey or a NOAA hydrographic ship in the same years (soundings may be shared)"
            rec["lr_cruise"] = ""
        if rec["excluded_by"]:
            rows.append(rec); continue
        best = indep[0] if indep else None
        if best:
            rec.update({k: best[k] for k in ("lr_cruise", "lr_platform", "lr_sonar", "lr_year", "overlap_km2")})
            rec["lr_source"] = "NCEI MBBDB (raw swath)"; rec["lr_raw_available"] = True; rec["overlap_km2_est"] = best["overlap_km2"]
            rec["lr_alternatives"] = " | ".join(f"{c['lr_cruise']} ({c['lr_sonar']}, {c['overlap_km2']} km²)" for c in indep[1:4])
            bw = K.beamwidth(best["lr_sonar"]) or 1.5
            rec["depth_needed_for_band_m"] = round(K.RATIO_BAND * h.bag_min_res_m / (2 * math.tan(math.radians(bw / 2))), 0)
            band = hssd_band(h.bag_min_res_m); rec["hssd_depth_band_m"] = f"{band[0]}–{band[1]}" if band else ""
            rec["plausible_under_hssd"] = bool(band and rec["depth_needed_for_band_m"] <= band[1])
        else:
            rec.update({"lr_cruise": "", "lr_platform": "", "lr_sonar": "", "lr_year": "", "overlap_km2": None, "lr_source": "", "lr_raw_available": None,
                        "overlap_km2_est": None, "lr_alternatives": "", "depth_needed_for_band_m": None, "hssd_depth_band_m": "", "plausible_under_hssd": None})
        rec["depth_min_m"] = None; rec["depth_max_m"] = None; rec["depth_source"] = "needs download (no depth in the NOS catalog record)"
        rec["lr_est_m"] = None; rec["lr_est_method"] = "needs download (depth not in catalog record)"; rec["lr_est_weak"] = True
        rec.update(K.estimates(h.bag_min_res_m, None, rec.get("overlap_km2_est")))
        rec["overlap_is_upper_bound"] = True; rec["footprint_suspect"] = False
        rec["status"], rec["status_reason"] = K.status_of(rec)
        rows.append(rec)
    df = pd.DataFrame(rows)
    for c, v in (("status", ""), ("status_reason", ""), ("lr_cruise", ""), ("lr_platform", ""), ("lr_sonar", ""), ("tiles_est", None), ("plausible_under_hssd", None),
                 ("overlap_km2_est", None), ("within_50km", False), ("nearest_corpus_ref", None), ("nearest_corpus_km", None)):
        if c not in df.columns:
            df[c] = v
    return df


def enrich_iso(df: pd.DataFrame) -> pd.DataFrame:
    """Vessel text from the ISO record for the shortlist (bounded to ISO_CAP), and a second rule-5 pass on it."""
    short = df[df.pool_eligible & (df.excluded_by == "") & df.lr_cruise.fillna("").ne("")].sort_values("overlap_km2_est", ascending=False).head(ISO_CAP)
    ves = {}
    for _, r in short.iterrows():
        ves[r.survey] = iso_vessel(r.survey, r.geoportal_id)
    df["nos_vessel"] = df.survey.map(lambda s: ves.get(s, {}).get("vessel", ""))
    df["nos_depth_text"] = df.survey.map(lambda s: ves.get(s, {}).get("depth_text", ""))
    df["iso_checked"] = df.survey.isin(ves)
    for i, r in df[df.iso_checked].iterrows():
        v = str(r.nos_vessel or ""); p = str(r.lr_platform or "")
        if v and p and any(_norm(tok) and _norm(tok) in _norm(p) for tok in re.split(r"[;,]", v) if len(tok.strip()) > 3):
            df.at[i, "excluded_by"] = "5"; df.at[i, "exclusion_detail"] = f"LR cruise platform '{p}' is the NOS survey vessel ({v})"; df.at[i, "status"] = ""; df.at[i, "status_reason"] = ""
    return df


def funnel(df: pd.DataFrame, total_index) -> dict:
    el = df[df.pool_eligible]; s = el[el.excluded_by == ""]
    f = {"records_found_nos_surveys": int(len(df)), "geoportal_index_total_for_query": total_index,
         "not_eligible": int((~df.pool_eligible).sum()), "not_eligible_breakdown": df[~df.pool_eligible].not_eligible_reason.value_counts().to_dict(),
         "bag_4m_or_finer": int(df.pool_eligible.sum())}
    for rule in ("1", "2", "3", "4", "5"):
        f[f"excluded_rule_{rule}"] = int((el.excluded_by == rule).sum())
    f["screened_under_s3"] = int(len(s)); f["in_range"] = int((s.status == "in range").sum()); f["outside_range"] = int((s.status == "outside range").sum())
    f["uncertain"] = int((s.status == "uncertain").sum()); f["no_ship_cruise_over_survey"] = int(s.status_reason.fillna("").str.contains("no independent ship cruise").sum())
    f["tiles_below_300"] = int(s.status_reason.fillna("").str.contains("tiles_est").sum())
    f["with_independent_lr"] = int(s.lr_cruise.fillna("").ne("").sum())
    f["with_independent_lr_and_tiles_ge_300"] = int((s.lr_cruise.fillna("").ne("") & (s.tiles_est.fillna(0) >= K.TILES_FLOOR)).sum())
    f["plausible_under_hssd_band"] = int(s.plausible_under_hssd.fillna(False).astype(bool).sum())
    f["iso_records_checked"] = int(df.get("iso_checked", pd.Series(dtype=bool)).sum()) if "iso_checked" in df else 0
    f["within_50km_flagged"] = int(s.within_50km.sum())
    return f


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    st = K.guard_selftest()
    if not st["all_blocked"]:
        raise SystemExit("blindness guard self-test failed")
    t0 = time.time()
    nos = harvest_nos(); log.info("NOS surveys %d (index total %s)", len(nos), nos.attrs.get("total_index"))
    nos.to_csv(OUT / "nos_surveys.csv", index=False)
    ncei = refresh_ncei_footprints()
    excl = gpd.read_file(K.OUT / "exclusion_footprints.gpkg", layer="excl") if (K.OUT / "exclusion_footprints.gpkg").exists() else K.build_exclusion_set()[0]
    df = screen(nos, ncei, excl)
    df = enrich_iso(df)
    df.to_csv(OUT / "nos_records.csv", index=False)
    cand = df[df.pool_eligible & (df.excluded_by == "")].copy().sort_values(["tiles_est"], ascending=False)
    cand.to_csv(OUT / "candidates.csv", index=False)
    fun = funnel(df, nos.attrs.get("total_index")); fun["elapsed_s"] = round(time.time() - t0); fun["generated"] = K.now_iso()
    K.write_json(OUT / "funnel.json", fun); K.write_json(K.OUT / "guard_state_pool_b.json", K.guard_state())
    print(json.dumps(fun, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
