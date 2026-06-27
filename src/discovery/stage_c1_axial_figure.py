"""Axial comparison figure for Steve's supersede ruling.

Compares the manifested HR (TN268x30466 = axsrift_auv1m, 'preliminary') against the
new float 32556 (AxialSRift + AxialNRift, ver2025) — hillshade + shared-scale
depth + a coverage/extent map + a banner (res/area/vintage/overlap), so the
supersede-vs-skip-vs-new-pair call is visual.
"""
from __future__ import annotations
import logging
from pathlib import Path
import numpy as np
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import gridspec
from matplotlib.patches import Rectangle
from matplotlib.colors import LightSource
from rasterio.warp import transform_bounds

log = logging.getLogger("axfig")
DATA = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
RH = DATA / "reharvest_c1/MGDS_32556"
OLD = DATA / "harmonized/TN268__MGDS_30466/hr.tif"
OUT = DATA / "qc_plots/reaudit_real23/AXIAL_compare_30466_vs_32556.png"
MAXPX = 1100


def read_dec(path):
    for cand in (str(path), "NETCDF:" + str(path)):
        try:
            ds = rasterio.open(cand)
        except Exception:
            continue
        try:
            dec = max(1, int(max(ds.width, ds.height) / MAXPX))
            H, W = max(1, ds.height // dec), max(1, ds.width // dec)
            a = ds.read(1, out_shape=(H, W)).astype("float64")
            nd = ds.nodata
            if nd is not None:
                a = np.where(np.isclose(a, nd, atol=1e-3), np.nan, a)
            a = np.where(np.isfinite(a), a, np.nan)
            b = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds) if ds.crs else ds.bounds
            res_m = abs(ds.res[0]) * 111320 if (ds.crs and ds.crs.is_geographic) else abs(ds.res[0])
            return a, b, {"w": ds.width, "h": ds.height, "res_m": round(float(res_m), 2)}
        finally:
            ds.close()
    return None, None, None


def hs(z):
    zf = np.where(np.isfinite(z), z, np.nanmean(z))
    return LightSource(azdeg=315, altdeg=45).hillshade(zf, vert_exag=8)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    items = [("OLD: TN268x30466 HR\n(axsrift 'preliminary')", OLD),
             ("NEW: 32556 AxialSRift\n(ver2025, same area)", RH / "AxialSRift_MAUV_ver2025_Topo1m.grd"),
             ("NEW: 32556 AxialNRift\n(ver2025, NEW seafloor)", RH / "AxialNRift_MAUV_ver2025_Topo1m.grd")]
    data = [(t, *read_dec(p)) for t, p in items]
    allv = np.concatenate([a[np.isfinite(a)] for _, a, _, _ in data if a is not None])
    vmin, vmax = np.nanpercentile(allv, 1), np.nanpercentile(allv, 99)

    fig = plt.figure(figsize=(15, 12))
    gs = gridspec.GridSpec(3, 3, height_ratios=[1, 1, 0.9], hspace=0.28, wspace=0.2)
    for j, (t, a, b, meta) in enumerate(data):
        ax = fig.add_subplot(gs[0, j])
        if a is not None:
            ax.imshow(hs(a), cmap="gray")
        ax.set_title(t + (f"\n{meta['w']}x{meta['h']} @~{meta['res_m']}m" if meta else ""), fontsize=9)
        ax.axis("off")
        ax = fig.add_subplot(gs[1, j])
        if a is not None:
            im = ax.imshow(a, cmap="viridis", vmin=vmin, vmax=vmax); plt.colorbar(im, ax=ax, shrink=0.7)
        ax.set_title("depth (shared scale)", fontsize=8); ax.axis("off")

    # extent / coverage map
    ax = fig.add_subplot(gs[2, :2])
    colors = ["k", "C3", "C0"]
    for (t, a, b, meta), c in zip(data, colors):
        if b is None:
            continue
        ax.add_patch(Rectangle((b[0], b[1]), b[2] - b[0], b[3] - b[1], fill=False, edgecolor=c, lw=2,
                               label=t.split(":")[0] + " " + t.split("\n")[0].split(" ")[-1]))
    ax.set_xlabel("lon"); ax.set_ylabel("lat"); ax.legend(fontsize=8, loc="upper right")
    ax.set_title("Coverage (4326): OLD 30466 sits INSIDE new SRift; NRift is new seafloor to the north", fontsize=9)
    ax.set_aspect("equal", adjustable="datalim"); ax.autoscale_view()

    # banner
    ax = fig.add_subplot(gs[2, 2]); ax.axis("off")
    b_old = data[0][2]; b_s = data[1][2]; b_n = data[2][2]
    txt = ("AXIAL SUPERSEDE COMPARISON\n\n"
           "OLD TN268x30466 HR = axsrift_auv1m\n  (manifested, 'preliminary' vintage)\n"
           "NEW 32556 = AxialSRift + AxialNRift\n  (MBARI ver2025, Dec-2025 reprocess)\n\n"
           "SRift vs 30466: IoU 0.31; 30466 is\n  100% INSIDE SRift; SRift ~3x larger\n"
           "NRift vs 30466: NO overlap (new area)\n\n"
           "Both ~1 m. Same MBARI Axial survey,\n  reprocessed + extended.\n\n"
           "Options:\n"
           " (a) SUPERSEDE 30466 HR -> SRift\n     (recorded; re-coreg/QC)\n"
           " (b) NRift as one NEW pair\n     (distinct seafloor)\n"
           " (c) SKIP")
    ax.text(0.0, 1.0, txt, va="top", ha="left", fontsize=9, family="monospace")

    fig.suptitle("Axial: manifested HR (TN268x30466) vs re-harvested float 32556 (ver2025)", fontsize=12)
    fig.savefig(OUT, dpi=85, bbox_inches="tight"); plt.close(fig)
    log.info("wrote %s", OUT)


if __name__ == "__main__":
    main()
