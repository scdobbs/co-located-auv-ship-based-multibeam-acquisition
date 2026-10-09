"""ACQ-R05 §0.2 / §5 — guard self-test.

(a) The ACQ-R04 reader guard (builtins.open, rasterio.open, numpy.load, geopandas.read_file, pyogrio.read_dataframe,
    pandas.read_parquet) on lockbox and confirmatory paths — the ACQ-R04 self-test, re-run here;
(b) the context builder refuses the lockbox pair ids, the confirmatory pair ids, any harmonized_confirmatory/ path and
    any pair outside units-v1 + EW0207, before touching anything.
Also records the fixed-input hashes (manifest v2.1, dropped list, tiles_v1_1.parquet).
Usage: python -m src.acq_r05.guard_test
"""
from __future__ import annotations

import json
import sys

from src.acq_r05 import common as R
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
               "geopandas.read_file": gpd.read_file, "pyogrio.read_dataframe": pyogrio.read_dataframe, "pandas.read_parquet": pd.read_parquet}
    targets = {f"lockbox:{l}": str(C.OAK / "harmonized" / l / "lr.tif") for l in C.LOCKBOX}
    targets.update({"confirmatory:nu01a": str(C.HARMONIZED_CONFIRMATORY / "nu01a" / "KN182L03__MGDS_30193" / "footprint.geojson"),
                    "confirmatory:root": str(C.HARMONIZED_CONFIRMATORY)})
    rows, ok = [], True
    for tn, path in targets.items():
        for rn, fn in readers.items():
            try:
                fn(path); res = "NOT BLOCKED"
            except PermissionError as e:
                res = "blocked" if "GUARD" in str(e) else f"PermissionError not from guard: {e}"
            except Exception as e:
                res = f"NOT BLOCKED ({type(e).__name__})"
            ok &= res == "blocked"; rows.append({"target": tn, "reader": rn, "result": res})
    # (b) builder refusals (no filesystem access happens before the refusal)
    from src.acq_r05 import build as B
    refusals = []
    cases = [("lockbox pair", p) for p in C.LOCKBOX] + [("confirmatory pair", p) for p in R.CONFIRMATORY_PAIRS] + \
            [("confirmatory path", str(C.HARMONIZED_CONFIRMATORY / "nu03" / "SUM1004__MGDS_33090")), ("no-k pair (out of scope)", "KIWI10RR__MGDS_24499"),
             ("dropped pair (out of scope)", "AT37-05__MGDS_24043")]
    for kind, pid in cases:
        try:
            B.build(pid); res = "NOT REFUSED"
        except PermissionError as e:
            res = "refused" if "GUARD" in str(e) else f"PermissionError not from guard: {e}"
        except SystemExit as e:
            res = "refused" if "refusing" in str(e) else f"SystemExit: {e}"
        except Exception as e:
            res = f"NOT REFUSED ({type(e).__name__}: {str(e)[:80]})"
        ok &= res == "refused"; refusals.append({"case": kind, "pair_or_path": pid, "result": res})
    for fn_name, fn in (("common.context_dir", R.context_dir), ("common.pair_dir", R.pair_dir), ("common.refuse_sealed_path", R.refuse_sealed_path)):
        for pid in list(C.LOCKBOX) + list(R.CONFIRMATORY_PAIRS):
            try:
                fn(pid); res = "NOT REFUSED"
            except PermissionError as e:
                res = "refused" if "GUARD" in str(e) else str(e)
            except Exception as e:
                res = f"NOT REFUSED ({type(e).__name__})"
            ok &= res == "refused"; refusals.append({"case": fn_name, "pair_or_path": pid, "result": res})
    try:
        with open(R.MANIFEST_V21, "rb") as f:
            f.read(4)
        ctrl = "control read ok"
    except Exception as e:
        ctrl = f"CONTROL FAILED {e}"; ok = False
    out = {"generated": R.utc_now(), "fixed_input_sha256": hashes, "all_passed": bool(ok), "control": ctrl,
           "reader_checks": {"n": len(rows), "n_blocked": sum(r["result"] == "blocked" for r in rows), "checks": rows},
           "builder_refusals": {"n": len(refusals), "n_refused": sum(r["result"] == "refused" for r in refusals), "checks": refusals},
           "builder_sha256": {"src/acq_r05/build.py": R.sha256_file(R.REPO / "src/acq_r05/build.py"), "src/acq_r05/lattice.py": R.sha256_file(R.REPO / "src/acq_r05/lattice.py"),
                              "src/acq_r05/sources.py": R.sha256_file(R.REPO / "src/acq_r05/sources.py"), "src/acq_r05/common.py": R.sha256_file(R.REPO / "src/acq_r05/common.py")},
           "code_commit": R.git_commit()}
    R.write_json(R.REPORT_DIR / "guard_selftest.json", out, mode=0o644)
    print(f"guard self-test: readers {out['reader_checks']['n_blocked']}/{out['reader_checks']['n']} blocked; builder {out['builder_refusals']['n_refused']}/{out['builder_refusals']['n']} refused; {ctrl}; hashes ok; all_passed={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
