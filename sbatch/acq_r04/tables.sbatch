#!/bin/bash
#SBATCH --job-name=acq_r04_tables
#SBATCH --partition=serc
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_tables_%j.out
# ACQ-R04 wrap-up step: tables
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition

echo "host=$(hostname) commit=$(git rev-parse --short HEAD)"
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r04.tables --manifest pretrain_manifest_v1.parquet; rc=$?; echo "exit=$rc"; exit $rc
