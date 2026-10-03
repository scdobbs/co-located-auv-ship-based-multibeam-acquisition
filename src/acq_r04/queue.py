"""ACQ-R04 full-run queue (steering ruling 2026-10-03).

The 390 non-pilot cruises of selection_v1 are split into fetch/processing batches.  Batch 1 starts with the first two
cruises (selection_v1 order) of each family the pilot did not cover — SeaBeam family, Reson, Kongsberg EM7xx/EM1xxx/
EM2040 (shallow), other/unknown — then fills to BATCH1 cruises in selection order; later batches take BATCH cruises
each in selection order.  Writes queue_v1.csv (cruise, batch, family, advertised bytes, gate_family) and
queue/batch_NN.txt (one cruise per line).
Gate (`gate` mode, after batch 1 is processed): HOLD (exit 1) if any of the four families has zero kept blocks over
its batch-1 cruises, or if gridding failed on every candidate block of its first cruise (or the cruise failed).
Usage: python -m src.acq_r04.queue build | gate
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from src.acq_r04 import common as R
from src.acq_r04.blocks import cdir_name

GATE_FAMILIES = ["SeaBeam family", "Reson", "Kongsberg EM7xx/EM1xxx/EM2040 (shallow)", "other/unknown"]
PER_FAMILY = 2
BATCH1 = 30
BATCH = 45
QDIR = R.REPORT_DIR / "queue"


def build():
    sel = pd.read_csv(R.REPORT_DIR / "selection_v1.csv").sort_values("order")
    pilot = set((R.REPORT_DIR / "pilot_cruises.txt").read_text().split())
    rest = sel[~sel.cruise.isin(pilot)]
    first = []
    for f in GATE_FAMILIES:
        first += rest[rest.family == f].cruise.head(PER_FAMILY).tolist()
    others = [c for c in rest.cruise if c not in first]
    b1 = first + others[: BATCH1 - len(first)]
    remain = others[BATCH1 - len(first):]
    batches = [b1] + [remain[i:i + BATCH] for i in range(0, len(remain), BATCH)]
    rows = []
    QDIR.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(batches, 1):
        (QDIR / f"batch_{i:02d}.txt").write_text("\n".join(b) + "\n")
        for c in b:
            r = sel[sel.cruise == c].iloc[0]
            rows.append({"cruise": c, "batch": i, "family": r.family, "advertised_bytes": int(r.advertised_bytes),
                         "gate_family": c in first})
    q = pd.DataFrame(rows)
    assert len(q) == len(rest) == q.cruise.nunique()
    q.to_csv(R.REPORT_DIR / "queue_v1.csv", index=False)
    print(q.groupby("batch").agg(n=("cruise", "count"), GB=("advertised_bytes", lambda s: round(s.sum() / 1e9, 1))).to_string())
    print("batch 1 gate cruises:", first)


def gate():
    q = pd.read_csv(R.REPORT_DIR / "queue_v1.csv")
    b1 = q[q.batch == 1]
    out, hold = {}, []
    for f in GATE_FAMILIES:
        cr = b1[b1.family == f].cruise.tolist()
        kept, per = 0, {}
        for c in cr:
            lg = R.WORK_LOGS / cdir_name(c)
            if (lg / "cruise_record.json").exists():
                rec = json.loads((lg / "cruise_record.json").read_text())
                st = rec.get("block_status", {})
                cand = sum(v for k, v in st.items() if k in ("kept", "drop_fill", "fail_mbgrid"))
                per[c] = {"kept": rec.get("blocks_kept", 0), "status": st, "candidates_gridded": cand,
                          "all_gridding_failed": cand > 0 and st.get("fail_mbgrid", 0) == cand}
                kept += rec.get("blocks_kept", 0)
            else:
                fail = lg / "cruise_failure.json"
                per[c] = {"kept": 0, "cruise_failure": json.loads(fail.read_text())["error"][:300] if fail.exists() else "no record",
                          "all_gridding_failed": True}
        first = per.get(cr[0], {}) if cr else {}
        reasons = []
        if kept == 0:
            reasons.append("zero kept blocks over its batch-1 cruises")
        if first.get("all_gridding_failed"):
            reasons.append(f"gridding failed on every block of its first cruise ({cr[0]})")
        out[f] = {"cruises": per, "kept_total": kept, "hold": bool(reasons), "reasons": reasons}
        if reasons:
            hold.append(f)
    res = {"generated": R.utc_now(), "families": out, "hold": bool(hold), "hold_families": hold}
    R.write_json(R.REPORT_DIR / "gate_batch1.json", res)
    print(json.dumps(res, indent=1, default=str))
    return 1 if hold else 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    sys.exit(build() or 0 if mode == "build" else gate())
