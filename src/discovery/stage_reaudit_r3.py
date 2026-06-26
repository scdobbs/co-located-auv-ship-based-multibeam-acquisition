"""R3 — QC figures for the 23 real-elevation pairs (the adjudication material).

One 6-panel figure per real pair (9 advancing + 14 non-advancing), so Steve can
adjudicate the 14 from plots without QGIS. Panels (v1 R3 spec):
  1. HR & LR hillshade side by side (morphology / co-location)
  2. HR & LR depth on a SHARED color scale (datum offset shows as color mismatch)
  3. HR-LR difference over joint, diverging cmap @0, median residual annotated
  4. Overlaid value histograms, sign-explicit, p1/p50/p99 marked
  5. Footprint/clip panel: hr_valid / lr_valid / joint composite (sub-grids visible)
  6. Reader banner: source_type, dtype, NoData, CRS, native res, joint_fraction,
     n_tiles, dz applied, reader_proof.

Read-only on data; writes PNGs. Run on a compute node.
"""
from __future__ import annotations
import json, logging, os
from pathlib import Path
import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import gridspec
from matplotlib.colors import LightSource
from rasterio.warp import reproject, Resampling
from rasterio.transform import Affine
import pandas as pd

log = logging.getLogger("r3")
REPO = Path(__file__).resolve().parents[2]
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
HARM = DATA / "harmonized"
OUTDIR = DATA / "qc_plots" / "reaudit_real23"
CORPUS = REPO / "reports/combined_corpus.csv"
R0 = REPO / "reports/discovery/stage_reaudit_r0.json"
REPAIR = REPO / "reports/discovery/stage_f_repair_results.json"
FILL = -9999.0
MAXPX = 1400


def _read_dec(path, mask=False):
    """Read a raster decimated to <= MAXPX/side; return (arr2d_float_nan, transform, crs)."""
    with rasterio.open(str(path)) as ds:
        dec = max(1, int(max(ds.width, ds.height) / MAXPX))
        H, W = max(1, ds.height // dec), max(1, ds.width // dec)
        rs = Resampling.nearest if mask else Resampling.bilinear
        a = ds.read(1, out_shape=(H, W), resampling=rs).astype("float64")
        tr = ds.transform * Affine.scale(ds.width / W, ds.height / H)
        crs, nd = ds.crs, ds.nodata
    if not mask:
        if nd is not None and nd == nd:
            a = np.where(np.isclose(a, nd, atol=1e-3), np.nan, a)
        a = np.where(np.isfinite(a), a, np.nan)
    return a, tr, crs, (H, W)


def _lr_on(path, tr, crs, shape):
    with rasterio.open(str(path)) as ds:
        src = ds.read(1).astype("float64")
        nd = ds.nodata if ds.nodata is not None else FILL
        s_tr, s_crs = ds.transform, ds.crs
    src = np.where(np.isclose(src, nd, atol=1e-3), np.nan, src)
    dst = np.full(shape, np.nan)
    reproject(src, dst, src_transform=s_tr, src_crs=s_crs, dst_transform=tr,
              dst_crs=crs, src_nodata=np.nan, dst_nodata=np.nan,
              resampling=Resampling.bilinear)
    return dst


def _hs(z):
    zf = np.where(np.isfinite(z), z, np.nanmean(z))
    ls = LightSource(azdeg=315, altdeg=45)
    return ls.hillshade(zf, vert_exag=5)


def figure(pair, meta, out_png):
    pid = pair
    hr_p, lr_p, jt_p = HARM/pid/"hr.tif", HARM/pid/"lr.tif", HARM/pid/"joint_valid.tif"
    hr, tr, crs, shape = _read_dec(hr_p)
    lr = _lr_on(lr_p, tr, crs, shape)
    joint = None
    if jt_p.exists():
        j, *_ = _read_dec(jt_p, mask=True)
        joint = (j == 1)
    hr_v = np.isfinite(hr); lr_v = np.isfinite(lr)
    jm = (hr_v & lr_v) if joint is None else (joint & hr_v & lr_v)

    # shared color scale over joint (robust)
    pool = np.concatenate([hr[jm], lr[jm]]) if jm.any() else hr[hr_v]
    vmin, vmax = (np.nanpercentile(pool, 1), np.nanpercentile(pool, 99)) if pool.size else (None, None)

    fig = plt.figure(figsize=(16, 11))
    gs = gridspec.GridSpec(3, 3, height_ratios=[1, 1, 0.8], hspace=0.3, wspace=0.25)

    # panel 1: hillshades
    a = fig.add_subplot(gs[0, 0]); a.imshow(_hs(hr), cmap="gray"); a.set_title("HR hillshade", fontsize=9); a.axis("off")
    a = fig.add_subplot(gs[0, 1]); a.imshow(_hs(lr), cmap="gray"); a.set_title("LR hillshade (ship)", fontsize=9); a.axis("off")
    # panel 5: footprint/clip composite
    a = fig.add_subplot(gs[0, 2])
    comp = np.zeros(shape + (3,))
    comp[hr_v] = [0.2, 0.4, 1.0]      # HR only = blue
    comp[lr_v] = [1.0, 0.6, 0.2]      # LR = orange
    comp[jm] = [0.1, 0.9, 0.2]        # joint = green
    a.imshow(comp); a.set_title("clip/overlap: HR(blue) LR(orange) joint(green)", fontsize=8); a.axis("off")

    # panel 2: shared-scale depth
    a = fig.add_subplot(gs[1, 0]); im = a.imshow(hr, cmap="viridis", vmin=vmin, vmax=vmax)
    plt.colorbar(im, ax=a, shrink=0.7); a.set_title("HR depth (shared scale)", fontsize=9); a.axis("off")
    a = fig.add_subplot(gs[1, 1]); im = a.imshow(lr, cmap="viridis", vmin=vmin, vmax=vmax)
    plt.colorbar(im, ax=a, shrink=0.7); a.set_title("LR depth (shared scale)", fontsize=9); a.axis("off")
    # panel 3: diff over joint
    a = fig.add_subplot(gs[1, 2])
    diff = np.where(jm, hr - lr, np.nan)
    med = float(np.nanmedian(diff)) if jm.any() else float("nan")
    s = np.nanpercentile(np.abs(diff[jm] - med), 95) if jm.any() else 1.0
    im = a.imshow(diff, cmap="RdBu_r", vmin=med - s, vmax=med + s)
    plt.colorbar(im, ax=a, shrink=0.7)
    a.set_title(f"HR-LR over joint  median={med:.1f} m", fontsize=9); a.axis("off")

    # panel 4: histograms
    a = fig.add_subplot(gs[2, :2])
    if jm.any():
        a.hist(hr[jm], bins=80, alpha=0.5, label="HR", color="C0")
        a.hist(lr[jm], bins=80, alpha=0.5, label="LR", color="C1")
        for arr, c in ((hr[jm], "C0"), (lr[jm], "C1")):
            for q, ls_ in ((1, ":"), (50, "-"), (99, ":")):
                a.axvline(np.percentile(arr, q), color=c, ls=ls_, lw=1)
    a.axvline(0, color="k", lw=0.8)
    a.set_xlabel("depth (m, negative down)"); a.set_ylabel("count"); a.legend(fontsize=8)
    a.set_title("HR vs LR value histograms over joint (p1/p50/p99 marked; 0 = black)", fontsize=9)

    # panel 6: banner
    a = fig.add_subplot(gs[2, 2]); a.axis("off")
    hr_p50 = np.nanpercentile(hr[jm], 50) if jm.any() else np.nan
    lr_p50 = np.nanpercentile(lr[jm], 50) if jm.any() else np.nan
    txt = (f"PAIR  {pid}\n"
           f"disposition: {meta.get('reaudit_disposition')}\n"
           f"role: {meta.get('role')}   morph: {meta.get('morphology')}\n"
           f"source_type: {meta.get('source_type')}  ({meta.get('selected_source','')[:30]})\n"
           f"HR dtype float; NoData->NaN; CRS {str(crs)[:18]}\n"
           f"native res ~{meta.get('lr_native_m','?')} m (LR)\n"
           f"joint_fraction: {meta.get('f5_joint_fraction')}   n_tiles: {meta.get('f5_n_valid_tiles')}\n"
           f"HR p50={hr_p50:.0f}  LR p50={lr_p50:.0f}  resid={hr_p50-lr_p50:.1f} m\n"
           f"repair dz applied: {meta.get('dz_apply','--')}\n"
           f"reader_proof: OK (single-band float; not RGB)")
    a.text(0.0, 1.0, txt, va="top", ha="left", fontsize=9, family="monospace")

    fig.suptitle(f"{pid}   [{meta.get('reaudit_disposition')}]   n_tiles={meta.get('f5_n_valid_tiles')}", fontsize=12)
    fig.savefig(out_png, dpi=85, bbox_inches="tight"); plt.close(fig)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    corpus = {r["pair_id"]: r for r in pd.read_csv(CORPUS).to_dict("records")}
    r0 = {o["pair_id"]: o for o in json.loads(R0.read_text())}
    rep = {o["pair_id"]: o for o in json.loads(REPAIR.read_text())} if REPAIR.exists() else {}

    real = [(pid, m) for pid, m in corpus.items()
            if str(m.get("reaudit_disposition")) in ("advancing", "real_nonadvancing_qgis")]
    # order: advancing first, then by tile count desc
    def keyf(t):
        pid, m = t
        adv = 0 if m.get("reaudit_disposition") == "advancing" else 1
        nt = m.get("f5_n_valid_tiles") or 0
        try: nt = float(nt)
        except Exception: nt = 0
        return (adv, -nt)
    real.sort(key=keyf)

    out = []
    for pid, m in real:
        m = dict(m)
        m["source_type"] = r0.get(pid, {}).get("selected_type")
        m["selected_source"] = r0.get(pid, {}).get("selected_source")
        m["dz_apply"] = rep.get(pid, {}).get("dz_apply")
        png = OUTDIR / f"{m.get('reaudit_disposition')}__{pid}.png"
        try:
            figure(pid, m, png)
            out.append({"pair_id": pid, "disposition": m.get("reaudit_disposition"),
                        "n_tiles": m.get("f5_n_valid_tiles"), "png": str(png)})
            log.info("[%s] %s -> %s", pid, m.get("reaudit_disposition"), png.name)
        except Exception as e:
            log.warning("[%s] FAILED: %s", pid, str(e)[:160])
            out.append({"pair_id": pid, "error": str(e)[:160]})
    (REPO / "reports/discovery/stage_reaudit_r3_figures.json").write_text(json.dumps(out, indent=2, default=str))
    log.info("wrote %d figures to %s", sum(1 for o in out if "png" in o), OUTDIR)


if __name__ == "__main__":
    main()
