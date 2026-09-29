#!/bin/bash
# run_g52_off.sh -- G5-2 gates G1-G3 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 6), offscreen: no gcdsd of the user's.
#   bash build/g52/run_g52_off.sh        (after the reboot into the G5-2 driver; CP started by the usual runner)
#
#   G1  fill the window with one colour -> replay the recorded world stream ONCE by SUBMIT2 -> dump
#   G2  fill again -> the same stream ONCE by SUBMIT3, then RETIRE -> dump.  Gate: byte-identical to G1
#       and different from the fill (something was drawn) -- the picture decides, not a counter
#   G3  the stream 20 times by SUBMIT3 with no RETIRE between, one at the end; then tdump:
#       asubmits moved by 21, lost 0, no latch, the RETIRE waited
set -u
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; T=$N/build/g52; L=$P/build/g52; OP=$P/build/r7b/r5op.sh
FILL=00204060; WORDS=4057; MAJ=38   # depth filled with 0: the recorded world stream tests GEQUAL (G4-11)
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf timeout 590 ./bin/gcds next "$1") 2>&1 | sed 's/.*mach: //'; }
op() { bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1; }
S=$(python3 -c "import time;print(int(time.time())-1000000000)")
echo "run $S $(date +%T)"
echo "== before: the kernel's async line";  op tdump >/dev/null
mach "wc -l < /usr/adm/messages > /tmp/g52-OFF.mark; grep 'RDN-R5 async' /usr/adm/messages | tail -1" | tee "$L/off-before.txt"
for arm in sync async; do
    S=$((S + 1)); extra=""; [ $arm = async ] && extra="async=1"
    echo "== G$([ $arm = sync ] && echo 1 || echo 2): fill $FILL, replay x1 $arm (runid $S)"
    mach "$N/build/g48/rdndump fill $FILL 640 480 0000 | tail -1; $N/build/g48/rdnreplay $S $MAJ $T/real-stream.bin words=$WORDS reps=1 $extra | tail -2; $N/build/g48/rdndump $T/$arm-colour.raw $T/$arm-depth.raw 640 480 | tail -1; sync" | tee "$L/off-$arm.log"
done
S=$((S + 1))
echo "== G3: x20 accepted, one RETIRE (runid $S)"
mach "$N/build/g48/rdnreplay $S $MAJ $T/real-stream.bin words=$WORDS reps=20 async=1 | tail -2; sync" | tee "$L/off-g3.log"
op tdump >/dev/null
mach "grep 'RDN-R5 async' /usr/adm/messages | tail -1; sed -n \"\`expr \\\`cat /tmp/g52-OFF.mark\\\` + 1\`,\\\$p\" /usr/adm/messages | grep -c 'RDN-R5 latch'" | tee "$L/off-after.txt"
python3 "$P/build/g52/judge_g52.py" off "$L"
