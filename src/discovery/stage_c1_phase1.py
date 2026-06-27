"""C1 close-out Phase 1 (all behind Steve QC sign-off; NO canonical writes).

P1.1 Axial supersede: re-harmonize TN268x30466 with SRift HR vs the SAME TN268 LR;
     joint-tile delta vs old 30466 HR (more area vs better quality?).
P1.2 Axial NRift: harmonize vs EW0207/EW9904/TN383 LRs; co-location by joint tiles.
P1.3 Arctic 30046: download (untested float) + depth proof + joint tiles vs 2009_Amundsen LR.
P1.4 Santa Monica res_ratio reconciliation: EM302 footprint estimate vs measured.

Candidate products -> $DATA_ROOT/harmonized/<candidate_pid>/ (new dirs; manifest untouched).
"""
from __future__ import annotations
import json, logging, os
from pathlib import Path
import numpy as np
import rasterio

from src.discovery.stage_c1_harmonize import one as harmonize_one
from src.discovery.stage_c1_reharvest import files_for, download, decompress
from src.discovery.stage_c1_step2_analysis import l2_joint_cells, grid_info

log = logging.getLogger("c1p1")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
RH = DATA / "reharvest_c1"
GRID = DATA / "raw_lr_gridded"
HARM = DATA / "harmonized"
RESULT = REPO / "reports/discovery/stage_c1_phase1_results.json"


def p11_supersede(tmp):
    p = {"pid": "TN268__MGDS_32556_SRiftSupersede", "hr": RH / "MGDS_32556" / "AxialSRift_MAUV_ver2025_Topo1m.grd",
         "lr": GRID / "TN268__union.grd", "site": "Axial_SRift", "lu": 22,
         "morph": "volcanic", "region": "JdF:Axial", "depth_m": 2258, "hr_doi": "10.60521/332556", "lr_cruise": "TN268"}
    rec = harmonize_one(p, tmp)
    # old joint tiles for delta
    old = HARM / "TN268__MGDS_30466" / "joint_valid.tif"
    if old.exists():
        with rasterio.open(str(old)) as ds:
            oj = (ds.read(1) == 1)
        rec["old_30466_joint_tiles_known"] = 825
        rec["old_30466_joint_cells"] = int(oj.sum())
    rec["delta_note"] = ("compare new SRift n_valid_tiles to old 825; if larger, TN268 LR covers more of "
                         "the bigger SRift footprint (more tiles); if ~same, gain is HR quality (ver2025) not area")
    return rec


def p12_nrift(tmp):
    out = {"candidates": []}
    for lr in ("EW0207", "EW9904", "TN383"):
        p = {"pid": f"{lr}__MGDS_32556_NRift", "hr": RH / "MGDS_32556" / "AxialNRift_MAUV_ver2025_Topo1m.grd",
             "lr": GRID / f"{lr}__union.grd", "site": "Axial_NRift", "lu": 22,
             "morph": "volcanic", "region": "JdF:Axial", "depth_m": 1849, "hr_doi": "10.60521/332556", "lr_cruise": lr}
        try:
            rec = harmonize_one(p, tmp)
        except Exception as e:
            rec = {"pair_id": p["pid"], "status": "reject", "reason": str(e)[:120]}
        out["candidates"].append({"lr": lr, "status": rec.get("status"), "reason": rec.get("reason"),
                                  "n_valid_tiles": rec.get("n_valid_tiles"), "joint_km2": rec.get("joint_area_km2"),
                                  "coreg": rec.get("coreg"), "hr_p50": rec.get("hr_p50_over_joint"),
                                  "qc_figure": rec.get("qc_figure")})
        log.info("NRift x %s: %s tiles=%s", lr, rec.get("status"), rec.get("n_valid_tiles"))
    cl = [c for c in out["candidates"] if c.get("n_valid_tiles")]
    out["best_lr"] = max(cl, key=lambda c: c["n_valid_tiles"])["lr"] if cl else None
    out["verdict"] = ("new_pair" if cl else "held_no_colocating_LR")
    return out


def p13_arctic30046(tmp):
    rec = {"uid": "30046", "files": []}
    dest = RH / "MGDS_30046"
    best = None
    for data_uid, sz in files_for("30046"):
        try:
            raw, how = download(data_uid, sz, dest)
            path = decompress(raw)
        except Exception as e:
            rec["files"].append({"data_uid": data_uid, "error": str(e)[:80]}); continue
        if "diff" in path.name.lower():
            rec["files"].append({"file": path.name, "skip": "diff grid"}); continue
        gi = grid_info(path)
        fr = {"file": path.name, "bounds": gi.get("bounds_4326")}
        # depth + joint vs 2009_Amundsen LR
        jr = l2_joint_cells(path, GRID / "2009_Amundsen__MGDS_30045.grd")
        fr["joint"] = jr
        rec["files"].append(fr)
        log.info("30046 %s joint_cells=%s p50=%s", path.name, jr.get("joint_cells_dec"), jr.get("hr_p50"))
        if (jr.get("joint_cells_dec") or 0) > (best or {}).get("joint", {}).get("joint_cells_dec", -1):
            best = fr
    rec["verdict"] = ("co_locates_proceed_to_full_gates" if best and (best["joint"].get("joint_cells_dec") or 0) > 0
                      else "arctic_unrecoverable_from_these_products_0_joint_cells")
    return rec


def p14_santamonica():
    """EM302 footprint estimate at site depth vs measured LR native (grid posting +
    fill-fraction proxy over the harmonized footprint)."""
    rec = {"recorded_lr_native_m": 221.0, "depth_m": 866}
    import math
    rec["em302_footprint_estimate_m"] = round(2 * 866 * math.tan(math.radians(0.5)), 1)  # ~1deg beam
    lr = GRID / "NA076__union.grd"
    for c in (str(lr), "NETCDF:" + str(lr)):
        try:
            ds = rasterio.open(c)
        except Exception:
            continue
        res = abs(ds.res[0])
        resm = res * 111320 * math.cos(math.radians((ds.bounds.bottom + ds.bounds.top) / 2)) if (ds.crs and ds.crs.is_geographic) else res
        a = ds.read(1, masked=True).filled(np.nan)
        ds.close()
        fill = float(np.isfinite(a).mean())
        rec["lr_grid_posting_m"] = round(float(resm), 1)
        rec["lr_grid_fill_fraction"] = round(fill, 3)
        # sounding-density proxy = posting / sqrt(fill) over the data region
        rec["lr_native_sqrt_fill_proxy_m"] = round(float(resm) / max(0.05, fill) ** 0.5, 1)
        break
    est = rec.get("lr_native_sqrt_fill_proxy_m") or rec.get("lr_grid_posting_m")
    rec["verdict"] = ("recorded_221_is_artifact_correct_to_measured" if est and est < 60
                      else "genuinely_sparse_keep_221_record_reconciliation")
    rec["proposed_lr_native_res_m"] = est
    rec["proposed_res_ratio"] = round(est / 1.0, 1) if est else None
    return rec


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "c1p1"; tmp.mkdir(parents=True, exist_ok=True)
    out = {}
    log.info("=== P1.1 SRift supersede ===")
    try: out["P1_1_supersede"] = p11_supersede(tmp)
    except Exception as e: out["P1_1_supersede"] = {"error": str(e)[:150]}
    log.info("=== P1.2 NRift pairing ===")
    try: out["P1_2_nrift"] = p12_nrift(tmp)
    except Exception as e: out["P1_2_nrift"] = {"error": str(e)[:150]}
    log.info("=== P1.3 Arctic 30046 ===")
    try: out["P1_3_arctic_30046"] = p13_arctic30046(tmp)
    except Exception as e: out["P1_3_arctic_30046"] = {"error": str(e)[:150]}
    log.info("=== P1.4 SantaMonica reconciliation ===")
    try: out["P1_4_santamonica"] = p14_santamonica()
    except Exception as e: out["P1_4_santamonica"] = {"error": str(e)[:150]}
    RESULT.write_text(json.dumps(out, indent=2, default=str))
    log.info("P1.1 SRift tiles=%s (old 825)", out.get("P1_1_supersede", {}).get("n_valid_tiles"))
    log.info("P1.2 NRift best_lr=%s verdict=%s", out.get("P1_2_nrift", {}).get("best_lr"), out.get("P1_2_nrift", {}).get("verdict"))
    log.info("P1.3 arctic verdict=%s", out.get("P1_3_arctic_30046", {}).get("verdict"))
    log.info("P1.4 verdict=%s proposed_ratio=%s", out.get("P1_4_santamonica", {}).get("verdict"), out.get("P1_4_santamonica", {}).get("proposed_res_ratio"))
    log.info("wrote %s", RESULT)


if __name__ == "__main__":
    main()
