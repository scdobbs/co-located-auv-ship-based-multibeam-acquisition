# Co-located AUV / Ship Bathymetry — Phase 2 Cold-Start Handoff Brief

*2026-06-05. For a **new Claude Code execution instance** on Sherlock, starting with no prior chat history. You are taking over raw-LR gridding and everything downstream of it. Read this fully before running anything. Phase 1 (staging download) is closed; this brief tells you what you inherit and what to do next, in order.*

---

## 1. The project and why it exists

Steve is building a **super-resolution model for seafloor bathymetry** (an SR U-Net with rectified flow) that generates high-resolution seafloor morphology from low-resolution input, with calibrated uncertainty. You are working on the **data pipeline**, not the model — your job is to produce physically valid HR/LR training pairs.

The data-integrity problem the whole repo exists to solve: the obvious global LR products (**GEBCO, GMRT**) ingest the same high-resolution multibeam you'd want as ground truth, so any pair built from them leaks the answer into the input. The fix is **real, physically-independent co-located pairs**:

- **HR = AUV bathymetry** — near-bottom, ~1–2 m grids.
- **LR = ship/hull multibeam** — surface-vessel MBES over the *same footprint*, a genuinely separate acquisition.

AUVs are flown over pre-existing ship maps, so many sites were measured twice, independently. Those are the gold-standard pairs.

---

## 2. How we work — your role

Two parallel Claude roles:

- **You — the Claude Code execution instance on Sherlock.** You have the APIs, filesystem, and compute. You harvest, grid, harmonize, co-register, run QA, write dated reports.
- **The assessment / directive instance.** Writes versioned markdown directives, reviews your reports critically, makes eligibility/tiering calls. You report; it steers.

Steve passes files between instances manually and **makes all consequential decisions** (retention, budget, exclusions). The loop: assessment issues a directive → you execute one milestone and write a dated report → assessment reviews and signs off or sends a fix. **Escalate unexpected findings; never silently absorb them.** Phase 1 caught several defects this way (a 278-byte error stub reported as a clean download, a gate that passed by construction, PDFs admitted as HR) — that scrutiny is the point.

**Human-confirmation gates before consequential actions.** Discovery proposes; human selects; pipeline executes. The gates in §5 below are marked — do not run past them without sign-off.

---

## 3. Working principles (hard-won; uphold these)

- **Anti-circularity / independence is the whole point.** LR must be hull/ship MBES, a genuinely separate acquisition from the AUV. **Never pair against a composite/synthesis** (GEBCO, GMRT, USGS composites, any multi-source compilation). **Never synthesize LR from HR** — resampling is for CRS alignment only.
- **Per-cruise, never composites.** When you grid LR, grid one independent ship cruise per pair. Do not mosaic across cruises in a way that blends sources.
- **True valid-data footprint, not a bounding box.** Inflated bbox envelopes have repeatedly produced false "pairs." Join on real polygons; QGIS visual QC is the arbiter, not a metric.
- **Ratio gates inclusion, not platform.** `res_ratio = LR_native / HR_native`. Training `5 ≤ ratio ≤ 25`; eval-only `25 < ratio ≤ 40`; exclude `>40` or `<5`. A grid qualifies as HR if it passes the ratio test against an independent LR, regardless of platform.
- **Sounding density, not grid posting, for native resolution.** Over-posted/interpolated grids report misleadingly fine cell sizes (Phase 1 saw apparent ~0.1 m cells). Derive native res from real sounding density, not from the grid's cell size.
- **Calibrate thresholds against known truth; never let a guess drive an irreversible decision.** Where a real measurement is coming (ratio after gridding, storage after dry-run), estimate honestly and defer the precise number.
- **Don't trust a metric blindly.** MAD passed spurious co-registrations before; bbox overlap ≠ real overlap; a symmetric cell-size gate failed valid finer-than-declared grids. Sanity-sweep beyond pass/fail.
- **Read-only / append-only against validated work.** Never modify, re-run, or delete existing `manifest/pairs.parquet` rows or harmonized products. Append new pairs only. Every report is a **new dated file**, never an in-place overwrite.
- **Completeness accounting:** rows == processed + rejected + dropped, no stale/limbo states.
- **Storage:** all bulk rasters on `$DATA_ROOT` = `/scratch/groups/hilley/auv_ship_colocated_bathy/`. Never home (~15 GB cap). **Scratch is purge-subject.**

---

## 4. What you inherit from Phase 1

Phase 1 staged the no-gridding-needed downloads and cleaned the HR corpus. **Reconcile these numbers against `staging_state_20260605.json` at startup** — it is the authoritative inventory.

**The validated, untouchable manifest** (`manifest/pairs.parquet`, 21 rows, never modify): DISCOL, 18 Cal DIG sub-pairs, CCZ, TAG.

**Clean HR corpus: 81** (61 `ok` + 10 `ok_finer_verify` + 10 `manifest_seed_clean`). Important framing:

- The **10 `manifest_seed_clean`** (`PANGAEA:tag_m127` + 9 `cal_dig_morro_bay__*`) are **already complete pairs in the untouchable 21**. Do **not** re-process or re-append them — the new bulk selection re-derived them. **Dedup against `pairs.parquet` on every append.**
- That leaves **71 new HR** to pair. Of these, only a small set (~8 distinct processed LR; 9 pairs) have a **processed LR already staged** and can go to harmonization immediately. **The rest have a raw-cruise LR that you must grid** — that is the core of Phase 2.
- The **10 `ok_finer_verify`** HR (`MGDS:21415, 21454, 21462, 24467, 24470, 31253, 31254, 31255, 31321, 31860`) are valid but their declared `native_res` is suspect (measured 2–5× finer). **Re-derive their native res from sounding density before tiering** — an overstated HR res understates the ratio and can hide an eval pair inside training.

**Staging layout:** `$DATA_ROOT/staging_phase1/<hr_id_safe>/` (HR files at root; processed LR under `lr/`). Quarantine at `$DATA_ROOT/quarantine_phase1/`. `$DATA_ROOT` held ~29.7 GB / ~2200 files after Phase 1.

**Raw-LR NOT fetched: 76 cruises** (41 companions of train/eval HR + 35 `raw_lr_to_grid`). These are your fetch-and-grid target.

**Open items carried in (assessment owns the calls; you execute/diagnose):**
- `MGDS:31600` — **quarantined**, multi-tile multi-resolution **compilation** (`d142…valley × {1sec, tenthsec, plain}`). Default-exclude unless provenance confirms a single AUV survey. Do not pair until ruled on.
- `MGDS:30272` (server-side download error), `MGDS:20836`, `MGDS:24425` (both are **PDFs**, not grids) — **dropped.** Closed.
- **Discovery-engine filter gap:** PDF-format entries reached the HR candidate list. Flag for the next discovery harvest so `format ∈ {PDF,…}` is rejected up front. Not urgent.
- **Tier provisionality:** the 41 train/eval HR whose LR is raw were tiered on a ratio that **cannot be final** until their LR is gridded. Their tiers are provisional — finalize after gridding (§5-E/F).
- **Sentry confirmed present** in the corpus — the earlier worry that a literal "AUV" string match dropped Sentry/ABE/REMUS did not bite.

---

## 5. Phase 2 roadmap (in order; human gates marked ⛔)

**Stage A — raw-LR dry-run (START HERE; non-destructive).**
NCEI MBBDB byte-size lookups for the 76 raw cruise files. Produce a precise total-GB figure and a per-cruise size table. No fetching. This is the number that has been deferred since Gate A ("50–500 GB plausible") — now measure it.

**⛔ Gate 1 — Steve confirms two things before any raw fetch:**
1. **Storage:** the measured raw total fits the scratch budget under `$DATA_ROOT`.
2. **Retention policy** (this sets the steady-state footprint): **purge** raw `.all`/`.gsf` after gridding + QC, or **keep** them. Present both with the dry-run number; do not pick.

**Stage B — raw-LR fetch.** After Gate 1, fetch the 76 raw cruises to `$DATA_ROOT`. Idempotent, append-only, byte-verified against the dry-run table.

**Stage C — MB-System gridding (the novel, failure-prone step — go carefully).**
Grid each raw cruise per-cruise (never a cross-source mosaic) with MB-System (`mbdatalist` → `mbprocess` → `mbgrid`). For each pair: confirm the cruise is the **independent ship survey** for that HR (re-verify independence, don't assume), grid to a cell size appropriate to sonar + water depth, and record the gridded LR's true native resolution from **sounding density**, not the output cell size. Estimate the expected resolution first from NCEI sonar metadata + depth (beam footprint ≈ 2·depth·tan(beamwidth/2)) so a wildly-off grid is caught immediately, then report estimate-vs-measured. Pilot a handful of cruises spanning sonar types/depths and have assessment review before gridding all 76.

**Stage D — ratio finalization + native_res re-derivation.**
With LR gridded, compute final `res_ratio` for each new pair. Re-derive native res for the 10 `ok_finer_verify` HR (sounding density). This produces the first real ratios for the 41 provisional-tier HR.

**Stage E — re-tier on finalized ratios.** Apply the bands (`5–25` train, `25–40` eval, exclude `<5` or `>40`). The 41 provisional HR get real tiers here; some may move or exclude. **Leakage constraint:** pairs sharing an LR survey stay on the same train/eval split side — `NCEI_MBBDB:NR07-1` serves both `MGDS:31813` and `MGDS:31814`; watch for any raw cruise that ends up serving two HR.

**⛔ Gate 2 — assessment + Steve rule on `MGDS:31600`** (provenance check) and on the re-tier results (any newly-excluded or moved pairs).

**Stage F — harmonization + QA.** Per pair: single-warp reproject to per-pair local UTM (**never nearest**; skip if CRS already matches), clip to HR∩LR, fresh co-registration, then the v1.1 §A QA (offset-magnitude flag, NCC peak sharpness/PSR, anisotropy/eig_ratio, per-pair hillshade overlay, status `auto_pass`/`needs_review`/`reject`). QGIS visual QC overrides metrics on disagreement.

**Stage G — append + audits.** Append new validated pairs to `manifest/pairs.parquet` (**append-only; dedup against the existing 21 and against the 10 seed sites**). Run completeness + provenance + independence audits. Report.

---

## 6. Key technical facts

- **HR (AUV) sources:** MGDS (FileServer + ISO19115 + FileDownloadServer — note the *corrected* endpoint; a constant-size error body from a reachable host is the move-pattern, read the body before assuming an outage), PANGAEA (AUV ABYSS), USGS ScienceBase/CMGDS (Cal DIG), SEANOE (IFREMER).
- **LR (ship) sources:** **NCEI MBBDB** (ArcGIS REST footprint layer for spatial query + Geoportal ISO per cruise; **mostly raw → grid with MB-System**), PANGAEA ship EM122 (DISCOL/CCZ/TAG companions). **Per-cruise, never composites.**
- **Processing tools:** MB-System (raw MBES → gridded LR), GMT (`.grd` with metadata-first CRS lookup + mandatory bbox verification; `.grd` lacking embedded CRS is *recoverable*, never blind-assumed EPSG:4326), QGIS (visual QA), GDAL.
- **HR target resolution convention:** the Seabed 2030 depth-dependent table (≈100 m at 0–1500 m depth, scaling to ~800 m at 5750–11000 m) is the physically-grounded reference for what resolution is meaningful at depth.
- **SWOT floor:** ~8 km deep-ocean gravity resolution is a hard physical floor; below it, output is hallucination, not super-resolution. Not a gridding concern, but context for why independent measured LR matters.
- **Leakage control:** each pair gets a `geo_cluster` so splits keep whole clusters on one side. **Watch:** `cluster_000` already holds ~9 of the training HR — a concentration to flag at split-design time; the 50 km radius may bundle distinct features.

---

## 7. Dead ends / set aside (don't re-open)

- **Marmara (IFREMER AsterX):** no open LR; excluded from automated runs.
- **Cascadia composite LR:** never use the USGS southern-Cascadia composite as LR — it ingested MBARI data (independence violation). Per-cruise NOAA/Nautilus only.
- **Ground-truth acceptance check:** dropped (false negatives). Validation is human review of proposed pairs via the confirm-before-download gate.

---

## 8. Start here

1. Read `staging_state_20260605.json` and reconcile the §4 counts (clean 81; the new-71; the ~8 processed-LR pairs; the 76 raw cruises; the open items).
2. Run **Stage A (raw-LR dry-run)** — non-destructive byte lookups → precise GB + per-cruise table.
3. Report to assessment and **stop at Gate 1** for Steve's storage + retention confirmation before any raw fetch.

Detailed per-stage directives will accompany each milestone. When in doubt, escalate rather than absorb.
