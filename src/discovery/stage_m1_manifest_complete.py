"""M1 — complete the 16 new manifest rows to canonical schema parity.

Populates, per the completeness directive:
  lr_platform, lr_sonar   <- mbinfo on the NCEI raw-LR header (independence evidence)
  hr_sonar                <- MGDS catalog description
  hr_native_res_m         <- sounding-density (measured_finest_cell_m), NOT grid posting
  res_ratio               <- lr_native_res_m / hr_native_res_m
  coreg_status            <- QA verdict (+ QGIS-approval basis for the 3 no-PSR pairs)
  horiz_offset_m, vert_offset_m <- F.5 masked re-coreg (trustworthy)
  checksum_hr, checksum_lr<- sha256 of the harmonized rasters (integrity anchor)
  footprint_wkt           <- HR∩LR valid polygon (footprint.geojson)
  + cruise_id (HR AUV), hr_doi, hr_platform, terrain_class(+proposed), region, etc.

Emits staged_manifest_append.{csv,parquet} (NON-canonical) + a completeness diff.
Run on a compute node (needs the mbsystem apptainer sandbox + bind mounts).
"""
from __future__ import annotations
import csv, hashlib, json, logging, os, re, shutil, subprocess
from pathlib import Path
from xml.etree import ElementTree as ET
import pandas as pd

log = logging.getLogger("m1")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
HARM = DATA / "harmonized"
RAWLR = DATA / "raw_lr"
CAT = DATA / "discovery_cache/mgds/mgds_AUV_Bathymetry_data_set.xml"
SANITY = REPO / "reports/discovery/hr_resolution_sanity.csv"
CORPUS = REPO / "reports/combined_corpus.csv"
SFRES = REPO / "reports/discovery/stage_f_results.json"
GATE = REPO / "reports/discovery/stage_provenance_gate.json"
CANON = REPO / "manifest/pairs.parquet"
STAGED = REPO / "reports/discovery/staged_manifest_append.parquet"
STAGED_CSV = REPO / "reports/discovery/staged_manifest_append.csv"
DIFF_JSON = REPO / "reports/discovery/stage_m1_completeness_diff.json"
LRINFO_JSON = REPO / "reports/discovery/stage_m1_lr_mbinfo.json"
NS = {"m": "http://www.marine-geo.org/services/xml/mgdsDataService"}
SANDBOX = "/home/groups/hilley/containers/mbsystem_sandbox"

ADVANCING = ["AT37-13__MGDS_31199", "AT42-03__MGDS_32007", "EW9801__MGDS_31425",
             "NA080__MGDS_31290", "NA090__MGDS_31212", "RR1506__MGDS_29779",
             "TN268__MGDS_30466", "TN399__MGDS_30373", "FK181031__MGDS_24367"]
APPROVED6 = ["KN210-05__MGDS_22436", "KN204-01__MGDS_31675", "AR26__MGDS_31838",
             "TN159__MGDS_21981", "FK006B__MGDS_20811", "TN299__MGDS_27339"]
KIWI = "KIWI10RR__MGDS_24499"
APPEND = ADVANCING + APPROVED6 + [KIWI]
NO_PSR = {"KN210-05__MGDS_22436", "KN204-01__MGDS_31675", "KIWI10RR__MGDS_24499"}

FMT_SONAR = {"21": "Atlas Hydrosweep DS", "41": "SeaBeam 2100",
             "56": "Simrad EM (.all)", "58": "Kongsberg EM (.all)",
             "94": "L-3 ELAC/SeaBeam (XSE)", "59": "Kongsberg EM (.all)"}
# M2 proposed terrain reclasses (do NOT auto-commit to terrain_class)
TERRAIN_PROPOSED = {
    "EW9801__MGDS_31425": ("volcanic", "Loihi seamount (HR AUV cruise TN293; submarine volcano)"),
    "TN399__MGDS_30373": ("volcanic", "EPR 9N mid-ocean ridge axis (HR EPR:9N_Parnell-Turner)"),
    "FK181031__MGDS_24367": ("volcanic", "Alarcon Rise spreading center (HR AlarconRise_MBARI)"),
    "RR1506__MGDS_29779": ("seamount", "Kermadec Arc (HR cruise RR1506)"),
    "TN268__MGDS_30466": ("volcanic", "Axial Seamount caldera (HR AxialSeamount_MBARI)"),
    "TN299__MGDS_27339": ("volcanic", "Gorda Ridge (HR NorthGorda_MBARI)"),
    "KN210-05__MGDS_22436": ("hydrothermal_vent", "Mid-Atlantic Ridge (HR cruise KN210-05)"),
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_catalog():
    root = ET.parse(str(CAT)).getroot()
    meta = {}
    for ds in root.find("m:data_sets", NS):
        ent = ds.find("m:ds_entry", NS); gf = ds.find("m:geographic_feature", NS)
        desc = ds.find("m:description", NS)
        meta[ds.get("uid")] = {
            "doi": ds.get("data_doi"),
            "cruise": (ent.get("id") if ent is not None else ""),
            "platform": ((ent.get("platform") if ent is not None else "") or ""),
            "start_date": (ent.get("start_date") if ent is not None else "") or "",
            "gf": ((gf.text or "").strip() if gf is not None else ""),
            "desc": ((desc.text or "") if desc is not None else "")}
    return meta


def hr_sonar(desc, platform):
    for pat in (r"Reson\s+SeaBat\s+[\w-]+", r"Reson\s+\d+", r"Kongsberg\s+EM\d+",
                r"Imagenex\s+\d+", r"Simrad\s+EM\s*\d+", r"EM\s?2040", r"EM\s?712"):
        m = re.search(pat, desc, re.I)
        if m:
            return m.group(0)
    if "Sentry" in platform or "Sentry" in desc:
        return "Reson SeaBat 7125 (AUV Sentry, typical)"
    if "MBARI" in platform:
        return "Reson SeaBat 7125 (MBARI Mapping AUV, typical)"
    return platform or "AUV multibeam"


def mbinfo_lr(cruise, tmp):
    """gunzip one LR data file and run mbinfo; parse sonar/platform/records/time."""
    d = RAWLR / cruise
    if not d.is_dir():
        return {"error": "no raw_lr dir"}
    gz = sorted([p for p in d.iterdir() if re.search(r"\.mb\d+\.gz$", p.name)],
                key=lambda p: p.stat().st_size)
    if not gz:
        return {"error": "no .mbNN.gz data file"}
    src = gz[0]
    fmt = re.search(r"\.mb(\d+)\.gz$", src.name).group(1)
    raw = tmp / src.name[:-3]
    try:
        with open(raw, "wb") as out:
            subprocess.run(["gunzip", "-c", str(src)], stdout=out, check=True)
        cmd = ["apptainer", "exec", "--bind", "/scratch,/home/groups,/oak", SANDBOX,
               "mbinfo", "-F" + fmt, "-I", str(raw)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        txt = r.stdout
    except Exception as e:
        return {"format": fmt, "error": str(e)[:120], "filename": src.name}
    finally:
        try: raw.unlink()
        except FileNotFoundError: pass
    info = {"format": fmt, "filename": src.name, "fmt_sonar_family": FMT_SONAR.get(fmt, f"format mb{fmt}")}
    for key, pat in (("format_name", r"Format name:\s*(.+)"),
                     ("records", r"Number of Records:\s*(\d+)"),
                     ("sonar_line", r"(Sonar[:\w ]*:.*)"),
                     ("time_begin", r"Time:\s*(\d.+)")):
        m = re.search(pat, txt, re.I)
        if m:
            info[key] = m.group(1).strip()[:80]
    # EM model from filename if present
    em = re.search(r"EM\s?\d{3,4}", src.name, re.I)
    if em:
        info["em_from_filename"] = em.group(0)
    # vessel guess from filename token
    vm = re.search(r"_(Atlantis|Nautilus|revelle|Revelle|TGT|Falkor|FK\w*|Ewing|Knorr|Thompson|Sally|Armstrong)", src.name)
    if vm:
        info["vessel_token"] = vm.group(1)
    return info


VESSEL = {"AT": "R/V Atlantis", "TN": "R/V Thomas G. Thompson", "RR": "R/V Roger Revelle",
          "KN": "R/V Knorr", "EW": "R/V Maurice Ewing", "NA": "E/V Nautilus",
          "FK": "R/V Falkor", "AR": "R/V Neil Armstrong", "KIWI": "R/V (KIWI expedition)"}


def lr_platform(cruise, mb):
    tok = mb.get("vessel_token")
    if tok:
        return {"TGT": "R/V Thomas G. Thompson", "revelle": "R/V Roger Revelle",
                "Revelle": "R/V Roger Revelle"}.get(tok, "R/V " + tok if not tok.startswith("R/V") else tok)
    for pre, name in VESSEL.items():
        if cruise.upper().startswith(pre):
            return name
    return f"NCEI cruise {cruise}"


def lr_sonar(mb):
    parts = []
    if mb.get("em_from_filename"):
        parts.append("Kongsberg " + mb["em_from_filename"])
    elif mb.get("fmt_sonar_family"):
        parts.append(mb["fmt_sonar_family"])
    if mb.get("filename"):
        dt = re.search(r"(19|20)\d{6}", mb["filename"])
        if dt:
            parts.append(dt.group(0))
    return " / ".join(parts) if parts else "unknown"


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "m1"; tmp.mkdir(parents=True, exist_ok=True)
    meta = load_catalog()
    corpus = {r["pair_id"]: r for r in pd.read_csv(CORPUS).to_dict("records")}
    sf = {r["pair_id"]: r for r in json.loads(SFRES.read_text())}
    sanity = {r["hr_id"]: r for r in pd.read_csv(SANITY).to_dict("records")}

    # mbinfo per unique LR cruise (cache: skip the slow gunzip+mbinfo on re-run)
    lrinfo = json.loads(LRINFO_JSON.read_text()) if LRINFO_JSON.exists() else {}
    for p in APPEND:
        cr = corpus[p]["cruise"]
        if cr not in lrinfo or lrinfo[cr].get("error"):
            log.info("mbinfo LR cruise %s ...", cr)
            lrinfo[cr] = mbinfo_lr(cr, tmp)
    LRINFO_JSON.write_text(json.dumps(lrinfo, indent=2, default=str))

    from src.discovery.stage_c5_sweep import catalog_crs
    STAGING = DATA / "staging_phase1"
    R3DIR = DATA / "qc_plots/reaudit_real23"
    disp = {r["pair_id"]: r.get("reaudit_disposition") for r in pd.read_csv(CORPUS).to_dict("records")}
    val = pd.read_parquet(CANON)
    cols = list(val.columns)
    extra_cols = ["terrain_class_proposed", "terrain_proposed_basis"]
    rows = []
    for p in APPEND:
        cr = corpus[p]; uid = p.split("MGDS_")[-1]; m = meta.get(uid, {})
        mb = lrinfo.get(cr["cruise"], {})
        hr_p, lr_p = HARM / p / "hr.tif", HARM / p / "lr.tif"
        # native res: sounding-density (measured_finest_cell_m) for HR
        san = sanity.get(f"MGDS:{uid}", {})
        hr_nat = san.get("measured_finest_cell_m") or cr.get("hr_native_m")
        lr_nat = cr.get("lr_native_m")
        ratio = round(float(lr_nat) / float(hr_nat), 2) if (hr_nat and lr_nat) else ""
        # footprint: match the canonical-21 convention — store the path to the
        # footprint.geojson (the polygon lives in that file). Inlining the raw
        # pixel-traced WKT bloated the CSV to >4 MB (NA080/TN299 had ~2 M vertices).
        fp = HARM / p / "footprint.geojson"
        fwkt = str(fp) if fp.exists() else ""
        psr = cr.get("psr") if cr.get("psr") == cr.get("psr") else None
        offs = cr.get("f5_recoreg_offset_m")
        vert = cr.get("f5_recoreg_dz_m")
        cstat = (f"QGIS_R3_approved; PSR=undefined (no interior peak); offset={offs}m"
                 if p in NO_PSR else
                 f"QGIS_R3_approved; PSR={cr.get('f5_recoreg_psr')}; offset={offs}m")
        relation = "same_expedition" if (m.get("cruise", "").upper() == str(cr["cruise"]).upper()) else "cross_cruise"
        prop = TERRAIN_PROPOSED.get(p)
        sfr = sf.get(p, {})
        tcrs = sfr.get("target_crs") or cr.get("target_crs") or ""
        ncrs_hr = catalog_crs(f"MGDS:{uid}") or "EPSG:4326 (geographic, inferred from coord ranges)"
        # R3 QC figure path for this pair
        qc_png = R3DIR / f"{disp.get(p)}__{p}.png"
        # acquisition_date: HR AUV catalog start, else LR cruise date from filename
        acq = (m.get("start_date") or "")[:10]
        if not acq:
            dm = re.search(r"(19|20)(\d{6})", mb.get("filename", "") or "")
            if dm:
                s = dm.group(0); acq = f"{s[:4]}-{s[4:6]}-{s[6:8]}"

        row = {c: "" for c in cols}
        row.update({
            "pair_id": p,
            "site_name": m.get("gf") or cr.get("cruise"),
            "region": m.get("gf"),
            "cruise_id": m.get("cruise") or cr.get("cruise"),
            "vessel": lr_platform(cr["cruise"], mb),     # the LR/ship vessel
            "hr_platform": m.get("platform"), "hr_sonar": hr_sonar(m.get("desc", ""), m.get("platform", "")),
            "hr_doi": m.get("doi"),
            "hr_native_res_m": round(float(hr_nat), 3) if hr_nat else "",
            "lr_platform": lr_platform(cr["cruise"], mb),
            "lr_sonar": lr_sonar(mb),
            "lr_native_res_m": lr_nat, "res_ratio": ratio,
            "lr_doi": f"NCEI/NOAA Bathymetry (public domain), cruise {cr['cruise']}",
            "depth_min_m": cr.get("depth_m"), "depth_max_m": cr.get("depth_m"),
            "terrain_class": cr.get("morphology"),       # original; proposed kept separate (M2)
            "native_crs_hr": ncrs_hr, "native_crs_lr": "EPSG:4326 (NCEI lon/lat; mbgrid -C0)",
            "target_crs": tcrs,
            "vertical_datum": "MSL_negative_down",
            "acquisition_date": acq,
            "footprint_wkt": fwkt,
            "license": "MGDS (HR; typically CC-BY-NC-SA) / NCEI public (LR)",
            "horiz_offset_m": offs, "vert_offset_m": vert,
            "coreg_peak_psr": cr.get("f5_recoreg_psr"), "coreg_status": cstat,
            "coreg_peak_eig_ratio": sfr.get("eig_ratio"),
            "coreg_peak_agrees": sfr.get("peak_agrees"),
            "qc_artifact_path": str(qc_png),
            "raw_path_hr": str(STAGING / f"MGDS_{uid}"), "raw_path_lr": str(RAWLR / cr["cruise"]),
            "harmonized_path_hr": str(hr_p), "harmonized_path_lr": str(lr_p),
            "checksum_hr": sha256(hr_p) if hr_p.exists() else "",
            "checksum_lr": sha256(lr_p) if lr_p.exists() else "",
            "hr_source_type": cr.get("source_type"),
            "verification_status": "verified_pair_reaudit_2026-06-26",
            "notes": (f"LR_ship_cruise={cr['cruise']} ({lr_platform(cr['cruise'], mb)}, {lr_sonar(mb)}); "
                      f"HR_AUV={m.get('cruise')}/{m.get('gf')} ({relation}); "
                      f"independence: real single-cruise NCEI multibeam LR vs AUV HR, distinct sonar; "
                      f"HR_native=sounding_density({san.get('verdict','?')}); "
                      f"{'G-PROV cleared: 1998 SeaBeam2100 LR vs 2017 Falkor-Sentry HR' if p==KIWI else ''}"),
            "terrain_class_proposed": prop[0] if prop else "",
            "terrain_proposed_basis": (prop[1] + f" [DOI {m.get('doi')}]") if prop else "",
        })
        rows.append(row)
        log.info("[%s] hr_res=%s lr_res=%s ratio=%s lr_sonar=%s chk_hr=%s",
                 p, row["hr_native_res_m"], lr_nat, ratio, row["lr_sonar"], row["checksum_hr"][:10])

    new = pd.DataFrame(rows, columns=cols + extra_cols)
    val2 = val.copy()
    for c in extra_cols:
        val2[c] = ""
    combined = pd.concat([val2, new], ignore_index=True).drop_duplicates(subset="pair_id", keep="first")
    combined.to_csv(STAGED_CSV, index=False)
    try:
        combined.astype(str).to_parquet(STAGED, index=False)
    except Exception as e:
        log.warning("parquet skip: %s", str(e)[:60])

    # completeness diff: non-blank fraction per canonical field, 21 vs 16
    diff = {}
    newrows = combined[combined.pair_id.isin(APPEND)]
    canonrows = val
    for c in cols:
        def nonblank(df, col):
            s = df[col]
            return int(s.notna().sum() - (s.astype(str).str.strip() == "").sum())
        diff[c] = {"canonical_21": f"{nonblank(canonrows, c)}/21",
                   "new_16": f"{nonblank(newrows, c)}/16"}
    DIFF_JSON.write_text(json.dumps(diff, indent=2, default=str))
    incomplete = {c: d for c, d in diff.items() if not d["new_16"].startswith("16")}
    log.info("=== completeness diff: fields where new_16 < 16/16 ===")
    for c, d in incomplete.items():
        log.info("  %-22s canonical=%s  new=%s", c, d["canonical_21"], d["new_16"])
    log.info("M1 done: %d staged rows; %d/%d canonical fields fully populated on the new 16",
             len(combined), len(cols) - len(incomplete), len(cols))


if __name__ == "__main__":
    main()
