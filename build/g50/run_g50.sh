#!/bin/bash
# run_g50.sh -- G5-0 (docs/G5_0_PERF_MEASURE_PLAN.md 3): three GLQuake runs under the
# frame-budget instrument, then the judge.  The library must already be built and
# GLQuake relinked against it (tools/mesa/target-build-mesa.sh, build-glquake.sh).
#
#   sh build/g50/run_g50.sh
#
# THE USER'S gcdsd MUST BE UP: run-glquake-self.sh opens a window.  Each run is
# 300 frames with a 110 s deadline (well under the two-minute rule).
#
#   R1  +map start, RDNMesaTime=1, kernel stage instrument on   -> g50-r1.log, g50-r1-tstage.txt
#   R2  the attract demo, same                                  -> g50-r2.log, g50-r2-tstage.txt
#   R3  +map start, no knob, kernel instrument off               -> g50-r3.log  (the instrument's cost)
#
# The kernel side is the M2c stage instrument, already in the driver: `time 1`
# turns it on, `tdump` prints the accumulated stages to the boot log once and
# zeroes them (build/m1l/run_m1l.sh 196, 378-382 did exactly this).
set -u
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; T=$N/build/g50; L=$P/build/g50
OP=$P/build/r7b/r5op.sh
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf timeout 590 ./bin/gcds next "$1") 2>&1 | sed 's/.*mach: //'; }
op() { line=`bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`; echo "   $* -> $line"; }
seed() { S=$(python3 -c "import time;print(int(time.time())-1000000000)"); echo $(( (S % 40000) * 100000 + $1 )); }
run() {
    name=$1; knob=$2; salt=$3; shift 3
    envs=""; [ "$knob" = 1 ] && envs="RDNMesaTime=1"
    rm -f "$L/$name.log"
    mach "cd /usr/local/quake; $envs RDNMesaSeed=$(seed $salt) sh /ndrv/openstep-quake/test/run-glquake-self.sh /usr/local/nxbuild/bin/glquake_radeon 300 110 0 -nosound $*; cp /tmp/glq-self.log $T/$name.log; sync; echo RDNT=\`grep -c 'RDN-T' /tmp/glq-self.log\` TICKS=\`grep -c 'mgastats tick' /tmp/glq-self.log\`" | tail -2
}
tstage() {
    mach "grep 'RDN-R5 tstage' /usr/adm/messages | tail -1" > "$L/$1-tstage.txt"
    cut -c1-220 "$L/$1-tstage.txt"
}
echo "== kernel stage instrument on"; op time 1
echo "== R1: +map start, knob on"; run g50-r1 1 1000 +map start
op tdump; tstage g50-r1
echo "== R2: the attract demo, knob on"; run g50-r2 1 2000
op tdump; tstage g50-r2
echo "== kernel stage instrument off"; op time 0
echo "== R3: +map start, no knob"; run g50-r3 0 3000 +map start
echo "== judge"
python3 "$L/judge_g50.py" "$L/g50-r1.log" "$L/g50-r1-tstage.txt" --ref "$L/g50-r3.log"
python3 "$L/judge_g50.py" "$L/g50-r2.log" "$L/g50-r2-tstage.txt"
