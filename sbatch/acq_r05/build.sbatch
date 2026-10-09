#!/bin/bash
#SBATCH --job-name=acq_r05_ctx
#SBATCH --partition=normal
#SBATCH --time=8:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r05_ctx_%A_%a.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r05_ctx_%A_%a.err
# ACQ-R05 §2: context grid + products + agreement for one pair per array task.  $1 = file with one pair id per line.
# CPU only; <= 4 product workers + 1 mbgrid container per task (ACQ-R04 container-count rule).
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
source sbatch/acq_r04/stage_sandbox.sh
PAIR=$(sed -n "$((SLURM_ARRAY_TASK_ID+1))p" "$1")
echo "host=$(hostname) commit=$(git rev-parse --short HEAD) pair=$PAIR"; df -h "$L_SCRATCH" | tail -1
/usr/bin/time -v /home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r05.build --pair "$PAIR" --nproc ${NPROC:-4} ${EXTRA:-}; echo "build exit=$?"
