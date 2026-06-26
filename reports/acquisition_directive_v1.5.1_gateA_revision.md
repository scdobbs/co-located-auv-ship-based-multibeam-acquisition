# Acquisition Directive v1.5.1 — Gate A revision (don't throttle the bulk set)

**Amends** v1.5 Stage A. The 2026-06-04 Gate A summary is honest but yields only **7 training pairs** — that's not the large set we're after. The gate added a criterion that wasn't in v1.5 and deferred the step that would size the dataset. Fix four things, then re-run selection and re-issue Gate A. Still **no mass download until the revised gate is signed off**; read-only/append-only against existing pairs preserved.

---

## 1. Drop the processed-grid-only LR criterion (the main bottleneck)

Gate A criterion 4 ("LR must have a NOAA NCEI Multibeam **Products** record / processed grid available") is **not** in v1.5 and contradicts it — v1.5 §4 says most NCEI LR is **raw** and to **grid it with MB-System in Stage C**. Restricting to already-gridded cruises excluded the large majority of co-located ship multibeam, which is exactly why training collapsed to 7 and 17 HR sit in `needs_LR_res`.

**Restore v1.5 intent:** select LR on co-located **independence** (per-cruise, hull MBES, not composite, not the AUV's own data), regardless of whether a processed product exists. A raw cruise is a valid LR — it just enters the Stage C gridding path. Re-tier the 17 `needs_LR_res` against their real LR once gridding/lookup gives a GSD; most should become training/eval, not be parked.

---

## 2. Resolve geometry **before** tiering, not after (un-defer the 35)

The 35 `needs_geometry` are the `footprint_suspect` MGDS grids — and they're the **bulk of the inventory**. They can't be tiered because their true extent hasn't been computed, so the gate currently can't tell you how big the dataset is.

HR download is trivial in size (the entire training HR side was 0.24 GB). So **run v1.5 Stage B (download HR + compute valid-data-mask extent) on all `needs_geometry` HR now**, before re-issuing Gate A. Then recompute their overlap + ratio and tier them normally. Expect some attrition (suspects that shrink below the overlap threshold) — record those as `dropped_no_overlap`. The point is the revised Gate A reflects the *real* dataset size, not a deferred unknown.

---

## 3. Fix terrain inference (province balance is currently untrustworthy)

`unknown` still dominates every tier × terrain cell, so the v1.4.1 §3 terrain inference did not fire. Apply it before re-issuing the gate: derive `terrain_class` from depth + AUV survey name/region (MBARI/Sentry names are descriptive), mark `terrain_source=inferred|metadata`. Without this the province breakdown — the thing that tells you which gaps the bulk set fills — is noise.

---

## 4. Plug the Zephyr leak (platform filter consistency)

`MGDS:21415` (R/V Zephyr, 4.1 m) appears in the pilot picks as `needs_geometry`/"canyon" — but v1.4.1 §3 should have classified it `surface_vessel` and excluded it. It resurfaced, which means the selection step and the platform filter aren't using the same classification. Make Stage A consume the platform-filter verdict directly (single source of truth); confirm Zephyr / Falkor / Atlantis / Thompson hull entries are excluded from the selection, not just from the earlier triage view.

---

## Keep as-is (these were right)

- Tier thresholds: training ≤25×, eval-only 25–40×, exclude >40× or <1.5×.
- Geographic cluster grouping (50 km) for leakage-safe splits.
- Independence rule (no composite / same-platform LR).
- One row per distinct AUV HR, best independent LR.
- Read-only/append-only; existing manifest untouched.

---

## Re-issue Gate A

After 1–4, regenerate the gate summary. Expectations for the revised gate:
- Training-tier count materially larger than 7 (the `needs_LR_res` and resolved `needs_geometry` HR flow in once LR-independence-only selection and true geometry are applied).
- Storage projection now includes **raw-LR cruises to be gridded** (the realistic tens-of-GB range, not 2.68 GB) — and re-surface the raw-LR retention decision (retain gridded product; purge raw after QC?).
- `unknown` terrain share materially reduced.
- No surface-vessel HR in the selection or pilot.

**Pause for human sign-off on the revised gate before Stage B/C mass download.** The pilot (M5.0) should then include a raw-LR-needs-gridding case and a resolved former-`needs_geometry` case, so the pilot actually exercises the paths that were skipped this round.
