#!/bin/bash
#SBATCH --job-name=acq_r04_fetch
#SBATCH --partition=normal
#SBATCH --time=48:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_fetch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_fetch_%j.err
# ACQ-R04 §3.2: NCEI raw swath -> scratch pretrain_raw/ (one process, <= 6 workers). Args passed through.
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) commit=$(git rev-parse --short HEAD) args=$*"
$PY -m src.acq_r04.fetch "$@"; echo "fetch exit=$?"
