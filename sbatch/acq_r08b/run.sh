#!/bin/bash
# ACQ-R08b driver: run inside a Slurm allocation (srun -p dev ... or sbatch). STEPS=download,measure (default both).
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) job=${SLURM_JOB_ID:-none} start=$(date -u +%FT%TZ)"
STEPS=${STEPS:-download,measure}; RC_D=0; RC_M=0
if [[ ",$STEPS," == *",download,"* ]]; then echo "=== download ==="; $PY -m src.acq_r08b.download; RC_D=$?; echo "download exit=$RC_D"; fi
if [[ ",$STEPS," == *",measure,"* ]] && [ $RC_D -eq 0 ]; then echo "=== measure ==="; $PY -m src.acq_r08b.measure; RC_M=$?; echo "measure exit=$RC_M"; fi
echo "end=$(date -u +%FT%TZ) exit=$((RC_D + RC_M))"
