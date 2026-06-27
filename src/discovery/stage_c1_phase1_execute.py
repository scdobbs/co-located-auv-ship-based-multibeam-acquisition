"""Execute Phase-1 canonical changes (Steve signed off; addendum v1.1).

C1 supersede TN268x30466 IN PLACE (pair_id stable): HR -> SRift (uid 32556),
hr_superseded_doi = old 30466 DOI, preserve old HR file, update paths/checksums/
offsets/footprint. Append EW0207x32556 (NRift, disjoint sub-grid of 32556) and
2009_Amundsen x30046 (Arctic). Correct NA076x32317 lr_native 221->~23 (P1.4).

Append-only; the 21 validated preserved verbatim-by-value; backup before write;
checksum re-verify; OAK sync + re-lock. 37 -> 39.
"""
from __future__ import annotations
import hashlib, json, logging, os, re, shutil, stat
from pathlib import Path
from xml.etree import ElementTree as ET
import pandas as pd

log = logging.getLogger("c1exec")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
HARM = DATA / "harmonized"
RAWLR = DATA / "raw_lr"
RH = DATA / "reharvest_c1"
CAT = DATA / "discovery_cache/mgds/mgds_AUV_Bathymetry_data_set.xml"
CANON = REPO / "manifest/pairs.parquet"
OAK = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy/manifest/pairs.parquet")
PH1 = REPO / "reports/discovery/stage_c1_phase1_results.json"
ARC = REPO / "reports/discovery/stage_c1_arctic_harmonize.json"
RESULT = REPO / "reports/discovery/stage_c1_phase1_execute_result.json"
NS = {"m": "http://www.marine-geo.org/services/xml/mgdsDataService"}

P14_NA076_LR_NATIVE = 22.9   # P1.4 corrected (artifact 221 -> measured ~23)


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


def lr_meta(cruise):
    d = RAWLR / cruise
    fn = next((p.name for p in d.iterdir() if re.search(r"\.mb\d+", p.name)), "") if d.is_dir() else ""
    vmap = {"Amundsen": "CCGS Amundsen", "ShipName": "", "TGT": "R/V Thomas G. Thompson"}
    ves = next((v for k, v in vmap.items() if k.lower() in fn.lower()), None)
    if not ves:
        ves = {"EW": "R/V Maurice Ewing"}.get(cruise[:2], f"NCEI cruise {cruise}")
    fmt = (re.search(r"\.mb(\d+)", fn) or [None, "?"])[1]
    em = re.search(r"EM\s?\d{3,4}", fn)
    sonar = ("Kongsberg " + em.group(0)) if em else (f"Kongsberg EM (.all)" if fmt == "58" else f"MB-format-{fmt} multibeam")
    dm = re.search(r"(19|20)(\d{2})(\d{2})(\d{2})", fn)
    date = f"{dm.group(1)}{dm.group(2)}-{dm.group(3)}-{dm.group(4)}" if dm else ""
    return ves, sonar, date


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = {"ok": False, "steps": []}
    M = catalog()
    ph1 = json.loads(PH1.read_text()); arc = json.loads(ARC.read_text())
    canon = pd.read_parquet(CANON); n0 = len(canon); cols = list(canon.columns)
    assert n0 == 37, f"expected 37, got {n0}"
    # P2-PRE-2 fix: the 21 validated carry verification_status='verified_pair'
    # (same as new pairs), so selecting by that status matched ZERO rows and the
    # verbatim guard passed on an empty set. Use the __MGDS_ discriminator anchor.
    from src.discovery.validated_anchor import VALIDATED_PAIR_IDS
    validated = set(canon.pair_id) & VALIDATED_PAIR_IDS
    assert len(validated) == 21, f"validated anchor cardinality {len(validated)} != 21 (empty-set guard would be vacuous)"

    bk = REPO / "manifest/pairs.parquet.bak_2026-06-26_phase1exec"
    if not bk.exists():
        shutil.copy2(CANON, bk)

    # ---- C1 filesystem supersede: TN268x30466 HR -> SRift (preserve old HR) ----
    pdir = HARM / "TN268__MGDS_30466"; cand = HARM / "TN268__MGDS_32556_SRiftSupersede"
    if not (pdir / "hr_preSupersede.tif").exists():
        shutil.copy2(pdir / "hr.tif", pdir / "hr_preSupersede.tif")  # preserve old HR
    for f in ("hr.tif", "lr.tif", "footprint.geojson", "hr_valid.tif", "lr_valid.tif", "joint_valid.tif"):
        if (cand / f).exists():
            shutil.copy2(cand / f, pdir / f)
    res["steps"].append("supersede files copied; old HR preserved as hr_preSupersede.tif")

    # ---- NRift dir rename to pair_id ----
    nrift_old = HARM / "EW0207__MGDS_32556_NRift"; nrift = HARM / "EW0207__MGDS_32556"
    if nrift_old.exists() and not nrift.exists():
        nrift_old.rename(nrift)

    # ---- build/modify rows ----
    df = canon.copy()
    sr = ph1["P1_1_supersede"]; nr = next(c for c in ph1["P1_2_nrift"]["candidates"] if c["lr"] == "EW0207")

    # (1) supersede TN268x30466 in place
    i = df.index[df.pair_id == "TN268__MGDS_30466"][0]
    df.at[i, "hr_superseded_doi"] = df.at[i, "hr_doi"]
    df.at[i, "hr_superseded_reason"] = "preliminary axsrift_auv1m -> ver2025 SRift (uid 32556), refined processing, same MBARI Axial survey + larger coverage"
    df.at[i, "hr_doi"] = M["32556"]["doi"]
    df.at[i, "checksum_hr"] = sha256(pdir / "hr.tif"); df.at[i, "checksum_lr"] = sha256(pdir / "lr.tif")
    df.at[i, "horiz_offset_m"] = sr["coreg"]["offset_m"]; df.at[i, "vert_offset_m"] = sr["coreg"]["dz"]
    df.at[i, "coreg_status"] = f"SUPERSEDE ver2025 SRift; masked_coreg offset={sr['coreg']['offset_m']}m MAD={sr['coreg']['post_mad_m']}m; QGIS_signed_off_2026-06-26"
    df.at[i, "hr_source_type"] = "gmt_grd_float"
    df.at[i, "notes"] = (str(df.at[i, "notes"]) + f" | SUPERSEDED 2026-06-26: HR->SRift ver2025 (uid32556, SRift sub-grid; disjoint from EW0207x32556=NRift); n_valid_tiles 825->{sr['n_valid_tiles']}; old HR preserved hr_preSupersede.tif; leakage_unit=22")

    # (2) NRift new pair EW0207x32556
    def new_row(pid, uid, lr_cruise, terrain, lr_native, coreg, ntiles, p50, lu, hr_grid_note):
        m = M[uid]; ves, lrson, lrdate = lr_meta(lr_cruise); pdir2 = HARM / pid
        row = {c: "" for c in cols}
        row.update({"pair_id": pid, "site_name": m["gf"], "region": m["gf"], "cruise_id": m["cruise"],
            "vessel": ves, "hr_platform": m["plat"] or "MBARI/AUV", "hr_sonar": "Reson SeaBat 7125 (MBARI/Sentry AUV, typical)",
            "hr_doi": m["doi"], "hr_native_res_m": 1.0, "lr_platform": ves, "lr_sonar": lrson,
            "lr_doi": f"NCEI/NOAA Bathymetry (public domain), cruise {lr_cruise}",
            "lr_native_res_m": lr_native, "res_ratio": round(lr_native / 1.0, 2),
            "depth_min_m": abs(p50 or 0), "depth_max_m": abs(p50 or 0), "terrain_class": terrain,
            "native_crs_hr": "EPSG:4326 (geographic)", "native_crs_lr": "EPSG:4326 (NCEI lon/lat; mbgrid -C0)",
            "target_crs": (HARM / pid), "vertical_datum": "MSL_negative_down", "acquisition_date": m["start"],
            "footprint_wkt": str(pdir2 / "footprint.geojson"),
            "license": "MGDS (HR; typically CC-BY-NC-SA) / NCEI public (LR)",
            "horiz_offset_m": coreg["offset_m"], "vert_offset_m": coreg["dz"],
            "coreg_status": f"masked_coreg offset={coreg['offset_m']}m MAD={coreg['post_mad_m']}m; QGIS_signed_off_2026-06-26" + ("; offset>30m_USBL_QGIS_basis" if coreg["offset_m"] > 30 else ""),
            "harmonized_path_hr": str(pdir2 / "hr.tif"), "harmonized_path_lr": str(pdir2 / "lr.tif"),
            "raw_path_hr": str(RH / f"MGDS_{uid}"), "raw_path_lr": str(RAWLR / lr_cruise),
            "checksum_hr": sha256(pdir2 / "hr.tif"), "checksum_lr": sha256(pdir2 / "lr.tif"),
            "hr_source_type": "gmt_grd_float", "verification_status": "verified_pair_c1_reharvest_2026-06-26",
            "notes": (f"C1 float recovery; LR_ship_cruise={lr_cruise} ({ves}, {lrson}, LR_acq={lrdate}); "
                      f"HR_AUV={m['cruise']}/{m['gf']} ({hr_grid_note}; HR_acq={m['start'] or 'NotProvided'}); "
                      f"independence: distinct ship LR vs AUV, co-located by {ntiles} joint tiles; leakage_unit={lu}")})
        # target_crs as string
        row["target_crs"] = {"EW0207__MGDS_32556": "EPSG:32609", "2009_Amundsen__MGDS_30046": "EPSG:32608"}.get(pid, "")
        return row

    rows_new = [
        new_row("EW0207__MGDS_32556", "32556", "EW0207", "volcanic", 87.8, nr["coreg"], nr["n_valid_tiles"], nr["hr_p50"], 22,
                "NRift sub-grid of uid32556; disjoint from TN268x30466=SRift; no shared HR pixels"),
        new_row("2009_Amundsen__MGDS_30046", "30046", "2009_Amundsen", "shelf_slope", 42.0, arc["coreg"], arc["n_valid_tiles"], arc["hr_p50_over_joint"], "new(Arctic)",
                "Shelf_Edge_Scar_w_Adj_Remnant sub-grid; only Arctic/shelf-slope; 4 more 30046 sub-grids available"),
    ]

    # (3) P1.4 NA076 ratio fix
    j = df.index[df.pair_id == "NA076__MGDS_32317"][0]
    df.at[j, "lr_native_res_m"] = P14_NA076_LR_NATIVE; df.at[j, "res_ratio"] = round(P14_NA076_LR_NATIVE / 1.0, 2)
    df.at[j, "notes"] = str(df.at[j, "notes"]) + f" | P1.4 2026-06-26: lr_native_res_m 221->{P14_NA076_LR_NATIVE} (derivation artifact; EM302 footprint ~15m, grid posting 15.2m, sqrt-fill proxy ~23m); rasters unchanged"

    new = pd.DataFrame(rows_new, columns=cols)
    for c in cols:
        if pd.api.types.is_numeric_dtype(canon[c].dtype):
            new[c] = pd.to_numeric(new[c], errors="coerce")
        else:
            new[c] = new[c].astype(object).where(new[c].notna(), "")
    combined = pd.concat([df, new[cols]], ignore_index=True)
    assert combined.pair_id.is_unique and len(combined) == n0 + 2

    # 21 validated preserved verbatim-by-value
    import pandas.testing as pdt
    a = canon[canon.pair_id.isin(validated)].sort_values("pair_id").reset_index(drop=True)
    b = combined[combined.pair_id.isin(validated)].sort_values("pair_id").reset_index(drop=True)
    pdt.assert_frame_equal(a, b, check_dtype=False)
    res["steps"].append({"validated_21_verbatim": True, "rows": len(combined)})

    combined.to_parquet(CANON, index=False)

    # checksum re-verify for changed/new pairs
    chk = []
    for pid in ("TN268__MGDS_30466", "EW0207__MGDS_32556", "2009_Amundsen__MGDS_30046"):
        for side in ("hr", "lr"):
            p = HARM / pid / f"{side}.tif"
            manifest_val = combined[combined.pair_id == pid][f"checksum_{side}"].iloc[0]
            chk.append({"pair_id": pid, "side": side, "match": bool(sha256(p) == manifest_val)})
    nbad = sum(1 for c in chk if not c["match"])
    res["checksum_verify"] = {"checked": len(chk), "mismatch": nbad}
    if nbad:
        shutil.copy2(bk, CANON); res["error"] = "checksum mismatch; restored"
        RESULT.write_text(json.dumps(res, indent=2, default=str)); log.error("MISMATCH restored"); return

    # OAK sync
    try:
        if OAK.exists():
            os.chmod(OAK, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        shutil.copy2(CANON, OAK)
        oak_ok = sha256(CANON) == sha256(OAK)
        os.chmod(OAK, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        res["oak_sync"] = {"byte_identical": bool(oak_ok)}
    except Exception as e:
        res["oak_sync"] = {"error": str(e)[:120]}
    res["ok"] = True
    RESULT.write_text(json.dumps(res, indent=2, default=str))
    log.info("EXEC COMPLETE: %d->%d rows; supersede TN268x30466; +EW0207x32556 +2009_Amundsenx30046; NA076 ratio fix; checksum %d/%d; OAK %s",
             n0, len(combined), len(chk) - nbad, len(chk), res.get("oak_sync"))


if __name__ == "__main__":
    main()
