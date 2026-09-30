"""ACQ-R02 §6.3 — stage-C gridding of a newly fetched LR cruise (MB-System 5.8.2beta06, raw mode).

Per cruise, exactly the stage C full-run recipe (stage_c_full.py): decompress the swath from OAK
raw_lr_swath/<cruise>/ to L_SCRATCH, datalist, footprint-local median depth (mblist -R over the HR
footprint bbox), cell = 2 * depth * tan(beamwidth/2) (documented beam footprint; C2a standard),
`mbgrid -A2 -G3 -F1 -C0 -M` over the union of the served HR footprints + 1 km margin, raw mode
(C-full-0).  New: the union grid AND the -M count/SD grids are persisted on OAK raw_lr_gridded/.

Usage (Slurm): python -m src.acq_r01.grid_lr --cruise <cruise> --hr MGDS:5174[,MGDS:...] [--sonar "Kongsberg EM122"]
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import math
import os
import re
import shutil
import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from shapely.ops import unary_union

from src.acq_r01 import common as C
from src.acq_r01.build_products import fmt_for, swath_files

log = logging.getLogger("acq_r02.grid")
R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"
GRIDDED = C.OAK / "raw_lr_gridded"
BEAMWIDTH = [("em122", 1.0), ("em120", 1.0), ("em124", 1.0), ("em302", 1.0), ("em304", 1.0), ("em300", 1.0), ("em710", 1.0), ("em712", 1.0),
             ("em1002", 2.0), ("em2040", 1.0), ("seabeam 2100", 2.0), ("seabeam 2112", 2.0), ("seabeam 2000", 3.3), ("seabeam 3012", 1.5),
             ("seabeam 3050", 1.5), ("seabeam1050", 1.5), ("seabeam 1050", 1.5), ("hydrosweep", 2.3), ("seabeam", 2.0), ("reson", 1.0)]
DEFAULT_BW = 1.5


def beamwidth_for(sonar: str):
    s = (sonar or "").lower()
    for k, v in BEAMWIDTH:
        if k in s:
            return v, k
    return DEFAULT_BW, "default"


def prepare(cruise: str, wd: Path):
    src = C.RAW_SWATH_OAK / cruise
    files = swath_files(src)
    wd.mkdir(parents=True, exist_ok=True)
    fmt = fmt_for(files[0].name)
    dl = wd / "datalist.mb-1"
    with dl.open("w") as f:
        for p in files:
            out = wd / (p.name[:-3] if p.name.endswith(".gz") else p.name)
            if not out.exists():
                if p.name.endswith(".gz"):
                    with gzip.open(p, "rb") as s, out.open("wb") as d:
                        shutil.copyfileobj(s, d, 1 << 22)
                else:
                    out.symlink_to(p)
            f.write(f"{out.name} {fmt}\n")
    return dl, files, fmt


def footprint_depth(dl: Path, wd: Path, poly) -> float:
    w, s, e, n = poly.bounds
    r = C.mb(["mblist", "-I", dl.name, "-OXYZ", "-R", f"{w}/{e}/{s}/{n}"], cwd=str(wd))
    d = []
    for ln in (r.stdout or "").splitlines()[:300000]:
        p = ln.split()
        if len(p) >= 3:
            try:
                d.append(abs(float(p[2])))
            except ValueError:
                pass
    return float(np.median(d)) if d else float("nan")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cruise", required=True); ap.add_argument("--hr", required=True); ap.add_argument("--sonar", default="")
    ap.add_argument("--cell-m", type=float, default=None, help="override the documented-beam-footprint cell")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    C.assert_no_lockbox_cruise([a.cruise])
    t0 = time.time()
    fps = gpd.read_file(R02 / "verification" / "hr_footprints.gpkg").set_index("hr_id")
    hrs = a.hr.split(","); union = unary_union([fps.loc[h].geometry for h in hrs])
    wd = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r02_grid" / a.cruise
    dl, files, fmt = prepare(a.cruise, wd)
    depth = footprint_depth(dl, wd, union)
    bw, bw_key = beamwidth_for(a.sonar)
    if not math.isfinite(depth):
        depth = 2000.0; log.warning("no soundings inside footprint bbox; depth fallback 2000 m")
    cell = a.cell_m or 2.0 * depth * math.tan(math.radians(bw / 2))
    w, s, e, n = union.bounds; mlat = (s + n) / 2
    dlon = 1 / (111320 * max(0.2, math.cos(math.radians(mlat)))); dlat = 1 / 111320
    R = f"{w - 1000 * dlon}/{e + 1000 * dlon}/{s - 1000 * dlat}/{n + 1000 * dlat}"
    root = f"grid_{a.cruise}"
    cmd = ["mbgrid", "-I", dl.name, "-O", root, "-R", R, "-E", f"{cell * dlon}/{cell * dlat}/degrees", "-A2", "-G3", "-F1", "-C0", "-M"]
    r = C.mb(cmd, cwd=str(wd))
    grd = wd / f"{root}.grd"
    if not grd.exists():
        log.error("mbgrid produced no grid: %s", (r.stderr or r.stdout)[-400:]); return 1
    GRIDDED.mkdir(exist_ok=True)
    outs = {}
    for suf in ("", "_num", "_sd"):
        src = wd / f"{root}{suf}.grd"
        if src.exists():
            dst = GRIDDED / f"{a.cruise}__union{suf}.grd"
            if dst.exists():
                dst.chmod(0o644)
            shutil.copyfile(src, dst); dst.chmod(0o444); outs[suf or "grid"] = str(dst)
    # fill over each HR footprint
    with rasterio.open(str(grd)) as ds:
        arr = ds.read(1, masked=True).filled(np.nan); tr = ds.transform
    fills = {}
    for h in hrs:
        inpoly = ~geometry_mask([fps.loc[h].geometry], out_shape=arr.shape, transform=tr, invert=False)
        fills[h] = round(float((np.isfinite(arr) & inpoly).sum() / max(1, inpoly.sum())), 4)
    rec = {"cruise": a.cruise, "hr": hrs, "n_files": len(files), "format": fmt, "sonar": a.sonar, "beamwidth_deg": bw, "beamwidth_key": bw_key,
           "footprint_depth_m": round(depth, 1), "cell_m": round(cell, 2), "region": R, "mbgrid_command": C.mb_cmdline(cmd), "mode": "raw",
           "outputs": outs, "fill_fraction_per_hr": fills, "grid_depth_median": round(float(np.nanmedian(arr)), 1) if np.isfinite(arr).any() else None,
           "wall_s": round(time.time() - t0, 1), "mbsystem": C.MBSYSTEM_VERSION, "code_commit": C.git_commit()}
    (R02 / "grid").mkdir(exist_ok=True)
    (R02 / "grid" / f"{a.cruise}.json").write_text(json.dumps(rec, indent=1))
    shutil.rmtree(wd, ignore_errors=True)
    log.info("%s", json.dumps(rec)); return 0


if __name__ == "__main__":
    sys.exit(main())
