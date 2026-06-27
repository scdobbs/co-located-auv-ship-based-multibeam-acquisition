#!/bin/bash
#SBATCH --job-name=auv_c1p1
#SBATCH --partition=normal
#SBATCH --time=02:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.discovery.stage_c1_phase1
