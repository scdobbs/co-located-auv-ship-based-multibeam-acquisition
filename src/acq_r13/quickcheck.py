"""ACQ-R13 §2 — quick check of the local co-registration rule on three development pairs (frozen OAK files, read only).
Their hr.tif is already globally corrected, so the global re-estimate is near zero; every quadrant group must agree with
it within one ship grid cell (rigid case).  Writes booleans and counts only.
Usage: python -B -m src.acq_r13.quickcheck"""
import json
import numpy as np
import rioxarray  # noqa: F401
import rasterio
from src.acq_r01 import common as C
from src import coregister as cor
from src.phase5 import localcoreg_p5 as LC

PAIRS = ["NA080__MGDS_31289", "KM0923__MGDS_31429", "FK151121__MGDS_22383"]
out = {}
for pid in PAIRS:
    d = C.OAK / "harmonized" / pid
    hr = rioxarray.open_rasterio(d / "hr.tif", masked=True).squeeze(); lr = rioxarray.open_rasterio(d / "lr.tif", masked=True).squeeze()
    with rasterio.open(d / "joint_valid.tif") as ds:
        valid = ds.read(1) == 1
    with rasterio.open(d / "lr.tif") as ds:
        px_lr = abs(ds.transform.a)
    g = cor.estimate_rigid_xyz(hr, lr)
    est = LC.estimate(hr, lr, valid, float(abs(hr.rio.resolution()[0])), px_lr, g)
    out[pid] = {"case": est["case"], "n_groups": est["n_groups"], "all_estimated": all(x["estimated"] for x in est["groups"]),
                "all_agree_within_one_ship_cell": all(x["agrees_with_global"] for x in est["groups"]), "rigid": est["case"] == "rigid"}
    print(pid, out[pid], flush=True)
res = {"directive": "ACQ-R13 §2", "pairs": out, "all_rigid": all(v["rigid"] for v in out.values()),
       "localcoreg_p5_sha256": C.sha256_file(C.REPO / "src/phase5/localcoreg_p5.py")}
(C.REPO / "reports_post_grl_review/ACQ-R13/quickcheck_r13.json").write_text(json.dumps(res, indent=1))
print("all rigid:", res["all_rigid"])
