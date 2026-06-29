"""Regenerate valid_tiles.parquet for the FULL 39-pair corpus (directive §8).

READ-ONLY over every pair's joint_valid.tif: tile the HR grid into 256-px squares,
keep a tile iff its joint_valid fraction >= 0.50 (same rule + geometry as the Stage
F5 tiler, stage_f5_valid_masks._tile_rows). The previous index covered only ~29
pairs (the new pairs that had joint_valid); now that all 39 carry joint_valid the
index spans the whole corpus. Reports per-pair tile counts; every pair is listed,
explicitly zero if it contributes none.

Backs up the existing parquet first. Writes nothing into the harmonized dirs.
Run on a compute node (sbatch).
"""
from __future__ import annotations
import json, logging, shutil
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio

from src.discovery.validated_anchor import is_new, is_validated
from src.discovery.stage_unify_valid_masks import resolve_dir, SCR_HARM

log = logging.getLogger("unify_tiles")
REPO = Path(__file__).resolve().parents[2]
CANON = REPO / "manifest/pairs.parquet"
TILES = REPO / "reports/discovery/valid_tiles.parquet"
RESULT = REPO / "reports/discovery/stage_unify_valid_tiles_result.json"

TILE_PX = 256
TILE_MIN_FRACTION = 0.50


def tile_pair(pid: str, jv_path: Path) -> tuple[list, int]:
    with rasterio.open(jv_path) as ds:
        jv = ds.read(1)
        nodata = ds.nodata
        tr = ds.transform
        crs = str(ds.crs)
    valid = (jv == 1)            # masks are {0,1} with 255 nodata
    H, W = valid.shape
    rows, n_total = [], 0
    for r0 in range(0, H, TILE_PX):
        for c0 in range(0, W, TILE_PX):
            tile = valid[r0:r0 + TILE_PX, c0:c0 + TILE_PX]
            if tile.size < TILE_PX * TILE_PX:
                continue            # only full tiles enter the index (matches F5)
            n_total += 1
            frac = float(tile.mean())
            if frac < TILE_MIN_FRACTION:
                continue
            minx, maxy = tr * (c0, r0)
            maxx, miny = tr * (c0 + TILE_PX, r0 + TILE_PX)
            rows.append({
                "pair_id": pid, "row0": int(r0), "col0": int(c0),
                "tile_px": TILE_PX, "joint_valid_fraction": round(frac, 4),
                "minx": float(minx), "miny": float(miny),
                "maxx": float(maxx), "maxy": float(maxy), "crs": crs,
            })
    return rows, n_total


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    df = pd.read_parquet(CANON)
    all_rows, per_pair = [], []
    for pid in df.pair_id:
        d = resolve_dir(SCR_HARM, pid)
        jv = d / "joint_valid.tif"
        if not jv.exists():
            per_pair.append({"pair_id": pid, "n_valid_tiles": 0, "n_total_tiles": 0,
                             "status": "MISSING_joint_valid",
                             "class": "validated" if is_validated(pid) else "new"})
            log.error("%-46s MISSING joint_valid.tif", pid)
            continue
        rows, n_total = tile_pair(pid, jv)
        all_rows.extend(rows)
        per_pair.append({"pair_id": pid, "n_valid_tiles": len(rows),
                         "n_total_tiles": n_total, "status": "ok",
                         "class": "validated" if is_validated(pid) else "new"})
        log.info("%-46s tiles=%4d / %4d full", pid, len(rows), n_total)

    if TILES.exists():
        bk = TILES.with_suffix(".parquet.bak_2026-06-29_unify")
        if not bk.exists():
            shutil.copy2(TILES, bk)
            log.info("backed up tiles -> %s", bk.name)
    out_df = pd.DataFrame(all_rows)
    out_df.to_parquet(TILES, index=False)

    n_pairs_with_tiles = len({r["pair_id"] for r in all_rows})
    missing = [p["pair_id"] for p in per_pair if p["status"] != "ok"]
    res = {
        "ok": len(missing) == 0,
        "n_pairs_total": int(len(df)),
        "n_pairs_with_tiles": n_pairs_with_tiles,
        "n_pairs_zero_tiles": sum(1 for p in per_pair if p["status"] == "ok" and p["n_valid_tiles"] == 0),
        "n_tiles_total": len(all_rows),
        "missing_joint_valid": missing,
        "per_pair": per_pair,
        "tile_px": TILE_PX, "min_fraction": TILE_MIN_FRACTION,
    }
    RESULT.write_text(json.dumps(res, indent=2, default=str))
    log.info("=== TILES: %d tiles over %d/%d pairs (%d zero-tile, %d missing-mask) -> %s ===",
             len(all_rows), n_pairs_with_tiles, len(df), res["n_pairs_zero_tiles"],
             len(missing), TILES)


if __name__ == "__main__":
    main()
