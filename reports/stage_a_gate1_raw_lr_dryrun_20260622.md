# Phase 2 — Stage A raw-LR byte dry-run + Gate 1 request

**Date:** 2026-06-22
**Author:** Claude Code execution instance (Sherlock)
**Milestone:** Phase 2 Stage A (non-destructive byte-size measurement). **No bulk data fetched.**
**Status:** ⛔ **STOP at Gate 1.** Awaiting Steve's two confirmations (storage + retention) before any raw fetch.

Artifacts:
- `reports/discovery/stage_a_raw_lr_sizes_2026-06-22.csv` — per-cruise table (sortable).
- `reports/discovery/stage_a_raw_lr_sizes_2026-06-22.json` — full breakdown + extension census.
- Code: `src/discovery/raw_lr_dryrun.py`, `src/discovery/run_stage_a_dryrun.py`.
- Cached NCEI directory listings: `$DATA_ROOT/discovery_cache/ncei_dirlist/` (idempotent re-runs).

---

## 1. Headline

| Quantity | Value |
|---|---|
| Raw-LR references in staging state | 76 |
| **Unique cruises to fetch** | **55** |
| Cruises resolved / failed | 55 / 0 |
| **Fetch estimate (swath data, dedup)** | **≈ 865 GB** |
| Full-mirror (everything incl. ancillary + dup formats) | ≈ 988 GB |
| Total files (full mirror, ≈ inodes) | ≈ 92,600 |

**This is well above the long-deferred "50–500 GB plausible" Gate-A guess** — but the overage is concentrated, see §3.

The figure is the **compressed download footprint** (the `.all.mb*.gz` / `.mbNNN` swath files NCEI actually serves) — exactly what Gate-1 question 1 needs. Uncompressed working size during MB-System gridding is a separate Stage-C / `$L_SCRATCH` concern, not this number.

---

## 2. Method (and why it's trustworthy)

1. The 76 raw-LR *references* in `staging_state_20260605.json` (41 `raw_lr_in_training_eval` + 35 `DEFER_PHASE_2_raw_lr_to_grid`) collapse to **55 unique cruises** — many cruises serve several HR (§4 reconciliation). Each cruise is sized **once**.
2. Each cruise's authoritative data directory is read from its **cached NCEI Geoportal ISO** record (`sys_xml_clob` → `data.ngdc.noaa.gov/.../multibeam/data/versionN/MB/`), never hand-constructed — the ship-name path segment is normalised unpredictably (`thomas_g._thompson`, and the ISO's verbose `noaa_ship_okeanos_explorer_(r337)` 404s where the live tree uses `okeanos_explorer`).
3. The Apache autoindex for each directory is GET-listed (cached to scratch), recursed into subdirectories, and advertised file sizes summed. No file is downloaded.

**Precision:** the autoindex advertises human-rounded sizes ("75M"), ~1 % per-file error. Errors are random/uncorrelated, so per-cruise and grand totals are accurate to well within 1 % — precise to the GB, which is the Gate-1 decision tolerance. (If a byte-exact figure is ever needed, HTTP HEAD per file gives exact `Content-Length`; not warranted for a fits/retain decision.)

**Two numbers, honest bounds.** The real fetch sits between:
- **fetch estimate (865 GB)** — primary swath encoding counted once + nav; *slightly under*-counts 8 tiny legacy-format cruises (see §5).
- **full-mirror (988 GB)** — every file incl. ancillary `.fbt`/`.fnv` and any duplicate vendor+MB-System encodings; *over*-counts.

---

## 3. ⚠️ Escalation — two Arctic cruises are 58 % of the entire budget

| Cruise | Fetch GB | Files | HR served |
|---|---|---|---|
| `2009_Amundsen` | **253.7** | 12,792 | `MGDS:30045` (1 HR) |
| `2010_Amundsen` | **246.8** | 12,088 | `MGDS:30270`, `MGDS:30272`†, `MGDS:31753`, `MGDS:31755` |
| **Subtotal** | **500.5 GB (58 %)** | | |
| **Remaining 53 cruises** | **364.6 GB** | | |

† `MGDS:30272` was **dropped** in Phase 1 (server-side download error) — so `2010_Amundsen` actually backs **3** live HR, not 4.

The CCGS *Amundsen* is a Canadian Arctic icebreaker; these are multi-month, basin-scale survey/transit datasets. `2009_Amundsen` would mean fetching **254 GB to grid an LR for a single AUV patch**. This is exactly the pattern the working principles flag — *"inflated bbox envelopes have repeatedly produced false pairs; true valid-data footprint, not a bounding box."* A 250 GB transit survey whose track merely crosses a small AUV footprint is a prime false-pair suspect.

**Recommendation:** rule on the two Amundsen cruises **before** any fetch (Stage C will need a footprint/independence check on them regardless). Excluding both drops the budget from **865 → 365 GB** — back inside the original "50–500 GB" envelope. I have **not** excluded them; that is an assessment/Steve call (and ties into the Gate-2 footprint review).

Size distribution of the 55: **2** cruises >100 GB, **12** in 10–100 GB, **20** in 1–10 GB, **21** <1 GB.

---

## 4. §4 reconciliation (per handoff "Start here" #1)

Reconciled against `staging_state_20260605.json` (the authoritative inventory):

- **"76 raw cruises" → 76 references = 55 unique cruises.** 15 cruises serve >1 HR (e.g. `TN268`→5 HR, `2010_Amundsen`→4, `TN159`→3). Sizing per unique cruise avoids double-counting fetch bytes.
- **9 truly-processed LR pairs** confirmed (`truly_processed_pairs`) — these have a processed LR already staged and skip gridding (Stage F directly). Note: this is **9 pairs**, not the "~8 processed LR / 9 pairs" framing — `NR07-1` serves both `MGDS:31813` and `31814` (one LR, two pairs), the rest are distinct.
- **Clean HR corpus 81** (61 `ok` + 10 `ok_finer_verify` + 10 `manifest_seed_clean`); the 10 seed-clean are already in the untouchable 21 — dedup on append still applies.
- **Untouchable manifest = 21 rows** confirmed present (DISCOL, 18 Cal DIG, CCZ, TAG).
- Open items from §4 noted: `MGDS:31600` quarantined (Gate-2); `MGDS:30272/20836/24425` dropped (and 30272's effect on `2010_Amundsen` flagged above).

**Multi-HR cruises feed the Stage-E leakage constraint** (pairs sharing an LR survey must stay on the same train/eval split side). The 15 shared-LR cruises are listed in the JSON (`n_hr_served`); flagging now so the split design accounts for them.

Minor: `staging_state` records `$DATA_ROOT` at **89 GB / 2,843 files** at capture, not the "~29.7 GB / ~2,200" in the handoff brief — the brief's figure is stale; not material to Stage A.

---

## 5. Caveats handled (not absorbed silently)

- **Duplicate-format cruises.** Some store the *same* soundings twice (e.g. `Channel`: `.all.gz` 7.0 GB **and** `.mb57.gz` 7.0 GB). The fetch estimate keeps **one** encoding per cruise; the full-mirror counts both. We grid from one — fetch is the right basis.
- **Ancillary `.fbt` = 25.5 GB** across the corpus (MB-System fast-bath tiles), plus `.fnv` 2.2 GB. These are **MB-System-regenerable** from the raw swath — a fetch-lean option can skip them (saves ~123 GB transfer/inodes, the mirror−fetch gap), and a purge policy would delete them post-QC regardless.
- **8 legacy SeaBeam-classic cruises** (1983–1991: `PASC02WT`, `PASC04WT`, `RNDB18WT`, `TUNE04WT`, `EW9914`, `AII8L11`, `RC2901`, `RP11SU81`) use date-named raw formats (`.83feb06`, `.d3NN.gz`, `.rc00`…) the swath classifier doesn't recognise, so they read `fetch=0` while their bytes are in the full-mirror. Total ~0.8 GB — negligible to the headline, and these very old/low-res cruises are likely weak LR companions anyway. Flagged for Stage C rather than chasing 0.8 GB.
- **3 cruises (`EX1101`, `EX1103`, `RB1604`)** 404'd on the ISO-advertised path; recovered by normalising the ship segment (strip `noaa_ship_` / `_(rNNN)`) and selecting the highest `versionN`. EX1101/EX1103 use uncompressed `.mb163` (Kongsberg `.kmall`-era), version2.
- **Completeness:** 55 cruises = 55 resolved + 0 empty + 0 failed. No limbo states.

---

## 6. ⛔ Gate 1 — two confirmations needed before any raw fetch

### Q1 — Storage: does the measured raw total fit the scratch budget?

**Yes, with enormous headroom — capacity is not the constraint.** `$DATA_ROOT` is on `GROUP_SCRATCH` (`/scratch/groups/hilley`), currently **2.8 TB / 100 TB (2 %)**, **1.7 M / 20 M inodes (8 %)**.

| Option | Adds (volume) | Adds (inodes) | Resulting GROUP_SCRATCH |
|---|---|---|---|
| Full mirror (988 GB) | +1.0 % | +92.6 k | ~3.8 TB / 1.8 M inodes |
| Swath-only fetch (865 GB) | +0.9 % | ~+50 k | ~3.7 TB |
| Exclude both Amundsen (365 GB) | +0.4 % | ~+43 k | ~3.2 TB |

All fit trivially. The real question is **scientific worth** (the 500 GB Amundsen question, §3), not disk. Scratch is **purge-subject** (90-day inactivity) — not archival.

### Q2 — Retention: purge or keep raw `.all`/`.gsf` after gridding + QC?

This sets the steady-state footprint. Presenting both, not picking:

- **Purge after gridding + QC** → steady state ≈ the gridded LR GeoTIFFs + harmonized pairs (small). Raw re-fetchable from NCEI if needed. Lowest footprint; safest against the 90-day purge eating value silently.
- **Keep raw** → steady state ≈ 865–988 GB of raw on scratch, itself purge-subject (must be touched/re-written to survive). Re-grids without re-download.
- **Fetch-lean modifier (independent of purge/keep):** fetch swath-only, skip `.fbt`/`.fnv` ancillary (MB-System regenerates them). Saves ~123 GB and ~25 k inodes up front.

### My recommendation (for steering, not a decision)

1. **Rule on the two Amundsen cruises first** (§3) — likely exclude as transit/bbox false-pairs; if so, budget → 365 GB and the question gets much easier.
2. **Fetch swath-only** (skip regenerable ancillary).
3. **Purge raw after gridding + QC**, keeping only gridded LR + harmonized products, since scratch is non-archival anyway.

---

## 7. Next (after Gate 1 sign-off)

Stage B fetch (idempotent, append-only, byte-verified against this table) → Stage C MB-System gridding **pilot** (a handful spanning sonar/depth, assessment review before all 55) → D/E ratio + re-tier → Gate 2 (`MGDS:31600` + re-tier) → F harmonize/QA → G append + audits.

**Holding here for Steve's Q1 + Q2 (and the Amundsen ruling).**
