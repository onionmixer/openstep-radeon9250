#!/bin/sh
# run_g44.sh -- the boot 9 run = its judge procedure (docs/G4_4_KERNEL_PLAN.md 6): K8 (GHOST_MANY
# in 2 batches), K7 (the regressions; the rule is proved on the host), K5 (GHOST_MIP, the mip
# qualification probe, card against stock), and every G4-2 / G4-3 scene again.
#   LIBRUN=<library runid> BUILD=<driver stamp> CAPSRUN=<r2b0 runid> bash build/g44/run_g44.sh
# CAPSRUN names the osrdncaps built with the version 2 header (the old one prints version 1 and
# the stamp line still parses, but the runner should ask with the tool of this build).  My own
# gcdsd is enough: everything is offscreen.  Judges: texbig, g43, g42 (MANY expects 2 now), g44.
set -e
: "${LIBRUN:?LIBRUN=<library runid>}"; : "${BUILD:?BUILD=<driver stamp>}"; : "${CAPSRUN:?CAPSRUN=<r2b0 runid>}"
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; LIB=$N/build/m1b/$LIBRUN/libGL_radeon.a
CAPS=$N/build/r2b0/$CAPSRUN/osrdncaps
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
O=$N/build/g44; H=$P/build/g44; L=$P/build/g44
rm -f "$H"/mb.* "$H"/mk.* "$H"/sb.* "$H"/sk.* "$H"/ob.* "$H"/ok.* "$H"/pb.* "$H"/pk.* "$H"/tb.* "$H"/tk.* "$H"/ab.* "$H"/ak.* "$H"/ub.* "$H"/uk.*
echo "== build the probe v18 (accel against $LIBRUN, and stock)"
mach "cd /tmp; sed -n '581,730p' /ndrv/openstep-mesa342/upstream/Mesa-3.4.2/widgets-mesa/demos/tea.c > /tmp/teapot-geometry.h; M=/ndrv/openstep-mesa342/upstream/Mesa-3.4.2; cc -O -m486 -D__OPENSTEP__ -I/tmp -I$N/mesa -I$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj -I\$M/src -I\$M/include $O/ghostprobe_v18.c $LIB -lm -o /tmp/ghostprobe18 > /tmp/cc-g18.log 2>&1; echo CC=\$?; grep error /tmp/cc-g18.log | head -2; cc -O -m486 -D__OPENSTEP__ -DGHOST_STOCK -I/tmp -I/LocalDeveloper/Headers $O/ghostprobe_v18.c -L/LocalDeveloper/Libraries -lGL -lm -o /tmp/ghostprobe_stock18 > /tmp/cc-gs18.log 2>&1; echo CCS=\$?" | tee "$L/build.log"
grep -q "CC=0" "$L/build.log" && grep -q "CCS=0" "$L/build.log" || { echo "== the probe did not build"; exit 5; }
echo "== GHOST_MANY (K8: 300 triangles, one state: 2 batches at 4068 words)"
mach "cd /tmp; GHOST_MANY=1 ./ghostprobe18 0 0 0 $O/mb | egrep 'GHOST many'; GHOST_MANY=1 ./ghostprobe_stock18 0 0 0 $O/mk | egrep 'GHOST many'; sync" | tee "$L/many.log"
echo "== GHOST_SEG (150 state changes in one stream)"
mach "cd /tmp; GHOST_SEG=1 ./ghostprobe18 0 0 0 $O/sb | egrep 'GHOST seg'; GHOST_SEG=1 ./ghostprobe_stock18 0 0 0 $O/sk | egrep 'GHOST seg'; sync" | tee "$L/seg.log"
echo "== GHOST_ORDER (the flush points)"
mach "cd /tmp; GHOST_ORDER=1 ./ghostprobe18 0 0 0 $O/ob | egrep 'GHOST order'; GHOST_ORDER=1 ./ghostprobe_stock18 0 0 0 $O/ok | egrep 'GHOST order'; sync" | tee "$L/order.log"
echo "== GHOST_MIP (K5: the qualification probe; RDNMesaMip=1 for the card, stock is the control)"
mach "cd /tmp; GHOST_MIP=1 RDNMesaMip=1 ./ghostprobe18 0 0 0 $O/pb | egrep 'GHOST mip'; GHOST_MIP=1 ./ghostprobe_stock18 0 0 0 $O/pk | egrep 'GHOST mip scene . square|GHOST mip scene .:'; sync" | tee "$L/mip.log"
echo "== regressions: GHOST_UV, GHOST_TEXBIG, GHOST_ALPHA (accel + stock), q2"
mach "cd /tmp; GHOST_UV=1 ./ghostprobe18 0 0 0 $O/ub | egrep 'GHOST uv|GHOST   tri'; sync" | tee "$L/uv.log"
mach "cd /tmp; GHOST_TEXBIG=1 ./ghostprobe18 0 0 0 $O/tb | egrep 'texbig written|GHOST hook'; GHOST_TEXBIG=1 ./ghostprobe_stock18 0 0 0 $O/tk | egrep 'texbig written'; sync" | tee "$L/texbig.log"
mach "cd /tmp; GHOST_ALPHA=1 ./ghostprobe18 0 0 0 $O/ab | egrep 'GHOST alpha'; GHOST_ALPHA=1 ./ghostprobe_stock18 0 0 0 $O/ak | egrep 'GHOST alpha'; sync" | tee "$L/alpha.log"
mach "sync; N=$N; cd /tmp; cc -O -m486 -D__OPENSTEP__ -I\$N/test/mgashim -I\$N/mesa -I\$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj -I/LocalDeveloper/Headers /ndrv/openstep-quake/test/q2-state-matrix.c $LIB -lm -o /tmp/q2matrix > /tmp/cc-q2.log 2>&1; echo CC=\$?; ./q2matrix 2>&1 | tail -27" | tee "$L/q2.log"
echo "== judge"
timeout 600 python3 "$P/build/g4/judge_texbig.py" "$H" "$L/texbig.log" | tee "$L/judge_texbig.out"
timeout 600 python3 "$P/build/g43/judge_g43.py" "$H" "$L" | tee "$L/judge_g43.out"
timeout 600 python3 "$P/build/g42/judge_g42.py" "$H" "$L" | tee "$L/judge_g42.out"
timeout 600 python3 "$P/build/g44/judge_g44.py" "$H" "$L" | tee "$L/judge_g44.out"
