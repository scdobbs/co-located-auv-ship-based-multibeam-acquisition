#!/bin/bash
#SBATCH --job-name=auv_cpilot
#SBATCH --partition=normal
#SBATCH --time=05:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.err

set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
echo "L_SCRATCH=$L_SCRATCH"; df -h "$L_SCRATCH" | tail -1
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.discovery.stage_c_pilot
