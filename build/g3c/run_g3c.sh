#!/bin/sh
# run_g3c.sh -- the offscreen picture gate for the G3c depth-clear fix (docs/G3B_CLEAR_PLAN.md 7).
#   LIBRUN=<library runid> BUILD=<driver stamp> bash build/g3c/run_g3c.sh
# No screen, no SDL: Claude's own gcdsd is enough.  Builds ghostprobe (accel link) on the
# target, draws the demo's scene once (a.ppm, VRAM) and the clear/teapot/clear sequence
# (seq.ppm.seq1..3.zraw, the depth region), then judges against the stock picture that is
# already in build/g3c (stock_a.ppm.mirror).  PASS here is the condition for the PRESENT
# arm on the screen (run_g3.sh, the user's gcdsd).
set -e
: "${LIBRUN:?LIBRUN=<library runid>}"; : "${BUILD:?BUILD=<driver stamp>}"
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; LIB=$N/build/m1b/$LIBRUN/libGL_radeon.a
CAPS=$N/build/r2b0/790016206/osrdncaps
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "$1") | sed 's/.*mach: //'; }
S=$(python3 -c "import time;print(int(time.time())-1000000000)")
CAPLINE=$(mach "sync; $CAPS ${S}q 2>&1 | head -1"); echo "   $CAPLINE"
case "$CAPLINE" in *build=$BUILD*) ;; *) echo "== the running driver is not build $BUILD -- stopping"; exit 3 ;; esac
# the CP, as run_g3.sh brings it up after a boot (record rec3d load map reset start)
OP=$P/build/r7b/r5op.sh
op() { line=`bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`; echo "   $* -> $line"; case "$line" in *"r=0") return 0 ;; *) return 1 ;; esac; }
case "$CAPLINE" in
  *cprunning=0*) echo "== bringing the CP up"; for o in record rec3d load map reset start; do op "$o" || { echo "== $o failed"; exit 4; }; done ;;
  *cprunning=1*) echo "== the CP is running" ;;
  *) echo "== CAPS did not answer"; exit 3 ;;
esac
O=$N/build/g3c
# stale outputs must not be judged: remove what this run is to write
rm -f "$P/build/g3c/a.ppm" "$P/build/g3c/a.ppm.mirror" "$P"/build/g3c/seq.ppm.seq?.zraw
echo "== build ghostprobe (accel) against $LIBRUN"
mach "cd /tmp; sed -n '581,730p' /ndrv/openstep-mesa342/upstream/Mesa-3.4.2/widgets-mesa/demos/tea.c > /tmp/teapot-geometry.h; cc -O -m486 -D__OPENSTEP__ -I/tmp -I$N/mesa -I$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj $O/ghostprobe.c $LIB -lm -o /tmp/ghostprobe > /tmp/cc-ghost.log 2>&1; echo CC=\$?; grep -c error /tmp/cc-ghost.log"
echo "== draw: one frame, then clear 0.25 / teapot / clear 0.75"
mach "cd /tmp; ./ghostprobe 1 0.0 1.5 $O/a.ppm | grep GHOST; GHOST_SEQ=1 ./ghostprobe 0 0.0 1.5 $O/seq.ppm | grep seq; GHOST_FILLTEST=1 GHOST_ORTHO=1 ./ghostprobe 0 0.0 1.5 $O/ft.ppm | grep filltest; sync"
echo "== judge"
python3 "$P/build/g3c/judge_ghost.py" "$P/build/g3c"
