#!/bin/bash
# ACQ-R04 full run: chained fetch batches (one at a time, <= 6 NCEI workers) -> per-batch gridding arrays on serc
# (<= 16 tasks x 8 CPUs per batch, serc guidance ~1000 CPUs/person) -> batch-1 HOLD gate gates batches >= 2 and fetches >= 3.
# Submits jobs only (no polling). Job ids -> reports_post_grl_review/ACQ-R04/full_run_jobs.txt
set -euo pipefail
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
Q=reports_post_grl_review/ACQ-R04/queue; J=reports_post_grl_review/ACQ-R04/full_run_jobs.txt
: > $J
prevF=""; G=""
for f in $(ls $Q/batch_*.txt | sort); do
  b=$(basename $f .txt); n=$(wc -l < $f); cr=$(paste -sd, $f)
  dep=""; [ -n "$prevF" ] && dep="afterany:$prevF"
  [ -n "$G" ] && [ "$b" != "batch_02" ] && dep="$dep,afterok:$G"
  F=$(sbatch --parsable --partition=serc --time=48:00:00 ${dep:+--dependency=${dep#,}} sbatch/acq_r04/fetch.sbatch --cruises "$cr" --workers 6)
  bdep="afterany:$F"; [ -n "$G" ] && bdep="$bdep,afterok:$G"
  B=$(sbatch --parsable --partition=serc --mem=16G --array=0-$((n-1))%16 --dependency=$bdep sbatch/acq_r04/blocks.sbatch $f)
  echo "$b fetch=$F blocks=$B n=$n" | tee -a $J
  if [ "$b" == "batch_01" ]; then
    G=$(sbatch --parsable --dependency=afterany:$B sbatch/acq_r04/gate.sbatch); echo "gate=$G" | tee -a $J
  fi
  prevF=$F
done
