"""Phase 2 Stage F REPAIR — independent verification + masked datum repair.

Directive: reports/directive_phase2_stage_f_repair.md.

This is written FRESH (not reusing the suspect F5 logic) to independently
re-verify the Stage F nodata/datum bug, reconstruct the repair value per pair
from the raw data, repair hr.tif (masked, append-only), and re-verify the F5
masks + the 21 validated pairs.

The bug (to be re-confirmed here): stage_f_harmonize.py:162 opened HR WITHOUT
masked=True before estimate_rigid_xyz, so -9999 fill was sampled as real,
producing a garbage dz that apply_xyz added to EVERY cell. Consequences:
  - fill moved -9999 -> -9999+dz (leaks past the still-(-9999) nodata tag)
  - real seafloor shifted by the garbage dz (vertical datum corrupted)

Modes:
  verify   : read-only. Per new pair: fill clusters, current-real stats,
             recovered HR_orig (=current-dz_stageF) stats, LR stats over joint,
             datum residual HR_orig-LR, an INDEPENDENT masked re-coreg, and
             absolute-depth sanity vs corpus depth_m. Also checks the 21
             validated pairs and the F5 masks/tiles. Writes a JSON.
  repair   : writes. For confirmed vertical-suspect pairs: preserve hr.tif as
             hr_preF5repair.tif, strip fill -> NaN, apply the chosen repair dz
             to real cells, rewrite hr.tif with NaN nodata (float32). The
             per-pair applied dz is read from the verify JSON decision.

Run on a compute node (sbatch) — never the login node.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import rioxarray  # noqa: F401
from rasterio.warp import reproject, Resampling

from src import coregister as cor

log = logging.getLogger("stage_f_repair")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
OAK = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy")
HARM = DATA / "harmonized"
RESULTS_F = REPO / "reports/discovery/stage_f_results.json"
CORPUS = REPO / "reports/combined_corpus.csv"
TILES_PARQUET = REPO / "reports/discovery/valid_tiles.parquet"
VERIFY_JSON = REPO / "reports/discovery/stage_f_repair_verify.json"

FILL = -9999.0
VSUSPECT_THRESH = 50.0     # |dz_stageF| above which the vertical datum is suspect


def _pct(a, qs=(1, 50, 99)):
    if a.size == 0:
        return {f"p{q}": None for q in qs}
    return {f"p{q}": round(float(np.percentile(a, q)), 3) for q in qs}


def _fill_decompose(hr_raw: np.ndarray, dz: float):
    """Classify cells into: -9999 fill, leaked -9999+dz fill, NaN, and real."""
    nan = ~np.isfinite(hr_raw)
    at_9999 = np.isclose(hr_raw, FILL, atol=1e-3)
    if abs(dz) > 1e-6:
        leaked = np.isclose(hr_raw, FILL + dz, atol=1.0) & ~at_9999
    else:
        leaked = np.zeros_like(at_9999)
    real = ~(nan | at_9999 | leaked)
    return real, at_9999, leaked, nan


def _masked_recoreg(hr_raw, real_mask, joint, hr_ds, lr_path, tmp):
    """INDEPENDENT masked re-coreg on real joint cells of the CURRENT hr.tif.

    Returns dz/dx/dy/mad/psr-free CoregResult-derived dict. We mask current HR
    to joint real cells (NaN elsewhere), write with NaN nodata, open masked, and
    run the same rigid estimator the validated pipeline used (which itself is
    not buggy — the bug was the unmasked OPEN in the caller)."""
    use = real_mask & joint
    n = int(use.sum())
    if n < 200:
        return {"n_joint_real": n, "note": "fewer than 200 joint-real cells"}
    arr = np.where(use, hr_raw, np.nan).astype("float32")
    mp = tmp / "hr_jointreal.tif"
    prof = hr_ds.profile.copy()
    prof.update(dtype="float32", nodata=np.nan, count=1, compress="DEFLATE")
    with rasterio.open(mp, "w", **prof) as d:
        d.write(arr, 1)
    hr_da = rioxarray.open_rasterio(str(mp), masked=True).squeeze()
    lr_da = rioxarray.open_rasterio(str(lr_path), masked=True).squeeze()
    c = cor.estimate_rigid_xyz(hr_da, lr_da)
    return {
        "n_joint_real": n,
        "dx": round(c.dx_m, 3), "dy": round(c.dy_m, 3), "dz": round(c.dz_m, 3),
        "offset_m": round(float(np.hypot(c.dx_m, c.dy_m)), 3),
        "post_mad_m": round(c.post_residual_mad_m, 3),
        "pre_median_m": round(c.pre_residual_median_m, 3),
        "n_samples": c.n_samples,
    }


def verify_pair(rec: dict, corpus_row: dict, tmp: Path) -> dict:
    pid = rec["pair_id"]
    dz = float(rec.get("coreg_dz") or 0.0)
    pdir = HARM / pid
    hr_p, lr_p, jt_p = pdir / "hr.tif", pdir / "lr.tif", pdir / "joint_valid.tif"
    out = {
        "pair_id": pid, "role": rec.get("role"), "morphology": rec.get("morphology"),
        "f5_bucket": corpus_row.get("f5_bucket"),
        "expected_depth_m": corpus_row.get("depth_m"),
        "dz_stageF": round(dz, 3),
        "f5_recoreg_dz": corpus_row.get("f5_recoreg_dz_m"),
        "vertical_suspect": abs(dz) > VSUSPECT_THRESH,
    }
    if not hr_p.exists():
        out["error"] = "missing hr.tif"
        return out

    with rasterio.open(str(hr_p)) as ds:
        hr_raw = ds.read(1)
        out["hr_nodata_tag"] = None if ds.nodata is None else round(float(ds.nodata), 3)
        prof_shape = (ds.height, ds.width)

    real, at9999, leaked, nan = _fill_decompose(hr_raw, dz)
    out["n_total"] = int(hr_raw.size)
    out["n_fill_9999"] = int(at9999.sum())
    out["n_fill_leaked"] = int(leaked.sum())
    out["n_nan"] = int(nan.sum())
    out["n_real"] = int(real.sum())
    out["leaked_fill_value_expected"] = round(FILL + dz, 3) if abs(dz) > 1e-6 else None
    real_vals = hr_raw[real].astype("float64")
    out["current_real_stats"] = _pct(real_vals)
    out["hr_orig_stats"] = _pct(real_vals - dz)        # undo the additive bug

    # joint mask
    joint = None
    if jt_p.exists():
        with rasterio.open(str(jt_p)) as ds:
            jt = ds.read(1)
        joint = (jt == 1)
        out["n_joint"] = int(joint.sum())
        # mask cross-check: leaked fill must be excluded from joint
        if leaked.any():
            out["leaked_in_joint"] = int((leaked & joint).sum())   # want 0
        if at9999.any():
            out["fill9999_in_joint"] = int((at9999 & joint).sum())  # want 0
    else:
        out["n_joint"] = None

    # LR over joint + datum residual (HR_orig - LR).
    # lr.tif is at native LR GSD on its own grid; reproject (bilinear) onto the
    # HR grid so it is cell-aligned for the datum comparison.
    if lr_p.exists() and joint is not None and joint.any():
        with rasterio.open(str(hr_p)) as hds:
            hr_tr, hr_crs = hds.transform, hds.crs
        with rasterio.open(str(lr_p)) as ds:
            lr_src = ds.read(1).astype("float64")
            lr_nd = ds.nodata if ds.nodata is not None else FILL
            lr_tr, lr_crs = ds.transform, ds.crs
        lr_src = np.where(np.isclose(lr_src, lr_nd, atol=1e-3), np.nan, lr_src)
        lr_on_hr = np.full(prof_shape, np.nan, dtype="float64")
        reproject(source=lr_src, destination=lr_on_hr,
                  src_transform=lr_tr, src_crs=lr_crs,
                  dst_transform=hr_tr, dst_crs=hr_crs,
                  src_nodata=np.nan, dst_nodata=np.nan,
                  resampling=Resampling.bilinear)
        lr_real = np.isfinite(lr_on_hr)
        jr = real & joint & lr_real
        out["n_joint_real_lr"] = int(jr.sum())
        if jr.any():
            out["lr_over_joint_stats"] = _pct(lr_on_hr[jr])
            resid = (hr_raw[jr] - dz) - lr_on_hr[jr]       # HR_orig - LR
            out["datum_resid_hrorig_minus_lr"] = {
                "median": round(float(np.median(resid)), 3),
                "mad": round(float(np.median(np.abs(resid - np.median(resid)))), 3),
            }
            # also the residual of the CURRENT (corrupted) HR vs LR, for context
            cur_resid = hr_raw[jr] - lr_on_hr[jr]
            out["datum_resid_current_minus_lr"] = {
                "median": round(float(np.median(cur_resid)), 3)}

    # independent masked re-coreg (suspect pairs only, to bound cost)
    if out["vertical_suspect"] and joint is not None:
        try:
            out["my_recoreg"] = _masked_recoreg(hr_raw, real, joint, _reopen(hr_p), lr_p, tmp)
        except Exception as e:
            out["my_recoreg"] = {"error": str(e)[:150]}

    return out


def _reopen(p):
    return rasterio.open(str(p))


def verify_validated(tmp: Path) -> list:
    """Step 4: read-only check of the 21 validated pairs for the bug signature.

    They were built by pipeline.py / reharmonize_user_hr.py — both open HR with
    masked=True before coreg (verified in source). Here we confirm empirically:
    a clean nodata tag, NO leaked-fill cluster, and physically plausible depths.
    """
    checks = []
    # discol/ccz/tag are single-dir; cal_dig is many subdirs (sample a few)
    targets = []
    for name in ("discol_so242_1", "ccz_so268_1", "tag_m127"):
        for root in (OAK, DATA):
            p = root / "harmonized" / name / "hr.tif"
            if p.exists():
                targets.append((name, p)); break
    caldig = (OAK / "harmonized" / "cal_dig_morro_bay")
    if not caldig.exists():
        caldig = DATA / "harmonized" / "cal_dig_morro_bay"
    if caldig.exists():
        subs = sorted([d for d in caldig.iterdir() if (d / "hr.tif").exists()])
        for d in subs[:4]:
            targets.append((f"cal_dig/{d.name}", d / "hr.tif"))

    for name, p in targets:
        rec = {"pair": name, "path": str(p)}
        try:
            with rasterio.open(str(p)) as ds:
                a = ds.read(1)
                nd = ds.nodata
            rec["nodata_tag"] = None if nd is None else round(float(nd), 3)
            finite = np.isfinite(a)
            if nd is not None:
                real = finite & ~np.isclose(a, nd, atol=1e-3)
            else:
                real = finite
            rv = a[real].astype("float64")
            rec["real_stats"] = _pct(rv)
            # bug signature: a finite cluster parked near -9999+something (a
            # leaked fill) would show as an isolated spike well below seafloor.
            # Flag any real value < -8000 (no real ocean is that deep) or any
            # implausibly large positive (a sign/datum flip).
            rec["n_real"] = int(real.sum())
            rec["suspicious_lt_-8000"] = int((rv < -8000).sum())
            rec["suspicious_gt_1000"] = int((rv > 1000).sum())
        except Exception as e:
            rec["error"] = str(e)[:150]
        checks.append(rec)
    return checks


def verify_tiles_sample() -> dict:
    """Step 5: sample valid_tiles.parquet and confirm tiles are joint-valid on
    both sides (joint fraction >= 0.5 and real on hr & lr)."""
    out = {}
    if not TILES_PARQUET.exists():
        return {"error": "valid_tiles.parquet missing"}
    df = pd.read_parquet(TILES_PARQUET)
    out["n_tiles"] = int(len(df))
    out["n_pairs"] = int(df["pair_id"].nunique())
    out["min_joint_fraction"] = round(float(df["joint_valid_fraction"].min()), 4)
    # sample 2 tiles from up to 4 pairs and verify against joint_valid.tif
    samples = []
    for pid in list(df["pair_id"].unique())[:4]:
        sub = df[df.pair_id == pid].head(2)
        jt_p = HARM / pid / "joint_valid.tif"
        if not jt_p.exists():
            continue
        with rasterio.open(str(jt_p)) as ds:
            jt = ds.read(1)
        for _, t in sub.iterrows():
            r0, c0, n = int(t.row0), int(t.col0), int(t.tile_px)
            tile = jt[r0:r0 + n, c0:c0 + n]
            frac = float((tile == 1).mean())
            samples.append({"pair_id": pid, "row0": r0, "col0": c0,
                            "recorded_frac": round(float(t.joint_valid_fraction), 4),
                            "recomputed_frac": round(frac, 4)})
    out["tile_samples"] = samples
    return out


def main_verify():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    recs = json.loads(RESULTS_F.read_text())
    corpus = pd.read_csv(CORPUS)
    crows = {r["pair_id"]: r for r in corpus.to_dict("records")}
    tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "stage_f_repair"
    tmp.mkdir(parents=True, exist_ok=True)

    pairs = []
    for r in recs:
        cr = crows.get(r["pair_id"], {})
        try:
            res = verify_pair(r, cr, tmp)
        except Exception as e:
            res = {"pair_id": r["pair_id"], "error": str(e)[:200]}
        log.info("[%s] suspect=%s dz_stageF=%s real=%s leaked=%s",
                 res.get("pair_id"), res.get("vertical_suspect"),
                 res.get("dz_stageF"), res.get("n_real"), res.get("n_fill_leaked"))
        pairs.append(res)

    validated = verify_validated(tmp)
    tiles = verify_tiles_sample()

    n_suspect = sum(1 for p in pairs if p.get("vertical_suspect"))
    n_leaked = sum(1 for p in pairs if (p.get("n_fill_leaked") or 0) > 0)
    summary = {"n_new_pairs": len(pairs), "n_vertical_suspect": n_suspect,
               "n_fill_leaked": n_leaked}
    log.info("SUMMARY %s", summary)
    VERIFY_JSON.write_text(json.dumps(
        {"summary": summary, "pairs": pairs, "validated_21": validated,
         "tiles_sample": tiles}, indent=2, default=str))
    log.info("wrote %s", VERIFY_JSON)


REPAIR_JSON = REPO / "reports/discovery/stage_f_repair_results.json"


def _lr_on_hr(lr_p: Path, hr_p: Path, shape) -> np.ndarray:
    """Reproject lr.tif (native GSD, own grid) onto the HR grid (bilinear)."""
    with rasterio.open(str(hr_p)) as hds:
        hr_tr, hr_crs = hds.transform, hds.crs
    with rasterio.open(str(lr_p)) as ds:
        lr_src = ds.read(1).astype("float64")
        lr_nd = ds.nodata if ds.nodata is not None else FILL
        lr_tr, lr_crs = ds.transform, ds.crs
    lr_src = np.where(np.isclose(lr_src, lr_nd, atol=1e-3), np.nan, lr_src)
    dst = np.full(shape, np.nan, dtype="float64")
    reproject(source=lr_src, destination=dst,
              src_transform=lr_tr, src_crs=lr_crs,
              dst_transform=hr_tr, dst_crs=hr_crs,
              src_nodata=np.nan, dst_nodata=np.nan,
              resampling=Resampling.bilinear)
    return dst


def repair_pair(rec: dict) -> dict:
    """Append-only datum/fill repair of one pair's hr.tif.

    - vertical-suspect (|dz_stageF|>50): align HR datum to the ship LR via a
      robust zero-horizontal-shift offset dz_apply = -median(current-LR) over
      joint real cells (depth-sane by construction; independent of the suspect
      horizontal search). Strip fill -> NaN.
    - small-dz fill-leaked (|dz_stageF|<=50, has leaked fill): dz_apply=0; the
      real values are already depth-sane (current ~ LR within a few m), so only
      strip the leaked fill -> NaN.
    Geometry (transform/CRS) is UNCHANGED, so the F5 masks/tiles stay aligned.
    Preserves the pre-repair file as hr_preF5repair.tif (idempotent: if that
    backup already exists, the pair is treated as already repaired and skipped).
    """
    pid = rec["pair_id"]
    dz = float(rec.get("coreg_dz") or 0.0)
    pdir = HARM / pid
    hr_p, lr_p, jt_p = pdir / "hr.tif", pdir / "lr.tif", pdir / "joint_valid.tif"
    backup = pdir / "hr_preF5repair.tif"
    out = {"pair_id": pid, "dz_stageF": round(dz, 3)}

    if not hr_p.exists():
        out["status"] = "skip"; out["reason"] = "no hr.tif"; return out

    with rasterio.open(str(hr_p)) as ds:
        hr_raw = ds.read(1)
        prof = ds.profile.copy()
        cur_nodata = ds.nodata
    real, at9999, leaked, nan = _fill_decompose(hr_raw, dz)
    out["n_real"] = int(real.sum())
    out["n_fill_9999"] = int(at9999.sum())
    out["n_fill_leaked"] = int(leaked.sum())

    suspect = abs(dz) > VSUSPECT_THRESH
    has_leak = int(leaked.sum()) > 0
    if not suspect and not has_leak:
        out["status"] = "untouched"; out["reason"] = "no datum corruption, no leaked fill"
        return out

    if backup.exists():
        out["status"] = "already_repaired"; out["reason"] = "hr_preF5repair.tif exists"
        return out

    # decide dz_apply
    dz_apply = 0.0
    if suspect:
        if not jt_p.exists():
            out["status"] = "error"; out["reason"] = "suspect but no joint_valid.tif"; return out
        with rasterio.open(str(jt_p)) as ds:
            joint = (ds.read(1) == 1)
        lr_on_hr = _lr_on_hr(lr_p, hr_p, hr_raw.shape)
        jr = real & joint & np.isfinite(lr_on_hr)
        if int(jr.sum()) < 200:
            out["status"] = "error"; out["reason"] = f"only {int(jr.sum())} joint-real-lr cells"; return out
        med_cur_minus_lr = float(np.median(hr_raw[jr] - lr_on_hr[jr]))
        dz_apply = -med_cur_minus_lr
        out["n_joint_real_lr"] = int(jr.sum())
        out["median_current_minus_lr"] = round(med_cur_minus_lr, 3)
        out["lr_median_over_joint"] = round(float(np.median(lr_on_hr[jr])), 3)
    out["dz_apply"] = round(dz_apply, 3)
    out["repair_mode"] = "datum_align_to_lr" if suspect else "fill_clean_only"

    # build repaired array: real -> current + dz_apply, everything else -> NaN
    repaired = np.where(real, hr_raw.astype("float64") + dz_apply, np.nan).astype("float32")
    out["repaired_real_p50"] = round(float(np.nanpercentile(repaired, 50)), 3)
    out["repaired_real_p1"] = round(float(np.nanpercentile(repaired, 1)), 3)
    out["repaired_real_p99"] = round(float(np.nanpercentile(repaired, 99)), 3)

    # preserve evidence, then write masked (NaN nodata)
    shutil.copy2(hr_p, backup)
    prof.update(dtype="float32", nodata=float("nan"), count=1,
                compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")
    with rasterio.open(str(hr_p), "w", **prof) as d:
        d.write(repaired, 1)
    out["status"] = "repaired"
    out["prev_nodata_tag"] = None if cur_nodata is None else round(float(cur_nodata), 3)
    out["new_nodata_tag"] = "nan"
    return out


def main_repair():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    recs = json.loads(RESULTS_F.read_text())
    out = []
    for r in recs:
        try:
            res = repair_pair(r)
        except Exception as e:
            res = {"pair_id": r["pair_id"], "status": "error", "reason": str(e)[:200]}
        log.info("[%s] %s dz_apply=%s repaired_p50=%s", res["pair_id"],
                 res.get("status"), res.get("dz_apply"), res.get("repaired_real_p50"))
        out.append(res)
        REPAIR_JSON.write_text(json.dumps(out, indent=2, default=str))
    from collections import Counter
    log.info("STATUS %s", dict(Counter(r.get("status") for r in out)))
    log.info("wrote %s", REPAIR_JSON)


POSTCHECK_JSON = REPO / "reports/discovery/stage_f_repair_postcheck.json"


def postcheck_pair(rec: dict, corpus_row: dict) -> dict:
    """After-repair verification, opening hr.tif with masked=True (the way the
    loader will). Confirms: nodata masking works (no leaked fill survives), the
    masks still align to hr.tif, and the masked HR median ~ LR median over joint
    (depth-sane). Independent of the repair's own reported numbers."""
    pid = rec["pair_id"]
    pdir = HARM / pid
    hr_p, lr_p, jt_p = pdir / "hr.tif", pdir / "lr.tif", pdir / "joint_valid.tif"
    out = {"pair_id": pid, "role": rec.get("role"), "morphology": rec.get("morphology"),
           "f5_bucket": corpus_row.get("f5_bucket"),
           "expected_depth_m": corpus_row.get("depth_m"),
           "repaired_present": (pdir / "hr_preF5repair.tif").exists()}
    if not hr_p.exists():
        out["error"] = "no hr.tif"; return out
    da = rioxarray.open_rasterio(str(hr_p), masked=True).squeeze()
    arr = np.asarray(da.values, dtype="float64")
    out["hr_nodata_tag"] = None if da.rio.nodata is None else (
        "nan" if (da.rio.nodata != da.rio.nodata) else round(float(da.rio.nodata), 3))
    out["shape"] = list(arr.shape)
    finite = np.isfinite(arr)
    out["n_finite_after_mask"] = int(finite.sum())
    if finite.any():
        out["masked_min"] = round(float(np.nanmin(arr)), 3)
        out["masked_max"] = round(float(np.nanmax(arr)), 3)
        out["masked_p50"] = round(float(np.nanpercentile(arr, 50)), 3)
        # leaked fill would survive as values far below any seafloor:
        out["n_below_-8000_after_mask"] = int((arr < -8000).sum())
        out["n_positive_after_mask"] = int((arr > 50).sum())

    if jt_p.exists():
        with rasterio.open(str(jt_p)) as ds:
            jt = ds.read(1); jshape = ds.shape
        out["mask_shape_matches"] = (list(jshape) == out["shape"])
        joint = (jt == 1)
        if lr_p.exists() and joint.any():
            lr_on_hr = _lr_on_hr(lr_p, hr_p, arr.shape)
            jr = joint & finite & np.isfinite(lr_on_hr)
            out["n_joint_real_lr"] = int(jr.sum())
            if jr.any():
                out["hr_median_over_joint"] = round(float(np.median(arr[jr])), 3)
                out["lr_median_over_joint"] = round(float(np.median(lr_on_hr[jr])), 3)
                out["resid_hr_minus_lr"] = round(float(np.median(arr[jr] - lr_on_hr[jr])), 3)
    return out


def main_postcheck():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    recs = json.loads(RESULTS_F.read_text())
    corpus = pd.read_csv(CORPUS)
    crows = {r["pair_id"]: r for r in corpus.to_dict("records")}
    out = []
    for r in recs:
        try:
            res = postcheck_pair(r, crows.get(r["pair_id"], {}))
        except Exception as e:
            res = {"pair_id": r["pair_id"], "error": str(e)[:200]}
        log.info("[%s] %s p50=%s resid_lr=%s below8k=%s pos=%s maskok=%s",
                 res["pair_id"], res.get("f5_bucket"), res.get("masked_p50"),
                 res.get("resid_hr_minus_lr"), res.get("n_below_-8000_after_mask"),
                 res.get("n_positive_after_mask"), res.get("mask_shape_matches"))
        out.append(res)
    POSTCHECK_JSON.write_text(json.dumps(out, indent=2, default=str))
    log.info("wrote %s", POSTCHECK_JSON)


STAGING_STATE = REPO / "reports/discovery/staging_state_20260605.json"


def main_updatecorpus():
    """Merge repair status + depth-sanity columns into combined_corpus.csv and
    append a stage_f_repair block to staging_state. Small text artifacts only."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    repair = {r["pair_id"]: r for r in json.loads(REPAIR_JSON.read_text())}
    post = {r["pair_id"]: r for r in json.loads(POSTCHECK_JSON.read_text())}
    verify = {r["pair_id"]: r for r in json.loads(VERIFY_JSON.read_text())["pairs"]}

    corpus = pd.read_csv(CORPUS)
    cols = {"repair_status": [], "repair_dz_applied": [], "repaired_hr_p50_m": [],
            "repair_resid_lr_m": [], "hr_orig_p50_m": [], "raw_datum_broken": [],
            "repair_depth_sane": [], "advances_stage_g": []}
    for pid, bucket in zip(corpus["pair_id"], corpus["f5_bucket"]):
        rp, po, ve = repair.get(pid), post.get(pid), verify.get(pid)
        if rp is None:                       # the 21 validated (not in the 32 new)
            for k in cols: cols[k].append("")
            continue
        status = rp.get("status")
        hr_orig = (ve or {}).get("hr_orig_stats", {}).get("p50")
        raw_broken = bool(hr_orig is not None and hr_orig > 0)
        resid = (po or {}).get("resid_hr_minus_lr")
        p50 = (po or {}).get("masked_p50")
        # depth-sane: aligned to LR (|resid|<30 m) AND not a broken raw datum
        sane = bool(resid is not None and abs(resid) < 30 and not raw_broken)
        cols["repair_status"].append(status)
        cols["repair_dz_applied"].append(rp.get("dz_apply") if rp.get("dz_apply") is not None else "")
        cols["repaired_hr_p50_m"].append(p50 if p50 is not None else "")
        cols["repair_resid_lr_m"].append(resid if resid is not None else "")
        cols["hr_orig_p50_m"].append(hr_orig if hr_orig is not None else "")
        cols["raw_datum_broken"].append(raw_broken)
        cols["repair_depth_sane"].append(sane)
        cols["advances_stage_g"].append(bool(str(bucket) == "clean" and sane))
    for k, v in cols.items():
        corpus[k] = v
    corpus.to_csv(CORPUS, index=False)
    n_adv = sum(1 for x in cols["advances_stage_g"] if x is True)
    log.info("corpus updated: %d advancing, %d raw_datum_broken",
             n_adv, sum(1 for x in cols["raw_datum_broken"] if x is True))

    # staging_state append
    ss = json.loads(STAGING_STATE.read_text())
    advancing = [pid for pid, a in zip(corpus["pair_id"], cols["advances_stage_g"]) if a is True]
    broken = [pid for pid, b in zip(corpus["pair_id"], cols["raw_datum_broken"]) if b is True]
    ss["stage_f_repair"] = {
        "generated": "2026-06-26",
        "directive": "reports/directive_phase2_stage_f_repair.md",
        "report": "reports/stage_f_repair_report_2026-06-23.md",
        "what": "Independent re-verification of the Stage F nodata/datum bug + masked datum repair of hr.tif (append-only).",
        "bug_confirmed": {"vertical_suspect": 15, "fill_leaked": 22,
                          "independently_reproduced": True},
        "repair_principle": "align HR datum to ship LR: dz_apply = -median(HR_current - LR) over joint real cells; fill -> NaN; geometry unchanged so F5 masks stay aligned",
        "written": {"repaired": 22, "untouched": 10,
                    "backup": "hr_preF5repair.tif retained per repaired pair"},
        "two_groups": {
            "group_A_garbage_dz": "7 pairs, >50% fill -> Stage F dz garbage; undoing recovers sane datum ~ LR",
            "group_B_broken_raw_datum": "8 pairs, <50% fill -> Stage F dz ~legit; underlying AUV grid datum broken (+70..+255 m plateau); all non-advancing"},
        "validated_21_bugpath": "NO — pipeline.py & reharmonize_user_hr.py open masked=True; empirically clean (discol -4147, ccz -4098, tag -3463, cal_dig margin). NOT modified.",
        "masks_reverified": "joint_valid excludes leaked fill (leaked_in_joint=0 all 22; NA076 77 stray -9999 negligible); valid_tiles.parquet fractions reproduce; masks align post-repair",
        "raw_datum_broken_pairs": broken,
        "advancing_stage_g": advancing,
        "advancing_count": len(advancing),
        "status": "HOLD for assessment before Stage G",
    }
    STAGING_STATE.write_text(json.dumps(ss, indent=1, default=str))
    log.info("staging_state updated; advancing=%s", advancing)


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "verify"
    if mode == "verify":
        main_verify()
    elif mode == "repair":
        main_repair()
    elif mode == "postcheck":
        main_postcheck()
    elif mode == "updatecorpus":
        main_updatecorpus()
    else:
        raise SystemExit(f"unknown mode {mode}")
