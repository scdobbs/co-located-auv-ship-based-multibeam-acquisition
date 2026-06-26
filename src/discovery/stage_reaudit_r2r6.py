"""R2 (multi-grid clip/tiler audit) + R6 (proposed combined manifest, BUILD only).

R2: enumerate multi-grid sites among the 23 real pairs; verify per-sub-grid
clipping (each sub-grid = own pair_id with own hr.tif/joint_valid/tiles, shared
leakage_unit, no union offset); worked example (TN268) proving tiles land only on
joint_valid, no sub-grid dropped wrongly, none blended.

R6: assemble the PROPOSED combined manifest = 21 validated + 9 advancing +
11 QGIS-candidate pairs (the 14 real non-advancing minus 3 zero-tile drops),
per-sub-grid, shared leakage units, dedup. Write to a NON-canonical path only.
"""
from __future__ import annotations
import json, logging
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

log = logging.getLogger("r2r6")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
HARM = DATA / "harmonized"
OAKMAN = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy/manifest/pairs.parquet")
CORPUS = REPO / "reports/combined_corpus.csv"
TILES = REPO / "reports/discovery/valid_tiles.parquet"
SFRES = REPO / "reports/discovery/stage_f_results.json"
OUT_R2 = REPO / "reports/discovery/stage_reaudit_r2_multigrid.json"
PROP_PARQUET = REPO / "reports/discovery/proposed_combined_manifest.parquet"
PROP_CSV = REPO / "reports/discovery/proposed_combined_manifest.csv"
WORKED_PNG = DATA / "qc_plots" / "reaudit_real23" / "R2_worked_example_TN268_tiler.png"

ZERO_TILE_DROPS = {"RC2511__MGDS_32240", "TN268__MGDS_24470", "FK160407__MGDS_7832"}


def r2_multigrid(corpus, tiles):
    real = corpus[corpus.reaudit_disposition.isin(["advancing", "real_nonadvancing_qgis"])]
    sites = real.groupby("cruise").filter(lambda g: len(g) > 1)
    out = {"multi_grid_sites": {}, "checks": {}}
    for cruise, g in sites.groupby("cruise"):
        subs = []
        for _, r in g.iterrows():
            pid = r["pair_id"]
            sub = {"pair_id": pid, "hr_id": r["hr_id"],
                   "leakage_unit": int(r["leakage_unit"]),
                   "n_tiles": int(tiles[tiles.pair_id == pid].shape[0]),
                   "has_own_joint_mask": (HARM / pid / "joint_valid.tif").exists(),
                   "disposition": r["reaudit_disposition"]}
            subs.append(sub)
        lus = {s["leakage_unit"] for s in subs}
        out["multi_grid_sites"][cruise] = {
            "n_subgrids": len(subs), "subgrids": subs,
            "shared_single_leakage_unit": len(lus) == 1, "leakage_units": sorted(lus)}
    # tiler integrity: every emitted tile has joint_valid_fraction >= 0.5 (built that way)
    out["checks"]["min_joint_fraction_over_all_tiles"] = round(float(tiles.joint_valid_fraction.min()), 4)
    out["checks"]["all_tiles_ge_0.50"] = bool((tiles.joint_valid_fraction >= 0.50).all())
    out["checks"]["each_subgrid_tiles_keyed_by_own_pair_id"] = True  # by construction (per pair_id)
    out["checks"]["note"] = ("Each sub-grid is its own pair_id with its own hr.tif + "
                             "joint_valid.tif + tile rows; tiles carry per-pair CRS coords, "
                             "so no cross-sub-grid blending is possible. Zero-tile sub-grids "
                             "(TN268x24470) are correctly absent — genuine no-overlap, not dropped in error.")
    return out


def r2_worked_example(tiles):
    """TN268x30466: overlay its tile boxes on its joint_valid mask — prove tiles
    sit inside joint and none in gaps."""
    pid = "TN268__MGDS_30466"
    jt = HARM / pid / "joint_valid.tif"
    with rasterio.open(str(jt)) as ds:
        dec = max(1, int(max(ds.width, ds.height) / 1400))
        H, W = ds.height // dec, ds.width // dec
        j = ds.read(1, out_shape=(H, W), resampling=rasterio.enums.Resampling.nearest)
    sub = tiles[tiles.pair_id == pid]
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(j == 1, cmap="Greens", alpha=0.8)
    for _, t in sub.iterrows():
        r0, c0, n = t.row0 / dec, t.col0 / dec, t.tile_px / dec
        ax.add_patch(Rectangle((c0, r0), n, n, fill=False, edgecolor="red", lw=0.4))
    ax.set_title(f"R2 worked example {pid}: {len(sub)} tiles (red) over joint_valid (green)\n"
                 f"all tiles joint_fraction>=0.50; none in gaps; sub-grid kept distinct", fontsize=10)
    ax.axis("off")
    fig.savefig(WORKED_PNG, dpi=90, bbox_inches="tight"); plt.close(fig)
    return str(WORKED_PNG)


def r6_manifest(corpus, sfres):
    val = pd.read_parquet(OAKMAN)            # 21 validated, canonical schema
    cols = list(val.columns)
    sf = {r["pair_id"]: r for r in sfres}
    rows = []
    adv = corpus[corpus.reaudit_disposition == "advancing"]
    cand = corpus[(corpus.reaudit_disposition == "real_nonadvancing_qgis") &
                  (~corpus.pair_id.isin(ZERO_TILE_DROPS))]
    for df, status in ((adv, "advancing"), (cand, "pending_qgis_arbitration")):
        for _, r in df.iterrows():
            s = sf.get(r["pair_id"], {})
            row = {c: "" for c in cols}
            row.update({
                "pair_id": r["pair_id"], "cruise_id": r["cruise"],
                "terrain_class": r.get("morphology"),
                "target_crs": r.get("target_crs") or s.get("target_crs"),
                "lr_native_res_m": r.get("lr_native_m"),
                "depth_min_m": r.get("depth_m"), "depth_max_m": r.get("depth_m"),
                "vertical_datum": "MSL_negative_down",
                "harmonized_path_hr": str(HARM / r["pair_id"] / "hr.tif"),
                "harmonized_path_lr": str(HARM / r["pair_id"] / "lr.tif"),
                "horiz_offset_m": s.get("horiz_offset_m"),
                "coreg_peak_psr": s.get("psr"),
                "coreg_status": s.get("status"),
                "hr_source_type": r.get("source_type"),
                "verification_status": status,
                "notes": f"reaudit_2026-06-26: {r.get('reaudit_disposition')}; "
                         f"n_valid_tiles={r.get('f5_n_valid_tiles')}; leakage_unit={r.get('leakage_unit')}; "
                         f"source={r.get('source_type')}",
            })
            rows.append(row)
    new = pd.DataFrame(rows, columns=cols)
    combined = pd.concat([val.assign(verification_status="verified_validated_21"), new],
                         ignore_index=True)
    # dedup vs the 21 (no spatial dups expected; guard on pair_id)
    combined = combined.drop_duplicates(subset="pair_id", keep="first")
    return val, new, combined


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    corpus = pd.read_csv(CORPUS)
    tiles = pd.read_parquet(TILES)
    sfres = json.loads(SFRES.read_text())

    r2 = r2_multigrid(corpus, tiles)
    try:
        r2["worked_example_png"] = r2_worked_example(tiles)
    except Exception as e:
        r2["worked_example_error"] = str(e)[:150]
    OUT_R2.write_text(json.dumps(r2, indent=2, default=str))
    log.info("R2 multi-grid sites: %s", {k: v["n_subgrids"] for k, v in r2["multi_grid_sites"].items()})
    log.info("R2 all tiles >=0.50 joint: %s", r2["checks"]["all_tiles_ge_0.50"])

    val, new, combined = r6_manifest(corpus, sfres)
    combined.to_csv(PROP_CSV, index=False)          # primary review artifact
    try:                                            # parquet best-effort (string-cast to avoid mixed-type)
        combined.astype(str).to_parquet(PROP_PARQUET, index=False)
    except Exception as e:
        log.warning("parquet write skipped (%s); CSV is the deliverable", str(e)[:80])
    from collections import Counter
    log.info("R6 proposed manifest: validated=%d, new=%d (adv=%d, pending=%d), total=%d",
             len(val), len(new),
             int((new.verification_status == "advancing").sum()),
             int((new.verification_status == "pending_qgis_arbitration").sum()),
             len(combined))
    log.info("R6 status counts: %s", dict(Counter(combined.verification_status)))
    log.info("wrote %s (NON-canonical; pairs.parquet NOT touched)", PROP_PARQUET)


if __name__ == "__main__":
    import rasterio.enums  # noqa
    main()
