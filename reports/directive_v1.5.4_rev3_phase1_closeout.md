# Directive v1.5.4 (rev 3) — Phase 1 close-out

*2026-06-05. Final Phase-1 pass, after the rev-2 remediation report. Rev 2 worked but two things need closing before handoff: (a) the three missing-data HR were escalated without ever capturing the actual server response, and (b) gate 6's symmetric band failed 10 HR that are merely **finer** than declared — valid data, not contamination. This pass captures the missing bodies, attempts recovery, recalibrates gate 6, and lands the true clean count. Every step is mechanical and pre-decided.*

**Assessment rulings already made (carry these in, do not re-litigate):**
- The 10 `flag_mismatch` HR are all 2–5× **finer** than declared → valid HR, **re-admitted to the clean corpus** (their `native_res` is suspect and gets verified in Phase 2, not here).
- `MGDS:31600` is a multi-tile, multi-resolution **compilation** (`d142…valley` × `{1sec, tenthsec, plain}`) → **stays quarantined; default-exclude pending provenance** confirming a single AUV survey. Not acted on as a manifest change here — recorded as a finding.
- The `no_grid_found` pair (`20836`, `24425`) are **missing data**, same class as `30272` — not eligibility flags. They go to the recovery attempt below, not the corpus.

---

## GUARDRAILS

- **READ-ONLY** against `manifest/pairs.parquet`. **APPEND-ONLY** to `$DATA_ROOT` (recovered files only; no deletions this pass).
- **Gate recalibration here is authorized** — it changes the *verification* gate logic only. The prohibition still stands on re-tiering HR, editing the Stage-A *selection* gate, or touching `pairs.parquet`.
- **NO RAW FETCH, NO GRIDDING, NO MANIFEST APPEND, NO RE-TIER.**
- **FAIL = STOP. No loops, no fabrication.** A re-fetch is attempted at most twice per id (original form + one corrected form); after that, record and escalate.

---

## Step C0 — capture the real response for the 3 missing-data HR, then attempt recovery

This is the gap rev 2 left: the 278-byte body was never captured (R0 read a stale 0-byte stub, then re-fetched to 278 without re-reading). A consistent 278-byte reply from a *reachable* endpoint is the marine-geo move-pattern — the server is answering and rejecting the request form. The body will say how.

For each of `MGDS:30272`, `MGDS:20836`, `MGDS:24425` (pull `hr_url` from `staging_state` / the manifest):

1. **Fetch with full capture.** Use `curl -sS -L -D <headers.txt> -o <body.bin> '<hr_url>'`. Record: final HTTP status, the `Location`/redirect chain, `Content-Type`, `Content-Length`, and the **first ~2 KB of the body verbatim** (escape newlines) into the report. Do this even if bytes == 278 — especially then.
2. **Read what the body says.** If it names a corrected parameter, a redirect target, or a renamed endpoint (as the earlier MGDS move did), attempt the corrected request **once**.
3. **Verify.** If the corrected fetch returns the expected size (exact where known, else a plausible grid > 100 KB), move the file into `staging_phase1/<id>/` and mark the id `recovered` → eligible for the clean corpus.
4. **If still failing** after the one corrected attempt: mark `recover_or_drop`, keep the captured body in the report, and leave it for the assessment instance. Do not loop.

(Capture the body for all three first, then attempt corrections — if they share one error, one fix likely recovers all three.)

---

## Step C1 — recalibrate gate 6 (asymmetric) and re-admit the finer HR

The symmetric 0.5×–2× band treated "finer than declared" as failure. Correct it:

- **BLOCK (FAIL-class):** `flag_coarse` (ratio > 2, i.e. measured **coarser** than declared) · `composite` · `no_grid_found`. These disqualify.
- **WARN (PASS, recorded):** measured **finer** than declared (ratio < 0.5). Reclass these from `flag_mismatch` to verdict **`ok_finer_verify`**, tag `native_res_verification_needed=true`, and **re-admit to the clean corpus**. (Note: "finer" may mean declared was overstated *or* the grid is over-posted/interpolated — e.g. the ~0.1 m values on `24467`/`24470` are almost certainly over-posting, not true resolution. Do **not** try to resolve which here; that's a Phase-2 native_res derivation from sounding density, not grid posting.)

Apply: the 10 HR (`21415, 21454, 21462, 24467, 24470, 31253, 31254, 31255, 31321, 31860`) all have ratio 0.19–0.49 → all become `ok_finer_verify`, re-admitted.

Resolution status of every non-`ok` HR after this pass:
- `31600` → resolved-by-quarantine (composite).
- `20836, 24425, 30272` → resolved-by-escalation (C0 recovery outcome: `recovered` or `recover_or_drop`).
- the 10 → `ok_finer_verify` (re-admitted).

**Re-run gate 6:** PASS iff zero **unresolved** BLOCK-class HR remain. Quarantined, escalated, and `ok_finer_verify` are recorded resolutions, not failures. Re-run gates 1–5 unchanged (expect all PASS).

Update `hr_resolution_sanity.csv`: add `native_res_verification_needed` and `resolution` (= `ok` / `ok_finer_verify` / `quarantined` / `escalated_recovered` / `escalated_recover_or_drop` / `blocked_coarse`) columns.

---

## Step C2 — update report + state, land the clean count

1. New file `stage1_report_20260605_rev3.md` (do not overwrite rev 2): the three captured bodies, recovery outcomes, the recalibrated gate-6 result, and the corrected accounting.
2. Refresh `staging_state_20260605.json` with the final disposition of all 85 and the **clean HR count**.

**Expected accounting** (confirm against actuals; report any deviation):

| bucket | count | notes |
|---|---:|---|
| ok | 61 | unchanged |
| manifest seed (clean) | 10 | prior milestones |
| ok_finer_verify (re-admitted) | 10 | native_res to verify in Phase 2 |
| **clean HR for Phase 2** | **81** | + any C0 recoveries |
| quarantined (composite) | 1 | `31600`, default-exclude pending provenance |
| escalated (missing data) | 3 | `30272, 20836, 24425` → recovered or recover_or_drop |

State plainly what Phase 2 inherits: the clean count (81 + recoveries), the `native_res_verification_needed` list (the 10), the quarantined id with its ruling, and any `recover_or_drop` ids still open.

---

## Out of scope (assessment / Phase 2 owns)

- Re-deriving `native_res` for the 10 (Phase 2, from sounding density — not grid posting).
- Final eligibility call on `31600` (needs provenance) and on any `recover_or_drop` id.
- Raw-LR fetch, gridding, retention decision, manifest append, re-tier.

## Deliverables

1. `stage1_report_20260605_rev3.md` — captured bodies, recovery outcomes, recalibrated gate 6
2. updated `hr_resolution_sanity.csv` (with `resolution` + `native_res_verification_needed`)
3. refreshed `staging_state_20260605.json` stating the clean HR count (81 + recoveries)

When the three bodies are captured, recovery attempted, gate 6 recalibrated and re-run, and the clean count stated, Phase 1 is closed.
