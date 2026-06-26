"""Stage F.5 finalizer — merge the F5 per-pair results into combined_corpus.csv
and print the summary tables the report needs.

Append-only: adds f5_* columns to the 32 new_c5c rows; the 21 validated rows are
left untouched (no F5 record -> blank). Run as a short job, never on the login node.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "reports/discovery/stage_f5_results.json"
CORPUS = REPO / "reports/combined_corpus.csv"

F5_COLS = {
    "f5_bucket": "bucket",
    "f5_joint_area_km2": "joint_valid_area_km2",
    "f5_joint_fraction": "joint_valid_fraction",
    "f5_hr_interp_status": "hr_interp_status",
    "f5_n_valid_tiles": "n_valid_tiles",
    "f5_fill_corruption_cells": "fill_corruption_cells",
}

VERT_SUSPECT_M = 50.0   # |Stage F coreg dz| above this => HR vertical datum suspect


def _recoreg(r, key):
    rc = r.get("recoreg")
    return rc.get(key) if isinstance(rc, dict) else None


def main():
    res = json.loads(RESULTS.read_text())
    sf = {r["pair_id"]: r for r in json.loads((REPO / 'reports/discovery/stage_f_results.json').read_text())}
    rows = {}
    for r in res:
        dz = sf.get(r["pair_id"], {}).get("coreg_dz")
        rows[r["pair_id"]] = {
            **{col: r.get(src) for col, src in F5_COLS.items()},
            "f5_recoreg_offset_m": _recoreg(r, "offset_m"),
            "f5_recoreg_psr": _recoreg(r, "psr"),
            "f5_recoreg_dz_m": _recoreg(r, "dz"),
            "f5_stage_f_dz_m": dz,
            "f5_hr_vertical_suspect": bool(dz is not None and abs(dz) > VERT_SUSPECT_M),
        }
    extra = ["f5_recoreg_offset_m", "f5_recoreg_psr", "f5_recoreg_dz_m",
             "f5_stage_f_dz_m", "f5_hr_vertical_suspect"]
    df = pd.read_csv(CORPUS)
    for col in list(F5_COLS) + extra:
        df[col] = df["pair_id"].map(lambda p: rows.get(p, {}).get(col))
    df.to_csv(CORPUS, index=False)
    print(f"updated {CORPUS} ({len(df)} rows; {len(rows)} F5 records merged)")

    print("\n=== Stage F fill-corruption / HR vertical-shift (DISCOVERED bug) ===")
    aff = [r for r in res if (r.get("fill_corruption_cells") or 0) > 0]
    print(f"pairs with leaked fill (stored fill != -9999 tag): {len(aff)} / {len(res)}")
    susp = [(p, rows[p]) for p in rows if rows[p]["f5_hr_vertical_suspect"]]
    print(f"pairs with |Stage F dz| > {VERT_SUSPECT_M} m (HR vertical datum suspect): {len(susp)}")
    for p, rr in sorted(susp, key=lambda x: -abs(x[1]["f5_stage_f_dz_m"])):
        fc = next((r.get("fill_corruption_cells") for r in res if r["pair_id"] == p), None)
        print(f"  {p:32} stageF_dz={rr['f5_stage_f_dz_m']:>10.2f}  fill_cells={fc}  "
              f"recoreg_dz={rr['f5_recoreg_dz_m']}  bucket={rr['f5_bucket']}")

    # ---- summary tables for the report ----
    from collections import Counter
    buckets = Counter(r.get("bucket") for r in res)
    print("\nBUCKETS:", dict(buckets), "  total:", sum(buckets.values()))

    print("\n=== EXCLUDE CANDIDATES (inflated / weak) ===")
    print(f"{'pair_id':32} {'bucket':28} {'joint_km2':>10} {'frac':>7} {'tiles':>6} {'stageF_km2':>10}")
    sf = {r["pair_id"]: r for r in json.loads((REPO / 'reports/discovery/stage_f_results.json').read_text())}
    for r in sorted(res, key=lambda x: -(x.get("joint_valid_area_km2") or 0)):
        if "exclude" in (r.get("bucket") or ""):
            print(f"{r['pair_id']:32} {r['bucket']:28} {r.get('joint_valid_area_km2'):>10} "
                  f"{r.get('joint_valid_fraction'):>7} {r.get('n_valid_tiles', 0):>6} "
                  f"{sf.get(r['pair_id'], {}).get('overlap_km2'):>10}")

    print("\n=== genuine_coreg_fail (PSR<=0 / lock fail on real cells) ===")
    for r in res:
        if r.get("bucket") == "genuine_coreg_fail":
            print(f"{r['pair_id']:32} offset={_recoreg(r,'offset_m')} psr={_recoreg(r,'psr')} "
                  f"eig={_recoreg(r,'eig_ratio')} dz={_recoreg(r,'dz')} frac={r.get('joint_valid_fraction')}")

    print("\n=== clean / rescued (advanceable) ===")
    for r in res:
        if r.get("bucket") in ("clean", "rescued"):
            print(f"{r['pair_id']:32} {r['bucket']:9} offset={_recoreg(r,'offset_m')} "
                  f"psr={_recoreg(r,'psr')} dz_F5={_recoreg(r,'dz')} dz_StageF={sf.get(r['pair_id'],{}).get('coreg_dz')} "
                  f"tiles={r.get('n_valid_tiles')}")

    print("\n=== F5-5 Gap-2 re-check (eval_only) ===")
    for r in res:
        if r.get("gap2_recheck"):
            print(f"{r['pair_id']:32} {json.dumps(r['gap2_recheck'])}")


if __name__ == "__main__":
    main()
