#!/bin/bash
# ACQ-R04 relaunch under selection_v1.1 (steering ruling 2026-10-03, option D): queue_v1_1/ batches, chained fetches
# (one at a time, <= 6 NCEI workers) -> per-batch serc gridding arrays (<= 16 tasks x 8 CPUs).  No gate (ruling resolved it).
set -euo pipefail
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
Q=reports_post_grl_review/ACQ-R04/queue_v1_1; J=reports_post_grl_review/ACQ-R04/full_run_jobs_v1_1.txt
: > $J; prevF=""
for f in $(ls $Q/batch_*.txt | sort); do
  b=$(basename $f .txt); n=$(wc -l < $f); cr=$(paste -sd, $f)
  F=$(sbatch --parsable --partition=serc --time=48:00:00 ${prevF:+--dependency=afterany:$prevF} sbatch/acq_r04/fetch.sbatch --cruises "$cr" --workers 6)
  B=$(sbatch --parsable --partition=serc --mem=16G --array=0-$((n-1))%16 --dependency=afterany:$F sbatch/acq_r04/blocks.sbatch $f)
  echo "$b fetch=$F blocks=$B n=$n" | tee -a $J; prevF=$F
done
