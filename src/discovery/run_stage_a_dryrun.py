"""Run the Phase 2 Stage A raw-LR byte dry-run over the unique NCEI cruises.

Reads the authoritative raw-LR cruise set from staging_state_20260605.json,
sizes each unique cruise via NCEI autoindex listings (cached), and writes:
  - reports/discovery/stage_a_raw_lr_sizes_<date>.csv  (per-cruise table)
  - reports/discovery/stage_a_raw_lr_sizes_<date>.json (full breakdown + census)

No bulk data is fetched. Idempotent: directory listings are cached on scratch.
"""

from __future__ import annotations

import csv
import json
import logging
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from src.discovery.raw_lr_dryrun import (
    CruiseSize, data_dir_from_iso, resolve_data_dir, size_cruise,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
log = logging.getLogger("stage_a")

REPO = Path(__file__).resolve().parents[2]
STATE = REPO / "reports/discovery/staging_state_20260605.json"
CACHE = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/discovery_cache")
GEOPORTAL = CACHE / "geoportal"
DIRLIST = CACHE / "ncei_dirlist"

# Primary swath formats: vendor-raw vs MB-System-converted. When BOTH appear
# for a cruise they are duplicate encodings of the same soundings -> count once.
VENDOR_SWATH = (".all.gz", ".gsf.gz", ".all", ".gsf")
MBSYS_SWATH_RE = r"\.mb\d+\.gz$|\.mb\d+$"  # .mb57.gz, .mb58.gz, .mb121 ...


def classify(ext: str) -> str:
    import re
    if ext in VENDOR_SWATH or ext.endswith(".all.mb58.gz") or ext.endswith(".all.mb59.gz") \
            or ext.endswith(".gsf.mb121.gz"):
        # ".all.mbXX.gz" is the MB-System wrapper of a vendor file = swath data.
        return "swath_mbsys" if ".mb" in ext else "swath_vendor"
    if re.search(MBSYS_SWATH_RE, ext):
        return "swath_mbsys"
    return "ancillary"


def fetch_estimate(cs: CruiseSize) -> tuple[int, str]:
    """Realistic fetch bytes for one cruise: the primary swath encoding counted
    once (prefer vendor-raw if both present, since MB-System can derive the rest)
    plus required nav ancillary. Returns (bytes, basis_note)."""
    swath_vendor = sum(b for e, b in cs.ext_bytes.items() if classify(e) == "swath_vendor")
    swath_mbsys = sum(b for e, b in cs.ext_bytes.items() if classify(e) == "swath_mbsys")
    if swath_vendor and swath_mbsys:
        # Duplicate encodings; keep one (the larger, to be conservative).
        swath = max(swath_vendor, swath_mbsys)
        basis = f"dup-format: vendor={swath_vendor/1024**3:.2f}GB + "\
                f"mbsys={swath_mbsys/1024**3:.2f}GB; kept larger"
    else:
        swath = swath_vendor or swath_mbsys
        basis = "single swath encoding"
    return swath, basis


def main() -> None:
    state = json.loads(STATE.read_text())
    refs = state["raw_lr_in_training_eval"] + state["DEFER_PHASE_2_raw_lr_to_grid"]
    # cruise -> list of HR served (with tier where known)
    served: dict[str, list[str]] = defaultdict(list)
    for r in refs:
        cruise = r["lr_id"].split(":", 1)[1]
        served[cruise].append(r.get("hr_id", "?"))
    cruises = sorted(served)
    log.warning("sizing %d unique cruises (%d raw-LR references)", len(cruises), len(refs))

    results: list[dict] = []
    ext_census: Counter = Counter()
    ext_census_bytes: Counter = Counter()
    for i, c in enumerate(cruises, 1):
        iso_url = data_dir_from_iso(c, GEOPORTAL)
        if not iso_url:
            cs = CruiseSize(cruise=c, data_url="", status="lookup_failed",
                            note="no data-dir URL in ISO")
            work_url, note = "", cs.note
        else:
            work_url, note = resolve_data_dir(iso_url, DIRLIST)
            if work_url is None:
                cs = CruiseSize(cruise=c, data_url=iso_url, status="lookup_failed", note=note)
            else:
                cs = size_cruise(c, work_url, DIRLIST)
                if note:
                    cs.note = (note + "; " + cs.note).strip("; ")
        for e, n in cs.ext_counts.items():
            ext_census[e] += n
            ext_census_bytes[e] += cs.ext_bytes.get(e, 0)
        fetch_b, basis = fetch_estimate(cs)
        results.append({
            "cruise": c,
            "n_hr_served": len(served[c]),
            "hr_served": ";".join(sorted(set(served[c]))),
            "status": cs.status,
            "n_files": cs.n_files,
            "full_mirror_bytes": cs.total_bytes,
            "full_mirror_gb": round(cs.total_bytes / 1024**3, 3),
            "fetch_estimate_bytes": fetch_b,
            "fetch_estimate_gb": round(fetch_b / 1024**3, 3),
            "fetch_basis": basis,
            "ext_breakdown": {e: cs.ext_bytes[e] for e in cs.ext_bytes},
            "data_url": cs.data_url,
            "note": cs.note,
        })
        log.warning("[%2d/%d] %-16s %-13s files=%-5d full=%6.2fGB fetch=%6.2fGB  %s",
                    i, len(cruises), c, cs.status, cs.n_files,
                    cs.total_bytes / 1024**3, fetch_b / 1024**3,
                    cs.note[:40])

    ok = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "lookup_failed"]
    empty = [r for r in results if r["status"] == "empty"]
    grand_full = sum(r["full_mirror_bytes"] for r in results)
    grand_fetch = sum(r["fetch_estimate_bytes"] for r in results)

    today = date.today().isoformat()
    out_json = REPO / f"reports/discovery/stage_a_raw_lr_sizes_{today}.json"
    out_csv = REPO / f"reports/discovery/stage_a_raw_lr_sizes_{today}.csv"

    summary = {
        "generated": today,
        "method": "NCEI MBBDB autoindex listing sum (no fetch); sizes are "
                  "Apache human-rounded, precise to the GB in aggregate",
        "n_raw_lr_references": len(refs),
        "n_unique_cruises": len(cruises),
        "n_ok": len(ok), "n_empty": len(empty), "n_lookup_failed": len(failed),
        "grand_full_mirror_gb": round(grand_full / 1024**3, 2),
        "grand_fetch_estimate_gb": round(grand_fetch / 1024**3, 2),
        "lookup_failed_cruises": [r["cruise"] for r in failed],
        "empty_cruises": [r["cruise"] for r in empty],
        "ext_census_counts": dict(ext_census.most_common()),
        "ext_census_gb": {e: round(b / 1024**3, 3) for e, b in ext_census_bytes.most_common()},
        "per_cruise": results,
    }
    out_json.write_text(json.dumps(summary, indent=2))

    with out_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cruise", "n_hr_served", "status", "n_files",
                    "full_mirror_gb", "fetch_estimate_gb", "fetch_basis",
                    "data_url", "note", "hr_served"])
        for r in sorted(results, key=lambda x: -x["fetch_estimate_gb"]):
            w.writerow([r["cruise"], r["n_hr_served"], r["status"], r["n_files"],
                        r["full_mirror_gb"], r["fetch_estimate_gb"], r["fetch_basis"],
                        r["data_url"], r["note"], r["hr_served"]])

    print("\n================ STAGE A DRY-RUN SUMMARY ================")
    print(f"raw-LR references         : {len(refs)}")
    print(f"unique cruises            : {len(cruises)}")
    print(f"  ok / empty / failed     : {len(ok)} / {len(empty)} / {len(failed)}")
    print(f"GRAND fetch estimate      : {grand_fetch/1024**3:.2f} GB  (swath, dedup)")
    print(f"GRAND full-mirror         : {grand_full/1024**3:.2f} GB  (everything incl. ancillary+dup)")
    if failed:
        print(f"lookup_failed             : {[r['cruise'] for r in failed]}")
    if empty:
        print(f"empty                     : {[r['cruise'] for r in empty]}")
    print(f"\nwrote {out_csv}")
    print(f"wrote {out_json}")


if __name__ == "__main__":
    main()
