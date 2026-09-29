#!/bin/bash
# the rest of the R6e procedure after G0's lane 0 (docs/R6E_PLAN.md 16); stops at the first non-zero kernel rc
B=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250/build/r6e/r5op.sh
G=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER
check() {   # the last $1 operation lines of this boot must all be rc=0
    L=$(cd $G && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "grep 'boot=ff63a8c4 n=' /usr/adm/messages | tail -$1")
    echo "$L" | sed 's/.*mach: //' | awk '{print $2, $4, $6, $7}' | tr '\n' ';'; echo
    if echo "$L" | grep -v ' rc=0 ' | grep -q 'boot=ff63a8c4 n='; then echo "STOP: a non-zero rc"; exit 1; fi
}
while read kind a rest; do
    if [ "$kind" = plane ]; then
        for k in $a $rest; do bash $B plane $k >/dev/null 2>&1; done
        check 12
    else
        bash $B zprep >/dev/null 2>&1
        bash $B zclear $a >/dev/null 2>&1
        n=2
        for k in $rest; do bash $B plane $k >/dev/null 2>&1; n=$((n+1)); done
        echo "case $a"; check $n
    fi
done < /mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250/build/r6e/plan_ops.txt
echo ALL-DONE
