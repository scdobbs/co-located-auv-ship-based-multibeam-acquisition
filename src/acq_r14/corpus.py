"""ACQ-R14 step 4: corpus-level files (directive section 3) written into the package next to the pair zips:
pairs.parquet/csv, tiles.parquet/csv (frozen CNN-repo scoring inputs, concatenated, never recomputed), blind_tests/
(+ blind_tests.zip for Zenodo's flat file list), README.md, DATA_DICTIONARY.md, CITATION.cff, LICENSE,
SOURCE_LICENSES.csv, examples/load_pair.py, zenodo_metadata.json and SHA256SUMS (last).

    python -B -m src.acq_r14.corpus
"""
from __future__ import annotations
import csv, json, os, shutil, subprocess, zipfile
from collections import Counter
from pathlib import Path
import numpy as np, pandas as pd
from . import common as C
from .build import BUILD_RESULTS

HERE = Path(__file__).resolve().parent
TILE_SOURCES = {"development": C.ARCH / "R10b/rehearsal/score_inputs/inputs_D1.parquet",
                "blind_test_1": C.ARCH / "phase4/score_inputs/inputs_D1.parquet",
                "blind_test_2": C.ARCH / "phase5/scores/inputs_D1.parquet"}
TILES_V1_1 = {"development": C.CNN / "R05/tiles/tiles_v1_1.parquet"}
EXCLUSIONS = C.CNN / "R17/exclusions_phase5_r17.json"
BLIND_FILES = [  # (source, destination name, note)
    (C.CNN / "R12c/PREREG_phase4_v2_1.md", "phase4_PREREG_v2_1.md", "blind test 1 pre-registration v2.1 (git tag phase4-prereg-v2.1)"),
    (C.CNN / "R12c/SIGNOFF_phase4_prereg_v2_1.md", "phase4_SIGNOFF_prereg_v2_1.md", "sign-off of the v2.1 pre-registration"),
    (C.CNN / "R16c/PREREG_phase5_v3_1.md", "phase5_PREREG_v3_1.md", "blind test 2 pre-registration v3.1 (git tag phase5-prereg-v3.1)"),
    (C.CNN / "R16c/SIGNOFF_phase5_prereg_v3_1.md", "phase5_SIGNOFF_prereg_v3_1.md", "sign-off of the v3.1 pre-registration"),
    (C.CNN / "R13/phase4_calls.csv", "phase4_calls.csv", "Steve's committed blind calls, blind test 1 (keyed by Q-code; commit 79802aa, before prediction)"),
    (C.ARCH / "phase4/figures/key/figset_A_key.json", "phase4_calls_key.json", "Q-code -> pair key for phase4_calls.csv"),
    (C.CNN / "R18/phase5_calls.csv", "phase5_calls.csv", "Steve's committed blind calls, blind test 2 (keyed by Q-code; commit fceab82)"),
    (C.ARCH / "phase5/figures/key/figset_A_key.json", "phase5_calls_key.json", "Q-code -> pair key for phase5_calls.csv"),
    (C.CNN / "R11/DEVIATION_phase4_01.md", "phase4_DEVIATION_01.md", "deviation note"),
    (C.CNN / "R11/DEVIATION_phase4_02.md", "phase4_DEVIATION_02.md", "deviation note"),
    (C.CNN / "R12c/DEVIATION_phase4_03.md", "phase4_DEVIATION_03.md", "deviation note"),
    (C.CNN / "R13/DEVIATION_phase4_04.md", "phase4_DEVIATION_04.md", "deviation note"),
    (C.CNN / "phase5/DEVIATIONS_phase5.md", "phase5_DEVIATIONS.md", "deviation notes, blind test 2 (seven items)"),
    (C.ARCH / "phase4/scores/results_D1.json", "phase4_results_D1.json", "blind test 1 scoring output (frozen)"),
    (C.ARCH / "phase4/scores/per_pair_D1.csv", "phase4_per_pair_D1.csv", "blind test 1 per-pair scores (frozen)"),
    (C.ARCH / "phase5/scores/results_D1.json", "phase5_results_D1.json", "blind test 2 scoring output (frozen; byte-identical to the committed R18/tables copy)"),
    (C.ARCH / "phase5/scores/per_pair_D1.csv", "phase5_per_pair_D1.csv", "blind test 2 per-pair scores (frozen)"),
    (EXCLUSIONS, "phase5_exclusions_r17.json", "the 22 Escanaba tiles excluded under the R17 H1 ruling (boundary-zeroed lattice tiles)"),
]
DEV_SCORES = C.ARCH / "R11/rehearsal/scores/per_pair_D1.csv"

PAIR_COLS = {  # pairs table: column -> (description, units)
    "pair_id": ("pair identifier: <ship cruise>__MGDS_<HR data set uid>, or a provider site id", ""),
    "group": ("development | blind_test_1 | blind_test_2 | excluded", ""),
    "role": ("development, development (EW0207, scored separately), confirmatory, lockbox, candidate, or the exclusion kind", ""),
    "unit": ("leakage unit (units-v1 for development; nu/lu for blind test 1; p5u for blind test 2)", ""),
    "unit_class": ("ten (real-relief unit) | six (low-amplitude, artifact-affected unit) | EW0207 | confirmatory | lockbox | candidate", ""),
    "in_corpus": ("True if the pair ships with rasters (<pair_id>.zip)", ""),
    "exclusion_reason": ("why a row has no rasters", ""),
    "site_name": ("site name", ""), "region": ("region", ""), "terrain_class": ("terrain class (controlled vocabulary)", ""),
    "hr_dataset_id": ("HR source data set (MGDS:<uid> or DOI)", ""), "hr_doi": ("HR DOI", ""), "hr_title": ("HR data set title", ""),
    "hr_cruise": ("HR acquisition cruise", ""), "hr_platform": ("HR platform (AUV)", ""), "hr_sonar": ("HR sonar", ""), "hr_license": ("HR source license (landing-page metadata)", ""),
    "lr_dataset_id": ("LR source (NCEI:<survey> or DOI)", ""), "lr_doi": ("LR DOI (provider grids only)", ""), "lr_cruise": ("ship cruise / NCEI survey", ""),
    "lr_platform": ("ship platform", ""), "lr_sonar": ("ship sonar", ""), "lr_license": ("LR source license", ""),
    "pair_license": ("license of the released pair: CC BY-NC-SA 4.0 for every pair (the whole record is CC BY-NC-SA 4.0)", ""),
    "pair_license_status": ("source audit: yes (all sources CC BY / public domain) | yes_conditional (a source is CC BY-NC-SA) | confirm", ""),
    "sources_cc_by_or_public_domain_only": ("True if every source data set of the pair is CC BY, CC0 or public domain (reusable under those terms from the sources)", ""),
    "hr_res": ("HR pixel of hr.tif as used", "m"), "hr_native_res_m": ("HR native resolution from the manifest", "m"),
    "lr_native": ("ship native cell by the C2a rule, max(beam footprint, posting)", "m"), "lr_pixel_m": ("pixel of lr.tif", "m"),
    "res_ratio": ("lr_native / hr_res", ""), "crs_epsg": ("projected CRS of all rasters of the pair", "EPSG code"),
    "vertical_reference": ("vertical reference statement", ""),
    "k": ("max recoverable super-resolution factor (2..32), empty if none", ""), "k_status": ("k sweep status", ""),
    "coreg_case": ("rigid | drift (blind test 2 local co-registration)", ""), "coreg_dx_m": ("HR -> ship shift, easting", "m"), "coreg_dy_m": ("HR -> ship shift, northing", "m"),
    "coreg_dz_m": ("HR -> ship vertical shift (includes the datum alignment where |dz| is thousands of meters)", "m"), "coreg_offset_m": ("horizontal shift magnitude", "m"),
    "coreg_pass": ("co-registration accepted (True), or empty where only a status string was recorded", ""), "coreg_status": ("recorded co-registration status", ""),
    "coreg_n_quadrant_groups": ("blind test 2: quadrant groups used", ""), "coreg_tiles_dropped_boundary": ("blind test 2 drift case: lattice tiles zeroed at group boundaries", ""),
    "datum_G": ("G = V95_rel datum statistic (development pairs)", ""), "datum_pass": ("G <= T_G (0.200712), or the recorded boolean (blind test 2)", ""),
    "ship_products_usable": ("contract v2.1 per-sounding ship products shipped", ""), "ship_products_reason": ("why not, or flags", ""),
    "products_v2_1_flags": ("contract v2.1 flags (vertical_offset, registration_shift, ...)", ""),
    "artifact_class": ("real-relief / low-amplitude artifact-affected / other", ""), "scoring_status": ("frozen per-pair status (in C1, in C1 (flagged), artifact-dominated, low-amplitude artifact-affected, not scorable, not testable)", ""),
    "eligible": ("eligible for the test's C1 criterion", ""), "eligibility_reason": ("reason when not eligible / not testable", ""),
    "view": ("interior | fallback | not_scorable (frozen scorer view)", ""), "target": ("A_fine | A_fine_int", ""), "bmin": ("minimum number of 4x4-tile blocks for a view", ""),
    "n_tiles": ("tiles with a finite A_fine", ""), "n_scored": ("tiles in the view", ""), "amplitude_m": ("median target amplitude over the view", "m"),
    "rho_s_lr": ("frozen Spearman rho of s_lr vs target over the view", ""), "rho_s_lr_ci_lo": ("block-bootstrap 95 % CI, lower", ""), "rho_s_lr_ci_hi": ("upper", ""),
    "rho_GBT_ship": ("frozen rho of the GBT_ship prediction", ""), "rho_P_V1": ("frozen rho of the P-V1 prediction", ""),
    "call_relief": ("Steve's blind call: relief visible", ""), "call_criteria": ("artifact criteria called (a, b, c)", ""), "call_dominant": ("dominant pattern called", ""), "call_ab_whole_survey": ("a/b artifact over the whole survey", ""),
    "zip_file": ("<pair_id>.zip", ""), "zip_bytes": ("zip size", "bytes"), "zip_sha256": ("sha256 of the zip", ""), "n_files_in_zip": ("files in the zip", ""),
}
TILE_COLS = {
    "tile_id": ("<pair>_r<r0>_c<c0>; unique", ""), "pair": ("pair_id", ""), "unit": ("leakage unit", ""), "group": ("development | blind_test_1 | blind_test_2", ""),
    "unit_class": ("ten | six | EW0207 | confirmatory | lockbox | candidate", ""), "role": ("row role in the frozen scoring input", ""),
    "r0": ("row of the 256-px window's top-left corner on the HR grid", "HR px"), "c0": ("column of the window corner", "HR px"),
    "tr0": ("row of the scored 128-px tile corner (= r0 + 64)", "HR px"), "tc0": ("column of the tile corner", "HR px"),
    "size_px": ("tile size", "HR px"), "left": ("tile bounds in the pair CRS", "m"), "bottom": ("", "m"), "right": ("", "m"), "top": ("", "m"),
    "block_id": ("bootstrap block <pair>_b<r0//512>_<c0//512> (4x4 tiles; CNN phase4_score.py blocks_of)", ""), "block_r": ("r0 // 128 // 4", ""), "block_c": ("c0 // 128 // 4", ""),
    "interior": ("interior tile: >= 95 % of its joint px are >= D1 = ceil(lr_native/hr_res) px from any invalid px", ""),
    "excluded_r17": ("one of the 22 Escanaba tiles excluded by the R17 H1 ruling (dropped before scoring)", ""),
    "A_fine": ("RMS of the band-passed HR field over the tile's joint px (target)", "m"), "A_fine_int": ("the same over interior px only; NaN if < 2048 interior px", "m"),
    "s_lr": ("ship-only feature: max(std of valid ship cells in the 256-px window, 0.5)", "m"),
    "GBT_ship": ("held-out GBT_ship prediction of A_fine", "m"), "P-V1": ("held-out P-V1 (CNN, seed average) prediction of A_fine", "m"),
    "hr_res": ("HR pixel", "m"), "lr_native": ("ship native cell", "m"), "k": ("pair k", ""),
}


def _pair_row(pj: dict, br: dict) -> dict:
    s, g, k, cr, dt, fl, sc = pj["sources"], pj["grids"], pj["k"], pj["coregistration"], pj["datum_check"], pj["flags"], pj.get("scoring") or {}
    idn = pj["identifiers"]
    return {"pair_id": idn["pair_id"], "group": idn["group"], "role": idn["role"], "unit": idn["unit"], "unit_class": fl["unit_class"], "in_corpus": True, "exclusion_reason": None,
            "site_name": idn.get("site_name"), "region": idn.get("region"), "terrain_class": idn.get("terrain_class"),
            "hr_dataset_id": s["hr"]["dataset_id"], "hr_doi": s["hr"]["doi"], "hr_title": s["hr"]["title"], "hr_cruise": s["hr"]["cruise"], "hr_platform": s["hr"]["platform"], "hr_sonar": s["hr"]["sonar"], "hr_license": s["hr"]["license"],
            "lr_dataset_id": s["lr"]["dataset_id"], "lr_doi": s["lr"]["doi"], "lr_cruise": s["lr"]["cruise"], "lr_platform": s["lr"]["platform"], "lr_sonar": s["lr"]["sonar"], "lr_license": s["lr"]["license"],
            "pair_license": s["pair_license"], "pair_license_status": s["pair_license_status"], "sources_cc_by_or_public_domain_only": s.get("sources_cc_by_or_public_domain_only"),
            "hr_res": g["hr_res"], "hr_native_res_m": g["hr_native_res_m"], "lr_native": g["lr_native"], "lr_pixel_m": g["lr_pixel_m"], "res_ratio": g["res_ratio"], "crs_epsg": g["crs_epsg"], "vertical_reference": g["vertical_reference"],
            "k": k["max_recoverable_k"], "k_status": k["status"],
            "coreg_case": cr["case"], "coreg_dx_m": cr["dx_m"], "coreg_dy_m": cr["dy_m"], "coreg_dz_m": cr["dz_m"], "coreg_offset_m": cr["offset_m"], "coreg_pass": cr["pass"], "coreg_status": cr["status_recorded"],
            "coreg_n_quadrant_groups": (len(cr["quadrant_groups"]) if cr.get("quadrant_groups") else None), "coreg_tiles_dropped_boundary": cr.get("n_tiles_dropped_boundary"),
            "datum_G": dt.get("G_V95_rel"), "datum_pass": dt.get("pass"),
            "ship_products_usable": fl["ship_products_usable"], "ship_products_reason": fl["ship_products_reason"], "products_v2_1_flags": fl["products_v2_1_flags"],
            "artifact_class": fl["artifact_class"], "scoring_status": fl["scoring_status"], "eligible": fl["eligible"], "eligibility_reason": fl["eligibility_reason"],
            "view": sc.get("view"), "target": sc.get("target"), "bmin": sc.get("bmin"), "n_tiles": sc.get("n_tiles_all"), "n_scored": sc.get("n_scored"), "amplitude_m": sc.get("amplitude_m"),
            "rho_s_lr": sc.get("rho_s_lr"), "rho_s_lr_ci_lo": sc.get("ci_lo_s_lr"), "rho_s_lr_ci_hi": sc.get("ci_hi_s_lr"), "rho_GBT_ship": sc.get("rho_GBT_ship"), "rho_P_V1": sc.get("rho_P-V1"),
            "call_relief": fl.get("call_relief"), "call_criteria": fl.get("call_criteria"), "call_dominant": fl.get("call_dominant"), "call_ab_whole_survey": fl.get("call_ab_whole_survey"),
            "zip_file": Path(br["zip"]).name, "zip_bytes": br["zip_bytes"], "zip_sha256": br["zip_sha256"], "n_files_in_zip": br["n_files"]}


def _excluded_row(e: dict) -> dict:
    m = e.get("manifest") or {}
    r = {c: None for c in PAIR_COLS}
    r.update(pair_id=e["pair_id"], group="excluded", role=e["role"], unit=e.get("unit"), in_corpus=False, exclusion_reason=e["exclusion_reason"],
             site_name=m.get("site_name"), region=m.get("region"), terrain_class=m.get("terrain_class"), hr_dataset_id=m.get("hr_doi"), lr_cruise=m.get("lr_cruise") or m.get("cruise_id"),
             hr_native_res_m=C.nan_to_none(m.get("hr_native_res_m")), lr_native=C.nan_to_none(m.get("lr_native_res_m")), k=C.nan_to_none(m.get("max_recoverable_k")), k_status=m.get("k_sweep_status"),
             coreg_offset_m=C.nan_to_none(m.get("horiz_offset_m")), coreg_dz_m=C.nan_to_none(m.get("vert_offset_m")), coreg_status=m.get("coreg_status"))
    return r


def pairs_table(inv, build):
    rows = []
    for e in inv["entries"]:
        if e["in_corpus"]:
            br = build["pairs"][e["pair_id"]]
            rows.append(_pair_row(br["pair_json"], br))
        else:
            rows.append(_excluded_row(e))
    df = pd.DataFrame(rows, columns=list(PAIR_COLS))
    df.to_parquet(C.PKG / "pairs.parquet", index=False)
    df.to_csv(C.PKG / "pairs.csv", index=False)
    return df


def tiles_table(inv):
    cls = {e["pair_id"]: e["unit_class"] for e in inv["entries"]}
    excl = set()
    ex = C.jload(EXCLUSIONS)

    def walk(o):
        if isinstance(o, dict):
            if "tile_id" in o:
                excl.add(o["tile_id"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(ex)
    parts = []
    for group, p in TILE_SOURCES.items():
        d = pd.read_parquet(p)
        d["group"] = group
        if "role" not in d:
            d["role"] = None
        parts.append(d)
    t = pd.concat(parts, ignore_index=True, sort=False)
    t["unit_class"] = t.pair.map(cls)
    t["excluded_r17"] = t.tile_id.isin(excl)
    t["block_r"], t["block_c"] = t.r0 // 128 // 4, t.c0 // 128 // 4
    t["block_id"] = [f"{p}_b{r:03d}_{c:03d}" for p, r, c in zip(t.pair, t.block_r, t.block_c)]
    # geometry columns from the frozen tiles_v1_1 tables
    geo = [pd.read_parquet(TILES_V1_1["development"], columns=["tile_id", "tr0", "tc0", "size_px", "left", "bottom", "right", "top", "k"])]
    for ph in ("phase4", "phase5"):
        for d in sorted((C.ARCH / ph / "build").glob("*__MGDS_*")):
            f = d / "tiles_v1_1.parquet"
            if f.exists():
                geo.append(pd.read_parquet(f, columns=["tile_id", "tr0", "tc0", "size_px", "left", "bottom", "right", "top", "k"]))
    geo = pd.concat(geo, ignore_index=True).drop_duplicates("tile_id")
    t = t.merge(geo, on="tile_id", how="left")
    miss = int(t.tr0.isna().sum())
    if miss:
        C.fix("corpus", None, f"{miss} tiles have no tiles_v1_1 geometry row; tr0/tc0 filled as r0+64/c0+64, bounds left empty")
        t["tr0"] = t.tr0.fillna(t.r0 + 64)
        t["tc0"] = t.tc0.fillna(t.c0 + 64)
    bad = int(((t.tr0 - t.r0) != 64).sum())
    if bad:
        C.fix("corpus", None, f"{bad} tiles have tr0 != r0 + 64 in tiles_v1_1 (kept as recorded)")
    assert t.tile_id.is_unique, "tile_id not unique across groups"
    t = t[list(TILE_COLS)]
    t.to_parquet(C.PKG / "tiles.parquet", index=False)
    t.to_csv(C.PKG / "tiles.csv", index=False)
    return t, len(excl)


def blind_tests():
    d = C.PKG / "blind_tests"
    d.mkdir(parents=True, exist_ok=True)
    index = []
    for src, name, note in BLIND_FILES:
        if not src.exists():
            raise SystemExit(f"blind test file missing: {src}")
        shutil.copyfile(src, d / name)
        index.append({"file": name, "origin": str(src).replace(str(C.CNN), "<CNN repo>/grl_reviews-and-prompt-reports/directives_and_reports").replace(str(C.ARCH), "<OAK>/grl_review_archive"),
                      "sha256": C.sha256(d / name), "bytes": (d / name).stat().st_size, "note": note})
    with open(d / "INDEX.md", "w") as f:
        f.write("# blind_tests/ index\n\nFrozen pre-registrations, committed calls, deviation notes and scoring outputs of the two blind tests. "
                "Nothing here was recomputed for the release; sha256 values are of the copies in this folder.\n\n| file | origin | sha256 | note |\n|---|---|---|---|\n")
        for r in index:
            f.write(f"| {r['file']} | {r['origin']} | {r['sha256']} | {r['note']} |\n")
    shutil.copyfile(DEV_SCORES, C.PKG / "development_scores_per_pair_D1.csv")
    with zipfile.ZipFile(C.PKG / "blind_tests.zip", "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(d.iterdir()):
            z.write(p, arcname=f"blind_tests/{p.name}")
    return index


def write_docs(inv, pairs: pd.DataFrame, n_tiles: int, n_excl: int, lic: dict):
    inc = pairs[pairs.in_corpus]
    n_dev, n_b1, n_b2 = (inc.group == "development").sum(), (inc.group == "blind_test_1").sum(), (inc.group == "blind_test_2").sum()
    n_ncsa = (inc.pair_license_status == "yes_conditional").sum()
    n_conf = (inc.pair_license_status == "confirm").sum()
    n_open = int(inc.sources_cc_by_or_public_domain_only.fillna(False).astype(bool).sum())
    tot_gb = inc.zip_bytes.sum() / 1e9
    conf_pairs = ", ".join(inc[inc.pair_license_status == "confirm"].pair_id)
    short = {}
    for k, d in lic["datasets"].items():
        l = d["license"].lower()
        short[k] = ("CC BY-NC-SA" if "noncommercial" in l.replace(" ", "").replace("-", "") or "by-nc-sa" in l else "CC0 / public domain" if ("public domain" in l or "cc0" in l)
                    else "CC BY" if "attribution" in l else d["license"][:40])
    src_rows = []
    for e in inv["entries"]:
        if not e["in_corpus"]:
            continue
        ids = {r["side"]: r["id"] for r in lic["rows"] if r["pair_id"] == e["pair_id"]}
        src_rows.append((e["pair_id"], e["group"], ids.get("hr"), short.get(ids.get("hr"), "?"), ids.get("lr"), short.get(ids.get("lr"), "?"),
                         "yes" if lic["per_pair"][e["pair_id"]]["sources_cc_by_or_public_domain_only"] else "no"))
    src_table = "\n".join(f"| {p} | {g} | {hid} | {hl} | {lid} | {ll} | {o} |" for p, g, hid, hl, lid, ll, o in src_rows)
    n_hr_mismatch = int(((inc.hr_res - inc.hr_native_res_m).abs() > 0.05 * inc.hr_native_res_m.clip(lower=1e-6)).sum())
    readme = f"""# Co-located ship and AUV multibeam bathymetry corpus (processed grids, masks, co-registration and tile tables)

Release {C.RELEASE_VERSION} (acquisition directive {C.DIRECTIVE_ID}, 2026-10-20). Companion data release of the GRL paper {C.PAPER_ID}.

## What this corpus is

Each pair is one patch of seafloor measured twice by independent instruments: a near-bottom AUV multibeam grid (HR, about 1-2 m
pixels) and a hull-mounted ship multibeam grid (LR, about 10-150 m native cells) over the same footprint. The ship grid is a real
measurement, never a downsampled copy of the AUV grid. The corpus holds {len(inc)} pairs with rasters:

| group | pairs | content |
|---|---|---|
| development | {n_dev} | the 16 units-v1 leakage units (38 pairs) plus EW0207 (lu16, scored separately); ten real-relief units and six low-amplitude, artifact-affected units (`unit_class`) |
| blind_test_1 | {n_b1} | 3 confirmatory units (KN182L03 has no recoverable k and no scored tiles) and 2 lockbox pairs |
| blind_test_2 | {n_b2} | all 8 candidate sites, including the 3 that were not testable (`eligibility_reason` names the rule that failed) |

`pairs.csv` also lists {int((~pairs.in_corpus).sum())} rows without rasters (dropped pairs such as AT37-05, Chapopote, Venere and the two
Amundsen pairs, the restricted Kolumbo site, and no-k pairs) with their reason in `exclusion_reason`.

Raw swath, intermediate gridding products, band-passed fields and model checkpoints are not included.

## The two anti-circularity rules

1. **The low-resolution input is never derived from the high-resolution target.** `lr.tif` is the ship grid as delivered by
   the provider or gridded from the NCEI raw swath; it is reprojected and clipped only. No pair's LR was made by degrading its HR.
2. **Nothing in the corpus comes from a compilation that ingests the AUV grids.** GEBCO, GMRT, SRTM-style compilations and
   regional syntheses are excluded on both sides; every LR grid is the single-cruise ship survey named in `lr_dataset_id`.

The scored feature `s_lr` is computed from `lr.tif` alone; the target `A_fine` from `hr.tif` alone (see DATA_DICTIONARY.md).

## Folder layout

```
<pair_id>.zip              one per pair (stored, not compressed: the COGs are DEFLATE-compressed internally)
  hr.tif                   AUV grid as used (after harmonization and co-registration), native resolution, float32 COG
  lr.tif                   ship grid as used, native cell size, same CRS, float32 COG
  hr_valid.tif             validity masks as used (uint8, 1 = valid, 0 = invalid, nodata 255), on the HR grid;
  lr_valid.tif             joint_valid includes the ACQ-R13 boundary zeroing for drift-case sites
  joint_valid.tif
  ship_products/           contract v2.1 per-sounding ship product rasters (ship_count, ship_sd, ship_rsd, ship_xtrack_frac,
                           ship_beam_angle, ship_mean_regrid, ship_median_regrid) + products.json, only where usable
  pair.json                identifiers, sources (DOI, cruise, platform, sonar, license, citation), hr_res / lr_native, k,
                           co-registration result and QA, datum statistic G, flags, eligibility, frozen scores, sha256 of every file
pairs.parquet / pairs.csv  one row per pair (the pair.json fields that fit a table)
tiles.parquet / tiles.csv  one row per scored tile: pair, window/tile coordinates, block id, interior flag, excluded_r17 flag,
                           A_fine, A_fine_int, s_lr, held-out GBT_ship and P-V1 predictions (frozen CNN-repo outputs)
development_scores_per_pair_D1.csv   frozen per-pair development scores (the rho values that load_pair.py reproduces)
blind_tests/ (+ blind_tests.zip)     pre-registrations v2.1 and v3.1, Steve's committed calls, deviation notes,
                                     Phase 4 and Phase 5 results_D1.json and per_pair_D1.csv, the R17 exclusion list
examples/load_pair.py      opens one pair's grids and tile rows and reproduces that pair's s_lr rho
DATA_DICTIONARY.md         every field, with units
SOURCE_LICENSES.csv        license audit of every source data set (DataCite / NCEI / USGS metadata)
CITATION.cff, LICENSE, SHA256SUMS
```

All rasters: Cloud-Optimized GeoTIFF, DEFLATE with predictor, internal overviews, the pair's projected CRS as an EPSG code
(local UTM), explicit nodata (NaN or -9999 for grids, as used; 255 for masks). Elevations are in meters, positive up (seafloor
depths are negative); the vertical reference is stated per pair in `pair.json` (`grids.vertical_reference`). The masks are on the
HR grid; `lr_valid` is the ship grid's validity resampled (nearest) to the HR lattice.

## How to cite

Cite this record (CITATION.cff) **and** each source data set you use: every pair's `pair.json` carries the HR and LR
`sources.*.citation`, DOI and license, and `SOURCE_LICENSES.csv` lists them all. The paper is {C.PAPER_ID}; the code records are
{C.CODE_RECORDS['ml_code']} (model and scoring code) and {C.CODE_RECORDS['acquisition_code']} (acquisition and harmonization code).

## License

The whole record, every pair and the corpus-level files (tables, documentation, scripts) are released under
**CC BY-NC-SA 4.0** (LICENSE): {n_ncsa} pairs contain an AUV grid published by MGDS under CC BY-NC-SA, whose share-alike
condition applies to the derived grids, and the record takes that license as a whole. The table below lists each pair's
source licenses; {n_open} pairs come only from CC BY, CC0 or public-domain sources (`sources_cc_by_or_public_domain_only` in
`pairs.csv`), and those sources can be reused under their own terms directly from the providers.{(' ' + str(n_conf) + ' pair(s) have a source without a stated license (' + conf_pairs + ').') if n_conf else ''}

| pair | group | HR source | HR license | LR source | LR license | CC BY / public-domain sources only |
|---|---|---|---|---|---|---|
{src_table}

## Known limitations

- Six development units are low-amplitude and artifact-affected (`unit_class` = six: discol, ccz, NA090, NA076, the 18 Cal DIG
  pairs, EX1402L2); their scores are reported separately in the paper.
- Ship line-to-line inconsistency was not checked (ACQ-R11b fallback): the datum test G compares HR to the ship grid as a whole.
- `hr_res` always records the pixel as used, which differs from the native resolution for {n_hr_mismatch} pairs: TN159 (lockbox)
  `hr.tif` has a 3.25 m pixel (native 0.99 m), AR26 1.77 m (0.99 m), the Cal DIG pairs 2 m (1 m, provider warp), discol 2.19 m (2 m),
  tag 1.89 m (2 m), EW0207 1.23 m (1 m), and NA090 / NA076 / FK181031 about 1.05 m (1 m); see `pair.json` `build_fixes`.
- Blind test 2: the 22 Escanaba tiles flagged `excluded_r17` straddle lattice tiles zeroed by the drift-case co-registration and
  were dropped before scoring; TN188, Monterey and MV1209 were not testable (reason in `eligibility_reason`).
- Blind test 1: KN182L03 has no recoverable k and therefore no scored tiles; RC2511 carries a vertical_offset flag.
- The datum statistic G exists as a value for the development pairs only; the blind protocol recorded pass/fail for the
  blind test 2 sites and nothing for blind test 1.
- Scratch-era provenance paths inside copied `products.json` files are written as `<data_root>/...`.

Total size {tot_gb:.2f} GB in {len(inc)} pair zips; {n_tiles} tile rows.
"""
    (C.PKG / "README.md").write_text(readme)
    # ---- data dictionary
    dd = ["# DATA_DICTIONARY", "", "Units are given in brackets; empty brackets mean dimensionless or text.", "", "## pairs.parquet / pairs.csv (one row per pair)", "",
          "| column | description | units |", "|---|---|---|"]
    dd += [f"| {c} | {d} | {u} |" for c, (d, u) in PAIR_COLS.items()]
    dd += ["", "## tiles.parquet / tiles.csv (one row per scored tile)", "", "| column | description | units |", "|---|---|---|"]
    dd += [f"| {c} | {d} | {u} |" for c, (d, u) in TILE_COLS.items()]
    dd += ["", "### How the tile quantities were computed (frozen CNN-repo code; not recomputed here)", "",
           "- Windows are 256 HR px at stride 128; the scored tile is the central 128 px (`tr0 = r0 + 64`). A window is kept if >= 50 % joint-valid, >= 50 % HR-valid, HR std >= 0.05 m and >= 2 ship cells.",
           "- `s_lr` = max(standard deviation of the valid ship cells area-averaged onto lr_px = max(2, round(256 * hr_res / lr_native)) cells over the window, 0.5 m) (preprocessing/extract_clean_patches.py build_inputs).",
           "- `A_fine` = RMS over the tile's joint px of the band-passed HR field, band [hr_res/lr_native, min(k f_lr, 0.45)] cycles/px with a Tukey taper (targets_v1.py).",
           "- `A_fine_int` = the same RMS over interior px only (px at >= D1 = ceil(lr_native/hr_res) px from any invalid px); NaN with < 2048 interior px. `interior` = tile with >= 95 % interior joint px.",
           f"- Per-pair rho (pairs.rho_s_lr): Spearman(s_lr, A_fine) on interior tiles if >= {C.MIN_TILES} tiles in >= bmin ({C.B_MIN_DEFAULT}) 4x4-tile blocks; else Spearman(s_lr, A_fine_int) on tiles with finite A_fine_int under the same counts; else not scorable. `excluded_r17` tiles are dropped first. 95 % CI by block bootstrap (2000 resamples, blocks `block_id`).",
           "- `GBT_ship`, `P-V1`: held-out predictions of A_fine from ship-side inputs (leave-one-unit-out for development; frozen artifacts for the blind tests).",
           "", "## pair.json", "", "| key | description |", "|---|---|",
           "| release | version, directive, generation time, paper id |",
           "| identifiers | pair_id, unit, role, group, site_name, region, terrain_class |",
           "| sources.hr / sources.lr | dataset_id, doi, title, provider, landing_page, license, license_evidence (API record used), redistribution, citation, cruise, platform, sonar, acquisition_date |",
           "| sources.pair_license / pair_license_status | license of the released pair and audit status |",
           "| grids | hr_res (m, as used), hr_native_res_m (m), lr_native (m), lr_pixel_m (m), res_ratio, crs_epsg, vertical_reference, elevation_units, nodata per raster, mask_grid, headers (COG header per raster: dtype, crs_epsg, nodata, pixel_m, shape, bounds, overviews, compression, blocksize), stats (n_valid, median/min/max elevation in m, positive_up), source_headers (as found on the archive before conversion) |",
           "| k | max_recoverable_k, status, k_in_scoring, k_source, per_k_verdicts, k_recoverable, definition |",
           "| coregistration | case (rigid/drift), dx_m, dy_m, dz_m, offset_m (HR -> ship shift), qa (estimator QA: psr, eig_ratio, peak_agrees, mad_m / post_residual_mad_m, n, overlap, qa_pass ...), pass, method, source, quadrant_groups and quadrant_post_qa (blind test 2: per-group dx/dy/dz, agrees_with_global, pixel_offset_from_global, QA), n_tiles_dropped_boundary, initial_estimate / datum_repair (June pairs), status_recorded |",
           "| datum_check | G_V95_rel, V95_m (m), T_G, pass, source, definition |",
           "| flags | unit_class, artifact_class, scoring_status, products_v2_1_flags, qa_status, ship_products_usable (+reason), eligible, eligibility_reason, call_* (Steve's blind calls), sign_convention_suspect (only if set) |",
           "| scoring | frozen per-pair scores: view, target, bmin, n_tiles_all, n_scored, n_interior, blocks_interior, n_fallback, blocks_fallback, amplitude_m (m), rho_s_lr, rho_all_s_lr, rho_int_s_lr, rho_GBT_ship, rho_P-V1, ci_lo_s_lr, ci_hi_s_lr, ci_estimable, c1_condition, status, note, cells_across, thinner_than_development, source, rule |",
           "| provenance_records | archive-relative paths of the acquisition records (step1_record, sweep_record, site_record, grid_record, hr_selection, footprint) and the confirmatory shift_vector |",
           "| files | sha256 and bytes of every file in the zip |",
           "| build_fixes | one line per plumbing fix applied while packaging this pair |",
           "", "## ship_products/ (contract v2.1, on the lr.tif lattice, float32, nodata NaN)", "",
           "| raster | description | units |", "|---|---|---|",
           "| ship_count | soundings per ship cell | count |", "| ship_sd | standard deviation of the soundings in the cell | m |", "| ship_rsd | robust (MAD-based) standard deviation | m |",
           "| ship_xtrack_frac | mean across-track position fraction of the soundings (0 nadir, 1 outer beam) | |", "| ship_beam_angle | mean beam angle | deg |",
           "| ship_mean_regrid, ship_median_regrid | mean / median of the soundings re-gridded on the lr lattice | m |",
           "| products.json | provenance: NCEI swath files (name, url, sha256), MB-System commands, grid lattice, frame offset, QA against lr.tif | |"]
    (C.PKG / "DATA_DICTIONARY.md").write_text("\n".join(dd) + "\n")
    # ---- citation, license, examples, source licenses
    cff = f"""cff-version: 1.2.0
message: "If you use this corpus, cite it together with every source data set listed in SOURCE_LICENSES.csv and the pair.json files."
title: "Co-located ship and AUV multibeam bathymetry corpus: processed grids, masks, co-registration and tile tables"
version: "{C.RELEASE_VERSION}"
date-released: "2026-10-20"
type: dataset
license: CC-BY-NC-SA-4.0
authors:
  - family-names: Dobbs
    given-names: Stephen Cole
    affiliation: "Department of Earth and Planetary Sciences, Stanford University"
    email: stephencoledobbs@gmail.com
keywords:
  - bathymetry
  - multibeam
  - AUV
  - super-resolution
  - seafloor
  - co-located surveys
related-identifiers:
  - type: doi
    value: "{C.CODE_RECORDS['ml_code']}"
    relation: isSupplementTo
  - type: doi
    value: "{C.CODE_RECORDS['acquisition_code']}"
    relation: isSupplementTo
notes: "Companion data release of GRL manuscript {C.PAPER_ID}. The whole record is CC BY-NC-SA 4.0; {n_ncsa} pairs contain a CC BY-NC-SA source grid, {n_open} pairs come only from CC BY / public-domain sources (see pairs.csv)."
"""
    (C.PKG / "CITATION.cff").write_text(cff)
    shutil.copyfile(HERE / "LICENSE_CC_BY_NC_SA_4.0.txt", C.PKG / "LICENSE")
    (C.PKG / "examples").mkdir(exist_ok=True)
    shutil.copyfile(HERE / "load_pair.py", C.PKG / "examples" / "load_pair.py")
    shutil.copyfile(C.RPT / "license_audit.csv", C.PKG / "SOURCE_LICENSES.csv")
    # ---- suggested Zenodo metadata (directive section 6.6)
    hr_lo, hr_hi = inc.hr_res.min(), inc.hr_res.max()
    lr_lo, lr_hi = inc.lr_native.min(), inc.lr_native.max()
    hr_range = f"{hr_lo:.0f}-{hr_hi:.2f} m" if hr_hi < 3.5 else f"{hr_lo:.0f}-{hr_hi:.0f} m"
    lr_range = f"{lr_lo:.0f}-{lr_hi:.0f} m"
    desc = (f"Processed co-located seafloor bathymetry pairs for testing whether ship multibeam ranks unresolved meter-scale seafloor relief: {len(inc)} pairs, each a near-bottom AUV "
            f"multibeam grid ({hr_range}) and the independent hull-mounted ship multibeam grid ({lr_range} native cells) of the same footprint, harmonized to a common UTM "
            f"grid and co-registered, with validity masks, per-sounding ship product rasters, co-registration parameters, the datum statistic, and the frozen tile "
            f"tables (s_lr, A_fine, held-out GBT_ship and P-V1 predictions) that reproduce every score in the paper. Groups: development ({n_dev} pairs, 16 units + EW0207), "
            f"blind test 1 ({n_b1} pairs) and blind test 2 ({n_b2} sites), plus a manifest of excluded pairs. Both pre-registrations, the committed blind calls, deviation "
            f"notes and scoring outputs are included. Cloud-Optimized GeoTIFF, meters positive up, EPSG UTM codes. Sources: MGDS/IEDA, NOAA NCEI, PANGAEA, USGS; "
            f"each source data set must be cited. The record is CC BY-NC-SA 4.0; {n_open} pairs come only from CC BY / public-domain sources.")
    n_zen = len([p for p in C.PKG.iterdir() if p.is_file() and p.name != "SHA256SUMS"]) + 2   # top-level files + SHA256SUMS + examples/load_pair.py
    zen = {"title": "Co-located ship and AUV multibeam bathymetry corpus: processed grids, masks, co-registration and tile tables (companion data of GRL 2026GL125574)",
           "upload_type": "dataset", "description": desc, "n_words_description": len(desc.split()), "license": "cc-by-nc-sa-4.0",
           "keywords": ["bathymetry", "multibeam", "AUV", "seafloor", "seafloor roughness", "co-located surveys", "NCEI", "MGDS", "PANGAEA", "USGS", "Cloud-Optimized GeoTIFF"],
           "related_identifiers": [{"identifier": "GRL 2026GL125574", "relation": "isSupplementTo", "note": "replace by the paper DOI when assigned"},
                                   {"identifier": C.CODE_RECORDS["ml_code"], "relation": "isSupplementTo", "resource_type": "software"},
                                   {"identifier": C.CODE_RECORDS["acquisition_code"], "relation": "isSupplementTo", "resource_type": "software"}],
           "creators": [{"name": "Dobbs, Stephen Cole", "affiliation": "Stanford University"}], "sole_author": True, "version": C.RELEASE_VERSION, "publication_date": "2026-10-20",
           "files_to_upload": {"count": n_zen, "rule": "all top-level files (pair zips, tables, docs, blind_tests.zip, SHA256SUMS) plus examples/load_pair.py uploaded as load_pair.py; the blind_tests/ folder is uploaded as blind_tests.zip"},
           "resolution_ranges_m": {"auv_hr_res": [float(hr_lo), float(hr_hi)], "ship_lr_native": [float(lr_lo), float(lr_hi)]}}
    C.jdump(zen, C.PKG / "zenodo_metadata.json")
    C.jdump(zen, C.RPT / "zenodo_metadata.json")


def sha256sums():
    lines = []
    for p in sorted(C.PKG.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            lines.append(f"{C.sha256(p)}  {p.relative_to(C.PKG)}")
    (C.PKG / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    return len(lines)


def main():
    inv, lic, build = C.jload(C.INVENTORY), C.jload(C.LICENSE_AUDIT), C.jload(BUILD_RESULTS)
    missing = [e["pair_id"] for e in inv["entries"] if e["in_corpus"] and e["pair_id"] not in build["pairs"]]
    if missing:
        raise SystemExit(f"corpus: build incomplete, missing {missing}")
    C.PKG.mkdir(parents=True, exist_ok=True)
    pairs = pairs_table(inv, build)
    C.log(f"pairs table: {len(pairs)} rows ({int(pairs.in_corpus.sum())} with rasters)")
    tiles, n_excl = tiles_table(inv)
    C.log(f"tiles table: {len(tiles)} rows; excluded_r17 {int(tiles.excluded_r17.sum())} (list has {n_excl}); groups {dict(Counter(tiles.group))}")
    idx = blind_tests()
    C.log(f"blind_tests: {len(idx)} files + INDEX.md; blind_tests.zip")
    write_docs(inv, pairs, len(tiles), n_excl, lic)
    n = sha256sums()
    C.log(f"SHA256SUMS: {n} files")


if __name__ == "__main__":
    main()
