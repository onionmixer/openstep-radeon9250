#!/bin/bash
# R6f cases after A and F (docs/R6F_PLAN.md 6): G1, K16a-d, K24a-d, I1-I7 (24), I1-I7 (16) -- each ZPREP, ZCLEAR,
# PLANE per (lane, chunk); stops at the first non-zero kernel rc.  usage: run_r6f.sh <boot nonce>
N=$1
case "$N" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;; *) echo "usage: run_r6f.sh <boot nonce>"; exit 2 ;; esac
B=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250/build/r6f/r5op.sh
G=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER
check() {   # the last $1 operation lines of this boot must all be rc=0
    L=$(cd $G && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "grep 'boot=$N n=' /usr/adm/messages | tail -$1")
    echo "$L" | sed 's/.*mach: //' | awk '{print $2, $4, $6, $7}' | tr '\n' ';'; echo
    if [ "$(echo "$L" | grep -c "boot=$N n=")" != "$1" ]; then echo "STOP: $1 lines wanted"; exit 1; fi
    if echo "$L" | grep -v ' rc=0 ' | grep -q "boot=$N n="; then echo "STOP: a non-zero rc"; exit 1; fi
}
while read kind a rest; do
    bash $B zprep >/dev/null 2>&1
    bash $B zclear $a >/dev/null 2>&1
    n=2
    for k in $rest; do bash $B plane $k >/dev/null 2>&1; n=$((n+1)); done
    echo "case $a"; check $n
done < /mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250/build/r6f/plan_ops.txt
echo ALL-DONE
