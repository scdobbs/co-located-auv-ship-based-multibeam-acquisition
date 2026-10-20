#!/bin/bash
#SBATCH --job-name=acq_r14_build
#SBATCH --partition=normal
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/reports_post_grl_review/ACQ-R14/job_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/reports_post_grl_review/ACQ-R14/job_%j.err
# ACQ-R14: build the public package (COG conversion + zips), corpus-level files, checks, copy to OAK. Idempotent.
set -euo pipefail
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
module load python/3.12.1 openblas/0.3.28
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
export GDAL_NUM_THREADS=${SLURM_CPUS_PER_TASK} GDAL_CACHEMAX=2048 OMP_NUM_THREADS=1
echo "host $(hostname) job ${SLURM_JOB_ID} start $(date -u +%FT%TZ)"
$PY -B -m src.acq_r14.build --workers 4
$PY -B -m src.acq_r14.corpus
$PY -B -m src.acq_r14.check --repro-all
$PY -B -m src.acq_r14.preserve --package
echo "done $(date -u +%FT%TZ)"
