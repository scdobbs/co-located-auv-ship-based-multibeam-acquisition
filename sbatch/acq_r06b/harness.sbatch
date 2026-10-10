#!/bin/bash
#SBATCH --job-name=acq_r06b_harn
#SBATCH --partition=serc,normal
#SBATCH --time=2:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r06b_harn_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r06b_harn_%j.err
# ACQ-R06b B2-B4 harness: fetch rehearsal (EW9801 -> scratch), prior-value rehearsal (RR1506 relabelled), write-path rehearsal (FK151121 copy).
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
source sbatch/acq_r04/stage_sandbox.sh
echo "host=$(hostname) commit=$(git rev-parse --short HEAD)"
/usr/bin/time -v /home/users/scdobbs/bathy_diffusion_env/bin/python -m src.phase4.harness_r06b; echo "harness exit=$?"
