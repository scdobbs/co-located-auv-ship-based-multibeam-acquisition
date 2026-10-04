#!/bin/bash
#SBATCH --job-name=acq_r04_blocks
#SBATCH --partition=normal
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_blocks_%A_%a.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_blocks_%A_%a.err
# ACQ-R04 §3.3-3.4: grid + products for one cruise per array task. $1 = file with one cruise per line.
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
CRUISE=$(sed -n "$((SLURM_ARRAY_TASK_ID+1))p" "$1")
echo "host=$(hostname) commit=$(git rev-parse --short HEAD) cruise=$CRUISE"; df -h "$L_SCRATCH" | tail -1
/usr/bin/time -v $PY -m src.acq_r04.blocks --cruise "$CRUISE" --grid-workers ${GRID_WORKERS:-2} --prod-workers ${PROD_WORKERS:-1} --grid-mode ${GRID_MODE:-dev_chain}; echo "blocks exit=$?"
