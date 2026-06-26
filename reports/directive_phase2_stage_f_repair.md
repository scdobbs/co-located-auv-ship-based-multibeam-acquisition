# Directive — Phase 2 Stage F REPAIR: masked re-coregistration + HR datum repair

**Date:** 2026-06-23 · **For:** a **NEW Claude Code execution instance** on Sherlock (fresh context) · **Blocks:** Stage G manifest append.

---

## ⚠️ READ FIRST — be open and critical of the previous instance's work

**The Stage F harmonization and Stage F.5 work you are inheriting were performed by a previous Claude Code instance that had run its context toward exhaustion and was likely degrading.** A **silent data-corruption bug was introduced in Stage F** and only caught in Stage F.5 — by the same possibly-degraded instance. So:

- **Do not trust the prior reports as ground truth.** Re-verify the bug diagnosis, the repair values, and the F.5 masks **independently** before acting on them.
- **The repair values (`dz`) come from the suspect instance.** Confirm them yourself from the raw data before writing anything to `hr.tif`.
- **"Clean" in the F.5 report means *horizontally* clean only** — the vertical axis was nearly missed entirely. Don't inherit that blind spot.
- Your skepticism is wanted. If your independent check disagrees with the prior report, the prior report is the thing in doubt, not your check. Escalate disagreements to the assessment instance rather than reconciling them silently.

This is append-only work. The **21 validated pairs are read-only** except for the verification in Step 4. No manifest/OAK writes (that's Stage G).

---

## The bug (verify this yourself — don't take it on faith)

Stage F's co-registration (`stage_f_harmonize.py:162-168`) opened HR with `rioxarray.open_rasterio(hr.tif)` **without `masked=True`**, so `-9999` fill cells were read as real elevations. `estimate_rigid_xyz` then sampled fill-vs-real pairs and produced a garbage vertical shift `dz` (reported up to ~10,000 m). `apply_xyz` added that `dz` to **every** HR cell and rewrote `hr.tif`. Two consequences:
1. **Leaked fill:** fill became `-9999 + dz` while the nodata tag stayed `-9999`, so `read(masked=True)` no longer masks it — it contaminates every isfinite metric.
2. **Corrupted vertical datum:** the real seafloor was shifted by the garbage `dz`.

Reported scope: **22/32 pairs fill-leaked, 15/32 vertical-suspect (`|dz|>50 m`)**. Verification example from the prior report: `AT37-13` HR ranges +3930…+6465 m with fill at −2068.78 (= −9999+7930).

**Verify the diagnosis independently before repairing:** open a suspect pair's `hr.tif` raw, confirm the fill sits at `−9999 + dz` (not −9999) and the seafloor values are physically implausible for the site. If the bug is *not* as described, STOP and report — the diagnosis itself may be a degraded-instance artifact.

---

## Step 1 — independently reconstruct the repair value per pair

For each of the 15 vertical-suspect pairs (and re-screen all 32 to confirm the count):
1. Open HR **with `masked=True`** so `-9999` (and the leaked `-9999+dz`) are excluded.
2. Re-run the rigid co-registration on **real cells only** (the F.5 `joint_valid` mask — but spot-check that mask is itself correct, since F.5 was suspect).
3. Derive your own repair `dz`. The prior report claims F.5 re-coreg `dz ≈ −(Stage F dz)` for large cases. **Confirm that relationship from your own run**; do not copy the prior `dz` values.

## Step 2 — repair `hr.tif` (masked, append-only)

For each confirmed vertical-suspect pair:
1. Re-clean fill → `NaN` (strip the leaked `-9999+dz` and any `-9999`).
2. Apply your verified repair `dz` to the real cells, restoring the true datum.
3. Rewrite `hr.tif` with a clean nodata tag (`NaN`), opened/written `masked=True` throughout.
4. Keep the pre-repair file (e.g. `hr_preF5repair.tif`) — append-only; don't destroy the evidence.

## Step 3 — absolute-depth sanity check (ALL advancing pairs, not just the 15)

Repairing the arithmetic is necessary but not sufficient — confirm the result is *physically true*:
- For every pair advancing toward Stage G, check the repaired HR seafloor sits at **physically correct absolute depths for that site** (e.g. a margin site at ~1–2 km, a vent/abyssal site at its known depth) — not merely that `dz` inverted.
- Run this on the 9 "clean" pairs too: 2 of them (`AT37-13`, `AT42-03`) are vertically corrupted despite passing the horizontal lock, and a sub-50 m corruption could hide under the flag threshold on others.
- Any pair whose repaired depths are still implausible → flag, do not advance.

## Step 4 — MANDATORY: did the 21 validated pairs go through the buggy code path?

The 21 validated pairs are the calibration anchor everything is measured against. **Determine whether they were ever harmonized by the unmasked-open code path** (same `stage_f_harmonize.py` coreg, or an earlier/different version). 
- If they predate this code / used masked opens → confirm clean, record the evidence.
- If they went through the buggy path → their HR datums may be corrupted, which is far worse than the 15 new pairs. **Escalate immediately** — do not "repair" the untouchable 21 without explicit assessment + Steve sign-off; just report the finding with evidence.
- This is read-only verification on the 21. Do not modify them.

## Step 5 — re-verify the F.5 masks and tile index

Since F.5 was also produced by the suspect instance:
- Spot-check that `hr_valid` / `lr_valid` / `joint_valid` actually exclude the leaked fill (not just `-9999`, but `-9999+dz`).
- Confirm `valid_tiles.parquet` tiles are genuinely valid-on-both-sides on a sample.
- If the masks are wrong, they must be rebuilt before Stage G — the training-sampling guarantee depends on them.

## Step 6 — report + HOLD

Write `stage_f_repair_report_2026-06-23.md`: your independent bug verification, per-pair repair `dz` (yours vs the prior report's), the absolute-depth sanity results (all advancing pairs), the 21-validated bug-path finding, the mask re-verification, and the final list of pairs that are (a) not excluded, (b) clean/repaired-and-depth-sane, (c) masked. 

**HOLD for assessment** before Stage G. Only fully-repaired, depth-sane, correctly-masked pairs advance.

---

## Guardrails

- **`masked=True` on every HR open/write.** This is the entire root cause — do not reintroduce it.
- **Append-only.** Keep pre-repair files. The 21 validated are read-only (Step 4 is verification only).
- **Independently re-verify before trusting any prior number.** The diagnosis, the `dz` values, and the masks all came from a possibly-degraded instance.
- **QGIS visual QC is the arbiter**; escalate disagreements rather than reconciling silently.
- **No manifest/OAK writes, no Stage G, no exclusions executed** — flag candidates for assessment.

## Deliverables

1. repaired `hr.tif` (masked, clean nodata) + retained pre-repair files, for the confirmed vertical-suspect pairs
2. `stage_f_repair_report_2026-06-23.md` (independent verification + repair `dz` + depth-sanity + 21-validated finding + mask re-verification)
3. updated `combined_corpus.csv` (repair status, depth-sanity verdict per pair)
4. updated `staging_state`

## Tracked carry-overs (unchanged)

Discovery footprint-bbox gate (next harvest); 6 orphan `cal_dig` sub-dirs (before Stage G); raw purge per retention policy; the 3 inflated + 6 weak + 14 coreg_fail exclusion/arbitration candidates (Stage G prep, after repair).
