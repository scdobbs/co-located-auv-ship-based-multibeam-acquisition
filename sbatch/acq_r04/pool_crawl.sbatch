#!/bin/bash
#SBATCH --job-name=acq_r04_crawl
#SBATCH --partition=normal
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_crawl_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_crawl_%j.err
# ACQ-R04 §1: pool attributes (NCEI metadata only: Geoportal ISO, autoindex listings, up to 3 .inf per cruise). Resumable.
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) commit=$(git rev-parse --short HEAD)"
$PY -m src.acq_r04.pool_crawl --workers 6; echo "crawl exit=$?"
