"""ACQ-R09 §2.10 — the per-site report fields for ACQ-R10 (and the rehearsal), from a run record only.

Per site ONLY: status, the eligibility fields (coreg_pass, k_recoverable, cells_across, hr_res_in_range, eligible,
eligibility_reason), spacings (hr_native_res_m, lr_native_res_m, ship grid cell), cells across, k, product status and
usability, file counts (HR files, HR grids kept, ship swath files) and the site record's sha256.  No amplitude, statistic,
image or view: the writer refuses any other field.
Usage: python -m src.phase5.report_p5 --run-record <json> [--out <md>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.phase5 import common_p5 as P

FIELDS = ["pair_id", "status", "coreg_pass", "k_recoverable", "cells_across", "hr_res_in_range", "eligible", "eligibility_reason",
          "hr_native_res_m", "lr_native_res_m", "ship_grid_cell_m", "max_recoverable_k", "products", "ship_products_usable",
          "n_hr_files", "n_hr_grids_kept", "n_ship_swath_files", "site_record_sha256"]


def rows(run: dict) -> list:
    out = []
    for pid, e in run["per_pair"].items():
        g = e.get("hr_grids") or {}
        r = {"pair_id": pid, "status": e["status"], **{k: e[k] for k in ("coreg_pass", "k_recoverable", "cells_across", "hr_res_in_range", "eligible", "eligibility_reason",
                                                                          "hr_native_res_m", "lr_native_res_m", "ship_grid_cell_m", "max_recoverable_k", "products",
                                                                          "ship_products_usable", "site_record_sha256")},
             "n_hr_files": g.get("n_files"), "n_hr_grids_kept": len(g.get("kept") or []), "n_ship_swath_files": e.get("ship_swath_files")}
        assert list(r) == FIELDS or set(r) == set(FIELDS), sorted(set(r) ^ set(FIELDS))
        out.append({k: r[k] for k in FIELDS})
    return out


def markdown(run: dict) -> str:
    rs = rows(run)
    hdr = "| " + " | ".join(FIELDS) + " |\n|" + "---|" * len(FIELDS) + "\n"
    body = "".join("| " + " | ".join("" if r[k] is None else (f"`{r[k][:16]}…`" if k == "site_record_sha256" and r[k] else str(r[k])) for k in FIELDS) + " |\n" for r in rs)
    n_el = sum(r["eligible"] for r in rs)
    return (f"Run record `{run.get('run_tag')}` ({run['mode']}), status {run['status']}, supplement sha256 `{run.get('supplement_sha256')}`.\n"
            f"Sites: {len(rs)}; eligible at step 1: {n_el}; not testable: {len(rs) - n_el}.\n\n" + hdr + body)


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--run-record", required=True); ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    run = json.loads(Path(a.run_record).read_text())
    md = markdown(run)
    if P.forbidden_keys(rows(run)):
        raise SystemExit("forbidden field in the report rows")
    out = Path(a.out) if a.out else Path(a.run_record).with_suffix(".report.md")
    out.write_text(md); print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
