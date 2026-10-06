#!/bin/bash
#SBATCH --job-name=acq_r04_manifest
#SBATCH --partition=serc
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_manifest_%j.out
# ACQ-R04 wrap-up step: manifest
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition

echo "host=$(hostname) commit=$(git rev-parse --short HEAD)"
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r04.corpus_manifest --version 1; rc=$?; echo "exit=$rc"; exit $rc
