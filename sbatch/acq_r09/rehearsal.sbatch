#!/bin/bash
#SBATCH --job-name=acq_r09_reh
#SBATCH --partition=serc,normal
#SBATCH --time=6:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r09_reh_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r09_reh_%j.err
# ACQ-R09 §3.2 — Phase 5 step 1 in rehearsal mode on the mock layout (development data, scratch, no network).
# Usage: sbatch sbatch/acq_r09/rehearsal.sbatch <run-tag> [extra args, e.g. --sites MGDS:31289 | --freeze-record <json>]
set -uo pipefail
TAG=${1:?run tag}; shift
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
source sbatch/acq_r04/stage_sandbox.sh
export L_SCRATCH=${L_SCRATCH_JOB:-$L_SCRATCH}
echo "host=$(hostname) commit=$(git rev-parse --short HEAD) tag=$TAG args=$*"
/usr/bin/time -v /home/users/scdobbs/bathy_diffusion_env/bin/python -B -m src.phase5.sealed_step1_p5 --mode rehearsal --run-tag "$TAG" --nproc 6 "$@"; echo "rehearsal exit=$?"
