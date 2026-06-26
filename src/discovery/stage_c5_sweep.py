"""Stage C.5 S1-S3 — apply the calibrated SR-signal metric to the 43 gridded
pairs (Stage C full + pilot) across k in {2,4,8}; reframe the corpus.

Per pair: co-register LR grid + AUV HR on a common UTM grid over the footprint,
compute sr_metrics + verdict at each k, the max recoverable k, and the
UQ-ceiling energy (AUV structure above the target band — the unrecoverable
roughness the model should express as uncertainty rather than fabricate).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform_bounds

import os
import geopandas as gpd

from src.discovery.stage_c5_spectral import load_to_common, perk_curve, perk_verdict, band_rms
from src.discovery.stage_c_full import footprint_for, RAW_LR
from src import gmt_grd

REPO = Path(__file__).resolve().parents[2]
GRIDDED = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/raw_lr_gridded")
STAGING = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/staging_phase1")
_CAT = gpd.read_file(REPO / "reports/discovery/hr_catalog.gpkg").set_index("hr_id")


def catalog_crs(hr_id):
    if hr_id in _CAT.index:
        for col in ("recovered_crs", "native_crs"):
            v = _CAT.loc[hr_id, col]
            if isinstance(v, str) and v.startswith("EPSG"):
                return v
    return None


def _read_coards_grd(path, crs, out):
    """Read a GMT-v6 COARDS NetCDF .grd (1-D x,y + 2-D z) — which rasterio can't
    georeference — and write a GeoTIFF with the catalog CRS."""
    import netCDF4 as nc
    from rasterio.transform import from_origin
    ds = nc.Dataset(str(path))
    try:
        x = np.asarray(ds.variables["x"][:], dtype="float64")
        y = np.asarray(ds.variables["y"][:], dtype="float64")
        z = np.asarray(ds.variables["z"][:], dtype="float32")
    finally:
        ds.close()
    if z.ndim != 2:
        return None
    dx = abs(x[1] - x[0]); dy = abs(y[1] - y[0])
    if y[0] < y[-1]:                       # y ascending -> flip so row 0 = north
        z = z[::-1]
    z = np.where(np.isfinite(z), z, -9999.0).astype("float32")
    tr = from_origin(float(x.min()), float(y.max()), dx, dy)
    prof = {"driver": "GTiff", "height": z.shape[0], "width": z.shape[1],
            "count": 1, "dtype": "float32", "crs": crs or "EPSG:4326",
            "transform": tr, "nodata": -9999.0, "compress": "DEFLATE",
            "BIGTIFF": "IF_SAFER"}
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(z, 1)
    return out


def materialize_hr(hr_id, hr_path, tmpdir):
    """Write the HR raster to a temp GeoTIFF with the CORRECT CRS: GMT-classic
    AND GMT-v6 COARDS .grd converted; no-CRS rasters re-tagged from the catalog."""
    tmpdir = Path(tmpdir); tmpdir.mkdir(parents=True, exist_ok=True)
    out = tmpdir / (hr_id.replace(":", "_") + ".tif")
    crs = catalog_crs(hr_id)
    if out.exists():
        return out
    try:
        if gmt_grd.is_gmt_grd(Path(hr_path)):
            gmt_grd.convert(Path(hr_path), out, crs=crs)
            return out
    except Exception:
        pass
    # rasterio / NETCDF with a real geotransform (clean minimal profile — reusing
    # the netCDF profile wholesale breaks the GTiff write)
    for cand in (str(hr_path), "NETCDF:" + str(hr_path)):
        try:
            with rasterio.open(cand) as ds:
                arr = ds.read(1).astype("float32")
                src_crs = ds.crs
                tr = ds.transform
                nod = ds.nodata
            if tr is None or (abs(tr.a - 1.0) < 1e-12 and abs(tr.e - 1.0) < 1e-12):
                continue                                    # identity = no georef
            use_crs = src_crs.to_string() if src_crs else crs
            if use_crs is None:
                continue
            prof = {"driver": "GTiff", "height": arr.shape[0], "width": arr.shape[1],
                    "count": 1, "dtype": "float32", "crs": use_crs, "transform": tr,
                    "nodata": (nod if nod is not None else -9999.0),
                    "compress": "DEFLATE", "BIGTIFF": "IF_SAFER"}
            with rasterio.open(out, "w", **prof) as dst:
                dst.write(arr, 1)
            return out
        except Exception:
            continue
    # GMT-v6 COARDS NetCDF (1-D x,y + 2-D z; no rasterio geotransform)
    try:
        return _read_coards_grd(hr_path, crs, out)
    except Exception:
        return None
CAL = json.loads((REPO / "reports/discovery/stage_c5b_calibration.json").read_text())
THR = CAL["thresholds"]
KS = (2, 4, 8, 16, 32)
RASTER_EXT = (".tif", ".tiff", ".grd", ".nc", ".asc")


def staged_hr_raster(hr_id: str):
    d = STAGING / hr_id.replace(":", "_").replace("/", "_")
    if not d.is_dir():
        return None
    cands = [p for p in d.iterdir()
             if p.suffix.lower() in RASTER_EXT and not p.name.endswith(".provenance.json")
             and not p.name.endswith(".a5conv.tif") and not p.name.lower().endswith(".pdf")
             and "diff" not in p.name.lower()                 # skip difference grids
             and "interp" not in p.name.lower() and "Int." not in p.name]
    if not cands:
        return None
    # Re-audit C2: prefer a genuine float-elevation tile; skip RGB visualization
    # renders (3-band uint8). Picking the "largest" file wrongly selected RGB
    # slope renders over the real float grid for 9 pairs (the "+255" bug).
    from .hr_format_gate import pick_elevation_tile
    elev = pick_elevation_tile(cands)
    if elev is not None:
        return elev
    return max(cands, key=lambda p: p.stat().st_size)   # fallback (legacy)


def lr_grid_path(cruise: str, hr_id: str):
    pilot = GRIDDED / f"{cruise}__{hr_id.replace(':', '_')}.grd"
    if pilot.exists():
        return pilot
    union = GRIDDED / f"{cruise}__union.grd"
    return union if union.exists() else None


def uq_ceiling(hr_arr, dx, lr_native, k):
    """Fraction of AUV HR spectral energy ABOVE the target band (finer than
    LR_native/k) — the unrecoverable structure = per-pair uncertainty target."""
    fc, psd = radial_psd(hr_arr, dx)
    if fc is None:
        return None
    f_target = k / lr_native
    valid = np.isfinite(psd) & (fc > 0)
    tot = np.nansum(psd[valid])
    above = np.nansum(np.where(valid & (fc > f_target), psd, np.nan))
    return round(float(above / tot), 4) if tot > 0 else None


def sweep_pair(cruise, hr_id, lr_native):
    lr_p = lr_grid_path(cruise, hr_id)
    hr_raw = staged_hr_raster(hr_id)
    if lr_p is None or hr_raw is None:
        return {"cruise": cruise, "hr_id": hr_id, "status": "missing_grid",
                "lr_grid": str(lr_p), "hr_raster": str(hr_raw)}
    tmpdir = Path(os.environ.get("L_SCRATCH", "/tmp")) / "c5_hr"
    hr_p = materialize_hr(hr_id, hr_raw, tmpdir)
    if hr_p is None:
        return {"cruise": cruise, "hr_id": hr_id, "status": "hr_unreadable",
                "hr_raster": str(hr_raw)}
    poly = footprint_for(hr_id)
    if poly is None:
        return {"cruise": cruise, "hr_id": hr_id, "status": "no_footprint"}
    # Window over the intersection of HR-data ∩ LR-data ∩ footprint — many HR
    # footprints are inflated (~1° wide), so the footprint centre misses the
    # small real HR patch; the data-bounds intersection lands on the true overlap.
    def _b4(p):
        with rasterio.open(str(p)) as ds:
            return transform_bounds(ds.crs, "EPSG:4326", *ds.bounds) if ds.crs else None
    fb = poly.bounds
    bb = [fb]
    for p in (lr_p, hr_p):
        try:
            bx = _b4(p)
            if bx:
                bb.append(bx)
        except Exception:
            pass
    w = max(x[0] for x in bb); s = max(x[1] for x in bb)
    e = min(x[2] for x in bb); n = min(x[3] for x in bb)
    if not (w < e and s < n):
        return {"cruise": cruise, "hr_id": hr_id, "status": "no_data_overlap"}
    b = (w, s, e, n)
    # AUV-NATIVE grid (Track A finer): resolves every k up to the AUV Nyquist,
    # so the per-k curve truncates honestly at each pair's ratio-bound, not at
    # an artificial LR/16 cap.
    with rasterio.open(str(hr_p)) as ds:
        hr_res = abs(ds.res[0])
    target_res = max(0.5, hr_res)
    try:
        lr, hr, dx = load_to_common(str(lr_p), str(hr_p), b, target_res)
    except Exception as e:
        return {"cruise": cruise, "hr_id": hr_id, "status": "coreg_failed", "err": str(e)[:120]}
    if not np.isfinite(hr).any() or not np.isfinite(lr).any():
        return {"cruise": cruise, "hr_id": hr_id, "status": "empty_overlap"}
    curve = perk_curve(lr, hr, dx, lr_native, KS)
    if curve is None:
        return {"cruise": cruise, "hr_id": hr_id, "status": "no_spectrum"}
    row = {"cruise": cruise, "hr_id": hr_id, "lr_native_m": round(lr_native, 1),
           "hr_res_m": round(hr_res, 2), "status": "ok",
           "edge_coh": curve["edge_coh"], "nyquist": curve["nyquist"], "per_k": {}}
    max_rec_k = None
    for k in KS:
        pk = curve["per_k"][str(k)]
        if not pk.get("resolvable"):
            row["per_k"][str(k)] = {"resolvable": False}
            continue
        v = perk_verdict(pk.get("slope_local"), curve["edge_coh"], THR)
        row["per_k"][str(k)] = {**pk, "verdict": v}
        if v == "recoverable_signal":
            max_rec_k = k
    row["max_recoverable_k"] = max_rec_k
    # physical measures @ k=8 (C: UQ in metres; B: SR-band new-signal magnitude)
    f_lr = 1.0 / lr_native
    f_t8 = 8 * f_lr
    nyq = curve["nyquist"]
    if f_t8 < nyq:
        row["uq_rms_m"], row["uq_char_m"] = band_rms(hr, dx, f_t8, nyq)
    else:
        row["uq_rms_m"], row["uq_char_m"] = None, None
    hi = min(f_t8, nyq * 0.99)
    row["hr_sr_rms_m"], _ = band_rms(hr, dx, f_lr, hi)
    row["lr_sr_rms_m"], _ = band_rms(lr, dx, f_lr, hi)
    return row


def main():
    full = json.loads((REPO / "reports/discovery/stage_c_full_measurements.json").read_text())
    pilot = json.loads((REPO / "reports/discovery/stage_c_pilot_measurements.json").read_text())
    pairs = []
    seen = set()
    for p in full + pilot:
        if p.get("status") != "gridded":
            continue
        key = (p["cruise"], p["hr_id"])
        if key in seen:
            continue
        seen.add(key)
        lrn = p.get("lr_native_res_m")
        if not lrn or lrn != lrn:
            continue
        pairs.append((p["cruise"], p["hr_id"], float(lrn),
                      p.get("provisional_ratio"), p.get("hr_bucket", "")))
    print(f"sweeping {len(pairs)} gridded pairs across k={KS}")
    rows = []
    for cruise, hr, lrn, ratio, bucket in pairs:
        r = sweep_pair(cruise, hr, lrn)
        r["prior_ratio"] = ratio
        r["hr_bucket"] = bucket
        rows.append(r)
        if r.get("status") == "ok":
            vs = {k: r["per_k"][k].get("verdict", "NR") for k in r["per_k"]}
            print(f"  {cruise:14s} {hr:12s} maxk={r['max_recoverable_k']} {vs}")
        else:
            print(f"  {cruise:14s} {hr:12s} {r.get('status')}")
    (REPO / "reports/discovery/stage_c5b_sweep.json").write_text(json.dumps(rows, indent=2, default=str))
    # flat CSV — per-k local slope + verdict curve
    with (REPO / "reports/stage_c5_sr_signal_sweep.csv").open("w", newline="") as f:
        w = csv.writer(f)
        head = ["cruise", "hr_id", "lr_native_m", "hr_res_m", "prior_ratio",
                "hr_bucket", "status", "edge_coh", "max_recoverable_k"]
        for k in KS:
            head += [f"k{k}_slope", f"k{k}_verdict", f"k{k}_uq"]
        w.writerow(head)
        for r in rows:
            pk = r.get("per_k", {})
            row = [r["cruise"], r["hr_id"], r.get("lr_native_m"), r.get("hr_res_m"),
                   r.get("prior_ratio"), r.get("hr_bucket"), r.get("status"),
                   r.get("edge_coh"), r.get("max_recoverable_k")]
            for k in KS:
                d = pk.get(str(k), {})
                row += [d.get("slope_local"), d.get("verdict", "NR"), d.get("uq_above_target")]
            w.writerow(row)
    print("wrote reports/discovery/stage_c5b_sweep.json + reports/stage_c5_sr_signal_sweep.csv")


if __name__ == "__main__":
    main()
