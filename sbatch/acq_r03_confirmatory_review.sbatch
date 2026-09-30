#!/bin/bash
#SBATCH --job-name=acq_r03_confrev
#SBATCH --partition=normal
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --array=1-2
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_confrev_%A_%a.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_confrev_%A_%a.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PAIRS=(KN182L03__MGDS_30193 SUM1004__MGDS_33090)
P=${PAIRS[$((SLURM_ARRAY_TASK_ID-1))]}
echo "host=$(hostname) commit=$(git rev-parse --short HEAD) pair=$P"
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r03.confirmatory_review_package --pair "$P"
echo "exit=$?"
