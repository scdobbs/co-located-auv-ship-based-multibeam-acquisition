#!/bin/bash
#SBATCH --job-name=acq_r12_reh
#SBATCH --partition=serc,normal
#SBATCH --time=8:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r12_reh_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r12_reh_%j.err
# ACQ-R12 §4 — rehearsals on development data only (scratch; NCEI fetch of the development cruise NA080 only).
#   pre   <tag>: mock layouts; rehearsal-mode run (its loaded modules feed the freeze); candidate freeze; phase5_mock A/B/C
#   final <tag>: mock layouts rebuilt (pre outputs moved aside); rehearsal against freeze v3 + FK151121 harness + compare;
#                phase5_mock A/B/C against freeze v3; compares; CNN lock copy; refusal suite; blindness test
# phase5_mock sequence: A = NA080 fetched + KM0923's sealed dir hidden -> stop after site 1 (resume test);
#                       B = resume with a planted G value in a mock log -> NA080 re-used, KM0923 computed, leak check stops;
#                       C = resume, clean -> complete (both sites re-used).
set -uo pipefail
STAGE=${1:?pre|final}; TAG=${2:?tag}
module load python/3.12.1 openblas/0.3.28
ACQ=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
cd $ACQ
source sbatch/acq_r04/stage_sandbox.sh
export L_SCRATCH=${L_SCRATCH_JOB:-$L_SCRATCH}
PY="/home/users/scdobbs/bathy_diffusion_env/bin/python -B"
R=$ACQ/reports_post_grl_review/ACQ-R12; RH=$R/rehearsal; S=/scratch/groups/hilley/auv_ship_colocated_bathy/ACQ-R12
MOCKIN=$RH/phase5_mock_inputs
echo "host=$(hostname) job=$SLURM_JOB_ID commit=$(git rev-parse --short HEAD) stage=$STAGE tag=$TAG start=$(date -u +%FT%TZ)"
if [ "$STAGE" = pre ]; then
  FR=$R/freeze_record_phase5_candidate.json
else
  FR=$ACQ/reports_post_grl_review/PHASE5/freeze_record_phase5_v3.json
  # move the pre-stage phase5_mock records aside; clear its scratch outputs, the NA080 fetch and the listing cache
  mkdir -p $RH/phase5_mock_pre; for f in $RH/phase5_mock/*; do [ -e "$f" ] && mv "$f" $RH/phase5_mock_pre/; done
  chmod -R u+w $S/phase5_mock $S/raw_lr_swath/NA080 $S/fetch_cache 2>/dev/null; rm -rf $S/phase5_mock $S/raw_lr_swath/NA080 $S/fetch_cache
fi
$PY -m src.phase5.mock_p5 || exit 2
$PY -m src.phase5.mock_p5 --phase5-mock || exit 2
# --- rehearsal mode (ACQ-R11b set: NA080, KM0923, mock repeat, NR07-1; FK151121 harness) ---
if [ "$STAGE" = pre ]; then
  /usr/bin/time -v $PY -m src.phase5.sealed_step1_p5 --mode rehearsal --run-tag "${TAG}_reh" --nproc 6; echo "rehearsal exit=$?"
  $PY -m src.phase5.freeze_p5 --run-record $RH/step1_run_rehearsal_${TAG}_reh.json --candidate; echo "candidate freeze exit=$?"
else
  /usr/bin/time -v $PY -m src.phase5.sealed_step1_p5 --mode rehearsal --run-tag "${TAG}_reh" --nproc 6 --freeze-record $FR; echo "rehearsal exit=$?"
  $PY -m src.phase5.harness_fk151121_p5 --run-tag "${TAG}" --nproc 6; echo "harness exit=$?"
  $PY -m src.phase5.compare_p5 --run-record $RH/step1_run_rehearsal_${TAG}_reh.json; echo "compare exit=$?"
fi
# --- phase5_mock: the phase5 branch, fetch on, mock inputs ---
SIGN=$MOCKIN/SIGNOFF_phase5_mock.md; PRE=$(sha256sum $MOCKIN/PREREG_phase5_mock.md | cut -d' ' -f1)
M="--mode phase5_mock --signoff $SIGN --prereg-sha256 $PRE --freeze-record $FR --nproc 6"
mv $S/mock5/sealed_candidates_v3/MGDS_31429 $S/mock5/hidden_MGDS_31429
$PY -m src.phase5.pathlog_p5 --out $RH/pathlog_${TAG}_A.jsonl.gz -- $M; echo "phase5_mock A exit=$? (expected: stopped after site 1)"
mv $S/mock5/hidden_MGDS_31429 $S/mock5/sealed_candidates_v3/MGDS_31429
PLANT=$L_SCRATCH/planted_mock.log
$PY - "$PLANT" <<'EOF'
import sys
from src.phase5 import common_p5 as P, vcheck_p5 as VC
d = P.MOCK5_OUT / "harmonized" / "NA080__MGDS_31289"
s = VC.statistic(d / "hr.tif", d / "lr.tif", d / "joint_valid.tif")
open(sys.argv[1], "w").write(f"mock log line (planted by the ACQ-R12 test): G {s['v95_rel']:.6g}\n")
print("planted a G value of NA080__MGDS_31289 into", sys.argv[1], "(value not printed)")
EOF
$PY -m src.phase5.pathlog_p5 --out $RH/pathlog_${TAG}_B.jsonl.gz -- $M --scan-logs $PLANT; echo "phase5_mock B exit=$? (expected: stopped, leak check)"
rm -f $PLANT
$PY -m src.phase5.pathlog_p5 --out $RH/pathlog_${TAG}_C.jsonl.gz -- $M; echo "phase5_mock C exit=$? (expected: complete)"
C_REC=$(ls -t $RH/phase5_mock/step1_run_phase5_mock_*.json | head -1)
$PY -m src.phase5.compare_p5 --run-record $C_REC --pairs NA080__MGDS_31289,KM0923__MGDS_31429 --out $RH/compare_${TAG}_phase5_mock.json; echo "compare mock exit=$?"
$PY - <<'EOF'
import json
from pathlib import Path
from src.phase5 import common_p5 as P
a, b = P.MOCK5_SWATH / "NA080", Path("/oak/stanford/groups/hilley/auv_ship_colocated_bathy/raw_lr_swath/NA080")
sa = dict(l.split("  ")[::-1] for l in (a / "SHA256SUMS").read_text().split("\n") if l.strip())
sb = dict(l.split("  ")[::-1] for l in (b / "SHA256SUMS").read_text().split("\n") if l.strip())
ma = json.loads((a / "fetch_manifest.json").read_text())
res = {"fetched_dir": str(a), "development_dir": str(b), "n_fetched": len(sa), "n_development": len(sb), "same_names": sorted(sa) == sorted(sb),
       "n_sha_equal": sum(sa.get(k) == v for k, v in sb.items()), "bytes_ok": ma.get("bytes_ok"), "n_files_ok": ma.get("n_files_ok"), "n_failed": ma.get("n_files_failed")}
res["identical"] = res["same_names"] and res["n_sha_equal"] == len(sb)
P.write_json(P.REHEARSAL_DIR / "swath_compare_na080.json", res, mode=0o644); print("swath compare:", res)
EOF
if [ "$STAGE" = final ]; then
  $PY -m src.phase5.cnn_lock_check_p5 --run-record $RH/step1_run_rehearsal_${TAG}_reh.json --freeze-record $FR; echo "cnn lock (rehearsal) exit=$?"
  $PY -m src.phase5.cnn_lock_check_p5 --run-record $C_REC --freeze-record $FR; echo "cnn lock (phase5_mock) exit=$?"
  $PY -m src.phase5.refusal_tests_p5; echo "refusal exit=$?"
  $PY -m src.phase5.blind_test_p5 --run-record $RH/step1_run_rehearsal_${TAG}_reh.json --logs logs/acq_r12_reh_${SLURM_JOB_ID}.out,logs/acq_r12_reh_${SLURM_JOB_ID}.err; echo "blind exit=$?"
fi
echo "end=$(date -u +%FT%TZ)"
