"""ACQ-R03 §1.4 — ingest files Steve downloaded himself from OAK raw_lr_swath/_inbox/<cruise>/.

A file is accepted only if (a) its name is in the §1.2 selection, (b) its size equals the advertised size
(±1 kB), (c) `mbinfo` reads it.  Accepted files are sha256'd, moved to raw_lr_swath/<cruise>/ (0444) and recorded
in fetch_manifest.json with "source": "manual".  Rejects stay in the inbox and are listed in
reports_post_grl_review/ACQ-R03/manual_ingest_<cruise>.json.  Files the automated fetch already holds are skipped
(left in the inbox, listed as "already_present").
Usage: python -m src.acq_r03.ingest_manual --cruise PANGAEA_892317      (light: fine in an sh_dev session)
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys

import pandas as pd

from src.acq_r03 import common as R
from src.acq_r03.fetch_pangaea import size_ok


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--cruise", required=True)
    a = ap.parse_args(argv)
    cruise_dir = R.RAW_SWATH / a.cruise; inbox = R.RAW_SWATH / "_inbox" / a.cruise
    inbox.mkdir(parents=True, exist_ok=True); cruise_dir.mkdir(parents=True, exist_ok=True)
    sel_p = R.REPORT_DIR / f"pangaea_selection_{a.cruise}.csv"
    if not sel_p.exists():
        print(f"no selection yet for {a.cruise} ({sel_p}); nothing ingested"); return 1
    sel = pd.read_csv(sel_p).set_index("file_name")
    man = R.load_manifest(cruise_dir)
    rep = {"cruise": a.cruise, "accepted": [], "rejected": [], "already_present": [], "at": R.utc_now()}
    for p in sorted(inbox.iterdir()):
        if not p.is_file():
            continue
        if p.name not in sel.index:
            rep["rejected"].append({"name": p.name, "reason": "not in the §1.2 selection"}); continue
        adv = int(sel.loc[p.name, "advertised_size_bytes"])
        dst = cruise_dir / p.name
        if dst.exists() and size_ok(dst.stat().st_size, adv):
            rep["already_present"].append(p.name); continue
        if not size_ok(p.stat().st_size, adv):
            rep["rejected"].append({"name": p.name, "size": p.stat().st_size, "advertised": adv, "reason": "size != advertised (±1 kB)"}); continue
        ok, note = R.mbinfo_reads(p)
        if not ok:
            rep["rejected"].append({"name": p.name, "reason": f"mbinfo does not read it ({note})"}); continue
        sha = R.C.sha256_file(p)
        if dst.exists():
            dst.chmod(0o644); dst.unlink()
        shutil.move(str(p), str(dst)); dst.chmod(0o444)
        man["files"] = [f for f in man["files"] if f["name"] != p.name]
        man["files"].append({"name": p.name, "url": str(sel.loc[p.name, "url"]), "size": dst.stat().st_size, "sha256": sha, "source": "manual", "mbinfo": note, "recorded_at": R.utc_now()})
        rep["accepted"].append(p.name)
    R.save_manifest(cruise_dir, man)
    R.write_json(R.REPORT_DIR / f"manual_ingest_{a.cruise}.json", rep)
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in rep.items()}, indent=1)); return 0


if __name__ == "__main__":
    sys.exit(main())
