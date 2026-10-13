"""ACQ-R09 §3.1 — the mock sealed layout for the rehearsal (development data only, scratch only).

$GROUP_SCRATCH/auv_ship_colocated_bathy/ACQ-R09/mock/sealed_candidates_v3/<token>/ holds COPIES (not links) of the files
the development download step stored for three development pairs, laid out as ACQ-R08b laid out the real sealed
directories (top-level downloaded files, plus an `_conv/` directory of decompressed copies that the step must ignore):
  MGDS_22383 (FK151121__MGDS_22383), MGDS_31289 (NA080__MGDS_31289), MGDS_31429 (KM0923__MGDS_31429);
plus
  MOCK_R09repeat — a constructed repeat-survey record: two overlapping copies of KM0923's sent_shdeep2m grid,
      A = the whole grid, file-name date 2006-06-15 (3 years from the KM0923 cruise year 2009),
      B = a sub-grid (rows/cols 15-85 %), file-name date 2009-06-15 (0 years);
      the repeat-survey rule must keep B (closest year) although A has the larger valid area, and drop A;
  MGDS_99999 — a decoy directory that is in no site list (the guard must refuse it after admission of the mock ids).
The mock site list (reports_post_grl_review/ACQ-R09/rehearsal/mock_sites.csv) names the four mock sites with their
development ship cruise (swath read from the development store OAK raw_lr_swath/<cruise>/, no network), sonar string as
the development grid record and cruise year.  Every copy is sha256-checked against its source.
Usage: python -m src.phase5.mock_p5
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import shutil
import sys
from pathlib import Path

from src.acq_r01 import common as C
from src.phase5 import common_p5 as P
from src.phase5 import guard_p5 as GP

RAW_HR = C.OAK / "raw_hr"
DEV = [("FK151121 development pair", "MGDS:22383", "FK151121", "Kongsberg EM302; EM710", 2015),
       ("NA080 development pair", "MGDS:31289", "NA080", "Kongsberg EM302", 2017),
       ("KM0923 development pair", "MGDS:31429", "KM0923", "Simrad EM120", 2009)]
MOCK_REPEAT = ("Mock repeat survey (KM0923 HR copies)", "MOCK:R09repeat", "KM0923", "Simrad EM120", 2009)
REPEAT_SRC = RAW_HR / "MGDS_31429" / "sent_shdeep2m.asc.gz"
REPEAT_A = "mockrepeat_shdeep_20060615_2m.asc.gz"
REPEAT_B = "mockrepeat_shdeep_20090615_2m_sub.asc.gz"
EXPECTED_REPEAT = {"kept": [REPEAT_B[:-3]], "dropped": [REPEAT_A[:-3]]}


def crop_asc(text: str, f0: float = 0.15, f1: float = 0.85) -> str:
    lines = text.splitlines()
    hdr = {}
    i = 0
    while len(hdr) < 6:
        k, v = lines[i].split()[:2]; hdr[k.lower()] = v; i += 1
    nc, nr, x0, y0, cs = int(hdr["ncols"]), int(hdr["nrows"]), float(hdr["xllcorner"]), float(hdr["yllcorner"]), float(hdr["cellsize"])
    r0, r1, c0, c1 = int(nr * f0), int(nr * f1), int(nc * f0), int(nc * f1)
    rows = [ln.split()[c0:c1] for ln in lines[i + r0:i + r1]]
    # yllcorner of the crop: the bottom row kept is r1-1 (rows count from the top)
    y_new = y0 + (nr - r1) * cs
    out = [f"ncols {c1 - c0}", f"nrows {r1 - r0}", f"xllcorner {x0 + c0 * cs!r}", f"yllcorner {y_new!r}", f"cellsize {hdr['cellsize']}", f"nodata_value {hdr['nodata_value']}"]
    return "\n".join(out + [" ".join(r) for r in rows]) + "\n"


def main(argv=None):
    root = P.MOCK_ROOT
    if root.exists():
        for p in root.rglob("*"):
            p.chmod(0o755 if p.is_dir() else 0o644)
        shutil.rmtree(root)
    root.mkdir(parents=True)
    toks = [P.token(r[1]) for r in DEV + [MOCK_REPEAT]] + ["MGDS_99999"]
    GP.install_phase5_allowance(toks, root, [], reason="ACQ-R09 rehearsal (mock root, development data): mock layout builder")
    try:
        return _build(root)
    finally:
        GP.remove_phase5_allowance()


def _build(root: Path):
    copies = []
    for name, hid, cruise, sonar, year in DEV:
        src_dir = RAW_HR / hid.replace(":", "_"); dst = root / P.token(hid); dst.mkdir()
        man = json.loads((src_dir / "download_manifest.json").read_text())
        for f in man["files"]:
            s = Path(f["path"]); d = dst / s.name
            shutil.copyfile(s, d)
            a, b = P.sha256_file(s), P.sha256_file(d)
            if a != b or (f.get("sha256") and f["sha256"] != a):
                raise SystemExit(f"copy mismatch {s} -> {d}")
            copies.append({"src": str(s), "dst": str(d), "sha256": b, "link": d.is_symlink()})
        conv = dst / "_conv"; conv.mkdir()                          # ACQ-R08b-like converted copies: the step must ignore them
        first = sorted(dst.glob("*.gz"))[0]
        with gzip.open(first, "rb") as fi, open(conv / first.name[:-3], "wb") as fo:
            shutil.copyfileobj(fi, fo)
    rep = root / P.token(MOCK_REPEAT[1]); rep.mkdir()
    shutil.copyfile(REPEAT_SRC, rep / REPEAT_A)
    if P.sha256_file(REPEAT_SRC) != P.sha256_file(rep / REPEAT_A):
        raise SystemExit("repeat copy A mismatch")
    with gzip.open(REPEAT_SRC, "rt") as fi:
        sub = crop_asc(fi.read())
    with gzip.open(rep / REPEAT_B, "wt") as fo:
        fo.write(sub)
    copies += [{"src": str(REPEAT_SRC), "dst": str(rep / REPEAT_A), "sha256": P.sha256_file(rep / REPEAT_A), "link": False, "note": "whole grid, date 2006-06-15 in the name"},
               {"src": str(REPEAT_SRC), "dst": str(rep / REPEAT_B), "sha256": P.sha256_file(rep / REPEAT_B), "link": False, "note": "rows/cols 15-85 % crop, date 2009-06-15 in the name"}]
    decoy = root / "MGDS_99999"; decoy.mkdir()
    (decoy / "decoy.grd").write_text("decoy: not in any site list\n")
    rows = [dict(zip(("site_name", "hr_id", "ship_cruise", "sonar", "year"), r)) for r in DEV + [MOCK_REPEAT]]
    P.MOCK_SITE_LIST.parent.mkdir(parents=True, exist_ok=True)
    with open(P.MOCK_SITE_LIST, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["site_name", "hr_id", "ship_cruise", "sonar", "year"]); w.writeheader(); w.writerows(rows)
    for p in root.rglob("*"):
        if p.is_file():
            p.chmod(0o440)
    rec = {"generated": P.utc_now(), "mock_root": str(root), "site_list": str(P.MOCK_SITE_LIST), "site_list_sha256": P.sha256_file(P.MOCK_SITE_LIST),
           "copies": copies, "n_copies": len(copies), "any_link": any(c["link"] for c in copies), "expected_repeat_rule": EXPECTED_REPEAT,
           "decoy": str(decoy), "swath": "development store OAK raw_lr_swath/<cruise>/ (read only; no network)"}
    P.write_json(P.REHEARSAL_DIR / "mock_layout.json", rec, mode=0o644)
    print(json.dumps({k: v for k, v in rec.items() if k != "copies"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
