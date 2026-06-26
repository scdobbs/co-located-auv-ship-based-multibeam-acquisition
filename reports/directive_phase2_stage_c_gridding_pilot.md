# Directive — Phase 2 Stage C: MB-System gridding PILOT

**Date:** 2026-06-23 · **For:** Phase 2 Claude Code execution instance · **After:** Stage B recovery · **Before:** full Stage C gridding (next directive).

*First real MB-System gridding run. This is a deliberately small, spanning **pilot** — grid a handful of cruises that exercise the failure-prone cases, learn what the processing chain actually needs, calibrate the ratio estimator against measurement, then **HOLD for assessment review** before gridding the other ~33 cruises. Gridding is the most novel step in the whole phase; we slow down here on purpose.*

**Corpus state going in:** legacy-7 excluded (Steve, 2026-06-23) → 63 HR. 38 swath-complete raw-LR cruises on `$DATA_ROOT/raw_lr/`. MB-System verified (Apptainer sandbox).

---

## Guardrails

- **PILOT only.** Grid the C1 pilot set, then stop. No full run without the next directive.
- **Per-cruise gridding, never a cross-cruise mosaic.** One independent ship cruise per LR grid.
- **Estimate, then measure.** Record the pre-grid physics estimate *before* gridding so a wildly-off result is caught immediately.
- **Native resolution from sounding density, not the cell size you asked for.** A grid can be posted finer than the soundings support; the true resolution is where real soundings back the cells (fill fraction).
- **Gridded LR → working dir on `$DATA_ROOT`** (`raw_lr_gridded/`). **No OAK writes, no manifest writes, no re-tier, no harmonization.** Those are Stages E/F/G.
- **Raw kept** (retention policy: no purge until post-pilot, post-QC, params final).
- **QGIS visual QC is the arbiter.** Produce a per-pair overlay for every pilot pair; a clean metric does not override a bad-looking grid.
- **Escalate surprises** (format failures, holes over the footprint, depth nonsense) — don't absorb.

---

## C0 — pin the MB-System build + datalists

1. **Record the reproducibility pin** (the loose end from recovery): the `mbari/mbsystem` image **digest** and the **MB-System version string** (`mbsystem --version` or the build banner) the sandbox was built from. Every grid we produce is only reproducible against a known build — capture it now while it's known, into `mbsystem_build_pin.txt`.
2. Confirm the working invocation + bind mounts (`--bind /scratch,/home/groups,/oak`).
3. Per pilot cruise, build the MB-System **datalist**; auto-detect format per file (`mbformat`). Flag any file whose format is ambiguous rather than guessing.

---

## C1 — pilot set (5 cruises, chosen to span the risk surface)

Recommended set; confirm the sonar/depth spread and **substitute with justification** if a cruise turns out unrepresentative:

| cruise | why it's in the pilot |
|---|---|
| **2009_Amundsen** (subset) | the novel Arctic case **and** a subset cruise — tests whether the intersecting-files-only fetch grids into coherent LR over the footprint (a hole here means the subset missed coverage) |
| **TN299** (watch) | thin edge-of-survey overlap — the outer-beam coverage-quality call A.6 deferred to gridding |
| **KN210-05** | deep (~5 km), `.xse`/`-F94` — already `mbinfo`-verified in recovery; a known-readable deep case |
| **AR26** | modern EM710 (`.all`/`-F58`) — the resolved-HEAD cruise; a clean shallow/margin contrast |
| **FK181031** | Falkor EM302/712 class — a third sonar family, mid-depth |

Report the final set with sonar format + median depth per cruise, so the spread is on the record.

---

## C2 — per-cruise gridding chain

For each pilot cruise:

1. **Pre-grid ratio estimate.** From the sonar beamwidth + median depth: footprint ≈ `2 · depth · tan(beamwidth/2)` → expected achievable LR cell size. Record it before gridding.
2. **Process** (minimal, sane — don't over-tune; the pilot is how we learn what's needed): `mbdatalist` → automated outlier flagging (`mbclean` defaults) → `mbprocess`. Record the parameters used; note if a cruise visibly needs more cleaning.
3. **Grid** over the cruise's HR-footprint union + margin (reuse the A.5/A.6 footprint polygons). Cell size = the estimate from step 1 (for a geographic grid, convert to degrees at the cruise's mean latitude). Record the interpolation/filter setting; **do not** infill large gaps silently.
4. **Measure (sounding-density native resolution).** Report: achieved cell size, **fill fraction** (cells backed by real soundings vs interpolated), and depth-range sanity (vs known cruise depth). If the grid is heavily interpolated at the requested cell, the *true* native resolution is coarser — report that coarser, sounding-supported value as `lr_native_res_m`.
5. **Provisional ratio** = `lr_native_res_m / hr_native_res_m`. **Flag pairs whose HR is `ok_finer_verify`** — their HR resolution is unverified, so the ratio is provisional pending Stage D; do not treat it as final.
6. **Coverage-quality** (mandatory for TN299, run for all): over the HR footprint, is the LR adequate-density near-nadir coverage, or sparse high-incidence outer-beam grazing? Give a `near_nadir` / `outer_beam_grazing` verdict. `outer_beam_grazing` → candidate Stage-C exclusion (flag, don't exclude).
7. **QGIS-ready QC overlay** per pair: LR hillshade + HR footprint outline, for visual inspection.

---

## C3 — pilot review report + HOLD

Write `stage_c_pilot_report_2026-06-23.md`:

- **Per-cruise table:** sonar/depth, estimate vs measured cell, fill fraction, `lr_native_res_m`, provisional ratio (+ `ok_finer_verify` flag), coverage verdict, any gridding failures/artifacts.
- **Estimator calibration:** estimate vs measured across the 5 — is the pre-grid physics estimate trustworthy enough to pre-screen the full run, or does it systematically mis-predict?
- **Watch-cruise call:** TN299 coverage verdict — now decidable; recommend keep or exclude (for assessment).
- **Processing-chain learnings:** what `mbprocess`/`mbclean` settings the full run should use; any cruise needing special handling.
- **Flags:** any cruise that gridded poorly (holes over footprint, format trouble, depth nonsense) — these reshape the full-run plan.

**HOLD for assessment review.** No full Stage-C run until the next directive. The pilot's job is to surface what breaks before 33 more cruises grid unattended.

---

## Deliverables

1. gridded LR for the 5 pilot cruises (`$DATA_ROOT/raw_lr_gridded/`)
2. per-pair QGIS QC overlays
3. `stage_c_pilot_report_2026-06-23.md`
4. `mbsystem_build_pin.txt` (image digest + version)
5. updated `staging_state`

## Out of scope

Full gridding run (post-review), re-tier (Stage E), harmonization/co-registration/QA (Stage F), manifest/OAK writes, HR `native_res` re-derivation (Stage D — flag where a provisional HR res blocks a final ratio, but don't solve it here). The 6 orphan `cal_dig` sub-dirs remain a tracked pre-Stage-G item.
