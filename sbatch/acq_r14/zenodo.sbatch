#!/bin/bash
#SBATCH --job-name=acq_r14_zenodo
#SBATCH --partition=normal
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/reports_post_grl_review/ACQ-R14/job_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/reports_post_grl_review/ACQ-R14/job_%j.err
# ACQ-R14 ruling 2026-10-20 (H-2): Zenodo draft + upload of the 66 package files from the OAK copy. Never publishes.
set -euo pipefail
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
module load python/3.12.1 openblas/0.3.28
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host $(hostname) job ${SLURM_JOB_ID} start $(date -u +%FT%TZ)"
$PY -B -m src.acq_r14.zenodo_upload
echo "done $(date -u +%FT%TZ)"
