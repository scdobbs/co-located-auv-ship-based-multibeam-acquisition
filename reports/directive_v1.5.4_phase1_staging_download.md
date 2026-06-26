# Directive v1.5.4 (rev 1) — Phase 1: state capture + no-gridding-needed staging download

*2026-06-05. For the current (compacted) Claude Code execution instance. Scope is deliberately narrowed to mechanical, pre-decided, idempotent execution — every judgment call removed. Raw-LR gridding, the Stage C dry-run, the retention decision, and CRS validation are **out of scope** and handed to a fresh instance in Phase 2.*

**Revision 1 (supersedes the original v1.5.4 framing):** The original directive drew the Phase-1 boundary on the *tier* axis (training+eval = 50) and wrongly assumed those have processed LR. Corrected: the boundary is the **gridding axis**. Only **9** selected pairs have an already-processed LR grid; the other **76** LR (41 sitting in training/eval + 35 in `raw_lr_to_grid`) are **raw cruises needing MB-System** and are deferred. HR grids never need gridding, so **all 85 non-excluded HR are fetched now.** See §Boundary.

---

## Boundary (the corrected cut line)

- **FETCH this phase (direct downloads, no gridding):**
  - **All 85 non-excluded HR grids** = training (31) + eval_only (19) + raw_lr_to_grid (35). HR are processed products; tier is irrelevant to download-readiness.
  - **The 9 already-processed LR grids** (wherever they sit in the selection).
- **DEFER to Phase 2 (need MB-System):**
  - **All 76 raw-LR cruises** (the 41 raw companions of training/eval HR + the 35 `raw_lr_to_grid`). Do not fetch any raw cruise file this phase.
- **Consequence to record, not act on:** 41 training/eval HR will be staged **without** their LR this phase (their LR is raw, deferred). Their tier label is provisional — a final ratio is impossible until the LR is gridded. **Do not reclassify or re-tier them. Do not touch the gate.** This is fixed in Phase 2 when gridding finalizes each ratio.

---

## GUARDRAILS — read these every time, do not violate

- **READ-ONLY** against `manifest/pairs.parquet`. Never write/modify/delete/re-order rows. Reading is fine.
- **APPEND-ONLY** to `$DATA_ROOT`. Never delete or overwrite an existing raster (see idempotency, Step 2).
- **NO RAW-LR FETCH.** Do not download any `.all`, `.gsf`, or raw cruise file. All 76 raw-LR cruises are **DEFER_PHASE_2**.
- **NO MANIFEST WRITES.** This phase only stages files; it appends no pairs.
- **NO RECLASSIFY / NO GATE EDIT.** Do not move HR between tiers, do not re-issue the gate.
- **NO STAGE B–G.** No harmonization, co-registration, gridding, QA.
- **STORAGE:** everything to `$DATA_ROOT` = `/scratch/groups/hilley/auv_ship_colocated_bathy/`. Never `~`.
- **FAIL = STOP.** If any verification gate fails, halt, write what you found, do not proceed or "fix and continue."

---

## Step 0 — State capture (FIRST, before any download)

Highest-value action; run before downloading because it is the durable handoff. Write `staging_state_20260605.json` to the repo (not scratch):

- **`$DATA_ROOT` inventory:** full file list + byte sizes (`find $DATA_ROOT -type f -printf '%p %s\n'`) and a total.
- **Manifest snapshot (read-only):** `pairs.parquet` row count, mtime, byte size; confirm the untouchable set present — DISCOL, 18 Cal DIG sub-pairs, CCZ, TAG.
- **Phase-1 fetch set** (from the v3 gate selection / `stage_a_selection.yaml`):
  - **HR list (85):** every non-excluded `hr_id` with `hr_url`, `hr_expected_bytes` (where available — exact for MGDS, may be blank for PANGAEA/USGS/SEANOE), `tier`, `hr_class`.
  - **Processed-LR list (9):** each `lr_id`, `lr_url`, paired `hr_id`, `lr_status=processed`.
- **DEFER_PHASE_2 set:** the 76 raw-LR cruise ids (`lr_status=raw`), each with its paired `hr_id`. Mark `DO-NOT-FETCH`.
- **CRS provenance:** the 11 `crs_recovered` ids and 3 held ids (2 unrecoverable, 1 failed verification), for Phase-2 awareness.

If this instance degrades further or the download interrupts, this file alone lets the next instance resume.

---

## Step 1 — Freeze the Phase-1 fetch manifest

Write `stage1_download_manifest.csv`, one row per **file to fetch**, columns:

`fetch_id, role, url, expected_bytes, paired_hr_id, tier, lr_status`

- `role` ∈ {`HR`, `LR_processed`}. Rows: **85 HR + 9 LR_processed = 94 fetch rows.**
- **No raw-LR rows.** Confirm zero rows have `lr_status=raw` before proceeding.
- Confirm HR rows == 85 and LR_processed rows == 9. If either count is off, **STOP** and report — the selection didn't parse as expected.

Decisions end at this file.

---

## Step 2 — Execute the download (idempotent, append-only)

Fetch each row to a structured layout under `$DATA_ROOT/staging_phase1/<hr_id>/`.

- **Idempotent:** if the target already exists with the correct byte size, **skip** (makes the step safe to re-run after a crash/compaction — it resumes, never duplicates).
- **Append-only / no clobber:** if a file exists with the *wrong* size, **do not overwrite** — log `size_mismatch_existing`, skip, flag for review.
- **No raw:** if any url resolves to a raw `.all`/`.gsf`, skip and log `unexpected_raw_skipped`. (None should — the manifest excluded them.)
- **Log every attempt** to `stage1_download_log.csv`: `fetch_id, role, url, bytes_expected, bytes_received, status` where status ∈ {`fetched`, `skipped_present`, `size_mismatch_existing`, `failed`, `unexpected_raw_skipped`}.

---

## Step 3 — Mechanical verification (pass/fail gates, no judgment)

Each gate → PASS/FAIL with numbers. **Any FAIL → STOP.**

1. **HR byte exactness (where available):** fetched HR with a known `expected_bytes` match it. HR without a published size: present and non-zero. List mismatches.
2. **Completeness identity:** `fetched + skipped_present + failed + size_mismatch_existing == 94` rows (85 HR + 9 LR). No limbo, no extra.
3. **Negative / no-raw check:** **zero** files belonging to the 76 raw-LR cruise ids exist anywhere under `$DATA_ROOT/staging_phase1/`.
4. **Read-only check:** `pairs.parquet` row count, mtime, byte size unchanged from Step 0.
5. **Untouchable check:** DISCOL / 18 Cal DIG / CCZ / TAG present and unchanged.

---

## Step 4 — Phase-1 completion report

Write `stage1_report_20260605.md`: counts + byte totals fetched; any mismatches/failures; all five gate results with numbers; an explicit line: **"Raw-LR NOT fetched — 76 raw-LR cruises (41 train/eval companions + 35 raw_lr_to_grid) deferred to Phase 2."**; and a note: **"41 train/eval HR staged without LR; tier provisional pending Phase-2 ratio finalization — not reclassified here."** Refresh `staging_state_20260605.json` to post-download reality.

---

## Out of scope this phase (if tempted, STOP — it's Phase 2)

Raw-LR fetch or MB-System gridding; Stage C dry-run; raw-LR retention decision; CRS validation; tier reclassification / gate re-issue; any `pairs.parquet` append; harmonization/co-registration/QA.

---

## Deliverables (the bridge to the fresh instance)

1. `staging_state_20260605.json` (refreshed post-download)
2. `stage1_download_manifest.csv`
3. The staged corpus under `$DATA_ROOT/staging_phase1/` (85 HR + 9 processed LR)
4. `stage1_report_20260605.md` (+ `stage1_download_log.csv`)

When these exist and all five gates PASS, Phase 1 is done. Stop there. Do not start Phase 2.
