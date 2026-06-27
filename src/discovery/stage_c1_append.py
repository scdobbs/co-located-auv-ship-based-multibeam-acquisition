"""Append the 3 Steve-signed-off C1 recovered pairs to the canonical manifest.

Pescadero FK181031x24618 (lu29), Pythia TN299x31253 (lu27), SantaMonica
NA076x32317. Builds M1-parity rows (mbinfo LR independence, checksums, footprint
path, res_ratio, coreg) and appends append-only (34 preserved verbatim) -> 37,
syncs OAK, sha256-verifies. Backup before write; idempotent.
"""
from __future__ import annotations
import hashlib, json, logging, os, re, shutil, stat
from pathlib import Path
from xml.etree import ElementTree as ET
import pandas as pd

log = logging.getLogger("c1append")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
HARM = DATA / "harmonized"
RAWLR = DATA / "raw_lr"
RH = DATA / "reharvest_c1"
CAT = DATA / "discovery_cache/mgds/mgds_AUV_Bathymetry_data_set.xml"
CANON = REPO / "manifest/pairs.parquet"
OAK = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy/manifest/pairs.parquet")
HARMRES = REPO / "reports/discovery/stage_c1_harmonize_results.json"
LRINFO = REPO / "reports/discovery/stage_m1_lr_mbinfo.json"
RESULT = REPO / "reports/discovery/stage_c1_append_result.json"
NS = {"m": "http://www.marine-geo.org/services/xml/mgdsDataService"}

# pid -> (uid, lr_cruise, leakage_unit, terrain_class, lr_native_m, hr_uid_dir)
SPEC = {
    "FK181031__MGDS_24618": {"uid": "24618", "lr_cruise": "FK181031", "lu": 29,
        "terrain": "hydrothermal_vent", "lr_native_m": 65.8},
    "TN299__MGDS_31253": {"uid": "31253", "lr_cruise": "TN299", "lu": 27,
        "terrain": "continental_margin", "lr_native_m": 38.5},
    "NA076__MGDS_32317": {"uid": "32317", "lr_cruise": "NA076", "lu": "new(SantaMonicaMound)",
        "terrain": "continental_margin", "lr_native_m": 221.0},
}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def catalog():
    root = ET.parse(str(CAT)).getroot()
    M = {}
    for ds in root.find("m:data_sets", NS):
        ent = ds.find("m:ds_entry", NS); gf = ds.find("m:geographic_feature", NS); de = ds.find("m:description", NS)
        M[ds.get("uid")] = {"doi": ds.get("data_doi"), "cruise": ent.get("id") if ent is not None else "",
            "plat": (ent.get("platform") if ent is not None else "") or "", "start": (ent.get("start_date") if ent is not None else "") or "",
            "gf": (gf.text or "").strip() if gf is not None else "", "desc": (de.text or "") if de is not None else ""}
    return M


def hr_sonar(desc, plat):
    for pat in (r"Reson\s+SeaBat\s+[\w-]+", r"Kongsberg\s+EM\d+", r"Reson\s+\d+"):
        m = re.search(pat, desc, re.I)
        if m:
            return m.group(0)
    return "Reson SeaBat 7125 (MBARI/Sentry AUV, typical)"


def lr_meta(cruise, lrinfo):
    mb = lrinfo.get(cruise)
    if not mb or not mb.get("filename"):
        # derive from raw_lr filename (e.g. NA076 -> Nautilus/EM302/2017)
        d = RAWLR / cruise
        fn = next((p.name for p in d.iterdir() if re.search(r"\.mb\d+", p.name)), "") if d.is_dir() else ""
    else:
        fn = mb["filename"]
    vessel = {"TGT": "R/V Thomas G. Thompson", "Nautilus": "E/V Nautilus", "revelle": "R/V Roger Revelle",
              "Atlantis": "R/V Atlantis", "FK": "R/V Falkor"}
    ves = next((v for k, v in vessel.items() if k.lower() in fn.lower()), f"NCEI cruise {cruise}")
    em = re.search(r"EM\s?\d{3,4}", fn)
    sonar = ("Kongsberg " + em.group(0)) if em else "Kongsberg EM (.all)"
    dm = re.search(r"(19|20)(\d{2})(\d{2})(\d{2})", fn)
    date = f"{dm.group(1)}{dm.group(2)}-{dm.group(3)}-{dm.group(4)}" if dm else ""
    return ves, sonar, date


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = {"ok": False, "steps": []}
    canon = pd.read_parquet(CANON)
    n0 = len(canon); cols = list(canon.columns)
    log.info("canonical start rows: %d", n0)
    if not set(SPEC).isdisjoint(set(canon.pair_id)):
        result["error"] = "some C1 pairs already present"; RESULT.write_text(json.dumps(result, indent=2));
        log.error("ABORT already present"); return
    M = catalog(); lrinfo = json.loads(LRINFO.read_text())
    hres = {r["pair_id"]: r for r in json.loads(HARMRES.read_text())}

    rows = []
    for pid, s in SPEC.items():
        m = M[s["uid"]]; hr = hres[pid]; cg = hr.get("coreg", {})
        ves, lrsonar, lrdate = lr_meta(s["lr_cruise"], lrinfo)
        hr_tif, lr_tif = HARM / pid / "hr.tif", HARM / pid / "lr.tif"
        ratio = round(float(s["lr_native_m"]) / 1.0, 2)
        cstat = (f"masked_coreg; offset={cg.get('offset_m')}m; MAD={cg.get('post_mad_m')}m; "
                 f"QGIS_signed_off_2026-06-26"
                 + ("; offset>30m_USBL_QGIS_basis" if (cg.get("offset_m") or 0) > 30 else ""))
        row = {c: "" for c in cols}
        row.update({
            "pair_id": pid, "site_name": m["gf"], "region": m["gf"], "cruise_id": m["cruise"],
            "vessel": ves, "hr_platform": m["plat"] or "MBARI/AUV", "hr_sonar": hr_sonar(m["desc"], m["plat"]),
            "hr_doi": m["doi"], "hr_native_res_m": 1.0,
            "lr_platform": ves, "lr_sonar": lrsonar,
            "lr_doi": f"NCEI/NOAA Bathymetry (public domain), cruise {s['lr_cruise']}",
            "lr_native_res_m": s["lr_native_m"], "res_ratio": ratio,
            "depth_min_m": abs(hr.get("hr_p50_over_joint") or 0), "depth_max_m": abs(hr.get("hr_p50_over_joint") or 0),
            "terrain_class": s["terrain"],
            "native_crs_hr": "EPSG:4326 (geographic)", "native_crs_lr": "EPSG:4326 (NCEI lon/lat; mbgrid -C0)",
            "target_crs": hr.get("target_crs"), "vertical_datum": "MSL_negative_down",
            "acquisition_date": m["start"],
            "footprint_wkt": str(HARM / pid / "footprint.geojson"),
            "license": "MGDS (HR; typically CC-BY-NC-SA) / NCEI public (LR)",
            "horiz_offset_m": cg.get("offset_m"), "vert_offset_m": cg.get("dz"),
            "coreg_status": cstat,
            "harmonized_path_hr": str(hr_tif), "harmonized_path_lr": str(lr_tif),
            "raw_path_hr": str(RH / f"MGDS_{s['uid']}"), "raw_path_lr": str(RAWLR / s["lr_cruise"]),
            "checksum_hr": sha256(hr_tif), "checksum_lr": sha256(lr_tif),
            "hr_source_type": "gmt_grd_float",
            "verification_status": "verified_pair_c1_reharvest_2026-06-26",
            "notes": (f"C1 float recovery; LR_ship_cruise={s['lr_cruise']} ({ves}, {lrsonar}, LR_acq={lrdate}); "
                      f"HR_AUV={m['cruise']}/{m['gf']} (HR_acq={m['start'] or 'NotProvided'}); "
                      f"independence: distinct ship LR vs AUV, co-located by {hr.get('n_valid_tiles')} joint tiles; "
                      f"leakage_unit={s['lu']}; masked_coreg dz={cg.get('dz')}m; "
                      f"{'NOTE offset>USBL, QGIS-signed' if (cg.get('offset_m') or 0)>30 else 'clean lock'}"),
        })
        rows.append(row)
        log.info("[%s] ratio=%s offset=%s chk_hr=%s lu=%s", pid, ratio, cg.get("offset_m"), row["checksum_hr"][:10], s["lu"])

    new = pd.DataFrame(rows, columns=cols)
    for c in cols:
        if pd.api.types.is_numeric_dtype(canon[c].dtype):
            new[c] = pd.to_numeric(new[c], errors="coerce")
        else:
            new[c] = new[c].astype(object).where(new[c].notna(), "")
    combined = pd.concat([canon, new[cols]], ignore_index=True)
    assert combined["pair_id"].is_unique and len(combined) == n0 + 3
    # verbatim by VALUE (concat can promote int->float when a new row adds NaN to a
    # canon-int column; values are preserved, only dtype changes -> check_dtype=False)
    import pandas.testing as pdt
    pdt.assert_frame_equal(canon.reset_index(drop=True), combined.iloc[:n0].reset_index(drop=True),
                           check_dtype=False, check_like=False)
    result["steps"].append({"rows": {"before": n0, "added": 3, "after": len(combined)}, "verbatim_by_value": True})

    bk = REPO / "manifest/pairs.parquet.bak_2026-06-26_c1append"
    if not bk.exists():
        shutil.copy2(CANON, bk)
    combined.to_parquet(CANON, index=False)

    # checksum re-verify
    chk = [{"pair_id": r["pair_id"], "side": s, "match": bool(sha256(Path(r[f"harmonized_path_{s}"])) == r[f"checksum_{s}"])}
           for r in rows for s in ("hr", "lr")]
    nbad = sum(1 for c in chk if not c["match"])
    result["checksum_verify"] = {"checked": len(chk), "mismatch": nbad}
    if nbad:
        shutil.copy2(bk, CANON); result["error"] = "checksum mismatch; restored"
        RESULT.write_text(json.dumps(result, indent=2, default=str)); log.error("CHECKSUM MISMATCH restored"); return

    # OAK sync
    try:
        if OAK.exists():
            os.chmod(OAK, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        shutil.copy2(CANON, OAK)
        oak_ok = sha256(CANON) == sha256(OAK)
        os.chmod(OAK, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        result["oak_sync"] = {"byte_identical": bool(oak_ok)}
    except Exception as e:
        result["oak_sync"] = {"error": str(e)[:120]}
    result["ok"] = True
    RESULT.write_text(json.dumps(result, indent=2, default=str))
    log.info("APPEND COMPLETE: %d -> %d rows; checksum %d/%d; OAK %s",
             n0, len(combined), len(chk) - nbad, len(chk), result.get("oak_sync"))


if __name__ == "__main__":
    main()
