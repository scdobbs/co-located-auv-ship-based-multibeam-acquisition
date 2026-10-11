#!/bin/bash
#SBATCH --job-name=acq_r07_step1
#SBATCH --partition=serc,normal
#SBATCH --time=4:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r07_step1_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r07_step1_%j.err
# ACQ-R07 §2: the frozen Phase 4 step 1 (src/phase4/sealed_step1.py --mode phase4), run ONCE, unchanged, with the
# ACQ-R06b rehearsal's resources and the node-local MB-System sandbox.  Prepared 2026-10-11; NOT submitted by ACQ-R07
# (precondition 1 failed: the sign-off is not committed in the CNN repo).  Submit only after Steve's ruling.
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
ACQ=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
CNN=/home/users/scdobbs/GAN_Bathymetry_Project
SIGNOFF=$CNN/grl_reviews-and-prompt-reports/directives_and_reports/R11/SIGNOFF_phase4_prereg_v2.md
PREREG=9795db3b22d6c54f7a85618dbaccafa054e88487b33236a7b2083ecb8c605979
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
cd $ACQ
echo "host=$(hostname) job=$SLURM_JOB_ID commit=$(git rev-parse HEAD) freeze_tag=$(git rev-parse phase4-acq-freeze^{commit}) start=$(date -u +%FT%TZ)"
grep -m1 "model name" /proc/cpuinfo
# §1.1 the sign-off must be committed in the CNN repo (checked again here; the step's lock 1 checks only existence + sha256)
if ! (cd $CNN && git ls-files --error-unmatch grl_reviews-and-prompt-reports/directives_and_reports/R11/SIGNOFF_phase4_prereg_v2.md >/dev/null 2>&1); then
  echo "PRECONDITION 1 FAILED: sign-off is not tracked in the CNN repo; not running the step"; exit 3; fi
echo "signoff_commit=$(cd $CNN && git log -1 --format=%H -- grl_reviews-and-prompt-reports/directives_and_reports/R11/SIGNOFF_phase4_prereg_v2.md) signoff_sha256=$(sha256sum $SIGNOFF | cut -d' ' -f1)"
# §1.3 freeze record hash
[ "$(sha256sum reports_post_grl_review/ACQ-R06b/freeze_record.json | cut -d' ' -f1)" = "331c94f01d7d1a2e52fb969c5fb1872aae2cd2ed249a3757b99e9d217b3ac0cb" ] || { echo "PRECONDITION 3 FAILED: freeze_record.json hash"; exit 3; }
source sbatch/acq_r04/stage_sandbox.sh
df -h "$L_SCRATCH" | tail -1
# §1.6 guard self-test immediately before the run (record in the ACQ-R07 directory; the step repeats it internally)
$PY -c "import sys; from src.phase4 import guard_selftest as G; r=G.run(write=True, out_path='reports_post_grl_review/ACQ-R07/guard_selftest.json'); print('guard', r['reader_checks']['n_blocked'], '/', r['reader_checks']['n'], 'all_passed', r['all_passed']); sys.exit(0 if r['all_passed'] else 4)" || { echo "PRECONDITION 6 FAILED: guard self-test"; exit 4; }
# §2 the run: exact command line; no --run-tag; --freeze-record at its default
echo "CMD: python -m src.phase4.sealed_step1 --mode phase4 --signoff $SIGNOFF --prereg-sha256 $PREREG"
/usr/bin/time -v $PY -m src.phase4.sealed_step1 --mode phase4 --signoff "$SIGNOFF" --prereg-sha256 "$PREREG"; rc=$?
echo "step1 exit=$rc end=$(date -u +%FT%TZ)"; exit $rc
