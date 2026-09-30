#!/bin/bash
#SBATCH --job-name=acq_r03_at37
#SBATCH --partition=normal
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_at37_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_at37_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
echo "host=$(hostname) commit=$(git rev-parse --short HEAD)"
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r03.at37_review_package --nproc 8
echo "exit=$?"
