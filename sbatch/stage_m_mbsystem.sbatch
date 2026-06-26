#!/bin/bash
#SBATCH --job-name=auv_mbsys
#SBATCH --partition=normal
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.err

# Track M — install MB-System via conda-forge (using micromamba for a reliable
# fast solve, since the system conda is 4.12 classic). Env lives on GROUP_HOME
# (persistent, backed up) per Sherlock policy (no conda envs in $HOME).
set -uo pipefail

GH=/home/groups/hilley
ENV_PREFIX=$GH/envs/mbsystem
MM=$GH/bin/micromamba
mkdir -p "$GH/bin" "$GH/envs"

echo "=== M1a: bootstrap micromamba ==="
if [ ! -x "$MM" ]; then
  cd "$GH/bin"
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba --strip-components=1
  chmod +x "$MM"
fi
"$MM" --version || { echo "MICROMAMBA_BOOTSTRAP_FAILED"; exit 3; }

echo "=== M1b: create env with mbsystem (conda-forge) ==="
export MAMBA_ROOT_PREFIX=$GH/micromamba_root
"$MM" create -y -p "$ENV_PREFIX" -c conda-forge mbsystem
rc=$?
if [ $rc -ne 0 ]; then echo "MBSYSTEM_INSTALL_FAILED rc=$rc"; exit $rc; fi

echo "=== M2: verify mbinfo ==="
"$ENV_PREFIX/bin/mbinfo" --version 2>&1 | head -5 || { echo "MBINFO_NOT_RUNNABLE"; exit 4; }
echo "ENV_PREFIX=$ENV_PREFIX"
echo "ACTIVATE: source $GH/bin/../etc/profile.d/conda.sh 2>/dev/null; export PATH=$ENV_PREFIX/bin:\$PATH"
echo "MBSYSTEM_INSTALL_OK"
