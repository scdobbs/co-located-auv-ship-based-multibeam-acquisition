#!/bin/bash
#SBATCH --job-name=acq_r03_pchain
#SBATCH --partition=normal
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_pchain_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_pchain_%j.err
# ACQ-R03 §1.5: standard chain for one PANGAEA cruise whose selected set is complete:
# stage C (grid_lr) -> C.5/F (harmonize_new: harmonize, masked coreg, masks, tiles, k sweep, QC figure) -> contract v2.1 products.
# Usage: sbatch --export=ALL,CRUISE=PANGAEA_864677,HR=PANGAEA:889317 sbatch/acq_r03_pangaea_chain.sbatch
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
export ACQ_REPORT_DIR=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/reports_post_grl_review/ACQ-R03
echo "host=$(hostname) commit=$(git rev-parse --short HEAD) cruise=$CRUISE hr=$HR"
$PY - <<PYEOF
import json,sys
s=json.load(open("reports_post_grl_review/ACQ-R03/fetch_summary_$CRUISE.json"))["latest"]
print("fetch status:", s["status"], "remaining", s["n_remaining"]); sys.exit(0 if s["n_remaining"]==0 else 3)
PYEOF
[ $? -eq 0 ] || { echo "selected set incomplete; chain not run"; exit 3; }
$PY -m src.acq_r01.grid_lr --cruise "$CRUISE" --hr "$HR" --sonar "Kongsberg EM122" || { echo "GRID FAILED"; exit 1; }
$PY -m src.acq_r01.harmonize_new --hr "$HR" --cruise "$CRUISE" --nproc 8 --products-version 2.1 || { echo "HARMONIZE FAILED"; exit 1; }
echo "exit=0"
