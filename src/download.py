"""Resumable, checksummed HTTP downloader.

Writes to ``<dest>.part`` with a Range header for resume; renames atomically on
completion; verifies SHA256 against an expected value when one is supplied; is
idempotent — re-running with an already-finished file is a no-op.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests


DEFAULT_TIMEOUT_S = 60
DEFAULT_CHUNK = 1 << 20  # 1 MiB
DEFAULT_THROTTLE_S = 0.1
USER_AGENT = "auv-ship-colocated-bathy/0.1 (Sherlock; +stephencoledobbs@gmail.com)"


class DownloadError(RuntimeError):
    pass


@dataclass
class DownloadResult:
    path: Path
    sha256: str
    size_bytes: int
    resumed: bool
    source_url: str


def sha256_file(path: Path, chunk: int = DEFAULT_CHUNK) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def local_release_matches(local_path: Path, expected_doi: str) -> bool:
    """Reuse-local guard per v1.1 §E: a local file may substitute for a
    fresh fetch ONLY when it carries a provenance sidecar `<file>.doi.json`
    whose ``doi`` field matches ``expected_doi``. Otherwise we fall back to
    fetch. The presence of a same-name file at a generic path is NOT
    sufficient — different releases can share filenames.
    """
    sidecar = local_path.with_suffix(local_path.suffix + ".doi.json")
    if not (local_path.exists() and sidecar.exists()):
        return False
    try:
        import json
        meta = json.loads(sidecar.read_text())
    except Exception:
        return False
    return str(meta.get("doi", "")).strip() == expected_doi.strip()


def fetch(
    url: str,
    dest: Path,
    *,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    throttle_s: float = DEFAULT_THROTTLE_S,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    chunk: int = DEFAULT_CHUNK,
    max_retries: int = 5,
) -> DownloadResult:
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        actual = sha256_file(dest)
        if expected_sha256 is None or actual == expected_sha256:
            return DownloadResult(
                path=dest,
                sha256=actual,
                size_bytes=dest.stat().st_size,
                resumed=False,
                source_url=url,
            )
        # Wrong checksum — start over.
        dest.unlink()

    part = dest.with_suffix(dest.suffix + ".part")
    headers = {"User-Agent": USER_AGENT}
    attempt = 0
    while True:
        attempt += 1
        existing = part.stat().st_size if part.exists() else 0
        if existing:
            headers["Range"] = f"bytes={existing}-"
        try:
            with requests.get(url, headers=headers, stream=True, timeout=timeout_s) as r:
                if existing and r.status_code == 200:
                    # Server ignored the Range header — restart from 0.
                    part.unlink(missing_ok=True)
                    existing = 0
                    headers.pop("Range", None)
                if r.status_code not in (200, 206):
                    raise DownloadError(f"HTTP {r.status_code} for {url}")
                mode = "ab" if existing else "wb"
                with part.open(mode) as f:
                    for block in r.iter_content(chunk_size=chunk):
                        if not block:
                            continue
                        f.write(block)
            break
        except (requests.RequestException, DownloadError) as exc:
            if attempt >= max_retries:
                raise DownloadError(f"giving up on {url} after {attempt} attempts: {exc}") from exc
            time.sleep(min(2 ** attempt, 30))

    size = part.stat().st_size
    if expected_size is not None and size != expected_size:
        raise DownloadError(f"size mismatch for {url}: got {size}, expected {expected_size}")
    digest = sha256_file(part)
    if expected_sha256 is not None and digest != expected_sha256:
        raise DownloadError(f"sha256 mismatch for {url}: got {digest}, expected {expected_sha256}")
    os.replace(part, dest)
    time.sleep(throttle_s)
    return DownloadResult(
        path=dest,
        sha256=digest,
        size_bytes=size,
        resumed=bool(existing),
        source_url=url,
    )
