"""ACQ-R04 challenge-section audit (steering ruling 2026-10-03): file-name collisions in the development LR cruises.

READ-ONLY, metadata only.  For every development / no-k pair of manifest v2.1 (lockbox and confirmatory rows excluded
by designation before any path is formed; nothing under harmonized_confirmatory/ or a lockbox path is touched):
  1. its LR cruise's planned swath files, from
       reports/discovery/stage_b_file_plan_2026-06-22.csv          (June stage B -> the stage-C union grids), and
       reports_post_grl_review/ACQ-R02/fetch_plan/file_plan.csv     (ACQ-R02 cruises -> grid_lr.py grids);
     a collision = the same file name planned from more than one NCEI URL (sonar subdirectory) for one cruise;
  2. which copy was actually used, per stage:
       stage C (June, $DATA_ROOT/raw_lr/<cruise>/, flat, since purged): reports/discovery/stage_b_fetch_log.csv
           (per-URL status / received bytes; the flat file holds the last completed write);
       ACQ-R01/R02 re-fetch to OAK raw_lr_swath/<cruise>/ (flat; source of the contract products v1/v2/v2.1 and of the
           ACQ-R02 grid_lr.py grids): the per-URL fetch logs (ACQ-R01 fetch_swath_log*.csv: head Content-Length,
           received, sha256), the OAK fetch_manifest.json entries, and os.stat size of the one file on OAK, matched
           against each URL's Content-Length.
  Outcome per collision: which URL's bytes are on disk / were gridded, and whether the other copy's soundings were
  silently missing from the development lr.tif and/or the product set.
Writes name_collision_audit.csv and name_collision_audit.json (report dir).  Builds nothing.
Usage: python -m src.acq_r04.audit_name_collisions
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

from src.acq_r04 import common as R
from src.acq_r01 import common as C

REP = C.REPO / "reports"
R01 = R.R01; R02 = R.R02


def main():
    m = pd.read_parquet(R.MANIFEST_V21)
    dev = m[m.designation.astype(str).str.startswith("development") & ~m.pair_id.isin(C.LOCKBOX)]
    lr_cruises = sorted(set(dev.lr_cruise.astype(str)))
    C.assert_no_lockbox_cruise(lr_cruises)
    plans = []
    sb = pd.read_csv(REP / "discovery" / "stage_b_file_plan_2026-06-22.csv"); sb["plan"] = "stage_b_2026-06-22"
    a2 = pd.read_csv(R02 / "fetch_plan" / "file_plan.csv"); a2["plan"] = "acq_r02_file_plan"
    for p in (sb, a2):
        p = p[(p.kind == "swath") & p.cruise.isin(lr_cruises)]
        plans.append(p[["cruise", "filename", "url", "advertised", "plan"]])
    P = pd.concat(plans, ignore_index=True).drop_duplicates(["cruise", "filename", "url", "plan"])
    dup = P[P.duplicated(["cruise", "filename", "plan"], keep=False)].copy()
    # per-URL fetch evidence
    sbl = pd.read_csv(REP / "discovery" / "stage_b_fetch_log.csv")
    r01 = pd.concat([pd.read_csv(f).assign(log=f.name) for f in sorted(R01.glob("fetch_swath_log*.csv")) if "pangaea" not in f.name], ignore_index=True)
    rows = []
    for (cr, fn, plan), g in dup.groupby(["cruise", "filename", "plan"]):
        urls = g.url.tolist()
        sb_rows = sbl[(sbl.get("cruise", pd.Series(dtype=str)) == cr) & sbl.url.isin(urls)] if "url" in sbl else pd.DataFrame()
        r1 = r01[(r01.cruise == cr) & r01.url.isin(urls)]
        oak = C.RAW_SWATH_OAK / cr / fn
        size = os.stat(oak).st_size if oak.exists() else None
        man = C.RAW_SWATH_OAK / cr / "fetch_manifest.json"
        mfiles = [f for f in (json.loads(man.read_text()).get("files", []) if man.exists() else [])
                  if (f.get("filename") or f.get("name")) == fn]
        cl = {u: (r1[r1.url == u].head_content_length.dropna().astype(int).tolist() or [None])[0] for u in urls}
        on_disk = [u for u, c in cl.items() if c is not None and size is not None and c == size]
        rows.append({"lr_cruise": cr, "filename": fn, "plan": plan, "n_urls": len(urls), "urls": " | ".join(urls),
                     "advertised": " | ".join(str(int(a)) for a in g.advertised),
                     "stage_b_log": "; ".join(f"{r.url.split('/')[-2]}:{r.status}:{r.get('received', '')}" for _, r in sb_rows.iterrows()) if len(sb_rows) else "",
                     "acq_r01_r02_log": "; ".join(f"{r.url.split('/')[-2]}:{r.status}:{r.received}:{str(r.sha256)[:12]}" for _, r in r1.iterrows()),
                     "oak_file_size": size, "content_length_per_url": json.dumps({u.split('/')[-2]: c for u, c in cl.items()}),
                     "oak_copy_is": ",".join(u.split("/")[-2] for u in on_disk) or ("absent" if size is None else "unmatched"),
                     "fetch_manifest_entries": len(mfiles), "fetch_manifest_sha256s": ",".join(sorted({str(f.get('sha256'))[:12] for f in mfiles})),
                     "pairs": ";".join(dev[dev.lr_cruise.astype(str) == cr].pair_id)})
    df = pd.DataFrame(rows)
    df.to_csv(R.REPORT_DIR / "name_collision_audit.csv", index=False)
    out = {"generated": R.utc_now(), "lr_cruises_checked": lr_cruises, "n_dev_pairs": int(len(dev)),
           "plans": {"stage_b": "reports/discovery/stage_b_file_plan_2026-06-22.csv", "acq_r02": "reports_post_grl_review/ACQ-R02/fetch_plan/file_plan.csv"},
           "collisions": int(len(df)), "cruises_with_collisions": sorted(df.lr_cruise.unique().tolist()) if len(df) else [],
           "rows": df.to_dict("records"), "code_commit": C.git_commit()}
    R.write_json(R.REPORT_DIR / "name_collision_audit.json", out)
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    if len(df):
        print(df.drop(columns=["urls"]).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
