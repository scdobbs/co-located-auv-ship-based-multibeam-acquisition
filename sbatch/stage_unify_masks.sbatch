#!/bin/bash
#SBATCH --job-name=auv_unify_masks
#SBATCH --partition=normal
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python

echo "=== STEP 1: generate validity masks for the 21 validated (scratch + manifest) ==="
$PY -m src.discovery.stage_unify_valid_masks || { echo "GENERATE FAILED"; exit 1; }

echo "=== STEP 2: regenerate valid_tiles.parquet for the full 39 ==="
$PY -m src.discovery.stage_unify_valid_tiles || { echo "TILES FAILED"; exit 1; }

echo "=== DONE (OAK persist is HELD for Steve — not run here) ==="
