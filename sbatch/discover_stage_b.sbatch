#!/bin/bash
#SBATCH --job-name=auv_stageb
#SBATCH --partition=normal
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.err

set -euo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.cli discover-stage-b
# After Stage B updates hr_catalog with true geometry, re-run rebuild
# (which re-joins HR×LR with new footprints) and re-run Stage A so the
# revised Gate A reflects post-resolution counts.
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.cli discover-rebuild
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.cli discover-stage-a
