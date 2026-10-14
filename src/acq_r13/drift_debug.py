"""ACQ-R13 v4.1 — the drift-case write path on a development pair (NA080__MGDS_31289, frozen OAK files, read only).
A zero tolerance forces the drift case; the drift output must write (the v4 bug: inherited _FillValue) and sit on the
same lattice as the frozen rigid correction.  Prints booleans / counts only.  Usage: python -B -m src.acq_r13.drift_debug"""
import json, numpy as np, rioxarray, rasterio
from src.acq_r01 import common as C
from src import coregister as cor
from src.phase5 import localcoreg_p5 as LC
d = C.OAK / "harmonized" / "NA080__MGDS_31289"
hr = rioxarray.open_rasterio(d / "hr.tif", masked=True).squeeze(); lr = rioxarray.open_rasterio(d / "lr.tif", masked=True).squeeze()
with rasterio.open(d / "joint_valid.tif") as ds:
    valid = ds.read(1) == 1
g = cor.estimate_rigid_xyz(hr, lr)
est = LC.estimate(hr, lr, valid, float(abs(hr.rio.resolution()[0])), 0.0, g)
res = {"case": est["case"], "n_groups": est["n_groups"]}
for name, da in (("drift", LC.apply_drift(hr, g, est)), ("rigid", cor.apply_xyz(hr, g.dx_m, g.dy_m, g.dz_m))):
    da.rio.write_nodata(np.nan, inplace=True)
    da.rio.to_raster(f"/tmp/r13_{name}.tif", compress="DEFLATE", tiled=True, BIGTIFF="IF_SAFER")
with rasterio.open("/tmp/r13_drift.tif") as a, rasterio.open("/tmp/r13_rigid.tif") as b:
    res.update({"drift_written": True, "same_transform": a.transform == b.transform, "same_shape": a.shape == b.shape, "same_crs": a.crs == b.crs,
                "residual_px": [x.get("residual_px") for x in est["groups"]]})
(C.REPO / "reports_post_grl_review/ACQ-R13/drift_check_v4_1.json").write_text(json.dumps(res, indent=1, default=str))
print(res)
