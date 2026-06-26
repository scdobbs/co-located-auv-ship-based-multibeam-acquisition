# Directive v1.5.4 (rev 2) — Phase 1 remediation

*2026-06-05. Addendum to v1.5.4 rev 1, after the Stage 1 report. The download largely succeeded (84/85 HR good, 9 processed-LR pairs present, `pairs.parquet` untouched, no raw fetched), but the all-PASS verdict masked two real HR defects and two gate-design holes. This addendum remediates them. **It expands scope by exactly these tasks and nothing else.** Same instance is fine — every step is mechanical and pre-decided.*

---

## GUARDRAILS (unchanged, the load-bearing ones restated)

- **READ-ONLY** against `manifest/pairs.parquet`. **APPEND-ONLY** to `$DATA_ROOT` except the one sanctioned deletion explicitly scoped in R0.
- **NO RECLASSIFY / NO GATE EDIT / NO RE-TIER.** Diagnoses below produce *findings* for the assessment instance. Do not exclude, re-tier, or edit the gate yourself.
- **QUARANTINE = MOVE, NOT DELETE.** Suspect files are moved to a quarantine dir, never deleted (except the R0 stub).
- **NO RAW FETCH, NO GRIDDING, NO MANIFEST APPEND.**
- **FAIL = STOP.** No loops, no fabrication. If a re-fetch keeps failing, record and escalate.

---

## Step R0 — `MGDS:30272`: inspect, re-fetch, verify

The existing `staging_phase1/MGDS_30272/data_uid_2427151.bin` is 278 bytes where 4,517,897 was expected — an error body, not bathymetry. The no-clobber rule has been skipping it (poison pill); break that.

1. **Inspect first:** read the first ~500 bytes of the 278-byte file and record them verbatim in the report (it will say what happened — HTML error, redirect, access notice). This matters: the URL is the marine-geo API endpoint that *moved* before, so an apparent failure may be a renamed endpoint, not an outage.
2. **Delete the stub.** This is the only sanctioned deletion — a known sub-expected error body, not validated data.
3. **Re-fetch** from `https://api.marine-geo.org/services/download/Document_Accept.php?data_uid=2427151`.
4. **Verify** received == **4,517,897** bytes exactly.
   - PASS → keep; update log row status to `fetched`.
   - Still 278 / wrong / small → do **not** retry in a loop. Record the body, mark `MGDS:30272` status `FETCH_FAILED_ESCALATE`, leave no partial file, and continue to R1 (do not abort the whole run for this one HR).

---

## Step R1 — `MGDS:31600`: quarantine + diagnose (no exclusion decision)

Its files are `d148/d149/dome.v7.latlon.1sec.grd.gz` — 1-arc-second (~30 m) lat/lon grids, inconsistent with declared `hr_class=auv`, `hr_native_res_m=9.80`. Possible wrong-file or coarse/composite product. Quarantine and measure; do **not** decide eligibility.

1. **Move** `$DATA_ROOT/staging_phase1/MGDS_31600/` → `$DATA_ROOT/quarantine_phase1/MGDS_31600/` (idempotent: if already there, skip).
2. For each grid file, run `gdalinfo` (via `/vsigzip/`) or `grdinfo` after gunzip to temp. Record: CRS, pixel/cell size, and — if the CRS is geographic — the cell size converted to meters at the grid's mean latitude (1 arc-sec ≈ 30.9 m in latitude; scale longitude by cos(lat)).
3. Record `declared_native_m=9.80` vs `measured_finest_cell_m`, plus a `looks_like` note ∈ {`auv_hr`, `coarse_or_composite`}. **Flag as a finding for assessment. Do not exclude or re-tier.**

---

## Step R2 — corpus-wide cell-size sanity sweep

`31600` is unlikely to be the only mis-resolved HR, and several Sentry grids are small enough to warrant a check. Sweep every HR.

1. For each HR directory under `staging_phase1/`, identify bathymetry grid files by extension (`.grd`, `.grd.gz`, `.nc`, `.tif`, `.asc`, `.asc.gz`). Run `grdinfo`/`gdalinfo` on each; take the **finest** cell size found for that HR as its effective resolution (convert to meters as in R1).
2. Compare to declared `hr_native_res_m`. Verdict per HR:
   - `ok` — measured within 0.5×–2× of declared.
   - `flag_mismatch` — ratio (measured/declared) > 2 or < 0.5.
   - `flag_coarse` — declared missing/unknown AND measured finest cell > 5 m (an HR should be fine-scale).
   - `no_grid_found` — no readable grid file (possible stub like R0).
3. Emit `hr_resolution_sanity.csv`: `hr_id, declared_native_m, measured_finest_cell_m, crs, ratio, verdict`.
4. **Diagnostic only — flag, don't act.** List every non-`ok` HR for the assessment instance.

---

## Step R3 — corrected verification gates (close the holes)

The original gates passed by construction. Fix and re-run:

- **Gate 1 (byte exactness) — corrected scope:** include `size_mismatch_existing` rows as FAIL conditions, not just `fetched` rows. After R0, `MGDS:30272` is either recovered (PASS) or `FETCH_FAILED_ESCALATE` (explicit FAIL) — never invisible.
- **Gate 6 (cell-size sanity) — new:** PASS only if every HR is `ok` or explicitly resolved (`31600` quarantined counts as resolved-by-quarantine, not a silent pass). Any unresolved `flag_*` / `no_grid_found` → FAIL.
- Re-run gates 2–5 unchanged.
- Any FAIL → STOP and report (escalations from R0 and quarantines from R1 are *recorded resolutions*, not blocking FAILs).

---

## Step R4 — update report + state

1. Append a **Remediation** section to a new `stage1_report_20260605_rev2.md` (new dated file, do not overwrite the original): the `30272` body + outcome, `31600` measurements + `looks_like`, the resolution-sweep summary, and the full list of any other flagged HR.
2. Refresh `staging_state_20260605.json`: `MGDS:30272` final status, `MGDS:31600` quarantined + findings, resolution-sweep verdicts, and an explicit **clean HR count** = 85 − (quarantined) − (FETCH_FAILED_ESCALATE) − (other unresolved flags).
3. State plainly what Phase 2 inherits: the clean HR count, the quarantined/flagged ids awaiting an assessment eligibility decision, and that no exclusion/re-tier was performed here.

---

## Out of scope (assessment decides; do not act)

- Excluding or re-tiering `MGDS:31600` or any flagged HR — that's a gate/re-tier call.
- Raw-LR fetch, MB-System gridding, retention decision, CRS validation, manifest append.

## Deliverables

1. `stage1_report_20260605_rev2.md` (with corrected gates 1 + 6)
2. `hr_resolution_sanity.csv`
3. `$DATA_ROOT/quarantine_phase1/` (with `MGDS:31600`, plus any `no_grid_found` HR)
4. Refreshed `staging_state_20260605.json` stating the clean HR count

When `30272` is resolved (recovered or escalated), `31600` is quarantined, the sweep is emitted, and the corrected gates report, Phase 1 is done. The clean HR count is what Phase 2 inherits.
