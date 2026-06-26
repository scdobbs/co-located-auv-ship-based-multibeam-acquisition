# M1.6 — Cal DIG HR remediation (v1.2 addendum) — 2026-06-03

Implements Acquisition Directive v1.2 (user-provided HR for Cal DIG only). 
DISCOL untouched. Cal DIG LR (`10.5066/P9QQZ27U`) untouched. Tier 2 still blocked.

## Status

- §B inventory: **done** → `user_hr_inventory_20260603.md` (28 files, all EPSG:32610 / WGS84 UTM 10N)
- §C proposed mapping: **done** → `user_hr_match_20260603.md` + `user_hr_proposed_mapping.yaml`
- §C human approval: **pending — awaiting `user_hr_approved_mapping.yaml`**
- §D re-harmonization: blocked until §C approval

## QC artefacts

- Per-file hillshade + FFT PNGs under `reports/user_hr_qc/` (28×2 = 56 PNGs).
- Per-file `<name>.provenance.json` sidecars next to the source files in `/scratch/groups/hilley/auv_ship_colocated_bathy/user-provided-cal-dig/`. Field `attested_artifact_free` is `null` until the human attests.

## §E provenance + audit

- Manifest schema (already extended): `hr_source_type`, `hr_local_path`, `hr_superseded_doi`, `hr_superseded_reason`.
- `src.audit.audit_row` now branches: for rows with `hr_source_type=='user_provided'` it requires the local file to exist, a `<file>.provenance.json` sidecar with `attested_artifact_free: true`, and the superseded-DOI provenance trail. The DOI-match check still applies to the LR side and to all DISCOL/PANGAEA rows.
- `python -m src.cli audit` runs the branched audit.

## Workflow from here

1. Review the §B PNGs (hillshade + FFT). For each file, edit its `*.provenance.json` and set `attested_artifact_free: true` (or `false`).
2. Review the proposed mapping in `user_hr_proposed_mapping.yaml`. Edit values to override any wrong matches (set value to `null` to reject; substitute a different `user_file` path to override). Rename to `user_hr_approved_mapping.yaml` when ready.
3. Run `python -m src.cli reharmonize-user-hr`. This:
   - re-projects user HR from EPSG:32610 → EPSG:26910 with the configured `resample_kernel` (`bilinear`). Reprojection is NOT skipped — all user files are WGS84 UTM 10N, the target is NAD83 UTM 10N, and the datum shift is real.
   - re-clips to the new HR∩LR overlap;
   - **re-solves co-registration from scratch** (no CMGDS dx/dy/dz reuse);
   - regenerates the v1.1 §A QA + overlay PNG;
   - updates the manifest row with the new fields.
4. Review the new overlay PNGs. Clear each sub-pair manually (`coreg_status` transitions from `needs_review` only via explicit human review of the new overlay; v1.1 thresholds are still uncalibrated).
5. `python -m src.cli audit` should pass with all 17 Cal DIG rows now branching on user_provided HR.

## Gate

- **Pause #1 (this report):** human attestation of §B artifact-free status; approval of §C mapping. No re-harmonization until both happen.
- **Pause #2 (after §D):** human clearance of the new overlay PNGs per sub-pair.
- Tier 2 remains blocked.
