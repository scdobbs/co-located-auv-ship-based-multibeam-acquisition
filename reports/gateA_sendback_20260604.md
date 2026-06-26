# Gate A — send-back before sign-off (2026-06-04)

MGDS is unblocked (the FileDownloadServer URL had **moved**, not gone down — it's a corrected endpoint, not an outage). Good: nothing needs to be deferred now — the full selection is reachable, so resolve everything and re-issue an honest gate rather than signing off on a partial/contradictory one. **Do not start Stage B/C mass download yet.** Three fixes, then re-issue Gate A.

## 1. Resolve geometry for all 37 `needs_geometry` now, then re-tier

These are MGDS `footprint_suspect` grids that were only stuck because of the (now-fixed) download URL. HR download is ~1 GB, so there's no reason to leave them untiered. Per v1.5.1 §2: run Stage B geometry resolution (download HR + compute valid-data-mask extent) on **all 37**, recompute true overlap + `res_ratio`, and tier them before re-issuing the gate. Record attrition (`dropped_no_overlap`) for any whose true footprint loses LR overlap. 20 of the 37 are `volcanic_or_seamount` — the province currently at zero coverage — so this is the high-value bucket; the gate's real training count is not knowable until these resolve.

## 2. Reconcile the raw-LR contradiction (the throttle question)

The report contradicts itself on the core LR policy:
- Criteria (line ~10): "No processed-grid filter… raw LR cruises enter Stage C gridding."
- Storage note (line ~68): "Raw-LR cruise files are not fetched (per v1.5 decision: processed-grid-only selection at Gate A)."
- Confirm item 2 (line ~93): "Processed-grid-only LR policy at Gate A."

These can't all hold, and the ~8.94 GB total is consistent with raw LR **not** being included. Disambiguate explicitly:
- If raw LR is genuinely in selection + routed to Stage C gridding (the v1.5.1 §1 intent), **say so**, drop the stale lines 68/93, and **re-estimate storage including raw-LR cruises to be gridded** (the realistic figure is well above ~9 GB).
- If selection is still effectively processed-grid-only, **say that plainly** — and fix it, because v1.5.1 §1 removed that throttle. Re-check whether the 17 `needs_LR_res` HR are parked only because their LR is raw/un-gridded; those should flow into Stage C, not be dropped at the gate.

The gate cannot be signed until it's unambiguous whether this is the bulk set or a processed-grid-only subset wearing the right label.

## 3. Fix the stale text

Remove/replace the processed-grid-only language at lines ~68 and ~93 so the document is internally consistent with the v1.5.1 criteria.

## Reporting requirement (do not overwrite prior reports)

Write the re-issued gate as a **new, dated/versioned file** in the reports repo — do **not** overwrite the existing `stage_a_gate_*` files. Use a distinct name (e.g. `reports/gates/stage_a_gate_20260604_v2.md` or a run-ID suffix) so the prior gate summaries remain intact as an audit trail. Same rule going forward: every gate/milestone report is appended as a new file, never an in-place overwrite of an earlier one. (This mirrors the read-only/append-only guarantee already applied to the manifest and harmonized data.)

## Keep as-is (already correct)

- Tier thresholds: training ≤25×, eval-only 25–40×, exclude >40× or <5×.
- Ratio-gated, platform-agnostic inclusion; `hr_class` + native res recorded.
- Independence rule (no composite / same-platform LR); one row per distinct HR, best independent LR.
- Pilot composition — picks #2 (`needs_geometry`) and #3 (`needs_LR_res`) sensibly exercise both resolution paths; fine once §1/§2 are settled.
- Read-only/append-only against existing pairs (DISCOL, 18 Cal DIG, CCZ, TAG untouched).

## Watch item (not a blocker)

cluster_000 now holds 9 of 26 training HR — a third of training in one 50 km cluster. Keep the per-pair `geo_cluster` tag accurate so the downstream split can keep that cluster on one side; flag if the 50 km radius is bundling distinct features.

## After re-issue

Pause for human sign-off on the corrected gate (true tiered count + honest storage). Then M5.0 pilot → review → full Stage B–G run.
