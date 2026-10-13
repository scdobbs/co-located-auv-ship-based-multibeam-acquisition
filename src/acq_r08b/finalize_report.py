"""ACQ-R08b — fill the report draft's placeholders (bottom line, summary, HOLDs) from the measured results."""
from __future__ import annotations

import json
import sys

import pandas as pd

from src.acq_r08b import common as K

R = K.OUT


def main(argv=None):
    draft = (R / f"REPORT_ACQ-R08b_{K.STAMP}.draft.md").read_text()
    res = json.loads((R / "candidates_measured.json").read_text())["results"]
    mh = json.loads((R / "must_hold_checks.json").read_text())
    dl = json.loads((R / "download_manifest.json").read_text())
    st = json.loads((R / "guard_selftest.json").read_text())
    by = {r["hr_id"]: r for r in res}
    inr = [r for r in res if r["status"] == "in range"]; outr = [r for r in res if r["status"] == "outside range"]; exc = [r for r in res if r["status"] == "excluded"]
    # distinct sites
    sites, seen = [], set()
    for r in inr:
        if r["hr_id"] in seen:
            continue
        grp = [r["hr_id"]] + [m for m in str(r.get("same_site_as") or "").split(";") if m and m in by and by[m]["status"] == "in range"]
        seen |= set(grp); sites.append(grp)
    n_dl = sum(1 for r in dl["candidates"].values() if r.get("downloaded")); gb_dl = sum(r.get("bytes", 0) for r in dl["candidates"].values()) / 1e9
    tiles_sites = [sum(by[h]["tiles_est"] for h in g) for g in sites]
    swath_gb = {}
    for g in sites:
        for h in g:
            swath_gb[by[h]["lr_cruise"]] = by[h].get("lr_swath_gb")
    moved_in = [r["hr_id"] for r in inr if r["r08_status"] != "in range"]
    bullets = [
        f"1. **{len(inr)} of the 10 downloaded candidates are in range, forming {len(sites)} distinct sites; Kolumbo was not downloaded (CONFIRMED; `candidates_measured.csv`, `candidate_table.csv`).** "
        f"Downloaded: {n_dl} candidates, {gb_dl:.2f} GB, {sum(len(r.get('files', [])) for r in dl['candidates'].values())} files, sha256 in `SHA256SUMS_candidates`, sealed under `sealed_candidates_v3/` (dirs 2750 setgid, files 0440). "
        f"In range: " + "; ".join(f"`{'+'.join(g)}` ({sum(by[h]['tiles_est'] for h in g):,} tiles, {by[g[0]]['depth_median_100m']} m, LR {by[g[0]]['lr_cruise']} {by[g[0]]['lr_sonar']} {by[g[0]]['lr_year']}, cells {by[g[0]]['cells_across_est']})" for g in sites) + ". "
        f"Outside range: " + "; ".join(f"`{r['hr_id']}` ({r['status_reason']})" for r in outr) + ". Excluded: " + "; ".join(f"`{r['hr_id']}` ({r['status_reason'][:90]}…)" for r in exc) + ".",
        f"2. **Changes from ACQ-R08 (§5.3).** Moved into range: {', '.join(f'`{h}`' for h in moved_in) or 'none'} — their catalog bounding boxes had made tiles and footprints upper bounds, and the measured footprints, depths and navigation coverage resolve them; the three ACQ-R08 in-range rows stay in range with fewer tiles than estimated ({', '.join(f'{h} {by[h]["tiles_est"]}' for h in ('MGDS:31860', 'MGDS:31675', 'MGDS:31954') if h in by)}) because the true validity masks are smaller than the catalog boxes and repeat epochs / grid versions are counted once. "
        f"`SEANOE:55744` (Marmara) moved to outside range: its only accessible ship partner (M51/4, Hydrosweep DS-2, 2001) has no track within half a swath of the AUV footprint (per-file start positions from the PANGAEA listing). `PANGAEA:958275` (Kolumbo) is excluded: all five ship partners answer HTTP 401 on the file listing (§2 rule), nothing downloaded.",
        f"3. **Blindness (CONFIRMED; `guard_selftest.json`, `guard_log.jsonl`, `must_hold_checks.json`).** Guard self-test before the first download: {st['probes']} probes ({st['targets']} sealed targets × {len(st['readers'])} readers), {st['blocked']} blocked, control file opened, no allowance installed; the §3 scripts then installed the named allowance ({len(mh['1_guard']['allowances'])} events logged). "
        f"The sealed root and every candidate id are refused by every patched reader in every other process (this also seals the September copies `raw_hr/MGDS_30368` and `raw_hr/PANGAEA_958275` on OAK). Forbidden-statistic grep over {mh['2_only_depth_median_100m']['files_scanned']} output/log files: {mh['2_only_depth_median_100m']['n_hits']} hits; image/plot files under the outputs: {len(mh['3_no_images']['image_or_plot_files'])}; every candidate has a status and reason; nothing designated.",
        "4. **What was measured, and how (CONFIRMED; `candidates_measured.json`).** Per grid: header only (size, cell size, CRS, extent, nodata); validity mask from finite-and-not-nodata cells (|z| < 20 km); `hr_footprint` = union of the masks of the chosen resolution group, block-pooled to ≈ 50 m and simplified 50 m in local UTM; `valid_km2` = that union's area (sum over grids is reported separately, repeat epochs and versions counted once); "
        "`depth_median_100m` = the median of |z| over the chosen grids rounded to 100 m — the only depth-derived number; companion products (backscatter, amplitude, sidescan, count/sd, slope/shade, difference and interpolated grids) skipped by name; grids coarser than 5 m bundled with a record (La Jolla's 15 m regional grid) treated as context, the finest ≤ 5 m group covering ≥ 80 % of the largest ≤ 5 m group used.",
        "5. **Ship side (CONFIRMED by listing).** Raw swath and `.fnv` navigation exist on NCEI for every NCEI cruise used (counts and GB in the table); coverage = per-file navigation tracks buffered by half the nominal swath width (3.5 × depth for Kongsberg EM12x/30x/EM300, 3.0 × for SeaBeam 2100/2112/2000, 2.0 × for Hydrosweep DS; documented in `common.SWATH_FACTOR`), intersected with the footprint; "
        "where the primary cruise gives < 300 tiles the ACQ-R08 alternatives are tried in order and the table's `lr_cruises_tried` records each attempt (every in-range row below used its primary cruise). `tiles_est` = 256-px windows at stride 128 with ≥ 50 % of cells inside footprint ∩ coverage on a raster at `hr_res_m` in local UTM.",
        f"6. **Same site (§3).** `MGDS:18210` and `MGDS:31811` (both AT15-63, Galápagos Spreading Center, 1 m and 2 m products) overlap and are one site; all other in-range candidates are > 10 km apart (nearest corpus footprint ≥ {min(r['nearest_corpus_km'] for r in inr):.0f} km for every in-range row).",
        f"7. **Ship raw-swath volume for the later acquisition step (§5.2):** " + ", ".join(f"{c} {g} GB" for c, g in swath_gb.items() if g is not None) + f" → {sum(g for g in swath_gb.values() if g):.1f} GB in total across the in-range sites.",
        "8. **Challenge notes (applied as stated).** (i) `valid_km2` is reported as the union of the chosen grids' masks (the directive's 'area of the validity mask'), with the per-grid sum alongside; (ii) the finest-grid rule needed a cap at 5 m to ignore the regional ship grid bundled in the La Jolla record; (iii) Marmara's HR grid was downloaded (its ship partner listing answered 200) before coverage showed no overlap; it stays sealed. No HOLD raised.",
    ]
    settings = {"MGDS:31860": "Chile margin / triple-junction area (46.3°S), Sentry", "MGDS:31675": "Bermuda platform (32.7°N), Sentry", "MGDS:31954": "Dorado Outcrop, Cocos plate (9.1°N), Sentry",
                "MGDS:30368": "Escanaba Trough, Gorda Ridge (41°N), AUV", "MGDS:18210": "Galápagos Spreading Center (2.3°N), near-bottom multibeam", "MGDS:31811": "Galápagos Spreading Center (2.3°N), AUV",
                "MGDS:24756": "Monterey Canyon (36.7°N), MBARI Mapping AUV, repeat surveys", "MGDS:22436": "Mid-Atlantic Ridge 16.5°N, Sentry", "MGDS:21415": "La Jolla Canyon (32.8°N), near-bottom"}
    summary = [f"- **Distinct in-range sites: {len(sites)}**, total `tiles_est` {sum(tiles_sites):,} (per site: " + ", ".join(f"{'+'.join(g)} {t:,}" for g, t in zip(sites, tiles_sites)) + ").",
               "- **Settings and regions:** " + "; ".join(f"{'+'.join(g)} — {settings.get(g[0], '')}" for g in sites) + ". Basins: Pacific " + str(sum(1 for g in sites if by[g[0]].get('basin', '') == 'Pacific' or g[0] in ('MGDS:31860', 'MGDS:31954', 'MGDS:30368', 'MGDS:18210', 'MGDS:24756', 'MGDS:21415'))) + ", Atlantic " + str(sum(1 for g in sites if g[0] in ('MGDS:31675', 'MGDS:22436'))) + ".",
               f"- **Ship raw swath to fetch later:** " + ", ".join(f"{c} {g} GB" for c, g in swath_gb.items() if g is not None) + f"; total {sum(g for g in swath_gb.values() if g):.1f} GB (from NCEI listings; nothing fetched).",
               f"- **Downloaded HR volume:** {gb_dl:.2f} GB in {n_dl} sealed directories; Kolumbo not downloaded."]
    holds = ["## 7. HOLDs", "", "None. Two judgment calls are recorded as challenge notes in §1.8 for Steve to overrule if wanted: the 5 m cap in the finest-grid rule, and the download of the Marmara grid before its coverage was known."]
    out = draft.replace("<<BULLETS>>", "\n".join(bullets)).replace("<<SUMMARY>>", "\n".join(summary)).replace("<<HOLDS>>", "\n".join(holds))
    (R / f"REPORT_ACQ-R08b_{K.STAMP}.md").write_text(out)
    print("written", len(out.splitlines()), "lines; sites", sites, "tiles", tiles_sites)
    return 0


if __name__ == "__main__":
    sys.exit(main())
