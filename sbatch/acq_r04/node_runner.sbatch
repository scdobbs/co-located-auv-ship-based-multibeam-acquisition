#!/bin/bash
#SBATCH --job-name=acq_r04_node
#SBATCH --partition=serc
#SBATCH --time=2-00:00:00
#SBATCH --exclusive
#SBATCH --constraint=CLASS:SH3_CBASE|CLASS:SH3_CBASE.1
#SBATCH --cpus-per-task=32
#SBATCH --mem=240G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_node_%A_%a.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r04_node_%A_%a.err
# ACQ-R04 (2026-10-04): one whole 32-core serc node per task, 2 cruises at a time, <= 4 containers active per node.
# 16 tasks x 32 CPUs = 512 CPUs (serc guidance: ~1000 concurrent CPUs per person). $1 = cruise list, $2 = number of slots.
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
echo "host=$(hostname) commit=$(git rev-parse --short HEAD) slot=$SLURM_ARRAY_TASK_ID/$2"; df -h "$L_SCRATCH" | tail -1
/home/users/scdobbs/bathy_diffusion_env/bin/python -m src.acq_r04.node_runner --list "$1" --slot "$SLURM_ARRAY_TASK_ID" --nslots "$2" --parallel 2; echo "runner exit=$?"
