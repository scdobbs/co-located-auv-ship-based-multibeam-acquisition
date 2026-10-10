"""ACQ-R06 Part B3 and C1 — records-only tabulations (no sealed file is opened, listed or computed on).

B3: for each sealed pair, which Part-A inputs / outputs exist as recorded values in manifest v2.1, the committed
    harmonize/<pair>.json and grid/<cruise>.json records (ACQ-R02), the June C2a / C2c records (lockbox pairs);
    the June fetch plan (CSV) for the lockbox LR cruises; the MB-System formats of the confirmatory LR cruises and
    whether the unchanged v2.1 builder has run on each format (development products.json + ACQ-R04 corpus).
C1: rule C1 applied to the 45 development rows against the recorded ship_products_usable.
Usage: python -m src.phase4.records
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.acq_r01 import common as C
from src.phase4 import common as P
from src.phase4 import sealed_step1 as S


def _v(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return x


def sealed_records() -> list:
    m = P.manifest().set_index("pair_id")
    c2a_june = {r["pair_id"]: r for r in json.loads(P.JUNE_C2A_RECORD.read_text())["pairs"]}
    c2c_june = {r["pair_id"]: r for r in json.loads(P.JUNE_C2C_SWEEP.read_text())["pairs"]}
    rows = []
    for pid, info in P.SEALED5.items():
        row = m.loc[pid]; cruise = str(row["lr_cruise"])
        rec = {"pair_id": pid, "set": info["set"], "unit": info["unit"], "lr_cruise": cruise, "harmonized_path": row["harmonized_path"],
               "manifest": {k: _v(row.get(k)) for k in ("hr_native_res_m", "lr_native_res_m", "res_ratio", "max_recoverable_k", "k_sweep_status",
                                                        "ship_products_usable", "products_v2_1_flags", "qa_status", "coreg_status", "horiz_offset_m",
                                                        "lr_sonar", "harmonized_path_hr", "harmonized_path_lr", "hr_valid", "lr_valid", "joint_valid", "target_crs")}}
        hp = P.R02 / "harmonize" / f"{pid}.json"; gp = P.R02 / "grid" / f"{cruise}.json"
        if hp.exists():
            h = json.loads(hp.read_text())
            rec["harmonize_record"] = {"status": h.get("status"), "hr_res_m": h.get("hr_res_m"), "lr_native": h.get("lr_native"), "k_sweep": h.get("k_sweep"),
                                       "coreg": h.get("coreg"), "qa_pass": h.get("qa_pass"), "n_valid_tiles_256": h.get("n_valid_tiles_256"), "out_dir": h.get("out_dir"),
                                       "target_crs": h.get("target_crs"), "hr_tiles_used": h.get("hr_tiles_used")}
        else:
            rec["harmonize_record"] = None
        if gp.exists():
            g = json.loads(gp.read_text())
            rec["grid_record"] = {k: g.get(k) for k in ("n_files", "format", "sonar", "beamwidth_deg", "beamwidth_key", "footprint_depth_m", "cell_m", "grid_depth_median", "mode")}
        else:
            rec["grid_record"] = None
        rec["june_c2a_record"] = {k: c2a_june[pid].get(k) for k in ("sonar", "beamwidth_deg", "depth_m", "documented_footprint_m", "grid_posting_m", "case")} if pid in c2a_june else None
        rec["june_c2c_sweep"] = {k: c2c_june[pid].get(k) for k in ("status", "lr_native_m", "max_recoverable_k")} if pid in c2c_june else None
        sonar, src, _ = S.sonar_for(pid, cruise, row)
        from src.acq_r01.grid_lr import beamwidth_for
        bw, key = beamwidth_for(sonar)
        rec["c2a_inputs_the_step_will_use"] = {"sonar": sonar, "sonar_source": src, "beamwidth_deg": bw, "beamwidth_key": key,
                                               "depth": "median of all valid cells of the harmonized lr.tif (read at the sealed step)", "posting": "lr.tif pixel size (read at the sealed step)"}
        rec["k_rule_at_the_sealed_step"] = ("prior k kept, no sweep: " + S.prior_k(pid, row)["k_source"] + f" (k={S.prior_k(pid, row)['max_recoverable_k']})") if pid in P.PRIOR_K_PAIRS else "sweep run (stage_c2c_recalibrate.sweep)"
        swath_dir_listed = cruise in {p.name for p in C.RAW_SWATH_OAK.iterdir()}
        rec["raw_swath_dir_present_in_oak_listing"] = swath_dir_listed
        rows.append(rec)
    return rows


def lockbox_fetch_plan() -> dict:
    out = {}
    plan = list(csv.DictReader(P.JUNE_FILE_PLAN.open()))
    fl = {r["cruise"]: r for r in csv.DictReader(P.JUNE_FETCH_LIST.open())}
    for c in C.LOCKBOX_LR_CRUISES:
        rows = [r for r in plan if r["cruise"] == c]
        sw = [r for r in rows if r["kind"] == "swath"]; nav = [r for r in rows if r["kind"] == "nav"]
        subdirs = sorted({r["url"].rsplit("/", 2)[-2] for r in sw})
        out[c] = {"plan_exists": bool(rows), "n_swath_files": len(sw), "swath_advertised_gb": round(sum(int(r["advertised"]) for r in sw) / 1e9, 3),
                  "n_nav_files": len(nav), "nav_advertised_gb": round(sum(int(r["advertised"]) for r in nav) / 1e9, 4),
                  "ncei_sonar_subdirs": subdirs, "fetch_list_row": {k: fl[c].get(k) for k in ("live_HR", "fetch_mode", "whole_GB", "subset_GB", "reason")} if c in fl else None,
                  "source_csv": str(P.JUNE_FILE_PLAN.relative_to(P.REPO)), "on_oak_raw_lr_swath_listing": c in {p.name for p in C.RAW_SWATH_OAK.iterdir()}}
    return out


def builder_formats() -> dict:
    """Which MB-System formats the unchanged builder has processed: development ship_products_v2_1 (products.json mb_format)
    and the ACQ-R04 corpus (selection_v1_1 mb_format x pretrain_manifest products)."""
    dev = {}
    for pj in sorted(C.OAK.glob("harmonized/*/ship_products_v2_1/products.json")) + sorted(C.OAK.glob("harmonized/*/lrv2_1/ship_products_v2_1/products.json")):
        if "harmonized_confirmatory" in pj.parts:
            continue
        j = json.loads(pj.read_text()); f = j["source"]["mb_format"]
        if f is None:
            continue
        dev.setdefault(int(f), []).append(j["pair_id"])
    sel = pd.read_csv(P.REPO / "reports_post_grl_review/ACQ-R04/selection_v1_1.csv")
    pm = pd.read_parquet(P.REPO / "reports_post_grl_review/ACQ-R04/pretrain_manifest_v1.parquet", columns=["cruise", "products_available", "products_usable"])
    pm = pm.merge(sel[["cruise", "mb_format"]], on="cruise", how="left")
    corpus = {}
    for f, g in pm.groupby("mb_format"):
        corpus[int(f)] = {"n_cruises": int(g.cruise.nunique()), "n_blocks": int(len(g)), "n_blocks_products_available": int(g.products_available.fillna(False).astype(bool).sum()),
                          "n_blocks_products_usable": int(g.products_usable.fillna(False).astype(bool).sum())}
    conf = {}
    for c in C.CONFIRMATORY_LR_CRUISES:
        g = json.loads((P.R02 / "grid" / f"{c}.json").read_text()); f = int(g["format"])
        conf[c] = {"mb_format": f, "sonar": g.get("sonar"), "n_files": g.get("n_files"), "beamwidth_deg": g.get("beamwidth_deg"), "beamwidth_key": g.get("beamwidth_key"),
                   "builder_run_on_format_development": sorted(dev.get(f, [])), "builder_run_on_format_acq_r04_corpus": corpus.get(f),
                   "ever_run": bool(dev.get(f)) or bool(corpus.get(f, {}).get("n_blocks_products_available"))}
    return {"confirmatory": conf, "development_formats": {str(k): v for k, v in sorted(dev.items())}, "corpus_formats": {str(k): v for k, v in sorted(corpus.items())}}


def c1_check() -> dict:
    """Rule C1 on the 45 development rows: products.json on OAK (available + contract flags) vs the recorded column."""
    m = P.manifest()
    dev = m[m.designation.astype(str).str.startswith("development")]
    rows = []
    for _, r in dev.iterrows():
        pj = C.OAK / str(r["harmonized_path"]) / "ship_products_v2_1" / "products.json"
        if pj.exists():
            p = json.loads(pj.read_text())
            prod = {"available": bool(p.get("available")) and all(p["available"].values()), "unavailable_reason": p.get("unavailable_reason"),
                    "flags": list((p.get("qa_vs_lr_tif") or {}).get("flags") or [])}
            src = "products.json"
        else:
            prod = {"available": False, "reason": "no ship_products_v2_1/products.json", "flags": []}; src = "none"
        rule, reason = S.usable_rule(prod)
        recorded = r.get("ship_products_usable")
        rows.append({"pair_id": r.pair_id, "designation": r.designation, "products_json": src, "available": prod["available"], "flags": ";".join(prod["flags"]),
                     "rule_C1": bool(rule), "rule_reason": reason, "recorded": None if recorded is None else bool(recorded), "recorded_reason": r.get("ship_products_usable_reason"),
                     "ruling_source": r.get("ruling_source"), "agree": (None if recorded is None else bool(rule) == bool(recorded))})
    df = pd.DataFrame(rows)
    return {"n_rows": int(len(df)), "n_agree": int(df.agree.fillna(False).sum()), "n_disagree": int((df.agree == False).sum()),   # noqa: E712
            "n_recorded_null": int(df.recorded.isna().sum()), "disagreements": df[df.agree == False].to_dict("records"), "rows": rows}   # noqa: E712


def main(argv=None):
    P.check_fixed_inputs()
    out = {"generated": P.utc_now(), "sealed_pairs": sealed_records(), "lockbox_fetch_plan": lockbox_fetch_plan(), "builder_formats": builder_formats(),
           "c1_check": c1_check(), "code_commit": P.git_commit()}
    P.write_json(P.REPORT_DIR / "sealed_records.json", {k: v for k, v in out.items() if k != "c1_check"}, mode=0o644)
    P.write_json(P.REPORT_DIR / "c1_check.json", out["c1_check"], mode=0o644)
    pd.DataFrame(out["c1_check"]["rows"]).to_csv(P.REPORT_DIR / "c1_check.csv", index=False)
    c1 = out["c1_check"]
    print(f"C1: {c1['n_agree']}/{c1['n_rows']} agree, {c1['n_disagree']} disagree, {c1['n_recorded_null']} recorded null")
    for d in c1["disagreements"]:
        print("  DISAGREE", d["pair_id"], "rule", d["rule_C1"], "recorded", d["recorded"], d["recorded_reason"], "|", d["ruling_source"])
    for c, v in out["lockbox_fetch_plan"].items():
        print(f"fetch plan {c}: {v['n_swath_files']} swath files, {v['swath_advertised_gb']} GB, subdirs {v['ncei_sonar_subdirs']}, on OAK listing {v['on_oak_raw_lr_swath_listing']}")
    for c, v in out["builder_formats"]["confirmatory"].items():
        print(f"format {c}: mb{v['mb_format']} sonar {v['sonar']!r} bw {v['beamwidth_deg']} ({v['beamwidth_key']}); dev {v['builder_run_on_format_development']}; corpus {v['builder_run_on_format_acq_r04_corpus']}")
    for r in out["sealed_pairs"]:
        print(r["pair_id"], r["set"], "| manifest hr/lr/k:", r["manifest"]["hr_native_res_m"], r["manifest"]["lr_native_res_m"], r["manifest"]["max_recoverable_k"],
              "| sonar:", r["c2a_inputs_the_step_will_use"]["sonar"], r["c2a_inputs_the_step_will_use"]["beamwidth_deg"], "| k rule:", r["k_rule_at_the_sealed_step"][:60], "| swath on OAK:", r["raw_swath_dir_present_in_oak_listing"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
