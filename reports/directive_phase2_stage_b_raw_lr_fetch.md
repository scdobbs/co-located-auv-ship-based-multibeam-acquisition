# Directive — Phase 2 Stage B: raw-LR fetch (cleaned subset plan)

**Date:** 2026-06-22 · **For:** Phase 2 Claude Code execution instance · **Runs after:** Gate 1 sign-off (now closed) · **Stops before:** Stage C gridding.

*Fetch the cleaned, deduplicated raw-LR plan from A.6 — 45 cruises (12 subset to intersecting files + 33 whole), ~131 GB. Swath + per-file nav only. This is a mechanical bulk fetch; the novel risk is Stage C, not here — so the job is to land the raw bytes correctly and prove they're real data, not error bodies.*

---

## Precondition — Gate 1 (now SATISFIED)

Gate 1 is signed (`gate1_signoff_20260622.md`) and storage is set up and verified (`gate1_storage_setup_20260622.md`). The relevant recorded decisions:

- **Fetch plan approved:** the A.6 cleaned list (`stage_b_fetch_list_2026-06-22.csv`), 45 cruises, ~131 GB, 71 HR.
- **Working data → scratch (unchanged):** raw fetch lands on `$DATA_ROOT` (`/scratch/groups/hilley/auv_ship_colocated_bathy/`), under `raw_lr/`, exactly where active work has always gone. Scratch is correct for raw and intermediates.
- **Validated outputs → `$OAK`:** persistent home is `$OAK/auv_ship_colocated_bathy/` (already created; the existing 21-pair manifest + harmonized products are mirrored there read-only). This matters at Stage F/G, **not** Stage B — Stage B writes raw only.
- **Retention:** keep raw through the pilot and first full gridding run, then purge per-cruise once that cruise's gridded LR passes Stage-F QC and its `mbgrid` parameters are final. **No purge happens in Stage B** — retention acts downstream. Stage B's only obligation is to write raw to `raw_lr/`.

(If for any reason the storage-setup record is absent at run time, STOP and report — do not fetch on assumption. Otherwise proceed.)

---

## Guardrails

- **Fetch only what the cleaned list specifies.** Subset cruises → only their intersecting swath files (the A.5/A.6 file lists). Whole cruises → all swath files. Plus each kept file's `.fnv`. **No `.fbt`** (MB-System regenerates it). **One encoding per cruise** (the dedup is already in the plan — don't re-add duplicate vendor/MB encodings).
- **Idempotent / append-only / no clobber.** Present-and-correct → skip. Present-and-wrong-size → log, skip, flag; never overwrite.
- **Verify content, not just presence.** The Phase-1 lesson: a small error body can masquerade as a file. Every fetched file is integrity-checked (B2).
- **Bounded retries, then escalate.** Transient 5xx → at most 3 retries with backoff. After that, record and move on; never loop. A cruise with any failed/corrupt file is `incomplete_for_grid` — flag it, don't silently pass it to Stage C.
- **Storage:** raw to `$DATA_ROOT/raw_lr/<cruise>/`. **No gridding, no manifest writes, no OAK writes** (OAK is a Stage-F/G destination).
- **Be polite to NCEI:** bounded concurrency (≈4–8), not a thundering herd.

---

## Step B0 — preflight (build the per-file plan; fetch nothing)

Load `stage_b_fetch_list_2026-06-22.csv`. Confirm 45 cruises (12 `subset` + 33 `whole`). Expand to a **per-file plan**: for each cruise, the exact swath files to fetch (subset → intersecting list; whole → all swath files) plus their `.fnv`. Record per file: `cruise, filename, url, advertised_size` (from the cached autoindex). This is the manifest B1 fetches against and B3 reconciles to.

---

## Step B1 — per-file fetch (Slurm, parallel, idempotent)

For each planned file:
1. **HEAD** the URL for exact `Content-Length` (the autoindex sizes are human-rounded ~1 %; HEAD is byte-exact and is the verification truth).
2. If a local copy exists with `bytes == Content-Length` → `skip_present`. If it exists with a different size → `size_mismatch_existing`, skip, flag (no clobber). Else fetch.
3. Fetch swath file + its `.fnv` to `$DATA_ROOT/raw_lr/<cruise>/`.

Log per file to `stage_b_fetch_log.csv`: `cruise, filename, url, advertised, head_content_length, received, status` where status ∈ {`fetched`, `skip_present`, `size_mismatch_existing`, `failed`}.

---

## Step B2 — integrity verification (the error-stub lesson)

For every fetched file:
- **Byte-exact:** `received == HEAD Content-Length`.
- **Content sanity:**
  - `.gz` → `gzip -t` must pass (a truncated download or HTML error body fails this).
  - uncompressed swath (`.mbNNN`, `.mb163`, legacy date-named) → `mbinfo` opens it without error, or `file` reports a plausible binary, not `HTML`/`ASCII text` error page.
- Flag any file that is byte-OK but content-FAIL (the dangerous case — right size, wrong content) as `corrupt_content`.

Per cruise: all planned files present **and** integrity-pass → `complete`. Otherwise → `incomplete_for_grid` (listed, not advanced).

---

## Step B3 — completeness accounting

- Identity: `fetched + skip_present + failed + size_mismatch_existing + corrupt_content == planned file count`, per cruise and total. No limbo.
- Total received bytes vs the **131 GB** plan (within ~1 % autoindex rounding). Report the delta.
- Cruise-level: `complete` count vs 45. Any `incomplete_for_grid` cruise is escalated with its failing files.

---

## Step B4 — report + state

Write `stage_b_fetch_report_2026-06-22.md`: per-cruise bytes/files/integrity, the completeness identity, total vs plan, and any `incomplete_for_grid` / `corrupt_content` / `failed` cruises with specifics. State plainly: raw fetched to `$DATA_ROOT/raw_lr/`, no `.fbt` fetched, no gridding performed, manifest untouched, no OAK writes. Update `staging_state` with per-cruise raw-LR fetch status.

---

## Deliverables

1. `$DATA_ROOT/raw_lr/<cruise>/` — the fetched raw corpus (+ `.fnv`)
2. `stage_b_fetch_log.csv` and `stage_b_fetch_report_2026-06-22.md`
3. updated `staging_state` (raw-LR fetch status per cruise)

---

## Next (do NOT start without a directive)

**Stage C MB-System gridding — PILOT first.** A handful of cruises spanning sonar types and depths, deliberately including one Amundsen subset (the novel Arctic case) and one `lr_coverage_quality_watch` cruise (`TN299`/`NA080`/`TN399`) so the pilot tests the failure-prone cases. Assessment reviews the pilot before any full gridding run. The gridding directive will specify per-cruise gridding, the estimate-then-measure ratio check, native-res from sounding density, and the coverage-quality call on the watch cruises.

## Out of scope

Gridding (Stage C), the retention purge (post-grid, per the recorded policy), `native_res` re-derivation (Stage D), manifest writes, OAK writes, re-opening the 21. Only `complete` cruises advance to Stage C; `incomplete_for_grid` cruises wait for assessment.

## Tracked downstream (not this stage)

- **6 orphan `cal_dig_morro_bay/` sub-dirs** surfaced during the OAK migration (24 sub-dirs vs 18 manifest pairs — e.g. `luciachica_2009`, `20180426m1_PockmarkNorthDet`). Marked "superseded" by the migration but unverified. Reconcile each (genuinely superseded duplicate vs accidental manifest omission) **before Stage G append**, so the validated count reconciles. Not a Stage-B concern; recorded here so it isn't lost.
