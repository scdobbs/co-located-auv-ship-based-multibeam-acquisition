#!/bin/bash
#SBATCH --job-name=acq_r04_excl
#SBATCH --partition=normal
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_excl_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_excl_%j.err
# ACQ-R04 §1: exclusion_v1 + pool ids (no network).
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) commit=$(git rev-parse --short HEAD)"
$PY -m src.acq_r04.exclusion; echo "exclusion exit=$?"
