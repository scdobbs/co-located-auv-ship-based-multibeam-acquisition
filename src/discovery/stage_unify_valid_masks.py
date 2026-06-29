"""Unify validity masks across the corpus — build hr_valid/lr_valid/joint_valid
for the 21 VALIDATED pairs so all 39 carry the same three masks.

Directive: reports/directive_unify_validity_masks_standalone_v2.md

STANDALONE, READ-ONLY generator (same spirit as stage_p2_qc_backfill.py):
read the EXISTING canonical hr.tif / lr.tif, derive masks, write NEW files.
It does NOT run stage_f5_valid_masks.py, does NOT re-coregister, and does NOT
modify hr.tif / lr.tif by a single byte (proven by a 42-grid sha256 snapshot
taken before and after, plus the validated-grid + manifest anchors).

Grid model (verified against the 18 new pairs, which are identical in shape):
  In THIS dataset hr.tif (fine, ~1-2 m) and lr.tif (coarse native, 10-80 m) are
  never the same shape — that is the whole point (coarse ship LR vs fine AUV HR).
  For BOTH new and validated pairs the three masks live on the HR grid; the new
  pairs' lr_valid is the LR coverage placed on the HR grid. We reproduce exactly
  that: same CRS (so NO reprojection / NO coreg shift — only a coverage upsample),
  hr.tif/lr.tif untouched. The §4 "grid-aligned" precondition is therefore
  hr.crs == lr.crs (so LR coverage can be placed on the HR grid) — asserted per
  pair; a CRS mismatch is escalated, not forced.

Mask definitions (directive §3, coverage_geotiff semantics for the 21):
  hr_valid    = real-data mask of HR: open masked=True honoring the file's OWN
                nodata tag (do not assume -9999); nodata / fill / NaN -> invalid.
  lr_valid    = isfinite(lr) expressed on the HR grid (nearest upsample of the
                LR coverage mask — never bilinear a mask).
  joint_valid = hr_valid & lr_valid, per pixel on the HR (shared) grid.

Two entrypoints:
  --generate (default): build masks on SCRATCH, snapshot the 42 grids before/after
      (0/42 drift required), update the repo manifest (mask path cols, checksums,
      lr_valid_semantic) guarded by the anchor, write a result JSON. Touches NO OAK.
  --persist-oak: HELD for Steve — copy the new masks into the validated pairs'
      OAK dirs, chmod 0444, byte-verify, snapshot OAK dir listings + grids + anchor
      before/after, resync the manifest read-only. Run ONLY on Steve's go.

Run on a compute node (sbatch) — never the login node.
"""
from __future__ import annotations
import argparse, hashlib, json, logging, os, shutil, stat
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import reproject, Resampling

from src.discovery.validated_anchor import (
    VALIDATED_PAIR_IDS, N_VALIDATED, is_validated, is_new,
    assert_validated_anchor, assert_validated_grids, compute_validated_grid_sha256)

log = logging.getLogger("unify_masks")
REPO = Path(__file__).resolve().parents[2]
CANON = REPO / "manifest/pairs.parquet"
GRID_SHA_REF = REPO / "manifest/validated_grid_sha256.json"
RESULT = REPO / "reports/discovery/stage_unify_valid_masks_result.json"
DATA_ROOT = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
SCR_HARM = DATA_ROOT / "harmonized"
REPO_TILES = REPO / "reports/discovery/valid_tiles.parquet"
OAKROOT = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy")
OAK_HARM = OAKROOT / "harmonized"
OAK_MANI = OAKROOT / "manifest" / "pairs.parquet"
OAK_TILES = OAKROOT / "manifest" / "valid_tiles.parquet"
OAK_BACKUPS = OAKROOT / "manifest_backups"
GATE_RESULT = REPO / "reports/discovery/stage_unify_oak_gate_result.json"
# expected stale-OAK signature (directive §1.1) — proves the refresh is needed
EXPECT_OAK_STALE_TILE_ROWS = 14795
BACKUP_STAMP = "2026-06-29_unifymasks_prewrite"   # no Date.now in scripts; fixed
RO = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH               # 0444
RW = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH  # 0644

MASK_FILES = ("hr_valid.tif", "lr_valid.tif", "joint_valid.tif")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def resolve_dir(harm_root: Path, pid: str) -> Path:
    """Physical harmonized dir (cal_dig sub-pairs are nested)."""
    if pid.startswith("cal_dig_morro_bay__"):
        return harm_root / "cal_dig_morro_bay" / pid.split("__", 1)[1]
    return harm_root / pid


def root_rel_mask_path(harmonized_path_hr: str, mask_name: str) -> str:
    """Derive the root-relative mask path from harmonized_path_hr so it matches the
    existing path convention exactly (handles the cal_dig nesting for free)."""
    assert harmonized_path_hr.endswith("hr.tif"), harmonized_path_hr
    return harmonized_path_hr[: -len("hr.tif")] + mask_name


def _mask_profile(hr_ds) -> dict:
    """uint8 / nodata 255 / tiled 256 / deflate — matches the new pairs' masks so
    the slicer treats all 39 identically."""
    return {
        "driver": "GTiff", "height": hr_ds.height, "width": hr_ds.width,
        "count": 1, "dtype": "uint8", "crs": hr_ds.crs,
        "transform": hr_ds.transform, "nodata": 255,
        "compress": "deflate", "tiled": True,
        "blockxsize": 256, "blockysize": 256,
    }


def _write_mask(arr_bool: np.ndarray, hr_ds, out_path: Path) -> None:
    prof = _mask_profile(hr_ds)
    with rasterio.open(out_path, "w", **prof) as d:
        d.write(arr_bool.astype("uint8"), 1)


def build_pair_masks(pid: str, src_dir: Path) -> dict:
    """Read hr.tif/lr.tif, derive the three masks on the HR grid, write them to
    src_dir. Returns diagnostics. NEVER writes to hr.tif/lr.tif."""
    hr_p, lr_p = src_dir / "hr.tif", src_dir / "lr.tif"
    assert hr_p.exists() and lr_p.exists(), f"missing hr/lr in {src_dir}"

    with rasterio.open(hr_p) as hr_ds, rasterio.open(lr_p) as lr_ds:
        # §4 precondition: same CRS so LR coverage can be placed on the HR grid
        # without reprojection or any coregistration shift. Escalate if not.
        crs_match = (hr_ds.crs is not None and lr_ds.crs is not None
                     and str(hr_ds.crs) == str(lr_ds.crs))
        if not crs_match:
            return {"pair_id": pid, "error": "crs_mismatch_escalate",
                    "hr_crs": str(hr_ds.crs), "lr_crs": str(lr_ds.crs)}

        # hr_valid: honor HR's OWN nodata tag + any NaN fill -> real-data mask
        hr_arr = hr_ds.read(1, masked=True).filled(np.nan).astype("float64")
        hr_valid = np.isfinite(hr_arr)
        # leakage sentinel: finite cells suspiciously near a -9999 fill that the
        # nodata tag failed to catch (the stage_f new-pair fill-corruption bug).
        susp = int((np.isfinite(hr_arr) & (np.abs(hr_arr + 9999.0) < 1.0)).sum())

        # lr coverage on its native grid -> {0,1} float, then NEAREST-upsample to HR
        lr_arr = lr_ds.read(1, masked=True).filled(np.nan).astype("float64")
        lr_cov = np.isfinite(lr_arr).astype("float32")
        lr_valid_f = np.zeros((hr_ds.height, hr_ds.width), dtype="float32")
        reproject(
            source=lr_cov, destination=lr_valid_f,
            src_transform=lr_ds.transform, src_crs=lr_ds.crs,
            dst_transform=hr_ds.transform, dst_crs=hr_ds.crs,
            src_nodata=0.0, dst_nodata=0.0,
            resampling=Resampling.nearest,
        )
        lr_valid = lr_valid_f > 0.5
        joint = hr_valid & lr_valid

        _write_mask(hr_valid, hr_ds, src_dir / "hr_valid.tif")
        _write_mask(lr_valid, hr_ds, src_dir / "lr_valid.tif")
        _write_mask(joint, hr_ds, src_dir / "joint_valid.tif")

        cell_km2 = abs(hr_ds.res[0] * hr_ds.res[1]) / 1e6
        diag = {
            "pair_id": pid, "error": None,
            "hr_shape": [hr_ds.height, hr_ds.width],
            "lr_shape": [lr_ds.height, lr_ds.width],
            "hr_res_m": round(abs(hr_ds.res[0]), 3),
            "lr_res_m": round(abs(lr_ds.res[0]), 3),
            "crs": str(hr_ds.crs),
            "hr_nodata": (None if hr_ds.nodata is None else float(hr_ds.nodata)),
            "lr_nodata": (None if lr_ds.nodata is None else float(lr_ds.nodata)),
            "hr_valid_cells": int(hr_valid.sum()),
            "lr_valid_cells": int(lr_valid.sum()),
            "joint_valid_cells": int(joint.sum()),
            "hr_valid_frac": round(float(hr_valid.mean()), 4),
            "joint_over_hr_frac": round(float(joint.sum() / max(1, hr_valid.sum())), 4),
            "joint_valid_area_km2": round(int(joint.sum()) * cell_km2, 4),
            "suspect_fill_cells": susp,
        }
    # checksum the freshly written masks
    diag["checksums"] = {m: sha256(src_dir / m) for m in MASK_FILES}
    return diag


def snapshot_grids(harm_root: Path) -> dict:
    """sha256 of all 42 validated grids (hr+lr) on the given root."""
    return compute_validated_grid_sha256(harm_root)


def assert_no_grid_drift(before: dict, after: dict, *, where: str) -> None:
    if len(before) != 2 * N_VALIDATED:
        raise AssertionError(f"{where}: expected 42 grids, snapshot has {len(before)}")
    drift = [k for k in before if after.get(k) != before[k]]
    extra = [k for k in after if k not in before]
    if drift or extra:
        raise AssertionError(f"{where}: GRID DRIFT {len(drift)}/42 changed {drift[:5]} "
                             f"extra={extra[:5]}")
    log.info("%s: validated grids 0/%d drift (PASS)", where, len(before))


# --------------------------------------------------------------------------- #
# generate (scratch + repo manifest; NO OAK)
# --------------------------------------------------------------------------- #
def cmd_generate() -> dict:
    res = {"ok": False, "mode": "generate", "pairs": [], "escalations": []}
    canon = pd.read_parquet(CANON)
    assert_validated_anchor(canon)
    grid_ref = json.loads(GRID_SHA_REF.read_text())
    # canonical OAK grids untouched (we don't write OAK here) — assert anyway
    assert_validated_grids(OAK_HARM, grid_ref)
    log.info("ANCHOR BEFORE: manifest + OAK validated grids PASS")

    # independent self-snapshot of the SCRATCH grids we write alongside
    scr_before = snapshot_grids(SCR_HARM)
    # confirm scratch grids == OAK canonical reference (they should be copies)
    scr_vs_ref = [k for k in grid_ref if scr_before.get(k) != grid_ref[k]]
    res["scratch_matches_oak_ref"] = (len(scr_vs_ref) == 0)
    if scr_vs_ref:
        log.warning("scratch grids differ from OAK ref on %d keys: %s",
                    len(scr_vs_ref), scr_vs_ref[:5])

    for pid in sorted(VALIDATED_PAIR_IDS):
        assert is_validated(pid), pid
        src = resolve_dir(SCR_HARM, pid)
        assert src.exists(), f"missing scratch dir {src}"
        d = build_pair_masks(pid, src)
        if d.get("error"):
            res["escalations"].append(d)
            log.error("ESCALATE %s: %s", pid, d["error"])
            continue
        res["pairs"].append(d)
        log.info("%-46s hr_valid=%d joint=%d (%.3f km2) joint/hr=%.3f susp_fill=%d",
                 pid, d["hr_valid_cells"], d["joint_valid_cells"],
                 d["joint_valid_area_km2"], d["joint_over_hr_frac"], d["suspect_fill_cells"])

    # prove hr/lr untouched on scratch
    scr_after = snapshot_grids(SCR_HARM)
    assert_no_grid_drift(scr_before, scr_after, where="scratch")
    res["grid_drift_scratch"] = "0/42"

    if res["escalations"]:
        res["ok"] = False
        res["note"] = "CRS-mismatch escalation(s) — manifest NOT updated; resolve first"
        RESULT.write_text(json.dumps(res, indent=2, default=str))
        log.error("Escalations present — stopping before manifest update")
        return res

    # ---- manifest update (additive) ----
    # back up first
    bk = REPO / "manifest/pairs.parquet.bak_2026-06-29_unifymasks"
    if not bk.exists():
        shutil.copy2(CANON, bk)
        log.info("backed up manifest -> %s", bk.name)

    # ensure columns exist
    for c in ("hr_valid", "lr_valid", "joint_valid", "lr_valid_semantic",
              "checksum_hr_valid", "checksum_lr_valid", "checksum_joint_valid"):
        if c not in canon.columns:
            canon[c] = pd.NA

    diag_by_pid = {d["pair_id"]: d for d in res["pairs"]}

    def set_row(pid: str, semantic: str):
        m = canon.pair_id == pid
        hp = canon.loc[m, "harmonized_path_hr"].iloc[0]
        canon.loc[m, "hr_valid"] = root_rel_mask_path(hp, "hr_valid.tif")
        canon.loc[m, "lr_valid"] = root_rel_mask_path(hp, "lr_valid.tif")
        canon.loc[m, "joint_valid"] = root_rel_mask_path(hp, "joint_valid.tif")
        canon.loc[m, "lr_valid_semantic"] = semantic

    # 21 validated: coverage_geotiff + checksums of the masks we just wrote
    for pid, d in diag_by_pid.items():
        set_row(pid, "coverage_geotiff")
        m = canon.pair_id == pid
        canon.loc[m, "checksum_hr_valid"] = d["checksums"]["hr_valid.tif"]
        canon.loc[m, "checksum_lr_valid"] = d["checksums"]["lr_valid.tif"]
        canon.loc[m, "checksum_joint_valid"] = d["checksums"]["joint_valid.tif"]

    # 18 new: real_sounding + point path cols at their existing masks (+ checksums)
    new_done = []
    for pid in canon.loc[canon.pair_id.apply(is_new), "pair_id"]:
        src = SCR_HARM / pid
        if not all((src / m).exists() for m in MASK_FILES):
            log.warning("new pair %s missing a mask on scratch — leaving path cols empty", pid)
            continue
        set_row(pid, "real_sounding")
        m = canon.pair_id == pid
        canon.loc[m, "checksum_hr_valid"] = sha256(src / "hr_valid.tif")
        canon.loc[m, "checksum_lr_valid"] = sha256(src / "lr_valid.tif")
        canon.loc[m, "checksum_joint_valid"] = sha256(src / "joint_valid.tif")
        new_done.append(pid)
    res["new_pairs_pathset"] = len(new_done)

    assert_validated_anchor(canon)
    canon.to_parquet(CANON, index=False)
    re = pd.read_parquet(CANON)
    assert_validated_anchor(re)
    # semantic tally
    sem = re["lr_valid_semantic"].value_counts(dropna=False).to_dict()
    res["lr_valid_semantic_counts"] = {str(k): int(v) for k, v in sem.items()}
    log.info("lr_valid_semantic: %s", res["lr_valid_semantic_counts"])

    res["n_validated_masked"] = len(res["pairs"])
    res["ok"] = (len(res["pairs"]) == N_VALIDATED and not res["escalations"])
    RESULT.write_text(json.dumps(res, indent=2, default=str))
    log.info("=== GENERATE COMPLETE: %d/21 validated masked on scratch; manifest "
             "updated (additive); grids 0/42 drift; OAK NOT touched (HELD) ===",
             len(res["pairs"]))
    return res


# --------------------------------------------------------------------------- #
# §1 pre-write gate (READ-ONLY — must pass + Steve's go before persisting)
# --------------------------------------------------------------------------- #
def _abs_or_scratch_offenders(df: pd.DataFrame) -> dict:
    """Path columns whose values are absolute (start with '/') or mention /scratch.
    Directive §1.3: no absolute /scratch paths may persist."""
    pathcols = [c for c in df.columns if "path" in c.lower()] + list(
        ("hr_valid", "lr_valid", "joint_valid"))
    out = {}
    for c in pathcols:
        if c not in df.columns:
            continue
        s = df[c].astype("string")
        bad = df.loc[s.str.startswith("/", na=False) | s.str.contains("/scratch", na=False),
                     "pair_id"].tolist()
        if bad:
            out[c] = bad
    return out


def cmd_gate() -> dict:
    """§1: prove OAK is stale, table the fresh tile counts, confirm root-relative
    paths. Read-only — touches nothing. Result feeds the HOLD for Steve."""
    g = {"ok": False, "mode": "gate"}
    repo_pairs = pd.read_parquet(CANON)
    repo_tiles = pd.read_parquet(REPO_TILES)
    oak_pairs = pd.read_parquet(OAK_MANI)
    oak_tiles = pd.read_parquet(OAK_TILES)

    # §1.1 staleness
    g["oak_pairs_has_joint_valid"] = bool("joint_valid" in oak_pairs.columns)
    g["oak_pairs_ncols"] = int(len(oak_pairs.columns))
    g["repo_pairs_has_joint_valid"] = bool("joint_valid" in repo_pairs.columns)
    g["repo_pairs_ncols"] = int(len(repo_pairs.columns))
    g["oak_valid_tiles_rows"] = int(len(oak_tiles))
    g["oak_valid_tiles_pairs"] = int(oak_tiles.pair_id.nunique())
    g["repo_valid_tiles_rows"] = int(len(repo_tiles))
    g["repo_valid_tiles_pairs"] = int(repo_tiles.pair_id.nunique())
    g["staleness_confirmed"] = bool(
        (not g["oak_pairs_has_joint_valid"])
        and g["oak_valid_tiles_rows"] == EXPECT_OAK_STALE_TILE_ROWS
        and g["repo_pairs_has_joint_valid"])

    # §1.2 per-pair tile table over the FRESH index, every manifest pair listed
    counts = repo_tiles.pair_id.value_counts().to_dict()
    per_pair = [{"pair_id": pid, "n_tiles": int(counts.get(pid, 0)),
                 "class": "validated" if is_validated(pid) else "new"}
                for pid in repo_pairs.pair_id]
    g["per_pair_tiles"] = per_pair
    g["zero_tile_pairs"] = [p["pair_id"] for p in per_pair if p["n_tiles"] == 0]
    g["EW0207__MGDS_32556_tiles"] = int(counts.get("EW0207__MGDS_32556", 0))
    # stale ids present in OAK index but not in the canonical manifest
    g["stale_oak_pair_ids"] = sorted(set(oak_tiles.pair_id) - set(repo_pairs.pair_id))

    # §1.3 path form — no absolute / /scratch paths in the fresh manifest
    offenders = _abs_or_scratch_offenders(repo_pairs)
    g["abs_or_scratch_path_offenders"] = offenders
    g["paths_root_relative"] = (len(offenders) == 0)

    # pre-flight: all 63 validated masks staged on scratch; 18 new masks on OAK;
    # repo grid ref matches OAK (so the write's anchor will pass)
    miss_scr = []
    for pid in VALIDATED_PAIR_IDS:
        sdir = resolve_dir(SCR_HARM, pid)
        miss_scr += [f"{pid}/{m}" for m in MASK_FILES if not (sdir / m).exists()]
    g["validated_masks_staged_on_scratch"] = (len(miss_scr) == 0)
    g["missing_scratch_masks"] = miss_scr
    miss_oak_new = []
    for pid in repo_pairs.loc[repo_pairs.pair_id.apply(is_new), "pair_id"]:
        odir = resolve_dir(OAK_HARM, pid)
        miss_oak_new += [f"{pid}/{m}" for m in MASK_FILES if not (odir / m).exists()]
    g["new_masks_present_on_oak"] = (len(miss_oak_new) == 0)
    g["missing_oak_new_masks"] = miss_oak_new
    grid_ref = json.loads(GRID_SHA_REF.read_text())
    cur_oak = snapshot_grids(OAK_HARM)
    g["oak_grids_match_ref"] = (len([k for k in grid_ref if cur_oak.get(k) != grid_ref[k]]) == 0
                                and len(grid_ref) == 2 * N_VALIDATED)

    g["ok"] = bool(g["staleness_confirmed"] and g["paths_root_relative"]
                   and not g["zero_tile_pairs"]
                   and g["validated_masks_staged_on_scratch"]
                   and g["new_masks_present_on_oak"] and g["oak_grids_match_ref"])
    GATE_RESULT.write_text(json.dumps(g, indent=2, default=str))
    log.info("GATE: stale=%s root_rel=%s zero_tile=%d 32556=%d staged=%s oak_new=%s grids=%s -> ok=%s",
             g["staleness_confirmed"], g["paths_root_relative"], len(g["zero_tile_pairs"]),
             g["EW0207__MGDS_32556_tiles"], g["validated_masks_staged_on_scratch"],
             g["new_masks_present_on_oak"], g["oak_grids_match_ref"], g["ok"])
    return g


# --------------------------------------------------------------------------- #
# persist-oak (HELD for Steve — runs only after the §1 gate + explicit go)
# --------------------------------------------------------------------------- #
def _listing(d: Path) -> list:
    return sorted(p.name for p in d.iterdir())


def _backup_oak_file(name: str) -> str | None:
    src = OAKROOT / "manifest" / name
    if not src.exists():
        return None
    OAK_BACKUPS.mkdir(exist_ok=True)
    dst = OAK_BACKUPS / f"{name}.bak_{BACKUP_STAMP}"
    if dst.exists():
        os.chmod(dst, RW)
    shutil.copy2(src, dst)
    ok = sha256(src) == sha256(dst)
    os.chmod(dst, RO)
    assert ok, f"OAK backup byte-verify failed {name}"
    return str(dst)


def _publish(src: Path, dst: Path) -> bool:
    if dst.exists():
        os.chmod(dst, RW)
    shutil.copy2(src, dst)
    ok = sha256(src) == sha256(dst)
    os.chmod(dst, RO)
    assert ok, f"publish byte-verify failed {dst}"
    return ok


def cmd_persist_oak() -> dict:
    res = {"ok": False, "mode": "persist-oak", "pairs": [], "backups": []}
    # re-run the gate as a hard precondition — refuse to write a stale/bad state
    gate = cmd_gate()
    if not gate["ok"]:
        raise AssertionError(f"§1 gate not satisfied — refusing OAK write: "
                             f"stale={gate['staleness_confirmed']} "
                             f"root_rel={gate['paths_root_relative']} "
                             f"zero_tile={gate['zero_tile_pairs']} "
                             f"staged={gate['validated_masks_staged_on_scratch']} "
                             f"grids={gate['oak_grids_match_ref']}")
    log.info("§1 GATE PASS — proceeding to OAK write")

    canon = pd.read_parquet(CANON)
    assert_validated_anchor(canon)
    grid_ref = json.loads(GRID_SHA_REF.read_text())
    oak_before = snapshot_grids(OAK_HARM)
    assert_validated_grids(OAK_HARM, grid_ref)
    assert_validated_anchor(pd.read_parquet(OAK_MANI))   # current (pre-mask) OAK still anchors
    log.info("ANCHOR BEFORE (OAK): grids 42 + manifest PASS")

    # §3.1 immutable backups of the current OAK parquets
    for name in ("pairs.parquet", "valid_tiles.parquet"):
        b = _backup_oak_file(name)
        if b:
            res["backups"].append(b)
            log.info("backed up OAK %s -> %s", name, Path(b).name)

    # §3.2 masks -> validated OAK dirs, additions-only, byte-verified, 0444
    for pid in sorted(VALIDATED_PAIR_IDS):
        sdir, odir = resolve_dir(SCR_HARM, pid), resolve_dir(OAK_HARM, pid)
        assert odir.exists(), f"missing OAK dir {odir}"
        before = _listing(odir)
        for m in MASK_FILES:
            srcm, dstm = sdir / m, odir / m
            assert srcm.exists(), f"missing scratch mask {srcm}"
            if dstm.exists():
                os.chmod(dstm, RW)
            shutil.copy2(srcm, dstm)
            ok = sha256(srcm) == sha256(dstm)
            os.chmod(dstm, RO)
            assert ok, f"OAK mask byte-verify failed {pid}/{m}"
        after = _listing(odir)
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        # additions-only: nothing removed; new names are only mask files; grids stay
        assert not removed, f"{pid}: dir lost files {removed}"
        assert set(after) - set(before) <= set(MASK_FILES), f"{pid}: non-mask add {added}"
        for keep in ("hr.tif", "lr.tif"):
            assert keep in before and keep in after, f"{pid}: {keep} missing!"
        res["pairs"].append({"pair_id": pid, "added": added,
                             "before_listing": before, "after_listing": after})
        log.info("OAK persist %-46s added=%s", pid, added)

    # grids untouched + anchor, on the OAK side, AFTER the mask write
    oak_after = snapshot_grids(OAK_HARM)
    assert_no_grid_drift(oak_before, oak_after, where="OAK")
    assert_validated_grids(OAK_HARM, grid_ref)
    res["grid_drift_oak"] = "0/42"

    # §3.3 publish both parquets, byte-verified, 0444
    res["pairs_byte_identical"] = _publish(CANON, OAK_MANI)
    res["valid_tiles_byte_identical"] = _publish(REPO_TILES, OAK_TILES)

    # §4 verification
    oak_canon = pd.read_parquet(OAK_MANI)
    assert_validated_anchor(oak_canon)
    empty = oak_canon[oak_canon[["hr_valid", "lr_valid", "joint_valid"]].isna().any(axis=1)]
    assert len(empty) == 0, f"OAK manifest empty mask paths: {empty.pair_id.tolist()}"
    # all 39 pairs: 3 masks present + 0444 on OAK (lock any stray-writable mask)
    writable = []
    for pid in oak_canon.pair_id:
        odir = resolve_dir(OAK_HARM, pid)
        for m in MASK_FILES:
            p = odir / m
            assert p.exists(), f"missing OAK mask {p}"
            if stat.S_IMODE(p.stat().st_mode) & 0o222:
                os.chmod(p, RO)
                writable.append(str(p))
    res["relocked_writable_masks"] = writable
    # §3.4 no writable parquet in manifest dir
    for pp in (OAK_MANI, OAK_TILES):
        if stat.S_IMODE(pp.stat().st_mode) & 0o222:
            os.chmod(pp, RO)
    repo_tiles_n = int(len(pd.read_parquet(REPO_TILES)))
    oak_t = pd.read_parquet(OAK_TILES)
    res["oak_valid_tiles_rows"] = int(len(oak_t))
    res["oak_valid_tiles_pairs"] = int(oak_t.pair_id.nunique())
    res["oak_stale_pair_ids"] = sorted(set(oak_t.pair_id) - set(oak_canon.pair_id))
    res["n_validated_persisted"] = len(res["pairs"])
    res["ok"] = bool(res["pairs_byte_identical"] and res["valid_tiles_byte_identical"]
                     and len(empty) == 0 and res["oak_valid_tiles_rows"] == repo_tiles_n
                     and res["oak_valid_tiles_pairs"] == int(oak_canon.pair_id.nunique())
                     and not res["oak_stale_pair_ids"]
                     and len(res["pairs"]) == N_VALIDATED)
    out = REPO / "reports/discovery/stage_unify_valid_masks_oak_result.json"
    out.write_text(json.dumps(res, indent=2, default=str))
    log.info("=== OAK PERSIST COMPLETE: 63 masks 0444 byte-verified; grids 0/42; "
             "pairs+tiles refreshed byte-identical; anchor PASS; tiles=%d/%d ===",
             res["oak_valid_tiles_rows"], res["oak_valid_tiles_pairs"])
    return res


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", action="store_true",
                    help="§1 read-only pre-write gate (staleness + tile table + path form)")
    ap.add_argument("--persist-oak", action="store_true",
                    help="HELD: write masks + refresh parquets into OAK (Steve's go only)")
    a = ap.parse_args()
    if a.persist_oak:
        cmd_persist_oak()
    elif a.gate:
        cmd_gate()
    else:
        cmd_generate()


if __name__ == "__main__":
    main()
