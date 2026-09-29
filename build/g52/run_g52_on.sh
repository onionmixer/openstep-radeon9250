#!/bin/bash
# run_g52_on.sh -- G5-2 gates G4-G7 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 6), ON SCREEN: the user's gcdsd must be up.
#   bash build/g52/run_g52_on.sh        (G5-2 driver booted, library built, GLQuake relinked, off gates PASS)
#
#   G4  +map start, 300 frames, RDNMesaSync=1 (the synchronous path in the same boot) -> g52-sync.log
#   G5  +map start, 300 frames, accepted submissions                                  -> g52-r1.log
#   G6  the attract demo, 300 frames, accepted submissions                             -> g52-r2.log
#   G7  after the last close: the kernel's async line and the close line (retires=)
#   G8  G5-4 8d (docs/G5_4_READPIX_AND_CLEANUP_PLAN.md 2-4): right after GLQuake, another process's
#       FIRST card clear -- G4-6 saw it time out once (RDN-G3 clear rc=8, recovered).  ghostprobe_v20
#       built against the newest library, one offscreen frame; the kernel's clear lines are judged
# RDNMesaTimeSplit=150 (G5-3): judge_g50 prints frames 1-150 (console, loading) and 150-300 (world) apart.
# Each run has the 110 s bound of run-glquake-self.sh (onscreen-runs-about-a-minute).
set -u
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; T=$N/build/g52; L=$P/build/g52; OP=$P/build/r7b/r5op.sh
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf timeout 590 ./bin/gcds next "$1") 2>&1 | sed 's/.*mach: //'; }
seed() { S=$(python3 -c "import time;print(int(time.time())-1000000000)"); echo $(( (S % 40000) * 100000 + $1 )); }
run() {
    name=$1; frames=$2; salt=$3; envx=$4; shift 4
    rm -f "$L/$name.log"
    mach "cd /usr/local/quake; $envx RDNMesaTime=1 RDNMesaTimeSplit=150 RDNMesaSeed=$(seed $salt) sh /ndrv/openstep-quake/test/run-glquake-self.sh /usr/local/nxbuild/bin/glquake_radeon $frames 110 0 -nosound $*; cp /tmp/glq-self.log $T/$name.log; sync; egrep '^RDN-C|^RDN-A|^RDN-P' /tmp/glq-self.log | tail -3" | tail -4
}
echo "== G4: +map start, synchronous (RDNMesaSync=1)"; run g52-sync 300 1000 "RDNMesaSync=1" +map start
echo "== G5: +map start, accepted";                  run g52-r1 300 2000 "" +map start
echo "== G6: the attract demo, accepted";             run g52-r2 300 3000 ""
echo "== G7: the kernel after the last close"
bash "$OP" tdump >/dev/null 2>&1
mach "egrep 'RDN-R5 async|RDN-R4 close' /usr/adm/messages | tail -3" | tee "$L/on-kernel.txt"
echo "== G8: the first card clear after GLQuake (ghostprobe_v20, one frame, offscreen)"
LIBR=$(ls -d $P/build/m1b/*/ | sort | tail -1 | xargs basename)
mach "cd /tmp; sed -n '581,730p' /ndrv/openstep-mesa342/upstream/Mesa-3.4.2/widgets-mesa/demos/tea.c > /tmp/teapot-geometry.h; M=/ndrv/openstep-mesa342/upstream/Mesa-3.4.2; cc -O -m486 -D__OPENSTEP__ -I/tmp -I$N/mesa -I$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj -I\$M/src -I\$M/include $N/build/g46/ghostprobe_v20.c $N/build/m1b/$LIBR/libGL_radeon.a -lm -o /tmp/ghostprobe20 > /tmp/cc-g20.log 2>&1; echo CC=\$?; wc -l < /usr/adm/messages > /tmp/g52-G8.mark; RDNMesaSeed=$(seed 4000) /tmp/ghostprobe20 1 0 0 /tmp/g52-gp.ppm > /tmp/g52-gp.out 2>&1; echo RC=\$?; sync" | tail -2
mach "sed -n \"\`expr \\\`cat /tmp/g52-G8.mark\\\` + 1\`,\\\$p\" /usr/adm/messages | egrep 'RDN-G3 clear|RDN-R5 skip|RDN-R5 latch'" | tee "$L/on-clear.txt"
echo "== judge"
for n in g52-sync g52-r1 g52-r2; do echo "-- $n"; python3 "$P/build/g50/judge_g50.py" "$L/$n.log" | grep -v "^   NOTE"; done
python3 "$P/build/g52/judge_g52.py" on "$L"
