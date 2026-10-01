"""ACQ-R03 §6 — manifest v2.1 (`manifest/pairs_v2_1.parquet`, `manifest/pairs_v2_1_dropped.csv`) under rulings_ACQ-R03.
`pairs_v2.parquet` is not modified.  Every row changed under a ruling carries `ruling_source = "rulings_ACQ-R03 R<n>"`.

R1  AT37-05__MGDS_24043 -> dropped (ship_internal_inconsistency); vu05 removed.
R2  PANGAEA_864677__PANGAEA_889317 (pu01) -> dropped (coreg_fail); files on OAK untouched.
R3  pu00 not acquired yet: no row (added as v2.1.1 when its chain finishes).
R4  ship_products_usable = false, reason registration_shift_unresolved (rulings R4) for ccz_so268_1, discol_so242_1,
    tag_m127 (and AT37-05, moot); true for every other pair with available, unflagged products; false with the flag
    reason for EW0207 (vertical_offset stands); null where no products.
R5  2009_Amundsen__MGDS_30046 -> harmonized_path = <pair>/lrv2_1 (lr_v2_1), lr_native / k / flags from the R5 record;
    2009_Amundsen__MGDS_30047 -> lr_native under the unified depth definition (+ k).  Applied when the R5 records exist.
R6  KN182L03__MGDS_30193 (nu01a) and SUM1004__MGDS_33090 (nu03) reinstated as confirmatory rows (path + designation only).
Labels: MGDS:5174 -> EPR 9°N; lu07 name; ACQ-R02 rows' site_name/region/terrain_class/geo_cluster filled from the
verification table and the unit records.
"""
from __future__ import annotations

import json
import sys
from datetime import date

import numpy as np
import pandas as pd

from src.acq_r01 import common as C
from src.acq_r03 import common as R

R02 = R.R02
SETTING_TO_TERRAIN = {"volcanic_or_seamount": "volcanic", "hydrothermal_vent": "hydrothermal_vent", "continental_margin": "continental_margin",
                      "abyssal_plain": "abyssal_plain", "nodule_field": "nodule_field", "seamount": "seamount"}
# unit-level labels for the ACQ-R02 rows (basin from the verification table; setting from the unit records / MGDS titles)
UNIT_LABELS = {
    "nu00": ("Izu-Bonin-Mariana arc (FK151121 / Sentry)", "Pacific", "volcanic"),
    "vu00": ("Gulf of Mexico (AT18-03 / EX1202L2)", "Gulf of Mexico/Caribbean", "continental_margin"),
    "vu02": ("Gulf of Mexico (AT26-14 / EX1402L2)", "Gulf of Mexico/Caribbean", "continental_margin"),
    "lu05": ("EPR 9°N", "Pacific", "volcanic"),
    "lu07": ("TN293 sites (Loihi; Necker Ridge)", "Pacific", "volcanic"),
    "lu13": ("DavidsonSeamount:OctopusGarden", "Pacific", "seamount"),
    "lu18": ("BeaufortSea", "Arctic", "shelf_slope"),
    "nu01a": ("Mid-Atlantic Ridge (AT40-02 / KN182L03)", "Atlantic", "volcanic"),
    "nu01b": ("Mid-Atlantic Ridge (RC2511)", "Atlantic", "volcanic"),
    "nu03": ("Mariana abyssal (NA179 / SUM1004)", "Pacific", "abyssal_plain"),
}


def main():
    m2 = pd.read_parquet(C.REPO / "manifest" / "pairs_v2.parquet")
    dropped = pd.read_csv(C.REPO / "manifest" / "pairs_v2_dropped.csv")
    m = m2.copy()
    m["ruling_source"] = ""; m["ship_products_usable"] = None; m["ship_products_usable_reason"] = ""
    v = pd.read_csv(R02 / "verification" / "candidates_verified.csv").set_index("hr_id")
    dropped_new = []

    def drop(pid, reason, ruling):
        nonlocal m
        row = m[m.pair_id == pid].iloc[0]
        dropped_new.append({"pair_id": pid, "dropped_from": row.designation, "leakage_unit": row.leakage_unit, "lr_cruise": row.lr_cruise, "reason": reason,
                            "harmonized_dir": row.harmonized_path, "ruling_source": ruling})
        m = m[m.pair_id != pid]

    # R1
    drop("AT37-05__MGDS_24043", "ship_internal_inconsistency", "rulings_ACQ-R03 R1")
    # R2 (pu01 was never a v2 row; recorded from its harmonize record)
    h = json.loads((R.REPORT_DIR / "harmonize" / "PANGAEA_864677__PANGAEA_889317.json").read_text())
    dropped_new.append({"pair_id": h["pair_id"], "dropped_from": h["designation"], "leakage_unit": h["unit"], "lr_cruise": h["lr_cruise"],
                        "reason": f"coreg_fail offset={h['coreg']['offset_m']} m dz={h['coreg']['dz_m']} m (1 tile, k=2)", "harmonized_dir": h["out_dir"].replace(str(C.OAK) + "/", ""),
                        "ruling_source": "rulings_ACQ-R03 R2"})
    # R6: reinstate the two confirmatory pairs (path + designation only)
    for pid in ("KN182L03__MGDS_30193", "SUM1004__MGDS_33090"):
        r = json.loads((R02 / "harmonize" / f"{pid}.json").read_text())
        rel = r["out_dir"].replace(str(C.OAK) + "/", "")
        m = pd.concat([m, pd.DataFrame([{"pair_id": pid, "designation": "confirmatory", "harmonized_path": rel, "leakage_unit": r["unit"], "lr_cruise": r["lr_cruise"],
                                          "cruise_id": r.get("hr_cruise", ""), "hr_doi": r["hr_id"], "verification_status": "acq_r02_verified", "qa_status": "pass (QGIS, rulings R6)",
                                          "ruling_source": "rulings_ACQ-R03 R6", "notes": "reinstated by QGIS review under the seal (rulings R6); confirmatory, sealed: no derived statistic"}])],
                      ignore_index=True, sort=False)
        dropped = dropped[dropped.pair_id != pid]
    # labels
    for i, row in m.iterrows():
        u = row.leakage_unit
        if pd.isna(row.get("site_name")) or row.get("site_name") in (None, "", "None"):
            if u in UNIT_LABELS:
                site, basin, terr = UNIT_LABELS[u]
                m.at[i, "site_name"] = site; m.at[i, "region"] = basin; m.at[i, "terrain_class"] = terr
                m.at[i, "geo_cluster"] = f"gc_{u}"
                m.at[i, "ruling_source"] = (m.at[i, "ruling_source"] + "; " if m.at[i, "ruling_source"] else "") + "rulings_ACQ-R03 labels"
        if u == "lu07" and row.get("site_name") == "Loihi":
            m.at[i, "site_name"] = "TN293 sites (Loihi; Necker Ridge)"; m.at[i, "region"] = "Pacific"
            m.at[i, "ruling_source"] = (m.at[i, "ruling_source"] + "; " if m.at[i, "ruling_source"] else "") + "rulings_ACQ-R03 labels"
        if row.pair_id == "AT42-06__MGDS_5174":
            m.at[i, "site_name"] = "EPR 9°N"; m.at[i, "region"] = "Pacific"; m.at[i, "terrain_class"] = "volcanic"
            m.at[i, "notes"] = (str(row.get("notes") or "") + " | location: EPR 9°N (ACQ-R02 text 'Necker-Ridge grid' was wrong; rulings labels)").strip(" |")
            m.at[i, "ruling_source"] = (m.at[i, "ruling_source"] + "; " if m.at[i, "ruling_source"] else "") + "rulings_ACQ-R03 labels"
    # R4 + products usability from the v2.1 products.json
    flags21 = {}
    for i, row in m.iterrows():
        if row.designation in ("lockbox",) or str(row.designation).startswith("confirmatory"):
            continue
        pj = C.OAK / str(row.harmonized_path) / "ship_products_v2_1" / "products.json"
        if not pj.exists():
            m.at[i, "ship_products_usable"] = False; m.at[i, "ship_products_usable_reason"] = "no v2.1 products"; continue
        p = json.loads(pj.read_text())
        if not all(p["available"].values()):
            m.at[i, "ship_products_usable"] = False; m.at[i, "ship_products_usable_reason"] = f"unavailable: {p.get('unavailable_reason', '')[:80]}"; continue
        fl = p["qa_vs_lr_tif"]["flags"]; flags21[row.pair_id] = fl
        m.at[i, "products_v2_1_flags"] = ";".join(fl)
        if row.pair_id in ("ccz_so268_1", "discol_so242_1", "tag_m127"):
            m.at[i, "ship_products_usable"] = False; m.at[i, "ship_products_usable_reason"] = "registration_shift_unresolved (rulings R4)"
            m.at[i, "ruling_source"] = (m.at[i, "ruling_source"] + "; " if m.at[i, "ruling_source"] else "") + "rulings_ACQ-R03 R4"
        elif fl:
            m.at[i, "ship_products_usable"] = False; m.at[i, "ship_products_usable_reason"] = f"flagged: {';'.join(fl)} (contract v2.1 §6, no sign-off)"
        else:
            m.at[i, "ship_products_usable"] = True; m.at[i, "ship_products_usable_reason"] = "available, no v2.1 flags"
    # R5 (applied when the records exist)
    r5_46 = R.REPORT_DIR / "harmonize" / "2009_Amundsen__MGDS_30046_lrv2_1_r5.json"; r5_47 = R.REPORT_DIR / "harmonize" / "2009_Amundsen__MGDS_30047_r5.json"
    r5_status = "pending"
    if r5_46.exists() and r5_47.exists():
        a46 = json.loads(r5_46.read_text()); a47 = json.loads(r5_47.read_text()); r5_status = "applied"
        i = m.index[m.pair_id == "2009_Amundsen__MGDS_30046"][0]
        rel = a46["out_dir"].replace(str(C.OAK) + "/", "")
        m.at[i, "harmonized_path"] = rel; m.at[i, "harmonized_path_lr"] = rel + "/lr.tif"; m.at[i, "harmonized_path_hr"] = rel + "/hr.tif"
        m.at[i, "hr_valid"] = rel + "/hr_valid.tif"; m.at[i, "lr_valid"] = rel + "/lr_valid.tif"; m.at[i, "joint_valid"] = rel + "/joint_valid.tif"
        m.at[i, "lr_native_res_m"] = a46["lr_native"]["lr_native_m"]; m.at[i, "res_ratio"] = round(a46["lr_native"]["lr_native_m"] / float(m.at[i, "hr_native_res_m"]), 2)
        m.at[i, "horiz_offset_m"] = a46["coreg"]["offset_m"]; m.at[i, "vert_offset_m"] = a46["coreg"]["dz_m"]
        m.at[i, "coreg_status"] = f"R5 re-coreg on lr_v2_1: offset={a46['coreg']['offset_m']} m MAD={a46['coreg']['post_residual_mad_m']} m; {'pass' if a46['coreg']['pass'] else 'FAIL'}"
        m.at[i, "max_recoverable_k"] = a46["k_sweep"].get("max_recoverable_k"); m.at[i, "k_sweep_status"] = a46["k_sweep"].get("status")
        m.at[i, "qa_status"] = "pass" if a46["qa_pass"] else "fail"
        pv = a46.get("products_v2_1") or {}; fl = (pv.get("qa") or {}).get("flags", []); m.at[i, "products_v2_1_flags"] = ";".join(fl)
        m.at[i, "ship_products_usable"] = bool(pv and not fl); m.at[i, "ship_products_usable_reason"] = "available, no v2.1 flags (lrv2_1)" if (pv and not fl) else f"flagged: {';'.join(fl)}"
        m.at[i, "notes"] = (str(m.at[i, "notes"] or "") + f" | R5: LR regridded at the stage-C cell for its own HR depth ({a46['own_hr_median_depth_m']} m -> {a46['grid']['cell_m']} m); harmonized_lr = lr_v2_1 (lrv2_1/lr.tif); June lr.tif unmodified; lr_native {a46['lr_native']['lr_native_m']} m (was 16.0)").strip(" |")
        m.at[i, "ruling_source"] = (m.at[i, "ruling_source"] + "; " if m.at[i, "ruling_source"] else "") + "rulings_ACQ-R03 R5"
        j = m.index[m.pair_id == "2009_Amundsen__MGDS_30047"][0]
        m.at[j, "lr_native_res_m"] = a47["lr_native"]["lr_native_m"]; m.at[j, "res_ratio"] = round(a47["lr_native"]["lr_native_m"] / float(m.at[j, "hr_native_res_m"]), 2)
        m.at[j, "max_recoverable_k"] = a47["k_sweep"].get("max_recoverable_k"); m.at[j, "k_sweep_status"] = a47["k_sweep"].get("status")
        m.at[j, "notes"] = (str(m.at[j, "notes"] or "") + f" | R5: lr_native {a47['lr_native']['lr_native_m']} m under the unified depth definition (own-HR median {a47['own_hr_median_depth_m']} m; was 4.87 m at the harmonized-LR median)").strip(" |")
        m.at[j, "ruling_source"] = (m.at[j, "ruling_source"] + "; " if m.at[j, "ruling_source"] else "") + "rulings_ACQ-R03 R5"
    # June k values (for the unit table; manifest rows of June pairs carry none)
    c2c = json.loads((C.REPO / "reports/discovery/stage_c2c_sweep.json").read_text())
    kmap = {p["pair_id"]: p for p in (c2c.get("pairs") or c2c.get("results") or []) if isinstance(p, dict) and "pair_id" in p}
    for i, row in m.iterrows():
        if "R5" in str(m.at[i, "ruling_source"]):
            continue                                     # R5 pairs carry the re-swept k (None = no-k), never the June value
        if (row.get("max_recoverable_k") is None or (isinstance(row.get("max_recoverable_k"), float) and np.isnan(row.get("max_recoverable_k")))) and row.pair_id in kmap and str(row.designation).startswith("development"):
            m.at[i, "max_recoverable_k"] = kmap[row.pair_id].get("max_recoverable_k"); m.at[i, "k_sweep_status"] = kmap[row.pair_id].get("status")
    for pid, why in C.STOPPED_NO_K.items():
        i = m.index[m.pair_id == pid]
        if len(i):
            m.at[i[0], "k_sweep_status"] = (m.at[i[0], "k_sweep_status"] or "") + " (June no-k stop)"
    m["ruling_source"] = m["ruling_source"].map(lambda v: "; ".join(dict.fromkeys([x for x in str(v).split("; ") if x])) if v else "")
    m["manifest_version"] = "2.1"
    out = C.REPO / "manifest" / "pairs_v2_1.parquet"; m.to_parquet(out, index=False)
    dall = pd.concat([dropped.assign(ruling_source=""), pd.DataFrame(dropped_new)], ignore_index=True, sort=False)
    pdrop = C.REPO / "manifest" / "pairs_v2_1_dropped.csv"; dall.to_csv(pdrop, index=False)
    summ = {"date": date.today().isoformat(), "rows": int(len(m)), "by_designation": m.designation.value_counts().to_dict(), "r5": r5_status,
            "dropped_rows": int(len(dall)), "dropped_new": [d["pair_id"] for d in dropped_new], "reinstated_R6": ["KN182L03__MGDS_30193", "SUM1004__MGDS_33090"],
            "ship_products_usable": m.ship_products_usable.value_counts(dropna=False).astype(int).to_dict(), "flags_v2_1": flags21,
            "path": str(out), "sha256": C.sha256_file(out), "dropped_path": str(pdrop), "dropped_sha256": C.sha256_file(pdrop)}
    R.write_json(R.REPORT_DIR / "manifest_v2_1_summary.json", summ)
    print(json.dumps({k: v for k, v in summ.items() if k != "flags_v2_1"}, indent=1, default=str)); return 0


if __name__ == "__main__":
    sys.exit(main())
