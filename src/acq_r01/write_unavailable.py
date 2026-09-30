"""ACQ-R01 §2.2 step 6 — write `products.json` with every `available` flag false for pairs whose
provider grid has no retrievable per-beam soundings (INTERFACE_CONTRACT_v1 §3: no rasters written).

Usage: python -m src.acq_r01.write_unavailable --unit CalDIG --reason "..."
       python -m src.acq_r01.write_unavailable --pair <pair_id> --reason "..."
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from src.acq_r01 import common as C


def write_one(row, reason: str, kind: str = "none"):
    C.assert_no_lockbox([row.pair_id])
    out_dir = C.pair_dir_oak(row) / "ship_products_v1"
    out_dir.mkdir(exist_ok=True)
    for f in out_dir.glob("*.tif"):
        raise RuntimeError(f"{row.pair_id}: rasters present in {out_dir}; refusing to mark unavailable")
    pj = {"contract_version": 1, "pair_id": row.pair_id,
          "available": {"ship_sd": False, "ship_count": False, "ship_xtrack_frac": False, "ship_beam_angle": False},
          "unavailable_reason": reason,
          "source": {"kind": kind, "files": [], "mb_format": None, "processing_mode": None},
          "software": {"mbsystem": C.MBSYSTEM_VERSION, "container": f"apptainer sandbox {C.SANDBOX}", "code_commit": C.git_commit()},
          "commands": [], "grid": None, "qa_vs_lr_tif": None,
          "created": datetime.now(timezone.utc).isoformat()}
    p = out_dir / "products.json"
    if p.exists():
        p.chmod(0o644)
    p.write_text(json.dumps(pj, indent=1)); p.chmod(0o444)
    return str(p)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", default=None); ap.add_argument("--pair", default=None)
    ap.add_argument("--reason", required=True); ap.add_argument("--kind", default="none")
    a = ap.parse_args(argv)
    m = C.load_manifest()
    if a.unit:
        pids = C.ALL15[a.unit] if a.unit in C.ALL15 else C.EW0207[a.unit]
    else:
        pids = [a.pair]
    rows = m[m.pair_id.isin(pids)]
    written = [write_one(r, a.reason, a.kind) for _, r in rows.iterrows()]
    print(json.dumps(written, indent=1)); return 0


if __name__ == "__main__":
    sys.exit(main())
