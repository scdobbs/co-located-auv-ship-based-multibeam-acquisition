"""ACQ-R04 §3.1 — pilot: choose 10 cruises, then summarise their run records and extrapolate to the 400.

choose:  the first 10 cruises in selection_v1.csv order that together span >= 4 instrument families: walk the rows in
         order and accept a row unless accepting it would leave too few remaining slots to reach 4 families (a row of an
         already-seen family is skipped only in that case).  -> pilot_cruises.txt
summary: per pilot cruise: files, bytes, fetch time, decompress/coverage/grid/product time, blocks (total / kept / by
         status), output bytes, failures.  Extrapolation to all selected cruises (rates per advertised raw byte, pooled
         over the pilot; per family where the pilot has the family, else pooled):
           raw download = selection_v1 advertised total (known, not extrapolated);
           fetch wall   = total bytes / pilot sustained fetch rate (one fetch process, 6 workers);
           processing   = sum over cruises of (pilot seconds per raw byte) x bytes; wall = processing / concurrency;
           full-run wall = max(fetch wall, processing wall) + one pilot-mean cruise (pipeline fill/drain);
           OAK output   = (pilot output bytes per raw byte) x total bytes.
         HOLD if raw > 3 TB, wall > 96 h at the stated concurrency, or OAK output > 600 GB.
Usage: python -m src.acq_r04.pilot choose | summary --concurrency N
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pandas as pd

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r04.blocks import cdir_name


def choose(n=10, k=4):
    sel = pd.read_csv(R.REPORT_DIR / "selection_v1.csv").sort_values("order")
    out, fams = [], set()
    for r in sel.itertuples():
        if len(out) == n:
            break
        new = r.family not in fams
        slots_after = n - len(out) - 1
        if new or len(fams) + slots_after >= k:
            out.append(r.cruise); fams.add(r.family)
    (R.REPORT_DIR / "pilot_cruises.txt").write_text("\n".join(out) + "\n")
    print(out, sorted(fams))
    return out


def summary(concurrency: int):
    cruises = (R.REPORT_DIR / "pilot_cruises.txt").read_text().split()
    sel = pd.read_csv(R.REPORT_DIR / "selection_v1.csv")
    rows = []
    for c in cruises:
        lg = R.WORK_LOGS / cdir_name(c)
        f = json.loads((lg / "fetch.json").read_text()) if (lg / "fetch.json").exists() else {}
        rj = lg / "cruise_record.json"
        r = json.loads(rj.read_text()) if rj.exists() else {}
        fail = json.loads((lg / "cruise_failure.json").read_text()) if (lg / "cruise_failure.json").exists() else None
        s = sel[sel.cruise == c].iloc[0]
        rows.append({"cruise": c, "family": s.family, "basin": s.basin, "files": f.get("n_files"), "files_failed": f.get("n_failed"),
                     "raw_bytes": f.get("bytes"), "advertised_bytes": int(s.advertised_bytes), "fetch_s": f.get("fetch_wall_s"),
                     "decompress_s": r.get("decompress_s"), "coverage_s": r.get("coverage_s"), "grid_s": r.get("grid_s"),
                     "products_s": r.get("products_s"), "process_wall_s": r.get("wall_s"), "soundings": r.get("soundings"),
                     "blocks_total": r.get("blocks_total"), "blocks_kept": r.get("blocks_kept"),
                     "block_status": json.dumps(r.get("block_status", {})), "output_bytes": r.get("output_bytes"),
                     "failures": len(r.get("failures", [])) + (1 if fail else 0) + (f.get("n_failed") or 0),
                     "cruise_error": fail["error"][:200] if fail else None})
    df = pd.DataFrame(rows)
    df.to_csv(R.REPORT_DIR / "pilot_v1.csv", index=False)
    ok = df[df.process_wall_s.notna()]
    tot_bytes = int(sel.advertised_bytes.sum())
    fetch_rate = float(ok.raw_bytes.sum() / ok.fetch_s.sum()) if len(ok) else None
    proc_per_byte = float(ok.process_wall_s.sum() / ok.raw_bytes.sum()) if len(ok) else None
    out_per_byte = float(ok.output_bytes.sum() / ok.raw_bytes.sum()) if len(ok) else None
    # per-family processing rate where the pilot has the family
    fam_rate = (ok.groupby("family").process_wall_s.sum() / ok.groupby("family").raw_bytes.sum()).to_dict()
    proc_s = float(sum(fam_rate.get(f, proc_per_byte) * b for f, b in zip(sel.family, sel.advertised_bytes)))
    fetch_wall_h = tot_bytes / fetch_rate / 3600 if fetch_rate else None
    proc_wall_h = proc_s / concurrency / 3600
    fill_h = float(ok.process_wall_s.mean()) / 3600 if len(ok) else 0.0
    wall_h = max(fetch_wall_h or 0, proc_wall_h) + fill_h
    oak_gb = out_per_byte * tot_bytes / 1e9 if out_per_byte is not None else None
    blocks_est = float(ok.blocks_kept.sum() / ok.raw_bytes.sum() * tot_bytes) if len(ok) else None
    ex = {"generated": R.utc_now(), "pilot_cruises": cruises, "families": sorted(df.family.unique()), "n_ok": int(len(ok)),
          "pilot_raw_bytes": int(ok.raw_bytes.sum()), "pilot_fetch_s": float(ok.fetch_s.sum()), "pilot_process_s": float(ok.process_wall_s.sum()),
          "pilot_output_bytes": int(ok.output_bytes.sum()), "pilot_blocks_kept": int(ok.blocks_kept.sum()),
          "fetch_rate_MBps": round(fetch_rate / 1e6, 2) if fetch_rate else None,
          "process_s_per_GB_pooled": round(proc_per_byte * 1e9, 1) if proc_per_byte else None,
          "process_s_per_GB_by_family": {k: round(v * 1e9, 1) for k, v in fam_rate.items()},
          "output_bytes_per_raw_byte": out_per_byte, "concurrency_assumed": concurrency,
          "extrapolation": {"raw_download_TB": round(tot_bytes / 1e12, 3), "fetch_wall_h": round(fetch_wall_h, 1) if fetch_wall_h else None,
                            "processing_cpu_task_h": round(proc_s / 3600, 1), "processing_wall_h": round(proc_wall_h, 1),
                            "full_run_wall_h": round(wall_h, 1), "oak_output_GB": round(oak_gb, 1) if oak_gb is not None else None,
                            "blocks_kept_est": round(blocks_est) if blocks_est is not None else None},
          "limits": {"raw_TB": 3.0, "wall_h": 96.0, "oak_GB": 600.0}}
    e = ex["extrapolation"]
    ex["hold"] = {"raw": e["raw_download_TB"] > 3.0, "wall": e["full_run_wall_h"] > 96.0, "oak": (e["oak_output_GB"] or 0) > 600.0}
    ex["any_hold"] = any(ex["hold"].values())
    R.write_json(R.REPORT_DIR / "pilot_v1.json", ex)
    print(df.to_string()); print(json.dumps(ex, indent=1))
    return ex


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("mode", choices=["choose", "summary"])
    ap.add_argument("--concurrency", type=int, default=16)
    a = ap.parse_args(argv)
    if a.mode == "choose":
        choose()
    else:
        summary(a.concurrency)
    return 0


if __name__ == "__main__":
    sys.exit(main())
