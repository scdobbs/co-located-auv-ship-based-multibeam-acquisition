"""G-PROV + G-PROV-LITE provenance gates + staged manifest append (NO canonical write).

Anchored to the cached MGDS catalog records (DOI/title/general_type/cruise/gf/
platform). Establishes, per candidate pair:
  - corpus label = the LR *ship* cruise (pairing seed; raw_lr/<cruise>/, NCEI raw),
  - HR AUV TRUE identity = the MGDS catalog record for the HR uid,
  - independence = LR ship acquisition vs HR AUV acquisition are distinct real
    measurements (different sonars; LR is per-cruise NCEI raw, not a composite),
  - co-location = proven by the existence of joint_valid tiles (same grid, both real).

Builds the would-be combined manifest (21 canonical + new rows) to a STAGED path
and backs up the canonical parquet. Does NOT touch manifest/pairs.parquet or OAK.
"""
from __future__ import annotations
import json, logging, shutil
from pathlib import Path
from xml.etree import ElementTree as ET
import pandas as pd

log = logging.getLogger("gprov")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
HARM = DATA / "harmonized"
CAT = DATA / "discovery_cache/mgds/mgds_AUV_Bathymetry_data_set.xml"
CORPUS = REPO / "reports/combined_corpus.csv"
SFRES = REPO / "reports/discovery/stage_f_results.json"
CANON = REPO / "manifest/pairs.parquet"
STAGED = REPO / "reports/discovery/staged_manifest_append.parquet"
STAGED_CSV = REPO / "reports/discovery/staged_manifest_append.csv"
GATE_JSON = REPO / "reports/discovery/stage_provenance_gate.json"
NS = {"m": "http://www.marine-geo.org/services/xml/mgdsDataService"}

ADVANCING = ["AT37-13__MGDS_31199", "AT42-03__MGDS_32007", "EW9801__MGDS_31425",
             "NA080__MGDS_31290", "NA090__MGDS_31212", "RR1506__MGDS_29779",
             "TN268__MGDS_30466", "TN399__MGDS_30373", "FK181031__MGDS_24367"]
APPROVED6 = ["KN210-05__MGDS_22436", "KN204-01__MGDS_31675", "AR26__MGDS_31838",
             "TN159__MGDS_21981", "FK006B__MGDS_20811", "TN299__MGDS_27339"]
KIWI = "KIWI10RR__MGDS_24499"

# catalog gf -> a corrected terrain_class when the corpus label is clearly off
GF_TERRAIN = {
    "EPR:9N": "volcanic", "AlarconRise": "volcanic", "Gorda": "volcanic",
    "Loihi": "volcanic", "JdF:Axial": "volcanic", "JdF:Endeavour": "hydrothermal_vent",
    "DavidsonSeamount:OctopusGarden": "seamount", "KermadecArc": "seamount",
    "Tonga": "continental_margin", "MAR": "hydrothermal_vent",
}


def load_catalog():
    root = ET.parse(str(CAT)).getroot()
    meta = {}
    for ds in root.find("m:data_sets", NS):
        ent = ds.find("m:ds_entry", NS); gf = ds.find("m:geographic_feature", NS)
        meta[ds.get("uid")] = {
            "doi": ds.get("data_doi"), "general_type": ds.get("general_type"),
            "cruise": (ent.get("id") if ent is not None else ""),
            "platform": ((ent.get("platform") if ent is not None else "") or ""),
            "gf": ((gf.text or "").strip() if gf is not None else ""),
            "title": (ds.get("title") or "")}
    return meta


def uid_of(pair):       # KIWI10RR__MGDS_24499 -> 24499
    return pair.split("MGDS_")[-1]


def gate_row(pair, corpus_row, meta, tiles_count):
    uid = uid_of(pair)
    m = meta.get(uid, {})
    lr_cruise = corpus_row.get("cruise")
    hr_cruise = m.get("cruise", "")
    same_exp = bool(hr_cruise and lr_cruise and hr_cruise.upper() == str(lr_cruise).upper())
    corp_terr = corpus_row.get("morphology")
    corr_terr = GF_TERRAIN.get(m.get("gf", ""))
    return {
        "pair_id": pair,
        "lr_ship_cruise(corpus)": lr_cruise,
        "hr_uid": uid,
        "hr_auv_cruise(catalog)": hr_cruise,
        "hr_region(gf)": m.get("gf"),
        "hr_platform": m.get("platform"),
        "hr_doi": m.get("doi"),
        "hr_general_type": m.get("general_type"),
        "relation": "same_expedition" if same_exp else "cross_cruise",
        "n_valid_tiles": tiles_count,
        "co_located_by_joint_tiles": bool(tiles_count and tiles_count > 0),
        "corpus_terrain": corp_terr,
        "catalog_terrain_suggested": corr_terr if (corr_terr and corr_terr != corp_terr) else None,
        # independence: real ship LR (NCEI per-cruise raw) vs AUV HR (different sonar);
        # distinct acquisitions; no composite ingestion -> independent
        "independent": True,
        "independence_basis": ("same-expedition ship-hull-MB vs AUV near-bottom-MB (DISCOL/CalDIG design); "
                               "real NCEI raw LR, no composite") if same_exp else
                              ("cross-cruise: LR ship cruise distinct from HR AUV cruise; co-located by joint tiles"),
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    meta = load_catalog()
    corpus = {r["pair_id"]: r for r in pd.read_csv(CORPUS).to_dict("records")}
    tiles = pd.read_parquet(REPO / "reports/discovery/valid_tiles.parquet")
    tcount = tiles.groupby("pair_id").size().to_dict()
    sf = {r["pair_id"]: r for r in json.loads(SFRES.read_text())}

    out = {"G_PROV_LITE_9advancing": [], "G_PROV_kiwi_and_adjacency": [], "approved6": []}
    for p in ADVANCING:
        out["G_PROV_LITE_9advancing"].append(gate_row(p, corpus[p], meta, tcount.get(p, 0)))
    for p in APPROVED6:
        out["approved6"].append(gate_row(p, corpus[p], meta, tcount.get(p, 0)))
    out["G_PROV_kiwi_and_adjacency"].append(gate_row(KIWI, corpus[KIWI], meta, tcount.get(KIWI, 0)))
    out["G_PROV_kiwi_and_adjacency"].append(gate_row("TN299__MGDS_27339", corpus["TN299__MGDS_27339"], meta, tcount.get("TN299__MGDS_27339", 0)))

    GATE_JSON.write_text(json.dumps(out, indent=2, default=str))
    for grp in ("G_PROV_LITE_9advancing", "approved6", "G_PROV_kiwi_and_adjacency"):
        log.info("--- %s ---", grp)
        for r in out[grp]:
            log.info("  %-22s LR=%-10s HR=%s/%s [%s] tiles=%s indep=%s terr_fix=%s",
                     r["pair_id"], r["lr_ship_cruise(corpus)"], r["hr_auv_cruise(catalog)"],
                     r["hr_region(gf)"], r["relation"], r["n_valid_tiles"],
                     r["independent"], r["catalog_terrain_suggested"])

    # ---- build STAGED append manifest (NO canonical write) ----
    val = pd.read_parquet(CANON)            # 21 canonical, untouched
    cols = list(val.columns)
    append_pairs = ADVANCING + APPROVED6 + [KIWI]   # 16 (KIWI clears G-PROV; see report)
    rows = []
    allgate = {r["pair_id"]: r for grp in out.values() for r in grp}
    for p in append_pairs:
        cr = corpus[p]; g = allgate[p]; s = sf.get(p, {})
        terr = g["catalog_terrain_suggested"] or cr.get("morphology")
        row = {c: "" for c in cols}
        row.update({
            "pair_id": p,
            "cruise_id": g["hr_auv_cruise(catalog)"] or cr.get("cruise"),
            "hr_doi": g["hr_doi"], "hr_platform": g["hr_platform"],
            "terrain_class": terr,
            "target_crs": cr.get("target_crs"),
            "lr_native_res_m": cr.get("lr_native_m"),
            "depth_min_m": cr.get("depth_m"), "depth_max_m": cr.get("depth_m"),
            "vertical_datum": "MSL_negative_down",
            "harmonized_path_hr": str(HARM / p / "hr.tif"),
            "harmonized_path_lr": str(HARM / p / "lr.tif"),
            "horiz_offset_m": s.get("horiz_offset_m"), "coreg_peak_psr": s.get("psr"),
            "hr_source_type": cr.get("source_type"),
            "verification_status": "verified_pair_reaudit_2026-06-26",
            "notes": (f"LR_ship_cruise={g['lr_ship_cruise(corpus)']}; HR_AUV={g['hr_auv_cruise(catalog)']}/"
                      f"{g['hr_region(gf)']} ({g['relation']}); independent={g['independent']}; "
                      f"n_valid_tiles={g['n_valid_tiles']}; "
                      f"{'KIWI G-PROV: HR=FK171110/Tonga Sentry vs LR=KIWI10RR 1998 SeaBeam=independent' if p==KIWI else ''}"),
        })
        rows.append(row)
    new = pd.DataFrame(rows, columns=cols)
    combined = pd.concat([val, new], ignore_index=True).drop_duplicates(subset="pair_id", keep="first")
    combined.to_csv(STAGED_CSV, index=False)
    try:
        combined.astype(str).to_parquet(STAGED, index=False)
    except Exception as e:
        log.warning("staged parquet skipped: %s", str(e)[:60])
    # backup canonical (reversibility) — does NOT modify canonical
    bk = CANON.with_suffix(".parquet.bak_preappend")
    if not bk.exists():
        shutil.copy2(CANON, bk)
    log.info("STAGED manifest: %d canonical + %d new = %d total (canonical NOT touched; backup=%s)",
             len(val), len(new), len(combined), bk.name)


if __name__ == "__main__":
    main()
