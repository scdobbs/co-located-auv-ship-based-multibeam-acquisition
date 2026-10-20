"""ACQ-R14 ruling 2026-10-20 (H-2 changed): create an UNPUBLISHED Zenodo draft of the release package and upload the files.

  * token: read from ~/.zenodo_token (deposit:write + deposit:actions); never printed, logged or written anywhere;
  * zenodo.org (not the sandbox); a new deposition, metadata from package/zenodo_metadata.json, DOI pre-reserved;
  * the 66 files of the file rule in zenodo_metadata.json: every top-level file of the package (pair zips, tables,
    docs, blind_tests.zip, SHA256SUMS) plus examples/load_pair.py as load_pair.py; flat; no extra zip;
  * each upload's MD5 is compared with the checksum Zenodo returns; a failed file is retried once;
  * never publishes. Resumable: the deposition id is kept in reports_post_grl_review/ACQ-R14/zenodo_draft.json and
    files already on the draft with the right MD5 are skipped.

    python -B -m src.acq_r14.zenodo_upload [--package DIR] [--dry-run]
"""
from __future__ import annotations
import argparse, hashlib, json, os, time
from pathlib import Path
import requests
from . import common as C

API = "https://zenodo.org/api"
STATE = C.RPT / "zenodo_draft.json"
TOKEN_FILE = Path.home() / ".zenodo_token"
DEFAULT_PKG = C.OAK_DEST / "package"


def _token() -> str:
    t = TOKEN_FILE.read_text().strip()
    if not t:
        raise SystemExit("empty ~/.zenodo_token")
    return t


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _req(method, url, token, **kw):
    """One request; the token goes in the Authorization header only, and error bodies are returned without it."""
    headers = {"Authorization": f"Bearer {token}", "User-Agent": C.HEADERS["User-Agent"]}
    headers.update(kw.pop("headers", {}))
    r = requests.request(method, url, headers=headers, timeout=kw.pop("timeout", 600), **kw)
    return r


def files_to_upload(pkg: Path) -> list[tuple[str, Path]]:
    out = [(p.name, p) for p in sorted(pkg.iterdir()) if p.is_file()]
    out.append(("load_pair.py", pkg / "examples" / "load_pair.py"))
    names = [n for n, _ in out]
    assert len(names) == len(set(names)), "duplicate upload names"
    return out


def metadata(pkg: Path) -> dict:
    m = C.jload(pkg / "zenodo_metadata.json")
    related = []
    for r in m["related_identifiers"]:
        ident = r["identifier"]
        if ident.startswith("10."):
            related.append({"identifier": ident, "relation": r["relation"], "resource_type": r.get("resource_type", "software"), "scheme": "doi"})
        else:
            related.append({"identifier": ident, "relation": r["relation"]})       # the manuscript id; Zenodo decides (reported if rejected)
    return {"title": m["title"], "upload_type": m["upload_type"], "description": m["description"], "creators": m["creators"], "keywords": m["keywords"],
            "license": m["license"], "related_identifiers": related, "version": m["version"], "publication_date": m["publication_date"],
            "access_right": "open", "prereserve_doi": True}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", default=str(DEFAULT_PKG))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    pkg = Path(a.package)
    files = files_to_upload(pkg)
    m = C.jload(pkg / "zenodo_metadata.json")
    if len(files) != m["files_to_upload"]["count"]:
        raise SystemExit(f"file rule says {m['files_to_upload']['count']} files, found {len(files)}")
    total = sum(p.stat().st_size for _, p in files)
    C.log(f"{len(files)} files, {total / 1e9:.3f} GB, package {pkg}")
    if a.dry_run:
        for n, p in files:
            print(f"  {n:52s} {p.stat().st_size:>12d}")
        return
    token = _token()
    state = C.jload(STATE) if STATE.exists() else {}
    # ---- 1. deposition (reuse an existing unpublished draft)
    if state.get("id"):
        r = _req("GET", f"{API}/deposit/depositions/{state['id']}", token)
        if r.status_code != 200 or r.json().get("submitted"):
            raise SystemExit(f"existing draft {state['id']} not usable: HTTP {r.status_code} submitted={r.json().get('submitted') if r.status_code == 200 else None}")
        dep = r.json()
        C.log(f"reusing draft {dep['id']}")
    else:
        r = _req("POST", f"{API}/deposit/depositions", token, json={}, headers={"Content-Type": "application/json"})
        if r.status_code != 201:
            raise SystemExit(f"create deposition failed: HTTP {r.status_code} {r.text[:500]}")
        dep = r.json()
        state = {"id": dep["id"], "created": C.utcnow(), "html": dep["links"]["html"], "bucket": dep["links"]["bucket"]}
        C.jdump(state, STATE)
        C.log(f"created draft {dep['id']} {dep['links']['html']}")
    bucket = dep["links"]["bucket"]
    # ---- 2. metadata (+ prereserve_doi); on a 400, drop the fields Zenodo names and retry once, recording both answers
    md = metadata(pkg)
    attempts = []
    r = _req("PUT", f"{API}/deposit/depositions/{dep['id']}", token, json={"metadata": md}, headers={"Content-Type": "application/json"})
    attempts.append({"status": r.status_code, "errors": (r.json().get("errors") if r.status_code != 200 else None)})
    if r.status_code == 400:
        bad = {e.get("field", "").removeprefix("metadata.").split(".")[0] for e in r.json().get("errors", [])}
        C.log(f"metadata rejected on {sorted(bad)}: {r.text[:400]}")
        if "related_identifiers" in bad:
            md["related_identifiers"] = [x for x in md["related_identifiers"] if x.get("scheme") == "doi"]
        for f in bad - {"related_identifiers"}:
            md.pop(f, None)
        r = _req("PUT", f"{API}/deposit/depositions/{dep['id']}", token, json={"metadata": md}, headers={"Content-Type": "application/json"})
        attempts.append({"status": r.status_code, "errors": (r.json().get("errors") if r.status_code != 200 else None), "dropped": sorted(bad)})
    if r.status_code != 200:
        raise SystemExit(f"metadata update failed: HTTP {r.status_code} {r.text[:800]}")
    dep = r.json()
    applied = dep["metadata"]
    changed = {k: {"sent": md[k], "zenodo": applied.get(k)} for k in md if k != "prereserve_doi" and json.dumps(applied.get(k), sort_keys=True) != json.dumps(md[k], sort_keys=True)}
    state.update(metadata_attempts=attempts, metadata_changed_by_zenodo=changed, prereserve_doi=applied.get("prereserve_doi"), html=dep["links"]["html"])
    C.jdump(state, STATE)
    C.log(f"metadata applied; reserved DOI {applied.get('prereserve_doi', {}).get('doi')}; fields changed by Zenodo: {sorted(changed)}")
    # ---- 3. files: skip those already present with the right MD5, upload the rest, verify, retry once
    r = _req("GET", f"{API}/deposit/depositions/{dep['id']}/files", token)
    present = {f["filename"]: f.get("checksum", "") for f in (r.json() if r.status_code == 200 else [])}
    results = state.get("files", {})
    for name, p in files:
        local = _md5(p)
        if present.get(name) in (local, f"md5:{local}"):
            results[name] = {"bytes": p.stat().st_size, "md5": local, "status": "already_present", "attempts": 0}
            continue
        ok, tries, last = False, 0, None
        while not ok and tries < 2:
            tries += 1
            with open(p, "rb") as fh:
                r = _req("PUT", f"{bucket}/{name}", token, data=fh, headers={"Content-Type": "application/octet-stream"}, timeout=3600)
            if r.status_code in (200, 201):
                remote = r.json().get("checksum", "").replace("md5:", "")
                ok = remote == local
                last = f"HTTP {r.status_code} md5 {'match' if ok else 'MISMATCH ' + remote}"
            else:
                last = f"HTTP {r.status_code} {r.text[:200]}"
            if not ok:
                C.log(f"  {name}: attempt {tries} failed: {last}")
                time.sleep(5)
        results[name] = {"bytes": p.stat().st_size, "md5": local, "status": "verified" if ok else "FAILED", "attempts": tries, "last": last}
        state["files"] = results
        C.jdump(state, STATE)
        C.log(f"  {name:52s} {p.stat().st_size / 1e6:8.1f} MB  {results[name]['status']} ({tries})")
    # ---- 4. final listing from Zenodo
    r = _req("GET", f"{API}/deposit/depositions/{dep['id']}/files", token)
    remote = r.json() if r.status_code == 200 else []
    n_ok = sum(1 for v in results.values() if v["status"] in ("verified", "already_present"))
    state.update(finished=C.utcnow(), n_files_local=len(files), n_files_zenodo=len(remote), bytes_zenodo=sum(f.get("filesize", 0) for f in remote),
                 n_verified=n_ok, n_failed=len(files) - n_ok, submitted=dep.get("submitted", False),
                 remote_checksums_match=all(any(f["filename"] == n and f.get("checksum", "").replace("md5:", "") == v["md5"] for f in remote) for n, v in results.items()))
    C.jdump(state, STATE)
    C.log(f"draft {state['html']} reserved DOI {state.get('prereserve_doi', {}).get('doi')}: {state['n_files_zenodo']} files on Zenodo, {state['bytes_zenodo'] / 1e9:.3f} GB, "
          f"verified {n_ok}/{len(files)}, failed {state['n_failed']}, submitted={state['submitted']}")
    if state["n_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
