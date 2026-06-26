# Phase 2 — Stage B recovery + MB-System setup report

**Date:** 2026-06-23 (campaign dated 2026-06-22) · **Author:** Claude Code execution instance (Sherlock)
**Directive:** `reports/directive_phase2_stage_b_recovery_mbsystem.md`
**Status:** ⛔ **HOLD for assessment** before the Stage C pilot. No gridding, no manifest/OAK writes.

**Artifacts**
- `reports/discovery/stage_b_fetch_log.csv` (updated) + `stage_b_failed_files_detail.csv`
- `reports/discovery/stage_b_recovery_2026-06-22.json`; `staging_state` updated
- MB-System container: `/home/groups/hilley/containers/mbsystem_sandbox` (Apptainer)
- Code: `src/discovery/stage_b_recovery.py`; sbatch `stage_r_recovery`, `stage_m_apptainer`

---

## 1. Headline

| | |
|---|---|
| **Swath (bathymetry) data** | **38 / 38 fetched cruises complete — 0 soundings missing** |
| The 106 "failed" files | **all empty (0-byte) `.fnv` nav sidecars** — benign, MB-System regenerates them |
| AR26 `9999` "size_mismatch" | **transient bad HEAD** (NCEI returned 1275 B for an 11 MB file) — restored + verified |
| Watch cruises (TN299/TN399/NA080) | overlap **swath 100 % present** — **not** exclude candidates |
| **MB-System** | **installed + verified** (Apptainer; reads real soundings) |
| Stage C readiness | **38 swath-complete cruises + MB-System verified = ready for pilot** |

The 22 `incomplete_for_grid` from the Stage-B report were a false alarm: the one-failed-file-flips-the-cruise rule fired on empty nav sidecars, not on missing data. **Every swath file is present and integrity-verified.**

---

## 2. Track R — fetch recovery

### R0 — AR26 (resolved; it was never bad data)
The Stage-B `size_mismatch_existing` on `AR26/9999.all.mb58.gz` was a **transient NCEI HEAD glitch**: the original run's HEAD returned `Content-Length: 1275` for a file that is actually a valid 11,138,466-byte gzip. On re-probe the HEAD returns the correct `11138466` and the body passes `gzip -t`. The file is restored from its real path (`…/neil_armstrong/AR26/…/em710/9999.all.mb58.gz` — AR26 is RV *Neil Armstrong*/EM710) and verified. AR26 is swath-complete (10/10).

### R1 / R2 — the 106 "failures" are empty nav sidecars, not data loss
The HTTP-status instrumentation (added this pass — the original run only logged a count) shows **all 106 still-failing files are `.fnv`, all `http_status=200`, `attempts=1`, plan-advertised size `0`**. They are the empty/zero-byte nav fragments: NCEI serves them `200 OK` **with no `Content-Length` header**, so the byte-exact fetcher cannot size them and flags `failed`.

- **Verdict — neither transient nor systematic, but a third category:** *empty-sidecar non-failures*. Not network noise (200, single attempt), not a moved/404 path. `stage_b_failed_files_detail.csv` records each (`cruise, filename, http_status=200, attempts=1`).
- **Impact: none.** `.fnv` is a derived fast-nav sidecar; the navigation is embedded in the swath file, and MB-System regenerates `.fnv` during `mbprocess`/`mbdatalist`. **Zero swath files failed** (9,345 `skip_present` + 1 `fetched` + AR26 restored = 9,347/9,347).

### R3 — corrected cruise status
Re-derived on **swath only**: **38 / 38 fetched cruises are gridding-ready.** Watch cruises — overlap swath fully recovered, so **not** exclude candidates on coverage-recovery grounds (their thin-overlap *quality* check stays a Stage-C item per A.6):

| Watch cruise | overlap swath files | recovered |
|---|---|---|
| TN299 | 12 | 12 (100 %) |
| TN399 | 10 | 10 (100 %) |
| NA080 | 51 | 51 (100 %) |

### R4 — legacy-7 HR-dependency (findings for assessment)
Each of the 7 `needs_format_review` cruises serves HR that depend **solely** on it — excluding all 7 drops **8 HR**:

| Legacy cruise | live HR (sole-dependent) |
|---|---|
| AII8L11 | MGDS:31430 |
| EW9914 | MGDS:7833 |
| RC2901 | MGDS:31860 |
| PASC04WT | MGDS:31824 |
| PASC02WT | MGDS:31059 |
| RP11SU81 | MGDS:30467, MGDS:27340 — **`.gps` only, no soundings → hard exclude** |
| TUNE04WT | MGDS:31427 |

Assessment recommendation carried (for confirmation, not executed): exclude all 7 — 1980s wide-beam SeaBeam-classic vs 1–2 m AUV HR lands >40× and eval-excludes at the ratio gate anyway. **Net effect to confirm: 8 HR drop** (71 → 63 if all 7 excluded). No HR is recoverable by chasing date-named format parsing without also accepting a >40× pair.

---

## 3. Track M — MB-System setup

- **M0:** confirmed absent (`module spider mb-system` → none; not on PATH).
- **M1 — conda-forge has NO MB-System package.** Authoritative: *"there currently are no packaged distributions of MB-System"* (MB-System BuildAndInstall.md). `micromamba/conda search -c conda-forge mbsystem` → *no entries*. So the directive's `conda install -c conda-forge mbsystem` cannot work — this is the M3 escalation, but the cause is **no package**, not a GMT/PROJ dependency conflict.
- **Pivot — official `mbari/mbsystem` Docker image via Apptainer** (Singularity is `/usr/bin/apptainer` 1.5.1, no module needed). `apptainer pull` (SIF) failed with `mksquashfs … exit status 139` even after pointing `APPTAINER_TMPDIR` at `$L_SCRATCH`; the **`--sandbox` build** (extracted dir, no squashfs) succeeded.
- **M2 — verified it reads real soundings**, not just that the binary exists:
  ```
  mbinfo -F94 on KN210-05/sb20130615183556.xse.mb94 →
    MBIO Data Format ID: 94 | Records: 9 | Good Beams: 1055 (77.6%)
    Lon -61.18..-60.96 | Depth 4882.98..5383.64 m
  ```
- **Working invocation (for the Stage C directive):**
  ```
  apptainer exec --bind /scratch,/home/groups,/oak \
    /home/groups/hilley/containers/mbsystem_sandbox mbinfo -F<fmt> -I <file>
  ```
  Note: it's a **sandbox directory**, not a `.sif` (mksquashfs segfaults on this host). Persistent on `$GROUP_HOME`; reusable for Stage C `mbdatalist`/`mbprocess`/`mbgrid`.

---

## 4. Stage C readiness + hold

**Ready for the Stage C pilot:** 38 swath-complete cruises on `$DATA_ROOT/raw_lr/` + MB-System verified working. **HOLD for assessment** on:
- **(a) Systematic path issues — none.** All 38 cruises resolved; the only "failures" are empty `.fnv` (regenerable) and the AR26 transient HEAD (resolved). Nothing needs path re-resolution.
- **(b) Watch-cruise calls** — TN299/TN399/NA080 have full overlap swath; the outer-beam coverage-*quality* check is deferred to the Stage-C pilot (they're included as pilot watch cases), not an exclude now.
- **(c) Legacy-7 confirmation** — confirm excluding the 7 (and the resulting 8-HR drop); RP11SU81 is a hard exclude regardless (no soundings).

Per the directive, the Stage C pilot (next directive) should deliberately include **one Amundsen subset** (novel Arctic case) and **one watch cruise** so the pilot exercises the failure-prone cases before any full gridding run.

---

## 5. Deliverables
1. updated `stage_b_fetch_log.csv` + `stage_b_failed_files_detail.csv` (106 empty-`.fnv`, HTTP 200)
2. this report + `stage_b_recovery_2026-06-22.json`
3. MB-System Apptainer sandbox + verified invocation (§3)
4. updated `staging_state` (swath-complete = 38/38; recovery interpretation)

## 6. Out of scope / tracked
Gridding (Stage C pilot — next directive), manifest/OAK writes, executing exclusions. The 6 orphan `cal_dig` sub-dirs remain a tracked pre-Stage-G item.
