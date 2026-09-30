#!/bin/bash
#SBATCH --job-name=acq_r03_m112
#SBATCH --partition=normal
#SBATCH --time=44:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_m112_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_m112_%j.err
# ACQ-R03 §1.2/1.3 for M112/1: (1) 2 MB Range heads of all 1,170 .all files + ONE MB-System pass -> positions -> selection;
# (2) single-worker resumable fetch of the selection.  (M114/1 completed in job 46121286.)
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) job=$SLURM_JOB_ID commit=$(git rev-parse --short HEAD) start=$(date -u +%FT%TZ)"
$PY -m src.acq_r03.m112_positions --throttle 0.5; echo "M112 positions exit=$?"
if [ -f reports_post_grl_review/ACQ-R03/pangaea_selection_PANGAEA_892317.csv ]; then
  $PY -m src.acq_r03.fetch_pangaea --cruise PANGAEA_892317 --throttle 1.0 --max-hours 36; echo "M112 fetch exit=$?"
fi
echo "end=$(date -u +%FT%TZ)"
