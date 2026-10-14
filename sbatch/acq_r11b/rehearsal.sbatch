#!/bin/bash
#SBATCH --job-name=acq_r11b_reh
#SBATCH --partition=serc,normal
#SBATCH --time=8:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r11b_reh_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r11b_reh_%j.err
# ACQ-R11b §4 — Phase 5 rehearsal on development data (scratch, no network).
#   pre   <tag>: build the mock layout, rehearsal run without a freeze record (its loaded-module list feeds the freeze)
#   final <tag>: rehearsal against freeze_record_phase5_v2.json, FK151121 harness, compare, CNN lock copy, refusal suite,
#                blindness test (this job's own logs included)
set -uo pipefail
STAGE=${1:?pre|final}; TAG=${2:?run tag}
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
source sbatch/acq_r04/stage_sandbox.sh
export L_SCRATCH=${L_SCRATCH_JOB:-$L_SCRATCH}
PY="/home/users/scdobbs/bathy_diffusion_env/bin/python -B"
LOGS=logs/acq_r11b_reh_${SLURM_JOB_ID}.out,logs/acq_r11b_reh_${SLURM_JOB_ID}.err
FR=$PWD/reports_post_grl_review/PHASE5/freeze_record_phase5_v2.json   # absolute: the CNN lock copy runs with cwd on scratch (job 47704841 passed a relative path; lock copy re-run by hand)
echo "host=$(hostname) job=$SLURM_JOB_ID commit=$(git rev-parse --short HEAD) stage=$STAGE tag=$TAG"
if [ "$STAGE" = pre ]; then
  $PY -m src.phase5.mock_p5 || exit 2
  /usr/bin/time -v $PY -m src.phase5.sealed_step1_p5 --mode rehearsal --run-tag "$TAG" --nproc 6; echo "rehearsal exit=$?"
  $PY -m src.phase5.blind_test_p5 --run-record reports_post_grl_review/ACQ-R11b/rehearsal/step1_run_rehearsal_${TAG}.json --logs $LOGS; echo "blind exit=$?"
else
  /usr/bin/time -v $PY -m src.phase5.sealed_step1_p5 --mode rehearsal --run-tag "$TAG" --nproc 6 --freeze-record $FR; echo "rehearsal exit=$?"
  REC=$PWD/reports_post_grl_review/ACQ-R11b/rehearsal/step1_run_rehearsal_${TAG}.json
  $PY -m src.phase5.harness_fk151121_p5 --run-tag "$TAG" --nproc 6; echo "harness exit=$?"
  $PY -m src.phase5.compare_p5 --run-record $REC; echo "compare exit=$?"
  $PY -m src.phase5.cnn_lock_check_p5 --run-record $REC --freeze-record $FR; echo "cnn lock exit=$?"
  $PY -m src.phase5.refusal_tests_p5; echo "refusal exit=$?"
  $PY -m src.phase5.blind_test_p5 --run-record $REC --logs $LOGS; echo "blind exit=$?"
fi
