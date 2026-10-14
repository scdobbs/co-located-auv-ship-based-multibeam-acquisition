"""ACQ-R09 §2.3 — the Phase 5 admission on top of the acquisition guard, and its self-test.

The acquisition guard (src/acq_r01/common.py, unchanged) refuses, in every patched reader (builtins.open, rasterio.open,
numpy.load, geopandas.read_file, pyogrio.read_dataframe, pandas.read_parquet), any path under a `sealed_candidates_v3`
directory and any path containing a candidate id token (MGDS_18210, ...), plus the lockbox / confirmatory / sealed-swath
paths.  The patched readers look the module-global `_check` up at call time; `install_phase5_allowance` wraps it once:
a path the guard refuses is admitted only if

  * no lockbox id, no `harmonized_confirmatory` component and no sealed-cruise `raw_lr_swath/<cruise>` is in it (those
    are never admitted), and it is not under OAK `raw_hr/` (the September copies stay sealed);
  * every candidate-id token in it is an admitted token (the site list's ids; MGDS_31811, PANGAEA_958275, SEANOE_55744 and
    every other id stay refused);
  * if it has a `sealed_candidates_v3` component, the directory before it is the mode's sealed root and the component
    after it is an admitted token (so `.../sealed_candidates_v3/MGDS_31811/...` and the bare root stay refused);
  * it lies under the mode's sealed root / <admitted token>, the mode's output root or the node-local work root.

phase5 mode installs it after every lock has passed; rehearsal mode installs it on the mock root and mock ids (no
sign-off).  `selftest()` checks the reader refusals before any allowance and the admission rules as pure string checks on
the REAL `sealed_candidates_v3/<hr_id>/` names (no sealed file is touched), then removes the allowance.
ACQ-R12: `seal_tokens` (phase5_mock rehearsal only) makes the guard refuse the mock tokens exactly as it refuses the real
candidate ids, before the locks; `admitted` treats them like real tokens.  The record directory is never admitted.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from src.acq_r01 import common as C

_ORIG_CHECK = C._check
_P5 = {"tokens": (), "sealed_root": None, "roots": (), "reason": None}
_EXTRA = {"tokens": ()}                       # ACQ-R12 mock seal (phase5_mock rehearsal only)
REASONS = ("ACQ-R09 phase5 locks passed", "ACQ-R09 rehearsal (mock root, development data)", "ACQ-R09 guard self-test",
           "ACQ-R12 phase5_mock locks passed")
_DRIVER_PREFIX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:(?=/)")


def _norm(path) -> str:
    try:
        s = str(os.fspath(path)) if not isinstance(path, int) else ""
    except TypeError:
        s = str(path)
    s = _DRIVER_PREFIX.sub("", s)                     # NETCDF:/path, GTIFF_DIR:/path ...
    if not s:
        return s
    return os.path.normpath(os.path.abspath(s))


def _tok_in(s: str, tok: str) -> bool:
    return re.search(re.escape(tok) + r"(?![0-9A-Za-z])", s) is not None


def _base_check(path):
    """The acquisition guard, plus the ACQ-R12 mock seal: a path holding a sealed mock token is refused like a real one."""
    r = _ORIG_CHECK(path)
    if _EXTRA["tokens"]:
        s = _norm(path)
        hit = [t for t in _EXTRA["tokens"] if _tok_in(s, t)]
        if hit:
            raise PermissionError(f"SEALED CANDIDATE GUARD (ACQ-R12 mock seal): refusing to open {s} (candidate {hit[0]})")
    return r


def seal_tokens(tokens) -> dict:
    """phase5_mock only: seal the mock tokens before the guard self-test and the locks (no allowance may be installed)."""
    if _P5["tokens"]:
        raise PermissionError("mock seal refused: a Phase 5 allowance is installed")
    toks = tuple(str(t) for t in tokens)
    if not toks or any(not re.fullmatch(r"[A-Za-z]+_[0-9A-Za-z]+", t) for t in toks) or any(t in C.SEALED_CANDIDATE_TOKENS for t in toks):
        raise PermissionError(f"mock seal refused: tokens must be record-id tokens that are not real candidates: {toks}")
    _EXTRA["tokens"] = toks
    C._check = _base_check
    return {"sealed_mock_tokens": list(toks)}


def admitted(path) -> tuple:
    """(True, reason) if the Phase 5 allowance admits the path, else (False, reason).  Pure string logic."""
    toks, sroot, roots = _P5["tokens"], _P5["sealed_root"], _P5["roots"]
    if not toks:
        return False, "no Phase 5 allowance installed"
    s = _norm(path)
    parts = s.split("/")
    for l in C.LOCKBOX:
        if l in s:
            return False, f"lockbox id {l}"
    if "harmonized_confirmatory" in parts:
        return False, "harmonized_confirmatory"
    for c in C.SEALED_LR_CRUISES:
        if re.search(r"raw_lr_swath/" + re.escape(c) + r"(/|$)", s):
            return False, f"sealed swath {c}"
    if s.startswith(str(C.OAK / "raw_hr") + "/"):
        return False, "OAK raw_hr (September copies stay sealed)"
    bad = [t for t in tuple(C.SEALED_CANDIDATE_TOKENS) + _EXTRA["tokens"] if _tok_in(s, t) and t not in toks]
    if bad:
        return False, f"non-admitted candidate id {bad}"
    if C.SEALED_CANDIDATES_V3_DIRNAME in parts:
        i = parts.index(C.SEALED_CANDIDATES_V3_DIRNAME)
        if "/".join(parts[:i + 1]) != str(sroot):
            return False, f"sealed root {'/'.join(parts[:i + 1])} is not the mode's sealed root {sroot}"
        if i + 1 >= len(parts) or parts[i + 1] not in toks:
            return False, "the sealed root itself or a non-admitted directory under it"
    under = [str(Path(sroot) / t) for t in toks] + [str(r) for r in roots]
    if not any(s == u or s.startswith(u.rstrip("/") + "/") for u in under):
        return False, "outside the admitted roots"
    return True, "admitted"


def _check_p5(path):
    try:
        return _base_check(path)
    except PermissionError:
        ok, why = admitted(path)
        if ok:
            return path
        raise


def _install(tokens, sealed_root, roots, reason: str) -> dict:
    """Admit the listed tokens under the sealed root and the output / work roots.  Called once by the entry script in
    phase5 mode after every lock, or in rehearsal mode on the mock layout.  The reason must say which."""
    if not any(str(reason).startswith(r) for r in REASONS):
        raise PermissionError("Phase 5 allowance refused: the reason must state that the phase5 locks passed (or rehearsal / self-test)")
    if C.phase4_allowance() or C.r08b_allowance():
        raise PermissionError("Phase 5 allowance refused: a Phase 4 or ACQ-R08b allowance is installed in this process")
    toks = tuple(str(t) for t in tokens)
    if not toks or any(not re.fullmatch(r"[A-Za-z]+_[0-9A-Za-z]+", t) for t in toks):
        raise PermissionError(f"Phase 5 allowance refused: tokens must be record-id tokens: {toks}")
    _P5.update({"tokens": toks, "sealed_root": str(Path(sealed_root)), "roots": tuple(str(Path(r)) for r in roots), "reason": str(reason)})
    C._check = _check_p5
    return dict(_P5)


install_phase5_allowance = _install          # public name (the refusal tests replace it by a safety net; selftest uses _install)


def remove_phase5_allowance():
    _P5.update({"tokens": (), "sealed_root": None, "roots": (), "reason": None})
    C._check = _base_check if _EXTRA["tokens"] else _ORIG_CHECK


def allowance() -> dict:
    return dict(_P5)


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #
def _readers():
    import builtins
    import numpy as np
    import pandas as pd
    import rasterio
    import geopandas as gpd
    import pyogrio
    return {"builtins.open": lambda p: builtins.open(p, "rb"), "rasterio.open": rasterio.open, "numpy.load": np.load,
            "geopandas.read_file": gpd.read_file, "pyogrio.read_dataframe": pyogrio.read_dataframe, "pandas.read_parquet": pd.read_parquet}


def _probe(fn, p) -> str:
    try:
        fn(p); return "NOT BLOCKED"
    except PermissionError as e:
        return "blocked" if "GUARD" in str(e) else f"PermissionError not from guard: {str(e)[:80]}"
    except Exception as e:
        return f"NOT BLOCKED ({type(e).__name__})"


def selftest(site_tokens: list, mock_tokens: list, out_root: Path, work_root: Path, decoy_mock: Path | None = None, mock_root: Path | None = None) -> dict:
    """(1) reader refusals before any allowance: the real sealed root, every real candidate directory and a file in it, the
    mock root, each mock id directory, the lockbox / confirmatory paths; (2) admission rules as string checks on the real
    sealed_candidates_v3/<hr_id>/ names with the site tokens, then (3) on the mock root with the mock tokens; the allowance is
    removed after each.  Nothing under the real sealed root is opened in (2): only C._check is called on path strings."""
    if _P5["tokens"]:
        raise RuntimeError("guard self-test must run before any Phase 5 allowance")
    from src.phase5 import common_p5 as P
    readers = _readers()
    real = C.SEALED_CANDIDATES_V3; mock = Path(mock_root) if mock_root else P.MOCK_ROOT
    targets = {"real root": str(real), "mock root": str(mock)}
    for i in C.SEALED_CANDIDATE_IDS:
        t = i.replace(":", "_")
        targets[f"real dir:{t}"] = str(real / t); targets[f"real file:{t}"] = str(real / t / "grid.grd.gz")
        targets[f"elsewhere:{t}"] = f"/tmp/{t}/copy.tif"
    for t in mock_tokens:
        targets[f"mock dir:{t}"] = str(mock / t); targets[f"mock file:{t}"] = str(mock / t / "grid.grd.gz")
    for l in C.LOCKBOX:
        targets[f"lockbox:{l}"] = str(C.OAK / "harmonized" / l / "lr.tif")
    targets["confirmatory"] = str(C.HARMONIZED_CONFIRMATORY / "nu01a")
    rows = []
    for tn, p in targets.items():
        for rn, fn in readers.items():
            rows.append({"target": tn, "reader": rn, "result": _probe(fn, p)})
    before_ok = all(r["result"] == "blocked" for r in rows)

    def string_cases(tokens, sroot, cases):
        _install(tokens, sroot, [out_root, work_root], reason="ACQ-R09 guard self-test")
        res = []
        try:
            for name, p, want in cases:
                try:
                    C._check(p); got = "admitted"
                except PermissionError:
                    got = "refused"
                res.append({"case": name, "path": str(p), "expected": want, "got": got, "passed": got == want, "why": admitted(p)[1]})
        finally:
            remove_phase5_allowance()
        return res

    s1, t_non = site_tokens[0], "MGDS_31811"
    real_cases = [(f"real site file {s1}", real / s1 / "sentry040ppp_1m.grd.gz", "admitted")]
    real_cases += [(f"real site dir {t}", real / t, "admitted") for t in site_tokens]
    real_cases += [("real non-admitted id MGDS_31811", real / t_non / "sentry039_2x2_post.grd.gz", "refused"),
                   ("real non-admitted id PANGAEA_958275", real / "PANGAEA_958275" / "x.tif", "refused"),
                   ("real non-admitted id SEANOE_55744", real / "SEANOE_55744" / "57399.zip", "refused"),
                   ("real root itself", real, "refused"),
                   ("real root file", real / "SHA256SUMS", "refused"),
                   ("traversal to a non-admitted id", str(real / s1) + "/../" + t_non + "/x.grd", "refused"),
                   ("OAK raw_hr September copy", C.OAK / "raw_hr" / "MGDS_30368" / "MAUV_NESCA_All_Topo_1m.grd", "refused"),
                   ("lockbox id with an admitted token", out_root / "harmonized" / f"{s1}__AT42-03__MGDS_32007" / "lr.tif", "refused"),
                   ("output root, admitted token", out_root / "harmonized" / f"X__{s1}" / "hr.tif", "admitted"),
                   ("output root, non-admitted token", out_root / "harmonized" / f"X__{t_non}" / "hr.tif", "refused"),
                   ("work root, admitted token", work_root / f"X__{s1}" / "tile0.tif", "admitted"),
                   ("admitted token outside the roots", f"/tmp/{s1}/copy.tif", "refused"),
                   ("mock root under the real allowance", mock / (mock_tokens[0] if mock_tokens else "x") / "f.grd", "refused"),
                   ("GDAL driver prefix", f"NETCDF:{real / s1 / 'sentry041pp_1m.grd'}", "admitted")]
    real_res = string_cases(site_tokens, real, real_cases)
    mock_cases = [(f"mock id file {t}", mock / t / "f.grd.gz", "admitted") for t in mock_tokens]
    mock_cases += [("mock non-admitted decoy id", mock / "MGDS_99999" / "f.grd.gz", "refused"),
                   ("mock root itself", mock, "refused"),
                   ("real site under the mock allowance", real / s1 / "x.grd.gz", "refused")]
    mock_res = string_cases(mock_tokens, mock, mock_cases) if mock_tokens else []
    # after removal everything is refused again
    after = [{"target": tn, "reader": "rasterio.open", "result": _probe(readers["rasterio.open"], p)} for tn, p in targets.items()]
    after_ok = all(r["result"] == "blocked" for r in after)
    decoy = None
    if decoy_mock is not None and Path(decoy_mock).exists():
        decoy = {"path": str(decoy_mock), "before": _probe(readers["builtins.open"], decoy_mock)}
    out = {"reader_checks": {"n": len(rows), "n_blocked": sum(r["result"] == "blocked" for r in rows), "all_blocked": before_ok, "rows": rows},
           "real_name_admission": real_res, "mock_admission": mock_res,
           "after_removal": {"n": len(after), "all_blocked": after_ok},
           "decoy": decoy, "allowance_installed_at_end": bool(_P5["tokens"]),
           "guard_file_sha256": C.sha256_file(C.REPO / "src" / "acq_r01" / "common.py")}
    out["all_passed"] = bool(before_ok and after_ok and all(r["passed"] for r in real_res + mock_res) and not _P5["tokens"])
    return out
