"""ACQ-R14 step 3 (compute job): per pair, rewrite the as-used grids, masks and ship products as Cloud-Optimized
GeoTIFFs (directive section 2), write pair.json, zip the pair. Values are never changed: the arrays are copied as they
are (float32 grids, uint8 masks), only the container (COG, DEFLATE + predictor, overviews, EPSG CRS, explicit
nodata) is new. Idempotent: a pair whose zip exists in build_results.json is skipped unless --force.

    python -B -m src.acq_r14.build [--workers N] [--pairs id ...] [--force]
"""
from __future__ import annotations
import argparse, json, os, re, shutil, zipfile
from multiprocessing import Pool
from pathlib import Path
import numpy as np, rasterio
from rasterio.crs import CRS
from . import common as C

BUILD_RESULTS = C.RPT / "build_results.json"
GRIDS = ("hr", "lr")
MASKS = ("hr_valid", "lr_valid", "joint_valid")
PRODUCT_RASTERS = ("ship_count", "ship_sd", "ship_rsd", "ship_xtrack_frac", "ship_beam_angle", "ship_mean_regrid", "ship_median_regrid")
PRODUCT_SIDE = ("products.json", "products_extra.json", "qa_shift_surface.csv")
SCRUB = (re.compile(r"/scratch/groups/hilley/auv_ship_colocated_bathy/[^\"' ,]*"), re.compile(r"/oak/stanford/groups/hilley/auv_ship_colocated_bathy/[^\"' ,]*"))


def _scrub(obj):
    """Replace absolute cluster paths in copied provenance JSON by their path relative to the data root."""
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    if isinstance(obj, str):
        s = obj
        for rx in SCRUB:
            s = rx.sub(lambda m: "<data_root>/" + m.group(0).split("auv_ship_colocated_bathy/", 1)[1], s)
        return s
    return obj


def to_cog(src: Path, dst: Path, kind: str, epsg_hint: int | None, pid: str, fixes: list) -> dict:
    """kind: grid | mask | product. Returns the header of the written COG."""
    with rasterio.open(src) as s:
        arr = s.read(1)
        crs, transform, nodata, dtype = s.crs, s.transform, s.nodata, s.dtypes[0]
        res = (abs(s.res[0]), abs(s.res[1]))
        src_hdr = {"driver": s.driver, "dtype": dtype, "nodata": None if nodata is None else (None if (isinstance(nodata, float) and np.isnan(nodata)) else float(nodata)),
                   "nodata_is_nan": bool(nodata is not None and isinstance(nodata, float) and np.isnan(nodata)),
                   "crs": s.crs.to_string() if s.crs else None, "tiled": s.is_tiled, "compression": str(s.compression.value) if s.compression else None,
                   "overviews": s.overviews(1), "shape": [s.height, s.width]}
    # --- CRS as an EPSG code
    epsg = crs.to_epsg() if crs else None
    if epsg is None and crs is not None and epsg_hint:
        if CRS.from_epsg(epsg_hint) == crs:
            epsg = epsg_hint
            fixes.append(f"{src.name}: CRS had no EPSG authority; matched the manifest target_crs EPSG:{epsg_hint}")
    if epsg is None and crs is None and epsg_hint:
        epsg = epsg_hint
        fixes.append(f"{src.name}: no CRS in the file; assigned the manifest target_crs EPSG:{epsg_hint}")
    if epsg is None:
        raise RuntimeError(f"{pid} {src.name}: CRS {crs} has no EPSG code and no usable hint")
    # --- dtype and nodata
    if kind == "mask":
        if dtype != "uint8":
            fixes.append(f"{src.name}: mask dtype {dtype} cast to uint8")
            arr = arr.astype(np.uint8)
        if nodata is None:
            nodata = 255
            fixes.append(f"{src.name}: mask had no nodata tag; set 255")
        nodata = int(nodata)
        vals = np.unique(arr)
        if not set(vals.tolist()) <= {0, 1, nodata}:
            raise RuntimeError(f"{pid} {src.name}: mask values {vals[:10]} are not in {{0,1,{nodata}}}")
        out_dtype, predictor, ovr = "uint8", 2, "NEAREST"
    else:
        if dtype != "float32":
            fixes.append(f"{src.name}: dtype {dtype} cast to float32")
            arr = arr.astype(np.float32)
        if nodata is None:
            nodata = float("nan")
            fixes.append(f"{src.name}: no nodata tag; set NaN (the file's invalid cells are NaN)")
        out_dtype, predictor, ovr = "float32", 3, "AVERAGE"
    # --- elevation convention check (grids only)
    stats = None
    if kind == "grid":
        valid = np.isfinite(arr) if (isinstance(nodata, float) and np.isnan(nodata)) else (np.isfinite(arr) & (arr != nodata))
        if valid.any():
            v = arr[valid].astype(np.float64)
            stats = {"n_valid": int(valid.sum()), "median_m": float(np.median(v)), "min_m": float(v.min()), "max_m": float(v.max()),
                     "positive_up": bool(np.median(v) < 0)}
    profile = dict(driver="COG", dtype=out_dtype, width=arr.shape[1], height=arr.shape[0], count=1, crs=CRS.from_epsg(epsg), transform=transform,
                   nodata=nodata, COMPRESS="DEFLATE", PREDICTOR=predictor, BLOCKSIZE=512, OVERVIEWS="IGNORE_EXISTING", OVERVIEW_RESAMPLING=ovr,
                   BIGTIFF="IF_SAFER", NUM_THREADS="ALL_CPUS")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    with rasterio.open(dst, "w", **profile) as d:
        d.write(arr, 1)
    with rasterio.open(dst) as d:
        hdr = {"dtype": d.dtypes[0], "crs_epsg": d.crs.to_epsg(), "nodata": ("nan" if (d.nodata is not None and np.isnan(d.nodata)) else d.nodata),
               "pixel_m": [abs(d.res[0]), abs(d.res[1])], "shape": [d.height, d.width], "bounds": list(d.bounds), "overviews": d.overviews(1),
               "compression": str(d.compression.value) if d.compression else None, "blocksize": [d.block_shapes[0][0], d.block_shapes[0][1]]}
    return {"source": src_hdr, "cog": hdr, "stats": stats, "bytes": dst.stat().st_size, "sha256": C.sha256(dst)}


# ----------------------------------------------------------------------------------------------------------------------
def _coreg(e: dict) -> dict:
    """The co-registration result as recorded for this pair (directive section 2.5), by group and record type."""
    m, R = e["manifest"] or {}, e["records"]
    out = {"case": "rigid", "dx_m": None, "dy_m": None, "dz_m": None, "offset_m": None, "qa": {}, "pass": None, "method": None, "source": None,
           "quadrant_groups": None, "n_tiles_dropped_boundary": 0, "status_recorded": m.get("coreg_status")}
    if e["group"] == "blind_test_2":
        sr = C.jload(Path(R["site_record"]))
        h = sr.get("harmonize", {})
        g, lc = h.get("coreg", {}), h.get("local_coreg", {})
        out.update(case=lc.get("case") or "rigid", dx_m=g.get("dx_m"), dy_m=g.get("dy_m"), dz_m=g.get("dz_m"), offset_m=g.get("offset_m"),
                   qa={"n": g.get("n"), "qa_components": h.get("qa_components"), "qa_pass": h.get("qa_pass"), "joint_area_km2": h.get("joint_area_km2"),
                       "n_valid_tiles_256": h.get("n_valid_tiles_256"), "case_pass": lc.get("case_pass"), "tolerance_m": lc.get("tolerance_m"), "rule": lc.get("rule")},
                   quadrant_groups=lc.get("groups"), quadrant_post_qa=lc.get("post_qa"), n_tiles_dropped_boundary=lc.get("n_tiles_dropped_boundary", 0),
                   **{"pass": bool(m.get("coreg_pass")) if m.get("coreg_pass") is not None else None},
                   method="ACQ-R13 local quadrant co-registration over the frozen rigid estimator (src/phase5/localcoreg_p5.py); drift case moves each quadrant group by whole HR pixels",
                   source="phase5_v4_1/harmonized/<pair>/site_record.json (harmonize.coreg, harmonize.local_coreg)")
        return out
    if "shift_vector" in R:
        sv = R["shift_vector"]
        out.update(dx_m=sv.get("dx_m"), dy_m=sv.get("dy_m"), dz_m=sv.get("dz_m"), offset_m=sv.get("horizontal_m"),
                   method="ACQ-R02 rigid xyz estimator; reviewed in QGIS under the seal (shift_vector.json)", source="harmonized_confirmatory/<unit>/<pair>/review/shift_vector.json")
    if "acq_r02" in R:
        c = R["acq_r02"].get("coreg", {})
        out.update(dx_m=out["dx_m"] if out["dx_m"] is not None else c.get("dx_m"), dy_m=out["dy_m"] if out["dy_m"] is not None else c.get("dy_m"),
                   dz_m=out["dz_m"] if out["dz_m"] is not None else c.get("dz_m"), offset_m=out["offset_m"] if out["offset_m"] is not None else c.get("offset_m"),
                   qa={"n": c.get("n"), "post_residual_mad_m": c.get("post_residual_mad_m"), "overlap_km2": R["acq_r02"].get("overlap_km2"),
                       "joint_area_km2": R["acq_r02"].get("joint_area_km2"), "n_valid_tiles_256": R["acq_r02"].get("n_valid_tiles_256"), "qa_pass": R["acq_r02"].get("qa_pass")},
                   **{"pass": c.get("pass")}, method=out["method"] or "ACQ-R02 rigid xyz estimator (src/acq_r01 chain; estimate_rigid_xyz)",
                   source=out["source"] or "reports_post_grl_review/ACQ-R02/harmonize/<pair>.json")
        return out
    if "stage_f5" in R and R["stage_f5"].get("recoreg"):
        f5, f = R["stage_f5"]["recoreg"], R.get("stage_f", {})
        rep = R.get("stage_f_repair", {})
        out.update(dx_m=f5.get("dx"), dy_m=f5.get("dy"), dz_m=f5.get("dz"), offset_m=f5.get("offset_m"),
                   qa={"psr": f5.get("psr"), "eig_ratio": f5.get("eig_ratio"), "peak_agrees": f5.get("peak_agrees"), "mad_m": f5.get("mad_m"),
                       "joint_valid_area_km2": R["stage_f5"].get("joint_valid_area_km2"), "n_valid_tiles": R["stage_f5"].get("n_valid_tiles"), "bucket": R["stage_f5"].get("bucket")},
                   initial_estimate={"dx_m": f.get("coreg_dx"), "dy_m": f.get("coreg_dy"), "dz_m": f.get("coreg_dz"), "offset_m": f.get("horiz_offset_m"), "psr": f.get("psr"), "source": "stage_f_results.json (first pass, superseded by the F5 re-co-registration)"} if f else None,
                   datum_repair={"dz_apply_m": rep.get("dz_apply"), "repair_mode": rep.get("repair_mode"), "status": rep.get("status"),
                                 "note": "June stage F repair: the HR grid was shifted vertically onto the ship datum; dz_m above includes that datum alignment where |dz| is thousands of metres"} if rep else None,
                   method="June stage F5 re-co-registration on the masked overlap: horizontal cross-correlation peak (PSR / eigen-ratio QA) and vertical median alignment to the ship grid; QGIS review R3 approved",
                   source="reports/discovery/stage_f5_results.json recoreg (+ stage_f_repair_results.json)")
        st = str(m.get("coreg_status") or "")
        out["pass"] = True if ("approved" in st or "signed_off" in st or st.startswith("pass")) else None
        return out
    if "stage_f" in R:
        f = R["stage_f"]
        rep = R.get("stage_f_repair", {})
        out.update(dx_m=f.get("coreg_dx"), dy_m=f.get("coreg_dy"), dz_m=f.get("coreg_dz"), offset_m=f.get("horiz_offset_m"),
                   qa={"psr": f.get("psr"), "eig_ratio": f.get("eig_ratio"), "peak_agrees": f.get("peak_agrees"), "coreg_mad_m": f.get("coreg_mad_m"), "overlap_km2": f.get("overlap_km2"), "status": f.get("status")},
                   datum_repair={"dz_apply_m": rep.get("dz_apply"), "repair_mode": rep.get("repair_mode"), "status": rep.get("status"),
                                 "note": "June stage F: the HR grid was shifted vertically to the ship datum; coreg dz includes that datum alignment"} if rep else None,
                   method="June stage F: horizontal cross-correlation peak (PSR / eigen-ratio QA) and vertical median alignment to the ship grid",
                   source="reports/discovery/stage_f_results.json (+ stage_f_repair_results.json)")
        st = str(m.get("coreg_status") or "")
        out["pass"] = True if ("approved" in st or "signed_off" in st or st.startswith("pass")) else None
        return out
    if "stage_c1" in R:
        c = R["stage_c1"].get("coreg", {})
        out.update(dx_m=c.get("dx"), dy_m=c.get("dy"), dz_m=c.get("dz"), offset_m=c.get("offset_m"),
                   qa={"n": c.get("n"), "post_mad_m": c.get("post_mad_m"), "overlap_km2": R["stage_c1"].get("overlap_km2"), "joint_area_km2": R["stage_c1"].get("joint_area_km2"), "n_valid_tiles": R["stage_c1"].get("n_valid_tiles")},
                   method="stage C1 masked rigid xyz estimator (re-harvested pairs); QGIS signed off 2026-06-26", source="reports/discovery/stage_c1_*.json")
        st = str(m.get("coreg_status") or "")
        out["pass"] = True if ("approved" in st or "signed_off" in st or st.startswith("pass")) else None
        return out
    if "notes_coreg" in R:
        n = R["notes_coreg"]
        out.update(dx_m=n["dx_m"], dy_m=n["dy_m"], dz_m=n["dz_m"], offset_m=float(np.hypot(n["dx_m"], n["dy_m"])),
                   qa={"psr": m.get("coreg_peak_psr"), "eig_ratio": m.get("coreg_peak_eig_ratio"), "peak_agrees": m.get("coreg_peak_agrees")},
                   method="M1 rigid offset of the AUV grid to the ship grid over the overlap (src/coregister.py)", source="manifest notes + coreg_* columns")
        return out
    # provider pairs and Cal DIG rows without a parsed note: manifest columns only
    out.update(offset_m=m.get("horiz_offset_m"), dz_m=m.get("vert_offset_m"),
               qa={"psr": m.get("coreg_peak_psr"), "eig_ratio": m.get("coreg_peak_eig_ratio"), "peak_agrees": m.get("coreg_peak_agrees")},
               method="M1 rigid offset of the AUV grid to the ship grid over the overlap (src/coregister.py); dx/dy not recorded separately",
               source="manifest columns horiz_offset_m / vert_offset_m / coreg_peak_*")
    return out


def _datum(e: dict) -> dict:
    g = e.get("datum_G")
    if g and g.get("G_V95_rel") is not None:
        return {"G_V95_rel": g["G_V95_rel"], "V95_m": g.get("V95_m"), "T_G": C.T_G, "pass": bool(g["G_V95_rel"] <= C.T_G), "source": g["source"],
                "definition": "V95_rel = 95th percentile of |HR - ship| over the joint-valid cells divided by the median ship depth (ACQ-R11b vcheck_p5.py); pass if <= T_G"}
    if e["group"] == "blind_test_2":
        sr = C.jload(Path(e["records"]["site_record"]))
        dc = sr.get("harmonize", {}).get("datum_check", {})
        return {"G_V95_rel": None, "T_G": C.T_G, "pass": dc.get("vertical_consistent"), "computed": dc.get("computed"),
                "source": "site_record.json harmonize.datum_check (the blind protocol recorded the boolean only; the value was never written)"}
    return {"G_V95_rel": None, "T_G": C.T_G, "pass": None, "source": "not computed for this pair (the datum check was introduced for the second blind test; development calibration covered the 38 v2.1 development pairs)"}


def _sources(e: dict, lic: dict) -> dict:
    m, rm = e["manifest"] or {}, e.get("raw_metadata") or {}
    per = lic["per_pair"][e["pair_id"]]
    ds = lic["datasets"]
    rows = [r for r in lic["rows"] if r["pair_id"] == e["pair_id"]]
    out = {}
    for side in ("hr", "lr"):
        r = next((x for x in rows if x["side"] == side), None)
        d = ds.get(r["id"], {}) if r else {}
        raw = rm.get(side, {})
        cite = raw.get("citation")
        if not cite and d.get("creators"):
            cite = f"{'; '.join(d['creators'])} ({d.get('year')}): {d.get('title')}. {d.get('publisher')}. https://doi.org/{d.get('doi')}"
        if not cite and r and r["provider"] == "NCEI":
            cite = f"NOAA National Centers for Environmental Information: {d.get('title') or 'Multibeam collection for ' + str(r.get('cruise'))}. NCEI Multibeam Bathymetry Database. {d.get('evidence')}"
        out[side] = {"dataset_id": r["id"] if r else None, "doi": d.get("doi") or raw.get("doi"), "title": d.get("title") or (e.get("mgds") or {}).get("title") if side == "hr" else d.get("title"),
                     "provider": r["provider"] if r else None, "landing_page": d.get("landing") or raw.get("landing_url"), "license": d.get("license"),
                     "license_evidence": d.get("evidence"), "redistribution": d.get("redistribution"), "citation": cite,
                     "cruise": (m.get("cruise_id") if side == "hr" else (m.get("lr_cruise") or m.get("cruise_id"))),
                     "platform": m.get(f"{side}_platform"), "sonar": m.get(f"{side}_sonar"), "acquisition_date": m.get("acquisition_date") if side == "hr" else None}
    if e["group"] == "blind_test_2":
        r8 = e.get("r08b", {})
        out["hr"].update(platform=out["hr"]["platform"] or _platform_from_title((e.get("mgds") or {}).get("title")), cruise=out["hr"]["cruise"] or _cruise_from_title((e.get("mgds") or {}).get("title")))
        out["lr"].update(cruise=r8.get("lr_cruise") or out["lr"]["cruise"], sonar=r8.get("lr_sonar") or out["lr"]["sonar"], acquisition_date=str(r8.get("lr_year")) if r8.get("lr_year") else None,
                         platform="ship (hull-mounted multibeam; NCEI survey " + str(r8.get("lr_cruise")) + ")")
    out["pair_license"] = per["pair_license"]
    out["pair_license_status"] = per["status"]
    return out


def _platform_from_title(t):
    if not t:
        return None
    for k in ("Sentry", "ABE", "MBARI Mapping AUV", "MBARI mapping AUV", "Jason", "Alvin"):
        if k.lower() in t.lower():
            return f"AUV {k}" if k in ("Sentry", "ABE") else k
    return "AUV (near-bottom; see dataset title)"


def _cruise_from_title(t):
    m = re.search(r"expedition\s+([A-Z]{2,4}\d{2,4}(?:-\d+)?[A-Z]?\d*)", t or "")
    return m.group(1) if m else None


def _k(e: dict) -> dict:
    m, s = e["manifest"] or {}, e.get("scoring") or {}
    return {"max_recoverable_k": C.nan_to_none(m.get("max_recoverable_k")), "status": m.get("k_sweep_status"),
            "k_in_scoring": C.nan_to_none(s.get("k")), "k_source": s.get("k_source"), "per_k_verdicts": s.get("per_k_verdicts"),
            "k_recoverable": (m.get("k_recoverable") if m.get("k_recoverable") is not None else (C.nan_to_none(m.get("max_recoverable_k")) is not None)),
            "definition": "largest k in {2,4,8,16,32} whose per-k spectral verdict is recoverable_signal (stage_c2c_recalibrate.sweep); no k = the pair is not scorable"}


def _flags(e: dict) -> dict:
    m, s = e["manifest"] or {}, e.get("scoring") or {}
    return {"unit_class": e["unit_class"], "artifact_class": {"ten": "real-relief unit", "six": "low-amplitude, artifact-affected unit", "EW0207": "scored separately (not in the ten/six sets)",
                                                               "confirmatory": "blind test 1, confirmatory", "lockbox": "blind test 1, lockbox", "candidate": "blind test 2 candidate"}[e["unit_class"]],
            "scoring_status": s.get("status"), "products_v2_1_flags": m.get("products_v2_1_flags") or "", "qa_status": m.get("qa_status"),
            "ship_products_usable": e["products_usable"], "ship_products_reason": e["products_reason"],
            "eligible": (bool(m["eligible"]) if m.get("eligible") is not None else (s.get("view") in ("interior", "fallback") if s else None)),
            "eligibility_reason": m.get("eligibility_reason") or (s.get("note") if s else None),
            "call_relief": s.get("call_relief"), "call_criteria": s.get("call_criteria"), "call_dominant": s.get("call_dominant"), "call_ab_whole_survey": s.get("call_ab_whole_survey")}


def _scoring(e: dict) -> dict | None:
    s = e.get("scoring")
    if not s:
        return None
    keys = ("view", "target", "bmin", "n_tiles_all", "n_scored", "n_interior", "blocks_interior", "n_fallback", "blocks_fallback", "amplitude_m", "rho_s_lr", "rho_all_s_lr", "rho_int_s_lr",
            "rho_GBT_ship", "rho_P-V1", "ci_lo_s_lr", "ci_hi_s_lr", "ci_estimable", "c1_condition", "status", "note", "cells_across", "thinner_than_development")
    return {k: C.nan_to_none(s.get(k)) for k in keys} | {"source": s.get("_source"), "rule": "Spearman rho of s_lr against A_fine on interior tiles if >= 10 tiles in >= bmin 4x4-tile blocks, else against A_fine_int on tiles with a defined A_fine_int (same counts); CNN phase4_score.py score_pair"}


def build_pair(args) -> dict:
    e, lic, force = args
    pid = e["pair_id"]
    st = C.STAGE / pid
    zpath = C.PKG / f"{pid}.zip"
    fixes: list[str] = []
    m = e["manifest"] or {}
    epsg_hint = C.epsg_int(m.get("target_crs"))
    files: dict[str, dict] = {}
    headers: dict[str, dict] = {}
    for k in GRIDS + MASKS:
        info = to_cog(Path(e["rasters"][k]), st / f"{k}.tif", "mask" if k in MASKS else "grid", epsg_hint, pid, fixes)
        files[f"{k}.tif"] = {"sha256": info["sha256"], "bytes": info["bytes"]}
        headers[k] = info
    epsgs = {headers[k]["cog"]["crs_epsg"] for k in GRIDS + MASKS}
    if len(epsgs) != 1:
        raise RuntimeError(f"{pid}: rasters on different CRS {epsgs}")
    if e["products_dir"]:
        pd_ = Path(e["products_dir"])
        for name in PRODUCT_RASTERS:
            src = pd_ / f"{name}.tif"
            if src.exists():
                info = to_cog(src, st / "ship_products" / f"{name}.tif", "product", epsg_hint, pid, fixes)
                files[f"ship_products/{name}.tif"] = {"sha256": info["sha256"], "bytes": info["bytes"]}
                headers[f"ship_products/{name}"] = {"cog": info["cog"]}
        for name in PRODUCT_SIDE:
            src = pd_ / name
            if src.exists():
                dst = st / "ship_products" / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                if name.endswith(".json"):
                    C.jdump(_scrub(C.jload(src)), dst)
                else:
                    shutil.copyfile(src, dst)
                files[f"ship_products/{name}"] = {"sha256": C.sha256(dst), "bytes": dst.stat().st_size}
    hr_px, lr_px = headers["hr"]["cog"]["pixel_m"][0], headers["lr"]["cog"]["pixel_m"][0]
    hr_native = C.nan_to_none(m.get("hr_native_res_m"))
    if hr_native is not None and abs(hr_px - hr_native) > 0.05 * max(hr_native, 1e-6):
        fixes.append(f"hr.tif pixel {hr_px:.4f} m differs from the manifest hr_native_res_m {hr_native}; hr_res records the as-used pixel")
    pj = {
        "release": {"version": C.RELEASE_VERSION, "directive": C.DIRECTIVE_ID, "generated": C.utcnow(), "paper": C.PAPER_ID},
        "identifiers": {"pair_id": pid, "unit": e["unit"], "role": e["role"], "group": e["group"], "site_name": m.get("site_name"), "region": m.get("region"),
                        "terrain_class": m.get("terrain_class")},
        "sources": _sources(e, lic),
        "grids": {"hr_res": hr_px, "hr_native_res_m": hr_native, "lr_native": C.nan_to_none(m.get("lr_native_res_m")), "lr_pixel_m": lr_px,
                  "res_ratio": (C.nan_to_none(m.get("lr_native_res_m")) / hr_px) if C.nan_to_none(m.get("lr_native_res_m")) else None,
                  "crs_epsg": headers["hr"]["cog"]["crs_epsg"], "crs": f"EPSG:{headers['hr']['cog']['crs_epsg']}",
                  "vertical_reference": _vertical_reference(e), "elevation_units": "metres, positive up (seafloor depths are negative)",
                  "nodata": {k: headers[k]["cog"]["nodata"] for k in GRIDS + MASKS}, "mask_grid": "all three masks are on the HR grid (lr_valid = isfinite(lr) resampled nearest to the HR lattice)",
                  "headers": {k: headers[k]["cog"] for k in headers}, "stats": {k: headers[k]["stats"] for k in GRIDS},
                  "source_headers": {k: headers[k]["source"] for k in GRIDS + MASKS}},
        "k": _k(e), "coregistration": _coreg(e), "datum_check": _datum(e), "flags": _flags(e), "scoring": _scoring(e),
        "provenance_records": {k: (v if isinstance(v, dict) else os.path.relpath(v, C.OAK)) for k, v in e["records"].items() if k not in ("stage_f", "stage_f5", "stage_f_repair", "stage_c1", "acq_r02", "notes_coreg")},
        "files": files,
    }
    sign_bad = [k for k in GRIDS if pj["grids"]["stats"][k] and not pj["grids"]["stats"][k]["positive_up"]]
    if sign_bad:
        pj["flags"]["sign_convention_suspect"] = sign_bad
        fixes.append(f"median elevation is positive in {sign_bad}: check sign convention (values left unchanged)")
    pj["build_fixes"] = fixes
    C.jdump(pj, st / "pair.json")
    # --- zip (stored; the COGs are already DEFLATE-compressed)
    C.PKG.mkdir(parents=True, exist_ok=True)
    tmp = zpath.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
        for rel in sorted(files) + ["pair.json"]:
            z.write(st / rel, arcname=rel)
    os.replace(tmp, zpath)
    return {"pair_id": pid, "group": e["group"], "zip": str(zpath), "zip_bytes": zpath.stat().st_size, "zip_sha256": C.sha256(zpath), "n_files": len(files) + 1,
            "fixes": fixes, "pair_json": pj}


def _vertical_reference(e: dict) -> str:
    m = e["manifest"] or {}
    vd = m.get("vertical_datum")
    if e["group"] == "blind_test_2":
        return "ship-grid vertical reference (NCEI swath, sound-speed-corrected depth below the transducer/sea surface as delivered); the AUV grid was shifted by the co-registration dz to the ship grid; datum consistency tested by the G statistic"
    if vd:
        return f"{vd}: elevation relative to the source grid's vertical reference (MSL / sea surface as delivered by the provider), negative down; HR shifted to the ship grid by the co-registration dz"
    return "as delivered by the sources (sea-surface / MSL referenced depths, negative down); HR shifted to the ship grid by the co-registration dz"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pairs", nargs="*")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    inv, lic = C.jload(C.INVENTORY), C.jload(C.LICENSE_AUDIT)
    done = C.jload(BUILD_RESULTS) if BUILD_RESULTS.exists() and not a.force else {"pairs": {}}
    todo = [e for e in inv["entries"] if e["in_corpus"] and (not a.pairs or e["pair_id"] in a.pairs)]
    todo = [e for e in todo if a.force or e["pair_id"] not in done["pairs"] or not Path(done["pairs"][e["pair_id"]]["zip"]).exists()]
    C.log(f"build: {len(todo)} pairs to build with {a.workers} workers (already done: {len(done['pairs'])})")
    C.STAGE.mkdir(parents=True, exist_ok=True)
    errors = {}
    with Pool(a.workers) as pool:
        for res in pool.imap_unordered(_safe, [(e, lic, a.force) for e in todo]):
            if "error" in res:
                errors[res["pair_id"]] = res["error"]
                C.log(f"  ERROR {res['pair_id']}: {res['error']}")
                continue
            done["pairs"][res["pair_id"]] = res
            for fx in res["fixes"]:
                C.fix("build", res["pair_id"], fx)
            C.log(f"  {res['pair_id']:48s} {res['zip_bytes'] / 1e6:8.1f} MB  {res['n_files']} files")
            C.jdump(done, BUILD_RESULTS)
    done["generated"] = C.utcnow()
    C.jdump(done, BUILD_RESULTS)
    tot = sum(v["zip_bytes"] for v in done["pairs"].values())
    C.log(f"build: {len(done['pairs'])} zips, {tot / 1e9:.2f} GB; errors: {errors}")
    if errors:
        raise SystemExit(1)


def _safe(args):
    try:
        return build_pair(args)
    except Exception as ex:  # reported, then the run stops after the pool drains
        import traceback
        return {"pair_id": args[0]["pair_id"], "error": f"{type(ex).__name__}: {ex}\n{traceback.format_exc()[-800:]}"}


if __name__ == "__main__":
    main()
