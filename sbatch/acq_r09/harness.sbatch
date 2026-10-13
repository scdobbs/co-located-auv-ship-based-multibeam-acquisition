#!/bin/bash
#SBATCH --job-name=acq_r09_fk
#SBATCH --partition=serc,normal
#SBATCH --time=4:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r09_fk_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r09_fk_%j.err
# ACQ-R09 ruling S3 — FK151121 isolation harness (pre-4122090 region rule; rehearsal support only).
set -uo pipefail
TAG=${1:?run tag}
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
source sbatch/acq_r04/stage_sandbox.sh
export L_SCRATCH=${L_SCRATCH_JOB:-$L_SCRATCH}
echo "host=$(hostname) commit=$(git rev-parse --short HEAD) tag=$TAG"
/usr/bin/time -v /home/users/scdobbs/bathy_diffusion_env/bin/python -B -m src.phase5.harness_fk151121_p5 --run-tag "$TAG" --nproc 6; echo "harness exit=$?"
