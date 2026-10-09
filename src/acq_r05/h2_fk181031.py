"""ACQ-R05 ruling H-2 (Steve, 2026-10-09): inspect FK181031__MGDS_24618's 60 context source files (26 newly fetched,
34 from the June subset) — NCEI sonar sub-directory (fetch-manifest URL), MB-System format (file name), sonar model
from the Kongsberg .all datagram headers (EM model number field; every datagram carries it), and the depth range of
the soundings inside the pair's context mbgrid region (one streamed `mblist -MA -OXYZ -R` per file, bounded).
Rebuilds nothing.  Usage (Slurm): python -m src.acq_r05.h2_fk181031  -> h2_fk181031_files.{csv,json}
"""
from __future__ import annotations

import gzip
import json
import os
import shlex
import struct
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.acq_r05 import common as R
from src.acq_r05 import lattice as L
from src.acq_r05 import sources as S
from src.acq_r01 import common as C
from src.acq_r04 import common as R4
from src.acq_r04 import blocks as B4

PAIR = "FK181031__MGDS_24618"; CRUISE = "FK181031"
KONGSBERG = {122: "EM 122", 124: "EM 124", 300: "EM 300", 302: "EM 302", 304: "EM 304", 710: "EM 710", 712: "EM 712", 2040: "EM 2040", 3002: "EM 3002", 1002: "EM 1002", 120: "EM 120"}


def em_models(path_gz: Path, max_dgrams: int = 2000) -> dict:
    """EM model numbers seen in the first datagram headers of a Kongsberg .all file (4-byte length, STX, type, model uint16 LE)."""
    with gzip.open(path_gz, "rb") as f:
        buf = f.read(8 << 20)
    pos, models, types = 0, {}, {}
    n = 0
    while pos + 8 <= len(buf) and n < max_dgrams:
        ln = struct.unpack_from("<I", buf, pos)[0]
        if buf[pos + 4] != 0x02 or ln < 4 or ln > 1 << 20:
            break
        typ = buf[pos + 5]; model = struct.unpack_from("<H", buf, pos + 6)[0]
        models[model] = models.get(model, 0) + 1; types[typ] = types.get(typ, 0) + 1
        pos += 4 + ln; n += 1
    return {"models": models, "n_datagrams_read": n, "datagram_types": {hex(k): v for k, v in sorted(types.items())}}


def main(argv=None):
    b = json.loads((R.context_dir(PAIR) / "context.json").read_text())
    region = b["gridding"]["mbgrid_region"]; w, s, e, n = region["w"], region["s"], region["e"], region["n"]
    man = json.loads((C.RAW_SWATH_OAK / CRUISE / "fetch_manifest.json").read_text())
    entries = {f["filename"]: f for f in man["files"]}
    files = [f["name"] for f in b["source_files"]]
    wd = Path(os.environ.get("L_SCRATCH", "/tmp")) / "acq_r05_h2"; wd.mkdir(parents=True, exist_ok=True)
    loc = B4.decompress(C.RAW_SWATH_OAK / CRUISE, files, wd, workers=4)
    fmt = S.fmt_for(files[0])
    rows = {}
    for gz, ln in zip(files, loc):
        ent = entries[gz]; url = ent.get("url", "")
        rows[ln] = {"file": gz, "origin": "newly fetched 2026-10-09 (nav ∩ context)" if "acq_r05" in ent else "June 2026 subset (nav ∩ HR footprint 4 km)",
                    "ncei_subdir": "/".join(url.split("/MB/")[1].split("/")[:-1]) if "/MB/" in url else url.rsplit("/", 2)[-2],
                    "mb_format": fmt, "size_mb": round(int(ent["size"]) / 1e6, 1), **{f"hdr_{k}": v for k, v in em_models(C.RAW_SWATH_OAK / CRUISE / gz).items()}}
        m = rows[ln]["hdr_models"]; rows[ln]["sonar_model"] = ", ".join(f"{KONGSBERG.get(k, 'EM ' + str(k))} ({v} dgrams)" for k, v in sorted(m.items(), key=lambda t: -t[1]))
    # soundings inside the context mbgrid region, per file, one container call (as the coverage pass)
    script = "for f in " + " ".join(shlex.quote(x) for x in loc) + f"; do printf '\\n#F %s\\n' \"$f\"; mblist -F{fmt} -I \"$f\" -MA -OXYZ -R {w!r}/{e!r}/{s!r}/{n!r} || printf '\\n#ERR %s\\n' \"$f\"; done; printf '\\n#F __END__\\n'"
    (wd / "h2.sh").write_text(script + "\n")
    out_path = wd / "h2_out.txt"
    res, attempts, cmd = R4.mb_bounded(["sh", "h2.sh"], wd, timeout=3 * 3600, attempts=3, stdout_path=out_path)
    cur, buf = None, {}
    for line in out_path.read_text(errors="replace").splitlines():
        if line.startswith("#F "):
            cur = line[3:].strip(); buf.setdefault(cur, [])
        elif line.startswith("#ERR "):
            rows[line[5:].strip()]["mblist_error"] = True
        elif cur and cur != "__END__" and line.strip():
            buf[cur].append(line)
    for ln, lines in buf.items():
        if ln == "__END__":
            continue
        z = []
        for l in lines:
            p = l.split()
            if len(p) >= 3:
                try:
                    z.append(float(p[2]))
                except ValueError:
                    pass
        z = np.asarray(z)
        rows[ln].update({"n_soundings_in_region": int(z.size), "depth_min_m": float(np.min(-z)) if z.size else None, "depth_median_m": float(np.median(-z)) if z.size else None,
                         "depth_max_m": float(np.max(-z)) if z.size else None})
    df = pd.DataFrame(list(rows.values())).sort_values(["origin", "file"])
    df.to_csv(R.REPORT_DIR / "h2_fk181031_files.csv", index=False)
    summ = {"pair": PAIR, "region_wesn": [w, e, s, n], "mblist_command": cmd, "attempts": attempts, "n_files": len(df),
            "by_origin": {o: {"n": int(len(g)), "subdirs": g.ncei_subdir.value_counts().to_dict(), "sonar_models": g.sonar_model.value_counts().to_dict(),
                              "n_soundings_in_region": int(g.n_soundings_in_region.fillna(0).sum()),
                              "depth_min_m": float(g.depth_min_m.min()) if g.depth_min_m.notna().any() else None, "depth_max_m": float(g.depth_max_m.max()) if g.depth_max_m.notna().any() else None,
                              "median_of_file_medians_m": float(g.depth_median_m.median()) if g.depth_median_m.notna().any() else None}
                         for o, g in df.groupby("origin")},
            "lr_tif_median_depth_m": float(np.nanmedian(np.abs(L.read_lr(PAIR)))), "generated": R.utc_now(), "code_commit": R.git_commit()}
    (R.REPORT_DIR / "h2_fk181031.json").write_text(json.dumps(summ, indent=1, default=str))
    print(json.dumps(summ, indent=1, default=str)); print(df.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
