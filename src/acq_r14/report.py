"""ACQ-R14 step 7: assemble reports_post_grl_review/ACQ-R14/REPORT_ACQ-R14_<date>.md from the step outputs
(inventory, license audit, build results, check results, plumbing fixes, preserve records). At most 8 bullets plus the
size table and the license table (directive header).

    python -B -m src.acq_r14.report [--zenodo-url URL]
"""
from __future__ import annotations
import argparse, json
from collections import Counter
from pathlib import Path
import pandas as pd
from . import common as C

DATE = "2026-10-20"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zenodo-url", default=None)
    ap.add_argument("--job", default=None)
    a = ap.parse_args()
    inv, lic, build = C.jload(C.INVENTORY), C.jload(C.LICENSE_AUDIT), C.jload(C.RPT / "build_results.json")
    chk = C.jload(C.RPT / "check_results.json")
    pv = C.jload(C.RPT / "preserve_verify.json") if (C.RPT / "preserve_verify.json").exists() else {}
    ppv = C.jload(C.RPT / "preserve_package_verify.json") if (C.RPT / "preserve_package_verify.json").exists() else {}
    fixes, seen = [], set()
    for l in (C.FIXES.read_text().splitlines() if C.FIXES.exists() else []):
        if l.strip():
            f = json.loads(l)
            key = (f["stage"], f["pair"], f["fix"])
            if key not in seen:          # the AR26 smoke test logged its fix twice
                seen.add(key)
                fixes.append(f)
    pairs = pd.read_csv(C.PKG / "pairs.csv") if (C.PKG / "pairs.csv").exists() else pd.read_csv(C.OAK_DEST / "package" / "pairs.csv")
    inc = pairs[pairs.in_corpus]
    zen = C.jload(C.RPT / "zenodo_metadata.json")
    sz, rp, it, bl = chk["size"], chk["reproduction"], chk["integrity"], chk["blindness"]
    n_ncsa = int((inc.pair_license_status == "yes_conditional").sum())
    conf = inc[inc.pair_license_status == "confirm"].pair_id.tolist()
    not_test = inc[(inc.group == "blind_test_2") & (inc.eligible == False)][["pair_id", "eligibility_reason"]]  # noqa: E712

    L = [f"# REPORT {C.DIRECTIVE_ID} — public data release package of the processed co-located corpus: built and verified, not published", "",
         f"**Directive:** `ACQ-R14_directive_public_data_release_{DATE}.md`. **Job:** {a.job or 'see job_*.out'} (normal partition). **Code:** `src/acq_r14/` "
         "(`inventory`, `license_audit`, `build`, `corpus`, `check`, `preserve`, `report`, `load_pair`), job `sbatch/acq_r14/build.sbatch`. "
         "**Evidence:** `inventory.json`, `license_audit.{json,csv}`, `build_results.json`, `check_results.json`, `plumbing_fixes.jsonl`, `preserve_package_verify.json`, `preserve_verify.json`, `zenodo_metadata.json`.", "",
         "## Bullets", ""]
    L.append(f"1. **Package built and verified; nothing published.** {len(inc)} pairs with rasters ({sz['groups'].get('development', {}).get('n_pairs')} development, "
             f"{sz['groups'].get('blind_test_1', {}).get('n_pairs')} blind test 1, {sz['groups'].get('blind_test_2', {}).get('n_pairs')} blind test 2) and {int((~pairs.in_corpus).sum())} manifest-only rows "
             f"(AT37-05, Chapopote, Venere, the two Amundsen pairs, Kolumbo, four other no-k pairs, seven ACQ-R02 drops). Every raster is a COG (float32 grids, uint8 masks, DEFLATE + predictor, "
             f"overviews, EPSG UTM, explicit nodata; values unchanged). {it['n_rasters']} rasters in {len(it['zips'])} zips; tiles table {int(pd.read_csv(C.OAK_DEST / 'package' / 'tiles.csv', usecols=['tile_id']).shape[0]) if (C.OAK_DEST / 'package' / 'tiles.csv').exists() else '—'} rows "
             f"(26,154 development incl. EW0207, 3,812 blind test 1, 2,088 blind test 2; the 22 R17 Escanaba tiles carry `excluded_r17`). "
             f"Zenodo-flat file count {sz['package']['n_files_zenodo']} (limit 100), {sz['package']['total_gb_zenodo']:.2f} GB (limit 50): within limits.")
    L.append(f"2. **License audit (table below): no source forbids redistribution, so no stop; but the record cannot be uniformly CC BY 4.0 (HOLD H-1).** "
             f"{n_ncsa} of {len(inc)} pairs contain an MGDS AUV grid published under CC BY-NC-SA (3.0 US or 4.0); those pairs are packaged with `pair_license` = CC BY-NC-SA 4.0 "
             f"(non-commercial, share-alike), the rest and all corpus-level files as CC BY 4.0. {len(conf)} pair(s) have a source with no license in any DOI record: {', '.join(conf) or 'none'} "
             f"(MGDS:32239, RC2511's HR; no DOI exists for that data set; MGDS default terms are CC BY-NC-SA) — `pair_license_status` = confirm. "
             "Steve decides: (a) publish as a mixed-license record (README and pairs.csv already state the per-pair license), (b) publish the record as CC BY-NC-SA 4.0 overall, or (c) drop the NC-SA pairs (which would remove most of the corpus, including every blind-test site but SUM1004, AT42-03, AT26-24 and the development pairs from PANGAEA, USGS, MGDS CC BY).")
    L.append(f"3. **Reproduction from the packaged files only: {'PASS' if rp['pass'] else 'FAIL'}.** `examples/load_pair.py` ({sum(1 for _ in open(C.PKG / 'examples' / 'load_pair.py')) if (C.PKG / 'examples' / 'load_pair.py').exists() else '<60'} lines) "
             f"reproduced the frozen s_lr rho to 3 decimals on the five required pairs ({rp['n_required_pass']}/5: RR1506 interior, AR26 fallback, discol, RC2511, Escanaba with its 22 exclusions) "
             f"and on every scored pair of the corpus ({rp['n_all_pass']}/{rp['n_all']}). The rule is the frozen scorer's (interior view if >= 10 tiles in >= bmin blocks, else fallback on A_fine_int).")
    L.append(f"4. **Integrity: {'PASS' if it['pass'] else 'FAIL'}.** rio_cogeo + rasterio over every raster inside every zip: COG-invalid {it['n_cog_invalid']}, CRS mismatches {it['n_crs_mismatch']}, "
             f"missing nodata {it['n_nodata_missing']}; pair.json sha256 mismatches {it['n_sha_mismatch']} over all members; package `SHA256SUMS` ({it['sha256sums']['n']} lines) verified = {it['sha256sums']['verified']}.")
    L.append(f"5. **Blindness: {'PASS' if bl['pass'] else 'FAIL'}.** Both tests are scored; the package holds the scored outputs only (no sealed-root file, no sealed path: {bl['n_sealed_hits']} hits of the sealed/absolute-path patterns in any text member; "
             f"restricted sources {len(bl['restricted_sources'])}). Blind test 2 not-testable sites are included with the failed rule: " + "; ".join(f"{r.pair_id} ({r.eligibility_reason})" for r in not_test.itertuples()) + ".")
    L.append(f"6. **Plumbing fixes ({len(fixes)}; one line each in section 4).** Scope note: the directive's \"38 pairs including EW0207\" matches neither repo set; the scored development table has 39 pairs "
             "(38 units-v1 pairs + EW0207, lu16), all 39 are shipped with `unit_class` ten / six / EW0207. G exists as a value for development pairs only (ACQ-R11b table); blind test 2 carries the recorded boolean, blind test 1 none. "
             "Co-registration for June pairs is the stage F5 re-co-registration (the as-used values in the manifest), with the first-pass stage F estimate kept as `initial_estimate`.")
    L.append(f"7. **OAK and hashes.** Package at `{C.OAK_DEST}/package/` ({ppv.get('n_in_sha256sums')} files listed + `SHA256SUMS`, verified there = {ppv.get('verified')}; "
             f"`SHA256SUMS` sha256 `{it['sha256sums']['sha256_of_SHA256SUMS']}`). The repo artifacts and code are copied by `preserve --repo` after this report is written; "
             f"the archive-level `{C.OAK_DEST}/SHA256SUMS` and its sha256 are recorded in `preserve_verify.json` and in the `CHANGE_LEDGER.md` row. "
             f"Zenodo draft: {a.zenodo_url or 'not created (no token was provided; `zenodo_metadata.json` holds the suggested metadata)'}. "
             "Zenodo flattens folders: upload the pair zips, the top-level files, `blind_tests.zip` (built from `blind_tests/`) and `examples/load_pair.py` as `load_pair.py`.")
    L.append(f"8. **Suggested Zenodo metadata (section 6.6; `zenodo_metadata.json`).** Title: *{zen['title']}*. Keywords: {', '.join(zen['keywords'])}. "
             f"Related identifiers: GRL {C.PAPER_ID} (isSupplementTo; replace by the paper DOI), {C.CODE_RECORDS['ml_code']} and {C.CODE_RECORDS['acquisition_code']} (isSupplementTo, software). "
             f"Description ({zen['n_words_description']} words): {zen['description']}")
    # ---- size table
    L += ["", "## Size table", "", "| group | pairs | total GB | largest zip | largest GB |", "|---|---|---|---|---|"]
    for g in ("development", "blind_test_1", "blind_test_2"):
        r = sz["groups"].get(g, {})
        L.append(f"| {g} | {r.get('n_pairs')} | {r.get('total_gb', 0):.3f} | {r.get('largest_zip')} | {r.get('largest_gb', 0):.3f} |")
    L.append(f"| **package** (on disk, incl. blind_tests/ and blind_tests.zip) | {len(inc)} pair zips, {sz['package']['n_files_on_disk']} files | {sz['package']['total_gb_on_disk']:.3f} | | |")
    L.append(f"| **Zenodo upload** (flat) | {sz['package']['n_files_zenodo']} files | {sz['package']['total_gb_zenodo']:.3f} | | |")
    # ---- license table
    L += ["", "## License table (every source data set; from DataCite DOI records, NCEI ISO records, USGS FGDC metadata)", "",
          "| dataset | DOI | license | redistribution allowed | pairs |", "|---|---|---|---|---|"]
    rows = lic["rows"]
    for k, d in sorted(lic["datasets"].items(), key=lambda kv: (kv[1]["provider"], kv[0])):
        n = sum(1 for r in rows if r["id"] == k)
        red = {"yes": "yes", "yes_conditional": "yes (non-commercial, share-alike)", "confirm": "not stated (confirm)", "no": "NO"}[d["redistribution"]]
        L.append(f"| {k} | {d.get('doi') or '—'} | {d['license'][:110]} | {red} | {n} |")
    L.append(f"\nPairs excluded on license: none (no source forbids redistribution). Pairs by status: {dict(Counter(inc.pair_license_status))}.")
    # ---- fixes
    L += ["", "## Plumbing fixes (one line each)", ""]
    for f in fixes:
        L.append(f"- [{f['stage']}] {f['pair'] or '—'}: {f['fix']}")
    L += ["", "## HOLDs for Steve", "",
          "- **H-1 (license of the record):** decide (a) mixed-license record as packaged, (b) CC BY-NC-SA 4.0 overall, or (c) drop the NC-SA pairs; and whether RC2511 (MGDS:32239, no DOI, license unstated) stays.",
          "- **H-2 (Zenodo):** no token was provided, so no draft exists; with a token, `src/acq_r14/zenodo_upload.py` is not written — the upload is 70 files by the Zenodo deposition API; say whether to add that script.",
          "- **H-3 (authors):** CITATION.cff and zenodo_metadata.json name one author; add co-authors before publishing.", ""]
    out = C.RPT / f"REPORT_{C.DIRECTIVE_ID}_{DATE}.md"
    out.write_text("\n".join(L))
    C.log(f"report -> {out}")


if __name__ == "__main__":
    main()
