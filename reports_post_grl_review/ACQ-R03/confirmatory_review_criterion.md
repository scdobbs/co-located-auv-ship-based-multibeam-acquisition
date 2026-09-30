# ACQ-R03 §5.1 — Confirmatory co-registration review criterion (committed before any package is rendered)

**Pairs under review:** KN182L03__MGDS_30193 (nu01a, rigid shift 48.1 m) and SUM1004__MGDS_33090 (nu03, 46.7 m),
both dropped in ACQ-R02 under the 30 m USBL bound (HOLD H3). Steve decides by QGIS review under the seal.

## 1. The records (extracted by `src/acq_r03/confirmatory_criterion.py` → `confirmatory_review_criterion_records.json`)

Existing corpus pairs accepted with a co-registration offset > 30 m and a recorded QGIS basis (`manifest/pairs_v2.parquet`):

| pair | unit | offset m | recorded `coreg_status` | recorded rationale (notes / June report) |
|---|---|---|---|---|
| NA076__MGDS_32317 | lu11 | 47.01 | `masked_coreg; offset=47.01m; MAD=0.77m; QGIS_signed_off_2026-06-26; offset>30m_USBL_QGIS_basis` | notes: "NOTE offset>USBL, QGIS-signed"; `stage_c1_reharvest_step2_harmonization_2026-06-26.md` l.18: "offset > 30 m USBL → **QGIS arbitrate** (MAD 0.8 m is excellent; same ~47–53 m offset the original NA076 pair showed)"; l.20: "Santa Monica's 47 m solved offset is the one judgment call (a real USBL error vs a soft lock — the overlay is the arbiter, exactly as for the corpus's borderline pairs)" |
| EW0207__MGDS_32556 | lu16 | 50.85 | `masked_coreg offset=50.85m MAD=9.27m; QGIS_signed_off_2026-06-26; offset>30m_USBL_QGIS_basis` | `stage_c1_phase1_report_2026-06-26.md` (P1.2 NRift): signed off with the C1 batch on the QC figure `c1_candidate__EW0207__MGDS_32556_NRift.png` |
| 2009_Amundsen__MGDS_30046 | lu18 | 35.43 | `masked_coreg offset=35.43m MAD=0.73m; QGIS_signed_off_2026-06-26; offset>30m_USBL_QGIS_basis` | `stage_c1_phase1_report_2026-06-26.md` l.28: "Offset just over the 30 m USBL bound (like Santa Monica) → **QGIS read** — MAD 0.73 m is excellent" |
| AR26__MGDS_31838 | lu14 | 32.59 | `QGIS_R3_approved; PSR=3.42; offset=32.59m` | R3 re-audit QC figure `qc_plots/reaudit_real23/real_nonadvancing_qgis__AR26__MGDS_31838.png` |
| TN159__MGDS_21981 | lu17 (lockbox) | 44.79 | `QGIS_R3_approved; PSR=5.2; offset=44.79m` | R3 re-audit QC figure (lockbox pair; record only) |

The `offset>30m_USBL_QGIS_basis` tag was attached by code (`src/discovery/stage_c1_append.py` l.104,
`stage_c1_phase1_execute.py` l.130) to every C1 pair whose masked co-registration exceeded 30 m, after Steve's
per-item QGIS sign-off of 2026-06-26. The nine Cal DIG pairs above 30 m carry `needs_review`, not this basis.

What the June records say the reviewer judged:
- `stage_f_harmonization_2026-06-23.md` §3b (l.52): "a large solved offset may be a real USBL error correction or a
  bad lock. **QGIS arbitrates**"; §5 (l.71): "Scrutinize the large-offset/negative-PSR pairs — **confirm real
  alignment vs bad lock**."
- `stage_f5_valid_masks_2026-06-23.md` l.142: "a solved shift beyond the AUV USBL bound: either a real large USBL
  error or a bad lock; **QGIS arbitrates**"; l.180: "QGIS-arbitrate large-offset vs bad-lock via the `_overlay_f5`"
  (l.145: the overlay = "NCC heat-map + hillshade").
- Supporting numbers cited alongside the sign-offs: the post-shift residual MAD ("excellent") and the NCC peak
  sharpness (PSR). **These are excluded under the confirmatory seal** (no residual statistic); the criterion below
  uses only what §5.2 allows.

## 2. Criterion (Steve's June criterion, restated for the sealed review)

**Reinstate** the pair if, in QGIS, the rigid shift turns a visibly misaligned overlay into an aligned one: after the
shift the HR hillshade and HR contours coincide with the LR hillshade and LR contours (scarps, ridge crests,
contour lines fall on the same features, to within the LR cell), whereas before the shift they are displaced by
about the shift vector; and the co-registration search surface has one well-defined minimum at the recorded
vector rather than a ridge or plateau. That is the "real USBL-scale navigation error, corrected by the shift"
case under which NA076 (47 m), EW0207 (51 m) and 2009_Amundsen (35 m) were accepted.

**Drop** the pair if the shift does not produce visible alignment, the before/after overlays are equally (mis)aligned,
or the search surface is ambiguous (several minima, a ridge, or a minimum at the search edge). That is the "bad
lock" case.

No amplitude, residual, spectral or roughness quantity enters the decision. The package (§5.2) holds only the
before/after hillshades, matched contours, the shift vector, the search surface and the navigation basis if recorded.
