"""ACQ-R04 §3.5 — corpus manifest + failure ledger, from the persisted per-cruise records and block directories.

pretrain_manifest_v1.parquet: one row per kept block (cruise, block, stratum, instrument family, basin, year, depth,
cell, fill, products usable + flags, OAK location: oak_tar + tar_member_dir, and grid_vsitar for direct GDAL reads —
per-cruise tar layout, decision 2026-10-06).  failure_ledger_v1.csv: every selected cruise, file or
block that was skipped, failed or dropped, with its reason (fetch failures, cruises not processed, files without
soundings, polar soundings, blocks dropped by depth / guard / fill, mbgrid and product failures).
Usage: python -m src.acq_r04.corpus_manifest [--version 1] [--remove-blocks file.csv --reason "..."]
"""
from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r04.blocks import cdir_name


def build(cruises=None):
    sel = pd.read_csv(R.REPORT_DIR / "selection_v1.csv")
    cruises = cruises if cruises is not None else sel.cruise.tolist()
    rows, led = [], []
    rm_v11 = R.REPORT_DIR / "selection_v1_1_removed.csv"
    removed_v11 = pd.read_csv(rm_v11).set_index("cruise").reason.to_dict() if rm_v11.exists() else {}
    for c in cruises:
        cd = cdir_name(c); lg = R.WORK_LOGS / cd
        if c in removed_v11:
            led.append({"level": "cruise", "cruise": c, "item": c, "stage": "removed_selection_v1_1", "reason": removed_v11[c]}); continue
        fj = lg / "fetch.json"
        if not fj.exists():
            led.append({"level": "cruise", "cruise": c, "item": c, "stage": "fetch", "reason": "not fetched"}); continue
        fl = pd.read_csv(lg / "fetch_log.csv")
        for r in fl[~fl.status.isin(["fetched", "fetched_unverified_len", "skip_present", "skip_present_unverified_len"])].itertuples():
            led.append({"level": "file", "cruise": c, "item": r.filename, "stage": "fetch", "reason": f"{r.status} (http {r.http_status})"})
        rj = lg / "cruise_record.json"
        if not rj.exists():
            fail = lg / "cruise_failure.json"
            why = json.loads(fail.read_text())["error"] if fail.exists() else "not processed"
            led.append({"level": "cruise", "cruise": c, "item": c, "stage": "grid", "reason": why}); continue
        rec = json.loads(rj.read_text())
        for u in rec.get("unreadable_files", []):
            led.append({"level": "file", "cruise": c, "item": u["file"], "stage": "unreadable_skipped",
                        "reason": f"{u['reason']}; {u['attempts']} attempts; left out of the cruise (ruling 2026-10-04 option 2)"})
        for f in rec.get("files_without_soundings", []):
            led.append({"level": "file", "cruise": c, "item": f, "stage": "coverage", "reason": "mblist returned no valid soundings"})
        if rec.get("polar_soundings_dropped"):
            led.append({"level": "soundings", "cruise": c, "item": str(rec["polar_soundings_dropped"]), "stage": "coverage",
                        "reason": "soundings poleward of 84N/80S (no UTM zone) dropped"})
        blp = lg / "block_ledger.csv"
        if not blp.exists() or blp.stat().st_size <= 1:      # cruise produced no blocks at all (e.g. AII8501: only polar soundings)
            led.append({"level": "cruise", "cruise": c, "item": c, "stage": "no_blocks",
                        "reason": f"no 10 km blocks: {rec.get('soundings', 0)} soundings in UTM range, "
                                  f"{rec.get('polar_soundings_dropped', 0)} polar soundings dropped, "
                                  f"{len(rec.get('files_without_soundings', []))} file(s) without soundings"})
            bl = pd.DataFrame(columns=["block", "status", "median_depth_m"])
        else:
            bl = pd.read_csv(blp)
        for r in bl[bl.status != "kept"].itertuples():
            led.append({"level": "block", "cruise": c, "item": r.block, "stage": r.status,
                        "reason": {"drop_depth": f"median depth {r.median_depth_m} m outside 300-6500 m",
                                   "drop_exclusion_guard": f"within exclusion threshold (margin {getattr(r, 'guard_margin_m', '')} m, {getattr(r, 'guard_nearest', '')})",
                                   "drop_fill": f"fill {getattr(r, 'fill', '')} < 0.50",
                                   "fail_mbgrid": f"mbgrid failed: {str(getattr(r, 'error', ''))[:200]}"}.get(r.status, r.status)})
        for f in rec.get("failures", []):
            if f["stage"] == "products":
                led.append({"level": "block", "cruise": c, "item": f["block"], "stage": "products_failed", "reason": str(f["detail"])[:300]})
        for bdir in sorted((R.STAGE / cd).glob("*/block.json")):
            b = json.loads(bdir.read_text()); p = b.get("products", {})
            pj = bdir.parent / "ship_products_v2_1" / "products.json"
            qa = (json.loads(pj.read_text()).get("qa_vs_lr_tif") or {}) if pj.exists() else {}
            rows.append({"cruise": c, "block": b["block"], "stratum": b["stratum"], "instrument_family": b["family"], "basin": b["basin"],
                         "year": b["year"], "instrument": b["instrument"], "crs": b["crs"], "median_depth_m": b["median_depth_m"],
                         "cell_m": b["cell_m"], "fill": b["fill"], "n_soundings": b["n_soundings"],
                         "products_usable": bool(p.get("usable", False)), "products_flags": ";".join(p.get("flags", []) or []),
                         "products_available": json.dumps(p.get("available", {})), "products_error": p.get("error"),
                         "qa_median_offset_m": qa.get("median_offset_m"), "qa_robust_sigma_m": qa.get("robust_sigma_m"),
                         "qa_shift_argmin_cells": json.dumps(qa.get("shift_argmin_cells")), "qa_gain_m": qa.get("gain_m"),
                         "qa_n_common_cells": qa.get("n_common_cells"), "grid_mode": b.get("grid_mode"),
                         "grid_tif_sha256": b["grid_tif_sha256"],
                         "oak_tar": str(R.OAK_OUT / "blocks" / f"{cd}.tar"), "tar_member_dir": f"{cd}/{b['block']}",
                         "grid_vsitar": f"/vsitar/{R.OAK_OUT / 'blocks' / f'{cd}.tar'}/{cd}/{b['block']}/grid.tif"})
    return pd.DataFrame(rows), pd.DataFrame(led)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="1"); ap.add_argument("--cruises", default=None)
    ap.add_argument("--remove-blocks", default=None, help="CSV cruise,block of blocks to remove (§4.1 disagreements)")
    ap.add_argument("--reason", default=None)
    a = ap.parse_args(argv)
    man, led = build(a.cruises.split(",") if a.cruises else None)
    C.assert_no_lockbox_cruise(man.cruise.unique().tolist() if len(man) else [])
    removed = []
    if a.remove_blocks:
        rm = pd.read_csv(a.remove_blocks)
        key = set(zip(rm.cruise, rm.block))
        mask = [(c, b) in key for c, b in zip(man.cruise, man.block)]
        removed = man[mask][["cruise", "block"]].to_dict("records")
        man = man[[not x for x in mask]]
        led = pd.concat([led, pd.DataFrame([{"level": "block", "cruise": r["cruise"], "item": r["block"], "stage": "removed_s4_1",
                                             "reason": a.reason or "§4.1 exclusion disagreement"} for r in removed])], ignore_index=True)
    out = R.REPORT_DIR / f"pretrain_manifest_v{a.version}.parquet"
    man.to_parquet(out, index=False)
    led.to_csv(R.REPORT_DIR / f"failure_ledger_v{a.version}.csv", index=False)
    summ = {"generated": R.utc_now(), "version": a.version, "rows": int(len(man)), "sha256": R.sha256_file(out),
            "ledger_rows": int(len(led)), "ledger_by_stage": led.stage.value_counts().to_dict() if len(led) else {},
            "removed_blocks": removed, "code_commit": C.git_commit()}
    R.write_json(R.REPORT_DIR / f"pretrain_manifest_v{a.version}.json", summ)
    print(json.dumps(summ, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
