#!/bin/bash
# R7b (docs/R7_PLAN.md 10-9): the same sixteen streams as R7a, through the CHARACTER DEVICE.
# The operation list comes from build/r7b/plan_ops.txt and nowhere else -- tools/r6/check_plan_ops.py
# has already compared that file with the judge's procedure, which is what a boot costs when the
# two drift (the R6m lesson, boot 00ef86d4).
#
# Each "case 171" line is one rdnr7dev run: CAPS, mmap, fill, SUBMIT -- and the SUBMIT performs the
# ZCLEAR.  "case 6" is the F control and goes through rdnr5cp like every other rung's.
# Stops at the first kernel rc that is neither 0 nor the verifier's own refusal.
#
# It runs the WHOLE procedure: gates C and E first (they are refused before any CP
# operation happens, so everything after them is the evidence they changed nothing),
# then the preamble, the plan's cases, and the tail.
#   C  a second open while one is held
#   E  nwords 0, nwords over the limit, and an unknown command
#
# usage: run_r7b.sh <boot nonce>       (SKIP=n resumes after n case lines)
N=$1
case "$N" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
  *) echo "usage: run_r7b.sh <boot nonce>"; exit 2 ;; esac
P=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250
G=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER
B=$P/build/r7b/r5op.sh
BUILDDIR=${BUILDDIR:-/ndrv/openstep-radeon9250/build/r2b0/790003982}
MAJOR=${MAJOR:-38}

# the last $1 operation lines of this boot: most streams are SUPPOSED to be refused, so
# rc=1 why=34 (CP_WHY_R7) is as acceptable as rc=0 and anything else stops the run
check() {
    L=$(cd $G && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "grep 'boot=$N n=' /usr/adm/messages | tail -$1")
    echo "$L" | sed 's/.*mach: //' | awk '{print $2, $4, $6, $7, $8}' | tr '\n' ';'; echo
    if [ "$(echo "$L" | grep -c "boot=$N n=")" != "$1" ]; then echo "STOP: $1 lines wanted"; exit 1; fi
    if echo "$L" | grep "boot=$N n=" | grep -v ' rc=0 ' | grep -v ' rc=1 why=34 ' > /dev/null; then
        echo "STOP: an rc that is neither 0 nor the verifier's refusal"; exit 1
    fi
}

# The run id is the SEED the kernel gets, and it refuses a repeat (CP_WHY_SEED),
# so it must strictly increase rather than merely be "the time now": two calls in
# one second would collide.  A base plus a counter gives both.
SEEDBASE=$(python3 -c "import time;print(int(time.time())-1000000000)")
SEEDN=0
# +100000 keeps the client's seeds clear of r5op.sh's, which are the time itself:
# the two streams could otherwise cross and a zprep would hand the next zclear its
# own seed (28 hours of running before they could meet -- build/r7b/run_r7b.sh note).
nextseed() { SEEDN=$((SEEDN+1)); R=$((SEEDBASE+100000+SEEDN)); }

# one client run; $1 = case, $2.. = extra arguments for the gates
dev() {
    nextseed
    O=$(cd $G && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "sync; $BUILDDIR/rdnr7dev $R $MAJOR $* > $BUILDDIR/r7b-$R.out 2>&1; echo rc=\$? >> $BUILDDIR/r7b-$R.out; sync; sleep 1; cat $BUILDDIR/r7b-$R.out")
    echo "$O" | sed 's/.*mach: //' | grep 'RDNR7B\|^rc='
    LAST="$O"
}

# ---- the gates that never reach the CP, FIRST -------------------------------
# They go first on purpose: everything below is then the evidence that a refused
# open, a bad count and an unknown command changed nothing.  None of them performs
# a CP operation, which is why plan_ops.txt does not list them.
if [ "${SKIP:-0}" = "0" ]; then
    echo "== C a second open while one is held"; dev 0 hold
    echo "== E an unknown command";              dev 0 unknown
    echo "== E nwords 0";                        dev 0 n=0
    echo "== E nwords over the limit";           dev 0 n=2017
    echo GATES-DONE
fi

# ---- the preamble, which is PART OF THE PROCEDURE ---------------------------
# check_plan_ops.py expands plan_ops.txt to PRE + the cases + TAIL and compares
# that with the judge's ORDERS.  R7a's runner left PRE and TAIL to be typed by
# hand, which is the same gap in a different place: the run this script performs
# must BE the procedure that was checked, so it runs them.
if [ "${SKIP:-0}" = "0" ]; then
    for op in record rec3d load map reset start rec3d; do
        echo "-- preamble $op"
        bash $B $op >/dev/null 2>&1
        check 1
    done
fi

SKIP=${SKIP:-0}
DONE=0
K=0
while read kind a rest; do
    case "$kind" in \#*|"") continue ;; esac
    case "$kind" in case) ;; *) continue ;; esac
    DONE=$((DONE+1))
    if [ "$DONE" -le "$SKIP" ]; then
        case "$a" in 171) K=$((K+1)) ;; esac
        continue
    fi
    bash $B zprep >/dev/null 2>&1
    if [ "$a" = "171" ]; then
        echo "== client $K"
        dev $K
        case "$LAST" in *"step=submit n="*) ;; *) echo "STOP: the client never reached SUBMIT"; exit 1 ;; esac
        K=$((K+1))
    else
        echo "== case $a"
        bash $B zclear "$a" >/dev/null 2>&1
    fi
    check 2
done < $P/build/r7b/plan_ops.txt

# ---- the tail, likewise.  It runs only if nothing above stopped: STOP ends the
# CP's one LOAD..STOP cycle for this boot, so it must not happen on a half run.
for op in rec3d stop record; do
    echo "-- tail $op"
    bash $B $op >/dev/null 2>&1
    check 1
done
echo ALL-DONE
