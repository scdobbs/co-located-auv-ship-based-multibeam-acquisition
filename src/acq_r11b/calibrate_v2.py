"""ACQ-R11b §2 — calibration v2: datum threshold T_G, line-check computability, fallback decision.

G (datum check) = V95_rel of src/acq_r11/vcheck.py (sha256 5a2c65d4…, unchanged); its values are read from the ACQ-R11
table (hash-checked), not recomputed.  T_G = 3 x max(V95_rel over the 45 development-designated rows, accepted and info).
L (line check, §1.2) needs, per pair, the LR grid's own mbgrid cell, region and origin (to grid each swath file alone on
the same lattice) and the raw swath on disk.  A pair is "computable" only if its lr.tif was made from a grid whose mbgrid
command (-R, -E) is recorded and whose grid file is on OAK, and its cruise's raw swath is on OAK.  Fallback (§0.2, §2.3):
if fewer than 10 accepted pairs are computable, L is not computed and the datum check is implemented alone.
Usage: python -B -m src.acq_r11b.calibrate_v2
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RPG = REPO / "reports_post_grl_review"
OAK = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy")
R11_TABLE = RPG / "ACQ-R11" / "vcheck_calibration.csv"
R11_TABLE_SHA = "b7f3732d9830d24911de0f17380082fc887a5f02bba20767090a65e34898c711"
VCHECK = REPO / "src" / "acq_r11" / "vcheck.py"
VCHECK_SHA = "5a2c65d4e50286945dc04eb66b4f8f965beee93c65a9967c15da017fdaf52a44"
OUT = RPG / "ACQ-R11b"
PROVIDER = ("cal_dig_morro_bay__", "ccz_so268_1", "discol_so242_1", "tag_m127")
# pairs whose lr.tif grid has a recorded mbgrid command and a grid file on OAK
RECORDED = {"FK151121__MGDS_22383": (RPG / "ACQ-R02/grid/FK151121.json", OAK / "raw_lr_gridded/FK151121__union.grd"),
            "2009_Amundsen__MGDS_30046": (RPG / "ACQ-R03/grid/2009_Amundsen__MGDS_30046_lrv2_1_r5.json", OAK / "raw_lr_gridded/2009_Amundsen__MGDS_30046__lrv2_1.grd")}
MIN_COMPUTABLE = 10


def sha(p) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def l_status(pid: str) -> tuple:
    cr = pid.split("__")[0]
    if pid.startswith(PROVIDER):
        return "not computable", "LR is a provider grid / compilation (no per-file raw swath gridding)"
    if pid in RECORDED:
        rec, grd = RECORDED[pid]
        ok = rec.exists() and grd.exists() and "-R" in json.loads(rec.read_text()).get("mbgrid_command", "") and (OAK / "raw_lr_swath" / cr).is_dir()
        return ("computable", f"mbgrid command in {rec.relative_to(REPO)}; grid {grd.name} on OAK; swath on OAK") if ok else ("not computable", "record, grid or swath missing")
    why = "LR grid made in June (src/discovery/stage_c_full or C1 reharvest); its union grid is not on disk and its -R/-E are not recorded, so a per-file grid on the same lattice cannot be made"
    if not (OAK / "raw_lr_swath" / cr).is_dir():
        why += "; raw swath not on OAK"
    return "not computable", why


def main():
    if sha(R11_TABLE) != R11_TABLE_SHA or sha(VCHECK) != VCHECK_SHA:
        raise SystemExit("ACQ-R11 table or vcheck.py changed")
    rows = list(csv.DictReader(open(R11_TABLE, newline="")))
    dev = [r for r in rows if r["set"] in ("accepted", "info")]
    g_max = max(float(r["V95_rel"]) for r in dev)
    T_G = 3.0 * g_max
    out = []
    for r in rows:
        g = float(r["V95_rel"]) if r["V95_rel"] else None
        ls, lwhy = l_status(r["pair_id"]) if r["set"] == "accepted" else (("not computed", "fallback") if r["status"] == "ok" else ("not computed", "no files"))
        out.append({"pair_id": r["pair_id"], "set": r["set"], "G_V95_rel": r["V95_rel"], "V95_m": r["V95_m"], "median_lr_depth_m": r["median_lr_depth_m"],
                    "G_below_T_G": (g < T_G) if g is not None else None, "L_status": ls, "L_note": lwhy, "L": "", "n_files_kept": ""})
    n_comp = sum(1 for x in out if x["set"] == "accepted" and x["L_status"] == "computable")
    fallback = n_comp < MIN_COMPUTABLE
    if fallback:
        for x in out:
            if x["L_status"] == "computable":
                x["L_status"], x["L_note"] = "computable, not computed", "fallback (§2.3: fewer than 10 accepted pairs computable)"
    nr = [x for x in out if x["pair_id"].startswith("NR07-1__")]
    checks = {"NR07-1_above_T_G": all(x["G_V95_rel"] and float(x["G_V95_rel"]) > T_G for x in nr) and len(nr) == 2,
              "all_45_development_below_T_G": all(x["G_below_T_G"] for x in out if x["set"] in ("accepted", "info")) and len(dev) == 45,
              "AT37-05_above_T_G": [float(x["G_V95_rel"]) > T_G for x in out if x["pair_id"].startswith("AT37-05")][0]}
    OUT.mkdir(parents=True, exist_ok=True)
    tab = OUT / "vcheck_calibration_v2.csv"
    with open(tab, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    rec = {"directive": "ACQ-R11b §2", "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "G_source": {"table": str(R11_TABLE.relative_to(REPO)), "sha256": R11_TABLE_SHA, "statistic": str(VCHECK.relative_to(REPO)), "statistic_sha256": VCHECK_SHA},
           "T_G_rule": "3 x max(V95_rel over the 45 development-designated rows, accepted and info)", "G_max_development": g_max,
           "G_max_development_pair": [x["pair_id"] for x in out if x["set"] in ("accepted", "info") and float(x["G_V95_rel"]) == g_max][0],
           "T_G": T_G, "checks": checks,
           "T_L_rule": "2 x max(L over the accepted pairs where L is computable)", "n_accepted_L_computable": n_comp, "min_computable_required": MIN_COMPUTABLE,
           "fallback_applied": fallback, "T_L": None,
           "fallback_basis": "§2.3: fewer than 10 accepted pairs have a computable L -> §0.2 fallback (Steve, approved in advance): datum check only; ship line-to-line inconsistency unchecked for v3.1",
           "table": str(tab.relative_to(REPO)), "table_sha256": sha(tab)}
    (OUT / "vcheck_calibration_v2.json").write_text(json.dumps(rec, indent=1))
    print(json.dumps(rec, indent=1))
    return 0 if (checks["NR07-1_above_T_G"] and checks["all_45_development_below_T_G"]) else 5


if __name__ == "__main__":
    sys.exit(main())
