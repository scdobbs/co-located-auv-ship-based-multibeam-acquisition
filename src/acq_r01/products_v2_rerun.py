"""ACQ-R02 §6 — re-run the contract-v2 products for one already-harmonized new pair and write the result back
into its harmonize record.  Used when the in-line build inside harmonize_new failed for a resource reason
(2009_Amundsen__MGDS_30047: the 48 GB harmonize job was OOM-killed inside the products process pool).
Nothing in the harmonized directory other than ship_products_v2/ is touched.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from src.acq_r01 import common as C
from src.acq_r01 import build_products_v2 as V2

R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", required=True); ap.add_argument("--cruise", required=True)
    ap.add_argument("--nproc", type=int, default=4); ap.add_argument("--batch-files", type=int, default=1)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    C.assert_no_lockbox([a.pair]); C.assert_no_lockbox_cruise([a.cruise])
    jp = R02 / "harmonize" / f"{a.pair}.json"
    rec = json.loads(jp.read_text())
    if str(rec.get("designation", "")).startswith("confirmatory"):
        raise SystemExit(f"{a.pair} is confirmatory: products are built only at Phase 4")
    spec = [{"pair_id": a.pair, "pair_dir": rec["out_dir"], "cruise_dir": str(C.RAW_SWATH_OAK / a.cruise),
             "src_kind": "provider_swath" if a.cruise.startswith("PANGAEA_") else "ncei_swath"}]
    res = V2.build_cruise(a.cruise, None, a.nproc, None, a.batch_files, spec=spec)
    rec["products_v2"] = res[0] if res else {"error": "build_cruise returned no result"}
    rec["products_v2_rerun"] = {"reason": "in-line build failed in harmonize job (OOM in process pool)", "nproc": a.nproc, "code_commit": C.git_commit()}
    jp.write_text(json.dumps(rec, indent=1, default=str))
    print(json.dumps(rec["products_v2"], indent=1, default=str))
    return 0 if res else 1


if __name__ == "__main__":
    sys.exit(main())
