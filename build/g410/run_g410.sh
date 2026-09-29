#!/bin/sh
# run_g410.sh -- G4-10 (docs/G4_10_MIP_SUBSTITUTE_PLAN.md 4): scene D of ghostprobe v19 under the DEFAULT knob,
# against one library build; the picture must show level selection (judge_g410.py).  Offscreen: my gcdsd.
#   LIBRUN=<library runid> BUILD=<driver stamp> CAPSRUN=<r2b0 runid> sh build/g410/run_g410.sh
set -e
: "${LIBRUN:?LIBRUN=<library runid>}"; : "${BUILD:?BUILD=<driver stamp>}"; : "${CAPSRUN:?CAPSRUN=<r2b0 runid>}"
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; LIB=$N/build/m1b/$LIBRUN/libGL_radeon.a
CAPS=$N/build/r2b0/$CAPSRUN/osrdncaps
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf timeout 590 ./bin/gcds next "$1") | sed 's/.*mach: //'; }
S=$(python3 -c "import time;print(int(time.time())-1000000000)")
SEEDBASE=$(( (S % 40000) * 100000 ))
CAPLINE=$(mach "sync; $CAPS ${S}q 2>&1 | head -1"); echo "   $CAPLINE"
case "$CAPLINE" in *build=$BUILD*) ;; *) echo "== the running driver is not build $BUILD -- stopping"; exit 3 ;; esac
OP=$P/build/r7b/r5op.sh
op() { line=`bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`; echo "   $* -> $line"; case "$line" in *"r=0") return 0 ;; *) return 1 ;; esac; }
case "$CAPLINE" in
  *cprunning=0*) echo "== bringing the CP up"; for o in record rec3d load map reset start; do op "$o" || { echo "== $o failed"; exit 4; }; done ;;
  *cprunning=1*) echo "== the CP is running" ;;
  *) echo "== CAPS did not answer"; exit 3 ;;
esac
O=$N/build/g410; H=$P/build/g410; L=$P/build/g410; G45=$N/build/g45
rm -f "$H"/qd.* "$H"/kd.*
echo "== build the probe v19 against $LIBRUN"
mach "cd /tmp; sed -n '581,730p' /ndrv/openstep-mesa342/upstream/Mesa-3.4.2/widgets-mesa/demos/tea.c > /tmp/teapot-geometry.h; M=/ndrv/openstep-mesa342/upstream/Mesa-3.4.2; cc -O -m486 -D__OPENSTEP__ -I/tmp -I$N/mesa -I$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj -I\$M/src -I\$M/include $G45/ghostprobe_v19.c $LIB -lm -o /tmp/ghostprobe19 > /tmp/cc-g19.log 2>&1; echo CC=\$?; grep error /tmp/cc-g19.log | head -2" | tee "$L/build.log"
grep -q "CC=0" "$L/build.log" || { echo "== the probe did not build"; exit 5; }
echo "== scene D, DEFAULT knob (the blending modes substituted by level selection)"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 7000)) GHOST_MIPD=1 ./ghostprobe19 0 0 0 $O/qd | egrep 'GHOST mipd'; sync" | tee "$L/mipd.log"
python3 "$P/build/g410/judge_g410.py" "$H" "$L"
