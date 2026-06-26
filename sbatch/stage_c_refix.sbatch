#!/bin/bash
#SBATCH --job-name=auv_crefix
#SBATCH --partition=normal
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=24G
#SBATCH --array=1-4
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/crefix_%A_%a.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/crefix_%A_%a.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
C=$(sed -n "${SLURM_ARRAY_TASK_ID}p" reports/discovery/stage_c_refix_list.txt)
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.discovery.stage_c_full --cruise "$C" --mode raw
