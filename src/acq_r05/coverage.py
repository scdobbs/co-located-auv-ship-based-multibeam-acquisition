"""ACQ-R05 §4 — coverage report for the CNN repo's window choice (data availability only; nothing is scored).

For each pair and W in {16, 32, 64} ship cells: W x W context cells centred on the centre of each tiles_v1.1 tile of the
pair (tile centres from the CNN repo's tiles_v1_1.parquet, tag phase0-freeze, sha256 verified; tile bounds are in the
pair's UTM CRS = lr.tif's CRS), the fraction of tiles whose window has >= 50 % valid ctx_lr cells, the median valid
fraction per window, and the window's ground size.  Window cells outside the context grid count as invalid.
Per pair and per unit (tile-weighted).  Usage: python -m src.acq_r05.coverage  -> coverage_v1.{json,csv}
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
import rasterio

from src.acq_r05 import common as R


def windows_for_pair(pid: str, tiles: pd.DataFrame) -> dict:
    out_dir = R.context_dir(pid)
    with rasterio.open(out_dir / "ctx_lr_valid.tif") as ds:
        valid = ds.read(1).astype(bool); t = ds.transform; crs = ds.crs.to_string()
    tt = tiles[tiles.pair == pid]
    if tt.crs.nunique() != 1 or tt.crs.iloc[0] != crs:
        raise RuntimeError(f"{pid}: tile CRS {tt.crs.unique()} != context CRS {crs}")
    cx = (tt.left.to_numpy() + tt.right.to_numpy()) / 2; cy = (tt.bottom.to_numpy() + tt.top.to_numpy()) / 2
    col = np.floor((cx - t.c) / t.a).astype(int); row = np.floor((cy - t.f) / t.e).astype(int)
    H, W_ = valid.shape
    # integral image for O(1) window sums
    ii = np.zeros((H + 1, W_ + 1), "int64"); ii[1:, 1:] = np.cumsum(np.cumsum(valid, 0), 1)
    rec = {"pair_id": pid, "unit": R.UNIT_OF[pid], "n_tiles": int(len(tt)), "cell_m": float(t.a), "context_shape": [H, W_],
           "n_tile_centres_inside_context": int(((row >= 0) & (row < H) & (col >= 0) & (col < W_)).sum())}
    per_tile = {}
    for W in R.WINDOWS:
        r0 = row - W // 2; c0 = col - W // 2; r1 = r0 + W; c1 = c0 + W
        rr0 = np.clip(r0, 0, H); rr1 = np.clip(r1, 0, H); cc0 = np.clip(c0, 0, W_); cc1 = np.clip(c1, 0, W_)
        s = ii[rr1, cc1] - ii[rr0, cc1] - ii[rr1, cc0] + ii[rr0, cc0]
        frac = s / float(W * W)
        per_tile[W] = frac
        rec[f"W{W}_ground_km"] = W * float(t.a) / 1000.0
        rec[f"W{W}_frac_tiles_ge50"] = float(np.mean(frac >= 0.5)) if len(frac) else None
        rec[f"W{W}_median_valid_frac"] = float(np.median(frac)) if len(frac) else None
        rec[f"W{W}_frac_tiles_full"] = float(np.mean(frac >= 0.999)) if len(frac) else None
    return rec, pd.DataFrame({"pair": pid, "unit": R.UNIT_OF[pid], "tile_id": tt.tile_id.to_numpy(), **{f"W{W}_valid_frac": per_tile[W] for W in R.WINDOWS}})


def main(argv=None):
    hashes = R.check_fixed_inputs()
    tiles = pd.read_parquet(R.TILES_V1_1, columns=["unit", "pair", "tile_id", "left", "bottom", "right", "top", "crs"])
    rows, per = [], []
    for pid in R.PAIRS_IN_SCOPE:
        if not (R.context_dir(pid) / "ctx_lr_valid.tif").exists():
            rows.append({"pair_id": pid, "unit": R.UNIT_OF[pid], "status": "context not built"}); continue
        rec, df = windows_for_pair(pid, tiles); rec["status"] = "ok"; rows.append(rec); per.append(df)
    pairs = pd.DataFrame(rows)
    tiles_all = pd.concat(per, ignore_index=True) if per else pd.DataFrame()
    units = []
    if len(tiles_all):
        for u, g in tiles_all.groupby("unit"):
            rec = {"unit": u, "n_pairs": int(g.pair.nunique()), "n_tiles": int(len(g))}
            cell = pairs[pairs.unit == u].cell_m
            for W in R.WINDOWS:
                f = g[f"W{W}_valid_frac"]
                rec[f"W{W}_frac_tiles_ge50"] = float((f >= 0.5).mean()); rec[f"W{W}_median_valid_frac"] = float(f.median())
                rec[f"W{W}_ground_km_min"] = float(W * cell.min() / 1000); rec[f"W{W}_ground_km_max"] = float(W * cell.max() / 1000)
            units.append(rec)
    units = pd.DataFrame(units)
    R.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pairs.to_csv(R.REPORT_DIR / "coverage_v1_pairs.csv", index=False); units.to_csv(R.REPORT_DIR / "coverage_v1_units.csv", index=False)
    tiles_all.to_parquet(R.REPORT_DIR / "coverage_v1_tiles.parquet", index=False)
    summary = {"generated": R.utc_now(), "tiles_v1_1_sha256": hashes["tiles_v1_1.parquet"], "windows": list(R.WINDOWS), "n_pairs_built": int((pairs.status == "ok").sum()),
               "n_pairs_not_built": int((pairs.status != "ok").sum()), "n_tiles": int(len(tiles_all)), "code_commit": R.git_commit()}
    for W in R.WINDOWS:
        if len(tiles_all):
            f = tiles_all[f"W{W}_valid_frac"]
            summary[f"W{W}"] = {"frac_tiles_ge50_all": float((f >= 0.5).mean()), "median_valid_frac_all": float(f.median()),
                                "min_pair_frac_tiles_ge50": float(pairs[pairs.status == "ok"][f"W{W}_frac_tiles_ge50"].min()),
                                "n_pairs_all_tiles_ge50": int((pairs[pairs.status == "ok"][f"W{W}_frac_tiles_ge50"] >= 0.999).sum())}
    (R.REPORT_DIR / "coverage_v1.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, indent=1)); print(pairs.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
