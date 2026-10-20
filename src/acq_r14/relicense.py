"""ACQ-R14 ruling 2026-10-20 (H-1 option b): relicense every pair to CC BY-NC-SA 4.0. Rewrites each pair's pair.json in
the stage directory (sources.pair_license, pair_license_status, record_license, sources_cc_by_or_public_domain_only,
release.ruling), re-zips the pair from the unchanged staged COGs, and updates build_results.json. Rasters untouched.

    python -B -m src.acq_r14.relicense
"""
from __future__ import annotations
import os, zipfile
from pathlib import Path
from . import common as C
from .build import BUILD_RESULTS

RULING = "2026-10-20 H-1 option (b): the whole record, every pair and the corpus-level files are CC BY-NC-SA 4.0"


def main():
    lic, build = C.jload(C.LICENSE_AUDIT), C.jload(BUILD_RESULTS)
    n = 0
    for pid, br in build["pairs"].items():
        st = C.STAGE / pid
        pj = br["pair_json"]
        per = lic["per_pair"][pid]
        files = pj["files"]
        for rel, f in files.items():
            p = st / rel
            if not p.exists() or p.stat().st_size != f["bytes"]:
                raise SystemExit(f"{pid}: staged file {rel} missing or changed; rebuild needed")
        pj["sources"]["pair_license"] = per["pair_license"]
        pj["sources"]["pair_license_status"] = per["status"]
        pj["sources"]["record_license"] = per["pair_license"]
        pj["sources"]["sources_cc_by_or_public_domain_only"] = per["sources_cc_by_or_public_domain_only"]
        pj["sources"]["hr"]["license"] = lic["datasets"][pj["sources"]["hr"]["dataset_id"]]["license"]
        pj["sources"]["hr"]["license_evidence"] = lic["datasets"][pj["sources"]["hr"]["dataset_id"]].get("evidence")
        pj["sources"]["hr"]["redistribution"] = lic["datasets"][pj["sources"]["hr"]["dataset_id"]]["redistribution"]
        pj["release"]["ruling"] = RULING
        pj["grids"]["elevation_units"] = "meters, positive up (seafloor depths are negative)"
        if pj["coregistration"].get("datum_repair"):
            pj["coregistration"]["datum_repair"]["note"] = pj["coregistration"]["datum_repair"]["note"].replace("metres", "meters")
        pj["release"]["generated"] = C.utcnow()
        C.jdump(pj, st / "pair.json")
        zpath = Path(br["zip"])
        tmp = zpath.with_suffix(".zip.tmp")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as z:
            for rel in sorted(files) + ["pair.json"]:
                z.write(st / rel, arcname=rel)
        os.replace(tmp, zpath)
        br["zip_bytes"], br["zip_sha256"] = zpath.stat().st_size, C.sha256(zpath)
        n += 1
    build["relicensed"] = {"ruling": RULING, "time": C.utcnow(), "n": n}
    C.jdump(build, BUILD_RESULTS)
    C.fix("relicense", None, f"ruling applied: {n} pair.json rewritten with pair_license = CC BY-NC-SA 4.0 and re-zipped from the unchanged staged COGs")
    C.log(f"relicense: {n} pairs re-zipped")


if __name__ == "__main__":
    main()
