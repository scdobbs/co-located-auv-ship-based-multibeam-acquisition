"""Phase 2 Stage C — MB-System gridding PILOT (5 cruises, 8 pairs).

Per pilot pair (cruise x served-HR): gunzip swath -> datalist -> mbprocess
(mbclean defaults) -> mbgrid over the HR footprint+margin -> measure achieved
cell, fill fraction (real soundings vs interpolated), native resolution from
sounding density, provisional ratio, coverage-quality verdict, hillshade QC.

Gridded LR -> $DATA_ROOT/raw_lr_gridded/. NO OAK/manifest writes, no re-tier,
no harmonization. PILOT only — HOLD for assessment after.

MB-System runs in the Apptainer sandbox; this orchestrator runs outside and
shells into the container per command.
"""

from __future__ import annotations

import json
import logging
import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio

log = logging.getLogger("stage_c")

DATA_ROOT = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
RAW_LR = DATA_ROOT / "raw_lr"
GRIDDED = DATA_ROOT / "raw_lr_gridded"
REPO = Path(__file__).resolve().parents[2]
A6_FP = REPO / "reports/discovery/stage_a6_hr_footprints_2026-06-22.gpkg"
FETCH_LIST = REPO / "reports/stage_b_fetch_list_2026-06-22.csv"
HR_CAT = REPO / "reports/discovery/hr_catalog.gpkg"
SANITY = REPO / "reports/discovery/hr_resolution_sanity.csv"

SANDBOX = "/home/groups/hilley/containers/mbsystem_sandbox"
BIND = ["--bind", "/scratch,/home/groups,/oak"]

# Smallest-first so results accrue even if a large cruise fails late.
PILOT = ["AR26", "TN299", "FK181031", "2009_Amundsen", "KN210-05"]
DO_PROCESS = True          # run mbclean+mbprocess on small cruises
PROCESS_FILE_CAP = 100     # above this, grid raw (mbprocess too slow for pilot)

# LR ship-sonar across-track beamwidth (deg) for the footprint estimate.
BEAMWIDTH = {"EM302": 1.0, "EM710": 1.0, "EM122": 1.0, "EM712": 1.0,
             "SeaBeam 3012": 1.5}
DEFAULT_BW = 1.5

# Work area (node-local SSD, fast, wiped at job end — copy .grd back to GRIDDED).
WORK = Path("/lscratch") if False else None  # set at runtime from $L_SCRATCH


def mb(args: list[str], **kw) -> subprocess.CompletedProcess:
    """Run an MB-System command inside the Apptainer sandbox."""
    cmd = ["apptainer", "exec", *BIND, SANDBOX, *args]
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def sonar_beamwidth(sonar: str) -> float:
    for k, v in BEAMWIDTH.items():
        if k.lower() in (sonar or "").lower():
            return v
    return DEFAULT_BW


def fmt_for(name: str) -> int:
    import re
    m = re.search(r"\.mb(\d+)\.gz$", name) or re.search(r"\.mb(\d+)$", name)
    if m:
        return int(m.group(1))
    if name.endswith((".all.gz", ".all")):
        return 56
    return 58


def estimate_cell_m(depth_m: float, beamwidth_deg: float) -> float:
    return 2.0 * abs(depth_m) * math.tan(math.radians(beamwidth_deg / 2.0))


@dataclass
class PairResult:
    cruise: str
    hr_id: str
    lr_sonar: str = ""
    beamwidth_deg: float = 0.0
    median_depth_m: float = float("nan")
    est_cell_m: float = float("nan")
    achieved_cell_m: float = float("nan")
    fill_fraction: float = float("nan")
    n_cells_footprint: int = 0
    n_cells_data: int = 0
    lr_native_res_m: float = float("nan")
    hr_native_res_m: float = float("nan")
    hr_bucket: str = ""
    provisional_ratio: float = float("nan")
    ratio_provisional_ok_finer: bool = False
    grid_depth_min: float = float("nan")
    grid_depth_max: float = float("nan")
    grid_depth_median: float = float("nan")
    coverage_verdict: str = ""
    grd_path: str = ""
    overlay_path: str = ""
    notes: str = ""
    status: str = ""


def gunzip_cruise(cruise: str, workdir: Path) -> tuple[Path, list[Path], str]:
    """Decompress a cruise's swath files into workdir; build datalist.mb-1."""
    src = RAW_LR / cruise
    gz = sorted(p for p in src.iterdir()
                if p.name.endswith(".gz") and not p.name.endswith(".fnv"))
    workdir.mkdir(parents=True, exist_ok=True)
    files, fmt = [], 58
    dlist = workdir / "datalist.mb-1"
    with dlist.open("w") as dl:
        for p in gz:
            out = workdir / p.name[:-3]                # strip .gz
            if not out.exists():
                with __import__("gzip").open(p, "rb") as s, out.open("wb") as d:
                    while True:
                        b = s.read(1 << 22)
                        if not b:
                            break
                        d.write(b)
            fmt = fmt_for(p.name)
            dl.write(f"{out.name} {fmt}\n")
            files.append(out)
    return dlist, files, str(fmt)


def cruise_median_depth(dlist: Path, workdir: Path) -> float:
    import re
    r = mb(["mbinfo", "-I", dlist.name], cwd=str(workdir))
    for ln in (r.stdout or "").splitlines():
        if "Minimum Depth" in ln and "Maximum Depth" in ln:
            nums = re.findall(r"[-+]?\d+\.\d+", ln)
            if len(nums) >= 2:
                return (abs(float(nums[0])) + abs(float(nums[1]))) / 2.0
    return float("nan")


def process_cruise(dlist: Path, workdir: Path) -> Path:
    """mbclean (default outlier flagging) -> mbprocess. Returns the processed
    datalist (datalistp.mb-1) to grid from; falls back to the raw datalist if
    processing produced nothing."""
    mb(["mbdatalist", "-I", dlist.name, "-Z"], cwd=str(workdir))   # make inf/fbt
    mb(["mbclean", "-I", dlist.name], cwd=str(workdir))            # -> .esf edits
    mb(["mbprocess", "-I", dlist.name], cwd=str(workdir))          # -> p.mbNN + datalistp
    dp = workdir / "datalistp.mb-1"
    return dp if dp.exists() else dlist


def grid_pair(cruise, hr_id, dlist, workdir, bbox, sonar, depth, hr_res,
              hr_bucket) -> PairResult:
    pr = PairResult(cruise=cruise, hr_id=hr_id, lr_sonar=sonar,
                    hr_bucket=hr_bucket, hr_native_res_m=hr_res)
    pr.beamwidth_deg = sonar_beamwidth(sonar)
    pr.median_depth_m = depth
    pr.est_cell_m = estimate_cell_m(depth, pr.beamwidth_deg) if depth == depth else float("nan")
    if pr.est_cell_m != pr.est_cell_m or pr.est_cell_m <= 0:
        pr.est_cell_m = 50.0           # fallback if depth unknown
        pr.notes += "depth unknown; cell fallback 50 m; "
    # margin: 1 km around the footprint
    w, s, e, n = bbox
    mean_lat = (s + n) / 2.0
    deg_per_m_lat = 1.0 / 111320.0
    deg_per_m_lon = 1.0 / (111320.0 * max(0.2, math.cos(math.radians(mean_lat))))
    mw = 1000 * deg_per_m_lon; mh = 1000 * deg_per_m_lat
    R = f"{w-mw}/{e+mw}/{s-mh}/{n+mh}"
    dx = pr.est_cell_m * deg_per_m_lon
    dy = pr.est_cell_m * deg_per_m_lat
    outroot = workdir / f"grid_{hr_id.replace(':','_')}"
    r = mb(["mbgrid", "-I", dlist.name, "-O", outroot.name,
            "-R", R, "-E", f"{dx}/{dy}/degrees", "-A2", "-G3", "-F1",
            "-C0", "-M"], cwd=str(workdir))
    grd = workdir / f"{outroot.name}.grd"
    if not grd.exists():
        pr.status = "grid_failed"
        pr.notes += f"mbgrid no output: {(r.stderr or r.stdout)[-200:]}"
        return pr
    _measure(pr, grd, workdir / f"{outroot.name}_num.grd")
    # persist grid to GRIDDED
    GRIDDED.mkdir(parents=True, exist_ok=True)
    dest = GRIDDED / f"{cruise}__{hr_id.replace(':','_')}.grd"
    dest.write_bytes(grd.read_bytes())
    pr.grd_path = str(dest)
    pr.overlay_path = make_overlay(grd, bbox, cruise, hr_id)
    pr.status = "gridded"
    return pr


def make_overlay(grd: Path, bbox, cruise: str, hr_id: str) -> str:
    """QGIS-ready QC overlay: LR hillshade with the HR footprint outline."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import LightSource
        a, res = _read_grd(grd)
        if a is None:
            return ""
        ls = LightSource(azdeg=315, altdeg=45)
        hs = ls.hillshade(np.nan_to_num(a, nan=float(np.nanmedian(a))),
                          vert_exag=1.0, dx=1.0, dy=1.0)
        w, s, e, n = bbox
        fig, ax = plt.subplots(figsize=(7, 7))
        ax.imshow(hs, cmap="gray", origin="upper", extent=[w, e, s, n], aspect="auto")
        ax.imshow(np.where(np.isfinite(a), a, np.nan), origin="upper",
                  extent=[w, e, s, n], cmap="viridis", alpha=0.45, aspect="auto")
        ax.add_patch(plt.Rectangle((w, s), e - w, n - s, fill=False,
                                   edgecolor="red", lw=2, label="HR footprint"))
        ax.set_title(f"{cruise} -> {hr_id}  (LR gridded; red = HR footprint)")
        ax.set_xlabel("lon"); ax.set_ylabel("lat")
        out = GRIDDED / f"overlay_{cruise}__{hr_id.replace(':','_')}.png"
        fig.savefig(out, dpi=130, bbox_inches="tight"); plt.close(fig)
        return str(out)
    except Exception as e:
        log.warning("overlay failed %s/%s: %s", cruise, hr_id, e)
        return ""


def _read_grd(path: Path):
    for cand in (str(path), f"NETCDF:{path}"):
        try:
            with rasterio.open(cand) as ds:
                a = ds.read(1, masked=True)
                res = ds.res
            return np.asarray(a.filled(np.nan), dtype="float64"), res
        except Exception:
            continue
    return None, None


def _measure(pr: PairResult, grd: Path, numgrd: Path) -> None:
    a, res = _read_grd(grd)
    if a is None:
        pr.notes += "grd unreadable; "
        return
    mean_lat = pr.median_depth_m  # placeholder; recompute cell in m below
    # achieved cell in metres (res is in degrees)
    if res:
        pr.achieved_cell_m = round(res[1] * 111320.0, 2)
    finite = np.isfinite(a)
    pr.n_cells_footprint = int(a.size)
    pr.n_cells_data = int(finite.sum())
    pr.fill_fraction = round(pr.n_cells_data / a.size, 4) if a.size else 0.0
    vals = a[finite]
    if vals.size:
        pr.grid_depth_min = round(float(np.nanmin(vals)), 1)
        pr.grid_depth_max = round(float(np.nanmax(vals)), 1)
        pr.grid_depth_median = round(float(np.nanmedian(vals)), 1)
    # number-of-soundings grid (real-data cells)
    num, _ = _read_grd(numgrd)
    if num is not None:
        real = np.isfinite(num) & (num > 0)
        pr.n_cells_data = int(real.sum())
        pr.fill_fraction = round(real.sum() / num.size, 4) if num.size else 0.0
    # native res from sounding density: if fill is low, true res is coarser.
    if pr.fill_fraction and pr.fill_fraction > 0:
        pr.lr_native_res_m = round(pr.achieved_cell_m / math.sqrt(pr.fill_fraction), 2)
    else:
        pr.lr_native_res_m = pr.achieved_cell_m
    if pr.hr_native_res_m == pr.hr_native_res_m and pr.hr_native_res_m > 0:
        pr.provisional_ratio = round(pr.lr_native_res_m / pr.hr_native_res_m, 2)
    pr.ratio_provisional_ok_finer = (pr.hr_bucket == "ok_finer_verify")
    # coverage proxy: dense fill over footprint => near-nadir; sparse => grazing
    pr.coverage_verdict = "near_nadir" if (pr.fill_fraction or 0) >= 0.15 else "outer_beam_grazing"


def run(only: str | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import os
    global WORK
    WORK = Path(os.environ.get("L_SCRATCH", "/tmp")) / "stage_c_work"
    fl = pd.read_csv(FETCH_LIST).set_index("cruise")
    a6 = gpd.read_file(A6_FP).set_index("hr_id")
    cat = gpd.read_file(HR_CAT).set_index("hr_id")
    san = pd.read_csv(SANITY).set_index("hr_id")
    lr = gpd.read_file(REPO / "reports/discovery/lr_candidates.gpkg")
    lr_sonar = {c: (lr[lr.cruise_id == c]["sonar"].dropna().iloc[0]
                    if (lr.cruise_id == c).any() and lr[lr.cruise_id == c]["sonar"].notna().any()
                    else "") for c in PILOT}

    out = REPO / "reports/discovery/stage_c_pilot_measurements.json"
    # merge with any prior results (so a re-run of a subset preserves the rest)
    prior = json.loads(out.read_text()) if out.exists() else []
    cruises = [c.strip() for c in only.split(",")] if only else PILOT
    prior = [r for r in prior if r.get("cruise") not in cruises]

    results: list[PairResult] = []
    def flush():
        merged = prior + [vars(r) for r in results]
        out.write_text(json.dumps(merged, indent=2, default=str))

    for cruise in cruises:
        log.info("=== cruise %s ===", cruise)
        wd = WORK / cruise
        dlist, files, fmt = gunzip_cruise(cruise, wd)
        log.info("[%s] %d files, format %s", cruise, len(files), fmt)
        depth = cruise_median_depth(dlist, wd)
        log.info("[%s] median depth from mbinfo: %s", cruise, depth)
        # mbclean+mbprocess on big cruises is prohibitively slow (it hung the
        # 377-file Amundsen for hours) — for the pilot, process only small
        # cruises; grid raw above a file-count cap and flag it.
        if DO_PROCESS and len(files) <= PROCESS_FILE_CAP:
            dlist = process_cruise(dlist, wd)
            log.info("[%s] processed datalist: %s", cruise, dlist.name)
            proc_note = "mbclean+mbprocess"
        else:
            proc_note = f"RAW (no mbprocess; {len(files)} files > cap {PROCESS_FILE_CAP})"
            log.info("[%s] gridding RAW (skipped mbprocess: %d files)", cruise, len(files))
        live = [h for h in str(fl.loc[cruise, "live_HR"]).split(";") if h]
        for hr in live:
            if hr not in a6.index:
                results.append(PairResult(cruise=cruise, hr_id=hr,
                                          status="no_footprint")); continue
            bbox = a6.loc[hr].geometry.bounds
            hr_res = cat.loc[hr, "native_res_m"] if hr in cat.index else float("nan")
            try:
                hr_res = float(hr_res)
            except Exception:
                hr_res = float("nan")
            bucket = san.loc[hr, "resolution"] if hr in san.index else ""
            # Estimate depth = the HR FOOTPRINT depth (footprint-specific), NOT
            # the cruise-wide mbinfo median (biased by shallow transit lines).
            # Fall back to the cruise median only when HR depth is unknown.
            d = float("nan")
            dm = cat.loc[hr, "depth_min_m"] if hr in cat.index else None
            dxx = cat.loc[hr, "depth_max_m"] if hr in cat.index else None
            try:
                d = (abs(float(dm)) + abs(float(dxx))) / 2
            except Exception:
                d = float("nan")
            if d != d:
                d = depth  # cruise-wide mbinfo median (e.g. Amundsen, HR depth nan)
            pr = grid_pair(cruise, hr, dlist, wd, bbox, lr_sonar[cruise], d,
                           hr_res, bucket)
            log.info("[%s x %s] est=%.1fm achieved=%.1fm fill=%.3f native=%.1fm "
                     "ratio=%.1f cov=%s %s", cruise, hr, pr.est_cell_m,
                     pr.achieved_cell_m, pr.fill_fraction or 0, pr.lr_native_res_m,
                     pr.provisional_ratio or 0, pr.coverage_verdict, pr.status)
            results.append(pr)
            flush()                       # incremental: survive a timeout
        # free node-local space between cruises
        for f in files:
            try: f.unlink()
            except Exception: pass

    flush()
    print(f"\nwrote {out}")
    for r in results:
        print(f"  {r.cruise:14s} {r.hr_id:14s} {r.status:12s} "
              f"cell={r.achieved_cell_m} fill={r.fill_fraction} "
              f"native={r.lr_native_res_m} ratio={r.provisional_ratio} {r.coverage_verdict}")


if __name__ == "__main__":
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    run(only)
