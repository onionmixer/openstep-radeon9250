#!/bin/sh
# run_g43.sh -- the G4-3 boot's runner = its judge procedure (docs/G4_3_KERNEL_PLAN.md 8).
#   LIBRUN=<library runid> BUILD=<driver stamp> bash build/g43/run_g43.sh
# My own gcdsd is enough: everything here is offscreen.  Order: the running driver is BUILD;
# the CP is brought up as run_g3c.sh does after a boot; the probe (accel + stock) is built;
# K1: GHOST_UV uv 64/256 must be drawn (no EIO); K3/K1b: TEXBIG regression + judge_texbig;
# K2: GHOST_ALPHA (accel + stock) + judge_alpha; q2-state-matrix through the shim; K4: the
# batch count of a fixed scene (TEXBIG's counters: opens) must be lower than the G4-1b run's.
set -e
: "${LIBRUN:?LIBRUN=<library runid>}"; : "${BUILD:?BUILD=<driver stamp>}"
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; LIB=$N/build/m1b/$LIBRUN/libGL_radeon.a
CAPS=$N/build/r2b0/790016206/osrdncaps
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf timeout 590 ./bin/gcds next "$1") | sed 's/.*mach: //'; }
S=$(python3 -c "import time;print(int(time.time())-1000000000)")
CAPLINE=$(mach "sync; $CAPS ${S}q 2>&1 | head -1"); echo "   $CAPLINE"
case "$CAPLINE" in *build=$BUILD*) ;; *) echo "== the running driver is not build $BUILD -- stopping"; exit 3 ;; esac
OP=$P/build/r7b/r5op.sh
op() { line=`bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`; echo "   $* -> $line"; case "$line" in *"r=0") return 0 ;; *) return 1 ;; esac; }
case "$CAPLINE" in
  *cprunning=0*) echo "== bringing the CP up"; for o in record rec3d load map reset start; do op "$o" || { echo "== $o failed"; exit 4; }; done ;;
  *cprunning=1*) echo "== the CP is running" ;;
  *) echo "== CAPS did not answer"; exit 3 ;;
esac
O=$N/build/g3c; H=$P/build/g3c; L=$P/build/g43
mkdir -p "$L"
rm -f "$H"/tb.*.ppm "$H"/ub.*.ppm "$H"/uk.*.ppm "$H"/ab.*.ppm "$H"/ak.*.ppm
echo "== build the probe (accel against $LIBRUN, and stock)"
mach "cd /tmp; sed -n '581,730p' /ndrv/openstep-mesa342/upstream/Mesa-3.4.2/widgets-mesa/demos/tea.c > /tmp/teapot-geometry.h; M=/ndrv/openstep-mesa342/upstream/Mesa-3.4.2; cc -O -m486 -D__OPENSTEP__ -I/tmp -I$N/mesa -I$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj -I\$M/src -I\$M/include $O/ghostprobe_v16.c $LIB -lm -o /tmp/ghostprobe16 > /tmp/cc-g16.log 2>&1; echo CC=\$?; grep error /tmp/cc-g16.log | head -2; cc -O -m486 -D__OPENSTEP__ -DGHOST_STOCK -I/tmp -I/LocalDeveloper/Headers $O/ghostprobe_v16.c -L/LocalDeveloper/Libraries -lGL -lm -o /tmp/ghostprobe_stock16 > /tmp/cc-gs16.log 2>&1; echo CCS=\$?" | tee "$L/build.log"
grep -q "CC=0" "$L/build.log" && grep -q "CCS=0" "$L/build.log" || { echo "== the probe did not build"; exit 5; }
echo "== K1: GHOST_UV (uv 64 and 256 must be drawn, no EIO)"
mach "cd /tmp; GHOST_UV=1 ./ghostprobe16 0 0 0 $O/ub | egrep 'GHOST uv|GHOST   tri'; sync" | tee "$L/uv.log"
echo "== K4: GHOST_MANY (300 triangles, one state: 2 batches at 4068 words)"
mach "cd /tmp; GHOST_MANY=1 ./ghostprobe16 0 0 0 $O/mb | egrep 'GHOST many'; GHOST_MANY=1 ./ghostprobe_stock16 0 0 0 $O/mk | egrep 'GHOST many'; sync" | tee "$L/many.log"
echo "== K3 regression: GHOST_TEXBIG accel + stock"
mach "cd /tmp; GHOST_TEXBIG=1 ./ghostprobe16 0 0 0 $O/tb | egrep 'texbig written|GHOST hook'; GHOST_TEXBIG=1 ./ghostprobe_stock16 0 0 0 $O/tk | egrep 'texbig written'; sync" | tee "$L/texbig.log"
echo "== K2: GHOST_ALPHA accel + stock"
mach "cd /tmp; GHOST_ALPHA=1 ./ghostprobe16 0 0 0 $O/ab | egrep 'GHOST alpha'; GHOST_ALPHA=1 ./ghostprobe_stock16 0 0 0 $O/ak | egrep 'GHOST alpha'; sync" | tee "$L/alpha.log"
echo "== q2-state-matrix through the shim"
mach "sync; N=$N; cd /tmp; cc -O -m486 -D__OPENSTEP__ -I\$N/test/mgashim -I\$N/mesa -I\$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj -I/LocalDeveloper/Headers /ndrv/openstep-quake/test/q2-state-matrix.c $LIB -lm -o /tmp/q2matrix > /tmp/cc-q2.log 2>&1; echo CC=\$?; ./q2matrix 2>&1 | tail -27" | tee "$L/q2.log"
echo "== judge"
timeout 600 python3 "$P/build/g4/judge_texbig.py" "$H" "$L/texbig.log" | tee "$L/judge_texbig.out"
timeout 600 python3 "$P/build/g43/judge_g43.py" "$H" "$L" | tee "$L/judge_g43.out"
