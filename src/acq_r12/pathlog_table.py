"""ACQ-R12 §4.3.2 — the phase5_mock opened-path logs (src/phase5/pathlog_p5.py) against the §1 write-path table.

Every logged path is normalized (pair ids -> <pair>, cruise -> <cruise>, roots -> <OUT>/<WORK>/<SWATH>/<SEALED>/<RECORD>/...)
and counted per (event kind, pattern, guard verdict).  Reported: write events (open w/a/x/+, rename, mkdir, chmod, copy,
rmtree, remove, symlink) with the root they land under; every guard refusal (must be none); any write under the record
directory (must be the run record only); any path carrying a pair token outside the admitted roots.
Usage: python -m src.acq_r12.pathlog_table <log.jsonl.gz> [...] --out <json>
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path

PAIRS = ("NA080__MGDS_31289", "KM0923__MGDS_31429")
TOKENS = ("MGDS_31289", "MGDS_31429")
CRUISES = ("NA080", "KM0923")
SCR = "/scratch/groups/hilley/auv_ship_colocated_bathy"
ROOTS = [(f"{SCR}/ACQ-R12/phase5_mock", "<OUT>"), (f"{SCR}/ACQ-R12/mock5/sealed_candidates_v3", "<SEALED>"), (f"{SCR}/ACQ-R12/raw_lr_swath", "<SWATH>"),
         (f"{SCR}/ACQ-R12/fetch_cache", "<FETCH_CACHE>"), ("/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/reports_post_grl_review/ACQ-R12/rehearsal/phase5_mock", "<RECORD>"),
         ("/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition", "<REPO>"), ("/oak/stanford/groups/hilley/auv_ship_colocated_bathy", "<OAK>"), (SCR, "<GSCR>")]
WRITE_EV = {"os.rename", "os.replace", "os.mkdir", "os.chmod", "shutil.copyfile", "shutil.rmtree", "os.remove", "os.rmdir", "os.symlink", "shutil.move"}


def norm(p: str) -> str:
    p = re.sub(r"^[A-Za-z_][A-Za-z0-9_]*:(?=/)", "", p)
    p = re.sub(r"/lscratch/[^/]+/\d+/acq_p5/phase5_mock", "<WORK>", p)
    p = re.sub(r"/lscratch/[^/]+/\d+", "<LSCRATCH>", p)
    for r, tag in ROOTS:
        if p.startswith(r):
            p = tag + p[len(r):]; break
    for x in PAIRS:
        p = p.replace(x, "<pair>")
    for x in TOKENS:
        p = p.replace(x, "<tok>")
    for x in CRUISES:
        p = re.sub(rf"(?<![A-Za-z0-9]){re.escape(x)}(?![A-Za-z0-9])", "<cruise>", p)
    p = re.sub(r"\d{8}T\d{6}Z", "<UTC>", p)
    p = re.sub(r"(?<=/)[^/]*\.(mb58|mb57|mb56|mb41|all|gz|fnv|inf|fbt)(\.gz)?$", "<swathfile>", p)
    p = re.sub(r"tile\d+\.tif", "tile<i>.tif", p)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    out = argv[argv.index("--out") + 1]; logs = [a for a in argv if a.endswith(".jsonl.gz")]
    res = {}
    for lg in logs:
        writes, reads, refused, record_writes, outside, popen = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
        meta = None; allowed = False; refused_before = 0; rel_names = Counter(); inner_admitted = Counter()
        for line in gzip.open(lg, "rt"):
            r = json.loads(line)
            if r["ev"] == "meta":
                meta = r; continue
            if r["ev"] == "popen":
                popen[(Path(r["exe"]).name, norm(r.get("cwd", "")), " ".join(norm(x) for x in r["argv"].split()[:3]))] += 1; continue
            p = r.get("path", ""); n = norm(p)
            if not allowed and r["ev"] == "os.mkdir" and n.startswith("<OUT>/harmonized/.staging/<pair>"):
                allowed = True                                  # first site directory: the allowance is installed from here on
            is_w = (r["ev"] == "open" and any(c in r.get("mode", "") for c in "wax+")) or r["ev"] in WRITE_EV
            if r["ev"] == "guard":
                if r["verdict"] == "refused":
                    if allowed and n.startswith("<SEALED>/<tok>/"):
                        inner_admitted[n] += 1                  # inner guard layer refuses sealed_candidates_v3/...; the Phase 5
                                                                # allowance layer admits <sealed root>/<admitted token> (run proceeded)
                    elif allowed:
                        refused[n] += 1                         # a refusal during the run (must be none)
                    else:
                        refused_before += 1                     # the self-test and site-path probes before the allowance
                continue
            if not re.sub(r"^[A-Za-z_][A-Za-z0-9_]*:(?=/)", "", p).startswith("/"):   # rmtree names relative to a directory fd
                rel_names[(r["ev"], n)] += 1; continue
            (writes if is_w else reads)[(r["ev"] if r["ev"] != "open" else ("open-w" if is_w else "open-r"), n)] += 1
            if is_w and n.startswith("<RECORD>"):
                record_writes[n] += 1
            if ("<pair>" in n or "<tok>" in n) and not n.startswith(("<OUT>", "<WORK>", "<SEALED>")):
                outside[(r["ev"], n)] += 1
        res[Path(lg).name] = {"meta": meta, "n_write_patterns": len(writes), "writes": sorted([list(k) + [v] for k, v in writes.items()]),
                              "n_read_patterns": len(reads), "reads": sorted([list(k) + [v] for k, v in reads.items()]),
                              "guard_refusals_during_run": dict(refused), "inner_refusals_admitted_by_allowance": dict(inner_admitted), "guard_refusals_before_allowance (probes)": refused_before,
                              "dirfd_relative_events": sorted([list(k) + [v] for k, v in rel_names.items()]), "record_dir_writes": dict(record_writes),
                              "token_paths_outside_admitted_roots": sorted([list(k) + [v] for k, v in outside.items()]),
                              "subprocesses": sorted([list(k) + [v] for k, v in popen.items()])}
    Path(out).write_text(json.dumps(res, indent=1))
    for k, v in res.items():
        print(f"{k}: meta rc={v['meta']['rc']} err={str(v['meta']['error'])[:80]}; write patterns {v['n_write_patterns']}, read patterns {v['n_read_patterns']}; "
              f"probe refusals before allowance {v['guard_refusals_before_allowance (probes)']}; refusals during run {sum(v['guard_refusals_during_run'].values())}; record-dir writes {v['record_dir_writes']}; token paths outside roots {len(v['token_paths_outside_admitted_roots'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
