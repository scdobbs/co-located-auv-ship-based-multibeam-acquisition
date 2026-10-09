"""ACQ-R05 incident 2026-10-09 — whole-cruise over-fetch of NA080 and TN299 (NCEI generated/ listing failure).

Lists, per cruise, the files fetched by the context run (fetch manifest entries tagged acq_r05) that NO in-scope pair
selects for its context region (sources.select_files on the coverage pass).  Nothing is deleted: the list is for the
HOLD (Steve decides).  Usage: python -m src.acq_r05.overfetch  -> overfetch_deletable_v1.csv / .json
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from src.acq_r05 import common as R
from src.acq_r05 import sources as S
from src.acq_r01 import common as C


def main(argv=None):
    rows, summary = [], {}
    for cruise in ("NA080", "TN299"):
        man = json.loads((C.RAW_SWATH_OAK / cruise / "fetch_manifest.json").read_text())
        added = {f["filename"]: f for f in man["files"] if "acq_r05" in f}
        cov = S.load_coverage(cruise)
        need = S.needed_region_4326(cruise)
        selected = set()
        for pid, v in need["pairs"].items():
            selected |= set(S.select_files(cov, v["region"]))
        for name, f in sorted(added.items()):
            used = name in selected
            rows.append({"cruise": cruise, "filename": name, "size": f["size"], "sha256": f["sha256"], "selected_by_a_pair": used,
                         "n_soundings": cov["files"].get(name, {}).get("n")})
        d = pd.DataFrame([r for r in rows if r["cruise"] == cruise])
        summary[cruise] = {"n_fetched_by_acq_r05": len(added), "gb_fetched": round(d["size"].sum() / 1e9, 2), "n_selected_by_a_pair": int(d.selected_by_a_pair.sum()),
                           "n_not_selected": int((~d.selected_by_a_pair).sum()), "gb_not_selected": round(d[~d.selected_by_a_pair]["size"].sum() / 1e9, 2),
                           "manifest_backup": str(C.RAW_SWATH_OAK / cruise / "fetch_manifest.json.pre_acq_r05_2026-10-09")}
    df = pd.DataFrame(rows); df.to_csv(R.REPORT_DIR / "overfetch_deletable_v1.csv", index=False)
    out = {"generated": R.utc_now(), "note": "files listed as deletable are NOT deleted; the fetch manifests and SHA256SUMS on OAK include them (originals kept as *.pre_acq_r05_2026-10-09)",
           "per_cruise": summary, "total_gb_not_selected": round(sum(v["gb_not_selected"] for v in summary.values()), 2), "code_commit": R.git_commit()}
    (R.REPORT_DIR / "overfetch_deletable_v1.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
