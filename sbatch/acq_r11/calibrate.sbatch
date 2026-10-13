#!/bin/bash
#SBATCH --job-name=acq_r11_cal
#SBATCH --partition=serc,normal
#SBATCH --time=3:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r11_cal_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r11_cal_%j.err
# ACQ-R11 §2 — vertical-consistency calibration on development and known-bad pairs (read only).
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
echo "host=$(hostname) commit=$(git rev-parse --short HEAD) vcheck_sha256=$(sha256sum src/phase5/vcheck_p5.py | cut -d' ' -f1)"
/usr/bin/time -v /home/users/scdobbs/bathy_diffusion_env/bin/python -B -m src.acq_r11.calibrate_vcheck; echo "calibrate exit=$?"
