#!/bin/bash
#SBATCH --job-name=acq_r01_fetch_pg
#SBATCH --partition=normal
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r01_fetch_pg_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r01_fetch_pg_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) job=$SLURM_JOB_ID"
# hs.pangaea.de rate-limits (HTTP 429/503 with 4 workers): single worker, 1.5 s throttle, backoff on 429
$PY -m src.acq_r01.fetch_swath --pangaea ${PANGAEA_IDS:-859528,899408,919755} --workers 1 --throttle ${PANGAEA_THROTTLE:-1.5}
echo "exit=$?"
