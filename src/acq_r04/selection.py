"""ACQ-R04 §2 — seeded, stratified selection of 400 pool cruises (committed before any download).

1. Readable only: pool_v1.csv `readable` (stage-B swath classifier finds swath files and the dominant format is one
   the stage-C / contract builders infer; pool_crawl.py).
2. Strata = instrument family (ACQ-R01 §5 families) x basin (7 basins).  Strata with < 5 readable cruises are merged
   into "<family> | other basins".
3. 400 cruises: every family with >= 15 readable cruises gets a floor of 15; the remaining 400 - 15 k are allocated to
   families in proportion to their readable pool counts (largest remainder), then within a family to its strata in
   proportion to stratum counts (largest remainder); never above a stratum's size.
   Draw: one numpy.random.default_rng(20261003); strata in sorted order; each stratum's cruises (sorted by id) are put
   in a random order by rng.permutation; the first n are selected, the rest are the stratum's "next draws".
4. Size cap 3 TB (advertised bytes of the planned swath files): while the total exceeds the cap, every over-represented
   stratum (share of selected bytes > share of selected cruises), in decreasing order of over-representation, replaces
   its largest selected cruise with its next draw; stop as soon as the total is <= 3 TB.  Every replacement is recorded.
   If no stratum can replace any more and the total still exceeds 3 TB, the selection is written and flagged (HOLD).
5. selection_v1.csv (cruise, stratum, advertised size, file list source; order = draw rank, then stratum: round-robin)
   and selection_v1.json (seed, allocation, replacements, total size).
Usage: python -m src.acq_r04.selection
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
import pandas as pd

from src.acq_r04 import common as R
from src.acq_r01 import common as C


def largest_remainder(total: int, weights: dict, caps: dict) -> dict:
    keys = sorted(weights)
    out = {k: 0 for k in keys}
    remaining = total
    while remaining > 0:
        open_ = [k for k in keys if out[k] < caps[k]]
        if not open_:
            break
        w = sum(weights[k] for k in open_)
        quota = {k: remaining * weights[k] / w for k in open_}
        add = {k: min(caps[k] - out[k], math.floor(quota[k])) for k in open_}
        if sum(add.values()) == 0:
            for k in sorted(open_, key=lambda k: (-(quota[k] - math.floor(quota[k])), k))[:remaining]:
                add[k] = 1 if out[k] < caps[k] else 0
        for k in open_:
            out[k] += add[k]
        remaining = total - sum(out.values())
    return out


def main(argv=None):
    pool = pd.read_csv(R.REPORT_DIR / "pool_v1.csv")
    C.assert_no_lockbox_cruise(pool.survey_id.tolist())
    rd = pool[pool.readable].copy()
    rd["stratum0"] = rd.family + " | " + rd.basin
    n0 = rd.stratum0.value_counts()
    rd["stratum"] = [s if n0[s] >= 5 else f"{f} | other basins" for s, f in zip(rd.stratum0, rd.family)]
    fam_n = rd.family.value_counts().to_dict()
    floors = {f: (R.FAMILY_FLOOR if n >= R.FAMILY_FLOOR else 0) for f, n in fam_n.items()}
    rest = R.N_SELECT - sum(floors.values())
    prop = largest_remainder(rest, fam_n, {f: fam_n[f] - floors[f] for f in fam_n})
    fam_alloc = {f: floors[f] + prop[f] for f in fam_n}
    alloc = {}
    for f in sorted(fam_n):
        st = rd[rd.family == f].stratum.value_counts().to_dict()
        alloc.update(largest_remainder(fam_alloc[f], st, st))
    rng = np.random.default_rng(R.SEED_SELECT)
    order = {}
    for s in sorted(alloc):
        ids = sorted(rd.loc[rd.stratum == s, "survey_id"])
        order[s] = [ids[i] for i in rng.permutation(len(ids))]
    size = rd.set_index("survey_id").advertised_bytes.astype("int64").to_dict()
    sel = {s: list(order[s][:alloc[s]]) for s in alloc}
    nxt = {s: alloc[s] for s in alloc}
    total = lambda: sum(size[c] for s in sel for c in sel[s])
    tot0 = total(); repl = []; rounds = 0
    while total() > R.CAP_BYTES:
        rounds += 1
        n_sel = sum(len(v) for v in sel.values()); t = total()
        over = {s: (sum(size[c] for c in sel[s]) / t) / (len(sel[s]) / n_sel) for s in sel if sel[s]}
        cands = [s for s in sorted(over, key=lambda s: -over[s]) if over[s] > 1.0 and nxt[s] < len(order[s])]
        if not cands:
            break
        for s in cands:
            big = max(sel[s], key=lambda c: (size[c], c))
            new = order[s][nxt[s]]; nxt[s] += 1
            sel[s][sel[s].index(big)] = new
            repl.append({"round": rounds, "stratum": s, "over_representation": round(over[s], 4), "removed": big, "removed_bytes": size[big],
                         "added": new, "added_bytes": size[new], "total_after_bytes": total()})
            if total() <= R.CAP_BYTES:
                break
    final = total()
    rows = []
    for s in sorted(sel):
        for rank, c in enumerate(sel[s]):
            r = rd[rd.survey_id == c].iloc[0]
            rows.append({"cruise": c, "stratum": s, "family": r.family, "basin": r.basin, "draw_rank": rank,
                         "advertised_bytes": int(size[c]), "n_swath_files": int(r.n_swath_files), "mb_format": int(r.dominant_format),
                         "year": r.year, "platform": r.platform, "instrument": r.instrument,
                         "file_list_source": f"NCEI autoindex {r.data_url} (listing cached; file list {r.file_list})"})
    df = pd.DataFrame(rows).sort_values(["draw_rank", "stratum"]).reset_index(drop=True)
    df.insert(0, "order", range(1, len(df) + 1))
    C.assert_no_lockbox_cruise(df.cruise.tolist())
    df.to_csv(R.REPORT_DIR / "selection_v1.csv", index=False)
    # the selected cruises' file lists, frozen beside the selection (plain CSV, one row per planned swath file)
    fl = pd.concat([pd.read_csv(p) for p in df.file_list_source.str.extract(r"file list (.*)\)$")[0]], ignore_index=True)
    fl.to_csv(R.REPORT_DIR / "selection_v1_filelist.csv.gz", index=False)
    out = {"generated": R.utc_now(), "code_commit": C.git_commit(), "seed": R.SEED_SELECT, "n_select": R.N_SELECT,
           "pool_v1_sha256": R.sha256_file(R.REPORT_DIR / "pool_v1.csv"),
           "readable_pool": int(len(rd)), "unreadable_pool": int((~pool.readable).sum()),
           "strata_merged": sorted(set(rd.loc[rd.stratum != rd.stratum0, "stratum0"])),
           "family_counts_readable": fam_n, "family_floor": floors, "family_allocation": fam_alloc,
           "allocation_per_stratum": dict(sorted(alloc.items())), "stratum_sizes": rd.stratum.value_counts().sort_index().to_dict(),
           "total_bytes_initial": int(tot0), "cap_bytes": R.CAP_BYTES, "replacement_rounds": rounds, "replacements": repl,
           "n_replacements": len(repl), "total_bytes_final": int(final), "total_tb_final": round(final / 1e12, 4),
           "cap_met": bool(final <= R.CAP_BYTES), "n_selected": int(len(df)),
           "selected_per_family": df.family.value_counts().to_dict(), "selected_per_basin": df.basin.value_counts().to_dict(),
           "files_planned": int(len(fl))}
    R.write_json(R.REPORT_DIR / "selection_v1.json", out)
    print(json.dumps({k: v for k, v in out.items() if k not in ("replacements",)}, indent=1))
    return 0 if out["cap_met"] else 2


if __name__ == "__main__":
    sys.exit(main())
