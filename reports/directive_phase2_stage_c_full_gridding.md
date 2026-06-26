# Directive — Phase 2 Stage C: full MB-System gridding run

**Date:** 2026-06-23 · **For:** Phase 2 Claude Code execution instance · **After:** Stage C pilot (reviewed, approved) · **Before:** Stage E re-tier / Stage F harmonize.

*Grid the remaining swath-complete cruises with the pilot's corrections locked in. The pilot proved the chain end-to-end; this run applies it at scale with the measurement fixes that mattered. LR native resolution is the definitive deliverable here; ratios are **provisional/informational only** until Stage D supplies HR resolution — no tiering in this stage.*

**Inputs locked from the pilot:** MB-System 5.8.2beta06 (Apptainer sandbox, image `sha256:106f502d…`). Measure on the **true HR footprint polygon**, never the bbox. Cell estimate uses **footprint-local depth**, not the cruise-wide `mbinfo` median. **Decompress `.gz` before gridding** (MB-System reads 0 records from gzip).

---

## Guardrails

- **Per-cruise gridding, never a cross-cruise mosaic.**
- **LR native res is definitive** (we hold the raw soundings); **provisional ratio is informational only** — no tiering, no exclusions executed. Tiering is Stage E (after Stage D).
- **Measure inside the footprint polygon**, at footprint-local depth. The bbox proxy mis-ranked a pilot pair by ~2× — it is not permitted here.
- **Gridded LR → `$DATA_ROOT/raw_lr_gridded/`.** No OAK/manifest writes, no re-tier, no harmonization. Raw kept (no purge — this is the first full run; purge waits for post-QC, params-final).
- **QGIS visual QC is the arbiter** — a per-pair overlay for every pair; a clean metric does not override a bad-looking grid.
- **Escalate** gridding failures, holes over a footprint, depth nonsense, fill < 0.3 — don't absorb.

---

## C-full-0 — processing-policy spot check (do this first)

The pilot found serial `mbclean` untenable (3.5 h hang on Amundsen) and gridded raw above a file cap. Grid-raw trades a speed problem for a quality risk (uncleaned outlier spikes blow out cells, and fill/depth sanity doesn't catch spikes). Resolve it properly:

1. On **one mid-size multibeam cruise** (~100–300 files, an EM302/EM710 cruise not in the pilot), grid two ways: **raw** vs **per-file parallel `mbclean` → `mbprocess`**. Parallelize cleaning across cores — cleaning is cheap when not serial.
2. Compare the two grids over the footprint: % of cells changed materially, spike presence, fill, depth sanity.
3. **Default to parallel-`mbclean` for the full run** (the safe choice). Fall back to grid-raw **only if** the spot check shows cleaning changes the grid negligibly **and** parallel-`mbclean` is genuinely time-infeasible. Report the chosen policy with the spot-check evidence.

---

## C-full-1 — per-cruise gridding (Slurm array, parallel)

For each of the ~33 remaining swath-complete cruises (38 − pilot − any already excluded; reconcile the exact list):

1. Decompress `.gz` → node-local `$L_SCRATCH`; clean up node-local after gridding. (Budget node-local space for the largest uncompressed cruise — ~60 GB for Amundsen-class.)
2. `mbdatalist` → processing per the C-full-0 policy → `mbgrid` over the cruise's **HR-footprint-union + margin**, cell = footprint-local-depth estimate (`2·depth·tan(beam/2)`, depth = median of soundings *inside* the footprint).
3. **Multi-HR cruises:** grid once over the union footprint, then measure per-HR-footprint separately (the pilot's FK181031→{24367,24620} and TN299→{27339,31256} pattern).

---

## C-full-2 — LR native resolution (definitive) + provisional ratio (informational)

Per HR footprint:

1. **Fill fraction** inside the footprint polygon.
2. **Native resolution:**
   - If the provisional ratio lands **within 20 % of a tier edge** (5 / 25 / 40): **measure real median sounding spacing inside the footprint** (`mblist` the soundings → median nearest-neighbour spacing). We have the raw soundings, so this is the *true* LR native res — use it, not a proxy, wherever a pair could flip a tier.
   - Otherwise: the `native = cell/√fill` proxy is adequate.
3. **Provisional ratio = `lr_native_res / hr_res`**, where `hr_res` is the **A.6-measured grid cell** (join `hr_resolution_sanity.csv`) — **not** the catalog `native_res_m` (NaN for many HR; that's the pilot's "3 unrankable" plumbing gap, not a real unknown). Flag every provisional ratio, and double-flag `ok_finer_verify` HR. **This ratio is informational triage only** — the authoritative HR res and the tier come from Stage D / Stage E.
4. **Coverage verdict** per footprint (`near_nadir` / `outer_beam_grazing`). Grazing → candidate Stage-E exclusion (flag, don't exclude).

---

## C-full-3 — QC + skeptical sanity

- **Per-pair QC overlay**: LR hillshade + the real footprint-polygon outline, for visual inspection.
- **Per-pair sanity:** plausible depth range, no all-nodata, footprint fill ≥ 0.3 (flag below), no hole over the footprint.
- **Corpus sweep:** distributions of `lr_native_res`, footprint fill, provisional ratio, and coverage verdict across all gridded pairs — flag outliers a per-pair check would miss (the cell-size-sanity-sweep lesson, applied to the LR side).

---

## C-full-4 — report + HOLD

Write `stage_c_full_report_2026-06-23.md`:
- **Per-pair table:** sonar, footprint-local depth, achieved cell, footprint fill, `lr_native_res` (+ method: real-spacing vs √fill proxy), provisional ratio (flagged; `ok_finer_verify` noted), coverage verdict, QC pass/fail.
- **Lists:** candidate excludes (outer-beam grazing, or raw cell already > 40× regardless of HR res — those exclude safely now), pairs awaiting Stage-D HR res, any gridding failures.
- **Carry-forward to Stage D/E — the contamination asymmetry:** the dangerous error is *over-coarse* HR (HR res too large → ratio understated → a pair wrongly enters training). So Stage D must justify any HR res **coarser than its grid posting** with sounding-density/spectral evidence, and any pair that moves **into** training on a Stage-D coarsening gets extra scrutiny. Over-fine HR only over-excludes (safe). Record this explicitly so Stage E doesn't treat a Stage-D coarsening as routine.

**HOLD for assessment** before Stage E (re-tier) and Stage F (harmonize). The full ratio/tier picture isn't real until Stage D lands.

---

## Sequencing note

**This run does not wait on Stage D.** LR gridding produces LR native res independently; Stage D produces HR res; Stage E combines them. Grid every remaining cruise now — the pairs that can't yet be *tiered* can still be *gridded*. Stage D proceeds in parallel under its own directive.

## Deliverables

1. gridded LR for all remaining cruises (`$DATA_ROOT/raw_lr_gridded/`) + per-pair QC overlays
2. `stage_c_full_report_2026-06-23.md` + `stage_c_full_measurements.json` (polygon + bbox fills, native-res method per pair)
3. processing-policy spot-check result
4. updated `staging_state`

## Out of scope

Re-tier (Stage E), harmonization/co-registration/QA (Stage F), Stage-D HR-res derivation (parallel track), manifest/OAK writes, retention purge (after the full run clears QC). The 6 orphan `cal_dig` sub-dirs remain a tracked pre-Stage-G item.
