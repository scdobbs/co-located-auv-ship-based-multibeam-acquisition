"""ACQ-R04 selection_v1.1 — removal only (steering ruling on the batch-1 HOLD, 2026-10-03, option D).

Removes from selection_v1 every cruise of the Reson, Kongsberg EM7xx/EM1xxx/EM2040 (shallow) and other/unknown families
that has not been processed yet.  No new draw; nothing else changes.  The 9 cruises of those families processed in
batch 1 stay in the selection and in the ledger as zero-yield (0 kept blocks), their block ledgers unchanged.
Reason: the 300 m depth floor (§3.3.4) — 9 of 9 tested cruises of the three families kept 0 blocks
(gate_batch1.json / their cruise_record.json).
Writes selection_v1_1.csv (the remaining selection), selection_v1_1_removed.csv (cruise, family, stratum, advertised
bytes, reason), selection_v1_1.json (counts, bytes, hashes), queue_v1_1.csv + queue_v1_1/batch_NN.txt (the revised
queue for the relaunch: AR30-01 first (re-fetch + re-grid under the collision fix), then the not-yet-processed
cruises of queue_v1 batches 2-9 in their original order, 45 per batch).
Usage: python -m src.acq_r04.selection_v1_1
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from src.acq_r04 import common as R
from src.acq_r01 import common as C
from src.acq_r04.blocks import cdir_name

FAMILIES = ["Reson", "Kongsberg EM7xx/EM1xxx/EM2040 (shallow)", "other/unknown"]
REASON = ("steering ruling 2026-10-03 (batch-1 HOLD, option D): removed under the 300 m depth floor (§3.3.4); "
          "9 of 9 tested cruises of the Reson, EM7xx/shallow and other/unknown families kept 0 blocks")
BATCH = 45


def processed(c):
    return (R.WORK_LOGS / cdir_name(c) / "cruise_record.json").exists()


def main():
    sel = pd.read_csv(R.REPORT_DIR / "selection_v1.csv")
    q = pd.read_csv(R.REPORT_DIR / "queue_v1.csv")
    fam = sel[sel.family.isin(FAMILIES)]
    tested = [c for c in fam.cruise if processed(c)]
    tested_kept = {c: json.loads((R.WORK_LOGS / cdir_name(c) / "cruise_record.json").read_text())["blocks_kept"] for c in tested}
    assert len(tested) == 9 and sum(tested_kept.values()) == 0, (tested, tested_kept)
    rm = fam[~fam.cruise.isin(tested)].copy()
    rm["reason"] = REASON
    keep = sel[~sel.cruise.isin(rm.cruise)].copy()
    keep.to_csv(R.REPORT_DIR / "selection_v1_1.csv", index=False)
    rm[["cruise", "family", "stratum", "basin", "advertised_bytes", "reason"]].to_csv(R.REPORT_DIR / "selection_v1_1_removed.csv", index=False)
    # revised queue: AR30-01 first, then the unprocessed remainder of queue_v1 batches >= 2 in order
    rest = q[(q.batch >= 2) & ~q.cruise.isin(rm.cruise)].sort_values(["batch"], kind="stable")
    todo = ["AR30-01"] + [c for c in rest.cruise if c != "AR30-01" and not processed(c)]
    qd = R.REPORT_DIR / "queue_v1_1"; qd.mkdir(exist_ok=True)
    rows = []
    for i in range(0, len(todo), BATCH):
        b = todo[i:i + BATCH]; n = i // BATCH + 1
        (qd / f"batch_{n:02d}.txt").write_text("\n".join(b) + "\n")
        rows += [{"cruise": c, "batch": n} for c in b]
    qq = pd.DataFrame(rows).merge(sel[["cruise", "family", "advertised_bytes"]], on="cruise", how="left")
    qq.to_csv(R.REPORT_DIR / "queue_v1_1.csv", index=False)
    C.assert_no_lockbox_cruise(qq.cruise.tolist())
    out = {"generated": R.utc_now(), "code_commit": C.git_commit(), "basis": "selection_v1 (seed 20261003), removal only, no new draw",
           "selection_v1_sha256": R.sha256_file(R.REPORT_DIR / "selection_v1.csv"), "reason": REASON,
           "families": FAMILIES, "tested_zero_yield": tested_kept, "removed_n": int(len(rm)),
           "removed_bytes": int(rm.advertised_bytes.sum()), "removed_by_family": rm.family.value_counts().to_dict(),
           "selection_v1_1_n": int(len(keep)), "selection_v1_1_bytes": int(keep.advertised_bytes.sum()),
           "selection_v1_1_per_family": keep.family.value_counts().to_dict(),
           "queue_v1_1": {"cruises": int(len(qq)), "batches": int(qq.batch.max()), "bytes": int(qq.advertised_bytes.sum()),
                          "first": "AR30-01 (re-fetch + re-grid under the file-name collision fix, commit 6f06846)"},
           "sha256": {n: R.sha256_file(R.REPORT_DIR / n) for n in ("selection_v1_1.csv", "selection_v1_1_removed.csv", "queue_v1_1.csv")}}
    R.write_json(R.REPORT_DIR / "selection_v1_1.json", out)
    print(json.dumps({k: v for k, v in out.items() if k != "sha256"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
