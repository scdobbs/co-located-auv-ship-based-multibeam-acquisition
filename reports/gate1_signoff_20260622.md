# Gate 1 — sign-off record

**Date:** 2026-06-22 · **Signed:** Steve · **Retention + output-home decisions:** delegated to assessment instance and recorded here. Steve may override any of these.

*This record satisfies the Stage B precondition (recorded Gate-1 sign-off covering the cleaned fetch list, the retention policy, and the non-purge output home). Stage B may proceed once the storage targets in §3 are confirmed to exist.*

---

## 1. Approved — fetch plan and rulings (A.5 + A.6)

- **Cleaned fetch list** (`stage_b_fetch_list_2026-06-22.csv`): **45 cruises** (12 subset + 33 whole), **≈131 GB**, pairing **71 HR**. Approved.
- **Drop the 10 duplicate HR** (re-derivations of the untouchable 21; manifest authoritative). Approved.
- **Drop the 10 cruises** serving only dead/duplicate/quarantined HR (MV1405, EX1101, NA073, RR0916, SR1903, DRFT01RR, EW0407, KN180L02, KIWI01RR, RNDB18WT). Approved.
- **Amundsen ×2 → keep-subset** (real co-located pairs; 500→45 GB via footprint subsetting). Approved.
- **`TN299` / `NA080` / `TN399` → `lr_coverage_quality_watch`** carried into Stage C (coverage-quality call at gridding, not now). Approved.

## 2. Q1 — Storage

Confirmed. ≈131 GB into `GROUP_SCRATCH` at 2 % used is trivial; capacity is not the constraint.

## 3. Q2 — Retention + output home (assessment ruling, per delegation)

**Raw `.all`/`.gsf` retention: keep through the pilot and first full gridding run; then purge per-cruise** once that cruise's gridded LR passes Stage-F QC **and** its `mbgrid` parameters are final.
- No purge during the pilot or first full run.
- Purge is per-cruise and conditional on "done," not a global sweep.
- Rationale: at 131 GB keeping is cheap; gridding is untested and likely to be re-run with tuned parameters, so retaining raw avoids re-downloading cruises mid-tuning. Raw is re-fetchable from NCEI, so a 90-day scratch lapse during any long pause is acceptable.

**Output home: `$OAK`** for all validated outputs — gridded LR, harmonized pairs, and `manifest/pairs.parquet`.
- **Confirm the group `$OAK` allocation exists and report the exact path** before relying on it. Fallback: `$GROUP_HOME` with a quota check, only if no OAK allocation.
- **Migrate existing validated work too, not just new outputs.** Verify where the current `manifest/pairs.parquet` and the harmonized DISCOL / 18 Cal DIG / CCZ / TAG products actually live. If they are on scratch (`$DATA_ROOT`), place a persistent copy on `$OAK` — the untouchable 21 must not sit on a 90-day purge timer. (Copy, read-only; do not modify the originals.)

## 4. Stage B — cleared to proceed

Precondition satisfied. Stage B fetches the 45-cruise cleaned plan per `directive_phase2_stage_b_raw_lr_fetch.md` (idempotent, byte-exact via HEAD, content-integrity verified), to `$DATA_ROOT/raw_lr/`. No gridding, no manifest writes. Holds before Stage C, which begins with a reviewed pilot.

## 5. Still assessment/Steve-owned downstream (not part of this sign-off)

`MGDS:31600` provenance call (Gate 2), the re-tier results after ratio finalization (Stage E), and any Stage-C coverage-quality exclusions on the watch cruises.
