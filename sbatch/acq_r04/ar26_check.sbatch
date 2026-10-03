#!/bin/bash
#SBATCH --job-name=acq_r04_ar26
#SBATCH --partition=serc
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_ar26_%j.out
# ACQ-R04 AR26 collision check (read/compare only; rebuilds nothing).
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r04.ar26_check 2>&1; echo "exit=$?"
