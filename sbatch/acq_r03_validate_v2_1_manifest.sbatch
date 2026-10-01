#!/bin/bash
#SBATCH --job-name=acq_r03_val21m
#SBATCH --partition=normal
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=24G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_val21_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r03_val21_%j.err
# ACQ-R03 §2.5-2.7: validate every pair against contract v2.1 (incl. Cal DIG unavailable) and write the flag table.
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
cd /home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
echo "host=$(hostname) commit=$(git rev-parse --short HEAD)"
$PY -m src.acq_r03.validate_contract_v2_1 --manifest manifest/pairs_v2_1.parquet --out contract_v2_1_validation_manifest_v2_1; echo "validate exit=$?"
$PY -m src.acq_r03.report_v2_1_table; echo "table exit=$?"
