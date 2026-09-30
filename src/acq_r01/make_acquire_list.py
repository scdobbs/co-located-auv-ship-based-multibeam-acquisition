"""ACQ-R02 §6 helper — build the per-cruise acquisition list from the verification + fetch-plan outputs.

Line format for sbatch/acq_r02_acquire.sbatch:  <cruise>|<hr1,hr2,...>|<sonar>
Only cruises whose plan status is `planned` (or already_on_oak) and whose served HR are not dropped.
"""
from __future__ import annotations

import json
import sys

import geopandas as gpd
import pandas as pd

from src.acq_r01 import common as C

R02 = C.REPO / "reports_post_grl_review" / "ACQ-R02"


def main():
    v = pd.read_csv(R02 / "verification" / "candidates_verified.csv")
    v = v[v.status == "verified"]
    ua = json.loads((R02 / "verification" / "units_after.json").read_text())
    desig = {}
    for u in ua["units"]:
        desig.update(u["designations"])
    cp = pd.read_csv(R02 / "fetch_plan" / "cruise_plan.csv")
    ok = set(cp[cp.status.isin(["planned", "already_on_oak"])].cruise.astype(str))
    ncei = gpd.read_file(C.SCRATCH_DATA / "discovery_cache" / "acq_r01_2026-09-29" / "ncei_all_footprints.geojson")
    sonar = ncei.drop_duplicates("SURVEY_ID").set_index("SURVEY_ID").INSTRUMENT.to_dict()
    psd = R02 / "discovery_pangaea" / "ship_datasets.csv"
    if psd.exists():      # PANGAEA ship datasets: sonar parsed from the dataset title (EM122, EM710, SEABEAM1050, ...)
        for i, r in pd.read_csv(psd, dtype={"id": str}).set_index("id").iterrows():
            sonar[f"PANGAEA:{i}"] = str(r.sonar) if isinstance(r.sonar, str) else ""
    lines = []
    for cr, g in v.groupby("lr_best_real"):
        cr = str(cr)
        hrs = [h for h in g.hr_id if not str(desig.get(h, "")).startswith("dropped")]
        if cr not in ok or not hrs:
            continue
        cdir = cr.replace("PANGAEA:", "PANGAEA_")
        lines.append(f"{cdir}|{','.join(hrs)}|{sonar.get(cr, '')}")
    p = C.REPO / "sbatch" / "acq_r02_acquire_list.txt"
    p.write_text("\n".join(lines) + "\n")
    print("\n".join(lines)); print(f"{len(lines)} cruises -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
