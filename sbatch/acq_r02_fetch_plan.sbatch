#!/bin/bash
#SBATCH --job-name=acq_r02_plan
#SBATCH --partition=normal
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r02_plan_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r02_plan_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) job=$SLURM_JOB_ID"
$PY -m src.acq_r01.fetch_plan
echo "exit=$?"
