#!/bin/bash
#SBATCH --job-name=auv_c1ap
#SBATCH --partition=normal
#SBATCH --time=00:40:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.discovery.stage_c1_append
