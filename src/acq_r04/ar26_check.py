"""ACQ-R04 — AR26 name-collision check (steering ruling on the AR26 HOLD, 2026-10-03).  Builds nothing.

1. Re-fetch both NCEI copies of AR26 9999.all.mb58.gz (MB/em710, MB/em122) to scratch under distinct names with the
   ACQ-R01 fetch_one method (byte-exact vs Content-Length, gzip -t, sha256); compare each sha256 with its entry in OAK
   raw_lr_swath/AR26/fetch_manifest.json (matched by URL).
2. Product window of AR26__MGDS_31838 exactly as build_products_v2_1.build(): V1.lr_window(<pair dir>/lr.tif)
   (lr.tif bounds padded by max(2000 m, 3 x median |depth|), to EPSG:4326).  The lr.tif path is the one the v2.1
   products.json records.
3. Per copy: `mblist -F58 -I <file> -MA -R <window> -O XYZDG,AFNM` (the builder's command, V1.MBLIST_O), through the
   bounded/retried/loud wrapper; count valid soundings in the window, those inside the lr.tif grid, the lr.tif cells
   they hit, and the fraction of the grid's cells (and of its valid cells) covered.
4. NCEI sonar subdirectory of every AR26 file in the OAK fetch manifest (from its URL).
Writes ar26_check.json.  Usage (Slurm): python -m src.acq_r04.ar26_check
"""
from __future__ import annotations

import gzip
import io
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
import rasterio
import requests

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r01 import build_products as V1
from src.acq_r01 import fetch_swath as FS

PAIR = "AR26__MGDS_31838"
CR = "AR26"
BASE = "https://data.ngdc.noaa.gov/platforms/ocean/ships/neil_armstrong/AR26/multibeam/data/version1/MB/"
COPIES = {"em710": BASE + "em710/9999.all.mb58.gz", "em122": BASE + "em122/9999.all.mb58.gz"}
OUT = R.SCR / "acq_r04_ar26_check"


def main():
    C.assert_no_lockbox([PAIR])
    man = json.loads((C.RAW_SWATH_OAK / CR / "fetch_manifest.json").read_text())
    by_url = {f["url"]: f for f in man["files"]}
    # 1. fetch
    FS.C.RAW_SWATH_OAK = OUT                        # fetch_one writes under <RAW_SWATH_OAK>/<cruise>/
    sess = requests.Session(); res = {}
    for sub, url in COPIES.items():
        r = FS.fetch_one({"cruise": CR, "filename": f"{sub}__9999.all.mb58.gz", "url": url, "advertised": 0, "kind": "swath"}, sess)
        m = by_url.get(url, {})
        res[sub] = {"url": url, "local": str(OUT / CR / f"{sub}__9999.all.mb58.gz"), "status": r["status"], "content_length": r["head_content_length"],
                    "received": r["received"], "bytes_match_content_length": r["received"] == r["head_content_length"], "gzip_ok": r["gzip_ok"],
                    "sha256": r["sha256"], "manifest_sha256": m.get("sha256"), "manifest_size": m.get("size"),
                    "sha256_matches_manifest": r["sha256"] == m.get("sha256")}
    FS.C.RAW_SWATH_OAK = C.OAK / "raw_lr_swath"
    # 2. window, as build_products_v2_1.build()
    pj = json.loads((C.OAK / "harmonized" / PAIR / "ship_products_v2_1" / "products.json").read_text())
    lr_path = Path(pj["lr_tif_path"])
    geom = V1.lr_window(lr_path)
    w, e, s, n = geom["window"]
    ny, nx = geom["shape"]; tr = geom["transform"]
    lr_valid = np.isfinite(geom["lr"])
    to = pyproj.Transformer.from_crs("EPSG:4326", geom["crs"], always_xy=True)
    # 3. mblist per copy
    wd = Path(os.environ.get("L_SCRATCH", "/tmp")) / "ar26_check"; wd.mkdir(parents=True, exist_ok=True)
    for sub, rr in res.items():
        local = wd / f"{sub}__9999.all.mb58"
        with gzip.open(rr["local"], "rb") as a, local.open("wb") as b:
            shutil.copyfileobj(a, b)
        args = ["mblist", "-F58", "-I", local.name, "-MA", "-R", f"{w:.6f}/{e:.6f}/{s:.6f}/{n:.6f}", "-O", V1.MBLIST_O]
        outp = wd / f"{sub}.txt"
        _, att, cmd = R.mb_bounded(args, wd, timeout=2400, stdout_path=outp)
        txt = outp.read_bytes()
        a = pd.read_csv(io.BytesIO(txt), sep="\t", header=None, names=V1.COLS, dtype="float64") .to_numpy() if txt.strip() else np.zeros((0, len(V1.COLS)))
        x, y = to.transform(a[:, 0], a[:, 1]) if len(a) else (np.zeros(0), np.zeros(0))
        col = np.floor((np.asarray(x) - tr.c) / tr.a).astype(int); row = np.floor((np.asarray(y) - tr.f) / tr.e).astype(int)
        inside = (row >= 0) & (row < ny) & (col >= 0) & (col < nx) & np.isfinite(a[:, 2]) if len(a) else np.zeros(0, bool)
        cells = set(zip(row[inside].tolist(), col[inside].tolist()))
        cv = sum(1 for r_, c_ in cells if lr_valid[r_, c_])
        # whole-file extent (for context): mblist without -R would be needed; record the window soundings only
        rr.update({"mblist_command": f"(cd {wd} && {cmd})", "mblist_attempts": att, "soundings_in_window": int(len(a)),
                   "soundings_inside_lr_grid": int(inside.sum()), "lr_cells_hit": len(cells), "lr_cells_total": int(ny * nx),
                   "lr_cells_valid": int(lr_valid.sum()), "frac_of_grid_cells": round(len(cells) / (ny * nx), 6),
                   "frac_of_valid_lr_cells": round(cv / max(1, int(lr_valid.sum())), 6), "lr_valid_cells_hit": cv,
                   "pings_in_window": int(len(set(zip(a[:, 7].tolist(), a[:, 8].tolist())))) if len(a) else 0})
    # 4. sonar subdirectory of every file in the AR26 manifest
    subs = Counter(f["url"].rstrip("/").split("/")[-2] for f in man["files"])
    per_file = [{"file": f.get("filename") or f.get("name"), "subdir": f["url"].split("/")[-2], "size": f.get("size"), "sha256": str(f.get("sha256"))[:12]}
                for f in man["files"]]
    out = {"generated": R.utc_now(), "pair": PAIR, "lr_tif_path": str(lr_path), "window_wesn": [w, e, s, n], "margin_m": geom["margin_m"],
           "lr_grid": {"crs": geom["crs"].to_string(), "shape": [ny, nx], "cell_m": abs(tr.a)}, "copies": res,
           "oak_file": {"path": str(C.RAW_SWATH_OAK / CR / "9999.all.mb58.gz"), "size": os.stat(C.RAW_SWATH_OAK / CR / "9999.all.mb58.gz").st_size},
           "manifest_subdir_counts": dict(subs), "manifest_files": per_file, "code_commit": C.git_commit()}
    R.write_json(R.REPORT_DIR / "ar26_check.json", out)
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
