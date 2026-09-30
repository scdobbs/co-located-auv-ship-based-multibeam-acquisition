#!/bin/bash
#SBATCH --job-name=acq_r03_prodv21_am
#SBATCH --partition=bigmem
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=256G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_prodv21_am_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_prodv21_am_%j.err
# 2009_Amundsen__MGDS_30047: 24 M common cells; ACQ-R02 peak RSS 54 GB -> 64 GB (OOM at 64 GB on normal, per-core cap 8 GB) -> bigmem 256 GB (partition minimum), 4 workers
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) commit=$(git rev-parse --short HEAD)"
$PY -m src.acq_r03.build_products_v2_1 --pair 2009_Amundsen__MGDS_30047 --nproc 4
echo "exit=$?"
