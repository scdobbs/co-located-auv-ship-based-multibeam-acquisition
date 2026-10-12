#!/bin/bash
#SBATCH --job-name=acq_r07b_compl
#SBATCH --partition=serc,normal
#SBATCH --time=4:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r07b_compl_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r07b_compl_%j.err
# ACQ-R07b Part F3: the completion, ONCE, in phase4 mode (ACQ-R07 driver's resources and sandbox).  Submit only after
# Steve's go-ahead (deviation note committed) and after F2 (lockbox directories chgrp oak_hilley, chmod 2770).
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
ACQ=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
CNN=/home/users/scdobbs/GAN_Bathymetry_Project
R11=grl_reviews-and-prompt-reports/directives_and_reports/R11
PREREG=9795db3b22d6c54f7a85618dbaccafa054e88487b33236a7b2083ecb8c605979
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
cd $ACQ
echo "host=$(hostname) job=$SLURM_JOB_ID commit=$(git rev-parse HEAD) freeze_tag=$(git rev-parse phase4-acq-freeze^{commit}) complete_tag=$(git rev-parse phase4-acq-complete^{commit} 2>/dev/null) start=$(date -u +%FT%TZ)"
grep -m1 "model name" /proc/cpuinfo
for f in SIGNOFF_phase4_prereg_v2.md DEVIATION_phase4_01.md; do
  (cd $CNN && git ls-files --error-unmatch $R11/$f >/dev/null 2>&1) || { echo "PRECONDITION FAILED: $f not tracked in the CNN repo"; exit 3; }
  echo "$f commit=$(cd $CNN && git log -1 --format=%H -- $R11/$f) sha256=$(sha256sum $CNN/$R11/$f | cut -d' ' -f1)"
done
[ "$(sha256sum reports_post_grl_review/ACQ-R06b/freeze_record.json | cut -d' ' -f1)" = "331c94f01d7d1a2e52fb969c5fb1872aae2cd2ed249a3757b99e9d217b3ac0cb" ] || { echo "PRECONDITION FAILED: freeze_record.json hash"; exit 3; }
source sbatch/acq_r04/stage_sandbox.sh
df -h "$L_SCRATCH" | tail -1
$PY -c "import sys; from src.phase4 import guard_selftest as G; r=G.run(write=True, out_path='reports_post_grl_review/ACQ-R07b/guard_selftest_completion.json'); print('guard', r['reader_checks']['n_blocked'], '/', r['reader_checks']['n'], 'all_passed', r['all_passed']); sys.exit(0 if r['all_passed'] else 4)" || { echo "PRECONDITION FAILED: guard self-test"; exit 4; }
echo "CMD: python -m src.phase4.sealed_step1_complete --mode phase4 --signoff $CNN/$R11/SIGNOFF_phase4_prereg_v2.md --prereg-sha256 $PREREG"
/usr/bin/time -v $PY -m src.phase4.sealed_step1_complete --mode phase4 --signoff "$CNN/$R11/SIGNOFF_phase4_prereg_v2.md" --prereg-sha256 "$PREREG"; rc=$?
echo "completion exit=$rc end=$(date -u +%FT%TZ)"; exit $rc
