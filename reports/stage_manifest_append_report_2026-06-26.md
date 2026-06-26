# Canonical manifest append — EXECUTED & VERIFIED (34 pairs)

**Date:** 2026-06-26 · **Directive:** `directive_phase2_manifest_append_greenlight_v1.md`
**Status:** ✅ **Append executed.** Steve confirmed all 6 M2 terrain reclasses; 13 new rows appended; `manifest/pairs.parquet` (repo) + OAK both at **34 rows**, byte-identical, checksum-verified. The 21 validated preserved verbatim.

**Code:** `src/discovery/stage_manifest_append.py` · **Result:** `reports/discovery/stage_manifest_append_result.json` · **Backups:** `manifest/pairs.parquet.bak_2026-06-26_append` (+ earlier `.bak_preappend`).

---

## What was written
- **34 rows = 21 validated + 13 new.** Pair_ids unique; no spatial dups; the 6 orphan `cal_dig` sub-dirs were not among the new pairs.
- **The 13 new:** AT37-13×31199, AT42-03×32007, EW9801×31425, NA080×31290, NA090×31212, RR1506×29779, TN268×30466, TN399×30373, FK181031×24367, AR26×31838, TN159×21981, TN299×27339, KIWI10RR×24499. Eval set = NA090×31212 + TN159×21981 (unchanged).
- **3 dropped** (logged, not data-quality exclusions): KN210-05×22436, FK006B×20811, KN204-01×31675 → `stage_append_exclusions_2026-06-26.csv`, reason `unconfirmed_coregistration_eligible_for_manual_recoreg`.

## Verification (evidence, not assertion)
| check | result |
|---|---|
| canonical rows | **34** (was 21) |
| pair_id unique | **True** |
| 21 validated preserved verbatim | **True** (first-21 == pre-append backup, exact) |
| checksum re-verify (sha256 of rasters vs manifest value) | **26/26 match, 0 mismatch** (13 pairs × hr+lr) |
| OAK sync byte-identical (sha256 repo == OAK) | **True**; repo DataFrame `.equals(OAK)` **True** |
| OAK file re-locked read-only | **`-r--r--r--`** |
| dedup vs the 21 | clean (idempotency guard would have aborted on any collision) |

The append script was self-protecting: it aborts if a new pair_id already exists, and would have **restored the canonical from backup** had any checksum mismatched (none did).

## Terrain reclasses applied (Steve-confirmed, all 6)
EW9801→volcanic (Loihi), RR1506→seamount (Kermadec Arc), TN268→volcanic (Axial caldera), TN399→volcanic (EPR 9°N), FK181031→volcanic (Alarcón Rise), TN299→volcanic (Gorda Ridge).

**Resulting terrain mix (34):** continental_margin 23, volcanic 5, seamount 2, hydrothermal_vent 2, nodule_field 1, abyssal_plain 1. Margin share is now **68% (23/34)**, down from the prior inflated ~74% — the diversity correction (margin labels that were really MOR/volcanic/seamount) is reflected in the canonical record.

## §4 temporal independence (recorded per row)
Each cross_cruise row's `notes` now carries the LR acquisition date, e.g. `KIWI10RR×24499 → LR_acq_date=1998-04-12` (vs HR AUV FK171110/2017), `TN399 → LR_acq_date=2022-01-29`. An older LR cannot ingest a newer HR — readable straight off the row.

## Forward (unchanged)
- **C1 re-harvest** (Amundsen 31753/30046; Axial 32556/32557/30218) proceeds as a separate candidate track — each through independence + reader proof + **leakage_unit assignment vs any existing pair over the same seafloor** (esp. Axial float vs `TN268×30466`) before its own append.
- The 3 dropped pairs remain candidates for future manual control-point co-registration (real data, not excluded for quality).

## Deliverables
1. `manifest/pairs.parquet` = 34 rows (repo); `$OAK/.../manifest/pairs.parquet` synced + read-only. ✅
2. `stage_manifest_append_result.json` (per-field final completeness + checksum-verify + OAK byte check). ✅
3. `stage_append_exclusions_2026-06-26.csv` (3 dropped, manual-recoreg-eligible). ✅
4. Pre-append backup retained. ✅
