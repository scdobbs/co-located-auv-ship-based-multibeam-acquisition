"""ACQ-R14 step 5: checks (directive section 5) on the packaged files only.
  1. license table (from the audit; pairs excluded on license);
  2. reproduction: examples/load_pair.py on three development pairs, one Phase 4 pair and one Phase 5 site (and, as a bonus,
     on every scored pair), each s_lr rho equal to the frozen value to 3 decimals;
  3. integrity: every raster in every zip opened with GDAL (rio_cogeo.cog_validate + rasterio), CRS = pair.json EPSG, nodata set;
     every pair.json sha256 matches its file; SHA256SUMS verifies;
  4. blindness: no sealed-only material / sealed paths; no restricted license;
  plus the size table. Writes reports_post_grl_review/ACQ-R14/check_results.json.

    python -B -m src.acq_r14.check [--repro-all]
"""
from __future__ import annotations
import argparse, io, json, os, re, subprocess, sys, zipfile
from collections import defaultdict
from pathlib import Path
import numpy as np, pandas as pd, rasterio
from rio_cogeo.cogeo import cog_validate
from . import common as C

REPRO_PAIRS = ["RR1506__MGDS_29779", "AR26__MGDS_31838", "discol_so242_1", "RC2511__MGDS_32239", "Escanaba__MGDS_30368"]
TEXT_EXT = {".json", ".csv", ".md", ".py", ".cff", ".txt", ""}
SEALED_PATTERNS = [re.compile(r"sealed_candidates_v3"), re.compile(r"/scratch/groups/hilley"), re.compile(r"/oak/stanford/groups/hilley"), re.compile(r"do[- ]not[- ]open", re.I)]


def integrity() -> dict:
    out = {"zips": {}, "n_rasters": 0, "n_cog_invalid": 0, "n_crs_mismatch": 0, "n_nodata_missing": 0, "n_sha_mismatch": 0, "problems": []}
    for z in sorted(C.PKG.glob("*.zip")):
        if z.name == "blind_tests.zip":
            continue
        rec = {"rasters": 0, "cog_invalid": [], "crs_mismatch": [], "nodata_missing": [], "sha_mismatch": [], "warnings": 0}
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            pj = json.loads(zf.read("pair.json"))
            epsg = pj["grids"]["crs_epsg"]
            for n in names:
                if n == "pair.json":
                    continue
                data = zf.read(n)
                if C.sha256_bytes(data) != pj["files"][n]["sha256"]:
                    rec["sha_mismatch"].append(n)
                if n.endswith(".tif"):
                    rec["rasters"] += 1
                    vp = f"/vsizip/{z}/{n}"
                    ok, errs, warns = cog_validate(vp, quiet=True)
                    rec["warnings"] += len(warns)
                    if not ok:
                        rec["cog_invalid"].append({"file": n, "errors": errs})
                    with rasterio.open(vp) as d:
                        if d.crs is None or d.crs.to_epsg() != epsg:
                            rec["crs_mismatch"].append({"file": n, "crs": str(d.crs), "expected": epsg})
                        if d.nodata is None:
                            rec["nodata_missing"].append(n)
        out["zips"][z.name] = rec
        out["n_rasters"] += rec["rasters"]
        for k in ("cog_invalid", "crs_mismatch", "nodata_missing", "sha_mismatch"):
            out[f"n_{k}"] += len(rec[k])
            if rec[k]:
                out["problems"].append({"zip": z.name, k: rec[k]})
        C.log(f"  integrity {z.name:52s} rasters={rec['rasters']:2d} cog_invalid={len(rec['cog_invalid'])} crs={len(rec['crs_mismatch'])} nodata={len(rec['nodata_missing'])} sha={len(rec['sha_mismatch'])}")
    # SHA256SUMS
    bad, n = [], 0
    for line in (C.PKG / "SHA256SUMS").read_text().splitlines():
        h, rel = line.split("  ", 1)
        n += 1
        if C.sha256(C.PKG / rel) != h:
            bad.append(rel)
    out["sha256sums"] = {"n": n, "bad": bad, "verified": not bad, "sha256_of_SHA256SUMS": C.sha256(C.PKG / "SHA256SUMS")}
    out["pass"] = (out["n_cog_invalid"] == 0 and out["n_crs_mismatch"] == 0 and out["n_nodata_missing"] == 0 and out["n_sha_mismatch"] == 0 and not bad)
    return out


def reproduction(repro_all: bool) -> dict:
    pairs = pd.read_parquet(C.PKG / "pairs.parquet")
    scored = pairs[pairs.in_corpus & pairs.rho_s_lr.notna()].pair_id.tolist()
    todo = REPRO_PAIRS + ([p for p in scored if p not in REPRO_PAIRS] if repro_all else [])
    res = {"required": {}, "all": {}, "n_required_pass": 0, "n_all_pass": 0, "n_all": 0}
    for pid in todo:
        r = subprocess.run([sys.executable, "-B", str(C.PKG / "examples" / "load_pair.py"), str(C.PKG), pid], capture_output=True, text=True, timeout=600)
        last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
        try:
            d = json.loads(last)
        except json.JSONDecodeError:
            d = {"pair": pid, "error": (r.stderr or r.stdout)[-600:], "match_3dp": False}
        d["returncode"] = r.returncode
        bucket = "required" if pid in REPRO_PAIRS else "all"
        res[bucket][pid] = d
        res["n_all"] += 1
        res["n_all_pass"] += int(bool(d.get("match_3dp")))
        if pid in REPRO_PAIRS:
            res["n_required_pass"] += int(bool(d.get("match_3dp")))
        C.log(f"  repro {pid:48s} view={d.get('view')} rho={d.get('rho_s_lr')} frozen={d.get('frozen')} match={d.get('match_3dp')}")
    res["pass"] = res["n_required_pass"] == len(REPRO_PAIRS) and res["n_all_pass"] == res["n_all"]
    return res


def blindness(lic: dict) -> dict:
    """Sealed-only material = files from the sealed roots or generated files that still point at them. The frozen blind-test
    documents (pre-registrations, deviation notes, results JSON) legitimately mention the sealing and archive paths; their
    mentions are listed as informational, not failures."""
    hits, info = [], []
    for p in sorted(C.PKG.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(C.PKG))
        frozen_doc = rel.startswith("blind_tests/") or p.name == "blind_tests.zip"
        if p.suffix in TEXT_EXT and p.suffix != "" and p.stat().st_size < 50_000_000:
            txt = p.read_text(errors="ignore")
            for rx in SEALED_PATTERNS:
                for m in rx.finditer(txt):
                    rec = {"file": rel, "pattern": rx.pattern, "context": txt[max(0, m.start() - 60):m.end() + 60].replace("\n", " ")}
                    (info if frozen_doc else hits).append(rec)
                    if len(hits) > 200:
                        break
        if p.suffix == ".zip" and p.name != "blind_tests.zip":
            with zipfile.ZipFile(p) as zf:
                for n in zf.namelist():
                    if n.endswith(".json") or n.endswith(".csv"):
                        txt = zf.read(n).decode(errors="ignore")
                        for rx in SEALED_PATTERNS:
                            for m in rx.finditer(txt):
                                hits.append({"file": f"{p.name}!{n}", "pattern": rx.pattern, "context": txt[max(0, m.start() - 60):m.end() + 60].replace("\n", " ")})
        if "sealed" in p.name.lower():
            hits.append({"file": str(p.relative_to(C.PKG)), "pattern": "file name", "context": p.name})
    restricted = [k for k, v in lic["datasets"].items() if v["redistribution"] == "no"]
    confirm = [k for k, v in lic["datasets"].items() if v["redistribution"] == "confirm"]
    return {"sealed_hits": hits[:200], "n_sealed_hits": len(hits), "frozen_doc_mentions": info[:200], "n_frozen_doc_mentions": len(info),
            "restricted_sources": restricted, "confirm_sources": confirm, "pass": (len(hits) == 0 and not restricted)}


def size_table(pairs: pd.DataFrame) -> dict:
    inc = pairs[pairs.in_corpus]
    rows = {}
    for g, d in inc.groupby("group"):
        rows[g] = {"n_pairs": int(len(d)), "total_gb": float(d.zip_bytes.sum() / 1e9), "largest_zip": d.loc[d.zip_bytes.idxmax(), "zip_file"], "largest_gb": float(d.zip_bytes.max() / 1e9)}
    top_files = [p for p in C.PKG.iterdir() if p.is_file()]
    all_files = [p for p in C.PKG.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in all_files)
    zen_files = top_files + [C.PKG / "examples" / "load_pair.py"]   # Zenodo upload: top-level files + load_pair.py (blind_tests/ is uploaded as blind_tests.zip)
    zen_total = sum(p.stat().st_size for p in zen_files)
    return {"groups": rows, "package": {"n_files_on_disk": len(all_files), "total_gb_on_disk": total / 1e9, "n_files_zenodo": len(zen_files), "total_gb_zenodo": zen_total / 1e9,
                                        "zenodo_limits_ok": len(zen_files) <= C.ZENODO_MAX_FILES and zen_total / 1e9 <= C.ZENODO_MAX_GB}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repro-all", action="store_true")
    a = ap.parse_args()
    lic = C.jload(C.LICENSE_AUDIT)
    pairs = pd.read_parquet(C.PKG / "pairs.parquet")
    out = {"generated": C.utcnow(), "package": str(C.PKG)}
    out["size"] = size_table(pairs)
    C.log(f"size: {json.dumps(out['size'])}")
    out["license"] = {"n_datasets": len(lic["datasets"]), "by_status": dict(pd.Series([v["redistribution"] for v in lic["datasets"].values()]).value_counts()),
                      "pairs_by_status": dict(pairs[pairs.in_corpus].pair_license_status.value_counts()), "pairs_excluded_on_license": [], "confirm_pairs": pairs[pairs.pair_license_status == "confirm"].pair_id.tolist()}
    out["reproduction"] = reproduction(a.repro_all)
    out["integrity"] = integrity()
    out["blindness"] = blindness(lic)
    out["pass"] = bool(out["reproduction"]["pass"] and out["integrity"]["pass"] and out["blindness"]["pass"] and out["size"]["package"]["zenodo_limits_ok"])
    C.jdump(out, C.RPT / "check_results.json")
    C.log(f"check: reproduction {out['reproduction']['pass']} ({out['reproduction']['n_required_pass']}/{len(REPRO_PAIRS)} required, {out['reproduction']['n_all_pass']}/{out['reproduction']['n_all']} all); "
          f"integrity {out['integrity']['pass']} ({out['integrity']['n_rasters']} rasters); blindness {out['blindness']['pass']}; limits {out['size']['package']['zenodo_limits_ok']} -> PASS={out['pass']}")
    if not out["pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
