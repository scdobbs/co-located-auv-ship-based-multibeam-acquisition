#!/bin/bash
#SBATCH --job-name=auv_mbsys2
#SBATCH --partition=normal
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/sbatch_%j.err

# Track M (pivot) — MB-System has NO conda-forge package; use the official
# mbari/mbsystem Docker image via Apptainer (Singularity) instead.
set -uo pipefail

GH=/home/groups/hilley
SIF=$GH/containers/mbsystem.sif
SANDBOX=$GH/containers/mbsystem_sandbox
mkdir -p "$GH/containers"
# mksquashfs segfaults (exit 139) when TMPDIR is the small node /tmp tmpfs;
# point both cache and tmp at the roomy node-local SSD.
export APPTAINER_CACHEDIR=$L_SCRATCH/apptainer_cache
export APPTAINER_TMPDIR=$L_SCRATCH/apptainer_tmp
mkdir -p "$APPTAINER_CACHEDIR" "$APPTAINER_TMPDIR"
BIND="--bind /scratch,/home/groups,/oak"
RUN=""   # set to the runnable image (sif or sandbox)

echo "=== M1: pull mbari/mbsystem image (SIF) ==="
if [ -f "$SIF" ]; then
  RUN=$SIF
else
  apptainer pull "$SIF" docker://mbari/mbsystem:latest && RUN=$SIF
fi
if [ -z "$RUN" ]; then
  echo "SIF pull failed (mksquashfs?); falling back to --sandbox build"
  rm -rf "$SANDBOX"
  apptainer build --sandbox "$SANDBOX" docker://mbari/mbsystem:latest \
    && RUN=$SANDBOX
fi
if [ -z "$RUN" ]; then echo "APPTAINER_PULL_FAILED"; exit 5; fi
echo "RUN=$RUN"; ls -ld "$RUN"
SIF=$RUN   # downstream exec uses $SIF

echo "=== M2a: mbinfo --version ==="
apptainer exec $BIND "$SIF" mbinfo --version 2>&1 | head -6 || { echo "MBINFO_VERSION_FAILED"; exit 4; }

echo "=== M2b: mbinfo on a real complete file (Channel .all, format 56) ==="
RAW=/scratch/groups/hilley/auv_ship_colocated_bathy/raw_lr
SRC=$(ls "$RAW"/Channel/*.all.gz 2>/dev/null | head -1)
WORK=$L_SCRATCH/$(basename "${SRC%.gz}")
gunzip -c "$SRC" > "$WORK"
echo "test file: $WORK ($(du -h "$WORK" | cut -f1))"
apptainer exec $BIND "$SIF" mbinfo -F56 -I "$WORK" 2>&1 | grep -iE "Number of Records|Total Number of|Minimum Longitude|Minimum Depth|Maximum Depth|format" | head -20
echo "MBSYSTEM_APPTAINER_OK"
echo "INVOCATION: apptainer exec --bind /scratch,/home/groups,/oak $SIF mbinfo -F<fmt> -I <file>"
