#!/bin/bash
#SBATCH --job-name=acq_r14_finish2
#SBATCH --partition=normal
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/reports_post_grl_review/ACQ-R14/job_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/reports_post_grl_review/ACQ-R14/job_%j.err
# ACQ-R14 ruling 2026-10-20: relicense every pair (re-zip from the staged COGs), regenerate the corpus-level files,
# re-run every check, copy the changed files to OAK and re-verify there.
set -euo pipefail
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
module load python/3.12.1 openblas/0.3.28
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
export GDAL_NUM_THREADS=${SLURM_CPUS_PER_TASK} OMP_NUM_THREADS=1
echo "host $(hostname) job ${SLURM_JOB_ID} start $(date -u +%FT%TZ)"
$PY -B -m src.acq_r14.relicense
$PY -B -m src.acq_r14.corpus
$PY -B -m src.acq_r14.check --repro-all
$PY -B -m src.acq_r14.preserve --package
echo "done $(date -u +%FT%TZ)"
