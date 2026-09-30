"""ACQ-R02 §6.2 — (re)compute the H1 processed-grid cross-check for every harmonized H1 development pair
and write it back into the harmonize record (reports_post_grl_review/ACQ-R02/harmonize/<pair>.json).
The processed NCEI grid is compared with the raw-swath LR over the harmonized LR grid; it is never used as LR.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from src.acq_r01 import common as C
from src.acq_r01.harmonize_new import processed_lr_crosscheck

log = logging.getLogger("acq_r02.xcheck")
R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    tmp = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r02_xcheck"; tmp.mkdir(parents=True, exist_ok=True)
    n = 0
    for jp in sorted((R02 / "harmonize").glob("*.json")):
        r = json.loads(jp.read_text())
        if r.get("set") != "H1" or r.get("status") != "harmonized_development":
            continue
        lr_out = Path(r["out_dir"]) / "lr.tif"
        if not lr_out.exists():
            continue
        try:
            r["processed_lr_crosscheck"] = processed_lr_crosscheck(r["lr_cruise"], lr_out, tmp)
        except Exception as e:
            r["processed_lr_crosscheck"] = {"status": f"error: {str(e)[:120]}"}
        jp.write_text(json.dumps(r, indent=1, default=str)); n += 1
        log.info("%s: %s", r["pair_id"], json.dumps(r["processed_lr_crosscheck"], default=str)[:300])
    print(f"{n} H1 records updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
