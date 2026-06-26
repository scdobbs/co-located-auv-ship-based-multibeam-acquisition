# Gate 1 — storage setup record (§3 implementation)

**Date:** 2026-06-22 · **Author:** Claude Code execution instance (Sherlock)
**Implements:** `reports/gate1_signoff_20260622.md` §3 (output home + migration of validated work). Read-only against originals.

---

## 1. `$OAK` allocation — confirmed

- **Path:** `$OAK = /oak/stanford/groups/hilley` (group allocation exists, writable).
- **Usage:** 16.1 TB / 20 TB (80 %) → **~3.9 TB free**; inodes 162 K / 3 M (5 %).
- **Headroom note:** 3.9 TB is ample for the validated outputs (small GeoTIFFs/parquet) accumulating through Phase 2, but OAK is at 80 % — worth watching as gridded LR grows. Not a blocker now. Fallback `$GROUP_HOME` (`/home/groups/hilley`, 239 GB/1 TB) was **not** needed.
- **Output root created:** `$OAK/auv_ship_colocated_bathy/`.

## 2. Validated work migrated to OAK (persistent, off the 90-day purge timer)

Copied scratch → OAK with `rsync -a`; integrity verified; originals on `$DATA_ROOT` untouched.

| Item | Source (`$DATA_ROOT`) | OAK destination | Size | Integrity |
|---|---|---|---|---|
| Harmonized products | `harmonized/` | `$OAK/auv_ship_colocated_bathy/harmonized/` | 251 MB / 167 files | byte-total MATCH; sample raster md5 identical |
| Raw provenance (21 pairs) | `raw/` | `$OAK/.../raw/` | 2.27 GB / 108 files | byte-total MATCH |
| Manifest | repo `manifest/pairs.parquet` | `$OAK/.../manifest/pairs.parquet` | 39 KB | md5 identical |

- **Scope note:** the sign-off named *harmonized products + manifest*; I also mirrored `raw/` (2.27 GB) — the immutable source of the untouchable 21 — since it is cheap and makes the 21 fully reproducible off-scratch. `harmonized/cal_dig_morro_bay/` contains 24 sub-dirs (a few beyond the 18 manifest pairs, e.g. superseded `luciachica_2009`, `20180426m1_PockmarkNorthDet`); the whole tree was mirrored rather than cherry-picked, so nothing validated is lost.
- **Protection:** migrated **files** set read-only (`chmod a-w`, now `-r--r--r--`) so the untouchable 21 cannot be overwritten on OAK; **directories left writable** so Stage-F can append new validated pairs to the same OAK tree.
- **Originals:** `$DATA_ROOT/{harmonized,raw}` and the repo manifest are unchanged.

## 3. Stage B precondition

The sign-off (§3/§5) makes Stage B contingent on the storage targets existing. **They now exist and are verified.** Precondition satisfied.

## 4. Open — Stage B directive not yet present

`reports/directive_phase2_stage_b_raw_lr_fetch.md` (referenced by sign-off §4) is **not in the repo yet**. The sign-off gives the spec in outline — fetch the 45-cruise cleaned plan (`stage_b_fetch_list_2026-06-22.csv`, ≈131 GB) idempotently, byte-exact via HEAD, content-integrity verified, to `$DATA_ROOT/raw_lr/`; no gridding, no manifest writes — but defers mechanics to that directive.

**Holding the 131 GB fetch** until the Stage B directive lands (or an explicit instruction to proceed on the §4 outline). Everything upstream of the fetch is done and signed off; this is the only thing between here and Stage B.
