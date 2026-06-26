#!/bin/bash
#SBATCH --job-name=auv_stagef
#SBATCH --partition=normal
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
ARG="${1:-}"
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.discovery.stage_f_harmonize $ARG
