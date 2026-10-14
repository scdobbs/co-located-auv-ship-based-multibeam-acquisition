"""ACQ-R12 §4.3.2 — opened-path recorder for rehearsals (never used in phase5 mode).

Runs sealed_step1_p5.main(argv) unchanged in this process and records, until it returns or raises:
  * Python audit events: open (path, mode), os.rename / os.replace / os.remove / os.rmdir / os.mkdir / os.chmod /
    os.symlink / shutil.copyfile / shutil.rmtree / shutil.move, subprocess.Popen (argv head, cwd);
  * every call that reaches the acquisition guard (builtins.open, rasterio.open, numpy.load, geopandas / pyogrio readers,
    pandas.read_parquet), with the guard's verdict (passed / refused), by wrapping guard_p5._ORIG_CHECK.
Child processes of the product builder's process pool are not recorded (their paths are listed from the code).
The log is written gzip-compressed JSON lines to --out (a path without a candidate token).
Usage: python -m src.phase5.pathlog_p5 --out <log.jsonl.gz> -- <sealed_step1_p5 arguments>
"""
from __future__ import annotations

import gzip
import json
import sys
import time

EVENTS = {"open", "os.rename", "os.replace", "os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.symlink", "shutil.copyfile",
          "shutil.rmtree", "shutil.move", "subprocess.Popen"}
LOG: list = []


def _hook(ev, args):
    if ev not in EVENTS:
        return
    try:
        if ev == "open":
            p = args[0]
            if isinstance(p, int):
                return
            LOG.append({"ev": "open", "path": str(p), "mode": str(args[1]) if len(args) > 1 else ""})
        elif ev == "subprocess.Popen":
            argv = args[1] if len(args) > 1 else None
            head = " ".join(str(x) for x in (argv or [])[:8]) if isinstance(argv, (list, tuple)) else str(argv)[:200]
            LOG.append({"ev": "popen", "exe": str(args[0]), "argv": head[:400], "cwd": str(args[2]) if len(args) > 2 else ""})
        else:
            LOG.append({"ev": ev, "path": str(args[0]), "path2": str(args[1]) if len(args) > 1 and isinstance(args[1], (str, bytes)) else ""})
    except Exception:
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--out" not in argv or "--" not in argv:
        raise SystemExit(__doc__)
    out = argv[argv.index("--out") + 1]
    step_args = argv[argv.index("--") + 1:]
    if "phase5" in step_args and step_args[step_args.index("--mode") + 1] == "phase5":
        raise SystemExit("pathlog_p5 is for rehearsals only (phase5 mode refused)")
    sys.addaudithook(_hook)
    from src.phase5 import guard_p5 as GP
    orig = GP._ORIG_CHECK

    def logged(path):
        try:
            r = orig(path)
            LOG.append({"ev": "guard", "path": str(path), "verdict": "passed"}); return r
        except PermissionError:
            LOG.append({"ev": "guard", "path": str(path), "verdict": "refused"}); raise
    GP._ORIG_CHECK = logged
    from src.phase5 import sealed_step1_p5 as S
    t0 = time.time(); rc, err = None, None
    try:
        rc = S.main(step_args)
    except BaseException as e:            # recorded, then re-raised
        err = f"{type(e).__name__}: {str(e)[:300]}"
        raise
    finally:
        GP._ORIG_CHECK = orig
        with gzip.open(out, "wt") as f:
            f.write(json.dumps({"ev": "meta", "step_args": step_args, "rc": rc, "error": err, "wall_s": round(time.time() - t0, 1), "n_events": len(LOG)}) + "\n")
            for r in LOG:
                f.write(json.dumps(r) + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
