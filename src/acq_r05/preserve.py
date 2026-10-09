"""ACQ-R05 §6 — preservation record.

context_v1.parquet: one row per pair in scope with the context paths, the sha256 of ctx_lr.tif, ctx_lr_valid.tif,
products.json and context.json, coverage and agreement statistics and flags; every file of every context directory is
re-verified against the directory's SHA256SUMS on OAK.  Usage: python -m src.acq_r05.preserve
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from src.acq_r05 import common as R
from src.acq_r05.build import verify_sums


def main(argv=None):
    rows, verify = [], {}
    for pid in R.PAIRS_IN_SCOPE:
        d = R.context_dir(pid); cj = d / "context.json"
        if not cj.exists():
            rows.append({"pair_id": pid, "unit": R.UNIT_OF[pid], "status": "not_built"}); continue
        c = json.loads(cj.read_text()); v = verify_sums(d); verify[pid] = v
        ag = c["agreement"]; cov = c["coverage"]; pr = c.get("products", {})
        pj = d / "ship_products_v2_1" / "products.json"
        rows.append({"pair_id": pid, "unit": R.UNIT_OF[pid], "kind": c["kind"], "lr_cruise": c["lr_cruise"], "status": "built" if v["n_bad"] == 0 else "SHA_MISMATCH",
                     "context_dir": str(d), "ctx_lr_path": str(d / "ctx_lr.tif"), "ctx_lr_valid_path": str(d / "ctx_lr_valid.tif"), "context_json_path": str(cj), "products_json_path": str(pj),
                     "sha256_ctx_lr": c["outputs"]["ctx_lr.tif"], "sha256_ctx_lr_valid": c["outputs"]["ctx_lr_valid.tif"],
                     "sha256_products_json": R.sha256_file(pj) if pj.exists() else None, "sha256_context_json": R.sha256_file(cj),
                     "crs": c["lattice"]["crs"], "cell_m": c["lattice"]["dx"], "width": c["lattice"]["width"], "height": c["lattice"]["height"],
                     "lr_offset_col": c["lattice"]["lr_offset_col"], "lr_offset_row": c["lattice"]["lr_offset_row"], "buffer_m": c["buffer_m"],
                     "n_source_files": len(c.get("source_files", [])), "valid_fraction": cov["valid_fraction"], "valid_fraction_outside_lr_window": cov["valid_fraction_outside_lr_window"],
                     "agree_n_cells": ag["n_cells"], "agree_median_diff_m": ag["median_diff"], "agree_rms_m": ag["rms"], "agree_robust_sigma_m": ag["robust_sigma"],
                     "agree_max_abs_diff_m": ag["max_abs_diff"], "agree_identical": ag["identical"], "median_s_lr_m": ag["median_s_lr_m"],
                     "agree_robust_sigma_over_s_lr": ag.get("robust_sigma_over_s_lr"), "agree_frac_gt_0p1_s_lr": ag.get("frac_abs_diff_gt_0p1_s_lr"),
                     "flags": ";".join(ag["flags"]), "ctx_disagrees": "ctx_disagrees" in ag["flags"],
                     "products_available": bool(pr.get("available") and all(pr["available"].values())) if isinstance(pr.get("available"), dict) else False,
                     "products_flags": ";".join(pr.get("flags") or []) if isinstance(pr.get("flags"), list) else None,
                     "n_files_verified": v["n_files"], "n_files_bad": v["n_bad"], "wall_s": c.get("wall_s"), "code_commit": c.get("code_commit")})
    df = pd.DataFrame(rows)
    out = R.REPORT_DIR / "context_v1.parquet"
    df.to_parquet(out, index=False)
    sha = R.sha256_file(out)
    rec = {"generated": R.utc_now(), "context_v1_parquet": str(out), "sha256": sha, "n_rows": len(df), "n_built": int((df.status == "built").sum()),
           "n_not_built": int((df.status == "not_built").sum()), "n_sha_mismatch": int((df.status == "SHA_MISMATCH").sum()),
           "n_files_verified_total": int(sum(v["n_files"] for v in verify.values())), "n_files_bad_total": int(sum(v["n_bad"] for v in verify.values())),
           "per_pair": verify, "code_commit": R.git_commit()}
    (R.REPORT_DIR / "preserve_verify.json").write_text(json.dumps(rec, indent=1, default=str))
    df.to_csv(R.REPORT_DIR / "context_v1.csv", index=False)
    print(json.dumps({k: v for k, v in rec.items() if k != "per_pair"}, indent=1))
    return 0 if rec["n_files_bad_total"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
