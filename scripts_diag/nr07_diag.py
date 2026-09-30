"""ACQ-R02 diagnostic (development pair NR07-1__MGDS_31813): where is the LR valid data relative to the HR tiles?"""
import rasterio, numpy as np, geopandas as gpd
from rasterio.features import shapes
from shapely.geometry import shape
from shapely.ops import unary_union
from src.acq_r01.harmonize_new import hr_rasters, materialize, lr_to_tif
from pathlib import Path
import os
tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "nr07_diag"; tmp.mkdir(exist_ok=True, parents=True)
lr_tif, post = lr_to_tif("NR07-1", tmp)
with rasterio.open(lr_tif) as ds:
    a = ds.read(1, masked=True); v = (~np.ma.getmaskarray(a)) & np.isfinite(a.filled(np.nan))
    print("LR grid", ds.crs, ds.shape, ds.res, "bounds", [round(x, 4) for x in ds.bounds], "valid n", int(v.sum()), "frac", round(float(v.mean()), 3), flush=True)
    polys = [shape(s) for s, val in shapes(v.astype("uint8"), mask=v, transform=ds.transform) if val == 1]
lrp = unary_union(polys); print("LR valid bounds", [round(x, 4) for x in lrp.bounds], "area deg2", lrp.area, flush=True)
hf = gpd.read_file("/oak/stanford/groups/hilley/auv_ship_colocated_bathy/raw_hr/MGDS_31813/footprint.geojson").geometry.union_all()
print("HR footprint bounds", [round(x, 4) for x in hf.bounds], "area deg2", hf.area, "inter LR-valid deg2", hf.intersection(lrp).area, flush=True)
for i, p in enumerate(hr_rasters("MGDS:31813")):
    mt = materialize("MGDS:31813", p, tmp / f"t{i}.tif")
    if mt is None:
        print(p.name[:50], "materialize None"); continue
    with rasterio.open(mt) as ds:
        b = ds.bounds; arr = ds.read(1, masked=True)
        from shapely.geometry import box
        print(p.name[:58], ds.crs, [round(x, 4) for x in (b.left, b.bottom, b.right, b.top)], ds.res[0], "valid", int((~np.ma.getmaskarray(arr)).sum()), "p50", float(np.ma.median(arr)), "inter LR-valid", box(*b).intersection(lrp).area, flush=True)
