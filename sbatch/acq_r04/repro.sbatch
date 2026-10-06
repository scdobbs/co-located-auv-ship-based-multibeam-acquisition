#!/bin/bash
#SBATCH --job-name=acq_r04_repro
#SBATCH --partition=serc
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_repro_%j.out
# ACQ-R04 wrap-up step: repro
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
source sbatch/acq_r04/stage_sandbox.sh
echo "host=$(hostname) commit=$(git rev-parse --short HEAD)"
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r04.repro_check --manifest pretrain_manifest_v1.parquet --root OAK; rc=$?; echo "exit=$rc"; exit $rc
