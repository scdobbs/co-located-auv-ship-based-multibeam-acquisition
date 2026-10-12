#!/bin/bash
#SBATCH --job-name=acq_r07b_harn
#SBATCH --partition=serc,normal
#SBATCH --time=4:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r07b_harn_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r07b_harn_%j.err
# ACQ-R07b B1 (stopped-then-completed vs uninterrupted, development stand-ins, scratch) then B2 (refusal tests).
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
source sbatch/acq_r04/stage_sandbox.sh
echo "host=$(hostname) job=$SLURM_JOB_ID commit=$(git rev-parse --short HEAD)"; grep -m1 "model name" /proc/cpuinfo
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
/usr/bin/time -v $PY -m src.phase4.harness_r07b; echo "harness exit=$?"
$PY -m src.phase4.refusal_tests_r07b; echo "refusal exit=$?"
