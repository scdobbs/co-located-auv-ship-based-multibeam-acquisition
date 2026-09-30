"""ACQ-R02 §5 — candidate verification: lockbox pre-check, real HR footprint, LR overlap, HR-survey
axis, leakage re-run with the designation-change rules.

Candidates: the 16 ACQ-R01 candidates (candidates_gated.csv status new_candidate), the 11 H1 HR
(development-only by ruling), and the §4 PANGAEA candidates (discovery_pangaea/candidates.csv,
status candidate) once §4.3 designation is committed.

Per candidate, in this order:
  5.1 lockbox pre-check from METADATA (HR cruise from the June catalog or the MGDS dataset description,
      all LR cruises, catalog centroid vs the lockbox centroids) — before any file is opened;
      MGDS:5174 is checked first.  Failing candidates are excluded and recorded.
  5.2 HR grid download to OAK raw_hr/<hr>/ (permanent; sha256), RGB-render gate, valid-data polygon
      per raster (stage_b machinery, downsampled read) -> footprint.geojson; overlap with every LR
      cruise footprint (NCEI polygons; PANGAEA bboxes); no real overlap -> false_pair.
  5.3 HR cruise / survey identity from the HR files' own metadata (raster tags) + MGDS description.
  5.4 leakage re-run (shared HR cruise, shared LR cruise, centroid <= 50 km) against the corpus, the
      lockbox, and all candidates, then the binding designation-change rules.

Outputs: reports_post_grl_review/ACQ-R02/verification/{candidates_verified.csv, units_after.json,
designation_changes.md, hr_footprints.gpkg}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from shapely import wkb as shp_wkb, make_valid
from shapely.geometry import box, shape
from shapely.ops import unary_union

from src.acq_r01 import common as C
from src.acq_r01.discovery_rerun import basin, hav_km, UF
from src.discovery import stage_b
from rasterio.features import shapes as _shapes
stage_b.shapes = _shapes
from src.discovery.hr_format_gate import is_rgb_visualization

log = logging.getLogger("acq_r02.verify")
R01 = C.REPO / "reports_post_grl_review" / "ACQ-R01"
R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"
OUT = R02 / "verification"
RAW_HR = C.OAK / "raw_hr"
H1 = ["MGDS:5174", "MGDS:24002", "MGDS:31321", "MGDS:31813", "MGDS:31814", "MGDS:31831", "MGDS:20815", "MGDS:21847", "MGDS:31073", "MGDS:31291", "MGDS:24467"]
LOCKBOX_HR_CRUISES = {"AT42-03", "AT15-36"}
R_KM = 50.0
MIN_OVERLAP_KM2 = 0.5
CRUISE_RE = re.compile(r"(?:expedition|cruise|Expedition|Cruise)s?\s+(?:[A-Za-z .]{0,30}?\s)?([A-Z]{1,5}\d{2,6}(?:[-/][A-Z0-9]{1,4})?)")
NCEI_FP = C.SCRATCH_DATA / "discovery_cache" / "acq_r01_2026-09-29" / "ncei_all_footprints.geojson"
H = {"User-Agent": "auv-ship-acq/0.4 (Sherlock; ACQ-R02 verification; stephencoledobbs@gmail.com)"}


def mgds_descriptions() -> dict:
    out = {}
    for xmlp in (C.SCRATCH_DATA / "discovery_cache" / "acq_r01_2026-09-29" / "mgds" / "mgds_AUV_Bathymetry_data_set.xml",):
        if not xmlp.exists():
            continue
        root = ET.fromstring(xmlp.read_bytes()); ns = {"m": "http://www.marine-geo.org/services/xml/mgdsDataService"}
        for ds in root.find("m:data_sets", ns) or []:
            uid = ds.get("uid"); d = ds.find("m:description", ns); e = ds.find("m:ds_entry", ns)
            out[f"MGDS:{uid}"] = {"description": (d.text or "") if d is not None else "", "ds_entry": e.get("id") if e is not None else "",
                                  "title": ds.get("title") or "", "general_type": ds.get("general_type") or ""}
    return out


def cruise_from_text(text: str) -> str:
    m = CRUISE_RE.search(text or "")
    return m.group(1) if m else ""


def load_candidates(include_pangaea: bool) -> pd.DataFrame:
    cg = pd.read_csv(R01 / "discovery_rerun" / "candidates_gated.csv")
    r01 = cg[cg.status == "new_candidate"].copy()
    new_cat = gpd.read_file(R01 / "discovery_rerun" / "hr_catalog.gpkg", layer="hr").set_index("hr_id")
    old_cat = gpd.read_file(C.REPO / "reports/discovery/hr_catalog.gpkg", layer="hr").set_index("hr_id")
    sel = gpd.read_file(C.REPO / "reports/discovery/stage_a_selection.gpkg").set_index("hr_id")
    desc = mgds_descriptions()
    des = pd.read_csv(R01 / "designation" / "designation.csv")
    unit_of = {}
    for _, r in des.iterrows():
        for m in str(r.members).split(";"):
            unit_of[m] = (r.unit_id, r.assignment)
    rows = []
    for _, r in r01.iterrows():
        h = r.hr_id; cat = new_cat.loc[h] if h in new_cat.index else old_cat.loc[h]
        rows.append({"hr_id": h, "set": "R01", "source": "MGDS", "title": str(cat.title)[:120], "doi": str(cat.doi or ""), "file_ids": str(cat.file_ids or ""),
                     "hr_res_m": cat.native_res_m, "hr_cruise_catalog": str(old_cat.loc[h].cruise_id) if h in old_cat.index and isinstance(old_cat.loc[h].cruise_id, str) else "",
                     "hr_cruise_desc": cruise_from_text(desc.get(h, {}).get("description", "")), "lr_best": str(r.best_lr), "lr_cruises_all": str(r.lr_cruises_all),
                     "lon": float(r.lon), "lat": float(r.lat), "prior_unit": unit_of.get(h, ("", ""))[0],
                     "prior_designation": unit_of.get(h, ("", "development (joins existing unit)" if r.joins_existing_units else ""))[1],
                     "prior_joins": str(r.joins_existing_units) if isinstance(r.joins_existing_units, str) else "", "general_type": desc.get(h, {}).get("general_type", "")})
    for h in H1:
        cat = old_cat.loc[h]
        lr = sel.loc[h, "lr_cruise_id"] if h in sel.index else ""
        rows.append({"hr_id": h, "set": "H1", "source": "MGDS", "title": str(cat.title)[:120], "doi": str(cat.doi or ""), "file_ids": str(cat.file_ids or ""),
                     "hr_res_m": cat.native_res_m, "hr_cruise_catalog": str(cat.cruise_id) if isinstance(cat.cruise_id, str) else "",
                     "hr_cruise_desc": cruise_from_text(desc.get(h, {}).get("description", "")), "lr_best": str(lr), "lr_cruises_all": str(lr),
                     "lon": cat.geometry.centroid.x, "lat": cat.geometry.centroid.y, "prior_unit": "", "prior_designation": "development (ruling H1)", "prior_joins": "",
                     "general_type": desc.get(h, {}).get("general_type", "")})
    if include_pangaea and (R02 / "discovery_pangaea" / "candidates.csv").exists():
        pc = pd.read_csv(R02 / "discovery_pangaea" / "candidates.csv")
        pdes = R02 / "designation_pangaea" / "designation.csv"
        punit = {}
        if pdes.exists():
            for _, r in pd.read_csv(pdes).iterrows():
                for m in str(r.members).split(";"):
                    punit[m] = (r.unit_id, r.assignment)
        for _, r in pc[(pc.status == "candidate") & ~pc.shares_lockbox].iterrows():
            hid = f"PANGAEA:{r.id}"
            rows.append({"hr_id": hid, "set": "P4", "source": "PANGAEA", "title": str(r.title)[:120], "doi": str(r.doi), "file_ids": "", "hr_res_m": r.hr_res_m,
                         "hr_cruise_catalog": str(r.campaigns).split(";")[0] if isinstance(r.campaigns, str) else "", "hr_cruise_desc": "",
                         "lr_best": str(r.best_lr), "lr_cruises_all": str(r.lr_cruises_all), "lon": float(r.lon), "lat": float(r.lat),
                         "prior_unit": punit.get(hid, ("", ""))[0],
                         "prior_designation": punit.get(hid, ("", "development (joins existing unit)" if isinstance(r.joins_existing_units, str) and r.joins_existing_units else ""))[1],
                         "prior_joins": str(r.joins_existing_units) if isinstance(r.joins_existing_units, str) else "", "general_type": ""})
    df = pd.DataFrame(rows)
    df["hr_cruise_meta"] = df.hr_cruise_catalog.where(df.hr_cruise_catalog != "", df.hr_cruise_desc)
    # MGDS:5174 first (directive §5.1)
    df["_o"] = (df.hr_id != "MGDS:5174").astype(int)
    return df.sort_values(["_o", "set", "hr_id"]).drop(columns="_o").reset_index(drop=True)


def lockbox_precheck(df: pd.DataFrame) -> pd.DataFrame:
    la = pd.read_csv(C.REPO / "reports/discovery/leakage_assignment.csv")
    lock_c = {r.pair_id: (float(r.centroid_lon), float(r.centroid_lat)) for _, r in la[la.pair_id.isin(C.LOCKBOX)].iterrows()}
    res = []
    for _, r in df.iterrows():
        lrs = {x for x in str(r.lr_cruises_all).split(";") if x and x != "nan"}
        reasons = []
        if r.hr_cruise_meta in LOCKBOX_HR_CRUISES:
            reasons.append(f"shared HR cruise {r.hr_cruise_meta}")
        if lrs & set(C.LOCKBOX_LR_CRUISES):
            reasons.append(f"shared LR cruise {sorted(lrs & set(C.LOCKBOX_LR_CRUISES))}")
        for p, cc in lock_c.items():
            d = hav_km((r.lon, r.lat), cc)
            if d <= R_KM:
                reasons.append(f"{d:.0f} km from {p}")
        res.append("; ".join(reasons))
    df = df.copy(); df["lockbox_precheck"] = res
    df["lockbox_min_km"] = [min(hav_km((r.lon, r.lat), cc) for cc in lock_c.values()) for _, r in df.iterrows()]
    return df


def sha256_file(p: Path) -> str:
    return C.sha256_file(p)


def pangaea_file_urls(pid: str) -> list[str]:
    """PANGAEA grid products are listed in the dataset's tab export ('URL file' / 'URL raw' columns) or
    offered as the dataset zip (?format=zip); the JSON-LD distribution only points at the tab/html."""
    import io
    urls = []
    r = requests.get(f"https://doi.pangaea.de/10.1594/PANGAEA.{pid}?format=textfile", headers=H, timeout=120)
    lines = r.text.splitlines()
    try:
        s = [i for i, l in enumerate(lines) if l.startswith("*/")][0] + 1
        df = pd.read_csv(io.StringIO("\n".join(lines[s:])), sep="\t")
        for col in [c for c in df.columns if "URL" in c]:
            for u in df[col].dropna().astype(str):
                if re.search(r"\.(tif|tiff|nc|grd|asc|zip|xyz)(\.gz)?$", u, re.I):
                    urls.append(u)
        if "Binary" in df.columns:          # PANGAEA binary files: https://download.pangaea.de/dataset/<id>/files/<name>
            for name in df["Binary"].dropna().astype(str):
                if re.search(r"\.(tif|tiff|nc|grd|asc|zip)(\.gz)?$", name, re.I):
                    urls.append(f"https://download.pangaea.de/dataset/{pid}/files/{name}")
    except Exception as e:
        log.warning("PANGAEA %s tab parse: %s", pid, str(e)[:80])
    if not urls:
        j = requests.get(f"https://doi.pangaea.de/10.1594/PANGAEA.{pid}?format=metadata_jsonld", headers=H, timeout=60).json()
        for d in j.get("distribution") or []:
            u = d.get("contentUrl") or ""
            if "format=zip" in u or re.search(r"\.(tif|tiff|nc|grd|asc|zip)(\.gz)?$", u, re.I):
                urls.append(u)
    # prefer gridded products over point clouds when both are offered
    grids = [u for u in urls if not re.search(r"\.xyz(\.gz)?$", u, re.I)]
    return list(dict.fromkeys(grids or urls))


def download_hr(row) -> dict:
    d = RAW_HR / row.hr_id.replace(":", "_"); d.mkdir(parents=True, exist_ok=True)
    meta_p = d / "download_manifest.json"
    if meta_p.exists():
        return json.loads(meta_p.read_text())
    files = []
    if row.source == "MGDS":
        for uid in [u for u in str(row.file_ids).split(",") if u]:
            p = stage_b._download_file(uid, d)
            files.append({"data_uid": uid, "path": str(p) if p else None, "bytes": p.stat().st_size if p else 0, "sha256": sha256_file(p) if p else None})
    else:
        for u in pangaea_file_urls(row.hr_id.split(":")[1]):
            name = u.rsplit("/", 1)[-1]
            if "format=zip" in u:
                name = f"PANGAEA_{row.hr_id.split(':')[1]}.zip"
            p = d / name
            if not p.exists():
                with requests.get(u, headers=H, stream=True, timeout=600) as g:
                    g.raise_for_status()
                    with p.open("wb") as fh:
                        for ch in g.iter_content(1 << 20):
                            fh.write(ch)
            files.append({"url": u, "path": str(p), "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    meta = {"hr_id": row.hr_id, "files": files, "bytes": int(sum(f["bytes"] for f in files))}
    meta_p.write_text(json.dumps(meta, indent=1))
    return meta


def hr_footprint(row, meta) -> dict:
    d = RAW_HR / row.hr_id.replace(":", "_"); fp = d / "footprint.geojson"
    if fp.exists():
        g = gpd.read_file(fp); info = json.loads((d / "footprint_meta.json").read_text())
        return {**info, "geom": g.geometry.union_all()}
    polys, per_file, tags_all = [], [], {}
    for f in meta["files"]:
        if not f.get("path") or not Path(f["path"]).exists():
            per_file.append({"file": f.get("path"), "status": "missing"}); continue
        try:
            rasters = stage_b._decompress(Path(f["path"]))
        except Exception as e:
            per_file.append({"file": f["path"], "status": f"decompress_err:{str(e)[:60]}"}); continue
        for rp in rasters:
            if rp.suffix.lower() in (".pdf", ".txt", ".xml", ".jpg", ".png", ".kml", ".kmz"):
                per_file.append({"file": rp.name, "status": "non_raster"}); continue
            if rp.suffix.lower() in (".xyz", ".txt", ".csv", ".dat"):
                per_file.append({"file": rp.name, "status": "xyz_points_not_a_grid"}); continue
            rgb, why = is_rgb_visualization(rp)
            if rgb:
                per_file.append({"file": rp.name, "status": f"rgb_render:{why}"}); continue
            try:
                p4326, crs, how = polygon_with_crs_fallback(rp, row.hr_id, d)
                polys.append(p4326); per_file.append({"file": rp.name, "status": "ok", "crs": crs, "crs_source": how, "area_km2": round(stage_b._polygon_area_km2(p4326), 3)})
                try:
                    with rasterio.open(str(rp)) as ds:
                        for k, v in ds.tags().items():
                            if re.search(r"title|source|history|cruise|survey|comment|remark|expedition", k, re.I) and len(tags_all) < 20:
                                tags_all[k] = str(v)[:200]
                except Exception:
                    pass
            except Exception as e:
                per_file.append({"file": rp.name, "status": f"poly_err:{str(e)[:80]}"})
    geom = unary_union(polys) if polys else None
    info = {"n_rasters_ok": len(polys), "per_file": per_file, "area_km2": round(stage_b._polygon_area_km2(geom), 3) if geom is not None else 0.0,
            "raster_tags": tags_all}
    if geom is not None:
        gpd.GeoDataFrame({"hr_id": [row.hr_id]}, geometry=[geom], crs="EPSG:4326").to_file(fp, driver="GeoJSON")
    (d / "footprint_meta.json").write_text(json.dumps(info, indent=1, default=str))
    return {**info, "geom": geom}


def lr_overlaps(geom, lr_cruises: set, ncei: gpd.GeoDataFrame, pship: pd.DataFrame | None) -> dict:
    out = {}
    if geom is None:
        return out
    geom = make_valid(geom)
    for cr in lr_cruises:
        if cr.startswith("PANGAEA:"):
            if pship is not None and cr.split(":")[1] in pship.index:
                r = pship.loc[cr.split(":")[1]]; g = box(r.west, r.south, r.east, r.north)
                inter = make_valid(geom).intersection(g); out[cr] = round(stage_b._polygon_area_km2(inter), 3) if not inter.is_empty else 0.0
            continue
        sub = ncei[ncei.SURVEY_ID == cr]
        if sub.empty:
            out[cr] = None; continue
        try:
            g = unary_union([make_valid(x) for x in sub.geometry]); inter = geom.intersection(g)
            out[cr] = round(stage_b._polygon_area_km2(inter), 3) if not inter.is_empty else 0.0
        except Exception as e:
            log.warning("overlap %s failed: %s", cr, str(e)[:80]); out[cr] = None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--no-pangaea", action="store_true"); ap.add_argument("--only", default=None)
    ap.add_argument("--leakage-only", action="store_true", help="re-run §5.4 from candidates_verified.csv (no downloads)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.leakage_only:
        leakage_rerun(pd.read_csv(OUT / "candidates_verified.csv")); return 0
    OUT.mkdir(parents=True, exist_ok=True)
    df = lockbox_precheck(load_candidates(not a.no_pangaea))
    if a.only:
        df = df[df.hr_id.isin(a.only.split(","))]
    ncei = gpd.read_file(NCEI_FP)
    pship = None
    if (R02 / "discovery_pangaea" / "ship_datasets.csv").exists():
        pship = pd.read_csv(R02 / "discovery_pangaea" / "ship_datasets.csv", dtype={"id": str}).set_index("id")
    recs, geoms = [], {}
    for _, r in df.iterrows():
        rec = r.to_dict()
        if r.lockbox_precheck:
            rec.update({"status": "excluded_lockbox", "reason": r.lockbox_precheck}); recs.append(rec)
            log.warning("[%s] LOCKBOX pre-check FAILED: %s", r.hr_id, r.lockbox_precheck); continue
        log.info("[%s] lockbox pre-check ok (min %.0f km); downloading HR", r.hr_id, r.lockbox_min_km)
        try:
            meta = download_hr(r)
            fpi = hr_footprint(r, meta)
        except Exception as e:
            rec.update({"status": "hr_download_or_footprint_failed", "reason": str(e)[:150]}); recs.append(rec); continue
        rec["hr_bytes"] = meta["bytes"]; rec["hr_n_files"] = len(meta["files"]); rec["hr_area_km2"] = fpi["area_km2"]
        rec["hr_rasters_ok"] = fpi["n_rasters_ok"]; rec["hr_file_status"] = "; ".join(f"{p.get('file', '')[:40]}:{p['status'][:40]}" for p in fpi["per_file"][:8])
        tags = fpi.get("raster_tags", {}); rec["hr_raster_tags"] = json.dumps(tags)[:400]
        tag_cruise = next((cruise_from_text(v) for v in tags.values() if cruise_from_text(v)), "")
        rec["hr_cruise_final"] = r.hr_cruise_meta or tag_cruise
        rec["hr_cruise_source"] = "catalog" if r.hr_cruise_catalog else ("mgds_description" if r.hr_cruise_desc else ("raster_tags" if tag_cruise else "unknown"))
        geom = fpi["geom"]
        if geom is None:
            rec.update({"status": "no_elevation_raster", "reason": "no readable float raster (renders/PDF only)"}); recs.append(rec); continue
        geoms[r.hr_id] = geom
        rec["lon"], rec["lat"] = float(geom.centroid.x), float(geom.centroid.y); rec["basin"] = basin(rec["lon"], rec["lat"])
        lrs = {x for x in str(r.lr_cruises_all).split(";") if x and x != "nan"} | ({str(r.lr_best)} if r.lr_best and r.lr_best != "nan" else set())
        ov = lr_overlaps(geom, lrs, ncei, pship)
        real = {k: v for k, v in ov.items() if v and v >= MIN_OVERLAP_KM2}
        rec["lr_overlap_km2"] = json.dumps(ov); rec["lr_cruises_real"] = ";".join(sorted(real))
        if not real:
            rec.update({"status": "false_pair", "reason": f"no LR footprint overlaps the real HR footprint (best {r.lr_best}: {ov.get(r.lr_best)})"}); recs.append(rec); continue
        rec["lr_best_real"] = r.lr_best if r.lr_best in real else max(real, key=real.get)
        rec["lr_best_overlap_km2"] = real[rec["lr_best_real"]]
        # post-footprint lockbox re-check with the real centroid
        la = pd.read_csv(C.REPO / "reports/discovery/leakage_assignment.csv")
        dmin = min(hav_km((rec["lon"], rec["lat"]), (float(x.centroid_lon), float(x.centroid_lat))) for _, x in la[la.pair_id.isin(C.LOCKBOX)].iterrows())
        rec["lockbox_min_km_real"] = round(dmin, 1)
        if dmin <= R_KM:
            rec.update({"status": "excluded_lockbox", "reason": f"real footprint centroid {dmin:.0f} km from a lockbox pair"}); recs.append(rec); continue
        rec["status"] = "verified"; recs.append(rec)
        log.info("[%s] verified: area %.2f km2, LR real %s (best %s %.2f km2), HR cruise %s [%s]", r.hr_id, fpi["area_km2"], sorted(real), rec["lr_best_real"], rec["lr_best_overlap_km2"], rec["hr_cruise_final"], rec["hr_cruise_source"])
    v = pd.DataFrame(recs)
    v.to_csv(OUT / "candidates_verified.csv", index=False)
    if geoms:
        gpd.GeoDataFrame({"hr_id": list(geoms)}, geometry=list(geoms.values()), crs="EPSG:4326").to_file(OUT / "hr_footprints.gpkg", driver="GPKG")
    leakage_rerun(v)
    print(v[["hr_id", "set", "status", "hr_cruise_final", "lr_best_real" if "lr_best_real" in v else "lr_best", "hr_area_km2" if "hr_area_km2" in v else "set", "reason" if "reason" in v else "set"]].to_string())
    return 0


def leakage_rerun(v: pd.DataFrame):
    """§5.4: components over verified candidates + corpus pairs, then the designation-change rules."""
    m = C.load_manifest()
    cents = json.loads((R01 / "discovery_rerun" / "seed_centroids.json").read_text())
    unit_of_pair = dict(zip(m.pair_id, m.leakage_unit))
    nodes = {}
    for _, r in m.iterrows():
        nodes[r.pair_id] = {"hr_cruise": str(r.cruise_id), "lr": {str(r.lr_cruise)}, "c": cents.get(r.pair_id), "unit": r.leakage_unit, "kind": "corpus",
                            "designation": "lockbox" if r.pair_id in C.LOCKBOX else "development"}
    ok = v[v.status == "verified"]
    for _, r in ok.iterrows():
        nodes[r.hr_id] = {"hr_cruise": str(r.hr_cruise_final or ""), "lr": {str(r.lr_best_real)} if isinstance(r.lr_best_real, str) and r.lr_best_real else set(), "c": (r.lon, r.lat),
                          "unit": r.prior_unit if isinstance(r.prior_unit, str) else "", "kind": r.set,
                          "designation": r.prior_designation if isinstance(r.prior_designation, str) and r.prior_designation else "development"}
    keys = list(nodes); uf = UF(keys)
    for i, a in enumerate(keys):
        A = nodes[a]
        for b in keys[i + 1:]:
            B = nodes[b]
            if A["kind"] == "corpus" and B["kind"] == "corpus":
                continue
            shared_hr = bool(A["hr_cruise"]) and A["hr_cruise"] not in ("", "nan", "None") and A["hr_cruise"] == B["hr_cruise"]
            shared_lr = bool(A["lr"] & B["lr"] - {"", "nan"})
            near = A["c"] and B["c"] and hav_km(A["c"], B["c"]) <= R_KM
            if shared_hr or shared_lr or near:
                uf.union(a, b)
    comps = {}
    for k in keys:
        comps.setdefault(uf.find(k), []).append(k)
    changes, units_after = [], []
    k_new = 0
    for root, mem in comps.items():
        cand = [x for x in mem if nodes[x]["kind"] != "corpus"]
        if not cand:
            continue
        corp = [x for x in mem if nodes[x]["kind"] == "corpus"]
        corp_units = sorted({nodes[x]["unit"] for x in corp})
        lock = any(x in C.LOCKBOX for x in corp)
        prior_units = sorted({nodes[x]["unit"] for x in cand if nodes[x]["unit"]})
        desigs = {x: nodes[x]["designation"] for x in cand}
        conf = [x for x in cand if desigs[x].startswith("confirmatory")]
        dev = [x for x in cand if not desigs[x].startswith("confirmatory")]
        if lock:
            final = {x: "dropped (shares acquisition with lockbox)" for x in cand}
            changes.append(f"{sorted(cand)}: component includes a LOCKBOX pair -> all dropped")
        elif corp:
            final = {x: ("dropped (confirmatory unit merged with existing unit)" if x in conf else (desigs[x] if desigs[x].startswith("development") else "development")) for x in cand}
            for x in conf:
                changes.append(f"{x} ({nodes[x]['unit']}, confirmatory) merges with existing unit(s) {corp_units} -> DROPPED")
            for x in dev:
                if desigs[x] not in ("development", "development (ruling H1)", "development (joins existing unit)"):
                    changes.append(f"{x}: {desigs[x]} -> development (joins {corp_units})")
            unit_id = "+".join(corp_units)
        elif conf and dev:
            final = {x: ("dropped (confirmatory unit merged with development/H1 unit)" if x in conf else desigs[x]) for x in cand}
            for x in conf:
                changes.append(f"{x} ({nodes[x]['unit']}, confirmatory) merges with development members {dev} -> DROPPED")
            unit_id = "+".join(prior_units) or f"vu{k_new:02d}"; k_new += 1
        elif conf and len({nodes[x]["unit"] for x in conf}) > 1:
            final = {x: "dropped (two confirmatory units merged)" for x in cand}
            changes.append(f"confirmatory units {sorted({nodes[x]['unit'] for x in conf})} merge -> all members DROPPED")
            unit_id = "+".join(prior_units)
        else:
            final = {x: desigs[x] for x in cand}
            unit_id = "+".join(prior_units) or f"vu{k_new:02d}"
            if not prior_units:
                k_new += 1
        units_after.append({"unit_id": unit_id, "members": sorted(cand), "corpus_units": corp_units, "designations": final,
                            "hr_cruises": sorted({nodes[x]["hr_cruise"] for x in cand}), "lr_cruises": sorted(set().union(*[nodes[x]["lr"] for x in cand])),
                        "corpus_members": corp})
    # splits: a prior unit whose members now sit in different components inherit the parent's designation (already the case: desigs carried)
    prior_groups = {}
    for x in ok.hr_id:
        if nodes[x]["unit"]:
            prior_groups.setdefault(nodes[x]["unit"], set()).add(uf.find(x))
    for u, roots in prior_groups.items():
        if len(roots) > 1:
            changes.append(f"unit {u} SPLIT into {len(roots)} components; each part inherits its designation")
    dropped_by_verification = [(r.hr_id, r.prior_unit, r.prior_designation, r.status, r.reason) for _, r in v[v.status != "verified"].iterrows()]
    C.write_json(OUT / "units_after.json", {"units": units_after, "changes": changes, "dropped": dropped_by_verification})
    md = ["# Designation changes (ACQ-R02 §5.4)\n", "## Components after verification\n",
          "| unit | members | corpus units | designations | HR cruises | LR cruises |", "|---|---|---|---|---|---|"]
    md += [f"| {u['unit_id']} | {'; '.join(u['members'])} | {','.join(u['corpus_units'])} | {'; '.join(f'{k}: {v}' for k, v in u['designations'].items())} | {','.join(u['hr_cruises'])} | {','.join(u['lr_cruises'])} |" for u in units_after]
    md += ["", "## Changes against ACQ-R01 / §4.3 assignments", ""] + [f"- {c}" for c in changes] + ["", "## Dropped at verification", "", "| hr | prior unit | prior designation | status | reason |", "|---|---|---|---|---|"]
    md += [f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in dropped_by_verification]
    (OUT / "designation_changes.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    sys.exit(main())
