#!/bin/bash
#SBATCH --job-name=acq_r01_disc
#SBATCH --partition=normal
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r01_disc_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r01_disc_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) job=$SLURM_JOB_ID"
echo "=== §3 discovery re-run (counts only) ==="
$PY -m src.acq_r01.discovery_rerun ${DISC_ARGS:-}; RC1=$?
echo "discovery exit=$RC1"
echo "=== §5 pretraining scoping ==="
$PY -m src.acq_r01.pretrain_scope --sample 240; RC2=$?
echo "pretrain exit=$RC2"
echo "exit=$((RC1 + RC2))"
