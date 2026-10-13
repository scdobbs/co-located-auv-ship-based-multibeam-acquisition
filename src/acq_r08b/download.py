"""ACQ-R08b step 1 — download the candidate high-resolution grids into the guarded root (directive §1–§2).

Order: guard self-test (before any download; must pass) → allowance → per candidate: ship-partner access check by file
listing where the directive asks for it (PANGAEA datasets: tab export; NCEI: autoindex) → download (MGDS FileDownloadServer
by data_uid; SEANOE data link from the landing page; PANGAEA grids are NOT downloaded when every ship partner is
restricted) → sha256 → files 0440, directories 2750 (group read only, setgid).  Nothing is opened.
"""
from __future__ import annotations

import json
import logging
import os
import re
import stat
import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from src.acq_r08b import common as K
from src.acq_r01 import common as C
from src.discovery import stage_b
from src.discovery.raw_lr_dryrun import data_dir_from_iso, resolve_data_dir
from src.discovery.stage_a5_subset import iter_cruise_files
from src.discovery import geoportal

log = logging.getLogger("acq_r08b.download")


def pangaea_access(pid: str) -> dict:
    """File-listing request only (the dataset's tab export); 401 = restricted."""
    r = requests.get(f"https://doi.pangaea.de/10.1594/PANGAEA.{pid}?format=textfile", headers=K.UA, timeout=120)
    n_urls = len(re.findall(r"https?://\S+\.(?:all|mb\d+|gsf|kmall)(?:\.gz)?", r.text)) if r.status_code == 200 else 0
    return {"pangaea_id": pid, "status": r.status_code, "restricted": r.status_code in (401, 403), "n_swath_urls_listed": n_urls,
            "note": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:160] if r.status_code != 200 else ""}


def ncei_access(cruise: str) -> dict:
    geoportal.fetch_geoportal_resolution(cruise, K.R08_CACHE / "geoportal")
    iso = data_dir_from_iso(cruise, K.R08_CACHE / "geoportal")
    url, note = resolve_data_dir(iso, K.R08_CACHE / "ncei_dirlist") if iso else (None, "no data directory in the ISO record")
    if not url:
        return {"cruise": cruise, "downloadable": False, "note": note}
    recs = iter_cruise_files(url, K.R08_CACHE / "ncei_dirlist")
    sw = [r for r in recs if r.kind == "swath"]; nv = [r for r in recs if r.kind == "nav"]
    return {"cruise": cruise, "downloadable": len(sw) > 0, "data_url": url, "n_swath_files": len(sw), "swath_gb": round(sum(r.bytes for r in sw) / 1e9, 2),
            "n_nav_files": len(nv), "note": ""}


def seanoe_links(landing: str) -> list[str]:
    """Data links on the SEANOE landing page (href extraction only, the documented-download-path precedent of CMGDS)."""
    r = requests.get(landing, headers=K.UA, timeout=120); r.raise_for_status()
    return sorted(set(u for u in re.findall(r'href="(https://www\.seanoe\.org/data/[^"]+/data/[^"]+)"', r.text)))


def _stream(url: str, target: Path) -> int:
    tmp = target.with_name(target.name + ".part")
    with requests.get(url, headers=K.UA, stream=True, timeout=900) as g:
        g.raise_for_status()
        with open(tmp, "wb") as fh:
            for ch in g.iter_content(1 << 20):
                fh.write(ch)
    tmp.rename(target)
    return target.stat().st_size


def seal(d: Path):
    for root, dirs, files in os.walk(d):
        for f in files:
            os.chmod(Path(root) / f, 0o440)
        for dd in dirs:
            os.chmod(Path(root) / dd, 0o2750)
    os.chmod(d, 0o2750)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    K.install_write_guard(); K.install_net_log(); K.OUT.mkdir(parents=True, exist_ok=True)
    st = K.guard_selftest()
    if not st["all_blocked"] or not st["control_opened"] or st["allowance_installed"]:
        raise SystemExit(f"guard self-test failed: {st['blocked']}/{st['probes']} blocked, control {st['control_opened']}")
    log.info("guard self-test: %d/%d probes blocked", st["blocked"], st["probes"])
    K.allow("download.py")
    K.SEALED.mkdir(parents=True, exist_ok=True); os.chmod(K.SEALED, 0o2750)
    cat = gpd.read_file(K.R08 / "pool_a" / "hr_catalog_mgds_raw.gpkg", layer="hr").set_index("hr_id")
    manifest = {"generated": K.now_iso(), "sealed_root": str(K.SEALED), "candidates": {}}
    for hid, c in K.CANDIDATES.items():
        d = K.SEALED / K.tok(hid)
        rec = {"hr_id": hid, "source": c["source"], "dir": str(d), "files": [], "access_checks": [], "downloaded": False, "skipped_reason": ""}
        # ship-partner access checks (file listing only)
        if c.get("lr_access_check"):
            rec["access_checks"] = [pangaea_access(p) for p in c["lr_access_check"]]
            if all(a["restricted"] for a in rec["access_checks"]):
                rec["skipped_reason"] = "every ship partner is restricted (HTTP 401 on the dataset file listing): no accessible independent ship data → grid not downloaded (directive §2)"
                manifest["candidates"][hid] = rec; log.info("%s: %s", hid, rec["skipped_reason"]); continue
        else:
            rec["access_checks"] = [ncei_access(c["lr"])]
        d.mkdir(parents=True, exist_ok=True)
        mp = d / "download_manifest.json"
        if mp.exists():
            rec = json.loads(mp.read_text()); rec["downloaded"] = True; manifest["candidates"][hid] = rec; log.info("%s: already downloaded (%d files)", hid, len(rec["files"])); continue
        if c["source"] == "MGDS":
            row = cat.loc[hid]
            rec.update({"doi": str(row.doi), "title": str(row.title), "catalog_format": str(row.format), "catalog_crs": str(row.native_crs), "catalog_res_m": float(row.native_res_m)})
            for uid in [u for u in str(row.file_ids).split(",") if u]:
                for attempt in range(3):
                    p = stage_b._download_file(uid, d)
                    if p is not None:
                        break
                    time.sleep(10 * (attempt + 1))
                rec["files"].append({"data_uid": uid, "name": p.name if p else None, "bytes": p.stat().st_size if p else 0, "sha256": C.sha256_file(p) if p else None,
                                     "url": f"{stage_b.FILEDOWNLOAD_BASE}?data_uid={uid}"})
        elif c["source"] == "SEANOE":
            rec.update({"doi": c["doi"], "landing": c["landing"]})
            links = seanoe_links(c["landing"]); rec["links_listed"] = links
            for u in links:
                name = u.rsplit("/", 1)[-1]; p = d / name
                nb = _stream(u, p) if not p.exists() else p.stat().st_size
                rec["files"].append({"url": u, "name": name, "bytes": nb, "sha256": C.sha256_file(p)})
        else:
            rec["skipped_reason"] = "PANGAEA grid: downloaded only if a ship partner is accessible (none is)"; manifest["candidates"][hid] = rec; continue
        rec["downloaded"] = any(f.get("bytes") for f in rec["files"]); rec["bytes"] = int(sum(f.get("bytes") or 0 for f in rec["files"]))
        (d / "download_manifest.json").write_text(json.dumps(rec, indent=1))
        with open(d / "SHA256SUMS", "w") as fh:
            for f in rec["files"]:
                if f.get("sha256"):
                    fh.write(f"{f['sha256']}  {f['name']}\n")
        seal(d)
        manifest["candidates"][hid] = rec
        log.info("%s: %d files, %.3f GB", hid, len(rec["files"]), rec["bytes"] / 1e9)
    manifest["not_processed"] = K.NOT_PROCESSED
    K.write_json(K.OUT / "download_manifest.json", manifest)
    with open(K.OUT / "SHA256SUMS_candidates", "w") as fh:
        for hid, rec in manifest["candidates"].items():
            for f in rec.get("files", []):
                if f.get("sha256"):
                    fh.write(f"{f['sha256']}  {K.tok(hid)}/{f['name']}\n")
    print(json.dumps({h: {"downloaded": r["downloaded"], "n_files": len(r.get("files", [])), "gb": round(r.get("bytes", 0) / 1e9, 3), "skipped": r.get("skipped_reason", "")} for h, r in manifest["candidates"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
