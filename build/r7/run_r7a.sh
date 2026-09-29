#!/bin/bash
# R7a (docs/R7_PLAN.md 5): the client's own streams.  Each "stage" line stages a stream with
# rdnr7sub (no hardware; it copies words into the driver's buffer) and each "case" line draws it
# with a ZCLEAR of case 171, which goes through the mode claim like every other case.
# Stops at the first non-zero kernel rc.  usage: run_r7a.sh <boot nonce>
N=$1
case "$N" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;; *) echo "usage: run_r7a.sh <boot nonce>"; exit 2 ;; esac
P=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250
B=$P/build/r7/r5op.sh
G=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER
BUILDDIR=/ndrv/openstep-radeon9250/build/r2b0/789994908
KEY=4398697d
check() {   # R7a: most streams are SUPPOSED to be refused, so the runner accepts rc=0 and the
            # verifier's own refusal (rc=1 why=34 = CP_WHY_R7) and stops on anything else.  WHICH
            # rule fired is the judge's business, not the runner's -- it reads gv= from these lines.
    L=$(cd $G && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "grep 'boot=$N n=' /usr/adm/messages | tail -$1")
    echo "$L" | sed 's/.*mach: //' | awk '{print $2, $4, $6, $7, $8}' | tr '\n' ';'; echo
    if [ "$(echo "$L" | grep -c "boot=$N n=")" != "$1" ]; then echo "STOP: $1 lines wanted"; exit 1; fi
    if echo "$L" | grep "boot=$N n=" | grep -v ' rc=0 ' | grep -v ' rc=1 why=34 ' > /dev/null; then
        echo "STOP: an rc that is neither 0 nor the verifier's refusal"; exit 1
    fi
}
stage() {   # $1 = case, $2 = pieces (optional)
    R=$(python3 -c "import time;print(int(time.time())-1000000000)")
    O=$(cd $G && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "sync; $BUILDDIR/rdnr7sub $R $KEY $1 $2 > $BUILDDIR/r7-$R.out 2>&1; echo rc=\$? >> $BUILDDIR/r7-$R.out; sync; sleep 1; cat $BUILDDIR/r7-$R.out")
    echo "$O" | sed 's/.*mach: //' | tail -2
    case "$O" in *"RDNR7 exit=0"*) ;; *) echo "STOP: staging refused"; exit 1 ;; esac
}
SKIP=${SKIP:-0}
DONE=0
while read kind a b rest; do
    case "$kind" in \#*|"") continue ;; esac
    case "$kind" in case) DONE=$((DONE+1)) ;; esac
    if [ "$DONE" -le "$SKIP" ]; then continue; fi
    case "$kind" in
        stage) echo "stage $a ${b:-1}"; stage "$a" "${b:-1}" ;;
        case)  bash $B zprep >/dev/null 2>&1
               bash $B zclear "$a" >/dev/null 2>&1
               echo "case $a"; check 2 ;;
    esac
done < $P/build/r7/plan_ops.txt
echo ALL-DONE
