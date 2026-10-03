"""ACQ-R04 §0.2 — self-test of the lockbox guard and its confirmatory extension.

Every patched reader (builtins.open, rasterio.open, numpy.load, geopandas.read_file, pyogrio.read_dataframe,
pandas.read_parquet) is called on (a) a path containing each lockbox pair id and (b) a path under
OAK harmonized_confirmatory/.  Each call must raise PermissionError from the guard (the paths need not exist:
the guard fires before any filesystem access).  A control read of a normal file must succeed.
Also records the fixed-input hashes (stop if either differs).
Usage: python -m src.acq_r04.guard_selftest
"""
from __future__ import annotations

import sys

from src.acq_r04 import common as R

from src.acq_r01 import common as C


def main():
    hashes = R.check_fixed_inputs()
    import builtins
    import numpy as np
    import pandas as pd
    import rasterio
    import geopandas as gpd
    import pyogrio
    readers = {"builtins.open": lambda p: builtins.open(p, "rb"), "rasterio.open": rasterio.open, "numpy.load": np.load,
               "geopandas.read_file": gpd.read_file, "pyogrio.read_dataframe": pyogrio.read_dataframe,
               "pandas.read_parquet": pd.read_parquet}
    targets = {f"lockbox:{l}": str(C.OAK / "harmonized" / l / "lr.tif") for l in C.LOCKBOX}
    targets.update({"confirmatory:nu01a": str(C.HARMONIZED_CONFIRMATORY / "nu01a" / "KN182L03__MGDS_30193" / "footprint.geojson"),
                    "confirmatory:root": str(C.HARMONIZED_CONFIRMATORY)})
    rows, ok = [], True
    for tn, path in targets.items():
        for rn, fn in readers.items():
            try:
                fn(path); res = "NOT BLOCKED"
            except PermissionError as e:
                res = "blocked" if ("GUARD" in str(e)) else f"PermissionError not from guard: {e}"
            except Exception as e:
                res = f"NOT BLOCKED ({type(e).__name__})"
            ok &= res == "blocked"
            rows.append({"target": tn, "reader": rn, "path": path, "result": res})
    try:
        with open(R.MANIFEST_V21, "rb") as f:
            f.read(4)
        ctrl = "control read ok"
    except Exception as e:
        ctrl = f"CONTROL FAILED {e}"; ok = False
    out = {"generated": R.utc_now(), "fixed_input_sha256": hashes, "all_blocked": bool(ok), "control": ctrl,
           "n_checks": len(rows), "checks": rows, "code_commit": C.git_commit()}
    R.write_json(R.REPORT_DIR / "guard_selftest.json", out)
    print(f"guard self-test: {sum(r['result'] == 'blocked' for r in rows)}/{len(rows)} blocked; {ctrl}; hashes ok")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
