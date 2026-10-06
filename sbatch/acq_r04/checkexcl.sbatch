#!/bin/bash
#SBATCH --job-name=acq_r04_checkexcl
#SBATCH --partition=serc
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_checkexcl_%j.out
# ACQ-R04 wrap-up step: checkexcl
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition

echo "host=$(hostname) commit=$(git rev-parse --short HEAD)"
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r04.check_exclusion --manifest pretrain_manifest_v1.parquet --tag v1; rc=$?; echo "exit=$rc"; exit $rc
