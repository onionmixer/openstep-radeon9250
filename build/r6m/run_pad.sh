#!/bin/bash
# Task #30, the ring's PADDING branch alone.  The first R6m sequence of boot 00ef86d4 ran without
# its F control (a sequencing error), which put every submission 112 words earlier and made the last
# one land on 4000 instead of wrapping.  This is a SECOND CP sequence in the same boot: a fresh
# load/map/reset/start puts the write pointer back at 16, and the submissions are chosen (the
# arithmetic of build/r6m/design2.py) so that the fourth does not fit before the ring end --
#   BA 16->704, BB ->2000, BB ->3296, BB: the draw wants 1264 with 768 left, so it pads 768 words,
#   restarts at 0 and leaves the pointer at 1264.
# Stops at the first non-zero kernel rc.
# usage: run_pad.sh <boot nonce>
N=$1
case "$N" in [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;; *) echo "usage: run_pad.sh <boot nonce>"; exit 2 ;; esac
B=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250/build/r6m/r5op.sh
G=/mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER
check() {   # the last $1 operation lines of this boot must all be rc=0
    L=$(cd $G && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "grep 'boot=$N n=' /usr/adm/messages | tail -$1")
    echo "$L" | sed 's/.*mach: //' | awk '{print $2, $4, $6, $7}' | tr '\n' ';'; echo
    if [ "$(echo "$L" | grep -c "boot=$N n=")" != "$1" ]; then echo "STOP: $1 lines wanted"; exit 1; fi
    if echo "$L" | grep -v ' rc=0 ' | grep -q "boot=$N n="; then echo "STOP: a non-zero rc"; exit 1; fi
}
while read kind a rest; do
    case "$kind" in \#*) continue ;; esac
    bash $B zprep >/dev/null 2>&1
    bash $B zclear $a >/dev/null 2>&1
    n=2
    for k in $rest; do bash $B plane $k >/dev/null 2>&1; n=$((n+1)); done
    echo "case $a"; check $n
done < /mnt/USERS/onion/DATA_ORIGN/Workspace/NeXT_DRIVER/openstep-radeon9250/build/r6m/plan_pad.txt
echo ALL-DONE
