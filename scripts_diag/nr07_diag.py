"""ACQ-R02 diagnostic (development pair NR07-1__MGDS_31813/31814): does the raw-swath LR have soundings under each HR tile?"""
import os, rasterio, numpy as np
from rasterio.windows import from_bounds
from rasterio.warp import transform_bounds
from src.acq_r01.harmonize_new import hr_rasters, materialize, lr_to_tif
from pathlib import Path
tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "nr07_diag"; tmp.mkdir(exist_ok=True, parents=True)
lr_tif, post = lr_to_tif("NR07-1", tmp)
L = rasterio.open(lr_tif)
print("LR grid", L.crs, L.shape, L.res, "bounds", [round(x, 4) for x in L.bounds], flush=True)
for hr in ("MGDS:31813", "MGDS:31814"):
    for i, p in enumerate(hr_rasters(hr)):
        mt = materialize(hr, p, tmp / f"{hr[-5:]}_t{i}.tif")
        if mt is None:
            print(hr, p.name[:50], "materialize None", flush=True); continue
        with rasterio.open(mt) as ds:
            b = transform_bounds(ds.crs, L.crs, *ds.bounds); arr = ds.read(1, masked=True)
            hv = int((~np.ma.getmaskarray(arr)).sum()); hp50 = float(np.ma.median(arr)) if hv else None
        try:
            w = from_bounds(*b, transform=L.transform)
            sub = L.read(1, window=w, masked=True, boundless=True)
            lv = (~np.ma.getmaskarray(sub)) & np.isfinite(sub.filled(np.nan)); n_lr = int(lv.sum()); lp50 = float(np.nanmedian(sub.filled(np.nan)[lv])) if n_lr else None
        except Exception as e:
            n_lr, lp50 = f"err {e}", None
        print(hr, p.name[:58], ds.crs, [round(x, 4) for x in b], round(ds.res[0], 3), "HR valid", hv, "HR p50", hp50, "| LR cells under tile", n_lr, "LR p50", lp50, flush=True)
