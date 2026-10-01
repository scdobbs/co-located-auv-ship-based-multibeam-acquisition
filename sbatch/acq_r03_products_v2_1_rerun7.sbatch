#!/bin/bash
#SBATCH --job-name=acq_r03_prodv21_rr7
#SBATCH --partition=normal
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --array=1-3
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_prodv21_%A_%a.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_prodv21_%A_%a.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" sbatch/acq_r03_products_v2_1_rerun7_list.txt)
echo "task ${SLURM_ARRAY_TASK_ID}: $LINE host=$(hostname) commit=$(git rev-parse --short HEAD)"
# shellcheck disable=SC2086
$PY -m src.acq_r03.build_products_v2_1 $LINE --nproc ${NPROC:-8}
echo "exit=$?"
