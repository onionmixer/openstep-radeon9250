#!/bin/bash
# M3a: run the teapot on the target, both links, two sizes (docs/M3A_PLAN.md 5).
#
#   RUNID=<teapot build runid> bash build/m3a/run_m3a.sh
#
# The CP is asked about first and brought up only if it is down -- one
# LOAD..STOP cycle per boot, as build/m1l/run_m1l.sh does.  Each accelerated
# run gets its own ZPREP and its own seed.
#
#   64  x 64   CARD:  inside the card's 64 x 64 depth buffer; every triangle on the card
#   128 x 128  GUARD: bigger; every triangle refused as ARGS and drawn in software
#
# Then on the host:  python3 tools/mesa/judge_teapot.py build/m3a/<runid>
set -u
: "${RUNID:?RUNID=<teapot build runid>}"
P=$(cd "$(dirname "$0")/../.." && pwd)
G=$(cd "$P/.." && pwd)
OP=$P/build/r7b/r5op.sh
T=/ndrv/openstep-radeon9250/build/m3a/$RUNID
CAPS=/ndrv/openstep-radeon9250/build/r2b0/790016206/osrdncaps
say() { echo "== $*"; }
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "$1") | sed 's/.*mach: //'; }
op() {
    line=`bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
    echo "   $* -> $line"
    case "$line" in
      *"r=0") ;;
      *) say "$* did not return 0 ($line).  Stopping."; exit 4 ;;
    esac
}

[ -f "$P/build/m3a/$RUNID/rdnteapot-accel" ] || { say "no build/m3a/$RUNID -- build it first"; exit 2; }
R=$(python3 -c "import time;print(int(time.time())-1000000000)")

say "is the CP already up?  (asking, not assuming)"
CAPLINE=$(mach "sync; $CAPS ${R}q 2>&1 | head -1")
echo "   $CAPLINE"
case "$CAPLINE" in
  *cprunning=1*) say "the CP is running -- nothing to bring up" ;;
  *cprunning=0*)
      say "bringing the CP up (this spends the boot's one cycle)"
      for o in record rec3d load map reset start; do op "$o"; done ;;
  *)  say "CAPS did not answer; stopping rather than guessing"; exit 3 ;;
esac

for S in 64 128; do
    say "teapot ${S}x${S}"
    op zprep
    mach "sync; cd /tmp; RDNMesaSeed=$((R + S * 1000)) $T/rdnteapot-accel $S $S 10 $T/accel-$S.ppm > $T/accel-$S.out 2>&1; echo RC=\$?; sync" | tail -1
    mach "sync; cd /tmp; $T/rdnteapot-stock $S $S 10 $T/stock-$S.ppm > $T/stock-$S.out 2>&1; echo RC=\$?; sync" | tail -1
done
# M3b: culling ALONE, 64 x 64 -- the case where nobody but the hook culls
say "teapot 64x64, back faces culled"
op zprep
mach "sync; cd /tmp; RDNMesaSeed=$((R + 99000)) $T/rdnteapot-accel 64 64 10 $T/accel-64c.ppm cull > $T/accel-64c.out 2>&1; echo RC=\$?; sync" | tail -1
mach "sync; cd /tmp; $T/rdnteapot-stock 64 64 10 $T/stock-64c.ppm cull > $T/stock-64c.out 2>&1; echo RC=\$?; sync" | tail -1
say "M3A-RUN-DONE $R"
