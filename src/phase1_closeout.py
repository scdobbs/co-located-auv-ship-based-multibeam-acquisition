"""v1.5.4 rev 3 — Phase 1 close-out.

C0 — capture the actual server response (status, redirect chain,
Content-Type, Content-Length, first ~2 KB body) for the three
``recover_or_drop`` candidates (MGDS:30272, MGDS:20836, MGDS:24425); if
the body names a corrected URL form, attempt ONE corrected fetch.

C1 — recalibrate Gate 6 asymmetric. ``ratio < 0.5`` (measured finer
than declared) is re-admitted as ``ok_finer_verify`` with
``native_res_verification_needed=true`` rather than blocking.

C2 — append-only rev3 report + final state refresh.
"""

from __future__ import annotations

import csv
import json
import logging
import shutil
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

from . import phase1_remediation as rem


log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "auv-ship-acq/0.1 (Sherlock; v1.5.4 rev3)"}


# ---------- C0 — full capture + one corrected fetch ----------

@dataclass
class CaptureResult:
    hr_id: str
    primary_url: str
    final_http_status: int | None
    redirect_chain: list[dict]
    content_type: str | None
    content_length_header: str | None
    body_bytes: int
    body_first_2k: str
    declared_format: str
    expected_total_bytes: int
    file_count_in_catalog: int
    corrected_attempted: bool
    corrected_url: str | None
    corrected_http_status: int | None
    corrected_bytes: int
    recovery_outcome: str            # 'recovered' | 'recover_or_drop'
    reason: str


def _capture(url: str) -> dict:
    """Return ``{status, redirect_chain, content_type, content_length,
    body_bytes, body_first_2k}`` for a single GET."""
    sess = requests.Session()
    sess.headers.update(_HEADERS)
    try:
        r = sess.get(url, allow_redirects=True, timeout=120, stream=False)
    except Exception as e:
        return {
            "status": None, "redirect_chain": [],
            "content_type": None, "content_length": None,
            "body_bytes": 0, "body_first_2k": f"<exception: {e}>",
            "final_url": url,
        }
    chain = []
    for resp in list(r.history) + [r]:
        chain.append({
            "url": resp.url,
            "status": resp.status_code,
            "location": resp.headers.get("Location"),
            "content_type": resp.headers.get("Content-Type"),
            "content_length": resp.headers.get("Content-Length"),
        })
    body = r.content or b""
    return {
        "status": r.status_code,
        "redirect_chain": chain,
        "content_type": r.headers.get("Content-Type"),
        "content_length": r.headers.get("Content-Length"),
        "body_bytes": len(body),
        "body_first_2k": body[:2048].decode("utf-8", errors="replace"),
        "final_url": r.url,
    }


def c0_capture_and_recover(hr_ids: list[str],
                            hr_catalog_path: Path,
                            staging_root: Path) -> list[CaptureResult]:
    """Run the per-id capture + one corrected fetch. The corrected fetch
    is the legacy MGDS endpoint (``marine-geo.org/services/FileDownloadServer``)
    which 301-redirects to the new path; if it lands on a real grid file
    instead of an HTML error, we accept it as recovered.
    """
    hr = gpd.read_file(hr_catalog_path, layer="hr")
    by_id = hr.set_index("hr_id")

    results: list[CaptureResult] = []
    for hr_id in hr_ids:
        row = by_id.loc[hr_id] if hr_id in by_id.index else None
        file_ids_raw = row["file_ids"] if row is not None else ""
        file_ids = [u.strip() for u in str(file_ids_raw).split(",") if u.strip()]
        declared_format = (row["format"] if row is not None
                           and "format" in row.index else "") or ""
        # Primary URL = first data_uid via the current api endpoint.
        first_uid = file_ids[0] if file_ids else ""
        primary_url = (
            f"https://api.marine-geo.org/services/download/Document_Accept.php"
            f"?client=DataLink&data_uid={first_uid}"
        ) if first_uid else ""

        cap = _capture(primary_url) if primary_url else {
            "status": None, "redirect_chain": [],
            "content_type": None, "content_length": None,
            "body_bytes": 0, "body_first_2k": "<no file_ids in catalog>",
            "final_url": "",
        }

        # Inspect body / Content-Type / Content-Disposition to decide
        # the next move.
        body = cap["body_first_2k"]
        ct = (cap["content_type"] or "").lower()
        is_pdf = body.startswith("%PDF-") or "application/pdf" in ct
        is_html_error = ("Download Error" in body or
                         (cap["body_bytes"] < 4096 and "<html" in body.lower()))

        corrected_url = None
        corrected_status = None
        corrected_bytes = 0
        attempted = False
        outcome = "recover_or_drop"
        reason = ""

        if is_pdf and declared_format.upper() == "PDF":
            # Server delivers PDFs because the dataset is PDF-only —
            # not bathymetry grid. Recovery impossible.
            reason = ("server delivers PDFs as catalogued "
                      f"(format='{declared_format}'); no grid data exists")
        elif is_html_error:
            # Try the legacy endpoint as the single corrected attempt.
            legacy_url = (
                f"https://www.marine-geo.org/services/FileDownloadServer"
                f"?data_uid={first_uid}"
            )
            corrected_url = legacy_url
            attempted = True
            corr = _capture(legacy_url)
            corrected_status = corr["status"]
            corrected_bytes = corr["body_bytes"]
            corr_body = corr["body_first_2k"]
            # Acceptance: HTTP 200, > 100 KB, not HTML
            if (corrected_status == 200
                    and corrected_bytes > 100 * 1024
                    and not corr_body.lower().lstrip().startswith("<")):
                # Save body to staging dir
                fname = f"data_uid_{first_uid}.bin"
                target_dir = staging_root / hr_id.replace(":", "_")
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / fname
                # Re-fetch streaming for clean write
                try:
                    sess = requests.Session()
                    sess.headers.update(_HEADERS)
                    r2 = sess.get(legacy_url, stream=True, timeout=600,
                                  allow_redirects=True)
                    if r2.status_code == 200:
                        tmp = target.with_suffix(target.suffix + ".part")
                        with tmp.open("wb") as f:
                            for chunk in r2.iter_content(chunk_size=1 << 20):
                                if chunk:
                                    f.write(chunk)
                        tmp.rename(target)
                        outcome = "recovered"
                        corrected_bytes = target.stat().st_size
                        reason = (f"legacy endpoint returned {corrected_bytes} bytes "
                                  "of binary data; saved to staging")
                except Exception as e:
                    reason = f"corrected attempt errored writing file: {e}"
            else:
                reason = (f"legacy endpoint also failed "
                          f"(status={corrected_status}, "
                          f"bytes={corrected_bytes}); both URL forms exhausted")
        else:
            reason = "primary returned unexpected content but no actionable hint"

        try:
            exp = sum(int(by_id.loc[hr_id].get("data_file_size", 0) or 0)
                      for _ in file_ids)
        except Exception:
            exp = 0
        results.append(CaptureResult(
            hr_id=hr_id, primary_url=primary_url,
            final_http_status=cap["status"],
            redirect_chain=cap["redirect_chain"],
            content_type=cap["content_type"],
            content_length_header=cap["content_length"],
            body_bytes=cap["body_bytes"],
            body_first_2k=cap["body_first_2k"],
            declared_format=declared_format,
            expected_total_bytes=exp,
            file_count_in_catalog=len(file_ids),
            corrected_attempted=attempted,
            corrected_url=corrected_url,
            corrected_http_status=corrected_status,
            corrected_bytes=corrected_bytes,
            recovery_outcome=outcome, reason=reason,
        ))
    return results


# ---------- C1 — recalibrate Gate 6 + augment CSV ----------

def c1_recalibrate(rows: list[rem.HRResolution],
                   recoveries: list[CaptureResult]
                   ) -> tuple[list[dict], dict]:
    """Apply asymmetric Gate 6. Adds ``resolution`` and
    ``native_res_verification_needed`` columns. Returns the row-of-dicts
    (for CSV emission) and Gate 6's result.
    """
    recovered_ids = {r.hr_id for r in recoveries
                     if r.recovery_outcome == "recovered"}
    escalated_ids = {r.hr_id for r in recoveries
                     if r.recovery_outcome == "recover_or_drop"}

    out_rows: list[dict] = []
    n_block = 0
    blocked: list[str] = []
    for r in rows:
        d = asdict(r)
        verdict = r.verdict
        verify_needed = False
        resolution = verdict

        if verdict == "ok":
            resolution = "ok"
        elif verdict == "quarantined":
            resolution = "quarantined"
        elif verdict == "manifest_seed_clean":
            resolution = "manifest_seed_clean"
        elif verdict == "fetch_failed_escalate":
            # C0 outcome carried forward
            if r.hr_id in recovered_ids:
                resolution = "escalated_recovered"
            else:
                resolution = "escalated_recover_or_drop"
        elif verdict == "flag_mismatch":
            # Asymmetric: finer-than-declared is OK with a verify tag.
            if r.ratio is not None and r.ratio < 0.5:
                resolution = "ok_finer_verify"
                verify_needed = True
            elif r.ratio is not None and r.ratio > 2.0:
                resolution = "blocked_coarse"
                n_block += 1
                blocked.append(r.hr_id)
            else:
                resolution = "blocked_other"
                n_block += 1
                blocked.append(r.hr_id)
        elif verdict == "flag_coarse":
            resolution = "blocked_coarse"
            n_block += 1
            blocked.append(r.hr_id)
        elif verdict == "no_grid_found":
            # If we attempted recovery this pass (PDFs / server errors),
            # carry the C0 outcome; otherwise block.
            if r.hr_id in recovered_ids:
                resolution = "escalated_recovered"
            elif r.hr_id in escalated_ids:
                resolution = "escalated_recover_or_drop"
            else:
                resolution = "blocked_no_grid"
                n_block += 1
                blocked.append(r.hr_id)

        d["resolution"] = resolution
        d["native_res_verification_needed"] = verify_needed
        out_rows.append(d)

    gate6 = {
        "pass": n_block == 0,
        "detail": (f"{n_block} unresolved BLOCK-class HR remain"
                   if n_block else
                   "every HR resolution is ok / ok_finer_verify / "
                   "quarantined / escalated"),
        "blocked": blocked,
        "definition": (
            "BLOCK: blocked_coarse (ratio>2) | blocked_no_grid | composite. "
            "PASS-recorded resolutions: ok | ok_finer_verify | "
            "manifest_seed_clean | quarantined | escalated_recovered | "
            "escalated_recover_or_drop."
        ),
    }
    return out_rows, gate6


# ---------- C2 — write rev3 report + refresh state ----------

def write_rev3_report(out_md: Path, captures: list[CaptureResult],
                      enriched_rows: list[dict], gate6: dict,
                      gates_1_to_5: dict,
                      manifest_csv: Path, log_csv: Path) -> None:
    n_total = len(enriched_rows)
    by_res: dict[str, list[str]] = {}
    for r in enriched_rows:
        by_res.setdefault(r["resolution"], []).append(r["hr_id"])
    n_ok = len(by_res.get("ok", []))
    n_finer = len(by_res.get("ok_finer_verify", []))
    n_seed = len(by_res.get("manifest_seed_clean", []))
    n_quar = len(by_res.get("quarantined", []))
    n_esc_rec = len(by_res.get("escalated_recovered", []))
    n_esc_drop = len(by_res.get("escalated_recover_or_drop", []))
    n_block_coarse = len(by_res.get("blocked_coarse", []))
    n_block_no_grid = len(by_res.get("blocked_no_grid", []))
    clean = n_ok + n_finer + n_seed + n_esc_rec
    verify_ids = [r["hr_id"] for r in enriched_rows
                  if r["native_res_verification_needed"]]

    lines = [
        "# Stage 1 staging-download report — rev 3 (close-out, 2026-06-05)",
        "",
        "*Phase 1 close-out per directive v1.5.4 rev 3. Captures the "
        "actual server response for the three missing-data HR, applies "
        "asymmetric Gate 6, and lands the final clean count.*",
        "",
        "## C0 — server-response capture + corrected-fetch attempt",
        "",
    ]
    for cap in captures:
        lines += [
            f"### {cap.hr_id}",
            "",
            f"- Declared catalog format: **{cap.declared_format}**",
            f"- file_ids in catalog: **{cap.file_count_in_catalog}**",
            f"- Primary URL: `{cap.primary_url}`",
            f"- Final HTTP status: **{cap.final_http_status}**",
            f"- Content-Type: `{cap.content_type}` · "
            f"Content-Length header: `{cap.content_length_header}` · "
            f"body bytes: **{cap.body_bytes}**",
            "",
            "Redirect chain:",
            "",
        ]
        for hop in cap.redirect_chain:
            lines.append(f"- `{hop['status']}` → `{hop['url']}` "
                         f"(Location={hop.get('location')}, "
                         f"CT={hop.get('content_type')}, "
                         f"CL={hop.get('content_length')})")
        body_escaped = cap.body_first_2k.replace("\r", "").replace("\n", "\\n")[:1800]
        lines += [
            "",
            "Body (first ~1.8K, newlines escaped):",
            "",
            f"> `{body_escaped}`",
            "",
            f"**Corrected attempt:** "
            f"{'yes' if cap.corrected_attempted else 'not applicable'}",
        ]
        if cap.corrected_attempted:
            lines += [
                f"- URL: `{cap.corrected_url}`",
                f"- HTTP: **{cap.corrected_http_status}**, bytes: "
                f"**{cap.corrected_bytes}**",
            ]
        lines += [
            f"- **Recovery outcome: `{cap.recovery_outcome}`** — {cap.reason}",
            "",
        ]

    lines += [
        "## C1 — Gate 6 recalibration (asymmetric)",
        "",
        "**BLOCK (FAIL-class):** `blocked_coarse` (ratio > 2, measured "
        "coarser than declared) · `blocked_no_grid` · `composite` (carries "
        "over from quarantine).",
        "",
        "**WARN (PASS, recorded):** measured *finer* than declared "
        "(ratio < 0.5) — reclassified from `flag_mismatch` to "
        "**`ok_finer_verify`**, tagged `native_res_verification_needed=true`, "
        "re-admitted to the clean corpus. The `native_res` of these HR is "
        "suspect (declared was overstated, OR the grid is over-posted / "
        "interpolated); the assessment instance owns the Phase-2 "
        "sounding-density derivation.",
        "",
        "## Verification gates (final)",
        "",
        "| # | gate | result | detail |",
        "|---|---|---|---|",
    ]
    for k in sorted(gates_1_to_5.keys()):
        g = gates_1_to_5[k]
        lines.append(f"| {k} | {k.split('_',1)[1]} | "
                     f"{'PASS' if g['pass'] else 'FAIL'} | {g['detail']} |")
    lines.append(f"| 6_cell_size_sanity_asymmetric | cell_size_sanity | "
                 f"{'PASS' if gate6['pass'] else 'FAIL'} | {gate6['detail']} |")

    lines += [
        "",
        "## What Phase 2 inherits",
        "",
        f"- **Clean HR count: {clean}** "
        f"= {n_ok} ok + {n_finer} ok_finer_verify "
        f"+ {n_seed} manifest_seed_clean + {n_esc_rec} escalated_recovered.",
        f"- Total accounted: {n_total} = clean ({clean}) + quarantined "
        f"({n_quar}) + escalated_recover_or_drop ({n_esc_drop}) + "
        f"blocked_coarse ({n_block_coarse}) + blocked_no_grid ({n_block_no_grid}).",
        "",
        f"### `native_res_verification_needed` (re-admitted, ratio < 0.5):",
        "",
        f"  {sorted(verify_ids)}",
        "",
        f"### Quarantined (composite, default-exclude pending provenance):",
        "",
        f"  {by_res.get('quarantined', [])}",
        "",
        f"### Escalated — recover_or_drop (assessment-instance decision):",
        "",
        f"  {by_res.get('escalated_recover_or_drop', [])}",
        "",
        "## Out-of-scope (unchanged from rev 1/2)",
        "",
        "Re-deriving `native_res` for the ok_finer_verify HR (Phase 2, "
        "from sounding density — not grid posting). Final eligibility on "
        "`MGDS:31600` (needs provenance) and on `recover_or_drop` ids. "
        "Raw-LR fetch, gridding, retention decision, manifest append, "
        "re-tier — all Phase 2 / assessment.",
        "",
    ]
    out_md.write_text("\n".join(lines))


def refresh_state_rev3(state_path: Path, captures: list[CaptureResult],
                       enriched_rows: list[dict], gate6: dict) -> None:
    state = json.loads(state_path.read_text())
    import os as _os
    DATA_ROOT = Path("/scratch/groups/hilley/auv_ship_colocated_bathy")
    inv = []
    total = 0
    for root, _, files in _os.walk(DATA_ROOT):
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

    by_res: dict[str, list[str]] = {}
    for r in enriched_rows:
        by_res.setdefault(r["resolution"], []).append(r["hr_id"])
    n_ok = len(by_res.get("ok", []))
    n_finer = len(by_res.get("ok_finer_verify", []))
    n_seed = len(by_res.get("manifest_seed_clean", []))
    n_esc_rec = len(by_res.get("escalated_recovered", []))
    clean = n_ok + n_finer + n_seed + n_esc_rec
    verify_ids = [r["hr_id"] for r in enriched_rows
                  if r["native_res_verification_needed"]]
    state["phase1_rev3"] = {
        "c0_captures": [asdict(c) for c in captures],
        "gate6_final": gate6,
        "resolution_counts": {k: len(v) for k, v in by_res.items()},
        "clean_hr_count": clean,
        "native_res_verification_needed": sorted(verify_ids),
        "quarantined_ids": by_res.get("quarantined", []),
        "escalated_recover_or_drop_ids": by_res.get(
            "escalated_recover_or_drop", []),
        "phase2_inherits_note": (
            "Clean HR count = ok + ok_finer_verify (native_res to verify "
            "in Phase 2 from sounding density) + manifest_seed_clean "
            "(prior milestones) + escalated_recovered (none this pass). "
            "Quarantined + recover_or_drop ids await assessment-instance "
            "decision; no re-tier in Phase 1."
        ),
    }
    state_path.write_text(json.dumps(state, indent=2, default=str))


def write_enriched_csv(out_csv: Path, rows: list[dict]) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "hr_id", "declared_native_m", "measured_finest_cell_m", "crs",
        "ratio", "verdict", "n_grid_files",
        "resolution", "native_res_verification_needed",
    ]
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})


# ---------- Orchestrator ----------

def run_closeout(staging_root: Path, quarantine_root: Path,
                 hr_catalog_path: Path,
                 manifest_csv: Path, log_csv: Path,
                 state_json: Path,
                 out_md_canonical: Path, resolution_csv: Path) -> dict:
    log.info("C0 — capture server bodies + one corrected attempt each")
    captures = c0_capture_and_recover(
        ["MGDS:30272", "MGDS:20836", "MGDS:24425"],
        hr_catalog_path, staging_root,
    )

    log.info("C1 — recompute sweep + recalibrate Gate 6")
    quarantined = {"MGDS:31600"}
    escalated = {"MGDS:30272", "MGDS:20836", "MGDS:24425"}
    sweep_rows = rem.r2_resolution_sweep(staging_root, hr_catalog_path,
                                          quarantined,
                                          manifest_csv=manifest_csv,
                                          escalated=escalated)
    enriched, gate6 = c1_recalibrate(sweep_rows, captures)

    # Gates 1-5 reuse the rev-2 verifier; they still PASS by construction.
    # Treat all C0 ids + quarantined + manifest seeds as "resolved" for
    # Gate 1's byte-exactness scope.
    resolved_ids = quarantined | escalated | {
        r["hr_id"] for r in enriched
        if r["resolution"] == "manifest_seed_clean"
    }
    gates_1_5 = {
        k: v for k, v in rem.verify_rev2(
            manifest_csv, log_csv, staging_root, state_json,
            sweep_rows, resolved_ids,
        ).items() if not k.startswith("6_")
    }

    write_enriched_csv(resolution_csv, enriched)

    # Append-only: write rev-3 to a new dated file even if the canonical
    # one exists. Use _runN suffix consistent with the rev-2 pattern.
    out_md = out_md_canonical
    if out_md.exists():
        stem = out_md.stem
        v = 2
        cand = out_md.with_name(f"{stem}_run{v}.md")
        while cand.exists():
            v += 1
            cand = out_md.with_name(f"{stem}_run{v}.md")
        out_md = cand

    write_rev3_report(out_md, captures, enriched, gate6, gates_1_5,
                      manifest_csv, log_csv)
    refresh_state_rev3(state_json, captures, enriched, gate6)
    return {
        "captures": [asdict(c) for c in captures],
        "gate6": gate6,
        "gates_1_5": {k: v["pass"] for k, v in gates_1_5.items()},
        "report": str(out_md),
        "resolution_csv": str(resolution_csv),
        "sweep_count": len(sweep_rows),
    }
