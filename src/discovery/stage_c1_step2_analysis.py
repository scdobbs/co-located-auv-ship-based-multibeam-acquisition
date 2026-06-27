"""C1 Step 2 — pre-harmonization rulings: L1 (shared-LR leakage), L2 (Amundsen
co-location by tiles), Axial comparison (32556 vs manifested 30466).

Anchored to bounds/cells/overlap, not labels. No pairs added; this informs the
leakage_unit assignment and Steve's Axial ruling before harmonization.
"""
from __future__ import annotations
import json, logging
from pathlib import Path
import numpy as np
import rasterio
import geopandas as gpd
from rasterio.warp import transform_bounds, reproject, Resampling
from rasterio.transform import Affine
from shapely.geometry import box

log = logging.getLogger("c1s2a")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
RH = DATA / "reharvest_c1"
HARM = DATA / "harmonized"
GRID = DATA / "raw_lr_gridded"
STAG = DATA / "staging_phase1"
OUT = REPO / "reports/discovery/stage_c1_step2_analysis.json"


def open_any(path):
    """Open a grid (.grd COARDS / .asc / .tif) -> (array, transform, crs, bounds4326)."""
    for cand in (str(path), "NETCDF:" + str(path)):
        try:
            ds = rasterio.open(cand)
            return ds
        except Exception:
            continue
    return None


def grid_info(path):
    ds = open_any(path)
    if ds is None:
        return {"error": "unreadable", "file": Path(path).name}
    try:
        b = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds) if ds.crs else ds.bounds
        res = (abs(ds.res[0]), abs(ds.res[1]))
        # if geographic, approx res in m at mid-lat
        res_m = res[0] * 111320 * np.cos(np.radians((b[1] + b[3]) / 2)) if (ds.crs and ds.crs.is_geographic) else res[0]
        return {"file": Path(path).name, "w": ds.width, "h": ds.height,
                "crs": str(ds.crs), "res_native": round(res[0], 6), "res_m_approx": round(float(res_m), 2),
                "bounds_4326": [round(x, 4) for x in b]}
    finally:
        ds.close()


def overlap_4326(b1, b2):
    g = box(*b1).intersection(box(*b2))
    if g.is_empty:
        return {"overlap": False, "iou": 0.0}
    a = g.area; u = box(*b1).union(box(*b2)).area
    return {"overlap": True, "iou": round(a / u, 4),
            "frac_of_b1": round(a / box(*b1).area, 4), "frac_of_b2": round(a / box(*b2).area, 4)}


def fp_bounds(geojson):
    g = gpd.read_file(geojson)
    if g.crs and str(g.crs) != "EPSG:4326":
        g = g.to_crs("EPSG:4326")
    return list(g.total_bounds)


def l2_joint_cells(hr_path, lr_path):
    """Warp LR onto a decimated HR grid; count cells where BOTH are finite."""
    hds = open_any(hr_path)
    if hds is None:
        return {"error": "HR unreadable"}
    try:
        dec = max(1, int(max(hds.width, hds.height) / 1500))
        H, W = hds.height // dec, hds.width // dec
        hr = hds.read(1, out_shape=(H, W)).astype("float64")
        nd = hds.nodata
        if nd is not None:
            hr = np.where(np.isclose(hr, nd, atol=1e-3), np.nan, hr)
        tr = hds.transform * Affine.scale(hds.width / W, hds.height / H)
        crs = hds.crs
    finally:
        hds.close()
    lds = open_any(lr_path)
    if lds is None:
        return {"error": "LR unreadable"}
    try:
        lsrc = lds.read(1).astype("float64")
        lnd = lds.nodata if lds.nodata is not None else -9999.0
        lsrc = np.where(np.isclose(lsrc, lnd, atol=1e-3), np.nan, lsrc)
        ltr, lcrs = lds.transform, lds.crs
    finally:
        lds.close()
    lr_on = np.full((H, W), np.nan)
    reproject(lsrc, lr_on, src_transform=ltr, src_crs=lcrs or "EPSG:4326",
              dst_transform=tr, dst_crs=crs or "EPSG:4326",
              src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
    hr_f = np.isfinite(hr); lr_f = np.isfinite(lr_on); joint = hr_f & lr_f
    return {"decimation": dec, "hr_finite_cells_dec": int(hr_f.sum()),
            "lr_finite_on_hr_dec": int(lr_f.sum()), "joint_cells_dec": int(joint.sum()),
            "joint_frac_of_hr": round(float(joint.sum() / max(1, hr_f.sum())), 4),
            "hr_p50": round(float(np.nanpercentile(hr[hr_f], 50)), 1) if hr_f.any() else None,
            "lr_p50_over_joint": round(float(np.nanpercentile(lr_on[joint], 50)), 1) if joint.any() else None}


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out = {}

    # ---- Axial comparison: 32556 (N+S rift, ver2025) vs manifested 30466 HR ----
    log.info("=== Axial comparison ===")
    ax = {"new_32556": {}, "manifest_30466_hr": {}}
    for f in ("AxialSRift_MAUV_ver2025_Topo1m.grd", "AxialNRift_MAUV_ver2025_Topo1m.grd"):
        ax["new_32556"][f] = grid_info(RH / "MGDS_32556" / f)
    # 30466's source HR (staging) + the harmonized hr.tif
    src30466 = next((p for p in (STAG / "MGDS_30466").glob("*.asc") if "Figure" in p.name or "auv" in p.name.lower()), None)
    if src30466:
        ax["manifest_30466_hr"]["staging_src"] = grid_info(src30466)
    ax["manifest_30466_hr"]["harmonized_hr_tif"] = grid_info(HARM / "TN268__MGDS_30466" / "hr.tif")
    # spatial overlap SRift(new) vs 30466 src
    try:
        bs = ax["new_32556"]["AxialSRift_MAUV_ver2025_Topo1m.grd"]["bounds_4326"]
        bn = ax["new_32556"]["AxialNRift_MAUV_ver2025_Topo1m.grd"]["bounds_4326"]
        b3 = ax["manifest_30466_hr"].get("staging_src", {}).get("bounds_4326") or ax["manifest_30466_hr"]["harmonized_hr_tif"]["bounds_4326"]
        ax["SRift_vs_30466_overlap"] = overlap_4326(bs, b3)
        ax["NRift_vs_30466_overlap"] = overlap_4326(bn, b3)
    except Exception as e:
        ax["overlap_error"] = str(e)[:100]
    out["axial"] = ax

    # ---- L1: shared-LR-cruise leakage (Pythia/TN299, Pescadero/FK181031) ----
    log.info("=== L1 shared-LR leakage ===")
    l1 = {}
    # Pythia new 31253 (s19a) vs manifest TN299x27339 (Gorda) footprint
    try:
        bnew = grid_info(RH / "MGDS_31253" / "Pythia_auv_s19a_gcs_1m.grd")["bounds_4326"]
        bex = fp_bounds(HARM / "TN299__MGDS_27339" / "footprint.geojson")
        l1["pythia_31253_vs_TN299x27339"] = {"new_bounds": bnew, "existing_bounds": [round(x,4) for x in bex],
            **overlap_4326(bnew, bex), "shared_LR_cruise": "TN299",
            "ruling": "merge into TN299x27339 leakage_unit (default; same LR survey)"}
    except Exception as e:
        l1["pythia_err"] = str(e)[:120]
    # Pescadero new 24618 vs manifest FK181031x24367 (Alarcon) footprint
    try:
        bnew = grid_info(RH / "MGDS_24618" / "GOCPescaderoBasin_Topo1m_Geo.grd")["bounds_4326"]
        bex = fp_bounds(HARM / "FK181031__MGDS_24367" / "footprint.geojson")
        l1["pescadero_24618_vs_FK181031x24367"] = {"new_bounds": bnew, "existing_bounds": [round(x,4) for x in bex],
            **overlap_4326(bnew, bex), "shared_LR_cruise": "FK181031",
            "ruling": "merge into FK181031x24367 leakage_unit (default; same LR survey)"}
    except Exception as e:
        l1["pescadero_err"] = str(e)[:120]
    out["L1_shared_lr"] = l1

    # ---- L2: Amundsen co-location by joint cells ----
    log.info("=== L2 Amundsen co-location ===")
    out["L2_amundsen"] = l2_joint_cells(RH / "MGDS_31753" / "ShelfEdgeIntactTopo2m_2022_mgds.grd",
                                        GRID / "2009_Amundsen__MGDS_30045.grd")

    OUT.write_text(json.dumps(out, indent=2, default=str))
    log.info("Axial SRift vs 30466 overlap: %s", out["axial"].get("SRift_vs_30466_overlap"))
    log.info("Axial NRift vs 30466 overlap: %s", out["axial"].get("NRift_vs_30466_overlap"))
    log.info("L1 pythia: %s", l1.get("pythia_31253_vs_TN299x27339", {}).get("overlap"))
    log.info("L1 pescadero: %s", l1.get("pescadero_24618_vs_FK181031x24367", {}).get("overlap"))
    log.info("L2 amundsen joint_cells: %s frac=%s", out["L2_amundsen"].get("joint_cells_dec"),
             out["L2_amundsen"].get("joint_frac_of_hr"))
    log.info("wrote %s", OUT)


if __name__ == "__main__":
    main()
