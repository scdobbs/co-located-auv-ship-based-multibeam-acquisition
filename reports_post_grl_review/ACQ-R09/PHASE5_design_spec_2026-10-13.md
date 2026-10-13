# Phase 5 design spec: a second pre-registered blind test (input to pre-registration v3)

**Date:** 2026-10-13
**Status:** steering spec, ruled by Steve on 2026-10-13. Pre-registration v3 is rendered from v2.1 with exactly
these changes, signed by Steve, and tagged before any candidate data beyond the ACQ-R08b metadata are processed.
**Name:** "Phase 5" keeps its paths, locks, records and outputs separate from Phase 4, which stays closed and
reported as it is.

## 1. Why

Phase 4 did not confirm C1 (0 of 2; pooled −0.20 [−0.34, −0.02]). Both scorable confirmatory sites had about 2
ship cells per tile, outside the development range; R14 showed coarse sampling alone does not explain the failure.
Phase 5 tests the same claim, with the same frozen models, on new sites inside the development sampling range.

## 2. What is unchanged from v2.1

- **Models:** s_lr; GBT_ship all-16 artifact (cfg 18, sha256 `ef934672…`); P-V1 (three R07 checkpoints,
  seed-averaged, CPU float32). No retraining, no refitting, no tuning. The development set is unchanged; no Phase 4
  sealed pair joins it.
- **Target and evaluation:** A_fine (targets_v1 band, k from the frozen sweep); interior tiles at D1, fallback
  A_fine_int; eval_v1.1 within-pair Spearman ρ at tile scale; block bootstrap over 4 x 4-tile blocks, 2,000
  resamples, seed 20261009, B_min = 8, 10-tile minimum; pooled row unit-stratified, seed 20261013.
- **Ship products:** used where usable, masked otherwise, as in v2.1.
- **Artifact rule and blind calls:** as in v2.1 (Q-coded pages, R08 §3.1 criteria; artifact-dominated out;
  `ab_whole_survey = yes` with amplitude below 0.04 m out of the first statement).
- **Order:** step 1 acquisition, step 2 build and blind pages, step 3 blind calls committed in the ledger, step 4
  predict (EW0207 control first), step 5 score once.

## 3. What changes

### 3.1 Sites (from ACQ-R08b; no other site may be added)

| site | high resolution | ship partner |
|---|---|---|
| Galápagos Spreading Center | MGDS:18210, 1 m product only (MGDS:31811 not used) | TN188, Simrad EM300, 2005 |
| Escanaba Trough | MGDS:30368 | Escanaba, Simrad EM300, 1998 |
| Monterey Canyon | MGDS:24756 | Monterey, Simrad EM300, 1998 |
| Mid-Atlantic Ridge 16.5°N | MGDS:22436 | KN161L04, SeaBeam 2112, 2000 |
| La Jolla Canyon | MGDS:21415 | MV1209, Kongsberg EM122, 2012 |
| Bermuda | MGDS:31675 | KN173L02, SeaBeam 2112, 2003 |
| Chile margin | MGDS:31860 | MV1003, Simrad EM122, 2010 |
| Dorado Outcrop | MGDS:31954 | AT26-24, Kongsberg EM122, 2014 |

Each site is one unit and one pair: one high-resolution mosaic, one ship cruise.

### 3.2 Mechanical product rules (applied by script, without viewing)

1. **Resolution group:** the finest group of grids with cell size 0.985 to 4.99 m whose union covers at least 80 %
   of the largest such group (the ACQ-R08b rule).
2. **Repeat surveys (overlapping grids of the same seafloor, for example Monterey):** keep, for each overlap, the
   grid whose acquisition date is closest to the ship cruise's year; ties go to the larger valid area. Dates come
   from file names or metadata. Non-overlapping grids are mosaicked.
3. **Ship side:** the named cruise's raw swath, gridded by the frozen development chain with contract v2.1
   products; harmonized, co-registered and k-swept exactly as the development pairs were.

### 3.3 Eligibility (fixed now; decided at step 1 from metadata only)

A site enters the C1 set only if all hold at step 1:

1. co-registration passes the development QA thresholds (ACQ-R03);
2. the frozen sweep recovers a k;
3. the gridded ship spacing gives 3.88 to 51.2 ship cells across a 256-px window, and the HR spacing is 0.985 to
   4.99 m;
4. at scoring, the B4 view rules give a scorable view (10 tiles in at least 8 blocks).

A site failing 1 to 3 is "not testable" at step 1 with its reason. A site failing 4 is "not scorable" at step 5.
Then the artifact rule applies at the blind call. No site is replaced or added.

### 3.4 Primary criterion: the pooled row

**C1 (primary):** the mean within-site s_lr ρ over the C1-set sites, with the unit-stratified block bootstrap 95 %
CI (seed 20261013). **Confirmed** if the CI lower bound is above zero; **not confirmed** otherwise; **not testable**
if fewer than 3 sites are in the C1 set.

**C1-per-site (secondary):** each site's s_lr CI as in v2.1, the count with lower bound above zero, and the v2.1
all-sites label, reported beside the primary.

**Why the change, for the manuscript (Steve's condition):** with n sites and a per-site pass rate of 9 in 14 at
development, "every site passes" occurs with probability about 0.64^n even if the method works as in development
(about 3 % at n = 8), so the v2.1 per-site label cannot confirm transfer with more than two or three sites. The
pooled mean estimates average transfer directly and has adequate power. The change is made after Phase 4 was known;
under it, Phase 4 would still read "not confirmed" (pooled −0.20 [−0.34, −0.02]), so the change does not alter
that result. Both readings are reported for Phase 5.

### 3.5 C2 (descriptive)

GBT_ship and P-V1 against s_lr, per site and pooled, each **with** a block-bootstrap CI (same resamples). If the
frozen score script gives no CI for GBT_ship or P-V1, a separate script pinned in v3 computes them. No superiority
claim.

### 3.6 Expectation (stated in v3)

At development, pooled s_lr is +0.392 [+0.317, +0.430] over 14 pairs, and +0.35 at 1.7 cells per tile (R14). Phase
4 was −0.20 on two sites. Phase 5 tests which of these the new sites resemble.

## 4. Prior exposure (for v3)

- Steve has seen none of the eight sites' bathymetry, including the June QC figure for Bermuda and the La Jolla
  Zephyr survey (stated 2026-10-13).
- Seen by everyone: the ACQ-R08 and ACQ-R08b metadata (listed in REPORT_ACQ-R08b §5), including one median depth
  per site rounded to 100 m.
- The executor that ran ACQ-R08b saw only those numbers.

## 5. Lessons from Phase 4, built in

1. The acquisition run record's keys are written to a contract file, and the CNN lock is tested against a real
   rehearsal record before v3 is signed (R12 H1).
2. The CNN allow-list is tested on paths under the real Phase 5 sealed roots (R12b H1).
3. A full dress rehearsal of all four CNN scripts and the acquisition step runs on a mock layout identical to the
   sealed one before v3 is signed (R12c).
4. The Q-code to pair join for the calls file is a pre-registered step of the procedure (Phase 4 deviation note 04).
5. Eligibility on ship sampling is fixed before step 1 (Phase 4's missing rule).

## 6. Directives

| order | directive | repo | what |
|---|---|---|---|
| 1 | ACQ-R09 | acquisition | write and rehearse the Phase 5 step-1 code on development pairs; record contract; freeze and tag |
| 2 | R16 | CNN | Phase 5 scripts (parameterised copies), dress rehearsal on a mock sealed layout against ACQ-R09's rehearsal record; deviation note 04 for Phase 4; render v3 and the sign-off draft; STOP |
| 3 | Steve | | sign v3; tag |
| 4 | ACQ-R10 | acquisition | step 1 on the eight sites: fetch and grid ship swath, harmonize, co-register, k sweep; supplement and run record; metadata-only report |
| 5 | R17 | CNN | build and blind pages |
| 6 | Steve | | blind calls, committed with sha256 in the ledger |
| 7 | R18 | CNN | predict once, score once |
