# Phase 2 — Stage F: harmonization + co-registration + QA report

**Date:** 2026-06-23 · **Author:** Claude Code execution instance (Sherlock)
**Directive:** `reports/directive_phase2_stage_f_harmonization.md`
**Status:** ⛔ **HOLD for assessment** — QGIS review of all `needs_review` (and the inflated-footprint flags) before Stage G appends to the manifest. No manifest/OAK writes done.

**Artifacts**
- Harmonized 32 new pairs: `$DATA_ROOT/harmonized/<pair_id>/` (hr.tif, lr.tif, footprint.geojson, qc/overlay.png)
- `reports/discovery/stage_f_results.json`; updated `reports/combined_corpus.csv` (qa_status, psr, offset, overlap, harmonized path, hr_res_provisional)
- Code: `src/discovery/stage_f_harmonize.py` (reuses `harmonize`/`coregister`/`qc`/`qa`)

---

## 1. Headline + completeness (F4)

| | |
|---|---|
| Harmonized (32 new pairs) | **32 / 32** |
| Status | **32 `needs_review`, 0 `reject`** |
| The 21 validated | untouched (read-only) |

**Completeness identity holds:** 32 == 32 `needs_review` + 0 `reject`, no limbo. Every new pair produced hr.tif + lr.tif + footprint.geojson + a QC overlay (single-warp reproject to per-pair local UTM, bilinear; clipped to the HR∩LR valid-data intersection; fresh co-registration). **All are `needs_review` by design** — the PSR/eig auto-pass thresholds were never calibrated (the M1 calibration was inconclusive; config leaves them null), so per established v1.1 practice nothing `auto_pass`es and **QGIS visual QC is the arbiter**.

---

## 2. F0 — margin-stratified test set (Option A)

The 8 Option-A test pairs span **geographically and morphologically distinct settings** — 4 distinct-region margins (Tonga ×2, MAR, KN204-01), 2 vents (Loihi, JdF Endeavour), 1 seamount (Davidson/Octopus Garden), 1 abyssal (DISCOL) — **not character-adjacent to the California-margin (Cal DIG) training.** Caveat carried: the Cal DIG margin-canyon morphology is the indivisible 18-pair unit (shared mosaic LR), so it is entirely in training; the test margins (Tonga/MAR/KN204) provide the held-out margin probe. No re-draw needed.

---

## 3. Co-registration QA — review priorities

All 32 need review; the overlays are the deliverable for the human arbiter. Two flag classes:

### 3a. ⚠️ Inflated-footprint pairs (likely re-clip or exclude) — the discovery bug again
**7 pairs harmonized to absurd overlap areas** (an AUV/ship co-located patch is km²-scale):

| pair | overlap km² |
|---|---|
| RC2511×32240 | 36,433 |
| TN268×24470 | 28,708 |
| FK160407×7832 | 11,980 |
| 2009_Amundsen×30045 | 1,886 |
| KN210-05×22436 | 1,181 |
| FK181031×24367 | 1,453 |
| EW0207×32558 | 1,034 |

These have **inflated HR footprints** (the same bbox-as-footprint bug recorded for the 5 excluded false pairs and AT18-11). The harmonized product spans an unrealistic area; the real co-located AUV patch is much smaller. **Recommend QGIS review re-clip each to the true AUV data extent, or exclude** if no genuine km-scale overlap exists. (Note `2009_Amundsen×30045` is real but multi-tile-spread — re-clip to the LR-covered tiles, don't exclude.)

### 3b. Poor co-registration lock (offset > USBL bound or negative PSR)
Several pairs have horizontal offsets **> 30 m** (the AUV USBL bound) or **negative PSR** (ambiguous lock) — e.g. `KN210-05×22436` (offset 145 m), `EW9904×30217` (64 m), `FK006B×20811` (PSR −0.97), `FK171110×24485` (PSR −18). Deep, large, sparse-LR pairs co-register poorly; **the overlay must confirm the alignment** — a large solved offset may be a real USBL error correction or a bad lock. QGIS arbitrates.

Only **3 pairs** look clean on metrics alone (PSR ≥ 3, offset ≤ 30 m, peak agrees) — but metrics don't pass; **every pair is visually reviewed.**

---

## 4. F3 — folded-in cleanups

- **`ok_finer_verify` (3 in corpus: `SKQ×31255`, `SKQ×31254`, `TN268×24470`):** flagged `hr_res_provisional=True`. Their **k and UQ are grid-content-based** (the C.5b spectral method, robust to over-posting), so the suspect grid posting does **not** change k/UQ — only the manifest `native_res` field carries the provisional flag. A true sounding-density native res needs raw AUV soundings, which are **not held** (only gridded AUV products) — recorded as a limitation, not solvable here.
- **3 residual co-reg failures (`RB1604×24756`, `TN157×21996`, `TN159×21998`):** **not in the corpus** — they didn't survive C.5b (no recoverable signal), so they are already excluded; no manual pass needed.
- **Per-pair record** (`combined_corpus.csv`): final native res, k, UQ (m RMS + scale), split role, morphology, qa_status, harmonized path.

---

## 5. Recommendation + HOLD

**HOLD for assessment / QGIS review** before Stage G:
1. **Review all 32 overlays** (QGIS is the arbiter; nothing auto-passes by design).
2. **Resolve the 7 inflated-footprint pairs (§3a)** — re-clip to the true AUV extent or exclude; this is the discovery footprint-bbox bug surfacing in harmonization (already recorded for the next harvest gate).
3. **Scrutinize the large-offset/negative-PSR pairs (§3b)** — confirm real alignment vs bad lock.
4. After review, only QGIS-cleared pairs advance to Stage G manifest append (append-only, dedup against the 21).

**Post-F retention note (tracked):** a cruise's raw becomes purge-eligible once its pair clears F QC and parameters are final — a separate confirmed action, never automatic here.

## Deliverables
1. 32 harmonized pairs + QC overlays (`$DATA_ROOT/harmonized/`)
2. v1.1 §A QA results (`stage_f_results.json`) + updated `combined_corpus.csv`
3. this report
4. updated `staging_state`
