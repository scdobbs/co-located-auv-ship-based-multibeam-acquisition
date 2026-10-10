#!/bin/bash
#SBATCH --job-name=acq_r06b_reh
#SBATCH --partition=serc,normal
#SBATCH --time=4:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r06b_reh_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r06b_reh_%j.err
# ACQ-R06b B1: the ten-pair rerun of sealed_step1.py --mode rehearsal with the edited code (one invocation, run tag r06b).
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
source sbatch/acq_r04/stage_sandbox.sh
TAG=${TAG:-r06b}
echo "host=$(hostname) commit=$(git rev-parse --short HEAD) tag=$TAG"; grep -m1 "model name" /proc/cpuinfo; df -h "$L_SCRATCH" | tail -1
/usr/bin/time -v /home/users/scdobbs/bathy_diffusion_env/bin/python -m src.phase4.sealed_step1 --mode rehearsal --run-tag "$TAG" --nproc ${NPROC:-6} --batch-files ${BATCH_FILES:-1} ${PAIRS:+--pairs $PAIRS}; echo "step1 exit=$?"
