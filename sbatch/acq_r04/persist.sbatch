#!/bin/bash
#SBATCH --job-name=acq_r04_persist
#SBATCH --partition=serc
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_persist_%j.out
# ACQ-R04 wrap-up step: persist
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition

echo "host=$(hostname) commit=$(git rev-parse --short HEAD)"
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r04.persist --manifest pretrain_manifest_v1.parquet --workers 6; rc=$?; echo "exit=$rc"; exit $rc
