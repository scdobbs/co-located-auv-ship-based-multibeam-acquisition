"""ACQ-R05 ruling H-1 (Steve, 2026-10-09): delete the unselected over-fetched NA080 / TN299 files from OAK, restore the
backed-up fetch manifests, keep the 76 TN299 files that TN299__MGDS_31253 uses (they stay in the manifest + SHA256SUMS).

Dry run by default; --execute deletes.  Writes overfetch_deletion_2026-10-09.json (every deleted file with size and
sha256, so it is re-fetchable and verifiable) and re-verifies each cruise directory afterwards (file set == manifest,
SHA256SUMS lines == manifest, kept files present with their recorded size).
Usage: python -m src.acq_r05.h1_delete_overfetch [--execute]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys

import pandas as pd

from src.acq_r05 import common as R
from src.acq_r01 import common as C
from src.acq_r01.build_products import swath_files

TAG = "pre_acq_r05_2026-10-09"


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--execute", action="store_true")
    a = ap.parse_args(argv)
    df = pd.read_csv(R.REPORT_DIR / "overfetch_deletable_v1.csv")
    rec = {"ruling": "ACQ-R05 H-1 (Steve, 2026-10-09)", "executed": a.execute, "at": R.utc_now(), "cruises": {}, "code_commit": R.git_commit()}
    ok_all = True
    for cruise in ("NA080", "TN299"):
        C.assert_no_lockbox_cruise([cruise])
        d = C.RAW_SWATH_OAK / cruise
        sub = df[df.cruise == cruise]
        to_delete = sub[~sub.selected_by_a_pair]; keep = sub[sub.selected_by_a_pair]
        man_bk = json.loads((d / f"fetch_manifest.json.{TAG}").read_text())
        man_cur = json.loads((d / "fetch_manifest.json").read_text())
        cur = {f["filename"]: f for f in man_cur["files"] if "acq_r05" in f}
        bk_names = {f.get("filename") or f.get("name") for f in man_bk["files"]}
        assert not (set(to_delete.filename) & bk_names), "a file to delete is in the backed-up manifest"
        assert set(keep.filename) <= set(cur) and set(to_delete.filename) <= set(cur)
        # restored manifest = backup + kept entries (with their acq_r05 tag and a ruling note)
        kept_entries = [{**cur[n], "acq_r05": cur[n]["acq_r05"] + "; kept under ruling H-1 (used by TN299__MGDS_31253 context)"} for n in keep.filename]
        new_man = dict(man_bk); new_man["files"] = list(man_bk["files"]) + kept_entries
        new_man["n_files_ok"] = len(new_man["files"]); new_man["n_files_failed"] = 0
        new_man["acq_r05_ruling_h1"] = {"at": R.utc_now(), "deleted_n": int(len(to_delete)), "deleted_gb": round(float(to_delete["size"].sum()) / 1e9, 2), "kept_n": int(len(keep)),
                                        "deleted_list": "reports_post_grl_review/ACQ-R05/overfetch_deletion_2026-10-09.json", "manifest_restored_from": f"fetch_manifest.json.{TAG}"}
        sums_bk = (d / f"SHA256SUMS.{TAG}").read_text()
        new_sums = sums_bk + "".join(f"{e['sha256']}  {e['filename']}\n" for e in kept_entries)
        crec = {"n_delete": int(len(to_delete)), "gb_delete": round(float(to_delete["size"].sum()) / 1e9, 2), "n_keep": int(len(keep)),
                "manifest_files_after": len(new_man["files"]), "deleted": to_delete[["filename", "size", "sha256"]].to_dict("records")}
        if a.execute:
            missing = [n for n in to_delete.filename if not (d / n).exists()]
            for n in to_delete.filename:
                p = d / n
                if p.exists():
                    p.chmod(0o644); p.unlink()
            for name, txt in (("fetch_manifest.json", json.dumps(new_man, indent=1, default=str)), ("SHA256SUMS", new_sums)):
                p = d / name
                if p.exists():
                    p.chmod(0o644)
                p.write_text(txt); R.chmod_ro(p)
            on_disk = {p.name for p in swath_files(d)}
            man_names = {f.get("filename") or f.get("name") for f in new_man["files"]}
            sums_n = len([l for l in new_sums.splitlines() if l.strip()])
            kept_ok = all((d / n).exists() and (d / n).stat().st_size == int(cur[n]["size"]) for n in keep.filename)
            crec["verify"] = {"files_on_disk": len(on_disk), "manifest_files": len(man_names), "disk_eq_manifest": on_disk == man_names,
                              "sha256sums_lines": sums_n, "sums_eq_manifest": sums_n == len(man_names), "kept_present_with_size": kept_ok,
                              "missing_before_delete": missing}
            ok_all &= on_disk == man_names and sums_n == len(man_names) and kept_ok
        rec["cruises"][cruise] = crec
        print(f"{cruise}: delete {crec['n_delete']} files ({crec['gb_delete']} GB), keep {crec['n_keep']}, manifest after {crec['manifest_files_after']}", crec.get("verify", "(dry run)"))
    out = R.REPORT_DIR / ("overfetch_deletion_2026-10-09.json" if a.execute else "overfetch_deletion_dryrun.json")
    out.write_text(json.dumps(rec, indent=1, default=str))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
