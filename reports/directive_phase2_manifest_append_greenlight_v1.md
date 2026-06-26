# Directive — Canonical manifest append: GREENLIT (34 pairs), pending one terrain confirmation v1

**Date:** 2026-06-26
**From:** Assessment instance · **To:** Claude Code (Sherlock)
**Builds on:** `stage_manifest_completeness_report_2026-06-26.md` (M1 parity verified independently — accepted).
**Status:** ✅ Artifact at canonical parity (verified). ✅ Pair membership FINAL (34). ⛔ Append executes on Steve's M2 terrain confirmation (the single remaining input). 21 read-only; backup retained.

---

## 0. Verified by assessment (independent check of the staged artifact)
- Per-field parity confirmed: checksums real sha256 (no hr/lr collision), `res_ratio` arithmetically correct + physically plausible (22–320×), `footprint_wkt` = path (matches canonical convention), pair_ids unique, canonical 21 preserved (18 cal_dig + discol + ccz + tag), independence fields carry real distinct ship sonars vs AUV Resons.
- PSR honestly left undefined where no interior peak exists (not fabricated). ✅

## 1. Pair membership — FINAL (Steve's QGIS re-assessment)

**Drop (3) — unconfirmed co-registration on QGIS re-review** (offset with no/degenerate NCC peak; **data is real — eligible for future manual control-point co-registration, not a data-quality exclusion**):
- `KN210-05×22436` (151 m offset, no peak)
- `FK006B×20811` (PSR = −8.97, degenerate)
- `KN204-01×31675` (51 m offset, no peak)

**Keep `KIWI10RR×24499`:** metric-unconfirmed (11 m offset, no interior peak) **but** G-PROV independence cleared on real evidence (SeaBeam 2100/1998 LR vs Sentry/2017 HR, cross_cruise) and QGIS overlay confirmed by Steve. Advances.

**Resulting corpus: 34 = 21 validated + 13 new.** Eval set = 2 (`NA090×31212`, `TN159×21981`), unchanged. No orphaning (the 3 dropped are standalone, not sub-grids of SKQ/TN268).

The 13 new: `AT37-13×31199`, `AT42-03×32007`, `EW9801×31425`, `NA080×31290`, `NA090×31212`, `RR1506×29779`, `TN268×30466`, `TN399×30373`, `FK181031×24367`, `AR26×31838`, `TN159×21981`, `TN299×27339`, `KIWI10RR×24499`.

## 2. M2 terrain reclassifications — confirm before write ⛔ (last input)
Dropping `KN210-05` moots its reclass; **6 remain on kept pairs.** Steve to confirm (per-pair or all):
- `EW9801×31425` → volcanic (Loihi)
- `RR1506×29779` → seamount (Kermadec Arc)
- `TN268×30466` → volcanic (Axial caldera)
- `TN399×30373` → volcanic (EPR 9°N)
- `FK181031×24367` → volcanic (Alarcón Rise)
- `TN299×27339` → volcanic (Gorda Ridge)

Apply confirmed reclasses to `terrain_class` at write time (avoids an append-only violation from fixing labels post-write). Unconfirmed ones stay original with the proposal preserved in `terrain_class_proposed`.

## 3. Execute the append (on M2 confirmation)
1. Remove the 3 dropped rows from the staged set → 13 new rows.
2. Apply Steve-confirmed terrain reclasses to `terrain_class`.
3. Append the 13 to `manifest/pairs.parquet` — **append-only; the 21 preserved verbatim**; dedup on `pair_id` (no spatial dups; the 6 orphan `cal_dig` sub-dirs are not among the new pairs).
4. Sync to `$OAK/auv_ship_colocated_bathy/`; byte + dedup + checksum verify against the staged file.
5. Report: final 34-row manifest, completeness diff (every canonical field), checksum-verify result, OAK sync confirmation. Record the 3 dropped pairs in an exclusions log with reason `unconfirmed_coregistration_eligible_for_manual_recoreg`.

## 4. Minor (record, non-blocking)
For cross_cruise pairs, `acquisition_date` holds the AUV date; capture the **LR acquisition date** in `notes` (e.g. KIWI10RR LR = 1998) so temporal independence (older LR cannot ingest newer HR) is readable straight off the row.

## 5. Forward (unchanged)
- **C1 re-harvest** (Amundsen 31753/30046, Axial 32556/32557/30218) proceeds as a separate candidate track — each through independence + reader proof + **leakage_unit assignment vs any existing pair over the same seafloor** (esp. Axial float vs `TN268×30466`) before its own append.
- 3 dropped pairs remain candidates for future manual co-registration.

## Frozen / unchanged
21 read-only until the append (then preserved verbatim within it); `pairs.parquet.bak_preappend` retained; per-cruise raw-LR independence non-negotiable.

**Skepticism note:** the append is the irreversible step and it waits behind (a) the independently-verified parity diff and (b) Steve's terrain confirmation — not behind a prose "ready." Post-write, the report must show the checksum-verify and dedup result, not assert success.
