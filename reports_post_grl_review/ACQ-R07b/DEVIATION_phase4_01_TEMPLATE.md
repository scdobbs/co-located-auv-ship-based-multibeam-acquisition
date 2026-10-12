# DEVIATION_phase4_01 — Phase 4 step 1 stopped and was completed

**Pre-registration:** `PREREG_phase4_v2.md`, sha256 `9795db3b22d6c54f7a85618dbaccafa054e88487b33236a7b2083ecb8c605979`
(tag `phase4-prereg-v2`), signed 2026-10-11 (sign-off commit 18e51397).

**What the pre-registration says.** B3 step 1 runs the frozen `sealed_step1.py --mode phase4` once, and it writes
`manifest/pairs_phase4_sealed.parquet` once.

**What happened.** The frozen step ran once (ACQ-R07, job 47434040; run record sha256
`7cc5b46d437a72976027f8e7ca9b0f31a8b9eeb5161928c67fce41f87127ce2b`).
- It completed KN182L03, RC2511 and SUM1004 and wrote AT42-03's outputs.
- It then stopped under its rule C4, because the directory mode of `harmonized/AT42-03__MGDS_32007` could not be
  restored. That directory belonged to group `nobody`, which is not one of the owner's groups, so `chmod` cleared its
  setgid bit (2770 became 0770).
- TN159 was not started, and no supplement was written.
- The cause is file-system metadata. No data value, rule or code path that computes a result was involved.

**What was done.**
1. The step-1 results of the four finished pairs were kept exactly as the frozen step wrote them, and were not
   recomputed.
2. The two lockbox directories were changed to group `oak_hilley` and mode 2770. No file inside them was touched.
3. A completion script (`src/phase4/sealed_step1_complete.py`, sha256 6c49a66a9fdf9b2156a13b10b315a71975e12791f909c5d6118e2a4f5dd255f0; completion freeze record sha256 9b84a378000c49b1cc191f33e6641e237d02e5eb6a2c87477307aafaa89d9b57; tag
   `phase4-acq-complete`), rehearsed in ACQ-R07b, did three things:
   - it read the four pairs from their records, after verifying every file hash;
   - it ran the frozen per-pair code on TN159;
   - it wrote the five-row supplement with the frozen row writer.

   Its run record cites the frozen freeze record (sha256 `331c94f01d7d1a2e52fb969c5fb1872aae2cd2ed249a3757b99e9d217b3ac0cb`),
   this note, and the stopped run.

**What did not change.** No rule, criterion, candidate, threshold or code path of the pre-registration. No step-1
value of any confirmatory pair. The order of operations in B3 from step 2 on.

**Known before this note was signed.** Steve had seen the step-1 quantities of the three confirmatory pairs reported
in REPORT_ACQ-R07: spacings, k and per-k verdicts, product status and flags, and cells across the window. No
amplitude, tile, figure, prediction or score existed.

Signed: ______Stephen Cole Dobbs________________   Date: __10/11/2026________
