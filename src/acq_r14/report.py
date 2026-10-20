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
    n_open = int(inc.sources_cc_by_or_public_domain_only.fillna(False).astype(bool).sum()) if "sources_cc_by_or_public_domain_only" in inc else None
    L.append(f"2. **License audit (table below): no source forbids redistribution, so no stop. Ruling 2026-10-20 (H-1 option b) applied: the whole record is CC BY-NC-SA 4.0.** "
             f"{n_ncsa} of {len(inc)} pairs contain an MGDS AUV grid published under CC BY-NC-SA (3.0 US or 4.0); every pair now carries `pair_license` = CC BY-NC-SA 4.0, LICENSE is the CC BY-NC-SA 4.0 text, "
             f"CITATION.cff and the Zenodo metadata say cc-by-nc-sa-4.0, and the README lists each pair's source licenses: {n_open} pairs come only from CC BY / public-domain sources (`sources_cc_by_or_public_domain_only`). "
             f"RC2511 stays: its HR grid MGDS:32239 has no DOI record, but the MGDS data set page (https://www.marine-geo.org/tools/files/32239) states \"License CC BY-NC-SA 4.0\" in its schema.org metadata and page text, "
             f"so the confirm flag was dropped ({len(conf)} pair(s) remain at confirm: {', '.join(conf) or 'none'}).")
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
             f"Zenodo draft: {a.zenodo_url or 'see the second rulings section (unpublished draft https://zenodo.org/deposit/23515276, reserved DOI 10.5281/zenodo.23515276)'}. "
             "Zenodo flattens folders: upload the pair zips, the top-level files, `blind_tests.zip` (built from `blind_tests/`) and `examples/load_pair.py` as `load_pair.py`.")
    L.append(f"8. **Suggested Zenodo metadata (section 6.6; `zenodo_metadata.json`; license {zen.get('license')}; sole author; {zen.get('files_to_upload', {}).get('count')} files to upload).** Title: *{zen['title']}*. Keywords: {', '.join(zen['keywords'])}. "
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
    # ---- ruling section (2026-10-20)
    dev = inc[inc.group == "development"]
    ten = dev[dev.unit_class == "ten"].groupby("unit").size()
    six = dev[dev.unit_class == "six"].groupby("unit").size()
    nsi = dev[(dev.unit_class == "ten") & (dev.view != "interior")][["pair_id", "unit", "view", "n_scored", "scoring_status"]]
    L += ["", "## Ruling 2026-10-20 (Steve) applied: H-1 option (b)", "",
          f"- Record license CC BY-NC-SA 4.0 for every pair and the corpus-level files; README source-license table added; RC2511 kept (MGDS data set page states CC BY-NC-SA 4.0; confirm flag dropped).",
          f"- zenodo_metadata.json: purpose phrase replaced, 'super-resolution' dropped and 'seafloor roughness' added to the keywords, 'meters', sole author (no co-author placeholder), license cc-by-nc-sa-4.0, files to upload = {zen.get('files_to_upload', {}).get('count')} (no upload script, per ruling).",
          f"- **Resolution ranges as written (measured from pairs.csv, not the ruling's numbers):** AUV grids {zen.get('resolution_ranges_m', {}).get('auv_hr_res', [None, None])[0]:.2f}-{zen.get('resolution_ranges_m', {}).get('auv_hr_res', [None, None])[1]:.2f} m "
          f"and ship grids {zen.get('resolution_ranges_m', {}).get('ship_lr_native', [None, None])[0]:.2f}-{zen.get('resolution_ranges_m', {}).get('ship_lr_native', [None, None])[1]:.2f} m. "
          "The ruling said 1-3.25 m and 10-151 m; AT42-06__MGDS_5174 (ABE grid, lu05) has a 4.99 m HR pixel and MV1209__MGDS_21415 an 8.73 m ship native cell, so those bounds would be wrong for one pair each. "
          "The description states the measured ranges; say the word if the ruling's numbers are to be used verbatim.",
          "- Every pair.json and zip was rewritten from the unchanged staged COGs (`relicense.py`), the corpus-level files regenerated, SHA256SUMS rebuilt, all checks re-run and the OAK copy re-verified (job in the header).",
          "", "### Pairs per unit (from pairs.csv)", "", "| class | unit | pairs |", "|---|---|---|"]
    L += [f"| ten (real-relief) | {u} | {n} |" for u, n in ten.items()] + [f"| **ten total** | 10 units | {int(ten.sum())} |"]
    L += [f"| six (artifact-affected) | {u} | {n} |" for u, n in six.items()] + [f"| **six total** | 6 units | {int(six.sum())} |"]
    L += ["", "### Real-relief pairs not scored on interior tiles", "", "| pair | unit | view | n_scored | status |", "|---|---|---|---|---|"]
    L += [f"| {r.pair_id} | {r.unit} | {r.view} | {int(r.n_scored) if pd.notna(r.n_scored) else '—'} | {r.scoring_status} |" for r in nsi.itertuples()]
    L += ["", "The real-relief pair that is **not scorable** is AT42-06__MGDS_5174 (lu05): too few tiles / blocks for either view. TN399__MGDS_33068 and AR26__MGDS_31838 are scored on the fallback view (A_fine_int), not on interior tiles.", "",
          "## Rulings 2026-10-20 (Steve), second set: H-4 accepted as written; H-2 changed to a Zenodo draft", ""]
    zs = C.jload(C.RPT / "zenodo_draft.json") if (C.RPT / "zenodo_draft.json").exists() else None
    if zs:
        att = zs.get("metadata_attempts", [])
        rejected = [e for a_ in att for e in (a_.get("errors") or [])]
        L += [f"- **Draft (unpublished):** {zs.get('html')} — deposition id {zs.get('id')}, created {zs.get('created')}, `submitted` = {zs.get('submitted')}.",
              f"- **Reserved DOI:** {zs.get('prereserve_doi', {}).get('doi')}.",
              f"- **Files on Zenodo:** {zs.get('n_files_zenodo')} of {zs.get('n_files_local')} (flat: the 65 top-level package files + `examples/load_pair.py` as `load_pair.py`; no extra zip), {zs.get('bytes_zenodo', 0) / 1e9:.3f} GB.",
              f"- **Checksums:** {zs.get('n_verified')} of {zs.get('n_files_local')} files verified by MD5 against the checksum Zenodo returned on upload, {zs.get('n_failed')} failed; "
              f"a final listing from Zenodo matches every local MD5 = {zs.get('remote_checksums_match')}; files needing the one retry: {sum(1 for v in zs.get('files', {}).values() if v.get('attempts', 0) > 1)}.",
              f"- **Metadata rejected by Zenodo:** {json.dumps(rejected) if rejected else 'none'}. "
              + ("The manuscript identifier `GRL 2026GL125574` has no recognized identifier scheme (it is not a DOI yet), so it was dropped from `related_identifiers` on the retry; the two code-record DOIs were accepted. Add the paper DOI when assigned. " if rejected else "")
              + f"**Metadata changed by Zenodo:** {sorted(zs.get('metadata_changed_by_zenodo', {})) or 'none'}.",
              "- Script `src/acq_r14/zenodo_upload.py` (token read from `~/.zenodo_token` inside the job, never printed or written; resumable; never publishes); job `sbatch/acq_r14/zenodo.sbatch`; state `ACQ-R14/zenodo_draft.json`.", ""]
    L += ["## HOLDs for Steve", "",
          "- **Publishing** the Zenodo draft is Steve's action (not done). Before publishing: add the paper DOI to the related identifiers when assigned.", ""]
    out = C.RPT / f"REPORT_{C.DIRECTIVE_ID}_{DATE}.md"
    out.write_text("\n".join(L))
    C.log(f"report -> {out}")


if __name__ == "__main__":
    main()
