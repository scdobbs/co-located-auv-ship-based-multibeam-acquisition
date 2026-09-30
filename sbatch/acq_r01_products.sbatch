#!/bin/bash
#SBATCH --job-name=acq_r01_prod
#SBATCH --partition=normal
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --array=1-15%6
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r01_prod_%A_%a.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r01_prod_%A_%a.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
LIST=sbatch/acq_r01_products_list.txt
LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$LIST")
echo "task ${SLURM_ARRAY_TASK_ID}: $LINE host=$(hostname) L_SCRATCH=$L_SCRATCH commit=$(git rev-parse --short HEAD)"
# shellcheck disable=SC2086
$PY -m src.acq_r01.build_products $LINE --nproc 8
echo "exit=$?"
