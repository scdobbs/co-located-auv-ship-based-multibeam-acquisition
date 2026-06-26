# Directive — Provenance gate + pool sign-offs + append readiness v2

**Date:** 2026-06-26
**From:** Assessment instance · **To:** Claude Code (Sherlock)
**Supersedes:** `directive_phase2_provenance_gate_v1.md` (incorporates Steve's R3 adjudication).
**Status:** ⛔ HOLD manifest append until G-PROV (one pair) + G-PROV-LITE (the 9) clear. Then append the confirmed set. 21 read-only.

---

## 0. Steve's R3 adjudication of the 11 pool pairs (recorded)

**Approved (7):** `KIWI10RR×24499`, `KN210-05×22436`, `KN204-01×31675`, `AR26×31838`, `TN159×21981` (eval), `FK006B×20811`, `TN299×27339`.

**Declined (4):** `TN268×30219`, `SKQ201705S×31254`, `SKQ201705S×31255`, `MGLN06MV×17700` (~900 m offset).

**Two consequences:**
- **Eval set restored to 2:** `TN159×21981` + `NA090×31212`.
- **Declining `SKQ×31254`/`×31255` moots their G-PROV gate** — they were two of the three provenance-gated pairs; they're now excluded by plot adjudication, no further action.

**Of the 7 approved, one is plot-approved but still GATED:**
- `KIWI10RR×24499` is provenance-gated (C1: HR grid 24499 = FK171110/Tonga, not KIWI10RR). **A hillshade cannot show independence**, so Steve's plot sign-off is necessary but not sufficient. It advances **only if G-PROV clears** (below). The other 6 approved pairs are clear and unencumbered.

---

## G-PROV — independence re-verification, now scoped to ONE pair ⛔

Only `KIWI10RR×24499` remains (the two SKQ pairs were declined). Do, anchored to external evidence:
1. **Substantiate the mislabel:** show the MGDS catalog record (DOI, title, `general_type`, acquisition cruise) establishing grid 24499's true AUV acquisition identity (claimed FK171110/Tonga), beside the corpus's `KIWI10RR` label. Show the record; don't assert.
2. **Re-verify independence against the TRUE identity:** confirm the paired LR is a genuinely separate acquisition from the true 24499 AUV survey (not same expedition, not a product ingesting it).
3. **Leakage_unit:** confirm the true identity stays in its existing cluster/leakage unit (the corpus already co-locates KIWI10RR/FK171110 at lu 8); fix if the true site differs.
4. **Outcome:** advances with corrected provenance + confirmed independence, OR excluded for unverifiable independence (anti-circularity — never relabel-and-keep).

**Cheap adjacency add (nearly free):** `TN299×27339` (approved) sits in cluster/leakage unit 27 — the same neighborhood as the SKQ/Cascadia-Pythia mislabel tangle. While pulling the catalog records above, confirm `TN299×27339`'s own cruise identity matches its label. Same lookup, no extra harvest.

---

## G-PROV-LITE — GREENLIT (Steve approved "quick spot check")

DOI/identity spot-check on the **9 advancing pairs**: confirm each corpus cruise label matches its MGDS record. Light confirmation only — the 9 already have independent corroboration (depth-sanity, QGIS, code-path). Flag any mismatch for individual re-verification; do not expand to a full 41-pair re-audit. Report a 9-row label-vs-record table.

---

## Append readiness (the gate to the canonical manifest)

**Confirmed ready to append now (15 new rows → 36 total):**
- 9 advancing + 6 unencumbered approved pool (`KN210-05×22436`, `KN204-01×31675`, `AR26×31838`, `TN159×21981`, `FK006B×20811`, `TN299×27339`).

**Conditional (+1 → 37):** `KIWI10RR×24499`, iff G-PROV clears.

**Append unblocks when:** G-PROV resolves `KIWI10RR×24499` AND G-PROV-LITE returns clean on the 9. Then append the new rows to `manifest/pairs.parquet` (append-only; the 21 are already canonical and untouched), dedup confirmed, sync OAK. The Amundsen/Axial re-harvest pairs append **later** as separate candidates once each passes independence + reader proof — do not block the 36/37 append on the re-harvest.

---

## Unchanged / still in force
- **C1 re-harvest** greenlit, priority Amundsen (31753, 30046) → Axial (32556, 32557, 30218) → rest; skip in-corpus floats; each new float is a *candidate*, not an auto-add. ✅
- C2 byte-level RGB gate + `Image Geo` catalog signal; C3 quarantine/restore of the 8 fake `hr.tif`. ✅
- 21 read-only; per-cruise independence non-negotiable; `hr_preF5repair.tif` retained.

## HOLD — for Steve
1. Confirm you want `KIWI10RR×24499` held to G-PROV (vs overriding on the plot) — my recommendation is hold.
2. Final manifest approval after G-PROV + G-PROV-LITE report back (36, or 37 with KIWI10RR).

**Skepticism note:** G-PROV and G-PROV-LITE both certify against the MGDS catalog records (DOIs/titles/`general_type`) — show the records. The append is the one irreversible step; it waits behind evidence, not behind another internally-consistent table.
