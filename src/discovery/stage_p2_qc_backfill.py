"""Phase 2 — QC overlay backfill for the 5 pairs that never had overlays.

STANDALONE, READ-ONLY renderer: visualizes the EXISTING harmonized hr.tif /
lr.tif / joint_valid.tif. It does NOT recompute masks or co-registration and
does NOT call stage_f5_valid_masks.py. The mask files' sha256 are snapshotted
before and asserted unchanged after, to prove nothing was mutated.

For each of the 5 pairs:
  - render a 4-panel overlay (HR hillshade, LR hillshade, shared-scale HR depth,
    joint_valid mask) to scratch qc/<pid>_overlay.png,
  - persist it to OAK qc/ byte-verified, chmod 0444,
  - set the manifest qc_artifact_path (root-relative) for that pair.
Then resync the manifest + grid anchors (manifest write guarded by the anchor;
grids untouched). Run as a Slurm job.
"""
from __future__ import annotations
import hashlib, json, logging, os, shutil, stat
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource

from src.discovery.validated_anchor import (
    assert_validated_anchor, assert_validated_grids, is_new)

log = logging.getLogger("p2qc")
REPO = Path(__file__).resolve().parents[2]
CANON = REPO / "manifest/pairs.parquet"
GRID_SHA_REF = REPO / "manifest/validated_grid_sha256.json"
RESULT = REPO / "reports/discovery/stage_p2_qc_backfill_result.json"
DATA_ROOT = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
SCR_HARM = DATA_ROOT / "harmonized"
OAKROOT = Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy")
OAK_HARM = OAKROOT / "harmonized"
OAK_MANI = OAKROOT / "manifest" / "pairs.parquet"
RO = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
RW = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH

PAIRS = ["FK181031__MGDS_24618", "TN299__MGDS_31253", "NA076__MGDS_32317",
         "EW0207__MGDS_32556", "2009_Amundsen__MGDS_30046"]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _read(p, max_px=2000):
    """Decimated read: cap the longest axis at max_px so a QC PNG of a huge
    full-res grid (e.g. 311 MB 1 m HR) does not OOM. Resolution is scaled to
    match the decimation so hillshade dx/dy stay physically correct."""
    with rasterio.open(str(p)) as ds:
        h, w = ds.height, ds.width
        f = max(1, int(np.ceil(max(h, w) / max_px)))
        oh, ow = max(1, h // f), max(1, w // f)
        a = ds.read(1, masked=True, out_shape=(oh, ow)).astype("float64").filled(np.nan)
        res = (abs(ds.res[0]) * w / ow, abs(ds.res[1]) * h / oh)
    return a, res


def _hillshade(z, dx, dy):
    zf = np.where(np.isfinite(z), z, np.nanmedian(z))
    ls = LightSource(azdeg=315, altdeg=45)
    return ls.hillshade(zf, vert_exag=1.0, dx=max(dx, 1e-6), dy=max(dy, 1e-6))


def render(pid, src):
    hr, hres = _read(src / "hr.tif")
    lr, lres = _read(src / "lr.tif")
    jv = None
    jvp = src / "joint_valid.tif"
    if jvp.exists():
        jv, _ = _read(jvp)
    vmin = np.nanpercentile(np.concatenate([hr[np.isfinite(hr)], lr[np.isfinite(lr)]]), 2)
    vmax = np.nanpercentile(np.concatenate([hr[np.isfinite(hr)], lr[np.isfinite(lr)]]), 98)
    ntiles = int(np.isfinite(jv).sum()) if jv is not None else 0

    fig, ax = plt.subplots(1, 4, figsize=(20, 5.2))
    ax[0].imshow(_hillshade(hr, *hres), cmap="gray"); ax[0].set_title(f"HR hillshade ({hres[0]:.1f} m)")
    ax[1].imshow(_hillshade(lr, *lres), cmap="gray"); ax[1].set_title(f"LR hillshade ({lres[0]:.1f} m)")
    im = ax[2].imshow(hr, cmap="viridis", vmin=vmin, vmax=vmax)
    ax[2].set_title("HR depth (m, shared scale)"); fig.colorbar(im, ax=ax[2], shrink=0.8)
    if jv is not None:
        ax[3].imshow(np.isfinite(jv) & (jv > 0), cmap="Greens"); ax[3].set_title("joint_valid mask")
    else:
        ax[3].axis("off"); ax[3].set_title("no joint_valid")
    for a in ax[:3]:
        a.set_xticks([]); a.set_yticks([])
    fig.suptitle(f"{pid}  |  depth {vmin:.0f}..{vmax:.0f} m  |  joint-valid px {ntiles}  "
                 f"|  QC backfill (read-only, no recoreg)", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    qc = src / "qc"; qc.mkdir(exist_ok=True)
    out = qc / f"{pid}_overlay.png"
    fig.savefig(out, dpi=110); plt.close(fig)
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = {"ok": False, "pairs": []}

    canon = pd.read_parquet(CANON)
    assert_validated_anchor(canon)
    grid_ref = json.loads(GRID_SHA_REF.read_text())
    assert_validated_grids(OAK_HARM, grid_ref)
    log.info("ANCHOR BEFORE: PASS")

    for pid in PAIRS:
        assert is_new(pid), pid
        src = SCR_HARM / pid
        assert src.exists(), f"missing scratch dir {src}"
        # snapshot mask shas (must be unchanged)
        masks = {f: sha256(src / f) for f in ("hr_valid.tif", "lr_valid.tif", "joint_valid.tif")
                 if (src / f).exists()}
        out = render(pid, src)
        # persist to OAK
        odst = OAK_HARM / pid / "qc" / out.name
        odst.parent.mkdir(parents=True, exist_ok=True)
        if odst.exists():
            os.chmod(odst, RW)
        shutil.copy2(out, odst)
        ok = sha256(out) == sha256(odst)
        os.chmod(odst, RO)
        assert ok, f"OAK qc byte-verify failed {pid}"
        # masks unchanged
        drift = [f for f, s in masks.items() if sha256(src / f) != s]
        assert not drift, f"MASK MUTATED for {pid}: {drift}"
        # set qc_artifact_path (root-relative)
        rel = f"harmonized/{pid}/qc/{out.name}"
        canon.loc[canon.pair_id == pid, "qc_artifact_path"] = rel
        res["pairs"].append({"pair_id": pid, "overlay": str(odst), "masks_unchanged": True,
                             "qc_artifact_path": rel})
        log.info("QC backfill %-30s -> %s (masks unchanged)", pid, rel)

    # write manifest + resync OAK (guarded; grids untouched)
    assert_validated_anchor(canon)
    bk = REPO / "manifest/pairs.parquet.bak_2026-06-26_qcbackfill"
    if not bk.exists():
        shutil.copy2(CANON, bk)
    canon.to_parquet(CANON, index=False)
    assert_validated_anchor(pd.read_parquet(CANON))
    if OAK_MANI.exists():
        os.chmod(OAK_MANI, RW)
    shutil.copy2(CANON, OAK_MANI)
    man_ok = sha256(CANON) == sha256(OAK_MANI)
    os.chmod(OAK_MANI, RO)
    assert man_ok
    assert_validated_anchor(pd.read_parquet(OAK_MANI))
    assert_validated_grids(OAK_HARM, grid_ref)
    res["oak_manifest_byte_identical"] = man_ok
    res["anchor_after"] = "PASS"
    res["ok"] = True
    RESULT.write_text(json.dumps(res, indent=2, default=str))
    log.info("=== QC BACKFILL COMPLETE: 5 overlays rendered+persisted; masks unchanged; "
             "qc_artifact_path set; anchor PASS ===")


if __name__ == "__main__":
    main()
