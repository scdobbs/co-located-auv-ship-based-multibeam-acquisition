#!/bin/bash
#SBATCH --job-name=auv_cfull
#SBATCH --partition=normal
#SBATCH --time=05:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --array=1-33%8
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/cfull_%A_%a.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/cfull_%A_%a.err

set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
LIST=reports/discovery/stage_c_cruise_list.txt
CRUISE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$LIST")
MODE="${STAGE_C_MODE:-clean}"
echo "task ${SLURM_ARRAY_TASK_ID}: cruise=$CRUISE mode=$MODE  L_SCRATCH=$L_SCRATCH"
df -h "$L_SCRATCH" | tail -1
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.discovery.stage_c_full --cruise "$CRUISE" --mode "$MODE"
