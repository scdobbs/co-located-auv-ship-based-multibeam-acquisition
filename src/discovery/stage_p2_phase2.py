"""Phase 2 — durability: leakage columns + persist harmonized data to OAK.

After V0 sign-off and P2-PRE-1/2/3. This is the project's largest OAK write, so
EVERY OAK write is bracketed by the P2-PRE-1 anchor check and a before/after
checksum diff of the 21 validated grids (which must remain byte-identical).

Steps:
  1. anchor BEFORE — assert_validated_anchor(canon) + assert_validated_anchor(OAK
     manifest) + assert_validated_grids(OAK harmonized) + snapshot 21 validated
     grid sha256.
  2. add `leakage_unit` / `geo_cluster` columns from leakage_assignment.csv.
  3. rewrite path columns to root-relative (OAK-resolving) form.
  4. backup canonical (dated) + assert_validated_anchor(new df) + write canonical.
  5. persist the 18 NEW pairs' grids + masks + footprint + QC to OAK, byte-verify
     each, chmod 0444. The 21 validated grids are already on OAK and are NOT
     rewritten (verified intact by the grid anchor).
  6. persist valid_tiles.parquet + leakage tables to OAK.
  7. resync canonical manifest to OAK (unlock/copy/verify/relock 0444).
  8. anchor AFTER — re-assert manifest + grid anchors on OAK; diff the 21
     validated grid sha256 (must be unchanged); verify new-pair checksums match
     the manifest.

Run as a Slurm job (copies ~2 GB + checksums). NOT on the login node.
"""
from __future__ import annotations
import hashlib, json, logging, os, shutil, stat
from pathlib import Path
import pandas as pd

from src.discovery.validated_anchor import (
    assert_validated_anchor, assert_validated_grids, compute_validated_grid_sha256,
    VALIDATED_PAIR_IDS, is_new)

log = logging.getLogger("p2")
REPO = Path(__file__).resolve().parents[2]
DATE = "2026-06-26"
CANON = REPO / "manifest/pairs.parquet"
LEAK_CSV = REPO / "reports/discovery/leakage_assignment.csv"
LEAK_UNITS = REPO / "reports/discovery/leakage_units_canonical.csv"
VALID_TILES = REPO / "reports/discovery/valid_tiles.parquet"
GRID_SHA_REF = REPO / "manifest/validated_grid_sha256.json"
RESULT = REPO / "reports/discovery/stage_p2_phase2_result.json"

DATA_ROOT = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
SCR_HARM = DATA_ROOT / "harmonized"
OAKROOT = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy")
OAK_HARM = OAKROOT / "harmonized"
OAK_MANI = OAKROOT / "manifest" / "pairs.parquet"
OAK_VALID_TILES = OAKROOT / "manifest" / "valid_tiles.parquet"
OAK_LEAK_CSV = OAKROOT / "manifest" / "leakage_assignment.csv"
OAK_LEAK_UNITS = OAKROOT / "manifest" / "leakage_units_canonical.csv"

# deliverables to persist per new pair; exclude scratch working intermediates
GRID_FILES = ["hr.tif", "lr.tif", "footprint.geojson",
              "hr_valid.tif", "lr_valid.tif", "joint_valid.tif"]
EXCLUDE = ("hr_preF5repair.tif", "hr_preSupersede.tif")
RO = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
RW = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def scr_pair_dir(pid):
    if pid.startswith("cal_dig_morro_bay__"):
        return SCR_HARM / "cal_dig_morro_bay" / pid.split("__", 1)[1]
    return SCR_HARM / pid


def oak_pair_dir(pid):
    if pid.startswith("cal_dig_morro_bay__"):
        return OAK_HARM / "cal_dig_morro_bay" / pid.split("__", 1)[1]
    return OAK_HARM / pid


def root_relative(p):
    """Strip the data_root prefix -> OAK-resolving root-relative path string."""
    if p is None or (isinstance(p, float)) or str(p) in ("", "nan", "None"):
        return p
    s = str(p)
    for root in (str(DATA_ROOT), str(OAKROOT)):
        if s.startswith(root + "/"):
            return s[len(root) + 1:]
    return s  # already relative or outside data_root (leave + flag)


def copy_verify_ro(src, dst):
    """Copy src->dst, byte-verify by sha256, chmod 0444. Idempotent."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if sha256(src) == sha256(dst):
            os.chmod(dst, RO)
            return "exists_ok"
        os.chmod(dst, RW)  # differs -> unlock to overwrite
    shutil.copy2(src, dst)
    ok = sha256(src) == sha256(dst)
    if not ok:
        raise RuntimeError(f"byte-verify FAILED {src} -> {dst}")
    os.chmod(dst, RO)
    return "copied"


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = {"date": DATE, "ok": False, "oak_writes": []}

    # ---------- 1. ANCHOR BEFORE ----------
    canon = pd.read_parquet(CANON)
    assert_validated_anchor(canon)
    grid_ref = json.loads(GRID_SHA_REF.read_text())
    assert_validated_grids(OAK_HARM, grid_ref)          # OAK validated grids intact
    if OAK_MANI.exists():
        assert_validated_anchor(pd.read_parquet(OAK_MANI))
    before_validated_sha = compute_validated_grid_sha256(OAK_HARM)
    log.info("ANCHOR BEFORE: manifest+OAK-manifest pass; %d validated grids snapshot",
             len(before_validated_sha))
    res["anchor_before"] = "PASS"

    # ---------- 2. leakage columns ----------
    leak = pd.read_csv(LEAK_CSV).set_index("pair_id")
    miss = set(canon.pair_id) - set(leak.index)
    assert not miss, f"leakage assignment missing pairs: {sorted(miss)[:5]}"
    canon["geo_cluster"] = canon.pair_id.map(leak["geo_cluster"])
    canon["leakage_unit"] = canon.pair_id.map(leak["leakage_unit"])
    assert canon["leakage_unit"].notna().all(), "null leakage_unit after map"
    res["n_leakage_units"] = int(canon["leakage_unit"].nunique())
    res["n_geo_clusters"] = int(canon["geo_cluster"].nunique())

    # ---------- 3. root-relative (OAK-resolving) path columns ----------
    PATHCOLS = ["raw_path_hr", "raw_path_lr", "harmonized_path_hr",
                "harmonized_path_lr", "qc_artifact_path", "hr_local_path"]
    path_examples = {}
    for c in PATHCOLS:
        if c in canon.columns:
            before = canon[c].copy()
            canon[c] = canon[c].map(root_relative)
            ex = canon[c].dropna()
            path_examples[c] = ex.iloc[0] if len(ex) else None
            # flag any value that did not become relative (still absolute)
            stillabs = [v for v in canon[c].dropna() if str(v).startswith("/")]
            if stillabs:
                log.warning("col %s has %d still-absolute values e.g. %s", c, len(stillabs), stillabs[0])
    res["path_examples"] = path_examples
    res["path_resolution_root"] = (
        f"OAK-resolving: resolve against $OAK/auv_ship_colocated_bathy (persistent, "
        f"Phase-2 canonical) for harmonized+qc; raw currently only under "
        f"$SCRATCH/auv_ship_colocated_bathy pending Gate-1.")

    # ---------- 4. backup + anchor + write canonical ----------
    assert_validated_anchor(canon)   # after column edits, before write
    bk = REPO / f"manifest/pairs.parquet.bak_{DATE}_phase2"
    if not bk.exists():
        shutil.copy2(CANON, bk)
    canon.to_parquet(CANON, index=False)
    assert_validated_anchor(pd.read_parquet(CANON))  # readback
    log.info("canonical written: +geo_cluster/+leakage_unit, paths root-relative; anchor OK")
    res["canonical_written"] = True

    # ---------- 5. persist NEW pairs' grids/masks/QC to OAK ----------
    new_ids = [p for p in canon.pair_id if is_new(p)]
    persisted = []
    for pid in new_ids:
        src = scr_pair_dir(pid); dst = oak_pair_dir(pid)
        if not src.exists():
            raise RuntimeError(f"scratch pair dir missing: {src}")
        files_done = {}
        for fn in GRID_FILES:
            sp = src / fn
            if sp.exists():
                files_done[fn] = copy_verify_ro(sp, dst / fn)
        # QC pngs
        qsrc = src / "qc"
        nqc = 0
        if qsrc.exists():
            for qp in sorted(qsrc.glob("*.png")):
                copy_verify_ro(qp, dst / "qc" / qp.name); nqc += 1
        persisted.append({"pair_id": pid, "files": files_done, "qc_pngs": nqc})
        log.info("OAK persist %-30s grids=%d qc=%d", pid, len(files_done), nqc)
    res["oak_writes"].append({"op": "new_pair_grids", "n_pairs": len(persisted)})
    res["persisted"] = persisted

    # validated grids unchanged mid-run (we never touched them)
    assert_validated_grids(OAK_HARM, grid_ref)

    # ---------- 6. valid_tiles + leakage tables to OAK ----------
    copy_verify_ro(VALID_TILES, OAK_VALID_TILES)
    copy_verify_ro(LEAK_CSV, OAK_LEAK_CSV)
    copy_verify_ro(LEAK_UNITS, OAK_LEAK_UNITS)
    res["oak_writes"].append({"op": "valid_tiles+leakage", "valid_tiles": str(OAK_VALID_TILES)})
    log.info("OAK persist valid_tiles + leakage tables")

    # ---------- 7. resync canonical manifest to OAK ----------
    if OAK_MANI.exists():
        os.chmod(OAK_MANI, RW)
    shutil.copy2(CANON, OAK_MANI)
    man_ok = sha256(CANON) == sha256(OAK_MANI)
    os.chmod(OAK_MANI, RO)
    res["oak_manifest_resync"] = {"byte_identical": bool(man_ok)}
    assert man_ok, "OAK manifest resync byte-verify failed"
    log.info("OAK manifest resync byte_identical=%s (0444)", man_ok)

    # ---------- 8. ANCHOR AFTER ----------
    assert_validated_anchor(pd.read_parquet(OAK_MANI))
    assert_validated_grids(OAK_HARM, grid_ref)
    after_validated_sha = compute_validated_grid_sha256(OAK_HARM)
    drift = [k for k in before_validated_sha
             if before_validated_sha[k] != after_validated_sha.get(k)]
    assert not drift, f"validated grid sha drift during Phase 2: {drift[:5]}"
    res["anchor_after"] = "PASS"
    res["validated_grids_unchanged"] = (len(before_validated_sha), len(drift))
    log.info("ANCHOR AFTER: manifest+grids pass; validated grid drift=%d", len(drift))

    # ---------- new-pair checksum cross-check vs manifest ----------
    m = pd.read_parquet(OAK_MANI)
    chk_bad = []
    for pid in new_ids:
        dst = oak_pair_dir(pid)
        row = m[m.pair_id == pid].iloc[0]
        for side in ("hr", "lr"):
            f = dst / f"{side}.tif"
            exp = row[f"checksum_{side}"]
            if not isinstance(exp, str) or len(exp) < 32:
                continue  # no manifest checksum to compare against
            if f.exists() and sha256(f) != exp:
                chk_bad.append(f"{pid}/{side}")
    res["new_pair_checksum_mismatches"] = chk_bad
    assert not chk_bad, f"new-pair OAK grid checksum != manifest: {chk_bad[:5]}"
    log.info("new-pair OAK grid checksums match manifest (%d pairs)", len(new_ids))

    res["ok"] = True
    RESULT.write_text(json.dumps(res, indent=2, default=str))
    log.info("=== PHASE 2 COMPLETE: %d new pairs to OAK; manifest +2 cols, paths "
             "root-relative; validated anchor intact ===", len(new_ids))


if __name__ == "__main__":
    main()
