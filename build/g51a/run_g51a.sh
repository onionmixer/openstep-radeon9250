#!/bin/bash
# run_g51a.sh -- G5-1a (docs/G5_1A_TEX_READBACK_PLAN.md 3): the upload read-back sampled.
#
#   sh build/g51a/run_g51a.sh          (library built and GLQuake relinked; the user's gcdsd up)
#
#   R1  +map start, 300 frames, RDNMesaTime=1        -> g51a-r1.log, then the colour surface dumped
#       (build/g48/rdndump) and compared with G4-11's dump of the same scene (build/g410/dump3-colour.raw)
#   R2  the attract demo, 300 frames, RDNMesaTime=1  -> g51a-r2.log
#   R4  +map start, 100 frames, RDNMesaTexVerify=1 RDNMesaTime=1 -> g51a-r4.log (the whole-loop path alive)
# The kernel stage instrument stays off: G5-0 already split the kernel side.
set -u
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; T=$N/build/g51a; L=$P/build/g51a
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf timeout 590 ./bin/gcds next "$1") 2>&1 | sed 's/.*mach: //'; }
seed() { S=$(python3 -c "import time;print(int(time.time())-1000000000)"); echo $(( (S % 40000) * 100000 + $1 )); }
run() {
    name=$1; envs=$2; frames=$3; salt=$4; shift 4
    rm -f "$L/$name.log"
    mach "cd /usr/local/quake; $envs RDNMesaSeed=$(seed $salt) sh /ndrv/openstep-quake/test/run-glquake-self.sh /usr/local/nxbuild/bin/glquake_radeon $frames 110 0 -nosound $*; cp /tmp/glq-self.log $T/$name.log; sync; echo RDNT=\`grep -c 'RDN-T' /tmp/glq-self.log\` TICKS=\`grep -c 'mgastats tick' /tmp/glq-self.log\`; grep '^texture ' /tmp/glq-self.log | tail -1" | tail -3
}
echo "== R1: +map start, sampled read-back"; run g51a-r1 "RDNMesaTime=1" 300 1000 +map start
echo "== the colour surface after R1"
mach "$N/build/g48/rdndump $T/r1-colour.raw $T/r1-depth.raw 640 480; sync" | grep RDNDUMP | tail -1
python3 - "$L" "$P" <<'E'
import sys
L, P = sys.argv[1], sys.argv[2]
a = open(P + '/build/g410/dump3-colour.raw', 'rb').read(); b = open(L + '/r1-colour.raw', 'rb').read()
n = len(a) // 4; diff = sum(1 for i in range(0, len(a), 4) if a[i:i+4] != b[i:i+4])
print('   colour surface against G4-11 (dump3): %d of %d pixels differ (%.2f %%)' % (diff, n, 100.0 * diff / n))
E
echo "== R2: the attract demo, sampled read-back"; run g51a-r2 "RDNMesaTime=1" 300 2000
echo "== R4: +map start, the whole loop under the knob"; run g51a-r4 "RDNMesaTexVerify=1 RDNMesaTime=1" 100 4000 +map start
echo "== judge"
python3 "$P/build/g50/judge_g50.py" "$L/g51a-r1.log" | grep -v "^   NOTE"
python3 "$P/build/g50/judge_g50.py" "$L/g51a-r2.log" | grep -v "^   NOTE"
python3 "$P/build/g50/judge_g50.py" "$L/g51a-r4.log" | grep "upload in hook\|judge_g50\|frames"
