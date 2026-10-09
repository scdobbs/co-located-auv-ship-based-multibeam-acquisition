#!/bin/bash
#SBATCH --job-name=acq_r05_h2
#SBATCH --partition=serc,normal
#SBATCH --time=3:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r05_h2_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r05_h2_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
source sbatch/acq_r04/stage_sandbox.sh
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r05.h2_fk181031; echo "h2 exit=$?"
