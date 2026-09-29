#!/bin/bash
#SBATCH --job-name=acq_r01_fetch
#SBATCH --partition=normal
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r01_fetch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r01_fetch_%j.err
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
CRUISES="${ACQ_CRUISES:-RR1506,AT37-13,TN399,EW9801,FK181031,NA090,NA076,NA080,AR26,TN299,EW0207,2009_Amundsen}"
echo "host=$(hostname) job=$SLURM_JOB_ID cruises=$CRUISES"
$PY -m src.acq_r01.fetch_swath --cruises "$CRUISES" --workers 6
echo "exit=$?"
