# Acquisition Directive v1.5.2 — CRS recovery for excluded grids

**Amends** v1.5 / v1.5.1 Stage A. Many HR landed in `excluded`, and some are there only because their GMT `.grd` lacks an embedded CRS — a missing label, not bad data. This adds a **safe, metadata-first CRS recovery pass** over the recoverable subset and re-tiers whatever recovers. Read-only/append-only; no mass download; the gate is re-issued as a new dated file afterward.

**Do not** blind-assume EPSG:4326 (the rejected option) — recovery is metadata-driven and **verified against an independent statement of location**, or the file stays excluded.

---

## 0. First — emit the excluded-by-reason tally (do this before any recovery work)

The current gate reports `excluded: 36` but the exclusion rule conflates two unrelated populations:
- **ratio rejects** — `res_ratio > 40` or `< 5`. These are genuine; recovering them would defeat the ratio gate. **Leave them excluded.**
- **CRS failures** — `excluded_recoverable: Stage B — GMT .grd lacks embedded CRS …`. These are rescuable.

Produce a breakdown of `excluded` by `tier_reason` (count by reason, with `hr_class`/terrain), so we know whether this is a handful or a large subset **before** spending effort. Report it. Recovery in §1 applies **only** to the CRS-failure subset; ratio rejects are never touched.

---

## 1. CRS recovery pass (CRS-failure subset only)

For each `excluded_recoverable` (CRS) HR, resolve the CRS in this order, stopping at the first that yields one:

1. **Metadata (preferred).** Read the dataset's MGDS **ISO19115** record (already harvested) for the spatial reference / projection. Also check for a sidecar `.prj` / `.aux.xml` / landing-page projection statement shipped with the grid. If a CRS is stated, use it; record `crs_source=metadata`.
2. **Constrained inference (only if metadata gives no CRS).** Read the `.grd` header coordinate ranges:
   - x ≈ −180..180 and y ≈ −90..90 → geographic (EPSG:4326).
   - x in ~10^5–10^6 and y in ~10^6 → UTM; pick the **zone from the dataset's known centroid longitude** (from the ISO bounding box), hemisphere from latitude sign.
   - Anything that fits neither pattern cleanly → **do not guess**; leave excluded (`crs_unrecoverable`).
   Record `crs_source=inferred` and the rule that fired.

---

## 2. Mandatory verification (this is what makes inference safe)

Every recovered/inferred CRS must pass an independent location check before the grid is accepted:
- Georeference the grid with the candidate CRS, compute its extent, and confirm it falls **inside the dataset's independently-stated geographic bounding box** from the ISO record (small tolerance allowed).
- If the georeferenced extent lands outside that bbox (wrong zone, wrong hemisphere, projected-treated-as-geographic, wrong ocean) → **reject the CRS**, keep the grid excluded as `crs_failed_verification`. Never accept a CRS that doesn't reconcile with an independent statement of where the data is.
- Metadata-sourced CRS is verified too — a stated CRS that fails the bbox check is still rejected.

---

## 3. Re-tier the recovered grids

For grids that recover a verified CRS:
- Run the normal Stage B geometry resolution (valid-data-mask extent), recompute true overlap + `res_ratio`.
- Apply the standard tiers: training ≤25×, eval-only 25–40×, `raw_lr_to_grid` if the LR is a raw cruise, **excluded if the real ratio fails** (>40× or <5×). A recovered CRS does not exempt a grid from the ratio gate — it just lets the grid be measured.
- Record `crs_source` and the recovery path on each so provenance is auditable.

---

## 4. Re-issue the gate (new file, do not overwrite)

Write the updated Gate A as a **new dated/versioned file** in the reports repo (e.g. `reports/gates/stage_a_gate_20260604_v3.md`) — do not overwrite `_v2`. Include: the excluded-by-reason tally (§0), how many CRS grids recovered vs. stayed excluded (`crs_unrecoverable` / `crs_failed_verification`), and the updated tier counts + storage. Pause for human sign-off.

---

## Hard rules

- Ratio rejects are never "recovered" — recovery applies only to the CRS-failure subset.
- No blind CRS assumption; metadata first, constrained inference second, and **every** CRS verified against an independent bbox or the grid stays excluded.
- Read-only/append-only against existing pairs (DISCOL, 18 Cal DIG, CCZ, TAG untouched); reports appended as new files, never overwritten.
- No mass download; recovery uses already-harvested metadata + grid headers (HR header reads are cheap).

## Acceptance

- Excluded-by-reason tally reported before recovery runs.
- Recovered grids each carry a verified CRS reconciled to their stated bbox; unverifiable ones remain excluded with an explicit reason.
- Re-issued gate (new file) shows the true post-recovery tier counts; ratio rejects unchanged.
