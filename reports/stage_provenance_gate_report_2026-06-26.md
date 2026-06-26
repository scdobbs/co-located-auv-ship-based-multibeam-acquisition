# Provenance gate (G-PROV + G-PROV-LITE) + append-readiness report

**Date:** 2026-06-26 · **Directive:** `reports/directive_phase2_provenance_gate_v2.md`
**Status:** ✅ Both gates cleared (nothing excluded). ⛔ **Canonical manifest append HELD for Steve's final approval** (HOLD item 2) — the gates surfaced a provenance/terrain finding that changes *what gets written*, so the one irreversible step waits behind it. Staged manifest built (37 rows); canonical `pairs.parquet` untouched + backed up.

**Code:** `src/discovery/stage_provenance_gate.py` · **Evidence:** `reports/discovery/stage_provenance_gate.json` · **Staged:** `reports/discovery/staged_manifest_append.{csv,parquet}` · **Backup:** `manifest/pairs.parquet.bak_preappend`. All certified against the cached MGDS catalog records (DOI/title/`general_type`/cruise/gf/platform).

---

## 0. The key provenance fact (resolves the "mislabel" question)

The pair id is **`<LR_ship_cruise>__MGDS_<HR_AUV_uid>`**. Verified from the data: every pair's `cruise` label has a matching `raw_lr/<cruise>/` (NCEI **ship** multibeam raw) and `raw_lr_gridded/<cruise>__*.grd` — so **the corpus `cruise` column is the LR ship cruise (the pairing seed), not the HR AUV's cruise.** The HR AUV's true identity lives in the MGDS catalog and, for independent pairs, *legitimately differs*.

So the `KIWI10RR×24499` "mislabel" I flagged in C1 is the general rule, not an anomaly: the label names the **ship** cruise; the AUV identity is separate. Two valid relations result:
- **same_expedition** (LR cruise == HR AUV cruise): one cruise carried both the hull multibeam (LR) and the AUV (HR) — the DISCOL/Cal-DIG co-located design. Independent *measurements* (hull EM-class ~30–50 m vs near-bottom AUV ~1–2 m), real ship LR, no composite.
- **cross_cruise** (LR cruise ≠ HR AUV cruise): a ship cruise's multibeam paired with a *different* expedition's AUV grid over the same seafloor — fully separate acquisitions (even more independent). Co-location is proven by the existence of `joint_valid` tiles (same UTM grid, both sides real).

**Anti-circularity holds in both:** LR is always NCEI per-cruise *raw* ship multibeam (established Stage A/B), never a GEBCO/GMRT composite, so it cannot ingest the AUV.

---

## G-PROV — `KIWI10RR×24499`: **CLEARS, advances with corrected provenance**

| evidence | value |
|---|---|
| HR uid 24499 catalog record | cruise **FK171110**, region **Tonga**, platform **R/V Falkor**, AUV **Sentry**, `general_type=Grid`, DOI **10.1594/IEDA/324499** |
| LR (corpus `KIWI10RR`) raw | `raw_lr/KIWI10RR/sb2100_vf.19980324-*.mb41` — **SeaBeam 2100, 1998** ship multibeam (a Melville-class "KIWI" SW-Pacific/Kermadec leg) |
| relation | **cross_cruise** — LR (1998 SeaBeam) ≠ HR (2017 Falkor/Sentry); different vessel, decade, sonar |
| co-location | **3 `joint_valid` tiles** on the shared UTM grid → genuinely the same Kermadec–Tonga seafloor |
| circularity | none — LR is NCEI raw, not a product ingesting the AUV |
| leakage_unit | 8 (unchanged; the pair is the only occupant; the true Tonga identity stays put) |

**Verdict:** independence verified against the *true* identity (FK171110/Tonga), not the label. **Advances** with corrected provenance recorded (`cruise_id=FK171110`, `notes` carry both ship and AUV cruises). This is *correct-and-keep*, not relabel-and-keep — the keep is justified by the independence evidence, not by hiding the mismatch.

**Adjacency (`TN299×27339`, free):** HR uid 27339 = **NorthGorda_MBARI**, region **Gorda**, MBARI Mapping AUV. Its label `TN299` is the LR ship cruise; cross_cruise, independent, 226 tiles. Identity clean (Gorda Ridge AUV). The lu-27 cluster it shares is now only itself among approved pairs (the SKQ/Cascadia-Pythia pairs that crowded lu 27 were declined by Steve).

---

## G-PROV-LITE — 9 advancing pairs: all independent (label = LR ship cruise)

| pair (LR ship) | HR AUV cruise / region (catalog) | relation | tiles | corpus terrain → catalog suggests |
|---|---|---|---:|---|
| AT37-13×31199 | AT37-13 / Costa Rica Rift (Atlantis) | same_exp | 47 | margin (ok) |
| AT42-03×32007 | AT42-03 / Central America (Atlantis) | same_exp | 59 | margin (ok) |
| EW9801×31425 | **TN293 / Loihi** (Thompson) | cross | 36 | margin → **volcanic** |
| NA080×31290 | **OctopusGarden_MBARI / Davidson Seamount** | cross | 814 | seamount (ok) |
| NA090×31212 | **RR2107** / (gf not provided; Revelle) | cross | 47 | margin (keep) |
| RR1506×29779 | RR1506 / Kermadec Arc (Revelle) | same_exp | 649 | margin → **seamount/arc** |
| TN268×30466 | **AxialSeamount_MBARI / JdF Axial** | cross | 825 | vent (≈volcanic, ok) |
| TN399×30373 | **EPR:9N (Parnell-Turner) / EPR 9°N** (Sentry) | cross | 1583 | margin → **volcanic (MOR axis)** |
| FK181031×24367 | **AlarconRise_MBARI / Alarcón Rise** | cross | 5 | margin → **volcanic (spreading)** |

All 9 are independent (real ship LR vs AUV; co-located by tiles). **No label requires exclusion.** Two findings to record:
1. **`cruise_id` in the manifest should be the HR AUV cruise** (done in the staged rows), with the LR ship cruise in `notes` — otherwise provenance reads backwards.
2. **Several "continental_margin" pairs are actually volcanic / MOR / seamount** (EW9801=Loihi, TN399=EPR 9N, FK181031=Alarcón, TN268=Axial, RR1506=Kermadec, and among the approved: KN210-05=MAR, TN299=Gorda). This is a **positive correction to the corpus's known 74%-margin diversity gap** — the validation set is more morphologically diverse than the labels implied. Terrain reclassification is **proposed** in the staged manifest, flagged for your confirmation (not silently committed to canonical).

---

## Append readiness

Gates clear the full set the directive named: **9 advancing + 6 unencumbered approved + `KIWI10RR×24499` (G-PROV cleared) = 16 new rows → 37 total.**

Staged result `staged_manifest_append.csv` (21 canonical preserved verbatim + 16 new, deduped on `pair_id`, no spatial dups; the 6 orphan `cal_dig` sub-dirs are not among the new pairs). **`manifest/pairs.parquet` and OAK were NOT written; a backup `pairs.parquet.bak_preappend` exists for reversibility.**

**Why I held the canonical write** (rather than auto-appending on gate-pass): the gates surfaced (a) the cruise-semantics correction and (b) the terrain reclassifications, both of which change manifest *content* (`cruise_id`, `terrain_class`). The append is the one irreversible step and HOLD item 2 reserves final approval. The staged file shows exactly what would be written.

---

## HOLD — for Steve (one decision unblocks the append)
1. **Approve the staged 37-row manifest** (or adjust): in particular (i) `cruise_id = HR AUV cruise` with LR ship cruise in notes, and (ii) the proposed terrain reclassifications (EW9801→volcanic, TN399→volcanic, FK181031→volcanic, RR1506→seamount, KN210-05→vent, TN299→volcanic). On your go I write `pairs.parquet` (append-only) + sync OAK + byte/dedup verify.
2. The Amundsen/Axial re-harvest pairs (C1) append later as separate candidates — not blocking this 37.

## Deliverables
1. G-PROV (KIWI10RR + TN299 adjacency) with catalog + LR-raw evidence. ✅
2. G-PROV-LITE 9-row label-vs-record table (all independent; LR-cruise semantics + terrain corrections). ✅
3. Staged 37-row manifest + canonical backup; **canonical untouched**. ✅
4. This report + `stage_provenance_gate.json`.

**Skepticism note:** every "independent" verdict is anchored to the MGDS catalog record (shown) and the NCEI raw LR provenance (shown for KIWI10RR), plus the joint-tile co-location proof — not to an internal table. The append waits behind your approval of the *corrected* manifest, because the gates changed what the correct manifest says.
