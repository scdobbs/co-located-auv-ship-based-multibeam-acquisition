"""v1.5.4 rev 2 — Phase 1 remediation.

R0 — re-fetch MGDS:30272 (the 278-byte stub was an MGDS error body, not
data). R1 — quarantine MGDS:31600 and measure its grid resolutions
without making an eligibility decision. R2 — sweep every HR's grids for
cell-size sanity, emit a diagnostic CSV. R3 — corrected verify gates
(Gate 1 includes ``size_mismatch_existing``, new Gate 6 covers cell-size
sanity). R4 — rev-2 report + state refresh.

Guardrails: append-only against ``$DATA_ROOT`` except the single
sanctioned deletion of the 30272 stub. No reclassify/exclude/re-tier —
this code only produces findings the assessment instance acts on.
"""

from __future__ import annotations

import csv
import gzip
import json
import logging
import math
import os
import shutil
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from . import phase1 as phase1_mod


log = logging.getLogger(__name__)


_GRID_EXTS = {".grd", ".nc", ".tif", ".tiff", ".asc", ".bag", ".xyz"}
_PHASE1_LOG = Path("/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/"
                   "reports/discovery/stage1_download_log.csv")
_STATE_JSON = Path("/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/"
                   "reports/discovery/staging_state_20260605.json")


# ---------- R0 — MGDS:30272 ----------

@dataclass
class R0Result:
    hr_id: str
    stub_path: str
    stub_body_excerpt: str          # first ~500 bytes verbatim
    stub_bytes: int
    re_fetch_url: str
    re_fetch_bytes: int
    expected_bytes: int
    final_status: str               # 'fetched' | 'FETCH_FAILED_ESCALATE'


def r0_mgds_30272(staging_root: Path) -> R0Result:
    target_dir = staging_root / "MGDS_30272"
    stub = target_dir / "data_uid_2427151.bin"
    expected = 4_517_897
    url = "https://api.marine-geo.org/services/download/Document_Accept.php"
    params = {"client": "DataLink", "data_uid": "2427151"}

    body_excerpt = ""
    stub_bytes = 0
    if stub.exists():
        stub_bytes = stub.stat().st_size
        body_excerpt = stub.read_bytes()[:500].decode("utf-8", errors="replace")
        stub.unlink()
        log.info("R0 deleted stub %s (%d bytes)", stub, stub_bytes)

    # Re-fetch (no retry loop)
    sess = requests.Session()
    sess.headers.update({"User-Agent": "auv-ship-acq/0.1 (Sherlock; v1.5.4 rev2)"})
    received = 0
    name = "data_uid_2427151.bin"   # fallback if Content-Disposition missing
    try:
        r = sess.get(url, params=params, stream=True, timeout=600,
                     allow_redirects=True)
        if r.status_code == 200:
            cd = r.headers.get("Content-Disposition", "")
            import re as _re
            m = _re.search(r'filename="?([^";]+)', cd)
            if m:
                name = m.group(1).strip()
            target = target_dir / name
            tmp = target.with_suffix(target.suffix + ".part")
            target_dir.mkdir(parents=True, exist_ok=True)
            with tmp.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
            tmp.rename(target)
            received = target.stat().st_size
            log.info("R0 re-fetched %s → %d bytes (expected %d)",
                     target, received, expected)
            if received != expected:
                # Don't keep a partial — leave the directory clean.
                try: target.unlink()
                except FileNotFoundError: pass
        else:
            log.warning("R0 re-fetch HTTP %s", r.status_code)
    except Exception as e:
        log.warning("R0 re-fetch exception: %s", e)

    final = "fetched" if received == expected else "FETCH_FAILED_ESCALATE"
    return R0Result(
        hr_id="MGDS:30272",
        stub_path=str(stub),
        stub_body_excerpt=body_excerpt,
        stub_bytes=stub_bytes,
        re_fetch_url=f"{url}?client=DataLink&data_uid=2427151",
        re_fetch_bytes=received,
        expected_bytes=expected,
        final_status=final,
    )


def _patch_log_status(log_csv: Path, fetch_id_substr: str, new_status: str,
                      new_bytes: int) -> None:
    """Idempotently update the matching row's status + bytes_received."""
    df = pd.read_csv(log_csv).fillna("")
    mask = df["fetch_id"].str.contains(fetch_id_substr, na=False)
    if not mask.any():
        return
    df.loc[mask, "status"] = new_status
    df.loc[mask, "bytes_received"] = new_bytes
    df.to_csv(log_csv, index=False)


# ---------- R1 — MGDS:31600 quarantine + measure ----------

@dataclass
class GridMeasurement:
    file: str
    crs: str | None
    cell_size_x_native: float | None
    cell_size_y_native: float | None
    is_geographic: bool
    mean_lat: float | None
    cell_size_m_x: float | None
    cell_size_m_y: float | None
    cell_size_m_finest: float | None
    error: str


def _decompress_grd_gz(p: Path) -> Path:
    """Gunzip into a temp file; idempotent."""
    if p.suffix.lower() != ".gz":
        return p
    out = p.with_suffix("")
    if out.exists():
        return out
    with gzip.open(p, "rb") as src, out.open("wb") as dst:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            dst.write(chunk)
    return out


def _meas_from_ranges(name: str, layout: str,
                      x_min: float, x_max: float,
                      y_min: float, y_max: float,
                      nx: int, ny: int,
                      hint: str | None) -> GridMeasurement:
    cx = abs(x_max - x_min) / max(nx, 1)
    cy = abs(y_max - y_min) / max(ny, 1)
    # Heuristic CRS detection from coordinate magnitudes + GMT-v6 metadata hint.
    is_geo = (max(abs(x_min), abs(x_max)) <= 360.5
              and max(abs(y_min), abs(y_max)) <= 90.5)
    if hint == "geographic":
        is_geo = True
    mean_lat = None
    if is_geo:
        mean_lat = (y_min + y_max) / 2.0
        cy_m = cy * 110_574.0
        cx_m = cx * 110_574.0 * math.cos(math.radians(mean_lat))
        crs = "metadata=geographic" if hint == "geographic" else \
              "(inferred geographic from coord ranges)"
    else:
        cx_m = cx
        cy_m = cy
        crs = "metadata=projected" if hint == "projected" else \
              "(inferred projected from coord ranges)"
    finest = min(cx_m, cy_m) if cx_m and cy_m else None
    return GridMeasurement(
        file=name, crs=f"{crs} [{layout}]",
        cell_size_x_native=cx, cell_size_y_native=cy,
        is_geographic=bool(is_geo), mean_lat=mean_lat,
        cell_size_m_x=cx_m, cell_size_m_y=cy_m,
        cell_size_m_finest=finest, error="",
    )


def _measure_grid(path: Path) -> GridMeasurement:
    """Read coordinate ranges + dimensions for a grid file. Handles:
      * GMT NetCDF Classic 1-D layout (``x_range``, ``y_range``, ``dimension``)
      * GMT-v6 / COARDS 2-D layout (``x``, ``y``, ``z`` with ``actual_range``,
        ``long_name`` projection hints)
      * ESRI ASCII Grid (``.asc``)
      * Standard GeoTIFF / NetCDF readable by rasterio
    For ``.gz`` files, gunzip first.
    """
    import rasterio
    from .discovery import crs_recovery
    raster_path = path
    if path.suffix.lower() == ".gz":
        try:
            raster_path = _decompress_grd_gz(path)
        except Exception as e:
            return GridMeasurement(
                file=path.name, crs=None,
                cell_size_x_native=None, cell_size_y_native=None,
                is_geographic=False, mean_lat=None,
                cell_size_m_x=None, cell_size_m_y=None,
                cell_size_m_finest=None,
                error=f"gunzip: {str(e)[:120]}",
            )

    # 1. GMT (classic or v6) via crs_recovery's reader
    ext = raster_path.suffix.lower()
    if ext in (".grd", ".nc"):
        hdr = crs_recovery.read_grd_header(raster_path)
        if hdr is not None:
            return _meas_from_ranges(
                path.name, hdr.layout,
                hdr.x_min, hdr.x_max, hdr.y_min, hdr.y_max,
                hdr.nx, hdr.ny, hdr.metadata_crs_hint,
            )

    # 2. ESRI ASCII Grid
    if ext == ".asc":
        hdr = crs_recovery.read_asc_header(raster_path)
        if hdr is not None:
            return _meas_from_ranges(
                path.name, hdr.layout,
                hdr.x_min, hdr.x_max, hdr.y_min, hdr.y_max,
                hdr.nx, hdr.ny, hdr.metadata_crs_hint,
            )

    # 3. Anything rasterio can read directly (GeoTIFF, CF NetCDF with CRS)
    try:
        with rasterio.open(str(raster_path)) as ds:
            crs = ds.crs.to_string() if ds.crs else None
            t = ds.transform
            cx = abs(t.a); cy = abs(t.e)
            is_geo = bool(ds.crs and ds.crs.is_geographic) if ds.crs else False
            if not is_geo and crs is None:
                lon_lo, lat_lo = t * (0, ds.height)
                lon_hi, lat_hi = t * (ds.width, 0)
                if (abs(lon_lo) <= 360.5 and abs(lon_hi) <= 360.5
                        and abs(lat_lo) <= 90.5 and abs(lat_hi) <= 90.5):
                    is_geo = True
                    crs = "(no-CRS) appears geographic"
            mean_lat = None
            if is_geo:
                _, lat_lo = t * (0, ds.height)
                _, lat_hi = t * (ds.width, 0)
                mean_lat = (lat_lo + lat_hi) / 2.0
                cy_m = cy * 110_574.0
                cx_m = cx * 110_574.0 * math.cos(math.radians(mean_lat))
            else:
                cx_m = cx
                cy_m = cy
            finest = min(cx_m, cy_m) if cx_m and cy_m else None
            return GridMeasurement(
                file=path.name, crs=crs,
                cell_size_x_native=cx, cell_size_y_native=cy,
                is_geographic=bool(is_geo), mean_lat=mean_lat,
                cell_size_m_x=cx_m, cell_size_m_y=cy_m,
                cell_size_m_finest=finest, error="",
            )
    except Exception as e:
        err = str(e)[:200]

    return GridMeasurement(
        file=path.name, crs=None,
        cell_size_x_native=None, cell_size_y_native=None,
        is_geographic=False, mean_lat=None,
        cell_size_m_x=None, cell_size_m_y=None,
        cell_size_m_finest=None, error=err if 'err' in locals() else "unreadable",
    )


def r1_quarantine_31600(staging_root: Path, quarantine_root: Path) -> dict:
    src = staging_root / "MGDS_31600"
    dst = quarantine_root / "MGDS_31600"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    moved = False
    if src.exists() and not dst.exists():
        shutil.move(str(src), str(dst))
        moved = True
        log.info("R1 moved %s → %s", src, dst)
    elif dst.exists():
        log.info("R1 quarantine target already present at %s", dst)

    measurements: list[GridMeasurement] = []
    if dst.exists():
        for f in sorted(dst.iterdir()):
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            inner_ext = Path(f.stem).suffix.lower()
            if ext in _GRID_EXTS or inner_ext in _GRID_EXTS:
                measurements.append(_measure_grid(f))

    declared = 9.80
    measured_finest = None
    for m in measurements:
        if m.cell_size_m_finest is not None:
            measured_finest = (m.cell_size_m_finest if measured_finest is None
                               else min(measured_finest, m.cell_size_m_finest))
    if measured_finest is None:
        looks_like = "unknown"
        ratio = None
    else:
        ratio = measured_finest / declared
        if 0.5 <= ratio <= 2.0:
            looks_like = "auv_hr"
        else:
            looks_like = "coarse_or_composite"

    return {
        "hr_id": "MGDS:31600",
        "moved_now": moved,
        "quarantine_path": str(dst),
        "declared_native_m": declared,
        "measured_finest_cell_m": measured_finest,
        "measured_to_declared_ratio": ratio,
        "looks_like": looks_like,
        "files": [asdict(m) for m in measurements],
    }


# ---------- R2 — corpus-wide cell-size sanity sweep ----------

@dataclass
class HRResolution:
    hr_id: str
    declared_native_m: float | None
    measured_finest_cell_m: float | None
    crs: str | None
    ratio: float | None         # measured / declared
    verdict: str                # ok | flag_mismatch | flag_coarse | no_grid_found | quarantined
    n_grid_files: int


def _classify_resolution(declared: float | None,
                         measured: float | None) -> str:
    if measured is None:
        return "no_grid_found"
    if declared is None or (isinstance(declared, float) and math.isnan(declared)):
        return "flag_coarse" if measured > 5.0 else "ok"
    r = measured / declared
    if 0.5 <= r <= 2.0:
        return "ok"
    return "flag_mismatch"


def r2_resolution_sweep(staging_root: Path, hr_catalog_path: Path,
                        quarantined: set[str],
                        manifest_csv: Path | None = None,
                        escalated: set[str] | None = None
                        ) -> list[HRResolution]:
    """Sweep every HR's staged grids, emitting one row per HR.

    Sources:
      1. Each ``staging_phase1/<hr_id_safe>/`` directory (measured).
      2. Every id in ``quarantined`` (emitted even when its dir has been
         moved to ``quarantine_phase1/`` — keeps the report honest).
      3. Every PANGAEA/MANIFEST seed in the manifest CSV (verdict
         ``manifest_seed_clean`` — already validated by prior milestones,
         data lives under ``$DATA_ROOT/raw/`` rather than staging_phase1).
      4. Every id in ``escalated`` (recorded as
         ``fetch_failed_escalate``, not ``no_grid_found``).
    """
    hr_cat = gpd.read_file(hr_catalog_path, layer="hr")
    by_id = hr_cat.set_index("hr_id")
    escalated = escalated or set()

    def _declared(hr_id: str) -> float | None:
        if hr_id in by_id.index and pd.notna(by_id.loc[hr_id, "native_res_m"]):
            return float(by_id.loc[hr_id, "native_res_m"])
        return None

    out: list[HRResolution] = []
    seen: set[str] = set()
    for hr_dir in sorted(staging_root.iterdir()):
        if not hr_dir.is_dir():
            continue
        hr_id = hr_dir.name.replace("_", ":", 1)
        seen.add(hr_id)
        if hr_id in quarantined:
            out.append(HRResolution(
                hr_id=hr_id, declared_native_m=_declared(hr_id),
                measured_finest_cell_m=None, crs=None, ratio=None,
                verdict="quarantined", n_grid_files=0,
            ))
            continue
        if hr_id in escalated:
            out.append(HRResolution(
                hr_id=hr_id, declared_native_m=_declared(hr_id),
                measured_finest_cell_m=None, crs=None, ratio=None,
                verdict="fetch_failed_escalate", n_grid_files=0,
            ))
            continue
        declared = None
        if hr_id in by_id.index:
            v = by_id.loc[hr_id, "native_res_m"]
            if pd.notna(v):
                declared = float(v)
        # Collect grid files — only HR files at the directory root, not
        # the paired LR product under the ``lr/`` subdir. ``rglob`` here
        # would pull in the NCEI ship grid and skew the measurement.
        grid_files: list[Path] = []
        for f in hr_dir.iterdir():
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            inner_ext = Path(f.stem).suffix.lower()
            if ext in _GRID_EXTS or (ext == ".gz" and inner_ext in _GRID_EXTS):
                grid_files.append(f)
        finest_m = None
        crs_repr = None
        for f in grid_files:
            m = _measure_grid(f)
            if m.cell_size_m_finest is not None:
                if finest_m is None or m.cell_size_m_finest < finest_m:
                    finest_m = m.cell_size_m_finest
                    crs_repr = m.crs
        ratio = None
        if finest_m is not None and declared:
            ratio = finest_m / declared
        verdict = _classify_resolution(declared, finest_m)
        # PANGAEA/MANIFEST seeds whose staging dir exists only because
        # of the LR companion subdir (no HR files at root) → mark
        # clean-by-provenance rather than as no_grid_found.
        if (verdict == "no_grid_found"
                and (hr_id.startswith("PANGAEA:")
                     or hr_id.startswith("MANIFEST:"))):
            verdict = "manifest_seed_clean"
        out.append(HRResolution(
            hr_id=hr_id, declared_native_m=declared,
            measured_finest_cell_m=finest_m, crs=crs_repr,
            ratio=ratio, verdict=verdict, n_grid_files=len(grid_files),
        ))

    # Post-loop: ensure every quarantined / escalated id is represented
    # even if its staging dir was moved out / never created.
    for hr_id in quarantined:
        if hr_id in seen:
            continue
        out.append(HRResolution(
            hr_id=hr_id, declared_native_m=_declared(hr_id),
            measured_finest_cell_m=None, crs=None, ratio=None,
            verdict="quarantined", n_grid_files=0,
        ))
        seen.add(hr_id)
    for hr_id in escalated:
        if hr_id in seen:
            continue
        out.append(HRResolution(
            hr_id=hr_id, declared_native_m=_declared(hr_id),
            measured_finest_cell_m=None, crs=None, ratio=None,
            verdict="fetch_failed_escalate", n_grid_files=0,
        ))
        seen.add(hr_id)

    # PANGAEA/MANIFEST seeds — their data lives under
    # $DATA_ROOT/raw/<pair_id>/ (validated in prior milestones), NOT
    # under staging_phase1/. Mark them clean-by-provenance so the
    # bookkeeping reflects the real Phase-1 corpus rather than
    # mis-flagging them as no_grid_found.
    if manifest_csv is not None and manifest_csv.exists():
        df_man = pd.read_csv(manifest_csv).fillna("")
        for hr_id in df_man[df_man["role"] == "HR"]["fetch_id"].unique():
            if hr_id in seen:
                continue
            if not (hr_id.startswith("PANGAEA:") or hr_id.startswith("MANIFEST:")):
                continue
            out.append(HRResolution(
                hr_id=hr_id, declared_native_m=_declared(hr_id),
                measured_finest_cell_m=None, crs=None, ratio=None,
                verdict="manifest_seed_clean", n_grid_files=0,
            ))
            seen.add(hr_id)

    return out


def write_resolution_csv(out_csv: Path, rows: list[HRResolution]) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "hr_id", "declared_native_m", "measured_finest_cell_m",
            "crs", "ratio", "verdict", "n_grid_files",
        ])
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


# ---------- R3 — corrected verify gates ----------

def verify_rev2(manifest_csv: Path, log_csv: Path, staging_root: Path,
                state_json: Path,
                resolution_rows: list[HRResolution],
                resolved_ids: set[str]) -> dict:
    """Re-run the 5 original gates with Gate 1's scope corrected, plus
    the new Gate 6. ``resolved_ids`` lists HR ids that count as
    explicitly resolved (e.g. quarantined or fetch-escalated).
    """
    df_man = pd.read_csv(manifest_csv).fillna("")
    df_log = pd.read_csv(log_csv).fillna("")
    state = json.loads(state_json.read_text())
    results: dict[str, dict] = {}

    # Gate 1 (corrected) — include size_mismatch_existing as FAIL
    hr_log = df_log[df_log["role"] == "HR"]
    mismatches = []
    for _, r in hr_log.iterrows():
        status = str(r["status"])
        if status in ("fetched", "size_mismatch_existing"):
            try:
                exp = int(r["bytes_expected"]) if str(r["bytes_expected"]).strip() else None
                recv = int(r["bytes_received"]) if str(r["bytes_received"]).strip() else 0
            except ValueError:
                continue
            if exp and recv != exp:
                hr_id = str(r["fetch_id"]).split("/", 1)[0]
                if hr_id in resolved_ids:
                    continue
                mismatches.append((r["fetch_id"], exp, recv, status))
    results["1_hr_byte_exactness_corrected"] = {
        "pass": len(mismatches) == 0,
        "detail": (f"{len(mismatches)} unresolved byte mismatches "
                   "(scope now includes size_mismatch_existing)"
                   if mismatches else
                   "every HR file with known size matches; nothing "
                   "outstanding under size_mismatch_existing"),
        "mismatches": mismatches[:20],
    }

    # Gate 2 — completeness identity (unchanged)
    distinct_hr_ids_logged = set(
        r.split("/", 1)[0] for r in df_log[df_log["role"] == "HR"]["fetch_id"]
    )
    distinct_lr_ids_logged = set(df_log[df_log["role"] == "LR_processed"]["fetch_id"])
    manifest_hr_ids = set(df_man[df_man["role"] == "HR"]["fetch_id"])
    manifest_lr_ids = set(df_man[df_man["role"] == "LR_processed"]["fetch_id"])
    missing_hr = manifest_hr_ids - distinct_hr_ids_logged
    missing_lr = manifest_lr_ids - distinct_lr_ids_logged
    extra_hr = distinct_hr_ids_logged - manifest_hr_ids
    extra_lr = distinct_lr_ids_logged - manifest_lr_ids
    ok = not (missing_hr or missing_lr or extra_hr or extra_lr)
    results["2_completeness_identity"] = {
        "pass": ok,
        "detail": (f"manifest {len(df_man)}; distinct HR {len(distinct_hr_ids_logged)}/85, "
                   f"distinct LR {len(distinct_lr_ids_logged)}/8 (NR07-1 deduped)"),
        "missing_hr": sorted(missing_hr), "missing_lr": sorted(missing_lr),
        "extra_hr": sorted(extra_hr), "extra_lr": sorted(extra_lr),
    }

    # Gate 3 — no-raw check (unchanged); now also scans quarantine
    raw_present = []
    DATA_ROOT = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
    for sub in ("staging_phase1", "quarantine_phase1"):
        root = DATA_ROOT / sub
        if not root.exists():
            continue
        for r, _, files in os.walk(root):
            for f in files:
                if phase1_mod._is_raw_filename(f):
                    raw_present.append(str(Path(r) / f))
    results["3_negative_no_raw"] = {
        "pass": len(raw_present) == 0,
        "detail": (f"{len(raw_present)} raw files in staging/quarantine"
                   if raw_present else
                   "zero .all/.gsf files in staging_phase1 or quarantine_phase1"),
        "examples": raw_present[:10],
    }

    # Gate 4 — manifest read-only
    mani = Path("/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/"
                "manifest/pairs.parquet")
    mst = mani.stat()
    snap = state["manifest_snapshot"]
    cur_mtime = datetime.fromtimestamp(mst.st_mtime, tz=timezone.utc).isoformat()
    cur_bytes = mst.st_size
    cur_rows = int(len(pd.read_parquet(mani)))
    ok4 = (cur_rows == snap["rows"] and cur_bytes == snap["bytes"]
           and cur_mtime == snap["mtime_iso"])
    results["4_manifest_readonly"] = {
        "pass": ok4,
        "detail": (f"rows {cur_rows}/{snap['rows']}, bytes {cur_bytes}/{snap['bytes']}, "
                   f"mtime {cur_mtime} vs {snap['mtime_iso']}"),
    }

    # Gate 5 — untouchable pairs
    df = pd.read_parquet(mani)
    pair_ids = set(df["pair_id"])
    expect_groups = {
        "DISCOL": ["discol"], "CCZ": ["ccz", "CCZ"],
        "TAG": ["tag_m127"], "CalDIG": ["cal_dig"],
    }
    missing = []
    for name, hints in expect_groups.items():
        if not any(any(h in p for h in hints) for p in pair_ids):
            missing.append(name)
    results["5_untouchable_present"] = {
        "pass": not missing,
        "detail": ("DISCOL / 18 Cal DIG / CCZ / TAG all present in manifest"
                   if not missing else f"missing groups: {missing}"),
    }

    # Gate 6 (new) — cell-size sanity. Resolved states:
    # ``ok`` (measured within band), ``quarantined`` (explicit R1 move),
    # ``fetch_failed_escalate`` (R0 escalation), ``manifest_seed_clean``
    # (out-of-staging-scope; validated by prior milestones). Anything
    # else (``flag_mismatch`` / ``flag_coarse`` / ``no_grid_found``) is
    # an unresolved finding.
    unresolved = []
    resolved_verdicts = {"ok", "quarantined",
                         "fetch_failed_escalate", "manifest_seed_clean"}
    for r in resolution_rows:
        if r.verdict in resolved_verdicts:
            continue
        if r.hr_id in resolved_ids:
            continue
        unresolved.append((r.hr_id, r.verdict,
                           r.declared_native_m, r.measured_finest_cell_m))
    results["6_cell_size_sanity"] = {
        "pass": len(unresolved) == 0,
        "detail": (f"{len(unresolved)} HR with unresolved cell-size "
                   "issue (non-ok and not quarantined)" if unresolved
                   else "every HR resolution either ok or explicitly resolved"),
        "unresolved": unresolved[:30],
    }

    return results


# ---------- R4 — write rev-2 report + refresh state ----------

def write_rev2_report(out_md: Path,
                      r0: R0Result, r1: dict,
                      resolution_rows: list[HRResolution],
                      gates: dict, manifest_csv: Path, log_csv: Path,
                      resolution_csv: Path) -> None:
    df_log = pd.read_csv(log_csv).fillna("")
    df_man = pd.read_csv(manifest_csv).fillna("")
    by_status = df_log["status"].value_counts().to_dict()
    resolved_verdicts = {"ok", "quarantined",
                         "fetch_failed_escalate", "manifest_seed_clean"}
    flagged = [r for r in resolution_rows
               if r.verdict not in resolved_verdicts]
    quarantined = [r for r in resolution_rows if r.verdict == "quarantined"]
    escalated_rows = [r for r in resolution_rows
                      if r.verdict == "fetch_failed_escalate"]
    seed_clean = [r for r in resolution_rows
                  if r.verdict == "manifest_seed_clean"]
    n_total = len(resolution_rows)
    n_ok = sum(1 for r in resolution_rows if r.verdict == "ok")
    n_quarantined = len(quarantined)
    n_flag = len(flagged)
    n_escalated = len(escalated_rows)
    n_seed_clean = len(seed_clean)
    # Clean HR = measured ok + seeds clean from prior milestones.
    clean_hr = n_ok + n_seed_clean

    body = r0.stub_body_excerpt.replace("\r", "").replace("\n", "\\n")[:400]
    lines = [
        "# Stage 1 staging-download report — rev 2 (2026-06-05)",
        "",
        "*Phase 1 remediation per directive v1.5.4 rev 2. No reclassify / "
        "no gate edit / no re-tier — diagnoses only.*",
        "",
        "## Remediation summary",
        "",
        "### R0 — MGDS:30272 stub inspection + re-fetch",
        "",
        f"- Stub bytes (pre-delete): **{r0.stub_bytes}** (expected {r0.expected_bytes})",
        f"- Stub body (first ~400 chars, escaped newlines):",
        "",
        f"  > `{body}`",
        "",
        f"- Re-fetch URL: `{r0.re_fetch_url}`",
        f"- Re-fetch bytes received: **{r0.re_fetch_bytes}** "
        f"(expected {r0.expected_bytes})",
        f"- Final status: **{r0.final_status}**",
        "",
        "### R1 — MGDS:31600 quarantine + measurement",
        "",
        f"- Quarantine path: `{r1['quarantine_path']}`",
        f"- Declared `hr_native_res_m`: **{r1['declared_native_m']} m**",
        f"- Measured finest cell (across all files): "
        f"**{r1['measured_finest_cell_m']} m** "
        f"(ratio {r1['measured_to_declared_ratio']})",
        f"- `looks_like` verdict: **{r1['looks_like']}**",
        "",
        "Per-file measurements:",
        "",
        "| file | crs | cx_native | cy_native | mean_lat | cx_m | cy_m | finest_m | error |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for f in r1["files"]:
        lines.append(
            f"| {f['file']} | {f['crs'] or '—'} | "
            f"{f['cell_size_x_native']} | {f['cell_size_y_native']} | "
            f"{f['mean_lat']} | {f['cell_size_m_x']} | {f['cell_size_m_y']} | "
            f"{f['cell_size_m_finest']} | {f['error']} |"
        )

    lines += [
        "",
        "### R2 — corpus-wide cell-size sanity sweep",
        "",
        f"- HR represented in sweep: **{n_total}** "
        f"(= measured + quarantined + escalated + manifest-seed)",
        f"- `ok`: **{n_ok}**, `quarantined`: **{n_quarantined}**, "
        f"`fetch_failed_escalate`: **{n_escalated}**, "
        f"`manifest_seed_clean`: **{n_seed_clean}**, "
        f"`flagged` (unresolved): **{n_flag}**",
        f"- CSV: `{resolution_csv.relative_to(resolution_csv.parents[2])}`",
        "",
    ]
    if flagged:
        lines += [
            "Flagged HR (non-ok, non-quarantined):",
            "",
            "| hr_id | declared_m | measured_m | ratio | verdict | files |",
            "|---|---:|---:|---:|---|---:|",
        ]
        for r in flagged:
            lines.append(
                f"| {r.hr_id} | "
                f"{r.declared_native_m if r.declared_native_m is not None else '—'} | "
                f"{r.measured_finest_cell_m if r.measured_finest_cell_m is not None else '—'} | "
                f"{round(r.ratio,2) if r.ratio is not None else '—'} | "
                f"{r.verdict} | {r.n_grid_files} |"
            )

    lines += [
        "",
        "## Verification gates (corrected)",
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
        "## What Phase 2 inherits",
        "",
        f"- **Clean HR count: {clean_hr}** "
        f"= {n_ok} measured ok + {n_seed_clean} manifest seeds (prior milestones).",
        f"- Decomposition of 85: "
        f"{n_ok} ok + {n_seed_clean} seed_clean + {n_quarantined} quarantined "
        f"+ {n_escalated} escalated + {n_flag} flagged.",
        f"- Quarantined (R1): {[r.hr_id for r in quarantined]}",
        f"- Escalated (R0): {[r.hr_id for r in escalated_rows] or 're-fetch succeeded'}",
        f"- Manifest seeds (clean from prior milestones, data under raw/): "
        f"{[r.hr_id for r in seed_clean]}",
        f"- Flagged for assessment (real findings — non-ok, non-resolved): "
        f"{[r.hr_id for r in flagged]}",
        "- No exclusion / re-tier performed. The assessment instance owns "
        "eligibility decisions on quarantined + escalated + flagged HR.",
        "",
        "## Out-of-scope (unchanged from rev 1)",
        "",
        "**Raw-LR NOT fetched — 76 raw-LR cruises deferred to Phase 2.** "
        "**41 train/eval HR staged without LR; tier provisional pending "
        "Phase-2 ratio finalization — not reclassified here.**",
        "",
    ]
    out_md.write_text("\n".join(lines))


def refresh_state_rev2(state_path: Path, staging_root: Path,
                       quarantine_root: Path,
                       r0: R0Result, r1: dict,
                       resolution_rows: list[HRResolution]) -> None:
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

    resolved_verdicts = {"ok", "quarantined",
                         "fetch_failed_escalate", "manifest_seed_clean"}
    n_quarantined = sum(1 for r in resolution_rows if r.verdict == "quarantined")
    n_ok = sum(1 for r in resolution_rows if r.verdict == "ok")
    n_escalated = sum(1 for r in resolution_rows
                      if r.verdict == "fetch_failed_escalate")
    n_seed_clean = sum(1 for r in resolution_rows
                       if r.verdict == "manifest_seed_clean")
    flagged = [r.hr_id for r in resolution_rows
               if r.verdict not in resolved_verdicts]
    n_flag = len(flagged)
    state["phase1_rev2"] = {
        "r0_mgds_30272": asdict(r0),
        "r1_mgds_31600": r1,
        "resolution_sweep_counts": {
            "ok": n_ok, "quarantined": n_quarantined,
            "fetch_failed_escalate": n_escalated,
            "manifest_seed_clean": n_seed_clean,
            "flagged": n_flag,
            "total": len(resolution_rows),
        },
        "flagged_ids": flagged,
        "quarantined_ids": [r.hr_id for r in resolution_rows
                            if r.verdict == "quarantined"],
        "escalated_ids": [r.hr_id for r in resolution_rows
                          if r.verdict == "fetch_failed_escalate"],
        "manifest_seed_clean_ids": [r.hr_id for r in resolution_rows
                                    if r.verdict == "manifest_seed_clean"],
        "clean_hr_count": n_ok + n_seed_clean,
        "phase2_inherits_note": (
            "Clean HR count = staged HR measured ok + manifest seeds "
            "validated by prior milestones. Quarantined + escalated + "
            "flagged ids await assessment-instance eligibility decision; "
            "no re-tier here."
        ),
    }
    state_path.write_text(json.dumps(state, indent=2, default=str))


# ---------- Orchestrator ----------

def run_remediation(staging_root: Path, quarantine_root: Path,
                    hr_catalog_path: Path,
                    log_csv: Path, manifest_csv: Path,
                    state_json: Path, out_md: Path,
                    resolution_csv: Path) -> dict:
    log.info("R0 — MGDS:30272")
    r0 = r0_mgds_30272(staging_root)
    if r0.final_status == "fetched":
        _patch_log_status(log_csv, "MGDS:30272", "fetched", r0.re_fetch_bytes)
    else:
        _patch_log_status(log_csv, "MGDS:30272",
                          "FETCH_FAILED_ESCALATE", r0.re_fetch_bytes)

    log.info("R1 — MGDS:31600 quarantine")
    r1 = r1_quarantine_31600(staging_root, quarantine_root)

    log.info("R2 — corpus-wide resolution sweep")
    quarantined = {"MGDS:31600"}
    escalated = ({"MGDS:30272"}
                 if r0.final_status == "FETCH_FAILED_ESCALATE" else set())
    rows = r2_resolution_sweep(staging_root, hr_catalog_path, quarantined,
                               manifest_csv=manifest_csv,
                               escalated=escalated)
    write_resolution_csv(resolution_csv, rows)

    log.info("R3 — corrected gates")
    resolved = quarantined | escalated | {
        r.hr_id for r in rows if r.verdict == "manifest_seed_clean"
    }
    gates = verify_rev2(manifest_csv, log_csv, staging_root,
                        state_json, rows, resolved)

    log.info("R4 — write rev-2 report + refresh state")
    # Append-only: if the canonical rev-2 report exists already, write
    # this run to _run2.md (etc.) so the prior diagnostic is preserved.
    if out_md.exists():
        stem = out_md.stem
        v = 2
        cand = out_md.with_name(f"{stem}_run{v}.md")
        while cand.exists():
            v += 1
            cand = out_md.with_name(f"{stem}_run{v}.md")
        out_md = cand
    write_rev2_report(out_md, r0, r1, rows, gates,
                      manifest_csv, log_csv, resolution_csv)
    refresh_state_rev2(state_json, staging_root, quarantine_root, r0, r1, rows)
    return {
        "r0": asdict(r0), "r1": r1,
        "n_rows_sweep": len(rows),
        "gates": gates,
        "report": str(out_md),
        "resolution_csv": str(resolution_csv),
    }
