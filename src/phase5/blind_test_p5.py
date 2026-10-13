"""ACQ-R11b §3.3 — blindness test: no value of the vertical-datum statistic in any output, record or log of a run.

For every pair of a (rehearsal, development-data) run record that has harmonized files, the statistic is recomputed in
memory (vcheck_p5.statistic) and its printed forms (repr and 4-8 significant digits / fixed decimals of V95 and V95_rel)
are searched for as whole numbers (not inside a longer number such as a coordinate) in: the run record, the supplement (every cell as text), every text file under the pair directories
(json, geojson, csv, md, txt), the rehearsal directory's records, and the job logs given with --logs.  Also: no record key
holds a forbidden part (common_p5.forbidden_keys, incl. "v95"), and vcheck_p5.gate returns only booleans and words.
Only counts, file names and the format kind of a hit are written, never a value.
Usage: python -m src.phase5.blind_test_p5 --run-record <json> [--logs a.out,a.err]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from src.phase5 import common_p5 as P
from src.phase5 import vcheck_p5 as VC

TEXT_SUFFIXES = {".json", ".geojson", ".csv", ".md", ".txt", ".log", ".out", ".err"}


def forms(x: float) -> dict:
    out = {"repr": repr(x)}
    for k in range(4, 9):
        out[f"{k}g"] = f"{x:.{k}g}"
    for k in range(2, 9):
        s = f"{x:.{k}f}"
        if len(s.lstrip("-0.").replace(".", "")) >= 4:          # at least 4 significant digits (no short false hits)
            out[f"{k}f"] = s
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--run-record", required=True); ap.add_argument("--logs", default="")
    a = ap.parse_args(argv)
    rr_path = Path(a.run_record); rr = json.loads(rr_path.read_text()); out_root = Path(rr["out_root"])
    files = [rr_path] + [p for p in sorted(P.REHEARSAL_DIR.glob("*")) if p.is_file() and p.suffix in TEXT_SUFFIXES]
    files += [Path(x) for x in a.logs.split(",") if x]
    texts = {str(p): p.read_text(errors="replace") for p in files if p.exists()}
    if rr.get("supplement") and Path(rr["supplement"]).exists():
        import pyarrow.parquet as pq
        texts[rr["supplement"]] = json.dumps(pq.read_table(rr["supplement"]).to_pylist(), default=repr)
    pats, gate_keys, n_pairs = [], set(), 0
    for pid in rr["per_pair"]:
        d = out_root / "harmonized" / pid
        for p in sorted(d.rglob("*")):
            if p.is_file() and p.suffix in TEXT_SUFFIXES:
                texts[str(p)] = p.read_text(errors="replace")
        need = [d / "hr.tif", d / "lr.tif", d / "joint_valid.tif"]
        if not all(x.exists() for x in need):
            continue
        n_pairs += 1
        s = VC.statistic(*need)
        if s.get("n"):
            for name in ("v95", "v95_rel"):
                pats += [(pid, name, kind, f) for kind, f in forms(float(s[name])).items()]
        g = VC.gate(*need, P.T_G); gate_keys |= set(g)
        if any(isinstance(v, float) for v in g.values()):
            gate_keys.add("FLOAT VALUE RETURNED")
        del s
    hits = [{"file": fn, "pair": pid, "statistic": name, "format": kind}
            for fn, t in texts.items() for pid, name, kind, f in pats if re.search(r"(?<![0-9.])" + re.escape(f) + r"(?![0-9])", t)]
    # site records: every key except the "files" map (its keys are file names, e.g. the v2.1 product ship_median_regrid.tif)
    key_hits = P.forbidden_keys(rr) + [h for fn, t in texts.items() if fn.endswith("site_record.json")
                                       for h in P.forbidden_keys({k: v for k, v in json.loads(t).items() if k != "files"})]
    ok_gate = gate_keys <= {"vertical_consistent", "computed", "why"}
    res = {"generated": P.utc_now(), "run_record": str(rr_path), "run_record_sha256": P.sha256_file(rr_path), "n_pairs_checked": n_pairs,
           "n_patterns": len(pats), "n_files_scanned": len(texts), "files_scanned": sorted(texts), "value_hits": hits, "forbidden_key_hits": key_hits,
           "gate_keys": sorted(gate_keys), "gate_returns_no_number": ok_gate,
           "passed": bool(n_pairs > 0 and pats and not hits and not key_hits and ok_gate)}
    P.write_json(P.REHEARSAL_DIR / f"blind_test_{rr['run_tag']}.json", res, mode=0o644)
    print(f"blind test: {n_pairs} pairs, {len(pats)} patterns, {len(texts)} files; value hits {len(hits)}; key hits {len(key_hits)}; "
          f"gate keys {sorted(gate_keys)}; passed {res['passed']}")
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
