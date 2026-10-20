# DIRECTIVE R20 / ACQ-R15 (both repos): documentation and release preparation for the GRL revision

**Date:** 2026-10-20
**Applies to:** the CNN repo (as R20) and the acquisition repo `co-located-auv-ship-based-multibeam-acquisition` (as ACQ-R15). Each executor does its own repo only.
**Report to:** `.../R20/REPORT_R20_<date>.md` (CNN repo) or `reports_post_grl_review/ACQ-R15/REPORT_ACQ-R15_<date>.md` (acquisition repo).
**Report length:** at most 8 bullets.

## 0. Purpose and rulings

Bring the repo up to date so it can be archived on Zenodo as the code record for the revised paper:

> Dobbs, S. C. "Ship Multibeam Roughness Ranks Unresolved Seafloor Relief at Unseen Sites: A Pre-Registered Blind Test." GRL 2026GL125574 (in revision).

The processed data are on Zenodo at **10.5281/zenodo.23515276** (CC BY-NC-SA 4.0).

**Steve's rulings (2026-10-20):**
1. **Documentation and release preparation only.** Change no computation, frozen script, threshold or result.
2. **Do not push** and do not create a GitHub release. Steve pushes and archives to Zenodo himself.
3. **Commit by explicit path**, never `git add -A`.
4. Use American English.
5. **Do not delete history.** Superseded material is marked or moved, not erased.

## 1. README.md (rewrite)

The README must cover, in this order, in plain language:
1. **What this repo is**, in two or three sentences, and how it relates to the paper and to the other repo (one links the other).
2. **The paper's question and headline result**, in a short paragraph: ship-grid roughness ranks unresolved fine-band relief within unseen sites (development ρ ≈ 0.4). It was confirmed by pre-registered blind test 2 (pooled ρ 0.43, 95% CI 0.28–0.53), and blind test 1 outside the development range was not confirmed.
3. **Data:** the Zenodo record 10.5281/zenodo.23515276 and what it holds. Raw swath is not redistributed; it comes from NCEI, MGDS, PANGAEA and USGS.
4. **Quick start:**
   - environment setup;
   - reproducing one pair's score from the Zenodo package (`load_pair.py`);
   - (CNN repo) rescoring the development table and both blind tests from the packaged tile tables.
5. **Pipeline map.** A table of stage, entry script, inputs, outputs and the directive that produced it, for this repo's stages only:
   - acquisition repo: discovery, fetch, gridding (MB-System), harmonize, co-register (including the ACQ-R13 quadrant test), datum check, k sweep, ship products, eligibility, data package;
   - CNN repo: targets and tiles, evaluation (eval_v1.1), GBT_ship, CNNs (V1, V2, P-V1, pretraining), Phase 4 and Phase 5 scripts.
6. **Frozen versions:** a table of every tag that governs a reported result, with what it froze. Include `phase0-freeze`, both pre-registration tags, and the Phase 4 and Phase 5 freeze tags up to `phase5-acq-freeze-v4.2`.
7. **Pre-registrations and deviations:** where they are in the repo, with a one-line pointer to every deviation note.
8. **What is superseded:** the submitted heteroscedastic CNN (`het_production_v1`), its σ product, and the synthetic-LR regime. Say plainly that they are kept for the record and do not support the revised paper's claims.
9. **Hardware and runtime:** what ran on CPU or GPU, and approximate run times.
10. **Citation and license:** cite the paper, the data record and this code record.

## 2. Other files

1. **Stale guidance:** `CLAUDE.md`, `METHOD.md` and any other file describing the abandoned synthetic-LR regime or the old σ product. Add a dated banner at the top ("Superseded 2026-10; see README") or move the file to `docs/legacy/`, whichever leaves fewer broken links.
2. **Environment:** pinned `environment.yml` or `requirements.txt` matching what produced the results. Record the MB-System version and container digest (acquisition repo) and the CUDA and PyTorch versions (CNN repo).
3. **`CITATION.cff`:** author S. C. Dobbs; title, version and date; preferred citation = the paper; references = the data DOI and the other code record.
4. **`.zenodo.json`:**
   - title, description (at most 200 words), keywords, creator, license and version;
   - related identifiers: data `10.5281/zenodo.23515276` (isSupplementedBy), and the other code record (`10.5281/zenodo.21300922` or `10.5281/zenodo.21300925`, isRelatedTo).
   - No paper identifier yet.
5. **`LICENSE`:** keep the existing code license if there is one, and report which it is. If there is none, add MIT and say so in the report.
6. **`.gitignore`:** must exclude tokens, local data, checkpoints, logs and scratch outputs.

## 3. Checks

1. **Secrets:** search the working tree and the full git history for tokens, keys and passwords (Zenodo, GitHub, NCEI, AWS, `Bearer`, `token=`, `.zenodo_token`). Report hits by file and commit only, never the value. Any hit in history is a stop: report it and wait. Do not rewrite history yourself.
2. **Size:** list any tracked file over 50 MB and any Git LFS objects. Do not remove them; report them.
3. **Uncommitted work:** list every uncommitted or untracked file in three groups:
   - (a) needed to reproduce a reported result: commit by explicit path;
   - (b) scratch: add to `.gitignore`;
   - (c) unsure: leave alone and list.
4. **Links:** every path and script named in the README exists, and every command in the quick start runs (one pair only, minutes).
5. **Paths:** no absolute personal paths in the README or docs. Inside code, leave them, but list the ones a user would need to change.

## 4. Release preparation

1. Commit the documentation by explicit path.
2. Create an annotated tag, not pushed: `grl-revision-v2.0` (CNN repo) or `acq-grl-revision-v2.0` (acquisition repo), with the message "Code for the GRL revision of 2026GL125574; data at 10.5281/zenodo.23515276".
3. Write the exact commands Steve should run to push the branch and the tag.

## 5. Report

1. The files changed or added.
2. The secrets result and the size result.
3. The uncommitted-file groups: what was committed, what was ignored, and what is left for Steve.
4. The quick-start result.
5. The license.
6. The commit sha, the tag, and the push commands for Steve.
7. The `.zenodo.json` description text.

## 6. Out of scope

- Any change to computations, frozen scripts or results.
- Pushing, creating GitHub releases, or publishing on Zenodo.
- Rewriting git history.
