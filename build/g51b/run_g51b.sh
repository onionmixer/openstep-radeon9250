#!/bin/bash
# run_g51b.sh -- G5-1b (docs/G5_1B_PRESENT_ONE_BLIT_PLAN.md 2): the frame presented in one blit.
#
#   sh build/g51b/run_g51b.sh          (library built and GLQuake relinked; the user's gcdsd up)
#
#   R1  +map start, 300 frames, RDNMesaTime=1  -> g51b-r1.log; the colour surface dumped after,
#       and -- the surface is top-down now -- compared row-reversed with G5-1a's r1b dump
#   R2  the attract demo, 300 frames, RDNMesaTime=1 -> g51b-r2.log
# The judge prints present ioctls a frame (want 1) and requires the RDN-C software paths at 0.
set -u
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; T=$N/build/g51b; L=$P/build/g51b
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf timeout 590 ./bin/gcds next "$1") 2>&1 | sed 's/.*mach: //'; }
seed() { S=$(python3 -c "import time;print(int(time.time())-1000000000)"); echo $(( (S % 40000) * 100000 + $1 )); }
run() {
    name=$1; frames=$2; salt=$3; shift 3
    rm -f "$L/$name.log"
    mach "cd /usr/local/quake; RDNMesaTime=1 RDNMesaSeed=$(seed $salt) sh /ndrv/openstep-quake/test/run-glquake-self.sh /usr/local/nxbuild/bin/glquake_radeon $frames 110 0 -nosound $*; cp /tmp/glq-self.log $T/$name.log; sync; echo RDNT=\`grep -c 'RDN-T' /tmp/glq-self.log\` TICKS=\`grep -c 'mgastats tick' /tmp/glq-self.log\`; grep '^present mode\|^texture \|^RDN-C' /tmp/glq-self.log | tail -3" | tail -5
}
echo "== R1: +map start, one blit a frame"; run g51b-r1 300 1000 +map start
echo "== the colour surface after R1 (top-down now)"
mach "$N/build/g48/rdndump $T/r1-colour.raw $T/r1-depth.raw 640 480; sync" | grep RDNDUMP | tail -1
python3 - "$L" "$P" <<'E'
import sys
L, P = sys.argv[1], sys.argv[2]
W, H = 640, 480
a = open(P + '/build/g51a/r1b-colour.raw', 'rb').read(); b = open(L + '/r1-colour.raw', 'rb').read()
# G5-1a's surface was bottom-up (row r = GL row r); G5-1b's is top-down (row s = GL row H-1-s)
flipped = b''.join(b[(H - 1 - r) * W * 4:(H - r) * W * 4] for r in range(H))
n = 0; big = 0; ratio = []
for i in range(0, len(a), 4):
    if a[i:i+4] != flipped[i:i+4]:
        n += 1; da = sum(a[i:i+3]); db = sum(flipped[i:i+3])
        if abs(db - da) >= 16: big += 1
        if da > 0: ratio.append(db / da)
ratio.sort()
unflipped_n = sum(1 for i in range(0, len(a), 4) if a[i:i+4] != b[i:i+4])
print('   G5-1b surface, row-reversed, against G5-1a r1b: %d of %d pixels differ (%.1f %%), |delta|>=16: %d (%.2f %%), ratio p10/p50/p90 %s; NOT reversed: %d differ'
      % (n, W * H, 100.0 * n / (W * H), big, 100.0 * big / (W * H),
         ('%.2f/%.2f/%.2f' % (ratio[len(ratio)//10], ratio[len(ratio)//2], ratio[9*len(ratio)//10])) if ratio else '-', unflipped_n))
print('   gate: |delta|>=16 under 1 %%: %s; the reversed comparison must be the close one: %s'
      % ('PASS' if big < 0.01 * W * H else 'FAIL', 'PASS' if n < unflipped_n else 'FAIL'))
E
echo "== R2: the attract demo"; run g51b-r2 300 2000
echo "== judge"
python3 "$P/build/g50/judge_g50.py" "$L/g51b-r1.log" | grep -v "^   NOTE"
python3 "$P/build/g50/judge_g50.py" "$L/g51b-r2.log" | grep -v "^   NOTE"
