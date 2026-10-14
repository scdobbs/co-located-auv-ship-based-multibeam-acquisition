#!/bin/bash
#SBATCH --job-name=acq_r10_p5
#SBATCH --partition=serc,normal
#SBATCH --time=48:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r10_p5_%j.out
#SBATCH --error=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition/logs/acq_r10_p5_%j.err
# ACQ-R10 §2 (re-issued by ACQ-R12 §6.4; earlier by ACQ-R11b §5.4) against PHASE5/freeze_record_phase5_v3.json, tag phase5-acq-freeze-v3): the frozen Phase 5 step 1 (src/phase5/sealed_step1_p5.py --mode phase5), run ONCE, unchanged.
# Resources (ACQ-R12 §5): phase5_mock fetch-on rehearsal 0.47 GB fetched in 16.5 s, NA080 site 272 s, KM0923 site 92 s, peak RSS 10.2 GB; scaled for 8 sites with the swath
# fetch (~61 GB; MV1003 subset ~37 GB, gunzipped to node-local disk by grid_lr.prepare) and the v2.1 product builder.
# Preconditions 1-4 re-checked here (read only); any failure exits before the step.
set -uo pipefail
module load python/3.12.1 openblas/0.3.28
ACQ=/home/users/scdobbs/co-located-auv-ship-based-multibeam-acquisition
CNN=/home/users/scdobbs/GAN_Bathymetry_Project
R16=grl_reviews-and-prompt-reports/directives_and_reports/R16c
SIGNOFF=$CNN/$R16/SIGNOFF_phase5_prereg_v3_1.md
PREREG=75b72eb6fae3804c7dea61aa4171744a2fcd4fbdb7c3916f3fb98f2c06f2c7b6
FREEZE_SHA=42cb8ebb65d104694c935b71627dd9f884b99a14c9474c02f87a7cc853daa85b
PY=/home/users/scdobbs/bathy_diffusion_env/bin/python
cd $ACQ
echo "host=$(hostname) job=$SLURM_JOB_ID commit=$(git rev-parse HEAD) freeze_tag=$(git rev-parse phase5-acq-freeze-v3^{commit}) start=$(date -u +%FT%TZ)"
grep -m1 "model name" /proc/cpuinfo
# §1.1 pre-registration = tag copy; sign-off committed and its first sha256 = v3.1
[ "$(sha256sum $CNN/$R16/PREREG_phase5_v3_1.md | cut -d' ' -f1)" = "$PREREG" ] || { echo "PRECONDITION 1 FAILED: PREREG hash"; exit 3; }
[ "$(cd $CNN && git show phase5-prereg-v3.1:$R16/PREREG_phase5_v3_1.md | sha256sum | cut -d' ' -f1)" = "$PREREG" ] || { echo "PRECONDITION 1 FAILED: tag copy"; exit 3; }
(cd $CNN && git ls-files --error-unmatch $R16/SIGNOFF_phase5_prereg_v3_1.md >/dev/null 2>&1 && git diff --quiet HEAD -- $R16/SIGNOFF_phase5_prereg_v3_1.md) || { echo "PRECONDITION 1 FAILED: sign-off not committed"; exit 3; }
[ "$(grep -o -m1 -E '[0-9a-f]{64}' $SIGNOFF | head -1)" = "$PREREG" ] || { echo "PRECONDITION 1 FAILED: sign-off first sha256"; exit 3; }
echo "signoff_commit=$(cd $CNN && git log -1 --format=%H -- $R16/SIGNOFF_phase5_prereg_v3_1.md) signoff_sha256=$(sha256sum $SIGNOFF | cut -d' ' -f1)"
# §1.2 freeze record hash; src/phase5 clean and equal to the tag (the step's lock 2 checks every listed file)
[ "$(sha256sum reports_post_grl_review/PHASE5/freeze_record_phase5_v3.json | cut -d' ' -f1)" = "$FREEZE_SHA" ] || { echo "PRECONDITION 2 FAILED: freeze record hash"; exit 3; }
git diff --quiet phase5-acq-freeze-v3 -- src/phase5 && [ -z "$(git status --porcelain src/phase5)" ] || { echo "PRECONDITION 2 FAILED: src/phase5 differs from phase5-acq-freeze-v3"; exit 3; }
# §1.4 no phase5 supplement, no phase5 run record
[ ! -e manifest/pairs_phase5_sealed.parquet ] && ! ls reports_post_grl_review/PHASE5/step1_run_phase5_*.json >/dev/null 2>&1 || { echo "PRECONDITION 4 FAILED: supplement or phase5 run record exists"; exit 3; }
source sbatch/acq_r04/stage_sandbox.sh
export L_SCRATCH=${L_SCRATCH_JOB:-$L_SCRATCH}
df -h "$L_SCRATCH" | tail -1
# §1.3 guard self-test before any other step: Phase 4 reader probes + Phase 5 admission on the real names, and the
# Phase 5 output / work roots probed with every site's pair path while no allowance is installed (must be blocked).
$PY -B - <<'EOF' || { echo "PRECONDITION 3 FAILED: guard self-test"; exit 4; }
import json, os, sys
from pathlib import Path
from src.acq_r01 import common as C
from src.phase4 import guard_selftest as G4
from src.phase5 import common_p5 as P, guard_p5 as GP
sites = P.read_site_list(P.SITE_LIST)
out_root = C.OAK / "phase5"; work_root = Path(os.environ["L_SCRATCH"]) / "acq_p5" / "phase5"
g4 = G4.run(write=False)
g5 = GP.selftest([s["token"] for s in sites], [], out_root, work_root, decoy_mock=None)
readers = GP._readers(); roots = []
for s in sites:
    for p in (out_root / "harmonized" / s["pair_id"] / "hr.tif", out_root / "harmonized" / ".staging" / s["pair_id"] / "lr.tif",
              out_root / "raw_lr_gridded" / s["pair_id"] / "x.grd", work_root / s["pair_id"] / "tile0.tif", C.SEALED_CANDIDATES_V3 / s["token"]):
        for rn, fn in readers.items():
            roots.append({"path": str(p), "reader": rn, "result": GP._probe(fn, p)})
roots_ok = all(r["result"] == "blocked" for r in roots)
n = g4["reader_checks"]["n"] + g5["reader_checks"]["n"] + len(roots)
nb = g4["reader_checks"]["n_blocked"] + g5["reader_checks"]["n_blocked"] + sum(r["result"] == "blocked" for r in roots)
ok = bool(g4["all_passed"] and g5["all_passed"] and roots_ok)
rec = {"directive": "ACQ-R10c (ACQ-R10 §1.3 guard self-test)", "phase4_reader_checks": {k: g4["reader_checks"][k] for k in ("n", "n_blocked")}, "phase4_all_passed": g4["all_passed"],
       "phase5_reader_checks": {k: v for k, v in g5["reader_checks"].items() if k != "rows"},
       "phase5_real_name_admission": {"n": len(g5["real_name_admission"]), "n_passed": sum(r["passed"] for r in g5["real_name_admission"])},
       "phase5_after_removal": g5["after_removal"], "phase5_all_passed": g5["all_passed"],
       "output_roots_sealed": {"n": len(roots), "n_blocked": sum(r["result"] == "blocked" for r in roots), "all_blocked": roots_ok, "rows": roots},
       "total_probes": n, "total_blocked_or_passed": nb, "all_passed": ok, "guard_file_sha256": g5["guard_file_sha256"]}
Path("reports_post_grl_review/ACQ-R10c").mkdir(exist_ok=True)
Path("reports_post_grl_review/ACQ-R10c/guard_selftest_r10c.json").write_text(json.dumps(rec, indent=1, default=str))
print("guard self-test: phase4 %d/%d blocked; phase5 readers %d/%d blocked; real-name admission %d/%d; output roots %d/%d blocked; all_passed %s"
      % (g4["reader_checks"]["n_blocked"], g4["reader_checks"]["n"], g5["reader_checks"]["n_blocked"], g5["reader_checks"]["n"],
         rec["phase5_real_name_admission"]["n_passed"], rec["phase5_real_name_admission"]["n"], rec["output_roots_sealed"]["n_blocked"], len(roots), ok))
sys.exit(0 if ok else 4)
EOF
# §2 the run: exact command line; no --run-tag; --freeze-record at its default
echo "CMD: python -B -m src.phase5.sealed_step1_p5 --mode phase5 --signoff $SIGNOFF --prereg-sha256 $PREREG"
/usr/bin/time -v $PY -B -m src.phase5.sealed_step1_p5 --mode phase5 --signoff "$SIGNOFF" --prereg-sha256 "$PREREG"; rc=$?
echo "step1 exit=$rc end=$(date -u +%FT%TZ)"; exit $rc
