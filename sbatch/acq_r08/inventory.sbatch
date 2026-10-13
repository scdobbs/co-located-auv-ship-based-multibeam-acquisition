#!/bin/bash
#SBATCH --job-name=acq_r08_inv
#SBATCH --partition=normal
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r08_inv_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r08_inv_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) job=$SLURM_JOB_ID start=$(date -u +%FT%TZ)"
POOLS=${POOLS:-c,a,b}; RC_C=0; RC_A=0; RC_B=0
if [[ ",$POOLS," == *",c,"* ]]; then echo "=== Pool C (records only) ==="; $PY -m src.acq_r08.pool_c; RC_C=$?; echo "pool_c exit=$RC_C"; fi
if [[ ",$POOLS," == *",a,"* ]]; then echo "=== Pool A (catalog harvest + screen) ==="; $PY -m src.acq_r08.pool_a ${POOL_A_ARGS:-}; RC_A=$?; echo "pool_a exit=$RC_A"; fi
if [[ ",$POOLS," == *",b,"* ]]; then echo "=== Pool B (NOS BAG surveys) ==="; $PY -m src.acq_r08.pool_b; RC_B=$?; echo "pool_b exit=$RC_B"; fi
echo "=== report draft ==="; $PY -m src.acq_r08.report; RC_R=$?; echo "report exit=$RC_R"
echo "end=$(date -u +%FT%TZ) exit=$((RC_C + RC_A + RC_B + RC_R))"
