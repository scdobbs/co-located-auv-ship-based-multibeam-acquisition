#!/bin/bash
#SBATCH --job-name=acq_r02_final
#SBATCH --partition=normal
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=96G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r02_final_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r02_final_%j.err
# ACQ-R02: Amundsen products-v2 re-run (OOM in the 48G harmonize job) -> H1 processed-grid cross-check
#          -> manifest v2 -> contract-v2 validation of the new development pairs -> manifest v2 -> acquisition tables
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) job=$SLURM_JOB_ID commit=$(git rev-parse --short HEAD)"
$PY -m src.acq_r01.products_v2_rerun --pair 2009_Amundsen__MGDS_30047 --cruise 2009_Amundsen --nproc 4 || echo "products rerun rc=$?"
$PY -m src.acq_r01.crosscheck_h1 || echo "crosscheck rc=$?"
$PY -m src.acq_r01.manifest_v2
NEW=$(cat reports_post_grl_review/ACQ-R02/new_dev_pairs.txt)
$PY -m src.acq_r01.validate_contract_v2 --manifest manifest/pairs_v2.parquet --pairs "$NEW" --out contract_v2_validation_new || echo "validate rc=$?"
$PY -m src.acq_r01.manifest_v2
$PY -m src.acq_r01.report_acq_table > /dev/null
echo "exit=0"
