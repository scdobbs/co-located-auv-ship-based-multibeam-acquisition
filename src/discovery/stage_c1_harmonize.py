"""C1 Step 2 — harmonize the 3 clear recovered float pairs (Stage F reuse).

Pairs: NA076xMGDS_32317 (SantaMonica), FK181031xMGDS_24618 (Pescadero, lu29),
TN299xMGDS_31253 (Pythia, lu27). Amundsen dropped (L2); Axial held (Steve).

Reuses harmonize.harmonize_pair (masked open, single-warp-to-UTM, clip to HR∩LR)
then a MASKED co-registration (the Stage F bug fix — open masked=True so -9999
fill is never sampled), builds joint_valid + tiles, and the R3 QC figure.
Writes to $DATA_ROOT/harmonized/<pid>/ (append-only new dirs; the 34 untouched).
"""
from __future__ import annotations
import json, logging, os
from pathlib import Path
import numpy as np
import rasterio
import rioxarray  # noqa
from rasterio.warp import transform_bounds, reproject, Resampling
from scipy import ndimage as ndi

from src import harmonize as H
from src import coregister as cor
from src import gmt_grd
from src.discovery.stage_c5_sweep import _read_coards_grd

log = logging.getLogger("c1harm")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
RH = DATA / "reharvest_c1"
GRID = DATA / "raw_lr_gridded"
HARM = DATA / "harmonized"
QCDIR = DATA / "qc_plots" / "reaudit_real23"
RESULT = REPO / "reports/discovery/stage_c1_harmonize_results.json"
FILL = -9999.0

PAIRS = [
    {"pid": "NA076__MGDS_32317", "hr": RH / "MGDS_32317" / "SantaMonica_800mMound_MAUV_Topo1m_sq.grd",
     "lr": GRID / "NA076__union.grd", "site": "SantaMonica_800mMound", "lu": "new",
     "morph": "continental_margin", "region": "PacificOcean:SouthernCalifornia", "depth_m": 866,
     "hr_doi": "10.60521/332317", "lr_cruise": "NA076"},
    {"pid": "FK181031__MGDS_24618", "hr": RH / "MGDS_24618" / "GOCPescaderoBasin_Topo1m_Geo.grd",
     "lr": GRID / "FK181031__MGDS_24620.grd", "site": "PescaderoBasin", "lu": 29,
     "morph": "hydrothermal_vent", "region": "GulfOfCalifornia:PescaderoBasin", "depth_m": 3788,
     "hr_doi": "10.1594/IEDA/324618", "lr_cruise": "FK181031"},
    {"pid": "TN299__MGDS_31253", "hr": RH / "MGDS_31253" / "Pythia_auv_s19a_gcs_1m.grd",
     "lr": GRID / "TN299__MGDS_31256.grd", "site": "Cascadia_Pythia", "lu": 27,
     "morph": "continental_margin", "region": "Cascadia", "depth_m": 1087,
     "hr_doi": "10.26022/IEDA/331253", "lr_cruise": "TN299"},
]


def _utm(lon, lat):
    z = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + z}"


def materialize(grd: Path, out: Path):
    """Float .grd (GMT-classic / COARDS / rasterio-readable) -> GeoTIFF (EPSG:4326)."""
    if out.exists():
        return out
    try:
        if gmt_grd.is_gmt_grd(grd):
            return gmt_grd.convert(grd, out, crs="EPSG:4326")
    except Exception:
        pass
    for cand in (str(grd), "NETCDF:" + str(grd)):
        try:
            with rasterio.open(cand) as ds:
                arr = ds.read(1).astype("float32"); tr = ds.transform
                crs = ds.crs.to_string() if ds.crs else "EPSG:4326"; nod = ds.nodata
            if tr is None or (abs(tr.a - 1) < 1e-12 and abs(tr.e - 1) < 1e-12):
                continue
            prof = {"driver": "GTiff", "height": arr.shape[0], "width": arr.shape[1], "count": 1,
                    "dtype": "float32", "crs": crs, "transform": tr,
                    "nodata": nod if nod is not None else FILL, "compress": "DEFLATE", "BIGTIFF": "IF_SAFER"}
            with rasterio.open(out, "w", **prof) as d:
                d.write(arr, 1)
            return out
        except Exception:
            continue
    return _read_coards_grd(grd, "EPSG:4326", out)


def lr_real_on_hr(lr_tif, hr_ds):
    with rasterio.open(str(lr_tif)) as ds:
        src = ds.read(1, masked=True).filled(np.nan).astype("float64")
        m = np.isfinite(src).astype("float32")
        s_tr, s_crs = ds.transform, ds.crs
    dst = np.zeros((hr_ds.height, hr_ds.width), "float32")
    reproject(m, dst, src_transform=s_tr, src_crs=s_crs, dst_transform=hr_ds.transform,
              dst_crs=hr_ds.crs, src_nodata=0.0, dst_nodata=0.0, resampling=Resampling.average)
    valid = dst >= 0.5
    return ndi.binary_erosion(valid, iterations=1, border_value=0)


def one(p, tmp):
    pid = p["pid"]; out_dir = HARM / pid
    rec = {"pair_id": pid, "site": p["site"], "leakage_unit": p["lu"]}
    hr_tif = materialize(p["hr"], tmp / f"{pid}_hr.tif")
    lr_tif = materialize(p["lr"], tmp / f"{pid}_lr.tif")
    if hr_tif is None or lr_tif is None:
        rec["status"] = "reject"; rec["reason"] = "materialize failed"; return rec
    with rasterio.open(str(hr_tif)) as ds:
        hb = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
    clon, clat = (hb[0] + hb[2]) / 2, (hb[1] + hb[3]) / 2
    tcrs = _utm(clon, clat)
    rec["target_crs"] = tcrs
    try:
        hp = H.harmonize_pair(pair_id=pid, hr_raw=hr_tif, lr_raw=lr_tif, target_crs=tcrs,
                              resample_kernel="bilinear", nodata=FILL, out_dir=out_dir,
                              vertical_sign="negative_down", min_overlap_area_km2=1.0)
        rec["overlap_km2"] = round(hp.overlap_area_km2, 2)
    except Exception as e:
        rec["status"] = "reject"; rec["reason"] = f"harmonize: {str(e)[:120]}"; return rec
    hr_out, lr_out = out_dir / "hr.tif", out_dir / "lr.tif"

    # MASKED co-registration (the Stage F fix: masked=True so fill never sampled)
    try:
        hr_da = rioxarray.open_rasterio(str(hr_out), masked=True).squeeze()
        lr_da = rioxarray.open_rasterio(str(lr_out), masked=True).squeeze()
        cg = cor.estimate_rigid_xyz(hr_da, lr_da)
        corrected = cor.apply_xyz(hr_da, cg.dx_m, cg.dy_m, cg.dz_m)
        corrected.rio.write_nodata(np.nan, inplace=True)
        corrected.rio.to_raster(hr_out, compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")
        rec["coreg"] = {"dx": round(cg.dx_m, 2), "dy": round(cg.dy_m, 2), "dz": round(cg.dz_m, 2),
                        "offset_m": round(float(np.hypot(cg.dx_m, cg.dy_m)), 2),
                        "post_mad_m": round(cg.post_residual_mad_m, 2), "n": cg.n_samples}
    except Exception as e:
        rec["coreg_error"] = str(e)[:120]

    # joint_valid + tiles
    with rasterio.open(str(hr_out)) as hds:
        hr_arr = hds.read(1)
        hr_real = np.isfinite(hr_arr) & ~np.isclose(hr_arr, FILL, atol=1e-3)
        lr_real = lr_real_on_hr(lr_out, hds)
        joint = hr_real & lr_real
        prof = {"driver": "GTiff", "height": hds.height, "width": hds.width, "count": 1,
                "dtype": "uint8", "crs": hds.crs, "transform": hds.transform, "nodata": 255, "compress": "DEFLATE"}
        tr = hds.transform
    for nm, a in (("hr_valid", hr_real), ("lr_valid", lr_real), ("joint_valid", joint)):
        with rasterio.open(out_dir / f"{nm}.tif", "w", **prof) as d:
            d.write(a.astype("uint8"), 1)
    cell = abs(tr.a * tr.e)
    n_tiles = 0; T = 256
    Hh, Ww = joint.shape
    for r0 in range(0, Hh - T + 1, T):
        for c0 in range(0, Ww - T + 1, T):
            if joint[r0:r0 + T, c0:c0 + T].mean() >= 0.5:
                n_tiles += 1
    rec["joint_area_km2"] = round(int(joint.sum()) * cell / 1e6, 3)
    rec["joint_frac"] = round(float(joint.sum() / max(1, (hr_real | lr_real).sum())), 4)
    rec["n_valid_tiles"] = n_tiles
    # depth sanity
    jr = joint & hr_real
    rec["hr_p50_over_joint"] = round(float(np.nanpercentile(hr_arr[jr], 50)), 1) if jr.any() else None
    rec["status"] = "harmonized"

    # R3 QC figure
    try:
        from src.discovery import stage_reaudit_r3 as R3
        meta = {"reaudit_disposition": "c1_reharvest_candidate", "role": "train_eligible",
                "morphology": p["morph"], "source_type": "gmt_grd_float", "selected_source": p["hr"].name,
                "lr_native_m": "", "f5_joint_fraction": rec["joint_frac"], "f5_n_valid_tiles": n_tiles,
                "dz_apply": rec.get("coreg", {}).get("dz")}
        png = QCDIR / f"c1_candidate__{pid}.png"
        R3.figure(pid, meta, png)
        rec["qc_figure"] = str(png)
    except Exception as e:
        rec["qc_error"] = str(e)[:120]
    return rec


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "c1harm"; tmp.mkdir(parents=True, exist_ok=True)
    out = []
    for p in PAIRS:
        try:
            r = one(p, tmp)
        except Exception as e:
            r = {"pair_id": p["pid"], "status": "error", "reason": str(e)[:150]}
        log.info("[%s] %s tiles=%s joint_km2=%s p50=%s coreg=%s", r["pair_id"], r.get("status"),
                 r.get("n_valid_tiles"), r.get("joint_area_km2"), r.get("hr_p50_over_joint"), r.get("coreg"))
        out.append(r)
        RESULT.write_text(json.dumps(out, indent=2, default=str))
    log.info("wrote %s", RESULT)


if __name__ == "__main__":
    main()
