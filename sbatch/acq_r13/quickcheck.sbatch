#!/bin/bash
#SBATCH --job-name=acq_r13_qc
#SBATCH --partition=serc,normal
#SBATCH --time=1:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r13_qc_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r13_qc_%j.err
# ACQ-R13 §2 quick check (development pairs, read only; not a rehearsal)
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
/home/users/scdobbs/bathy_diffusion_env/bin/python -B -m src.acq_r13.quickcheck; echo "quickcheck exit=$?"
