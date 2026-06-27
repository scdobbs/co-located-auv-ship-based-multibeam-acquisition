"""Phase 2 L-FIX apply — write recomputed leakage columns + lr_cruise + minors.

Targeted manifest-column fix (grids/paths NOT touched, not re-persisted):
  - add `lr_cruise` (first-class LR ship cruise axis),
  - overwrite `geo_cluster` / `leakage_unit` from the corrected assignment,
  - record the leakage policy in notes of the affected NEW merged pairs,
  - minor: FK181031__MGDS_24367 lr_platform "R/V FK181031_EM302" -> "R/V Falkor".

Guards: assert_validated_anchor before/after (canonical + OAK); the 21 validated
rows must be byte-identical EXCEPT the leakage columns (geo_cluster/leakage_unit
/lr_cruise); validated grid sha256 unchanged (grids untouched). Resync manifest
+ leakage tables to OAK read-only. Run as a Slurm job.
"""
from __future__ import annotations
import hashlib, json, logging, os, shutil, stat
from pathlib import Path
import pandas as pd
import pandas.testing as pdt

from src.discovery.validated_anchor import (
    assert_validated_anchor, assert_validated_grids, VALIDATED_PAIR_IDS, is_new)

log = logging.getLogger("p2leakapply")
REPO = Path(__file__).resolve().parents[2]
DATE = "2026-06-26"
CANON = REPO / "manifest/pairs.parquet"
ASSIGN = REPO / "reports/discovery/leakage_assignment.csv"
LEAK_UNITS = REPO / "reports/discovery/leakage_units_canonical.csv"
GRID_SHA_REF = REPO / "manifest/validated_grid_sha256.json"
RESULT = REPO / "reports/discovery/stage_p2_leakage_apply_result.json"
LEAK_COLS = ["geo_cluster", "leakage_unit", "lr_cruise"]

OAKROOT = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy")
OAK_HARM = OAKROOT / "harmonized"
OAK_MANI = OAKROOT / "manifest" / "pairs.parquet"
OAK_ASSIGN = OAKROOT / "manifest" / "leakage_assignment.csv"
OAK_UNITS = OAKROOT / "manifest" / "leakage_units_canonical.csv"
RO = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
RW = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH

POLICY_NOTE = ("leakage_policy=conservative (shared HR survey cruise_id OR shared "
               "LR ship cruise lr_cruise OR centroid<=50km => one unit, any distance)")
PLATFORM_FIX = {"FK181031__MGDS_24367": ("lr_platform", "R/V FK181031_EM302", "R/V Falkor")}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def copy_ro(src, dst):
    if dst.exists():
        os.chmod(dst, RW)
    shutil.copy2(src, dst)
    ok = sha256(src) == sha256(dst)
    os.chmod(dst, RO)
    if not ok:
        raise RuntimeError(f"byte-verify failed {src}->{dst}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = {"date": DATE, "ok": False, "policy": "conservative"}

    # ---- anchor BEFORE ----
    canon = pd.read_parquet(CANON)
    assert_validated_anchor(canon)
    grid_ref = json.loads(GRID_SHA_REF.read_text())
    assert_validated_grids(OAK_HARM, grid_ref)
    if OAK_MANI.exists():
        assert_validated_anchor(pd.read_parquet(OAK_MANI))
    log.info("ANCHOR BEFORE: PASS")

    # snapshot validated rows on the non-leakage columns (must stay identical)
    val_ids = sorted(VALIDATED_PAIR_IDS)
    keep_cols = [c for c in canon.columns if c not in LEAK_COLS]
    before_val = (canon[canon.pair_id.isin(val_ids)].sort_values("pair_id")
                  .reset_index(drop=True)[keep_cols].copy())

    # ---- assignment ----
    a = pd.read_csv(ASSIGN).set_index("pair_id")
    miss = set(canon.pair_id) - set(a.index)
    assert not miss, f"assignment missing: {sorted(miss)[:5]}"
    assert a["leakage_unit"].nunique() == 19, f"expected 19 leakage_units, got {a['leakage_unit'].nunique()}"

    canon["lr_cruise"] = canon.pair_id.map(a["lr_cruise"])
    canon["geo_cluster"] = canon.pair_id.map(a["geo_cluster"])
    canon["leakage_unit"] = canon.pair_id.map(a["leakage_unit"])
    assert canon[["lr_cruise", "geo_cluster", "leakage_unit"]].notna().all().all()
    res["n_leakage_units"] = int(canon.leakage_unit.nunique())
    res["n_geo_clusters"] = int(canon.geo_cluster.nunique())

    # ---- policy note on NEW members of multi-pair units (never touch validated) ----
    unit_sz = canon.groupby("leakage_unit").pair_id.transform("count")
    merged_new = canon[(unit_sz > 1) & canon.pair_id.map(is_new)].pair_id.tolist()
    for pid in merged_new:
        i = canon.index[canon.pair_id == pid][0]
        cur = str(canon.at[i, "notes"] or "")
        if "leakage_policy=" not in cur:
            canon.at[i, "notes"] = (cur + " | " + POLICY_NOTE).strip(" |")
    res["policy_noted_pairs"] = merged_new

    # ---- minor: lr_platform fix ----
    fixes = []
    for pid, (col, old, new) in PLATFORM_FIX.items():
        i = canon.index[canon.pair_id == pid]
        if len(i):
            i = i[0]
            if str(canon.at[i, col]) == old:
                canon.at[i, col] = new
                fixes.append({"pair_id": pid, col: f"{old} -> {new}"})
    res["platform_fixes"] = fixes

    # ---- validated rows unchanged except leakage columns ----
    after_val = (canon[canon.pair_id.isin(val_ids)].sort_values("pair_id")
                 .reset_index(drop=True)[keep_cols].copy())
    pdt.assert_frame_equal(before_val, after_val, check_dtype=False)
    res["validated_unchanged_except_leakage"] = True
    log.info("validated 21 rows identical on all non-leakage columns")

    # ---- backup + anchor + write ----
    assert_validated_anchor(canon)
    bk = REPO / f"manifest/pairs.parquet.bak_{DATE}_leakfix"
    if not bk.exists():
        shutil.copy2(CANON, bk)
    canon.to_parquet(CANON, index=False)
    assert_validated_anchor(pd.read_parquet(CANON))
    log.info("canonical written: +lr_cruise, leakage recomputed (%d units), notes+platform fix",
             res["n_leakage_units"])

    # ---- resync to OAK (manifest + leakage tables) ----
    copy_ro(CANON, OAK_MANI)
    copy_ro(ASSIGN, OAK_ASSIGN)
    copy_ro(LEAK_UNITS, OAK_UNITS)
    res["oak_manifest_byte_identical"] = sha256(CANON) == sha256(OAK_MANI)
    assert res["oak_manifest_byte_identical"]

    # ---- anchor AFTER ----
    assert_validated_anchor(pd.read_parquet(OAK_MANI))
    assert_validated_grids(OAK_HARM, grid_ref)   # grids untouched
    res["anchor_after"] = "PASS"
    log.info("ANCHOR AFTER: PASS; OAK manifest+grids intact; grids not re-persisted")

    res["ok"] = True
    RESULT.write_text(json.dumps(res, indent=2, default=str))
    log.info("=== L-FIX APPLY COMPLETE: leakage_unit recomputed on correct axes "
             "(%d units), lr_cruise added, validated untouched ===", res["n_leakage_units"])


if __name__ == "__main__":
    main()
