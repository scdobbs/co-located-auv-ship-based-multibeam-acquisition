"""ACQ-R03 §1.1/§1.3 — inventory, then single-worker resumable fetch of the §1.2 selection to OAK.

§1.1 inventory: a file already under raw_lr_swath/<cruise>/ is kept only if its size equals the advertised size
(±1 kB) and `mbinfo` reads it; anything else (including .part remnants) is removed.  Kept files are recorded
in fetch_manifest.json with source "acq_r02_inventory".
§1.3 fetch: one worker; polite throttle; exponential back-off on 429/503/5xx; Range-resume of .part files;
byte-exact against the advertised size (and Content-Length when given); sha256; 0444; the manifest is rewritten
after every file (source "automated"); files already ingested manually (§1.4) are skipped.
Stop rules: mean throughput below --min-rate MB/s after --rate-window hours, or --max-hours of wall time ->
exit 2 (HOLD) with the number of files remaining.
Usage (job): python -m src.acq_r03.fetch_pangaea --cruise PANGAEA_864677 [--throttle 1.0]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from src.acq_r03 import common as R

SKIP = {"fetch_manifest.json", "SHA256SUMS", "manual_ingest.json"}


def all_advertised(info: dict) -> dict:
    """file name -> advertised bytes, for every .all row of the dataset (not just the selection)."""
    df = R.parse_tab_export(R.fetch_tab_export(info["dataset"]))
    out = {}
    for _, r in df.iterrows():
        n, u = str(r[info["name_col"]]).strip(), str(r[info["url_col"]]).strip()
        if n.lower().endswith(".all") and u.endswith("/" + n):
            out[n] = (R.kbyte_to_bytes(r[info["size_col"]]), u)
    return out


def size_ok(n: int, adv: int) -> bool:
    return abs(int(n) - int(adv)) <= R.SIZE_TOL_B


def inventory(cruise_dir: Path, adv: dict, man: dict) -> dict:
    """§1.1: keep only byte-exact, mbinfo-readable files; record them; remove the rest."""
    known = {f["name"] for f in man["files"]}
    rep = {"kept": [], "removed": [], "already_recorded": []}
    for p in sorted(cruise_dir.iterdir()):
        if not p.is_file() or p.name in SKIP:
            continue
        if p.name.endswith(".part") or p.name not in adv:
            p.chmod(0o644); p.unlink(); rep["removed"].append({"name": p.name, "reason": "partial or not a .all file of this dataset"}); continue
        if p.name in known:
            rep["already_recorded"].append(p.name); continue
        sz = p.stat().st_size
        if not size_ok(sz, adv[p.name][0]):
            p.chmod(0o644); p.unlink(); rep["removed"].append({"name": p.name, "size": sz, "advertised": adv[p.name][0], "reason": "size != advertised"}); continue
        ok, note = R.mbinfo_reads(p)
        if not ok:
            p.chmod(0o644); p.unlink(); rep["removed"].append({"name": p.name, "size": sz, "reason": f"mbinfo does not read it ({note})"}); continue
        sha = R.C.sha256_file(p); p.chmod(0o444)
        man["files"].append({"name": p.name, "url": adv[p.name][1], "size": sz, "sha256": sha, "source": "acq_r02_inventory", "mbinfo": note, "recorded_at": R.utc_now()})
        rep["kept"].append(p.name)
    R.save_manifest(cruise_dir, man)
    return rep


def fetch_file(url: str, name: str, adv: int, cruise_dir, sess: requests.Session, throttle: float) -> dict:
    out = cruise_dir / name; part = cruise_dir / (name + ".part")
    rec = {"name": name, "url": url, "advertised": adv, "status": "", "http": None, "bytes_transferred": 0, "seconds": 0.0, "attempts": 0}
    t0 = time.time()
    for attempt in range(8):
        rec["attempts"] = attempt + 1
        have = part.stat().st_size if part.exists() else 0
        hdr = dict(R.HEADERS)
        if have:
            hdr["Range"] = f"bytes={have}-"
        try:
            with sess.get(url, headers=hdr, timeout=900, stream=True) as g:
                rec["http"] = g.status_code
                if g.status_code in (429, 503) or g.status_code >= 500:
                    ra = g.headers.get("Retry-After")
                    time.sleep(min(300.0, float(ra) if ra and ra.isdigit() else 5.0 * 2 ** attempt)); continue
                if have and g.status_code == 200:
                    have = 0                       # server ignored Range: start over
                if g.status_code not in (200, 206):
                    rec["status"] = f"failed_http_{g.status_code}"; return rec
                clen = g.headers.get("Content-Length")
                total = have + int(clen) if clen else None
                if total is not None and not size_ok(total, adv):
                    rec["status"] = f"failed_size_mismatch_server_{total}"; return rec
                mode = "ab" if have else "wb"
                with part.open(mode) as fh:
                    for ch in g.iter_content(1 << 20):
                        fh.write(ch); rec["bytes_transferred"] += len(ch)
            n = part.stat().st_size
            if (total is not None and n == total) or (total is None and size_ok(n, adv)):
                sha = R.C.sha256_file(part)
                if out.exists():
                    out.chmod(0o644); out.unlink()
                part.rename(out); out.chmod(0o444)
                rec.update({"status": "fetched", "size": n, "sha256": sha, "seconds": round(time.time() - t0, 1)})
                time.sleep(throttle); return rec
            if n > (total or adv + R.SIZE_TOL_B):
                part.unlink(missing_ok=True)       # over-long: restart
            time.sleep(min(60, 2 ** attempt))
        except (requests.Timeout, requests.ConnectionError) as e:
            rec["http"] = type(e).__name__; time.sleep(min(120, 5 * 2 ** attempt))
        except Exception as e:
            rec["http"] = f"err:{type(e).__name__}"; time.sleep(min(120, 5 * 2 ** attempt))
    rec["status"] = "failed_after_retries"; rec["seconds"] = round(time.time() - t0, 1)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cruise", required=True); ap.add_argument("--throttle", type=float, default=1.0)
    ap.add_argument("--max-hours", type=float, default=47.5); ap.add_argument("--min-rate", type=float, default=0.1, help="MB/s")
    ap.add_argument("--rate-window", type=float, default=6.0, help="hours before the min-rate rule applies")
    ap.add_argument("--inventory-only", action="store_true")
    a = ap.parse_args(argv)
    info = R.PANGAEA_UNITS[a.cruise]
    cruise_dir = R.RAW_SWATH / a.cruise; cruise_dir.mkdir(parents=True, exist_ok=True)
    adv = all_advertised(info)
    man = R.load_manifest(cruise_dir)
    # normalise ACQ-R02 manifest entries (filename/received -> name/size); re-verify them in the inventory pass
    norm = []
    for f in man.get("files", []):
        nm = f.get("name") or f.get("filename"); sz = f.get("size") or f.get("received")
        p = cruise_dir / nm
        if nm in adv and p.exists() and size_ok(p.stat().st_size, adv[nm][0]) and f.get("sha256"):
            norm.append({"name": nm, "url": f.get("url") or adv[nm][1], "size": int(p.stat().st_size), "sha256": f["sha256"], "source": f.get("source", "acq_r02_fetch"),
                         "recorded_at": f.get("recorded_at", man.get("fetched_at", ""))})
    man["files"] = norm; man.pop("failed", None); man.pop("n_files_planned", None)
    man["source"] = f"PANGAEA {info['doi']} ({info['cruise']}, hs.pangaea.de); ACQ-R03 §1 footprint-subset fetch (selection: pangaea_selection_{a.cruise}.csv)"
    inv = inventory(cruise_dir, adv, man)
    R.write_json(R.REPORT_DIR / f"fetch_inventory_{a.cruise}.json", {"cruise": a.cruise, **inv, "n_recorded_after_inventory": len(man["files"]), "at": R.utc_now()})
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in inv.items()}), flush=True)
    if a.inventory_only:
        return 0
    sel = pd.read_csv(R.REPORT_DIR / f"pangaea_selection_{a.cruise}.csv")
    have = {f["name"]: f for f in man["files"]}
    todo = [r for _, r in sel.iterrows() if not (r.file_name in have and (cruise_dir / r.file_name).exists() and size_ok((cruise_dir / r.file_name).stat().st_size, r.advertised_size_bytes))]
    print(f"{a.cruise}: {len(sel)} selected, {len(sel) - len(todo)} already on OAK, {len(todo)} to fetch ({sum(r.advertised_size_bytes for r in todo) / 1e9:.2f} GB)", flush=True)
    sess = requests.Session(); t_start = time.time(); moved = 0; log = []; status = "complete"
    prog = R.REPORT_DIR / f"fetch_progress_{a.cruise}.json"
    for k, r in enumerate(todo, 1):
        rec = fetch_file(r.url, r.file_name, int(r.advertised_size_bytes), cruise_dir, sess, a.throttle)
        log.append(rec); moved += rec["bytes_transferred"]
        if rec["status"] == "fetched":
            man["files"] = [f for f in man["files"] if f["name"] != r.file_name]
            man["files"].append({"name": r.file_name, "url": r.url, "size": rec["size"], "sha256": rec["sha256"], "source": "automated", "recorded_at": R.utc_now(),
                                 "attempts": rec["attempts"], "seconds": rec["seconds"]})
            R.save_manifest(cruise_dir, man)
        el = time.time() - t_start; rate = moved / 1e6 / max(el, 1)
        R.write_json(prog, {"cruise": a.cruise, "done": k, "todo": len(todo), "fetched": sum(1 for x in log if x["status"] == "fetched"),
                            "failed": [x for x in log if x["status"] != "fetched"], "gb_moved": round(moved / 1e9, 3), "elapsed_h": round(el / 3600, 3),
                            "mean_rate_MBps": round(rate, 4), "last": rec, "at": R.utc_now()})
        print(f"  [{k}/{len(todo)}] {r.file_name} {rec['status']} {rec['bytes_transferred'] / 1e6:.1f} MB in {rec['seconds']} s | mean {rate:.3f} MB/s, {el / 3600:.2f} h", flush=True)
        if el / 3600 >= a.rate_window and rate < a.min_rate:
            status = f"HOLD: mean throughput {rate:.3f} MB/s < {a.min_rate} MB/s after {el / 3600:.1f} h"; break
        if el / 3600 >= a.max_hours:
            status = f"HOLD: {a.max_hours} h wall time reached"; break
    remaining = [r.file_name for _, r in sel.iterrows() if not ((cruise_dir / r.file_name).exists() and size_ok((cruise_dir / r.file_name).stat().st_size, r.advertised_size_bytes))]
    if remaining and status == "complete":
        status = f"incomplete: {len(remaining)} files failed"
    el = time.time() - t_start
    summ = {"cruise": a.cruise, "status": status, "n_selected": int(len(sel)), "n_on_oak": int(len(sel) - len(remaining)), "n_remaining": len(remaining), "remaining": remaining,
            "gb_selected": round(float(sel.advertised_size_bytes.sum()) / 1e9, 3), "gb_transferred_this_run": round(moved / 1e9, 3), "wall_h_this_run": round(el / 3600, 3),
            "mean_rate_MBps_this_run": round(moved / 1e6 / max(el, 1), 4), "n_failed_this_run": sum(1 for x in log if x["status"] != "fetched"),
            "throttle_s": a.throttle, "workers": 1, "at": R.utc_now()}
    p = R.REPORT_DIR / f"fetch_summary_{a.cruise}.json"
    prev = json.loads(p.read_text()) if p.exists() else {"runs": []}
    prev["runs"].append(summ); prev["latest"] = summ
    R.write_json(p, prev)
    print(json.dumps(summ, indent=1, default=str))
    return 0 if not remaining else 2


if __name__ == "__main__":
    sys.exit(main())
