#!/bin/bash
# run_g52_0.sh -- G5-2 phase 0 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 3): of the ~1 ms a submission
# keeps the CPU waiting (G5-0 8-2: s2ring minus put/fence/wait), how much is the CP FETCHING
# 16 KB of ring over the bus and how much is the engine DRAWING?
#   bash build/g52/run_g52_0.sh            (offscreen: rdnreplay draws into the window, no gcdsd of the user's)
# Two streams of the SAME length (4,057 words) are replayed 20 times each with the kernel's stage
# instrument on (r5op time 1), and tdump prints the sums after each:
#   real   the recorded GLQuake world stream build/g410/trace-g411-last.bin[:4057]
#          (trace-g411.txt seq 9af: 4,057 words, 187 triangles in 7 draws, 58 register packets)
#   synth  the same prologue (60 words) x67 + 7 register pairs + ONE triangle: register writes
#          only, so the CP fetches the same 16 KB and the engine draws almost nothing
# card(synth) ~ fetch;  card(real) - card(synth) ~ drawing 187 triangles.  Both streams were
# built and walked by python (build/g52/mkstreams.py); rdnreplay walks them again on the target.
set -u
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; T=$N/build/g52; L=$P/build/g52; OP=$P/build/r7b/r5op.sh
WORDS=4057; REPS=20; MAJ=38
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf timeout 590 ./bin/gcds next "$1") 2>&1 | sed 's/.*mach: //'; }
op() { line=`bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`; echo "   r5op $* -> $line"; }
S=$(python3 -c "import time;print(int(time.time())-1000000000)")
echo "run $S $(date +%T)"
op time 1
for arm in real synth; do
    f=$T/$arm-stream.bin; [ $arm = synth ] && f=$T/synth-prologue.bin
    S=$((S + 1))
    echo "== $arm: $WORDS words x $REPS  (runid $S)"
    mach "$N/build/g48/rdnreplay $S $MAJ $f words=$WORDS reps=$REPS crumb=$T/$arm-$S.crumbs; echo rc=\$?; sync" | tee "$L/$arm-replay.log" | grep "step=\|rc=" | cut -c1-160
    op tdump
    mach "grep 'RDN-R5 tstage' /usr/adm/messages | tail -1" > "$L/$arm-tstage.txt"; cut -c1-220 "$L/$arm-tstage.txt"
done
op time 0
python3 - "$L" <<'PY'
import re,sys
L=sys.argv[1]; card={}
for arm in ('real','synth'):
    t=open(L+'/%s-tstage.txt'%arm).read()
    d={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',t)}
    n=d['ops']
    if n==0:
        print('%-5s ops 0: the instrument counted nothing (time 1 not on, or every submission refused)'%arm); continue
    c=(d['s2ring']-d['put']-d['fence']-d['wait'])/n
    card[arm]=c
    print('%-5s ops %3d: s2ring %5.0f = put %3.0f + fence %2.0f + wait %3.0f + card %5.0f us/submission   (s1ring %3.0f tail %3.0f)'
          %(arm,n,d['s2ring']/n,d['put']/n,d['fence']/n,d['wait']/n,c,d['s1ring']/n,d['tail']/n))
if len(card)==2:
    print('fetch (synth) ~ %.0f us, drawing (real - synth) ~ %.0f us of %.0f'%(card['synth'],card['real']-card['synth'],card['real']))
PY
