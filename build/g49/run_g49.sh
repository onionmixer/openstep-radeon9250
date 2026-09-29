#!/bin/bash
# G4-9 (docs/G4_8_REPLAY_PLAN.md 11): read PP_TRI_PERF/PP_PERF_CNTL before the CP, after START, and after one
# prefix; NO STOP -- the CP stays up for the GLQuake run that follows in this boot.
# The operation list is build/g49/plan_ops.txt, which check_plan_ops.py compares with check_r6a.ORDERS['g49'].
#   bash build/g49/run_g49.sh
# The boot nonce is only logged by the first CP operation (RDN-R2B0 state boot=...), so the runner reads it
# after its own first "record" -- which is also the procedure's first operation.
N=
P=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250
B=$P/build/r7b/r5op.sh
G=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER
L=$P/build/g49
mach() { (cd $G && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "$1"); }
op() {   # one operation; its RDN-R5 line for this boot must say rc=0
    bash $B $1 $2 > $L/op-$1$2.out 2>&1
    if [ -z "$N" ]; then
        N=$(mach "grep 'RDN-R2B0 state boot=' /usr/adm/messages | tail -1" | sed 's/.*boot=\([0-9a-f]*\).*/\1/')
        echo "boot nonce $N, driver $(mach "grep 'RDN-R2B0 state boot=' /usr/adm/messages | tail -1" | sed 's/.*build=\([0-9a-f]*\).*/\1/')"
        case "$N" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;; *) echo "STOP: no boot nonce"; exit 1 ;; esac
    fi
    line=$(mach "grep 'boot=$N n=' /usr/adm/messages | tail -1" | sed 's/.*mach: //')
    echo "$1 $2: $line" | cut -c1-110
    case "$line" in *" rc=0 "*) ;; *) echo "STOP: $1 did not say rc=0"; exit 1 ;; esac
}
tri() {  # the last REC3D's TAM_DEBUG3
    mach "grep 'RDN-R6 r3 ' /usr/adm/messages | grep 2d9c= | tail -1" | sed 's/.*mach: //' | tr ' ' '\n' | grep '^2d9c=\|^2cf8=' | tr '\n' ' '; echo " ($1)"
}
for o in record rec3d; do op $o; done; tri "boot value, before LOAD"
for o in load map reset start rec3d; do op $o; done; tri "after START"
op zprep; op zclear 1
mach "grep 'RDN-R6 zclear case=1' /usr/adm/messages | tail -1; grep 'RDN-R6 zpre' /usr/adm/messages | tail -1" | sed 's/.*mach: //'
op rec3d; tri "after the first prefix"
op record
mach "cat /usr/adm/messages" > $L/messages-$N.txt
echo "judge: python3 tools/r6/check_r6a.py build/g49/messages-$N.txt --boot $N --build <stamp> --procedure g49"
echo ALL-DONE
