#!/bin/bash
#SBATCH --job-name=acq_r02_snapshot
#SBATCH --partition=normal
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r02_snapshot_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r02_snapshot_%j.err
# ACQ-R02 §3 — corpus snapshot (non-lockbox harmonized + manifest + raw provider grids) and the
# lockbox byte-copy, both plain shell `tar` (no Python, no decoding).
set -uo pipefail
OAK=/oak/stanford/groups/hilley/auv_ship_colocated_bathy
SNAP=$OAK/snapshots; mkdir -p "$SNAP"
D=2026-09-30
cd "$OAK"
echo "host=$(hostname) job=$SLURM_JOB_ID start=$(date -Is)"
echo "=== corpus snapshot (excludes the two lockbox pair directories and raw swath) ==="
tar -cf "$SNAP/corpus_snapshot_$D.tar" --exclude='harmonized/AT42-03__MGDS_32007' --exclude='harmonized/TN159__MGDS_21981' harmonized manifest raw
echo "tar exit=$?"
tar -tvf "$SNAP/corpus_snapshot_$D.tar" > "$SNAP/corpus_snapshot_$D.filelist.txt"
( cd "$OAK" && find harmonized manifest raw -type f -not -path 'harmonized/AT42-03__MGDS_32007/*' -not -path 'harmonized/TN159__MGDS_21981/*' -print0 | sort -z | xargs -0 sha256sum ) > "$SNAP/corpus_snapshot_$D.SHA256SUMS"
sha256sum "$SNAP/corpus_snapshot_$D.tar" > "$SNAP/corpus_snapshot_$D.tar.sha256"
echo "=== lockbox byte copy (single tar command; nothing decoded) ==="
LCMD="tar -cf $SNAP/lockbox_snapshot_$D.tar -C $OAK harmonized/AT42-03__MGDS_32007 harmonized/TN159__MGDS_21981"
echo "LOCKBOX_CMD: $LCMD"
$LCMD
echo "lockbox tar exit=$?"
sha256sum "$SNAP/lockbox_snapshot_$D.tar" > "$SNAP/lockbox_snapshot_$D.tar.sha256"
ls -la "$SNAP"
cat "$SNAP"/*.sha256
chmod 0444 "$SNAP"/*
echo "end=$(date -Is)"
