#!/bin/bash
#SBATCH --job-name=acq_r02_harm
#SBATCH --partition=normal
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r02_harm_%A_%a.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r02_harm_%A_%a.err
# ACQ-R02 §6 harmonize-only re-run (raw swath and union grid already on OAK). List line: <cruise>|<hr>
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
LIST=${HARM_LIST:-sbatch/acq_r02_harmonize_list.txt}
LINE=$(sed -n "${SLURM_ARRAY_TASK_ID}p" "$LIST")
CRUISE=${LINE%%|*}; HR=${LINE#*|}
echo "task ${SLURM_ARRAY_TASK_ID}: cruise=$CRUISE hr=$HR host=$(hostname) commit=$(git rev-parse --short HEAD)"
$PY -m src.acq_r01.harmonize_new --hr "$HR" --cruise "$CRUISE" --nproc 8 --batch-files ${BATCH_FILES:-1} || echo "HARMONIZE FAILED for $HR"
echo "exit=0"
