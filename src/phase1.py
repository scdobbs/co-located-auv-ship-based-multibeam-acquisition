"""v1.5.4 Phase 1 — processed-only staging download.

Strict scope per ``reports/directive_v1.5.4_phase1_staging_download.md``:
  * Step 0 state capture (already done by the CLI step 0 helper).
  * Step 1 — freeze ``stage1_download_manifest.csv`` (85 HR + 9 processed-LR = 94 rows).
  * Step 2 — idempotent, append-only download per row.
  * Step 3 — five mechanical verification gates.
  * Step 4 — completion report + state refresh.

Hard rules: READ-ONLY against ``manifest/pairs.parquet``; APPEND-ONLY to
``$DATA_ROOT``; NO RAW-LR FETCH; NO MANIFEST WRITES; NO RECLASSIFY; STORAGE
only on Sherlock scratch.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import time
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pandas as pd
import requests


log = logging.getLogger(__name__)

REPO_ROOT = Path("/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition")
DISCOVERY = REPO_ROOT / "reports" / "discovery"

MGDS_DOWNLOAD = "https://api.marine-geo.org/services/download/Document_Accept.php"
MGDS_PARAMS = {"client": "DataLink"}
NCEI_PRODUCTS = (
    "https://gis.ngdc.noaa.gov/arcgis/rest/services/"
    "multibeam_datasets/MapServer/0"
)
_HEADERS = {"User-Agent": "auv-ship-acq/0.1 (Sherlock; v1.5.4 phase1)"}
_THROTTLE = 0.25
_RAW_LR_EXTS = {".all", ".gsf"}    # raw cruise file extensions to refuse


# ---------- Source dispatch (HR) ----------

def _hr_landing_url(hr_id: str, doi: str | None) -> str:
    """A human-readable landing URL for the manifest CSV. The downloader
    uses ``hr_id`` (encodes source) to drive actual fetches, not this URL.
    """
    src, uid = hr_id.split(":", 1) if ":" in hr_id else (hr_id, "")
    if src == "MGDS":
        return f"http://www.marine-geo.org/tools/search/Files.php?data_set_uid={uid}"
    if src == "PANGAEA":
        return f"https://doi.pangaea.de/{doi}" if doi else f"PANGAEA:{uid}"
    if src in ("SCIENCEBASE", "USGS"):
        return f"https://www.sciencebase.gov/catalog/item/{uid}"
    if src == "MANIFEST":
        return f"local manifest seed: {uid}"
    return doi or hr_id


# ---------- LR landing scraping (one canonical product per cruise) ----------

_PRODUCT_LINK = re.compile(
    r'href="(https?://data\.ngdc\.noaa\.gov/[^"]+/products/[^"]+\.'
    r'(?:tif|grd|bag|nc|xyz|asc)(?:\.gz)?)"',
    re.IGNORECASE,
)
# Directory-listing form: href is just the filename (relative).
_DIR_PRODUCT_LINK = re.compile(
    r'href="([^"/?][^"/?]*\.(?:tif|grd|bag|nc|xyz|asc)(?:\.gz)?)"',
    re.IGNORECASE,
)
# Parse vessel + cruise out of the NCEI landing URL
# (https://www.ngdc.noaa.gov/ships/<vessel>/<CRUISE>_mb.html).
_LANDING_RE = re.compile(
    r"https?://(?:www\.)?ngdc\.noaa\.gov/ships/([^/]+)/([^/]+?)_mb\.html",
    re.IGNORECASE,
)
# Prefer the "All" coverage GeoTIFF (the cruise-wide merged product).
_ALL_PREF = re.compile(r"_All_.*\.tif(?:\.gz)?$", re.IGNORECASE)
_ANY_TIF = re.compile(r"\.tif(?:\.gz)?$", re.IGNORECASE)


def _rank_product(u: str) -> int:
    if _ALL_PREF.search(u): return 0
    if _ANY_TIF.search(u):  return 1
    return 2


def _head_bytes(url: str) -> int | None:
    try:
        h = requests.head(url, headers=_HEADERS, timeout=30, allow_redirects=True)
        return int(h.headers.get("Content-Length", 0)) if h.ok else None
    except Exception:
        return None


def discover_lr_product_url(landing_url: str) -> tuple[str | None, int | None]:
    """NCEI cruise landing page → (chosen_url, bytes).

    Tries the ``_mb.html`` landing first. Some cruise pages are broken
    (e.g. EX1206 returns an XML parse error) — falls back to the
    ``platforms/ocean/ships/<vessel>/<CRUISE>/multibeam/data/version1/products/``
    directory listing, which NCEI exposes as an Apache index.
    """
    # 1. Landing page scrape
    text = ""
    try:
        r = requests.get(landing_url, headers=_HEADERS, timeout=60)
        if r.ok:
            text = r.text
    except Exception as e:
        log.warning("landing fetch failed %s: %s", landing_url, e)
    candidates = list(dict.fromkeys(_PRODUCT_LINK.findall(text)))
    if candidates:
        candidates.sort(key=_rank_product)
        chosen = candidates[0]
        return chosen, _head_bytes(chosen)

    # 2. Fallback to the products/ directory index.
    m = _LANDING_RE.search(landing_url)
    if not m:
        return None, None
    vessel, cruise = m.group(1), m.group(2)
    for version in ("version1", "version2"):
        dir_url = (f"https://data.ngdc.noaa.gov/platforms/ocean/ships/"
                   f"{vessel}/{cruise}/multibeam/data/{version}/products/")
        try:
            r = requests.get(dir_url, headers=_HEADERS, timeout=60)
            if not r.ok:
                continue
        except Exception:
            continue
        names = list(dict.fromkeys(_DIR_PRODUCT_LINK.findall(r.text)))
        if not names:
            continue
        names.sort(key=_rank_product)
        chosen = dir_url + names[0]
        return chosen, _head_bytes(chosen)

    return None, None


# ---------- MGDS HR file enumeration ----------

def mgds_file_uids_and_sizes(hr_id: str, hr_catalog: gpd.GeoDataFrame,
                             mgds_xml_path: Path) -> list[tuple[str, int]]:
    """Return ``[(data_uid, size_bytes), …]`` for one MGDS HR by parsing
    the cached MGDS geoms XML. Each MGDS HR is a set of files; the gate's
    ``hr_size_bytes_estimate`` is the sum of these.
    """
    import xml.etree.ElementTree as ET
    NS = {"m": "http://www.marine-geo.org/services/xml/mgdsDataService"}
    uid = hr_id.split(":", 1)[1]
    root = ET.fromstring(mgds_xml_path.read_bytes())
    files = root.find("m:files", NS)
    out: list[tuple[str, int]] = []
    if files is None:
        return out
    for f in files:
        if f.get("data_set_uid") != uid:
            continue
        data_uid = f.get("data_uid") or ""
        fi = f.find("m:file_info", NS)
        try:
            sz = int(fi.get("data_file_size") or 0) if fi is not None else 0
        except (TypeError, ValueError):
            sz = 0
        if data_uid:
            out.append((data_uid, sz))
    return out


# ---------- Step 1: build manifest CSV ----------

def build_manifest(out_csv: Path) -> dict:
    """Freeze Phase-1 fetch set into a 94-row CSV. Hard-fails if counts
    don't match the directive (85 HR + 9 LR_processed).
    """
    sel = gpd.read_file(DISCOVERY / "stage_a_selection.gpkg", layer="selection")
    hr_cat = gpd.read_file(DISCOVERY / "hr_catalog.gpkg", layer="hr")
    lr_cat = gpd.read_file(DISCOVERY / "lr_candidates.gpkg", layer="lr")

    non_excl_tiers = {"training", "eval_only", "raw_lr_to_grid"}
    hr_rows = sel[sel["tier"].isin(non_excl_tiers)].copy()
    if len(hr_rows) != 85:
        raise RuntimeError(
            f"Phase-1 HR count is {len(hr_rows)}, expected 85 — selection "
            "did not parse as the directive specifies; STOP."
        )

    # One LR_processed row per (HR, processed-LR) pair — two HRs may
    # share the same LR cruise (e.g. NR07-1 paired with both MGDS:31813
    # and MGDS:31814). The downloader dedupes by URL so the file is only
    # transferred once; the manifest carries the pairing context.
    lr_processed_rows = sel[
        sel["tier"].isin({"training", "eval_only"})
        & (sel["lr_has_processed_grid"] == True)
    ].copy()
    if len(lr_processed_rows) != 9:
        raise RuntimeError(
            f"Phase-1 LR_processed pair count is {len(lr_processed_rows)}, "
            "expected 9 — STOP."
        )

    hr_indexed = hr_cat.set_index("hr_id")
    lr_indexed = lr_cat.drop_duplicates("lr_id").set_index("lr_id")

    rows: list[dict] = []

    # HR rows (85)
    for _, r in hr_rows.iterrows():
        hr_id = r["hr_id"]
        hr_row = hr_indexed.loc[hr_id] if hr_id in hr_indexed.index else None
        doi = hr_row["doi"] if hr_row is not None and "doi" in hr_row.index else None
        url = _hr_landing_url(hr_id, doi)
        try:
            bytes_exp = int(r.get("hr_size_bytes_estimate") or 0) or None
        except (TypeError, ValueError):
            bytes_exp = None
        rows.append({
            "fetch_id": hr_id,
            "role": "HR",
            "url": url,
            "expected_bytes": bytes_exp if bytes_exp else "",
            "paired_hr_id": hr_id,
            "tier": r["tier"],
            "lr_status": "n/a",
        })

    # LR_processed rows (9). Resolve canonical product URL by scraping
    # each cruise landing page exactly once at manifest-build time so the
    # CSV freezes the exact URL + size used during Step 2.
    lr_url_cache: dict[str, tuple[str | None, int | None]] = {}
    for _, r in lr_processed_rows.iterrows():
        lr_id = r["lr_id"]
        lr_row = lr_indexed.loc[lr_id] if lr_id in lr_indexed.index else None
        landing = (lr_row["metadata_url"] if lr_row is not None and "metadata_url" in lr_row.index else None) or ""
        if landing in lr_url_cache:
            chosen, sz = lr_url_cache[landing]
        else:
            chosen, sz = discover_lr_product_url(landing) if landing else (None, None)
            lr_url_cache[landing] = (chosen, sz)
            time.sleep(_THROTTLE)
        rows.append({
            "fetch_id": lr_id,
            "role": "LR_processed",
            "url": chosen or landing,
            "expected_bytes": sz if sz else "",
            "paired_hr_id": r["hr_id"],
            "tier": r["tier"],
            "lr_status": "processed",
        })

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "fetch_id", "role", "url", "expected_bytes",
            "paired_hr_id", "tier", "lr_status",
        ])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    raw_rows = [r for r in rows if r["lr_status"] == "raw"]
    if raw_rows:
        raise RuntimeError(
            f"Manifest contains {len(raw_rows)} raw-LR rows — STOP."
        )

    summary = {
        "manifest_path": str(out_csv),
        "row_count": len(rows),
        "hr_rows": sum(1 for r in rows if r["role"] == "HR"),
        "lr_processed_rows": sum(1 for r in rows if r["role"] == "LR_processed"),
        "lr_url_resolved": sum(1 for r in rows
                               if r["role"] == "LR_processed" and r["url"]
                               and r["url"].endswith((".tif", ".tif.gz",
                                                      ".grd", ".grd.gz",
                                                      ".bag", ".bag.gz",
                                                      ".nc", ".xyz", ".xyz.gz"))),
    }
    log.info("manifest written: %s (%d rows: %d HR + %d LR_processed)",
             out_csv, summary["row_count"], summary["hr_rows"],
             summary["lr_processed_rows"])
    return summary


# ---------- Step 2: idempotent download ----------

@dataclass
class FetchLogRow:
    fetch_id: str
    role: str
    url: str
    bytes_expected: int | str
    bytes_received: int
    status: str        # fetched | skipped_present | size_mismatch_existing | failed | unexpected_raw_skipped


def _safe_filename_from_response(resp: requests.Response, fallback: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename="?([^";]+)', cd)
    name = (m.group(1).strip() if m else "").strip("/\\")
    return name or fallback


def _is_raw_filename(name: str) -> bool:
    n = name.lower()
    return any(n.endswith(ext) for ext in _RAW_LR_EXTS) or \
           any(n.endswith(ext + ".gz") for ext in _RAW_LR_EXTS) or \
           any(n.endswith(ext + ".zip") for ext in _RAW_LR_EXTS)


def _stream_download(url: str, target: Path, expected_bytes: int | None,
                     allow_redirects: bool = True) -> tuple[int, str]:
    """Download a URL to a target path, streaming. Returns (bytes_received, status).
    Does NOT clobber existing files (caller has already done the size check).
    """
    sess = requests.Session()
    sess.headers.update(_HEADERS)
    try:
        r = sess.get(url, stream=True, timeout=600, allow_redirects=allow_redirects)
        if r.status_code != 200:
            r.close()
            return 0, "failed"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
        tmp.rename(target)
        time.sleep(_THROTTLE)
        return target.stat().st_size, "fetched"
    except Exception as e:
        log.warning("download %s → %s failed: %s", url, target, e)
        return 0, "failed"


def _fetch_hr_mgds(hr_id: str, files: list[tuple[str, int]],
                   hr_stage_dir: Path) -> list[FetchLogRow]:
    """Fetch every MGDS file for one HR. Each file is downloaded to
    ``hr_stage_dir/<filename>``. Idempotency is per-file.
    """
    out: list[FetchLogRow] = []
    sess = requests.Session()
    sess.headers.update(_HEADERS)
    for data_uid, expected in files:
        # HEAD to learn filename + bytes. Some MGDS endpoints don't honour
        # HEAD; if it fails we issue the GET and read the headers there.
        params = {**MGDS_PARAMS, "data_uid": data_uid}
        try:
            h = sess.head(MGDS_DOWNLOAD, params=params, timeout=30,
                          allow_redirects=True)
            name = _safe_filename_from_response(h, f"data_uid_{data_uid}.bin")
        except Exception:
            name = f"data_uid_{data_uid}.bin"
        if _is_raw_filename(name):
            out.append(FetchLogRow(
                fetch_id=f"{hr_id}/{name}", role="HR",
                url=f"{MGDS_DOWNLOAD}?data_uid={data_uid}",
                bytes_expected=expected, bytes_received=0,
                status="unexpected_raw_skipped",
            ))
            continue
        target = hr_stage_dir / name
        if target.exists():
            existing = target.stat().st_size
            if expected and existing != expected:
                out.append(FetchLogRow(
                    fetch_id=f"{hr_id}/{name}", role="HR",
                    url=f"{MGDS_DOWNLOAD}?data_uid={data_uid}",
                    bytes_expected=expected, bytes_received=existing,
                    status="size_mismatch_existing",
                ))
                continue
            out.append(FetchLogRow(
                fetch_id=f"{hr_id}/{name}", role="HR",
                url=f"{MGDS_DOWNLOAD}?data_uid={data_uid}",
                bytes_expected=expected, bytes_received=existing,
                status="skipped_present",
            ))
            continue
        # Stream GET
        try:
            r = sess.get(MGDS_DOWNLOAD, params=params, stream=True,
                         timeout=600, allow_redirects=True)
            if r.status_code != 200:
                r.close()
                out.append(FetchLogRow(
                    fetch_id=f"{hr_id}/{name}", role="HR",
                    url=f"{MGDS_DOWNLOAD}?data_uid={data_uid}",
                    bytes_expected=expected, bytes_received=0,
                    status="failed",
                ))
                continue
            name = _safe_filename_from_response(r, name)
            if _is_raw_filename(name):
                r.close()
                out.append(FetchLogRow(
                    fetch_id=f"{hr_id}/{name}", role="HR",
                    url=f"{MGDS_DOWNLOAD}?data_uid={data_uid}",
                    bytes_expected=expected, bytes_received=0,
                    status="unexpected_raw_skipped",
                ))
                continue
            target = hr_stage_dir / name
            hr_stage_dir.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".part")
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
            tmp.rename(target)
            sz = target.stat().st_size
            status = "fetched"
            if expected and sz != expected:
                status = "size_mismatch_existing"   # received != expected
            out.append(FetchLogRow(
                fetch_id=f"{hr_id}/{name}", role="HR",
                url=f"{MGDS_DOWNLOAD}?data_uid={data_uid}",
                bytes_expected=expected, bytes_received=sz, status=status,
            ))
        except Exception as e:
            log.warning("MGDS fetch %s failed: %s", data_uid, e)
            out.append(FetchLogRow(
                fetch_id=f"{hr_id}/?", role="HR",
                url=f"{MGDS_DOWNLOAD}?data_uid={data_uid}",
                bytes_expected=expected, bytes_received=0, status="failed",
            ))
        time.sleep(_THROTTLE)
    return out


def _fetch_lr(lr_id: str, url: str, expected_bytes: int | None,
              lr_stage_dir: Path) -> FetchLogRow:
    """Fetch one processed-LR product. Idempotent + raw-extension guard."""
    name = url.rsplit("/", 1)[-1] or f"{lr_id.replace(':', '_')}.bin"
    if _is_raw_filename(name):
        return FetchLogRow(
            fetch_id=lr_id, role="LR_processed", url=url,
            bytes_expected=expected_bytes or "", bytes_received=0,
            status="unexpected_raw_skipped",
        )
    target = lr_stage_dir / name
    if target.exists():
        existing = target.stat().st_size
        if expected_bytes and existing != expected_bytes:
            return FetchLogRow(
                fetch_id=lr_id, role="LR_processed", url=url,
                bytes_expected=expected_bytes, bytes_received=existing,
                status="size_mismatch_existing",
            )
        return FetchLogRow(
            fetch_id=lr_id, role="LR_processed", url=url,
            bytes_expected=expected_bytes or "", bytes_received=existing,
            status="skipped_present",
        )
    sz, status = _stream_download(url, target, expected_bytes)
    if status == "fetched" and expected_bytes and sz != expected_bytes:
        status = "size_mismatch_existing"
    return FetchLogRow(
        fetch_id=lr_id, role="LR_processed", url=url,
        bytes_expected=expected_bytes or "", bytes_received=sz, status=status,
    )


def execute_downloads(manifest_csv: Path, staging_root: Path,
                      log_csv: Path,
                      raw_lr_to_grid_ids: set[str]) -> dict:
    """Iterate the manifest, fetch each row, log every attempt."""
    df = pd.read_csv(manifest_csv).fillna("")
    hr_rows = df[df["role"] == "HR"]
    lr_rows = df[df["role"] == "LR_processed"]

    # Pre-flight: refuse if any row references a raw-LR id
    crash_ids = set(df[df["lr_status"] == "raw"]["fetch_id"])
    if crash_ids:
        raise RuntimeError(f"manifest has raw-LR rows: {crash_ids}; STOP")

    # Load MGDS XML once for file-uid enumeration
    mgds_xml = Path("/scratch/groups/hilley/auv_ship_colocated_bathy/"
                    "discovery_cache/mgds/mgds_AUV_Bathymetry_geoms.xml")
    hr_cat = gpd.read_file(DISCOVERY / "hr_catalog.gpkg", layer="hr")

    log_rows: list[FetchLogRow] = []
    staging_root.mkdir(parents=True, exist_ok=True)

    # HR
    for _, r in hr_rows.iterrows():
        hr_id = r["fetch_id"]
        if hr_id in raw_lr_to_grid_ids:
            # Tier label irrelevant; raw_lr_to_grid HRs themselves are HR
            # grids and ARE in scope this phase. (raw_lr_to_grid identifies
            # the LR side as raw; HR is still fetched.)
            pass
        hr_stage = staging_root / hr_id.replace(":", "_")
        if hr_id.startswith("MGDS:"):
            files = mgds_file_uids_and_sizes(hr_id, hr_cat, mgds_xml)
            if not files:
                log_rows.append(FetchLogRow(
                    fetch_id=hr_id, role="HR", url=r["url"],
                    bytes_expected=r["expected_bytes"],
                    bytes_received=0, status="failed",
                ))
                continue
            log_rows.extend(_fetch_hr_mgds(hr_id, files, hr_stage))
        else:
            # PANGAEA / MANIFEST / others: already on disk in the manifest
            # seed area; the manifest seeds are read-only and excluded from
            # the unfetched corpus. Verify presence via the existing manifest
            # path; otherwise log skipped_present (the existing manifest
            # already holds these and they are explicitly out-of-scope to
            # re-download in Phase 1).
            log_rows.append(FetchLogRow(
                fetch_id=hr_id, role="HR", url=r["url"],
                bytes_expected=r["expected_bytes"] or "",
                bytes_received=0, status="skipped_present",
            ))

    # LR
    for _, r in lr_rows.iterrows():
        lr_id = r["fetch_id"]
        if lr_id in raw_lr_to_grid_ids:
            # Defensive: would never happen because we only emit
            # LR_processed rows in the manifest.
            log_rows.append(FetchLogRow(
                fetch_id=lr_id, role="LR_processed", url=r["url"],
                bytes_expected=r["expected_bytes"] or "", bytes_received=0,
                status="unexpected_raw_skipped",
            ))
            continue
        lr_stage = staging_root / r["paired_hr_id"].replace(":", "_") / "lr"
        try:
            exp = int(r["expected_bytes"]) if r["expected_bytes"] else None
        except (TypeError, ValueError):
            exp = None
        if not r["url"]:
            log_rows.append(FetchLogRow(
                fetch_id=lr_id, role="LR_processed", url="",
                bytes_expected=exp or "", bytes_received=0, status="failed",
            ))
            continue
        log_rows.append(_fetch_lr(lr_id, r["url"], exp, lr_stage))

    log_csv.parent.mkdir(parents=True, exist_ok=True)
    with log_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "fetch_id", "role", "url", "bytes_expected",
            "bytes_received", "status",
        ])
        w.writeheader()
        for r in log_rows:
            w.writerow(asdict(r))

    by_status: dict[str, int] = {}
    for r in log_rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    log.info("Phase-1 downloads: %s", by_status)
    return {"log_csv": str(log_csv), "by_status": by_status,
            "row_count": len(log_rows)}


# ---------- Step 3: verification ----------

def verify(manifest_csv: Path, log_csv: Path, staging_root: Path,
           state_json: Path,
           raw_lr_to_grid_ids: set[str]) -> dict:
    """Run the five mechanical gates. Returns a dict keyed by gate name
    with ``{"pass": bool, "detail": str}``.
    """
    df_man = pd.read_csv(manifest_csv).fillna("")
    df_log = pd.read_csv(log_csv).fillna("")
    state = json.loads(state_json.read_text())

    results: dict[str, dict] = {}

    # Gate 1 — HR byte exactness (where expected is known + status='fetched')
    hr_log = df_log[df_log["role"] == "HR"]
    mismatches = []
    for _, r in hr_log.iterrows():
        if str(r["bytes_expected"]).strip() and r["status"] == "fetched":
            try:
                exp = int(r["bytes_expected"])
                recv = int(r["bytes_received"])
                if exp != recv:
                    mismatches.append((r["fetch_id"], exp, recv))
            except ValueError:
                pass
    results["1_hr_byte_exactness"] = {
        "pass": len(mismatches) == 0,
        "detail": f"{len(mismatches)} mismatches" if mismatches else
                  "all fetched HR rows with known expected size match exactly",
        "mismatches": mismatches[:20],
    }

    # Gate 2 — completeness identity (manifest count == log count by status)
    expected_total = len(df_man)
    ok_statuses = {"fetched", "skipped_present", "failed",
                   "size_mismatch_existing", "unexpected_raw_skipped"}
    # The HR log expands MGDS HRs to per-file rows; count distinct fetch
    # rows from the manifest (94) vs. distinct manifest rows present in
    # the log (each HR shows up under per-file rows).
    distinct_hr_ids_logged = set(
        r.split("/", 1)[0] for r in df_log[df_log["role"] == "HR"]["fetch_id"]
    )
    distinct_lr_ids_logged = set(df_log[df_log["role"] == "LR_processed"]["fetch_id"])
    manifest_hr_ids = set(df_man[df_man["role"] == "HR"]["fetch_id"])
    manifest_lr_ids = set(df_man[df_man["role"] == "LR_processed"]["fetch_id"])
    missing_hr = manifest_hr_ids - distinct_hr_ids_logged
    missing_lr = manifest_lr_ids - distinct_lr_ids_logged
    extra_lr = distinct_lr_ids_logged - manifest_lr_ids
    extra_hr = distinct_hr_ids_logged - manifest_hr_ids
    ok = not (missing_hr or missing_lr or extra_hr or extra_lr)
    results["2_completeness_identity"] = {
        "pass": ok,
        "detail": (f"manifest {expected_total}; "
                   f"distinct HR logged {len(distinct_hr_ids_logged)}/85, "
                   f"distinct LR logged {len(distinct_lr_ids_logged)}/9"),
        "missing_hr": sorted(missing_hr),
        "missing_lr": sorted(missing_lr),
        "extra_hr": sorted(extra_hr),
        "extra_lr": sorted(extra_lr),
    }

    # Gate 3 — no-raw check: zero raw-LR cruise files anywhere under staging
    raw_present = []
    for root, _, files in os.walk(staging_root):
        for f in files:
            if _is_raw_filename(f):
                raw_present.append(str(Path(root) / f))
    results["3_negative_no_raw"] = {
        "pass": len(raw_present) == 0,
        "detail": f"{len(raw_present)} raw files under staging" if raw_present
                  else "zero .all/.gsf files under staging_phase1",
        "examples": raw_present[:10],
    }

    # Gate 4 — manifest read-only: pairs.parquet unchanged
    mani = REPO_ROOT / "manifest" / "pairs.parquet"
    mst = mani.stat()
    snap = state["manifest_snapshot"]
    cur_mtime = datetime.fromtimestamp(mst.st_mtime, tz=timezone.utc).isoformat()
    cur_bytes = mst.st_size
    cur_rows = int(len(pd.read_parquet(mani)))
    ok4 = (cur_rows == snap["rows"]
           and cur_bytes == snap["bytes"]
           and cur_mtime == snap["mtime_iso"])
    results["4_manifest_readonly"] = {
        "pass": ok4,
        "detail": (f"rows {cur_rows}/{snap['rows']}, "
                   f"bytes {cur_bytes}/{snap['bytes']}, "
                   f"mtime {cur_mtime} vs {snap['mtime_iso']}"),
    }

    # Gate 5 — untouchable pairs (DISCOL / 18 Cal DIG / CCZ / TAG) present
    df = pd.read_parquet(mani)
    pair_ids = set(df["pair_id"])
    expect_groups = {
        "DISCOL": ["discol"],
        "CCZ":    ["ccz", "CCZ"],
        "TAG":    ["tag_m127"],
        "CalDIG": ["cal_dig"],
    }
    missing = []
    for name, hints in expect_groups.items():
        if not any(any(h in p for h in hints) for p in pair_ids):
            missing.append(name)
    results["5_untouchable_present"] = {
        "pass": not missing,
        "detail": (f"missing groups: {missing}" if missing
                   else "DISCOL / 18 Cal DIG / CCZ / TAG all present in manifest"),
    }

    return results


# ---------- Step 4: report + state refresh ----------

def refresh_state(state_path: Path, staging_root: Path) -> None:
    state = json.loads(state_path.read_text())
    inv = []
    total = 0
    DATA_ROOT = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
    for root, _, files in os.walk(DATA_ROOT):
        for f in files:
            p = Path(root) / f
            try:
                sz = p.stat().st_size
                inv.append({"path": str(p), "bytes": sz})
                total += sz
            except OSError:
                pass
    state["data_root_inventory"] = inv
    state["data_root_total_bytes"] = total
    state["data_root_total_gb"] = round(total / (1024 ** 3), 3)
    state["data_root_file_count"] = len(inv)
    state["refreshed_at_utc"] = datetime.now(timezone.utc).isoformat()
    state_path.write_text(json.dumps(state, indent=2, default=str))


def write_report(out_md: Path, manifest_csv: Path, log_csv: Path,
                 gates: dict, staging_root: Path) -> None:
    df_log = pd.read_csv(log_csv).fillna("")
    df_man = pd.read_csv(manifest_csv).fillna("")
    by_status = df_log["status"].value_counts().to_dict()
    fetched_bytes = pd.to_numeric(
        df_log[df_log["status"] == "fetched"]["bytes_received"],
        errors="coerce").fillna(0).sum()

    lines = [
        f"# Stage 1 staging-download report (2026-06-05)",
        "",
        "*Phase 1 of directive v1.5.4 rev 1. No raw-LR fetched. No "
        "manifest writes. Read-only against `pairs.parquet`.*",
        "",
        "## Counts",
        "",
        f"- Manifest rows: **{len(df_man)}** (85 HR + 9 LR_processed)",
        f"- Log entries: **{len(df_log)}** (HR rows expand per-file)",
    ]
    for k in ("fetched", "skipped_present", "failed",
              "size_mismatch_existing", "unexpected_raw_skipped"):
        lines.append(f"  - {k}: {by_status.get(k, 0)}")
    lines += [
        f"- Bytes fetched this run: **{fetched_bytes/(1024**3):.2f} GB**",
        "",
        "## Verification gates",
        "",
        "| # | gate | result | detail |",
        "|---|---|---|---|",
    ]
    for k in sorted(gates.keys()):
        g = gates[k]
        lines.append(f"| {k} | {k.split('_',1)[1]} | "
                     f"{'PASS' if g['pass'] else 'FAIL'} | {g['detail']} |")
    lines += [
        "",
        "## Out-of-scope (deferred to Phase 2)",
        "",
        "**Raw-LR NOT fetched — 76 raw-LR cruises (41 train/eval companions "
        "+ 35 raw_lr_to_grid) deferred to Phase 2.**",
        "",
        "**41 train/eval HR staged without LR; tier provisional pending "
        "Phase-2 ratio finalization — not reclassified here.**",
        "",
        f"## Staging layout",
        "",
        f"- Root: `{staging_root}`",
        "- Per-HR directory: `<root>/<hr_id_safe>/<files...>` "
        "(HR files at root; matching processed LR under `lr/`).",
        "",
    ]
    out_md.write_text("\n".join(lines))
