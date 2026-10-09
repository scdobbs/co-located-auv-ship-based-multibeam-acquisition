#!/bin/bash
#SBATCH --job-name=acq_r05_src
#SBATCH --partition=normal
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r05_src_%A_%a.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r05_src_%A_%a.err
# ACQ-R05 §2.1.1: per LR cruise — NCEI listing + nav subset + fetch of missing context files (<= 6 workers) + ACQ-R04 coverage pass.
# $1 = file with one cruise per line.  Sandbox staged to node-local disk (ACQ-R04 rule).
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
source sbatch/acq_r04/stage_sandbox.sh
CRUISE=$(sed -n "$((SLURM_ARRAY_TASK_ID+1))p" "$1")
echo "host=$(hostname) commit=$(git rev-parse --short HEAD) cruise=$CRUISE"; df -h "$L_SCRATCH" | tail -1
/usr/bin/time -v /home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r05.sources --cruise "$CRUISE" --workers ${WORKERS:-6} ${EXTRA:-}; echo "sources exit=$?"
