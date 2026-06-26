"""R0 GATE — prove the HR reader against external ground truth.

Establishes, per new pair, what the HR *source* actually is and whether a real
elevation grid exists, then proves a corrected reader on the real pairs and
shows the RGB-visualization pairs are structurally the same as the TN299
figure control. Renders PNG evidence so Steve can adjudicate visually.

The finding driving this: many staged HR tiles are 3-band uint8 RGB
slope/hillshade *renders* (filenames `..._Topo1m_slope...`), not float
bathymetry. `materialize_hr` did `ds.read(1)` = the RED channel (0-255) -> the
"+255". The real pairs are GMT `.grd` float or `_elv_` float .tif.

External anchors used (never self-consistency):
  - file dtype/colorinterp (a real DEM is float; an RGB render is uint8 R/G/B),
  - corrected source depths vs the ship LR median and the corpus depth_m,
  - a Terrain-RGB decode test (does decoding the 3 bands yield plausible depth?),
  - PNG renders for human (Steve/QGIS) confirmation.

Read-only on sources; writes only PNGs + a JSON. Run on a compute node.
"""
from __future__ import annotations
import json, logging, os
from pathlib import Path
import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from rasterio.warp import reproject, Resampling

from src import gmt_grd
from src.discovery.stage_c5_sweep import materialize_hr, catalog_crs

log = logging.getLogger("r0")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
STAGING = DATA / "staging_phase1"
HARM = DATA / "harmonized"
RESULTS_F = REPO / "reports/discovery/stage_f_results.json"
CORPUS = REPO / "reports/combined_corpus.csv"
OUT = REPO / "reports/discovery/stage_reaudit_r0.json"
PNGDIR = DATA / "qc_plots" / "r0_evidence"
RASTER_EXT = (".tif", ".tiff", ".grd", ".nc", ".asc")
FILL = -9999.0


def _decimated(ds, band=1, target=2_000_000):
    dec = max(1, int(((ds.width * ds.height) / target) ** 0.5))
    # scalar band index + 2D out_shape -> returns a 2D (H,W) array (not 1D)
    return ds.read(band, out_shape=(max(1, ds.height // dec), max(1, ds.width // dec)))


def _stats(v):
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {}
    return {"min": round(float(v.min()), 2), "p1": round(float(np.percentile(v, 1)), 2),
            "p50": round(float(np.percentile(v, 50)), 2), "p99": round(float(np.percentile(v, 99)), 2),
            "max": round(float(v.max()), 2)}


def classify_tile(p: Path):
    """Return (type, stats_band1) for a staged HR tile.
    types: gmt_grd_float | float_tif | rgb_uint8 | other_readable | unreadable."""
    rec = {"file": p.name, "size_mb": round(p.stat().st_size / 1e6, 1)}
    # GMT .grd (rasterio can't open) -> real float bathymetry
    try:
        if gmt_grd.is_gmt_grd(p):
            import netCDF4 as nc
            with nc.Dataset(str(p)) as ds:
                z = np.asarray(ds.variables["z"][:], dtype="float64")
            z = z[np.isfinite(z)]
            if z.size > 4_000_000:
                z = z[:: z.size // 4_000_000 + 1]
            rec.update(type="gmt_grd_float", count=1, dtype="float32", **_stats(z))
            return rec
    except Exception:
        pass
    for cand in (str(p), "NETCDF:" + str(p)):
        try:
            with rasterio.open(cand) as ds:
                rec["count"] = ds.count
                rec["dtype"] = ds.dtypes[0]
                rec["colorinterp"] = [c.name for c in ds.colorinterp]
                a = _decimated(ds).astype("float64")
                nd = ds.nodata
                if nd is not None:
                    a = np.where(np.isclose(a, nd, atol=1e-3), np.nan, a)
                rec.update(_stats(a))
            if rec["count"] >= 3 and all(d == "uint8" for d in (ds.dtypes if False else [rec["dtype"]])):
                rec["type"] = "rgb_uint8"
            elif rec["dtype"].startswith(("float", "int")) and rec["count"] == 1:
                rec["type"] = "float_tif" if rec.get("min", 0) < -5 else "single_band_nonneg"
            else:
                rec["type"] = "other_readable"
            return rec
        except Exception:
            continue
    rec["type"] = "unreadable"
    return rec


def corrected_read_source(hr_id, tile, tmp):
    """The CORRECTED reader: returns (array_or_None, kind). RGB uint8 sources ->
    None (no elevation). GMT .grd / float .tif -> real elevation array via the
    same materializer the pipeline uses (which is correct for float)."""
    # detect RGB visualization first
    try:
        if not gmt_grd.is_gmt_grd(Path(tile)):
            with rasterio.open(str(tile)) as ds:
                if ds.count >= 3 and all(d == "uint8" for d in ds.dtypes):
                    return None, "rgb_visualization"
    except Exception:
        pass
    mt = materialize_hr(hr_id, tile, tmp)
    if mt is None:
        return None, "unreadable"
    with rasterio.open(str(mt)) as ds:
        a = _decimated(ds).astype("float64")
        nd = ds.nodata
    if nd is not None:
        a = np.where(np.isclose(a, nd, atol=1e-3), np.nan, a)
    return a, "elevation"


def terrain_rgb_decode_test(tile, lr_med):
    """Test the Mapbox/terrarium Terrain-RGB hypothesis: elev=-10000+(R*65536+G*256+B)*0.1.
    Report decoded median; if it lands near the LR depth it'd be recoverable."""
    try:
        with rasterio.open(str(tile)) as ds:
            if ds.count < 3 or ds.dtypes[0] != "uint8":
                return None
            dec = max(1, int(((ds.width*ds.height)/1e6)**0.5))
            shp = (3, max(1, ds.height//dec), max(1, ds.width//dec))
            rgb = ds.read(out_shape=shp).astype("float64")
        R, G, B = rgb[0], rgb[1], rgb[2]
        terr = -10000.0 + (R*65536.0 + G*256.0 + B) * 0.1
        mapbox = -10000.0 + (R*256.0*256.0 + G*256.0 + B) * 0.1
        return {"terrarium_p50": round(float(np.median(terr)), 1),
                "mapbox_p50": round(float(np.median(mapbox)), 1),
                "lr_med": lr_med,
                "plausible": bool(lr_med is not None and (
                    abs(np.median(terr) - lr_med) < 200 or abs(np.median(mapbox) - lr_med) < 200))}
    except Exception as e:
        return {"error": str(e)[:80]}


def lr_median_for(pid):
    lr_p = HARM / pid / "lr.tif"
    if not lr_p.exists():
        return None
    with rasterio.open(str(lr_p)) as ds:
        a = _decimated(ds).astype("float64")
        nd = ds.nodata if ds.nodata is not None else FILL
    a = a[np.isfinite(a) & ~np.isclose(a, nd, atol=1e-3)]
    return round(float(np.median(a)), 1) if a.size else None


def render_png(pid, hr_id, selected_tile, sel_type, out_png):
    """3-panel: original source | current harmonized hr.tif | LR — for Steve."""
    fig, ax = plt.subplots(1, 3, figsize=(15, 5))
    # panel 1: original source
    try:
        if sel_type == "rgb_uint8":
            with rasterio.open(str(selected_tile)) as ds:
                dec = max(1, int(((ds.width*ds.height)/1e6)**0.5))
                rgb = ds.read(out_shape=(3, ds.height//dec, ds.width//dec))
            ax[0].imshow(np.transpose(rgb, (1, 2, 0)))
            ax[0].set_title(f"SOURCE (3-band uint8 RGB)\n{selected_tile.name[:38]}", fontsize=8)
        else:
            tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "r0png"
            a, kind = corrected_read_source(hr_id, selected_tile, tmp)
            if a is not None:
                m = np.where(np.isfinite(a), a, np.nan)
                im = ax[0].imshow(m, cmap="viridis"); plt.colorbar(im, ax=ax[0], shrink=0.7)
            ax[0].set_title(f"SOURCE ({sel_type}, float depth)\n{selected_tile.name[:38]}", fontsize=8)
    except Exception as e:
        ax[0].set_title(f"source err {str(e)[:30]}")
    # panel 2: current harmonized hr.tif
    try:
        with rasterio.open(str(HARM / pid / "hr.tif")) as ds:
            a = _decimated(ds).astype("float64"); nd = ds.nodata
        if nd is not None and nd == nd:
            a = np.where(np.isclose(a, nd, atol=1e-3), np.nan, a)
        im = ax[1].imshow(a, cmap="viridis"); plt.colorbar(im, ax=ax[1], shrink=0.7)
        ax[1].set_title("harmonized hr.tif (current)", fontsize=9)
    except Exception as e:
        ax[1].set_title(f"hr err {str(e)[:30]}")
    # panel 3: LR
    try:
        with rasterio.open(str(HARM / pid / "lr.tif")) as ds:
            a = _decimated(ds).astype("float64"); nd = ds.nodata if ds.nodata is not None else FILL
        a = np.where(np.isclose(a, nd, atol=1e-3), np.nan, a)
        im = ax[2].imshow(a, cmap="viridis"); plt.colorbar(im, ax=ax[2], shrink=0.7)
        ax[2].set_title("ship LR (real bathymetry)", fontsize=9)
    except Exception as e:
        ax[2].set_title(f"lr err {str(e)[:30]}")
    fig.suptitle(f"{pid}  ({hr_id})  selected_source_type={sel_type}", fontsize=10)
    fig.tight_layout()
    fig.savefig(out_png, dpi=80); plt.close(fig)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    PNGDIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "r0"
    tmp.mkdir(parents=True, exist_ok=True)
    recs = json.loads(RESULTS_F.read_text())
    import pandas as pd
    corpus = {r["pair_id"]: r for r in pd.read_csv(CORPUS).to_dict("records")}
    # pairs to render (directive-named RGB + controls + reals)
    render_set = {"EW0207__MGDS_32558", "FK171110__MGDS_24485", "RC2511__MGDS_32241",
                  "2009_Amundsen__MGDS_30045", "TN299__MGDS_31256", "NA076__MGDS_32321",
                  "AT37-13__MGDS_31199", "AT42-03__MGDS_32007", "SKQ201705S__MGDS_31255",
                  "TN399__MGDS_30373", "NA080__MGDS_31290"}

    out = []
    for r in recs:
        pid, hr_id = r["pair_id"], r["hr_id"]
        d = STAGING / hr_id.replace(":", "_")
        tiles = []
        if d.is_dir():
            tiles = [p for p in d.iterdir() if p.suffix.lower() in RASTER_EXT
                     and not p.name.endswith(".provenance.json")
                     and not p.name.lower().endswith(".pdf")
                     and "diff" not in p.name.lower() and "interp" not in p.name.lower()]
        tiles = sorted(tiles, key=lambda x: -x.stat().st_size)
        inv = [classify_tile(p) for p in tiles]
        # pipeline selection = largest non-diff (staged_hr_raster behavior)
        sel = tiles[0] if tiles else None
        sel_type = inv[0]["type"] if inv else None
        types = {s["type"] for s in inv}
        has_float = any(t in types for t in ("gmt_grd_float", "float_tif"))
        only_rgb = bool(types) and types <= {"rgb_uint8", "single_band_nonneg", "other_readable", "unreadable"} and not has_float
        lr_med = lr_median_for(pid)
        rec = {"pair_id": pid, "hr_id": hr_id, "n_tiles": len(tiles),
               "selected_source": sel.name if sel else None, "selected_type": sel_type,
               "tile_types": sorted(types), "has_float_elevation_source": has_float,
               "rgb_visualization_only": only_rgb, "lr_median_m": lr_med,
               "expected_depth_m": corpus.get(pid, {}).get("depth_m"),
               "f5_bucket": corpus.get(pid, {}).get("f5_bucket"),
               "inventory": inv}
        # corrected read on the best float source if any
        if has_float:
            best = next((p for p, s in zip(tiles, inv) if s["type"] in ("gmt_grd_float", "float_tif")), None)
            a, kind = corrected_read_source(hr_id, best, tmp)
            if a is not None:
                rec["corrected_source_stats"] = _stats(a[np.isfinite(a)])
                rec["corrected_source_file"] = best.name
        # terrain-rgb decode test if RGB selected
        if sel_type == "rgb_uint8":
            rec["terrain_rgb_test"] = terrain_rgb_decode_test(sel, lr_med)
        # render
        if pid in render_set and sel is not None:
            png = PNGDIR / f"{pid}.png"
            try:
                render_png(pid, hr_id, sel, sel_type, png)
                rec["png"] = str(png)
            except Exception as e:
                rec["png_err"] = str(e)[:100]
        out.append(rec)
        log.info("[%s] sel=%s float_src=%s rgb_only=%s lr_med=%s corr_p50=%s",
                 pid, sel_type, has_float, only_rgb, lr_med,
                 rec.get("corrected_source_stats", {}).get("p50"))
    OUT.write_text(json.dumps(out, indent=2, default=str))
    from collections import Counter
    log.info("SELECTED_TYPE %s", dict(Counter(o["selected_type"] for o in out)))
    log.info("RGB_ONLY pairs: %s", [o["pair_id"] for o in out if o["rgb_visualization_only"]])
    log.info("wrote %s", OUT)


if __name__ == "__main__":
    main()
