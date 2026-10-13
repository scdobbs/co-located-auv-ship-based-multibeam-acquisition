"""ACQ-R08b step 3 — must-hold checks (§4) and the report (§5) from candidates_measured.json / .csv.  Runs on the login node
(reads only the small outputs under reports_post_grl_review/ACQ-R08b/; never touches the sealed root)."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from src.acq_r08b import common as K
from src.acq_r01 import common as C

FORBIDDEN = re.compile(r"\b(depth_min|depth_max|min_z|max_z|zmin|zmax|z_min|z_max|minimum depth|maximum depth|depth range|depth_mean|mean depth|"
                       r"std|stdev|variance|slope|roughness|rugosity|spectrum|spectral|histogram|percentile|p(?:05|10|25|75|90|95)\b|quantile)\b", re.I)
ALLOWED_DEPTH = re.compile(r"depth_median_100m|depth_used_m|depth_needed|depth_source|depth_text", re.I)
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".pdf", ".eps", ".ps", ".webp", ".tif", ".tiff")
TABLE_COLS = ["status", "hr_id", "title", "hr_res_m", "crs", "n_files", "size_gb", "valid_km2", "depth_median_100m", "lr_cruise", "lr_sonar", "lr_year",
              "lr_raw_downloadable", "lr_swath_gb", "ship_coverage_km2", "ship_coverage_fraction", "lr_est_m", "cells_across_est", "ratio_est", "tiles_est",
              "same_site_as", "nearest_corpus_ref", "nearest_corpus_km", "releasable", "status_reason"]


def must_hold(df: pd.DataFrame, res: dict) -> dict:
    out = {}
    # 1. guard
    gl = [json.loads(l) for l in K.GUARD_LOG.read_text().splitlines()] if K.GUARD_LOG.exists() else []
    st = json.loads((K.OUT / "guard_selftest.json").read_text()) if (K.OUT / "guard_selftest.json").exists() else {}
    out["1_guard"] = {"selftest_probes": st.get("probes"), "selftest_blocked": st.get("blocked"), "all_blocked": st.get("all_blocked"), "control_opened": st.get("control_opened"),
                      "selftest_before_allowance": (st.get("allowance_installed") is False), "allowances": [g for g in gl if g.get("event") == "allowance_installed"],
                      "guard_log_events": Counter(g.get("event") for g in gl)}
    # 2. forbidden depth statistics in outputs and logs
    hits = []
    scan = [p for p in K.OUT.rglob("*") if p.is_file() and p.suffix.lower() in (".json", ".csv", ".md", ".jsonl", ".txt", ".out", ".err", ".geojson")
            and p.name != "must_hold_checks.json" and not p.name.endswith(".draft.md")]
    for p in scan:
        try:
            txt = p.read_text(errors="replace")
        except Exception:
            continue
        for m in FORBIDDEN.finditer(txt):
            ctx = txt[max(0, m.start() - 120): m.end() + 120].replace("\n", " ")
            if ALLOWED_DEPTH.search(ctx) and not re.search(r"\d", ctx.split(m.group(0))[-1][:12]):
                continue
            if re.search(r"skipped|companion|no minimum|forbidden|may not compute|beyond §3|AUX_RE|slope/shade|hits", ctx, re.I):
                continue          # prose naming the product types that were skipped / the rule itself, not a computed value
            hits.append({"file": str(p.relative_to(K.OUT)), "term": m.group(0), "context": ctx})
    out["2_only_depth_median_100m"] = {"files_scanned": len(scan), "forbidden_term_hits": hits[:40], "n_hits": len(hits),
                                       "depth_numbers_per_candidate": {r["hr_id"]: r.get("depth_median_100m") for r in res["results"]}}
    # 3. no image or plot files
    imgs = [str(p.relative_to(K.OUT)) for p in K.OUT.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXT]
    out["3_no_images"] = {"files_under_outputs": sum(1 for p in K.OUT.rglob("*") if p.is_file()), "image_or_plot_files": imgs}
    # 4. every candidate has a status with reason
    out["4_status"] = {r["hr_id"]: (r["status"], r.get("status_reason", "") or ("all §3 conditions hold" if r["status"] == "in range" else "")) for r in res["results"]}
    out["4_all_have_status"] = all(r.get("status") for r in res["results"])
    # 5. no designation
    out["5_no_designation"] = {"designation_files": [str(p) for p in K.OUT.rglob("*designat*")], "seed": None, "split": None}
    return out


def main(argv=None):
    res = json.loads((K.OUT / "candidates_measured.json").read_text())
    df = pd.read_csv(K.OUT / "candidates_measured.csv")
    dl = json.loads((K.OUT / "download_manifest.json").read_text())
    mh = must_hold(df, res); K.write_json(K.OUT / "must_hold_checks.json", mh)
    netk = Counter()
    if K.NET_LOG.exists():
        for l in K.NET_LOG.read_text().splitlines():
            try:
                netk[json.loads(l)["kind"]] += 1
            except Exception:
                pass
    order = {"in range": 0, "outside range": 1, "excluded": 2}
    df["_o"] = df.status.map(order).fillna(3); df = df.sort_values(["_o", "tiles_est"], ascending=[True, False])
    # merge same sites for the table
    rows = []
    seen = set()
    for _, r in df.iterrows():
        if r.hr_id in seen:
            continue
        mates = [m for m in str(r.get("same_site_as") or "").split(";") if m and m != "nan"]
        row = r.to_dict()
        if mates:
            grp = df[df.hr_id.isin([r.hr_id] + mates)]
            row["hr_id"] = " + ".join(grp.hr_id); row["tiles_est"] = grp.tiles_est.sum(); row["valid_km2"] = grp.valid_km2.sum(); row["size_gb"] = grp.size_gb.sum()
            row["status"] = "in range" if (grp.status == "in range").any() else row["status"]
            row["status_reason"] = " | ".join(f"{g.hr_id}: {g.status} {g.status_reason if isinstance(g.status_reason, str) else ''}".strip() for _, g in grp.iterrows())
            seen |= set(grp.hr_id)
        rows.append(row)
    tbl = pd.DataFrame(rows)
    (K.OUT / "candidate_table.csv").write_text(tbl[[c for c in TABLE_COLS if c in tbl.columns]].to_csv(index=False))
    from src.acq_r08.common import md_table
    inr = df[df.status == "in range"]
    r08 = pd.read_csv(K.R08 / "candidates_pool_a_in_range_and_uncertain.csv").set_index("hr_id")
    moves = []
    for _, r in df.iterrows():
        before = r08.status.get(r.hr_id, r.get("r08_status", "")) if r.hr_id in r08.index else r.get("r08_status", "")
        if before != r.status:
            moves.append(f"`{r.hr_id}`: {before} → **{r.status}** ({r.status_reason if isinstance(r.status_reason, str) and r.status_reason else 'all conditions hold'})")
    L = [f"# REPORT ACQ-R08b — second-test candidates downloaded; header, footprint, one rounded depth and tile count measured", "",
         f"**Directive:** `ACQ-R08b_directive_blind_header_footprint_2026-10-13.md`. **Run:** {K.STAMP}, jobs in `run_jobs.json`. **Code:** `src/acq_r08b/` (`common` = guard allowance, self-test, write guard, network log; `download.py`, `measure.py`, `report.py`, `preserve.py`); guard extension in `src/acq_r01/common.py` (`sealed_candidates_v3` root + every candidate id refused by every patched reader; a named allowance for the §3 scripts only).",
         f"**Sealed root:** `{K.SEALED}` (directories 2750 setgid, files 0440; group `hilley` read only). **Evidence:** `guard_selftest.json`, `guard_log.jsonl`, `network_log.jsonl`, `download_manifest.json`, `SHA256SUMS_candidates`, `candidates_measured.json/.csv`, `candidate_table.csv`, `footprints/`, `must_hold_checks.json`.",
         "**Steve's rulings (2026-10-13, recorded):** " + "; ".join(K.RULINGS) + ".", "**Certainty labels:** CONFIRMED / CONTRADICTED / COULD NOT CHECK.", "",
         "## 1. Bottom line", "", "<<BULLETS>>", "",
         "## 2. Candidate table (§5.1; sites merged under `same_site_as`; sorted by status then `tiles_est`)", ""]
    L += md_table(tbl, [c for c in TABLE_COLS if c in tbl.columns], 60)
    L += ["", f"Not processed (directive §2): " + "; ".join(f"`{k}` — {v}" for k, v in K.NOT_PROCESSED.items()) + ".", "",
          "## 3. Summary (§5.2)", "", "<<SUMMARY>>", "", "## 4. Changes from ACQ-R08 (§5.3)", ""] + [f"- {m}" for m in moves] + ["",
          "## 5. Exposure statement (§5.4) — the exact numbers produced per candidate", "",
          "For every downloaded candidate the scripts wrote, and the executor saw, only: file names, sizes and sha256; grid width/height, cell size (native and metres), CRS, extent, nodata value and dtype per grid; "
          "the number of bathymetry grids and companion files skipped; `valid_km2`; the footprint polygon (block-pooled to ≈ 50 m, simplified 50 m) and its area; `depth_median_100m` (one integer, nearest 100 m); "
          "the ship cruise id, sonar, year, swath file count and size from listings; navigation-track counts, the half-swath buffer, ship-coverage polygon, area and fraction; `lr_est_m`, `cells_across_est`, `ratio_est`, `tiles_est`; "
          "`same_site_as`; nearest corpus footprint and distance; status and reason. No other depth-derived number exists in any output or log (check §6.2).", "",
          "Per candidate:", ""]
    for r in res["results"]:
        if r.get("status") == "excluded":
            L.append(f"- `{r['hr_id']}`: nothing downloaded; ship-partner access checks only (HTTP status per PANGAEA dataset listing)."); continue
        L.append(f"- `{r['hr_id']}`: {r.get('n_files')} files / {r.get('size_gb')} GB; {r.get('n_bathymetry_grids')} bathymetry grids (groups {json.dumps(r.get('resolution_groups'))}); hr_res_m {r.get('hr_res_m')}; CRS {r.get('crs')}; extent {r.get('extent_4326')}; "
                 f"valid_km2 {r.get('valid_km2')}; footprint {r.get('hr_footprint_km2')} km²; depth_median_100m {r.get('depth_median_100m')}; LR {r.get('lr_cruise')} ({r.get('lr_sonar')}, {r.get('lr_year')}; {r.get('lr_n_swath_files')} swath files, {r.get('lr_swath_gb')} GB); "
                 f"coverage {json.dumps({k: v for k, v in (r.get('ship_coverage') or {}).items() if k in ('n_nav_files', 'n_tracks_in_aoi', 'half_swath_m', 'coverage_km2', 'coverage_fraction', 'method')})}; lr_est_m {r.get('lr_est_m')}; cells {r.get('cells_across_est')}; ratio {r.get('ratio_est')}; tiles_est {r.get('tiles_est')}; "
                 f"same_site_as {r.get('same_site_as') or '—'}; nearest {r.get('nearest_corpus_ref')} {r.get('nearest_corpus_km')} km.")
    mh_short = {k: v for k, v in mh.items() if k != "4_status"}
    mh_short["2_only_depth_median_100m"] = {k: v for k, v in mh["2_only_depth_median_100m"].items() if k != "forbidden_term_hits"}
    L += ["", "## 6. Must hold (§4)", "", "```", json.dumps(mh_short, indent=1, default=str)[:6000], "```", "",
          "Network requests by kind: " + "; ".join(f"{k} ×{v}" for k, v in netk.most_common()) + ".", "", "<<HOLDS>>", "",
          "## 8. Not pursued", "", "- Legacy single-beam NOS surveys as coarse partners; re-screening the 15 outside-range Pool A rows (directive §8).", "- Any statistic, image or view of the candidate bathymetry beyond §3; downloading or gridding ship swath; co-registration; designation (§7).", ""]
    (K.OUT / f"REPORT_ACQ-R08b_{K.STAMP}.draft.md").write_text("\n".join(L))
    print("draft written;", len(inr), "in range;", len(moves), "moves; must-hold hits:", mh["2_only_depth_median_100m"]["n_hits"], "images:", mh["3_no_images"]["image_or_plot_files"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
