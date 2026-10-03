#!/bin/bash
#SBATCH --job-name=acq_r04_gate
#SBATCH --partition=serc
#SBATCH --time=00:20:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_gate_%j.out
# ACQ-R04 batch-1 HOLD gate (steering ruling 2026-10-03): exit 1 -> every later processing/fetch job never starts.
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r04.queue gate
