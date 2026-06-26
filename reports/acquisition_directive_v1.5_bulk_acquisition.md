# Acquisition Directive v1.5 — Bulk Acquisition (criteria-based, large training set)

**Builds on** v1.4 / v1.4.1 (discovery) and reuses the validated v1.0–v1.3 harmonization / co-registration / QA / manifest path. Goal: acquire **all distinct AUV grids that have a real, independent ship-multibeam LR**, as a large training set — selected by criteria, not hand-triaged.

**Append-only.** New pairs are added to the manifest; DISCOL, the 18 Cal DIG, CCZ, and TAG are never modified, re-run, or deleted.

---

## 0. Key correction up front — select on distinct HR, not pairs

The `pairs` layer (2,541 rows) is **fan-out** — one AUV grid × up to ~50 ship cruises. Downloading "all pairs" would fetch the same AUV grid dozens of times. Select on **distinct AUV HR, one best independent LR each**. After dedup the universe is ~132 HR / ~129 AUV; 78 are in the current triage tier and 48 are held as `footprint_suspect`. "All AUV with LR overlap" means **~125 distinct grids**, not 2,541 and not 78.

---

## 1. Why a criteria filter, not "everything"

Taken literally, "everything" would poison the set. The M3.1 ratio distribution is median **46×**, p75 **60×**, max **207×** — almost all far past where super-resolution is meaningful. At 50–100× the LR carries essentially none of the HR's structure, so those pairs train the model to *hallucinate* fine morphology rather than *recover* it — the exact failure this project exists to avoid. A large set dominated by 50×+ pairs is worse than a smaller one in the usable band. So we filter on ratio and select everything that passes.

---

## 2. Stage A — Criteria selection (automated; replaces manual triage)

From the discovery catalog, select distinct AUV HR where **all** hold:
- platform filter = `auv` (not surface-vessel / ambiguous);
- a best **independent** LR exists (per-cruise NCEI/PANGAEA, never a composite; LR is hull/ship MBES, not the AUV's own data archived under the host cruise);
- LR overlap ≥ `pair_qa.min_overlap_area_km2` **(provisional — re-checked after true geometry in Stage D)**;
- resolution ratio within the training band.

**Tiering by ratio** (config; propose, human-confirm — do not invent):
- `ratio_train_max` = **25×** → training tier;
- 25–`ratio_eval_max` (**40×**) → **eval-only tier** (flagged, never mixed into training);
- > 40× → **excluded** from acquisition.

`footprint_suspect` HR are **included for acquisition** (their geometry is resolved in Stage B) but their ratio/overlap are provisional until then.

**Gate A:** before any mass download, emit the projected selection — count by tier, by province, by geographic cluster, and an **estimated storage footprint** (HR + raw LR to grid). Pause for human sign-off on the criteria, the count, and the storage number. Do not start bulk download until confirmed.

---

## 3. Stage B — HR acquisition + true geometry (resolves the suspects)

For each selected HR: download the grid (MGDS FileDownloadServer / source archive; reuse local copies where present, e.g. user-provided Cal DIG), then **compute the true valid-data extent from the grid's non-nodata mask** (the fix the MGDS bbox couldn't do without the file in hand). Replace the provisional footprint. This is where the 48 `footprint_suspect` grids get real outlines — expect some to shrink dramatically.

---

## 4. Stage C — LR acquisition + gridding

For each HR's selected LR cruise:
- Prefer a cruise with an existing **processed grid/BAG** (`lr_has_processed_grid`) — fetch it directly.
- Otherwise the NCEI holding is **raw multibeam** → grid it with **MB-System (`mbgrid`)** to a depth-appropriate GSD (beam-footprint rule), and **QC the LR grid** (artifacts, track-line gaps) before use — gridded raw data has its own failure modes.
- Record the **actual achieved LR GSD** and `lr_res_source = gridded|processed`.
- Re-confirm independence: the LR must be hull/ship MBES, not an AUV product archived under the same cruise.

---

## 5. Stage D — Post-resolution re-filter (the honest attrition step)

Now that HR extents (Stage B) and real LR GSDs (Stage C) exist, recompute **true HR∩LR overlap** and **real `res_ratio`**, then re-apply Stage A criteria:
- Drop pairs whose overlap fell below threshold once the true (smaller) HR footprint was used — expect attrition among the former suspects; record them as `dropped_no_overlap`, don't silently lose them.
- Re-tier by the *real* ratio (a pair estimated at 20× may land at 45× once the LR GSD is known) → training / eval-only / excluded.
- The surviving training tier is the actual large set.

---

## 6. Stage E — Harmonize + co-register + QA at scale

Run the validated v1.0–v1.3 path per surviving pair: single-warp reproject (never nearest; skip if CRS matches), clip to overlap, **fresh co-registration**, v1.1 §A QA (offset vs USBL bound, PSR, eig_ratio, peak_agrees, MAD), overlay PNG.

**Scaled human gate:** ~125 pairs is too many to eyeball every overlay. Let the automated v1.1 flags do the first cut — `auto_pass` pairs proceed; only pairs that trip a flag (offset > bound, high eig_ratio / along-axis-slide signature, low PSR, peak disagreement) route to `needs_review` for human overlay inspection. Review the flagged subset, not all 125.

---

## 7. Stage F — Province + cluster tagging (leakage-safe splits)

These sites cluster hard (Axial, Juan de Fuca, Monterey, Cascadia, Loihi). Two near-identical patches on opposite sides of a train/test split would leak — the LuciaChica problem at scale. So tag every pair with `terrain_class` and a `geo_cluster` (spatial grouping of nearby HR), and emit split-ready metadata so downstream train/val/test can be **stratified by province and grouped by cluster** (no cluster spans the split). Do not assign the split here — provide the grouping so the modeling step can.

---

## 8. Stage G — Audit + manifest

Append surviving pairs to `pairs.parquet` with full provenance (`hr_source_type`, DOIs, true footprint, achieved LR GSD, ratio, tier, terrain, geo_cluster, coreg metrics, license). Run the v1.2.2 completeness audit (accounting identity: rows == processed + rejected + dropped, no stale/error states), the provenance audit (DOI-match for PANGAEA/USGS; sidecar+attestation for user-provided), and the independence audit. Existing rows untouched.

---

## 9. Storage & operational

- All bulk data on `$DATA_ROOT` scratch, never home. This is the jump from ~2.4 GB to plausibly tens–hundreds of GB — raw LR cruises are the bulk.
- **Raw-LR retention is a decision** (config): default retain the gridded LR product; optionally purge the raw cruise files after gridding + QC to control footprint (note scratch purge policy regardless). Flag the projected size at Gate A.
- APIs only; cache; resumable/idempotent; throttle NCEI/MGDS.

---

## 10. Milestones & gates

- **Gate A — selection sign-off.** Projected count/tier/province/cluster + storage estimate. Human confirms criteria and scope before mass download.
- **M5.0 — pilot batch.** Run Stages B–G end-to-end on ~10–15 pairs spanning provinces (include a former `footprint_suspect`, a raw-LR-needs-gridding case, and a known-good like a Loihi/TAG pair) to prove gridding + geometry-resolve + coreg + QA at scale. **Pause for review.**
- **M5.1 — full run** on the remaining selected set after the pilot validates. Automated QA flags drive the per-pair gate; human reviews only flagged pairs.
- **M5.2 — finalize.** Manifest appended, audits pass, attrition + tier + cluster report delivered.
- Tier handoff to modeling: training tier (≤25×) vs eval-only tier (25–40×) clearly separated; cluster grouping provided for leakage-safe splits.

---

## 11. Hard rules

- Select on distinct HR, one best independent LR each — never the fanned-out pairs.
- Filter by ratio: training ≤25×, eval-only 25–40×, exclude >40× (thresholds human-confirmed).
- Resolve true HR geometry before trusting overlap/ratio; expect and record attrition.
- Never pair against a composite LR; LR must be independent hull MBES.
- Read-only / append-only against all existing pairs and harmonized data.
- Bulk data on scratch only; flag storage at Gate A.
- Scaled QA: automated flags first cut; human reviews the flagged subset.
EOF
