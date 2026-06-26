#!/bin/bash
#SBATCH --job-name=auv_frepair
#SBATCH --partition=normal
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=96G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
MODE="${1:-verify}"
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.discovery.stage_f_repair "$MODE"
