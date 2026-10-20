#!/usr/bin/env python3
"""Open one pair's grids and its tile rows from the released package, and reproduce that pair's frozen s_lr rho.
Usage: python load_pair.py <package_dir> <pair_id>        (needs rasterio, pandas, pyarrow, numpy, scipy)
The rule is the frozen scorer's (CNN repo phase4_score.py score_pair): Spearman(s_lr, A_fine) on interior tiles if at
least MIN_TILES tiles fall in at least bmin 4x4-tile blocks, else Spearman(s_lr, A_fine_int) on tiles with a defined
A_fine_int under the same counts; otherwise the pair is not scorable (rho still shown for the larger subset)."""
import json, sys, zipfile
import numpy as np, pandas as pd, rasterio
from scipy.stats import spearmanr

MIN_TILES = 10
root, pair = sys.argv[1], sys.argv[2]
zpath = f"{root}/{pair}.zip"
meta = json.loads(zipfile.ZipFile(zpath).read("pair.json"))
for name in ("hr.tif", "lr.tif", "joint_valid.tif"):
    with rasterio.open(f"zip://{zpath}!{name}") as ds:
        print(f"{name:16s} {ds.width}x{ds.height} px, {abs(ds.res[0]):.3f} m, {ds.crs}, nodata={ds.nodata}, overviews={ds.overviews(1)}")

t = pd.read_parquet(f"{root}/tiles.parquet")
t = t[(t.pair == pair) & (~t.excluded_r17.astype(bool))]
t = t[np.isfinite(t.A_fine.values)]


def rho(p, y):
    ok = np.isfinite(p) & np.isfinite(y)
    if ok.sum() < 3 or np.std(p[ok]) == 0 or np.std(y[ok]) == 0:
        return float("nan")
    return float(spearmanr(p[ok], y[ok])[0])


def n_blocks(d):
    return len(set(zip(d.r0.values // 128 // 4, d.c0.values // 128 // 4)))


sc = meta.get("scoring") or {}
bmin = int(sc.get("bmin") or 8)
vi, vf = t[t.interior.astype(bool)], t[np.isfinite(t.A_fine_int.values)]
if len(vi) >= MIN_TILES and n_blocks(vi) >= bmin:
    view, tab, tgt = "interior", vi, "A_fine"
elif len(vf) >= MIN_TILES and n_blocks(vf) >= bmin:
    view, tab, tgt = "fallback", vf, "A_fine_int"
else:
    view = "not_scorable"
    tab = vi if len(vi) >= MIN_TILES else (vf if len(vf) >= MIN_TILES else None)
    tgt = "A_fine" if len(vi) >= MIN_TILES else "A_fine_int"
r = rho(tab.s_lr.values.astype(float), tab[tgt].values.astype(float)) if tab is not None else float("nan")
frozen = sc.get("rho_s_lr")
match = (frozen is not None and np.isfinite(r) and abs(r - frozen) < 5e-4) or (frozen is None and not np.isfinite(r))
print(f"tiles={len(t)} view={view} target={tgt} n_scored={0 if tab is None else len(tab)} rho_s_lr={r:.6f} frozen={frozen} "
      f"frozen_view={sc.get('view')} match_3dp={match}")
print(json.dumps({"pair": pair, "view": view, "n_scored": 0 if tab is None else int(len(tab)), "rho_s_lr": r, "frozen": frozen, "match_3dp": bool(match)}))
