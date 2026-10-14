"""ACQ-R12 §3 — the in-run leak check (last stage of sealed_step1_p5, under the locks and the allowance already in place).

Scope (Steve's ruling 2026-10-13, "records only"):
  * value search: every text file (common_p5.LEAK_TEXT_SUFFIXES / LEAK_TEXT_NAMES), the supplement's text (every cell),
    the run record about to be written, and the job's log files, searched for the printed forms of each site's G
    (V95_rel) and V95 — computed here in memory from the site's hr.tif / lr.tif / joint_valid.tif, never written —
    matched as whole numbers (not inside a longer number such as a coordinate; the ACQ-R11b rule);
  * key check: the forbidden keys (common_p5.forbidden_keys, incl. "v95" and the depth-statistic parts) in the records the
    step writes: the run record, and each site's site_record (without its file-name map), hr_selection, grid_record and
    sweep_record.  The frozen contract-v2.1 product files (ship_products_v2_1/) hold ship-vs-LR QA statistics by design;
    they are exempt from the key check (still value-searched) and are on the do-not-open list.
Only pass / fail and counts leave this module (no value, no matched text).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.phase5 import common_p5 as P
from src.phase5 import vcheck_p5 as VC


def forms(x: float) -> list:
    """Printed forms of a number: repr, 4-8 significant digits, fixed 2-8 decimals with >= 4 significant digits."""
    out = {repr(x)}
    for k in range(4, 9):
        out.add(f"{x:.{k}g}")
    for k in range(2, 9):
        s = f"{x:.{k}f}"
        if len(s.lstrip("-0.").replace(".", "")) >= 4:
            out.add(s)
    return sorted(out)


def _rx(f: str):
    return re.compile(r"(?<![0-9.])" + re.escape(f) + r"(?![0-9])")


def is_text(p: Path) -> bool:
    return p.is_file() and (p.suffix in P.LEAK_TEXT_SUFFIXES or p.name in P.LEAK_TEXT_NAMES)


def site_patterns(site_dir: Path) -> list:
    need = [site_dir / "hr.tif", site_dir / "lr.tif", site_dir / "joint_valid.tif"]
    if not all(x.exists() for x in need):
        return []
    s = VC.statistic(*need)
    if not s.get("n"):
        return []
    pats = [_rx(f) for name in ("v95", "v95_rel") for f in forms(float(s[name]))]
    del s
    return pats


def run_check(site_dirs: list, extra_files: list, texts: dict, records: list) -> dict:
    """site_dirs: final site directories; extra_files: other files this run wrote (logs, swath manifests, record-dir files);
    texts: {label: in-memory text} (run record, supplement); records: in-memory dicts for the key check (run record)."""
    pats, files = [], []
    for d in site_dirs:
        d = Path(d)
        pats += site_patterns(d)
        files += [p for p in sorted(d.rglob("*")) if is_text(p)]
    files += [Path(f) for f in extra_files if Path(f).exists() and Path(f).is_file()]
    files = list(dict.fromkeys(files))
    n_value_hits, hit_files = 0, 0
    bodies = [(str(f), f.read_text(errors="replace")) for f in files] + list(texts.items())
    for _, t in bodies:
        n = sum(1 for rx in pats if rx.search(t))
        n_value_hits += n; hit_files += bool(n)
    key_hits = []
    for r in records:
        key_hits += P.forbidden_keys(r)
    for d in site_dirs:
        for name in P.LEAK_KEY_RECORDS:
            f = Path(d) / name
            if f.exists():
                j = json.loads(f.read_text())
                if name == "site_record.json":
                    j = {k: v for k, v in j.items() if k != "files"}
                key_hits += [f"{Path(d).name}/{name}{h}" for h in P.forbidden_keys(j)]
    return {"passed": n_value_hits == 0 and not key_hits,
            "n_sites_with_patterns": sum(1 for d in site_dirs if (Path(d) / "hr.tif").exists()), "n_patterns": len(pats),
            "n_files_scanned": len(files), "n_texts_scanned": len(texts), "n_value_hits": n_value_hits, "n_files_with_value_hits": hit_files,
            "n_key_hits": len(key_hits), "key_hit_paths": key_hits[:20],
            "scope": "values: every text file / parquet text / log of the run; keys: run record + site/hr_selection/grid/sweep records (v2.1 products exempt; ruling 'records only')"}
