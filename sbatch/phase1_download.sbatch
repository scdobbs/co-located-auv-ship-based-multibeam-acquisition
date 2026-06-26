#!/bin/bash
#SBATCH --job-name=auv_phase1_dl
#SBATCH --partition=normal
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.err

set -euo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.cli phase1-download
# Verify + write report once the download completes. Both commands return
# 0 only when all 5 gates pass; the sbatch will reflect the last status.
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.cli phase1-verify || true
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.cli phase1-report || true
