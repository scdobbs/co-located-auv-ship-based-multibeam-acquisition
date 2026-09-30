#!/bin/bash
#SBATCH --job-name=acq_r03_pangaea
#SBATCH --partition=normal
#SBATCH --time=48:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_pangaea_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_pangaea_%j.err
# ACQ-R03 §1: (1) fetch the M114/1 selection, (2) derive M112/1 file positions (Range heads) and select,
# (3) fetch the M112/1 selection.  One worker throughout; every step resumable.
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) job=$SLURM_JOB_ID commit=$(git rev-parse --short HEAD) start=$(date -u +%FT%TZ)"
$PY -m src.acq_r03.fetch_pangaea --cruise PANGAEA_864677 --throttle 1.0 --max-hours 12; echo "M114 fetch exit=$?"
$PY -m src.acq_r03.m112_positions --throttle 0.5; echo "M112 positions exit=$?"
if [ -f reports_post_grl_review/ACQ-R03/pangaea_selection_PANGAEA_892317.csv ]; then
  $PY -m src.acq_r03.fetch_pangaea --cruise PANGAEA_892317 --throttle 1.0 --max-hours 33; echo "M112 fetch exit=$?"
fi
echo "end=$(date -u +%FT%TZ)"
