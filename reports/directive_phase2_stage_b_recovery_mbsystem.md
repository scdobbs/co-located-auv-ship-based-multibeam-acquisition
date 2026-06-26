# Directive — Phase 2 Stage B-recovery + MB-System setup

**Date:** 2026-06-22 · **For:** Phase 2 Claude Code execution instance · **After:** Stage B fetch report · **Before:** Stage C pilot.

*Stage B succeeded broadly — 18,339 / 18,448 files (99.4 %), 131.92 GB on-plan, completeness identity holds. The 22 `incomplete_for_grid` cruises are mostly single transient failures inflated by the (correct) one-failed-file-flips-the-cruise rule. Recovery is a near-free idempotent re-run. Separately, **MB-System is absent on Sherlock** — the hard blocker for all of Stage C — and must be set up. These two tracks are independent: start **Track M now**, in parallel with Track R.*

---

## Guardrails

- **Idempotent / append-only / no clobber**, except the single sanctioned AR26 deletion in R0.
- **Byte-exact (HEAD) + content integrity** (`gzip -t` / `file`) on every newly-fetched file, as in Stage B.
- **Bounded retries (3, backoff), then escalate.** No loops. **This time, capture the failed-file *detail*** (R2) — a count is not enough to rule transient vs systematic.
- **No gridding, no manifest writes, no OAK writes.** Raw stays at `$DATA_ROOT/raw_lr/`.
- **Execute no exclusions.** Legacy/watch-cruise calls are findings for assessment.

---

# Track R — fetch recovery

## R0 — clear the AR26 partial

`AR26` has one `size_mismatch_existing` (a pre-existing bad partial, like the Phase-1 stub). Inspect it (HEAD `Content-Length` vs on-disk bytes; read the head if small), **delete that one file** (sanctioned — known bad partial, not validated data), re-fetch, verify byte-exact + integrity.

## R1 — idempotent re-run

Re-run the full Stage-B per-file plan. Correct files already on disk → `skip_present` (the 18,339). Retry only the **106 `failed`** (3 retries, backoff). Verify each recovered file byte-exact + integrity-pass.

## R2 — failed-file detail (the transient-vs-systematic evidence)

For every file **still failing after retry**, emit `stage_b_failed_files_detail.csv`: `cruise, filename, url, http_status, head_content_length, bytes_received, attempts`. Then assess clustering explicitly:
- Do a cruise's failures share a subdirectory, a size class, or a consistent HTTP code?
- **Consistent 404 / moved path → systematic** (the NCEI analogue of the marine-geo endpoint shuffle), not network noise — a re-run won't fix it; the path needs re-resolving. Flag these.
- Scattered 5xx/timeouts across unrelated files → transient; recovered on retry.

Give a per-cruise verdict: `recovered` / `transient_residual` / `systematic_needs_path_fix`.

## R3 — re-evaluate cruise status

Recompute `complete` vs `incomplete_for_grid` after retry; report how many flipped to `complete`. For the three `lr_coverage_quality_watch` cruises specifically:
- **`TN299`, `TN399`, `NA080`** — report the **recovered fraction of their intersecting (overlap) files**. These overlaps were already thin (≤2 % of the cruise). If the overlap files did **not** recover, the LR coverage over the HR footprint is too degraded to be worth gridding → flag as **exclude candidate** for assessment (don't exclude). `NA080` lost only 1 file and is likely fine; `TN299` (5 failed) and `TN399` (4 failed) are the ones at risk.

## R4 — legacy-7 HR-dependency diagnostic

For the 7 `needs_format_review` cruises (`AII8L11`, `EW9914`, `RC2901`, `PASC04WT`, `PASC02WT`, `RP11SU81`, `TUNE04WT`), report **which HR each serves** (from the `live_HR` mapping). Flag any HR that depends **solely** on a legacy cruise — i.e. would drop entirely if that cruise is excluded.
- `RP11SU81` carries only `.gps` (no soundings) → **hard exclude** regardless.
- Assessment recommendation carried (for confirmation, not execution): exclude all 7 — 1980s wide-beam SeaBeam-classic against 1–2 m AUV HR lands well above 40× and excludes at the ratio gate anyway, so chasing date-named format recognition isn't worth it. **Confirm the HR-dependency check first** in case an HR would be lost.

---

# Track M — MB-System setup (start now, parallel)

## M0 — confirm truly absent
`module spider mb-system`, `module avail 2>&1 | grep -i mb`, `which mbinfo` — rule out it existing under another module name before installing.

## M1 — install via conda-forge
Into a group conda/mamba env (dedicated env is fine): `conda install -c conda-forge mbsystem` (or `mamba`). Record the env name + exact activation line.

## M2 — verify it actually works
`mbinfo --version`, then run `mbinfo` on **one complete fetched raw file** (e.g. a swath file from a `complete` cruise like `Channel` or `KN210-05`) to confirm it reads real soundings, not just that the binary exists. Record the working invocation (env activate + command) for the Stage C directive to use.

## M3 — if conda-forge fails
Escalate with the actual error (likely a GMT/PROJ dependency). Try resolving the dependency or a pinned version; do **not** silently leave Stage C blocked. Report status either way.

---

## Report + gate

Write `stage_b_recovery_report_2026-06-22.md`: post-retry completeness + flipped-to-complete count, the `stage_b_failed_files_detail` summary with the transient/systematic verdict, the watch-cruise overlap recovery + any exclude candidates, the legacy-7 HR-dependency table, and **MB-System status + the verified working invocation**. Update `staging_state`.

State **Stage C readiness**: `complete` cruise count + MB-System verified = ready for the pilot. **Hold for assessment review** of (a) any `systematic_needs_path_fix` cruises, (b) the watch-cruise exclude calls, (c) the legacy-7 confirmation — before the Stage C pilot directive.

## Deliverables

1. updated `stage_b_fetch_log.csv` + `stage_b_failed_files_detail.csv`
2. `stage_b_recovery_report_2026-06-22.md`
3. MB-System env + verified invocation record
4. updated `staging_state`

## Out of scope

Gridding (Stage C pilot — next directive), manifest/OAK writes, executing any exclusion. The 6 orphan `cal_dig` sub-dirs remain a tracked pre-Stage-G item (unchanged).
