"""ACQ-R04 §3.3–3.4 — per cruise: tile soundings into 10 km UTM blocks, grid each block with the stage-C recipe,
build contract-v2.1 ship products on each kept block.

Per cruise (raw swath already on scratch, fetch manifest complete):
  1. Decompress the planned (dominant-format) swath files to node-local scratch.
  2. Coverage pass: ONE container call streams `mblist -F<fmt> -I <file> -MA -OXYZ` for every file (all valid beams:
     lon, lat, topography positive-up).  Each sounding goes to the UTM zone of its own longitude/hemisphere and to the
     10 km x 10 km block floor(E/10 km), floor(N/10 km) of that zone.  Per block: sounding count and a 0.1 m depth
     histogram (median depth = its 50th percentile, resolution 0.1 m); per file: lon/lat bounds and soundings.
     Soundings poleward of 84 N / 80 S (no UTM) are counted and dropped (ledger).
  3. Block candidates: median depth in [300, 6500] m, and the block polygon at least the threshold from every
     exclusion_v1 geometry (block-level guard, distances in the block's UTM; 10 km to HR footprints and lockbox LR
     cruise footprints (+1.113 km NCEI simplification tolerance for the latter), 50 km to lockbox centroids).
  4. Grid each candidate: cell = 2 * median_depth * tan(bw / 2) (bw from the cruise's NCEI instrument, ACQ-R02
     grid_lr.beamwidth_for), over the files whose sounding bounds reach the block (+2 km); raw soundings.
     GRID_MODE "dev_chain" (default; steering ruling 2026-10-03) reproduces the development lr.tif chain:
     geographic `mbgrid -R <block lon/lat bounds +/- 1 km> -E dx/dy/degrees -A2 -G3 -F1 -C0 -M` (stage C), then the
     stage-F warp to the block's UTM zone (bilinear, GDAL default output grid) and a clip to the block.
     "direct_utm" (pilot v0): `mbgrid -R e0/e1/n0/n1 -J UTM<zz><N|S> -E cell/cell/meters ...`.
  5. Keep if fill (finite cells / grid cells) >= 0.50.  Write grid.tif (float32, NaN nodata, positive up, block UTM CRS),
     block.json, and `lr.tif -> grid.tif` (the role the contract builder reads).
  6. Products: src.acq_r03.build_products_v2_1.build() UNCHANGED, items=[(block_id, block_dir)], cruise_dir = a staging
     directory of symlinks to the same compressed raw files (+ their fetch-manifest rows); no frame offset (block ids are
     not in the ACQ-R03 header check).  Usable = every `available` true and QA flags empty (contract v2.1 §6).
Every block of the cruise ends in the block ledger with its status; MB-System failures are loud (common.mb_bounded).
Usage (Slurm): python -m src.acq_r04.blocks --cruise EW9703 [--grid-workers 4 --prod-workers 4]
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import rasterio
from shapely.geometry import box
from shapely.ops import transform as shp_transform
from shapely.strtree import STRtree

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r01.build_products import fmt_for, swath_files
from src.acq_r01.grid_lr import beamwidth_for

log = logging.getLogger("acq_r04.blocks")
BIN = 0.1                       # depth histogram resolution (m)
FILE_MARK = b"#F "
ERR_MARK = b"#ERR "


def cdir_name(cruise: str) -> str:
    return cruise.replace("/", "_")


def zone_code(lon, lat):
    z = np.floor((np.asarray(lon) + 180.0) % 360.0 / 6.0).astype("int64") + 1
    z = np.clip(z, 1, 60)
    return z * 2 + (np.asarray(lat) < 0).astype("int64")        # even = N, odd = S


def zone_epsg(zc: int) -> int:
    z, s = divmod(int(zc), 2)
    return (32700 if s else 32600) + z


def zone_label(zc: int) -> str:
    z, s = divmod(int(zc), 2)
    return f"{z:02d}{'S' if s else 'N'}"


_TR = {}


def _tr(zc):
    if zc not in _TR:
        _TR[zc] = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{zone_epsg(zc)}", always_xy=True)
    return _TR[zc]


def block_id(zc, ei, ni) -> str:
    return f"{zone_label(zc)}_E{int(ei):03d}_N{int(ni):04d}"


def parse_block_id(bid):
    m = re.match(r"(\d\d)([NS])_E(\d+)_N(\d+)$", bid)
    z, h, ei, ni = int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4))
    return z * 2 + (h == "S"), ei, ni


# --------------------------------------------------------------------------- #
# coverage pass
# --------------------------------------------------------------------------- #
class Coverage:
    def __init__(self):
        self.blocks = {}      # (zc, ei, ni) -> {"n": int, "off": int, "hist": np.ndarray(int64)}
        self.files = {}       # name -> {"n": int, "bounds": [w, s, e, n], "polar": int}
        self.polar = 0
        self.unparsed = 0     # mblist output lines with a non-numeric token (dropped, counted)

    def add_file(self, name, arr):
        """arr: (n, 3) lon, lat, topo.  Adds every sounding to its block histogram."""
        lon, lat, z = arr[:, 0], arr[:, 1], arr[:, 2]
        ok = np.isfinite(lon) & np.isfinite(lat) & np.isfinite(z)
        lon, lat, z = lon[ok], lat[ok], z[ok]
        polar = (lat > 84.0) | (lat < -80.0)
        rec = self.files.setdefault(name, {"n": 0, "bounds": [180.0, 90.0, -180.0, -90.0], "polar": 0})
        rec["polar"] += int(polar.sum()); self.polar += int(polar.sum())
        if lon.size:
            b = rec["bounds"]
            rec["bounds"] = [min(b[0], float(lon.min())), min(b[1], float(lat.min())), max(b[2], float(lon.max())), max(b[3], float(lat.max()))]
        lon, lat, z = lon[~polar], lat[~polar], z[~polar]
        rec["n"] += int(lon.size)
        if not lon.size:
            return
        zc = zone_code(lon, lat)
        depth_bin = np.floor(-z / BIN).astype("int64")
        for c in np.unique(zc):
            sel = zc == c
            e, n = _tr(int(c)).transform(lon[sel], lat[sel])
            ei = np.floor(np.asarray(e) / R.BLOCK_M).astype("int64"); ni = np.floor(np.asarray(n) / R.BLOCK_M).astype("int64")
            key = ei * 100000 + ni
            db = depth_bin[sel]
            order = np.argsort(key, kind="stable")
            key_s, db_s = key[order], db[order]
            uk, start = np.unique(key_s, return_index=True)
            stops = np.r_[start[1:], key_s.size]
            for k, a, b in zip(uk, start, stops):
                seg = db_s[a:b]
                lo = int(seg.min()); h = np.bincount(seg - lo)
                bk = (int(c), int(k // 100000), int(k % 100000))
                cur = self.blocks.get(bk)
                if cur is None:
                    self.blocks[bk] = {"n": int(seg.size), "off": lo, "hist": h.astype("int64")}
                else:
                    off = min(cur["off"], lo); top = max(cur["off"] + cur["hist"].size, lo + h.size)
                    nh = np.zeros(top - off, "int64")
                    nh[cur["off"] - off: cur["off"] - off + cur["hist"].size] += cur["hist"]
                    nh[lo - off: lo - off + h.size] += h
                    cur["off"], cur["hist"] = off, nh; cur["n"] += int(seg.size)

    @staticmethod
    def median_depth(b):
        c = np.cumsum(b["hist"]); half = (b["n"] + 1) / 2.0
        i = int(np.searchsorted(c, half))
        return (b["off"] + i + 0.5) * BIN


def _events(buf: bytes):
    """Ordered events of a chunk (cut at a newline): ('start', name) for '#F name', ('err', name) for '#ERR name',
    ('data', bytes) for sounding lines between markers."""
    ev, pos = [], 0
    for m in re.finditer(rb"^#(F|ERR) ([^\n]*)\n", buf, flags=re.M):
        if m.start() > pos:
            ev.append(("data", buf[pos:m.start()]))
        ev.append(("start" if m.group(1) == b"F" else "err", m.group(2).decode()))
        pos = m.end()
    if pos < len(buf):
        ev.append(("data", buf[pos:]))
    return ev


def _parse_xyz(x: bytes, cov) -> np.ndarray:
    """lon/lat/topo lines -> float array.  Fast path float64; if any token is not numeric (seen on KN199-02), coerce
    and drop those lines, counting them in cov.unparsed (recorded in the cruise record, never silent)."""
    try:
        return pd.read_csv(io.BytesIO(x), sep="\t", header=None, names=["lon", "lat", "topo"], dtype="float64",
                           engine="c", on_bad_lines="skip").to_numpy()
    except ValueError:
        d = pd.read_csv(io.BytesIO(x), sep="\t", header=None, names=["lon", "lat", "topo"], dtype=str, engine="c", on_bad_lines="skip")
        d = d.apply(pd.to_numeric, errors="coerce")
        bad = d.isna().any(axis=1)
        cov.unparsed += int(bad.sum())
        return d[~bad].to_numpy(dtype="float64")


def coverage_pass(wd: Path, names, fmt, timeout_s=48 * 3600, attempts=6):
    """One streamed container call over all files ('#F name' before each file's mblist output, '#ERR name' after a
    failed mblist, '#F __END__' at the end).  A file's soundings are committed only when the next '#F' marker closes
    it without an '#ERR'; failed or unclosed files (container failure/stall) are re-run in a new call (bounded, with
    a growing pause); exhausting the retries raises (never counted as 'no soundings')."""
    import threading
    cov = Coverage(); todo = list(names); cmds = []; attempts_log = []
    for attempt in range(attempts):
        if not todo:
            break
        script = "for f in " + " ".join(shlex.quote(n) for n in todo) + \
                 f"; do printf '\\n#F %s\\n' \"$f\"; mblist -F{fmt} -I \"$f\" -MA -OXYZ || printf '\\n#ERR %s\\n' \"$f\"; done; printf '\\n#F __END__\\n'"
        sp = wd / f"coverage_attempt{attempt + 1}.sh"          # script in a file: one argv string is capped at 128 KB
        sp.write_text(script + "\n")
        cmd = ["apptainer", "exec", *C.BIND, C.SANDBOX, "sh", sp.name]
        cmds.append(f"(cd {wd} && apptainer exec {' '.join(C.BIND)} {C.SANDBOX} sh -c 'for f in <{len(todo)} files>; do mblist -F{fmt} -I $f -MA -OXYZ; done')")
        t0 = time.time()
        p = subprocess.Popen(cmd, cwd=str(wd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        err_buf = []
        th = threading.Thread(target=lambda: err_buf.append(p.stderr.read()), daemon=True); th.start()
        cur, carry, failed, done, per = None, b"", set(), set(), []
        timed_out = False
        while True:
            chunk = p.stdout.read(1 << 26)
            if time.time() - t0 > timeout_s:
                C.killpg_quietly(p); timed_out = True; break
            if not chunk:
                break
            buf = carry + chunk
            cut = buf.rfind(b"\n") + 1
            buf, carry = buf[:cut], buf[cut:]
            for kind, x in _events(buf):
                if kind == "data":
                    if cur is not None and cur != "__END__" and cur not in failed and x.strip():
                        per.append(_parse_xyz(x, cov))
                elif kind == "err":
                    failed.add(x)
                    if x == cur:
                        per = []
                else:                                   # 'start': closes the current file
                    if cur is not None and cur not in failed:
                        if per:
                            cov.add_file(cur, np.concatenate(per))
                        else:
                            cov.files.setdefault(cur, {"n": 0, "bounds": None, "polar": 0})
                        done.add(cur)
                    cur, per = x, []
        if timed_out:
            C.reap_bounded(p)
        else:
            p.wait()
        th.join(timeout=60)
        stderr = (err_buf[0] if err_buf else b"").decode(errors="replace")[-400:]
        ended = cur == "__END__"
        attempts_log.append({"attempt": attempt + 1, "files": len(todo), "committed": len(done), "failed_mblist": sorted(failed),
                             "rc": p.returncode, "ended": ended, "timed_out": timed_out, "wall_s": round(time.time() - t0, 1),
                             "stderr_tail": stderr[-200:] if not ended or failed else ""})
        if not ended or failed:
            log.warning("coverage attempt %d: %s", attempt + 1, attempts_log[-1])
        todo = [n for n in todo if n not in done]
        if todo:
            time.sleep(15 * (attempt + 1))
    if todo:
        raise R.MBFailure(f"coverage pass: mblist failed for {len(todo)} file(s) after {attempts} attempts: {todo[:5]}")
    return cov, {"commands": cmds, "attempts": attempts_log}


# --------------------------------------------------------------------------- #
# exclusion guard (block level)
# --------------------------------------------------------------------------- #
class Guard:
    def __init__(self):
        g = gpd.read_file(R.CACHE / "exclusion_geometries_v1.geojson")
        self.g = g
        self.tree = STRtree(list(g.geometry))

    def check(self, zc, ei, ni):
        """(min margin m = distance - (threshold + tolerance) over nearby geometries, nearest geometry name)."""
        epsg = zone_epsg(zc)
        bx = box(ei * R.BLOCK_M, ni * R.BLOCK_M, (ei + 1) * R.BLOCK_M, (ni + 1) * R.BLOCK_M)
        inv = pyproj.Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
        fwd = pyproj.Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
        bll = shp_transform(inv.transform, bx.segmentize(1000.0))
        w, s, e, n = bll.bounds
        pad = 0.8                       # deg: > 50 km + tolerance at any latitude where UTM is used (<= 84 deg -> 0.45 deg lat, lon/cos)
        padlon = min(20.0, pad / max(0.1, math.cos(math.radians(max(abs(s), abs(n))))))
        win = box(w - padlon, s - pad, e + padlon, n + pad)
        best, who = float("inf"), None
        for i in self.tree.query(win):
            row = self.g.iloc[i]
            gi = row.geometry.intersection(box(w - padlon - 1, s - pad - 1, e + padlon + 1, n + pad + 1))
            if gi.is_empty:
                continue
            d = bx.distance(shp_transform(fwd.transform, gi))
            margin = d - (row.threshold_m + row.tolerance_m)
            if margin < best:
                best, who = margin, row["name"]
        return best, who


# --------------------------------------------------------------------------- #
# gridding
# --------------------------------------------------------------------------- #
def files_for_block(cov: Coverage, zc, ei, ni, pad_m=2000.0):
    epsg = zone_epsg(zc)
    inv = pyproj.Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    bx = box(ei * R.BLOCK_M - pad_m, ni * R.BLOCK_M - pad_m, (ei + 1) * R.BLOCK_M + pad_m, (ni + 1) * R.BLOCK_M + pad_m)
    w, s, e, n = shp_transform(inv.transform, bx.segmentize(1000.0)).bounds
    out = []
    for name, f in cov.files.items():
        b = f.get("bounds")
        if not b or f["n"] == 0:
            continue
        if b[0] <= e and b[2] >= w and b[1] <= n and b[3] >= s:
            out.append(name)
    return sorted(out)


GRID_MODE = "dev_chain"      # steering ruling 2026-10-03: match the development lr.tif representation ("direct_utm" = pilot v0)
DEV_FILL = -9999.0           # stage_f_harmonize.FILL / harmonize_new FILL


def geo_region(zc, ei, ni, cell):
    """Stage-C geographic recipe for a block (stage_c_full.py:181-187, acq_r01/grid_lr.py main): region = the block's
    lon/lat bounds +/- 1 km, mid-latitude cell conversion dlon = 1/(111320*max(0.2, cos(mlat))), dlat = 1/111320,
    -E dx/dy/degrees.  Returns (R string, dx, dy, lonlat bounds)."""
    epsg = zone_epsg(zc)
    inv = pyproj.Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    bx = box(ei * R.BLOCK_M, ni * R.BLOCK_M, (ei + 1) * R.BLOCK_M, (ni + 1) * R.BLOCK_M).segmentize(500.0)
    xs, ys = inv.transform(*bx.exterior.xy)
    xs = np.asarray(xs)
    if xs.max() - xs.min() > 180:                       # block straddles the antimeridian: express in 0..360
        xs = np.where(xs < 0, xs + 360.0, xs)
    w, e, s, n = float(xs.min()), float(xs.max()), float(np.min(ys)), float(np.max(ys))
    mlat = (s + n) / 2
    dlon = 1 / (111320 * max(0.2, math.cos(math.radians(mlat))))
    dlat = 1 / 111320
    Rg = f"{w - 1000 * dlon}/{e + 1000 * dlon}/{s - 1000 * dlat}/{n + 1000 * dlat}"
    return Rg, cell * dlon, cell * dlat, (w, s, e, n)


def mbgrid_args_geo(dl_name, root, Rg, dx, dy):
    """Stage-C mbgrid call, verbatim form (stage_c_full.py:189-190)."""
    return ["mbgrid", "-I", dl_name, "-O", root, "-R", Rg, "-E", f"{dx}/{dy}/degrees", *R.MBGRID_FLAGS]


def grd_to_block_tif(grd: Path, tmp_tif: Path, tif: Path, zc, ei, ni):
    """Development warp chain for one block:
      (1) .grd -> GeoTIFF with the grd's CRS and nodata (stage_f_harmonize._lr_to_tif / harmonize_new.lr_to_tif);
      (2) harmonize._open (rioxarray, masked) + harmonize._reproject(target UTM, bilinear, nodata -9999): GDAL default
          output grid, no explicit resolution (as harmonize.harmonize_pair; verified against 8 development lr.tif);
      (3) rio.clip to the block polygon, drop=True, all_touched=False (as harmonize_pair's overlap clip);
      (4) written as grid.tif: float32, NaN nodata (contract), positive up."""
    from src import harmonize as H
    with rasterio.open(str(grd)) as ds:
        arr = ds.read(1).astype("float32")
        prof = {"driver": "GTiff", "height": ds.height, "width": ds.width, "count": 1, "dtype": "float32",
                "crs": ds.crs.to_string() if ds.crs else "EPSG:4326", "transform": ds.transform,
                "nodata": ds.nodata if ds.nodata is not None else DEV_FILL}
    with rasterio.open(tmp_tif, "w", **prof) as d:
        d.write(arr, 1)
    epsg = zone_epsg(zc)
    da = H._open(tmp_tif)
    p = H._reproject(da, f"EPSG:{epsg}", H._RESAMPLING["bilinear"], DEV_FILL)
    bx = box(ei * R.BLOCK_M, ni * R.BLOCK_M, (ei + 1) * R.BLOCK_M, (ni + 1) * R.BLOCK_M)
    c = p.rio.clip([bx], f"EPSG:{epsg}", drop=True, all_touched=False)
    a = c.values.astype("float32")
    a[a == np.float32(DEV_FILL)] = np.nan
    a[np.abs(a) >= 99999.0] = np.nan
    tr = c.rio.transform()
    out_prof = {"driver": "GTiff", "dtype": "float32", "count": 1, "height": a.shape[0], "width": a.shape[1], "crs": f"EPSG:{epsg}",
                "transform": tr, "nodata": float("nan"), "compress": "DEFLATE", "predictor": 3}
    if tif.exists():
        tif.chmod(0o644)
    with rasterio.open(tif, "w", **out_prof) as d:
        d.write(a, 1)
    tif.chmod(0o444)
    with rasterio.open(tmp_tif) as g:
        geo_res = (abs(g.transform.a), abs(g.transform.e))
    tmp_tif.unlink(missing_ok=True)
    return a, tr, geo_res


def mbgrid_args(dl_name, root, zc, ei, ni, cell):
    """Pilot v0 ('direct_utm'): mbgrid straight into the block's UTM zone (superseded by GRID_MODE dev_chain)."""
    z, sh = divmod(int(zc), 2)
    e0, e1 = ei * R.BLOCK_M, (ei + 1) * R.BLOCK_M; n0, n1 = ni * R.BLOCK_M, (ni + 1) * R.BLOCK_M
    return ["mbgrid", "-I", dl_name, "-O", root, "-R", f"{e0:.1f}/{e1:.1f}/{n0:.1f}/{n1:.1f}", "-J", f"UTM{z:02d}{'S' if sh else 'N'}",
            "-E", f"{cell:.4f}/{cell:.4f}/meters", *R.MBGRID_FLAGS]


def run_mbgrid_batch(wd: Path, jobs, fmt, timeout_s=3 * 3600, attempts=6):
    """jobs: list of (bid, files, args).  One container call runs every mbgrid of the batch; per-block rc markers.
    Blocks whose mbgrid did not finish with rc 0 and a grid are re-run (bounded); still failing -> returned as failed."""
    res = {}; todo = list(jobs)
    for attempt in range(attempts):
        if not todo:
            break
        lines = []
        for bid, files, args in todo:
            dl = wd / f"dl_{bid}.mb-1"
            dl.write_text("".join(f"{f} {fmt}\n" for f in files))
            lines.append(f"{' '.join(shlex.quote(a) for a in args)} > log_{bid}.txt 2>&1; echo \"#RC {bid} $?\"")
        script = "\n".join(lines) + "\necho '#RC __END__ 0'"
        sp = wd / f"mbgrid_batch_{todo[0][0]}_a{attempt + 1}.sh"   # script in a file (argv-length limit)
        sp.write_text(script + "\n")
        try:
            out, _, _ = R.mb_bounded(["sh", sp.name], wd, timeout=timeout_s, attempts=1)
            text = out["stdout"] or ""
        except R.MBFailure as e:
            text = ""; log.warning("mbgrid batch attempt %d failed: %s", attempt + 1, str(e)[:300])
        rcs = dict(re.findall(r"#RC (\S+) (\d+)", text))
        nxt = []
        for bid, files, args in todo:
            root = args[args.index("-O") + 1]
            okg = rcs.get(bid) == "0" and (wd / f"{root}.grd").exists()
            if okg:
                res[bid] = {"ok": True, "attempts": attempt + 1}
            else:
                nxt.append((bid, files, args))
                res[bid] = {"ok": False, "attempts": attempt + 1, "rc": rcs.get(bid),
                            "log": (wd / f"log_{bid}.txt").read_text(errors="replace")[-400:] if (wd / f"log_{bid}.txt").exists() else ""}
        todo = nxt
        if todo:
            time.sleep(15 * (attempt + 1))
    return res


def grd_to_tif(grd: Path, tif: Path, epsg: int):
    with rasterio.open(str(grd)) as ds:
        a = ds.read(1, masked=True).astype("float32").filled(np.nan)
        tr = ds.transform; nd = ds.nodata
    if nd is not None:
        a[a == np.float32(nd)] = np.nan
    a[np.abs(a) >= 99999.0] = np.nan               # mbgrid's no-data sentinel when not NaN
    if tr.e > 0:                                     # bottom-up netCDF -> north-up
        a = a[::-1]; tr = rasterio.Affine(tr.a, tr.b, tr.c, tr.d, -tr.e, tr.f + tr.e * a.shape[0])
    prof = {"driver": "GTiff", "dtype": "float32", "count": 1, "height": a.shape[0], "width": a.shape[1], "crs": f"EPSG:{epsg}",
            "transform": tr, "nodata": float("nan"), "compress": "DEFLATE", "predictor": 3}
    if tif.exists():
        tif.chmod(0o644)
    with rasterio.open(tif, "w", **prof) as d:
        d.write(a, 1)
    tif.chmod(0o444)
    return a, tr


# --------------------------------------------------------------------------- #
# products (contract v2.1 builder, unchanged)
# --------------------------------------------------------------------------- #
def run_products(cruise, bid, block_dir: Path, files_gz, fman_files, log_dir: Path):
    from src.acq_r03 import build_products_v2_1 as B
    from src.acq_r03 import common as R3
    R3.REPORT_DIR = log_dir                              # where build() drops its per-run JSON (not the ACQ-R03 report dir)
    stg = R.SCR / "pretrain_v1_prodstage" / cdir_name(cruise) / bid
    if stg.exists():
        shutil.rmtree(stg)
    stg.mkdir(parents=True)
    raw = R.PRETRAIN_RAW / cdir_name(cruise)
    for f in files_gz:
        (stg / f).symlink_to(raw / f)
    sub = [x for x in fman_files if x["filename"] in set(files_gz)]
    (stg / "fetch_manifest.json").write_text(json.dumps({"cruise": cruise, "n_files_failed": 0, "files": sub,
                                                         "note": "ACQ-R04 per-block staging: the block's subset of the cruise fetch manifest"}))
    t0 = time.time()
    res = B.build([(bid, block_dir)], f"{cdir_name(cruise)}__{bid}", stg, "ncei_swath", 1, max(1, len(files_gz)))
    shutil.rmtree(stg, ignore_errors=True)
    pj = json.loads((block_dir / B.OUT_NAME / "products.json").read_text())
    flags = list((pj.get("qa_vs_lr_tif") or {}).get("flags") or [])
    avail = pj.get("available", {})
    return {"products_wall_s": round(time.time() - t0, 1), "available": avail, "flags": flags,
            "usable": bool(avail and all(avail.values()) and not flags), "n_cells": res[0]["cells"] if res else None}


# --------------------------------------------------------------------------- #
# main per-cruise driver
# --------------------------------------------------------------------------- #
def cruise_meta(cruise):
    sel = pd.read_csv(R.REPORT_DIR / "selection_v1.csv")
    r = sel[sel.cruise == cruise]
    if len(r) != 1:
        raise SystemExit(f"{cruise} not in selection_v1.csv")
    return r.iloc[0]


def decompress(raw: Path, names_gz, wd: Path, workers=4):
    def one(n):
        src = raw / n; dst = wd / (n[:-3] if n.endswith(".gz") else n)
        if dst.exists():
            return dst.name
        if n.endswith(".gz"):
            tmp = dst.with_name(dst.name + ".part")
            with gzip.open(src, "rb") as s, tmp.open("wb") as d:
                shutil.copyfileobj(s, d, 1 << 22)
            tmp.rename(dst)
        else:
            dst.symlink_to(src)
        return dst.name
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, names_gz))


def process(cruise, grid_workers=4, prod_workers=4, only_blocks=None, out_root: Path | None = None, keep_wd=False):
    t_all = time.time()
    C.assert_no_lockbox_cruise([cruise])
    meta = cruise_meta(cruise)
    out_root = out_root or R.STAGE
    cd = cdir_name(cruise)
    log_dir = R.WORK_LOGS / cd; log_dir.mkdir(parents=True, exist_ok=True)
    raw = R.PRETRAIN_RAW / cd
    fman = json.loads((raw / "fetch_manifest.json").read_text())
    if fman.get("n_files_failed", 0):
        raise SystemExit(f"{cruise}: fetch incomplete ({fman['n_files_failed']} failed); not gridding a partial cruise")
    gz_names = sorted(f["filename"] for f in fman["files"])
    fmt = fmt_for(gz_names[0])
    if any(fmt_for(n) != fmt for n in gz_names):
        raise SystemExit(f"{cruise}: mixed MB formats in the planned files")
    wd = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r04" / cd
    wd.mkdir(parents=True, exist_ok=True)
    rec = {"cruise": cruise, "stratum": meta.stratum, "family": meta.family, "basin": meta.basin, "year": meta.year,
           "instrument": meta.instrument, "mb_format": fmt, "n_files": len(gz_names), "raw_bytes": int(sum(f["size"] for f in fman["files"])),
           "host": os.uname().nodename, "started": R.utc_now(), "code_commit": C.git_commit(), "failures": []}
    t = time.time(); loc = decompress(raw, gz_names, wd); rec["decompress_s"] = round(time.time() - t, 1)
    gz_of = dict(zip(loc, gz_names))
    t = time.time(); cov, cov_cmds = coverage_pass(wd, loc, fmt); rec["coverage_s"] = round(time.time() - t, 1)
    rec["coverage"] = cov_cmds
    rec["soundings"] = int(sum(f["n"] for f in cov.files.values())); rec["polar_soundings_dropped"] = int(cov.polar)
    rec["unparsed_lines_dropped"] = int(cov.unparsed)
    rec["files_without_soundings"] = sorted(n for n, f in cov.files.items() if f["n"] == 0)
    bw, bw_key = beamwidth_for(str(meta.instrument))
    rec["beamwidth_deg"] = bw; rec["beamwidth_key"] = bw_key
    guard = Guard()
    ledger, cands = [], []
    for (zc, ei, ni), b in sorted(cov.blocks.items()):
        bid = block_id(zc, ei, ni)
        if only_blocks is not None and bid not in only_blocks:
            continue
        dmed = Coverage.median_depth(b)
        row = {"block": bid, "n_soundings": b["n"], "median_depth_m": round(dmed, 2), "status": None}
        if not (R.DEPTH_MIN <= dmed <= R.DEPTH_MAX):
            row["status"] = "drop_depth"
        else:
            margin, who = guard.check(zc, ei, ni)
            row["guard_margin_m"] = None if not math.isfinite(margin) else round(margin, 1); row["guard_nearest"] = who
            if margin < 0:
                row["status"] = "drop_exclusion_guard"
            else:
                row["cell_m"] = 2.0 * dmed * math.tan(math.radians(bw / 2.0))
                cands.append((zc, ei, ni, bid, row))
        ledger.append(row)
    # grid candidates in batches (<= grid_workers concurrent container calls)
    t = time.time()
    gjobs = []
    for zc, ei, ni, bid, row in cands:
        files = files_for_block(cov, zc, ei, ni)
        row["files"] = files
        if GRID_MODE == "dev_chain":
            Rg, dx, dy, _ = geo_region(zc, ei, ni, row["cell_m"])
            row["geo_E_deg"] = [dx, dy]
            gjobs.append((bid, files, mbgrid_args_geo(f"dl_{bid}.mb-1", f"g_{bid}", Rg, dx, dy)))
        else:
            gjobs.append((bid, files, mbgrid_args(f"dl_{bid}.mb-1", f"g_{bid}", zc, ei, ni, row["cell_m"])))
    nb = max(1, math.ceil(len(gjobs) / max(1, grid_workers * 4)))
    batches = [gjobs[i:i + nb] for i in range(0, len(gjobs), nb)]
    gres = {}
    with ThreadPoolExecutor(max_workers=grid_workers) as ex:
        for r_ in ex.map(lambda bt: run_mbgrid_batch(wd, bt, fmt), batches):
            gres.update(r_)
    rec["grid_s"] = round(time.time() - t, 1)
    kept = []
    for zc, ei, ni, bid, row in cands:
        g = gres.get(bid, {"ok": False})
        args = next(a for b_, _, a in gjobs if b_ == bid)
        row["mbgrid_command"] = f"(cd {wd} && {R.mb_cmdline(args)})  # datalist dl_{bid}.mb-1: {', '.join(row['files'])}"
        if not g["ok"]:
            row["status"] = "fail_mbgrid"; row["error"] = g
            rec["failures"].append({"block": bid, "stage": "mbgrid", "detail": g}); continue
        bdir = out_root / cd / bid
        if bdir.exists():
            for p in bdir.rglob("*"):
                if p.is_file() and not p.is_symlink():
                    p.chmod(0o644)
            shutil.rmtree(bdir)
        bdir.mkdir(parents=True)
        if GRID_MODE == "dev_chain":
            arr, tr, geo_res = grd_to_block_tif(wd / f"g_{bid}.grd", wd / f"g_{bid}_geo.tif", bdir / "grid.tif", zc, ei, ni)
            row["geo_grid_res_deg"] = [geo_res[0], geo_res[1]]
        else:
            arr, tr = grd_to_tif(wd / f"g_{bid}.grd", bdir / "grid.tif", zone_epsg(zc))
        fill = float(np.isfinite(arr).mean())
        row["fill"] = round(fill, 4); row["grid_shape"] = list(arr.shape); row["cell_m_actual"] = [round(tr.a, 4), round(-tr.e, 4)]
        if fill < R.FILL_MIN:
            row["status"] = "drop_fill"; shutil.rmtree(bdir); continue
        (bdir / "lr.tif").symlink_to("grid.tif")
        e0, n0 = ei * R.BLOCK_M, ni * R.BLOCK_M
        bj = {"cruise": cruise, "block": bid, "stratum": meta.stratum, "family": meta.family, "basin": meta.basin, "year": meta.year,
              "instrument": meta.instrument, "crs": f"EPSG:{zone_epsg(zc)}", "utm_zone": zone_label(zc),
              "bounds_block_m": [e0, n0, e0 + R.BLOCK_M, n0 + R.BLOCK_M],
              "bounds_grid_m": [tr.c, tr.f + tr.e * arr.shape[0], tr.c + tr.a * arr.shape[1], tr.f], "grid_shape": list(arr.shape),
              "n_soundings": row["n_soundings"], "median_depth_m": row["median_depth_m"], "median_depth_resolution_m": BIN,
              "beamwidth_deg": bw, "beamwidth_source": f"grid_lr.beamwidth_for('{meta.instrument}') -> {bw_key}",
              "cell_m": round(row["cell_m"], 4), "cell_m_actual": row["cell_m_actual"], "fill": row["fill"],
              "grid_mode": GRID_MODE,
              "gridding_chain": ("stage-C geographic mbgrid (-E dx/dy/degrees, stage_c_full.py:181-190) -> grd GeoTIFF "
                                 "(stage_f_harmonize._lr_to_tif) -> harmonize._open/_reproject to block UTM, bilinear, nodata -9999, GDAL "
                                 "default output grid (harmonize.py:53-63) -> rio.clip to block, drop=True, all_touched=False "
                                 "(harmonize.py:122-123) -> NaN nodata") if GRID_MODE == "dev_chain" else "mbgrid -J UTM direct (pilot v0)",
              "geo_E_deg": row.get("geo_E_deg"), "geo_grid_res_deg": row.get("geo_grid_res_deg"),
              "guard_margin_m": row["guard_margin_m"], "guard_nearest": row["guard_nearest"],
              "mb_format": fmt, "files": [gz_of[f] for f in row["files"]], "mbgrid_command": row["mbgrid_command"],
              "mbsystem": C.MBSYSTEM_VERSION, "container": f"{C.SANDBOX} ({C.CONTAINER_DIGEST})", "code_commit": C.git_commit(),
              "grid_tif_sha256": R.sha256_file(bdir / "grid.tif"), "created": R.utc_now()}
        R.write_json(bdir / "block.json", bj)
        row["status"] = "kept"; kept.append((bid, bdir, row))
    # products
    t = time.time()

    def prod(item):
        bid, bdir, row = item
        try:
            return bid, run_products(cruise, bid, bdir, [gz_of[f] for f in row["files"]], fman["files"], log_dir / "products"), None
        except Exception as e:
            return bid, None, f"{type(e).__name__}: {str(e)[:400]}"
    with ThreadPoolExecutor(max_workers=prod_workers) as ex:
        pres = list(ex.map(prod, kept))
    rec["products_s"] = round(time.time() - t, 1)
    for (bid, bdir, row), (_, pr, err) in zip(kept, pres):
        bj = json.loads((bdir / "block.json").read_text())
        if err:
            row["products"] = {"error": err}; bj["products"] = {"error": err, "usable": False}
            rec["failures"].append({"block": bid, "stage": "products", "detail": err})
        else:
            row["products"] = pr; bj["products"] = {k: pr[k] for k in ("available", "flags", "usable")}
        p = bdir / "block.json"; p.chmod(0o644); p.write_text(json.dumps(bj, indent=1, default=str)); p.chmod(0o444)
    if not keep_wd:
        shutil.rmtree(wd, ignore_errors=True)
    rec["blocks_total"] = len(ledger)
    rec["block_status"] = pd.Series([r["status"] for r in ledger]).value_counts().to_dict() if ledger else {}
    rec["blocks_kept"] = len(kept)
    rec["output_bytes"] = int(sum(p.stat().st_size for b in kept for p in b[1].rglob("*") if p.is_file() and not p.is_symlink()))
    rec["wall_s"] = round(time.time() - t_all, 1); rec["finished"] = R.utc_now()
    rec["grid_workers"] = grid_workers; rec["prod_workers"] = prod_workers
    pd.DataFrame([{k: (json.dumps(v, default=str) if isinstance(v, (dict, list)) else v) for k, v in r.items()} for r in ledger]).to_csv(
        log_dir / ("block_ledger.csv" if only_blocks is None else "block_ledger_subset.csv"), index=False)
    R.write_json(log_dir / ("cruise_record.json" if only_blocks is None else "cruise_record_subset.json"), rec)
    log.info("[%s] blocks %d, kept %d, failures %d, wall %.0f s", cruise, len(ledger), len(kept), len(rec["failures"]), rec["wall_s"])
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cruise", required=True)
    ap.add_argument("--grid-workers", type=int, default=4); ap.add_argument("--prod-workers", type=int, default=4)
    ap.add_argument("--grid-mode", default="dev_chain", choices=["dev_chain", "direct_utm"])
    a = ap.parse_args(argv)
    global GRID_MODE
    GRID_MODE = a.grid_mode
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        rec = process(a.cruise, a.grid_workers, a.prod_workers)
    except Exception as e:
        cd = cdir_name(a.cruise)
        R.write_json(R.WORK_LOGS / cd / "cruise_failure.json", {"cruise": a.cruise, "error": f"{type(e).__name__}: {e}", "at": R.utc_now()})
        raise
    return 0 if not rec["failures"] else 3


if __name__ == "__main__":
    sys.exit(main())
