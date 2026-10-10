"""ACQ-R06 §0.2 — guard self-test, run at the start of every ACQ-R06 script and on its own.

Every patched reader (builtins.open, rasterio.open, numpy.load, geopandas.read_file, pyogrio.read_dataframe,
pandas.read_parquet) is called on: a path containing each lockbox pair id, the harmonized_confirmatory/ tree,
and the raw swath directory of each of the five sealed LR cruises (ACQ-R06 extension: KN182L03, RC2511, SUM1004,
AT42-03, TN159).  Each call must raise PermissionError from the guard before any filesystem access (the paths need
not exist).  Controls: manifest v2.1 and a development cruise's fetch manifest must open; no phase4 allowance may
be installed.  Usage: python -m src.phase4.guard_selftest
"""
from __future__ import annotations

import sys

from src.phase4 import common as P
from src.acq_r01 import common as C


def run(write: bool = True, out_path=None) -> dict:
    import builtins
    import numpy as np
    import pandas as pd
    import rasterio
    import geopandas as gpd
    import pyogrio
    readers = {"builtins.open": lambda p: builtins.open(p, "rb"), "rasterio.open": rasterio.open, "numpy.load": np.load,
               "geopandas.read_file": gpd.read_file, "pyogrio.read_dataframe": pyogrio.read_dataframe,
               "pandas.read_parquet": pd.read_parquet}
    targets = {f"lockbox pair:{l}": str(C.OAK / "harmonized" / l / "lr.tif") for l in C.LOCKBOX}
    targets.update({"confirmatory:nu01a": str(C.HARMONIZED_CONFIRMATORY / "nu01a" / "KN182L03__MGDS_30193" / "footprint.geojson"),
                    "confirmatory:root": str(C.HARMONIZED_CONFIRMATORY)})
    for c in C.SEALED_LR_CRUISES:
        targets[f"sealed swath:{c}"] = str(C.RAW_SWATH_OAK / c / "fetch_manifest.json")
        targets[f"sealed swath dir:{c}"] = str(C.RAW_SWATH_OAK / c)
    rows, ok = [], True
    for tn, path in targets.items():
        for rn, fn in readers.items():
            try:
                fn(path); res = "NOT BLOCKED"
            except PermissionError as e:
                res = "blocked" if "GUARD" in str(e) else f"PermissionError not from guard: {e}"
            except Exception as e:
                res = f"NOT BLOCKED ({type(e).__name__})"
            ok &= res == "blocked"; rows.append({"target": tn, "reader": rn, "path": path, "result": res})
    controls = {}
    for name, p in (("manifest v2.1", P.MANIFEST_V21), ("development cruise fetch manifest (TN399)", C.RAW_SWATH_OAK / "TN399" / "fetch_manifest.json")):
        try:
            with open(p, "rb") as f:
                f.read(4)
            controls[name] = "control read ok"
        except Exception as e:
            controls[name] = f"CONTROL FAILED {e}"; ok = False
    allow = C.phase4_allowance()
    if allow:
        ok = False
    out = {"generated": P.utc_now(), "all_passed": bool(ok), "controls": controls, "phase4_allowance_installed": list(allow),
           "reader_checks": {"n": len(rows), "n_blocked": sum(r["result"] == "blocked" for r in rows), "checks": rows},
           "guard_extension": "ACQ-R06: raw_lr_swath/<cruise> blocked for the sealed LR cruises " + ", ".join(C.SEALED_LR_CRUISES),
           "guard_sha256": P.sha256_file(C.REPO / "src" / "acq_r01" / "common.py"), "code_commit": P.git_commit()}
    if write:
        P.write_json(out_path or (P.REPORT_DIR / "guard_selftest.json"), out, mode=0o644)
    return out


def main(argv=None):
    hashes = P.check_fixed_inputs()
    out = run(write=True)
    out["fixed_input_sha256"] = hashes
    P.write_json(P.REPORT_DIR / "guard_selftest.json", out, mode=0o644)
    print(f"guard self-test: {out['reader_checks']['n_blocked']}/{out['reader_checks']['n']} blocked; controls {out['controls']}; "
          f"allowance {out['phase4_allowance_installed']}; all_passed={out['all_passed']}")
    return 0 if out["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
