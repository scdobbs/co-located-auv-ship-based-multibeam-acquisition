#!/bin/bash
#SBATCH --job-name=acq_r02_acq
#SBATCH --partition=normal
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r02_acq_%A_%a.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r02_acq_%A_%a.err
# ACQ-R02 §6 per-LR-cruise pipeline: fetch (plan) -> grid (stage C) -> harmonize each served pair.
# List line format: <cruise>|<hr1,hr2>|<sonar>
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
LIST=${ACQ_LIST:-sbatch/acq_r02_acquire_list.txt}
LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$LIST")
CRUISE=${LINE%%|*}; REST=${LINE#*|}; HRS=${REST%%|*}; SONAR=${REST#*|}
echo "task ${SLURM_ARRAY_TASK_ID}: cruise=$CRUISE hrs=$HRS sonar=$SONAR host=$(hostname) commit=$(git rev-parse --short HEAD)"
# fetch is resumable: retry up to 3 times (transient HEAD/GET failures), then stop if still incomplete
RC=1
for attempt in 1 2 3; do
  $PY -m src.acq_r01.fetch_swath --plan-csv reports_post_grl_review/ACQ-R02/fetch_plan/file_plan.csv --cruises "$CRUISE" --workers ${FETCH_WORKERS:-4} --throttle ${FETCH_THROTTLE:-0.2} && { RC=0; break; }
  echo "fetch attempt $attempt incomplete"; sleep 60
done
[ $RC -eq 0 ] || { echo "FETCH FAILED"; exit 1; }
$PY -m src.acq_r01.grid_lr --cruise "$CRUISE" --hr "$HRS" --sonar "$SONAR" || { echo "GRID FAILED"; exit 1; }
IFS=',' read -ra HRA <<< "$HRS"
for h in "${HRA[@]}"; do
  $PY -m src.acq_r01.harmonize_new --hr "$h" --cruise "$CRUISE" --nproc 8 --batch-files ${BATCH_FILES:-1} || echo "HARMONIZE FAILED for $h"
done
echo "exit=0"
