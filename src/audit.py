"""Provenance audit (v1.1 §E.2).

Replaces the prior "lr_native_res_m > hr_native_res_m" non-synthesis check
with a stronger provenance assertion per sub-pair:

  1. The pair's `metadata.json` exists and includes both HR and LR entries.
  2. The LR entry's `doi` matches the manifest's `lr_doi`.
  3. The LR entry has a downloaded source (URL or file list) and a recorded
     checksum / origin path — proving the LR raster was *fetched*, not
     synthesized from HR.
  4. HR entry likewise has provenance and the declared HR DOI.

Failures are reported but not fatal — the audit's purpose is to surface,
not to gate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .manifest import load as load_manifest


def _safe_get(row, key: str, default=""):
    """pd.Series with NaN -> default."""
    v = row.get(key, default)
    try:
        import pandas as pd
        if pd.isna(v):
            return default
    except Exception:
        pass
    return v


log = logging.getLogger(__name__)


@dataclass
class AuditFinding:
    pair_id: str
    ok: bool
    issues: list[str]


def _parent_pair_dir(harm_path: str) -> Path:
    """Given a harmonized HR path, return the per-pair raw dir that holds
    the metadata.json. Layout:
      data_root/raw/<pair_id>/metadata.json
      data_root/harmonized/<pair_id>/...
    For multi-tile pairs the raw dir is the parent pair_id (no subdir per
    sub-pair on the raw side)."""
    p = Path(harm_path)
    # harmonized/<pair_id>/[<sub>/]hr.tif → raw/<pair_id>/metadata.json
    parts = p.parts
    try:
        idx = parts.index("harmonized")
    except ValueError:
        return p.parent
    pair_id = parts[idx + 1]
    root = Path(*parts[: idx])
    return root / "raw" / pair_id


def audit_row(row: pd.Series) -> AuditFinding:
    issues: list[str] = []
    raw_dir = _parent_pair_dir(row["harmonized_path_hr"])
    meta_path = raw_dir / "metadata.json"
    if not meta_path.exists():
        return AuditFinding(row["pair_id"], False, [f"missing metadata.json at {meta_path}"])
    try:
        meta = json.loads(meta_path.read_text())
    except Exception as e:
        return AuditFinding(row["pair_id"], False, [f"unreadable metadata.json: {e}"])

    hr = meta.get("hr", {})
    lr = meta.get("lr", {})

    # 1. HR provenance — branches on hr_source_type (v1.2 §E)
    src_type = _safe_get(row, "hr_source_type", "doi") or "doi"
    if src_type == "user_provided":
        # DOI-match check does not apply; instead verify local path + sidecar.
        local_path = _safe_get(row, "hr_local_path", "") or ""
        if not local_path or not Path(local_path).exists():
            issues.append(f"user_provided HR local_path missing or absent: {local_path!r}")
        else:
            sidecar = Path(local_path).with_suffix(Path(local_path).suffix + ".provenance.json")
            if not sidecar.exists():
                issues.append(f"user_provided HR has no provenance sidecar at {sidecar}")
            else:
                try:
                    pv = json.loads(sidecar.read_text())
                except Exception as e:
                    pv = {}
                    issues.append(f"unreadable provenance sidecar: {e}")
                if not pv.get("sha256"):
                    issues.append("provenance sidecar has no sha256")
                attested = pv.get("attested_artifact_free")
                if attested is not True:
                    issues.append(f"user_provided HR not attested artifact-free (attested={attested!r})")
        # hr_superseded_doi is required only when the pair previously had a
        # DOI-based HR. New pairs (no CMGDS ancestor) carry an empty value but
        # MUST still record an explanatory `hr_superseded_reason`.
        if not _safe_get(row, "hr_superseded_reason", ""):
            issues.append("user_provided HR missing hr_superseded_reason")
    else:
        if hr.get("doi") != row["hr_doi"]:
            issues.append(f"HR DOI mismatch: metadata={hr.get('doi')} manifest={row['hr_doi']}")
        if not (hr.get("downloaded_path") or hr.get("tile_paths") or hr.get("canonical_raster") or hr.get("primary_url")):
            issues.append("HR has no recorded download path / source URL")
        if "downloaded_at_utc" not in hr:
            issues.append("HR has no downloaded_at_utc timestamp")

    # 2. LR provenance (the part the prior audit checked weakly)
    if lr.get("doi") != row["lr_doi"]:
        issues.append(f"LR DOI mismatch: metadata={lr.get('doi')} manifest={row['lr_doi']}")
    has_lr_src = bool(
        lr.get("primary_url")
        or lr.get("source_urls")
        or lr.get("downloaded_path")
        or lr.get("used_lr_tile")
        or lr.get("canonical_raster")
    )
    if not has_lr_src:
        issues.append("LR has no recorded source URL / downloaded path")
    has_lr_checksum = bool(lr.get("sha256")) or (
        # CMGDS path: zip-derived; the checksum lives in the manifest row
        row["checksum_lr"] and len(str(row["checksum_lr"])) >= 40
    )
    if not has_lr_checksum:
        issues.append("LR has no recorded SHA256 (neither in metadata.json nor manifest)")

    # 3. LR cannot be a derivative of HR — sanity check that LR's source URL
    #    is from the declared LR provider (not the HR DOI). Skip when HR DOI
    #    is empty (user_provided rows): an empty substring trivially matches.
    hr_doi_val = str(row.get("hr_doi") or "").strip()
    if hr_doi_val:
        lr_urls = lr.get("source_urls") or ([lr.get("primary_url")] if lr.get("primary_url") else [])
        for u in lr_urls:
            if u and hr_doi_val.lower() in str(u).lower():
                issues.append(f"LR source URL references HR DOI: {u}")

    return AuditFinding(row["pair_id"], not issues, issues)


def run_audit() -> list[AuditFinding]:
    df = load_manifest()
    return [audit_row(row) for _, row in df.iterrows()]
