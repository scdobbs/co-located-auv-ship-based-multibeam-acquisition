#!/bin/bash
#SBATCH --job-name=diag_nr07
#SBATCH --partition=normal
#SBATCH --time=00:40:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=24G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/diag_nr07_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/diag_nr07_%j.err
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PYTHONPATH=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition /home/users/scdobbs/bathy_diffusion_env/bin/python scripts_diag/nr07_diag.py
