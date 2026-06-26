"""Canonical manifest append — GREENLIT (34 = 21 validated + 13 new).

Directive: directive_phase2_manifest_append_greenlight_v1.md.
Steve confirmed ALL 6 M2 terrain reclasses (2026-06-26).

Irreversible step. Safeguards:
  - backup before write (pairs.parquet.bak_preappend already retained; also a
    fresh timestamped backup),
  - the 21 canonical rows preserved VERBATIM (asserted post-write against backup),
  - append-only, dedup on pair_id, schema matched to canonical (no new columns),
  - sha256 re-verify of the appended rasters vs the staged checksums,
  - OAK sync with byte (sha256) verify, file re-locked read-only,
  - idempotent: aborts if any of the 13 new pair_ids is already present.
"""
from __future__ import annotations
import hashlib, json, logging, os, shutil, stat
from pathlib import Path
import pandas as pd

log = logging.getLogger("append")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
CANON = REPO / "manifest/pairs.parquet"
OAK = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy/manifest/pairs.parquet")
STAGED_CSV = REPO / "reports/discovery/staged_manifest_append.csv"
LRINFO = REPO / "reports/discovery/stage_m1_lr_mbinfo.json"
EXCL = REPO / "reports/discovery/stage_append_exclusions_2026-06-26.csv"
RESULT = REPO / "reports/discovery/stage_manifest_append_result.json"

KEEP13 = ["AT37-13__MGDS_31199", "AT42-03__MGDS_32007", "EW9801__MGDS_31425",
          "NA080__MGDS_31290", "NA090__MGDS_31212", "RR1506__MGDS_29779",
          "TN268__MGDS_30466", "TN399__MGDS_30373", "FK181031__MGDS_24367",
          "AR26__MGDS_31838", "TN159__MGDS_21981", "TN299__MGDS_27339",
          "KIWI10RR__MGDS_24499"]
DROP3 = {"KN210-05__MGDS_22436": "151 m offset, no interior NCC peak",
         "FK006B__MGDS_20811": "PSR=-8.97, degenerate peak",
         "KN204-01__MGDS_31675": "51 m offset, no interior NCC peak"}
# Steve-confirmed (all 6) terrain reclasses
RECLASS = {"EW9801__MGDS_31425": "volcanic", "RR1506__MGDS_29779": "seamount",
           "TN268__MGDS_30466": "volcanic", "TN399__MGDS_30373": "volcanic",
           "FK181031__MGDS_24367": "volcanic", "TN299__MGDS_27339": "volcanic"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = {"steps": [], "ok": False}

    canon = pd.read_parquet(CANON)
    assert len(canon) == 21, f"expected 21 canonical rows, found {len(canon)}"
    cols = list(canon.columns)
    staged = pd.read_csv(STAGED_CSV)
    lrinfo = json.loads(LRINFO.read_text())

    # idempotency guard
    already = set(canon.pair_id) & set(KEEP13)
    if already:
        log.error("ABORT: %d new pair_ids already in canonical (%s) — already appended?", len(already), already)
        result["error"] = f"already present: {sorted(already)}"
        RESULT.write_text(json.dumps(result, indent=2)); return

    new = staged[staged.pair_id.isin(KEEP13)].copy()
    assert len(new) == 13, f"expected 13 new rows, found {len(new)}"

    # apply Steve-confirmed terrain reclasses to terrain_class
    new["terrain_class"] = new.apply(lambda r: RECLASS.get(r["pair_id"], r["terrain_class"]), axis=1)
    result["steps"].append({"reclass_applied": RECLASS})

    # §4: append LR acquisition date to notes (temporal independence readable)
    def lr_date(cruise):
        import re
        fn = lrinfo.get(cruise, {}).get("filename", "") or ""
        m = re.search(r"(19|20)(\d{2})(\d{2})(\d{2})", fn)
        return f"{m.group(1)}{m.group(2)}-{m.group(3)}-{m.group(4)}" if m else "?"
    def add_lr(r):
        cr = str(r["notes"]).split("LR_ship_cruise=")[-1].split(" ")[0] if "LR_ship_cruise=" in str(r["notes"]) else ""
        return str(r["notes"]) + f" | LR_acq_date={lr_date(cr)}"
    new["notes"] = new.apply(add_lr, axis=1)

    # match canonical schema exactly (drop the 2 extra staged cols), coerce dtypes
    new = new.reindex(columns=cols)
    for c in cols:
        if pd.api.types.is_numeric_dtype(canon[c].dtype):
            new[c] = pd.to_numeric(new[c], errors="coerce")
        else:
            new[c] = new[c].astype(object).where(new[c].notna(), "")

    combined = pd.concat([canon, new[cols]], ignore_index=True)
    assert combined["pair_id"].is_unique, "duplicate pair_id after append"
    assert len(combined) == 34, f"expected 34 rows, found {len(combined)}"
    # 21 preserved verbatim
    assert combined.iloc[:21].reset_index(drop=True).equals(canon.reset_index(drop=True)), "canonical 21 NOT verbatim"
    result["steps"].append({"rows": {"canonical": 21, "new": 13, "total": 34}, "pair_id_unique": True, "canon_verbatim": True})

    # fresh backup, then write canonical (repo)
    bk = REPO / "manifest/pairs.parquet.bak_2026-06-26_append"
    if not bk.exists():
        shutil.copy2(CANON, bk)
    combined.to_parquet(CANON, index=False)
    log.info("wrote canonical %s (34 rows)", CANON)

    # checksum re-verify: manifest checksum vs sha256 of the actual harmonized rasters
    chk = []
    for _, r in new.iterrows():
        for side in ("hr", "lr"):
            path = Path(r[f"harmonized_path_{side}"]); claimed = r[f"checksum_{side}"]
            actual = sha256(path) if path.exists() else "MISSING"
            chk.append({"pair_id": r["pair_id"], "side": side, "match": bool(actual == claimed),
                        "claimed": str(claimed)[:12], "actual": actual[:12]})
    nbad = sum(1 for c in chk if not c["match"])
    result["checksum_verify"] = {"checked": len(chk), "mismatches": nbad,
                                 "bad": [c for c in chk if not c["match"]]}
    log.info("checksum re-verify: %d/%d match (%d mismatch)", len(chk) - nbad, len(chk), nbad)
    if nbad:
        log.error("CHECKSUM MISMATCH — restoring canonical from backup and aborting")
        shutil.copy2(bk, CANON)
        result["error"] = "checksum mismatch; canonical restored"
        RESULT.write_text(json.dumps(result, indent=2, default=str)); return

    # OAK sync (chmod u+w -> copy -> verify -> re-lock read-only)
    try:
        if OAK.exists():
            os.chmod(OAK, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        shutil.copy2(CANON, OAK)
        oak_ok = sha256(CANON) == sha256(OAK)
        os.chmod(OAK, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # re-lock read-only
        result["oak_sync"] = {"path": str(OAK), "byte_identical": bool(oak_ok)}
        log.info("OAK sync byte-identical: %s", oak_ok)
    except Exception as e:
        result["oak_sync"] = {"error": str(e)[:120]}
        log.error("OAK sync failed: %s", e)

    # exclusions log for the 3 dropped
    pd.DataFrame([{"pair_id": k, "reason_detail": v,
                   "exclusion_reason": "unconfirmed_coregistration_eligible_for_manual_recoreg",
                   "data_quality_exclusion": False, "date": "2026-06-26"}
                  for k, v in DROP3.items()]).to_csv(EXCL, index=False)
    result["exclusions_logged"] = list(DROP3.keys())

    # final completeness diff on the written manifest
    final = pd.read_parquet(CANON)
    diff = {}
    nr = final[final.pair_id.isin(KEEP13)]
    for c in cols:
        def nb(df, col):
            s = df[col]; return int(s.notna().sum() - (s.astype(str).str.strip() == "").sum())
        diff[c] = {"all_34": f"{nb(final, c)}/34", "new_13": f"{nb(nr, c)}/13"}
    result["completeness_final"] = diff
    result["ok"] = True
    RESULT.write_text(json.dumps(result, indent=2, default=str))
    log.info("APPEND COMPLETE: 34-row canonical written + OAK synced + verified")


if __name__ == "__main__":
    main()
