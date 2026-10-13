"""ACQ-R08 Pool C — every pair rejected in the June (v1.4/v1.5 discovery → stage A..F → re-audits) and September
(ACQ-R01..R03) acquisition runs, with its recorded reason, and whether that reason still applies under the current rules.

Sources (records only): reports_post_grl_review/ACQ-R01/corpus_reconciliation.csv (June fates of the 85 acquirable HR),
reports/discovery/stage_a_selection.gpkg (June stage-A tier ``excluded`` = the retired ratio gate),
ACQ-R01/discovery_rerun/candidates_gated.csv (September gate), ACQ-R02/verification/candidates_verified.csv,
ACQ-R02/discovery_pangaea/candidates.csv, manifest/pairs_v2_dropped.csv, manifest/pairs_v2_1_dropped.csv.

Re-screen under §3 only those whose reason no longer applies (the retired ratio gate): their ids are written to
``pool_c/rescreen_ids.json`` and Pool A (which re-harvests the same catalogs) screens and tags them.
"""
from __future__ import annotations

import json
import logging
import re
import sys

import geopandas as gpd
import pandas as pd

from src.acq_r08 import common as K
from src.acq_r01 import common as C

log = logging.getLogger("acq_r08.pool_c")
OUT = K.OUT / "pool_c"

# (regex on the recorded reason, still_applies, rationale)
RULES = [
    (r"ratio\s*[\d.]+\s*[<>]\s*(40|5)|super-resolution not meaningful|ratio gate|training.*25|eval_only.*40", "no",
     "the 5–25× / 25–40× ratio gate was retired; the current range is cells_across 3.88–51.2 (ratio ≈ 5–66) with a fine band at ratio ≥ 4.5 → re-screen under §3"),
    (r"REASON UNRECORDED", "superseded", "became a ruling-H1 development candidate in ACQ-R02; its September outcome (manifest v2.1 row or dropped list) is the current record"),
    (r"inflated|false pair|no real (data )?overlap|empty_overlap|no ship coverage|0 joint cells|false co-location|no LR footprint overlaps|no_lr_soundings", "yes",
     "false pair: measured on the data (no HR/LR overlap); not a rule that changed"),
    (r"declined by Steve|ruling", "yes", "a ruling, not a rule"),
    (r"0 valid tiles|zero_valid_tiles", "yes", "measured on the data after the real-data masks"),
    (r"co-registration|coreg|offset.*NCC|no interior NCC|re-coreg|registration failure", "yes",
     "QA finding on the harmonized pair; a QGIS arbitration would be Steve's call, not a rule change"),
    (r"render|RGB|no elevation band|no readable float|renders/PDF|not a float grid", "yes", "the record has no elevation grid (float siblings were acquired where they exist)"),
    (r"PDF, not bathymetry|HTML error page", "yes", "no grid file behind the record"),
    (r"legacy SeaBeam-classic|needs_format_review|\.gps swath", "yes",
     "technical blocker, not a rule: the swath format is unreadable by the gridding chain (manual recovery would be a new task)"),
    (r"degenerate|no recoverable SR signal|no_curve|not recoverable at any k|no spectrum", "yes", "measured on the data (k sweep)"),
    (r"coarse_or_composite|declared .* measures", "yes", "resolution mismatch measured on the file; a re-check would need the file"),
    (r"ship_internal_inconsistency|ship-internal", "yes", "ruling R1 (ACQ-R03) on a measured line offset"),
    (r"401|restricted|Unauthorized", "yes", "access restriction on the repository side (a HEAD on the data URL is a data request, not repeated here)"),
    (r"not_auv_bathymetry|hr_class=|is_non_bathy", "yes", "not near-bottom bathymetry by the record (platform / data type)"),
    (r"hr_raw_only|raw-only|soundings only", "yes", "the HR record is raw soundings, not a grid"),
    (r"no_independent_ship_lr|without independent ship", "re-check", "LR availability is re-checked in Pool A against the refreshed NCEI / PANGAEA catalogs"),
    (r"TN234 EM300|0 good beams|no usable bathymetry", "yes", "the LR raw files hold no usable soundings (measured)"),
    (r"not fetched|never fetched|never appears", "yes", "never processed; no new rule makes it processable without a new run"),
]


def judge(reason: str) -> tuple[str, str]:
    for rx, still, why in RULES:
        if re.search(rx, reason or "", re.I):
            return still, why
    return "yes", "no rule change bears on this reason"


def build() -> pd.DataFrame:
    rows = []
    m = K.load_manifest_v21(); in_manifest = {K.mgds_id_of_pair(p) for p in m.pair_id} | {f"MANIFEST:{p}" for p in m.pair_id} | {"PANGAEA:905580", "PANGAEA:915765", "PANGAEA:899415"}
    jun = K.june_hr_catalog()
    # June: reconciliation fates
    rec = pd.read_csv(K.R01 / "corpus_reconciliation.csv")
    for _, r in rec[~rec.fate.astype(str).str.startswith("in corpus")].iterrows():
        rows.append({"run": "June 2026", "hr_id": r.hr_id, "lr": r.gate_lr, "title": str(r.hr_title)[:90], "reason": r.fate, "reason_source": r.reason_source,
                     "now_in_manifest_v2_1": r.hr_id in in_manifest})
    # June: stage-A tier 'excluded' (ratio gate) — not in the reconciliation (it covered the 85 acquirable HR)
    sel = gpd.read_file(C.REPO / "reports/discovery/stage_a_selection.gpkg")
    for _, r in sel[sel.tier == "excluded"].iterrows():
        rows.append({"run": "June 2026 (stage A gate)", "hr_id": r.hr_id, "lr": r.lr_cruise_id, "title": str(r.hr_title)[:90],
                     "reason": f"stage-A tier excluded: {r.tier_reason}", "reason_source": "reports/discovery/stage_a_selection.gpkg (2026-06-05 v3)",
                     "now_in_manifest_v2_1": r.hr_id in in_manifest})
    # September: ACQ-R01 gate
    cg = pd.read_csv(K.R01 / "discovery_rerun" / "candidates_gated.csv")
    for _, r in cg[cg.status.isin(["gate_excluded", "render_no_elevation", "not_auv_bathymetry"])].iterrows():
        rows.append({"run": "Sept 2026 (ACQ-R01 gate)", "hr_id": r.hr_id, "lr": r.best_lr, "title": str(r.hr_title)[:90], "reason": f"{r.status}: {r.reason}",
                     "reason_source": "ACQ-R01/discovery_rerun/candidates_gated.csv", "now_in_manifest_v2_1": r.hr_id in in_manifest})
    # September: ACQ-R02 verification
    v = pd.read_csv(K.R02 / "verification" / "candidates_verified.csv")
    for _, r in v[v.status != "verified"].iterrows():
        rows.append({"run": "Sept 2026 (ACQ-R02 verification)", "hr_id": r.hr_id, "lr": r.lr_best, "title": str(r.title)[:90], "reason": f"{r.status}: {r.reason}",
                     "reason_source": "ACQ-R02/verification/candidates_verified.csv", "now_in_manifest_v2_1": r.hr_id in in_manifest})
    # September: PANGAEA discovery non-candidates
    pc = pd.read_csv(K.R02 / "discovery_pangaea" / "candidates.csv")
    for _, r in pc[pc.status.isin(["hr_raw_only", "no_independent_ship_lr"])].iterrows():
        rows.append({"run": "Sept 2026 (ACQ-R02 PANGAEA discovery)", "hr_id": f"PANGAEA:{r.id}", "lr": r.best_lr, "title": str(r.title)[:90], "reason": r.status,
                     "reason_source": "ACQ-R02/discovery_pangaea/candidates.csv", "now_in_manifest_v2_1": False})
    # September: manifest v2 / v2.1 dropped lists
    seen_drop = set()
    for f, run in (("pairs_v2_1_dropped.csv", "Sept 2026 (manifest v2.1 dropped)"), ("pairs_v2_dropped.csv", "Sept 2026 (manifest v2 dropped)")):
        for _, r in pd.read_csv(C.REPO / "manifest" / f).iterrows():
            if r.pair_id in seen_drop:
                continue
            seen_drop.add(r.pair_id)
            hid = K.mgds_id_of_pair(r.pair_id) or ("PANGAEA:889317" if "889317" in r.pair_id else r.pair_id)
            reinstated = r.pair_id in set(m.pair_id)
            rows.append({"run": run, "hr_id": hid, "lr": r.lr_cruise, "title": r.pair_id, "reason": r.reason + (" (reinstated as confirmatory by ACQ-R03 ruling R6)" if reinstated else ""),
                         "reason_source": f"manifest/{f}" + (f"; {r.ruling_source}" if isinstance(r.get("ruling_source"), str) and r.get("ruling_source") else ""),
                         "now_in_manifest_v2_1": reinstated})
    df = pd.DataFrame(rows)
    j = [judge(x) for x in df.reason]
    df["still_applies"] = [x[0] for x in j]; df["why"] = [x[1] for x in j]
    df.loc[df.now_in_manifest_v2_1, "still_applies"] = "n/a (now in manifest v2.1)"
    df["rescreen"] = df.still_applies.eq("no")
    # location (June/September catalog centroid) for the record
    cen = {}
    for hid in df.hr_id.unique():
        if hid in jun.index:
            c = jun.loc[hid].geometry.centroid; cen[hid] = (round(c.x, 3), round(c.y, 3))
    df["lon"] = df.hr_id.map(lambda h: cen.get(h, (None, None))[0]); df["lat"] = df.hr_id.map(lambda h: cen.get(h, (None, None))[1])
    return df


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    df = build()
    df.to_csv(OUT / "pool_c_table.csv", index=False)
    resc = {r.hr_id: f"{r.run}: {r.reason[:100]}" for _, r in df[df.rescreen].iterrows()}
    K.write_json(OUT / "rescreen_ids.json", resc)
    summary = {"rows": int(len(df)), "distinct_hr": int(df.hr_id.nunique()), "by_run": df.run.value_counts().to_dict(),
               "still_applies": df.still_applies.value_counts().to_dict(), "rescreen_ids": sorted(resc), "generated": K.now_iso()}
    K.write_json(OUT / "summary.json", summary)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
