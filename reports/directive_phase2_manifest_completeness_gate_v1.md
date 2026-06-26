# Directive — Manifest completeness gate before canonical append v1

**Date:** 2026-06-26
**From:** Assessment instance · **To:** Claude Code (Sherlock)
**Builds on:** `stage_provenance_gate_report_2026-06-26.md` (gates accepted; provenance reframe accepted).
**Status:** ⛔ **Canonical append HELD — not for approval as staged.** The staged 37-row manifest is not at schema parity; the 16 new rows must reach canonical-row completeness before any write to `pairs.parquet`/OAK. 21 read-only; backup retained.

---

## 0. Accepted (do not redo)

- **Provenance reframe correct:** `cruise` = LR ship cruise; HR AUV identity separate; same_expedition and cross_cruise both independent because LR is raw single-cruise NCEI multibeam (no composite, cannot ingest AUV). Consistent with the original design (NR07-1 serving two HRs; "AUVs over pre-existing ship maps"). ✅
- **G-PROV `KIWI10RR×24499` cleared** on real evidence (SeaBeam 2100 / 1998 LR vs Falkor-Sentry / 2017 HR; cross_cruise; 3 joint tiles). Advances. ✅
- **G-PROV-LITE** 9 advancing independent. ✅
- **Holding the canonical write was correct.** ✅
- **HR uids unique; among the 16 new pairs no shared LR cruise** → no new leakage edges introduced (verified). The only shared-LR group is the canonical `cal_dig_morro_bay` (18, already one leakage unit). ✅

---

## M1 — Bring the 16 new rows to canonical schema parity ⛔ (blocks append)

The 16 `verified_pair_reaudit` rows are blank on fields the 21 canonical rows carry. Populate all, sourced as noted; do not write canonical until every new row matches the 21's completeness:

| field | source | note |
|---|---|---|
| `lr_platform`, `lr_sonar` | NCEI raw-LR header / `mbinfo` per cruise | **Independence evidence — mandatory.** The canonical record must substantiate anti-circularity on its own (e.g. KIWI10RR → SeaBeam 2100, 1998). Already determined in the gate report; write it into the rows. |
| `hr_sonar` | MGDS catalog (Sentry / MBARI Mapping AUV / etc.) | from the same catalog records used in G-PROV |
| `hr_native_res_m` | **sounding density, not grid posting** | per the standing principle (over-posted grids report false-fine cells) |
| `res_ratio` | `lr_native_res_m / hr_native_res_m` | core SR quantity; must be present and consistent with the k-convention |
| `coreg_status` | QA verdict | the 3 no-PSR pairs (`KN210-05×22436`, `KN204-01×31675`, `KIWI10RR×24499`) → record the **QGIS-approval basis** (Steve's plot sign-off is the arbiter), not blank |
| `checksum_hr`, `checksum_lr` | sha256 of the harmonized rasters | **integrity anchor — mandatory** given the corruption history; this is how future drift is caught |
| `footprint_wkt` | HR∩LR valid polygon | spatial provenance |
| `vert_offset_m` | from co-registration | parity with canonical |

Re-emit `staged_manifest_append.csv`; report a completeness diff (every field: 21/21 canonical, 16/16 new) before requesting approval again.

## M2 — Terrain reclassifications: present for Steve's confirmation (do not auto-commit)
7 proposed: `EW9801`→volcanic (Loihi), `TN399`→volcanic (EPR 9°N), `FK181031`→volcanic (Alarcón), `RR1506`→seamount (Kermadec), `TN268`→volcanic (Axial), `TN299`→volcanic (Gorda), `KN210-05`→vent (MAR). Keep them flagged `terrain_class_proposed` until Steve confirms each. Record the catalog region/DOI that justifies each reclass in `notes`. **Implication to surface:** the corpus is more morphologically diverse than the prior "74% continental margin" characterization (which was partly a labeling artifact); this improves the known diversity gap and changes which pairs count as channelized for any future D8-loss scoping.

## M3 — Leakage note for the C1 re-harvest (forward, non-blocking)
When the Amundsen/Axial floats are re-harvested, several will **co-locate with existing manifest pairs** (Axial float vs `TN268×30466`; the render-site sploits). Each re-harvested pair must be assigned to the **same leakage_unit as any existing pair over the same seafloor** before it appends. Flag at re-harvest, not now.

---

## Append unblocks when
M1 completeness diff is clean (16/16 on every canonical field) **and** Steve confirms M2 terrain reclasses. Then write `pairs.parquet` (append-only, 21 untouched), sync OAK, byte/dedup/checksum verify, report. The re-harvest pairs append later as separate candidates (each through independence + reader proof + leakage assignment).

## Frozen / unchanged
21 read-only; `pairs.parquet.bak_preappend` retained; per-cruise raw-LR independence non-negotiable; no OAK write until M1+M2 clear.

**Skepticism note:** the gate report said "append-ready," but the staged rows are blank on independence, ratio, QA, and checksums — the artifact didn't meet the bar the verdict claimed. Same lesson as the +255 and the repair report: verify the artifact, not the summary. The completeness diff (not a prose "done") is the evidence this time.
