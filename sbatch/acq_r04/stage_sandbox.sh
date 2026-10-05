# ACQ-R04 (2026-10-05): stage the MB-System sandbox to node-local disk (Sherlock storage rule: no intensive I/O on
# $GROUP_HOME).  One tarball read from $GROUP_SCRATCH per job; sha256 verified; bind mount points added.
T=/scratch/groups/hilley/auv_ship_colocated_bathy/containers/mbsystem_sandbox.tar
want=$(cut -d' ' -f1 $T.sha256)
cp $T $L_SCRATCH_JOB/ && got=$(sha256sum $L_SCRATCH_JOB/mbsystem_sandbox.tar | cut -d' ' -f1)
if [ "$got" != "$want" ]; then echo "SANDBOX STAGING FAILED: sha256 $got != $want"; exit 2; fi
tar -C $L_SCRATCH_JOB -xf $L_SCRATCH_JOB/mbsystem_sandbox.tar && rm -f $L_SCRATCH_JOB/mbsystem_sandbox.tar
for d in scratch oak lscratch home/groups home/users; do mkdir -p $L_SCRATCH_JOB/mbsystem_sandbox/$d; done
export ACQ_MB_SANDBOX=$L_SCRATCH_JOB/mbsystem_sandbox
echo "sandbox staged: $ACQ_MB_SANDBOX (tar sha256 $want)"
