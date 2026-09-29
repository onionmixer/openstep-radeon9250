#!/bin/sh
# run_g45.sh -- the G4-5 run = its judge procedure (docs/G4_5_MIP_PLAN.md 5): the mip scenes C
# (knob all, then default), D (knob all), E, F (default), A/B again, and every earlier scene.  No
# reboot: driver 4d2ee38a as installed on boot 9.
#   LIBRUN=<library runid> BUILD=<driver stamp> CAPSRUN=<r2b0 runid> bash build/g45/run_g45.sh
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
# the kernel refuses a repeated seed (CP_WHY_SEED); a process without RDNMesaSeed starts at 1, so
# two runs in a row that each submit once collide (measured, G4-5 first run: three refusals).
# Every accelerated process below gets its own range, 1000 apart (m3a/m3e/m3h/g1 did this).
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
O=$N/build/g45; H=$P/build/g45; L=$P/build/g45
rm -f "$H"/mb.* "$H"/mk.* "$H"/sb.* "$H"/sk.* "$H"/ob.* "$H"/ok.* "$H"/pb.* "$H"/pk.* "$H"/q?.* "$H"/k?.* "$H"/tb.* "$H"/tk.* "$H"/ab.* "$H"/ak.* "$H"/ub.* "$H"/uk.*
echo "== build the probe v19 (accel against $LIBRUN, and stock)"
mach "cd /tmp; sed -n '581,730p' /ndrv/openstep-mesa342/upstream/Mesa-3.4.2/widgets-mesa/demos/tea.c > /tmp/teapot-geometry.h; M=/ndrv/openstep-mesa342/upstream/Mesa-3.4.2; cc -O -m486 -D__OPENSTEP__ -I/tmp -I$N/mesa -I$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj -I\$M/src -I\$M/include $O/ghostprobe_v19.c $LIB -lm -o /tmp/ghostprobe19 > /tmp/cc-g19.log 2>&1; echo CC=\$?; grep error /tmp/cc-g19.log | head -2; cc -O -m486 -D__OPENSTEP__ -DGHOST_STOCK -I/tmp -I/LocalDeveloper/Headers $O/ghostprobe_v19.c -L/LocalDeveloper/Libraries -lGL -lm -o /tmp/ghostprobe_stock19 > /tmp/cc-gs19.log 2>&1; echo CCS=\$?" | tee "$L/build.log"
grep -q "CC=0" "$L/build.log" && grep -q "CCS=0" "$L/build.log" || { echo "== the probe did not build"; exit 5; }
echo "== GHOST_MANY (K8: 300 triangles, one state: 2 batches at 4068 words)"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 1000)) GHOST_MANY=1 ./ghostprobe19 0 0 0 $O/mb | egrep 'GHOST many'; GHOST_MANY=1 ./ghostprobe_stock19 0 0 0 $O/mk | egrep 'GHOST many'; sync" | tee "$L/many.log"
echo "== GHOST_SEG (150 state changes in one stream)"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 2000)) GHOST_SEG=1 ./ghostprobe19 0 0 0 $O/sb | egrep 'GHOST seg'; GHOST_SEG=1 ./ghostprobe_stock19 0 0 0 $O/sk | egrep 'GHOST seg'; sync" | tee "$L/seg.log"
echo "== GHOST_ORDER (the flush points)"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 3000)) GHOST_ORDER=1 ./ghostprobe19 0 0 0 $O/ob | egrep 'GHOST order'; GHOST_ORDER=1 ./ghostprobe_stock19 0 0 0 $O/ok | egrep 'GHOST order'; sync" | tee "$L/order.log"
echo "== GHOST_MIP (K5: the qualification probe; RDNMesaMip=1 for the card, stock is the control)"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 4000)) GHOST_MIP=1 ./ghostprobe19 0 0 0 $O/pb | egrep 'GHOST mip'; GHOST_MIP=1 ./ghostprobe_stock19 0 0 0 $O/pk | egrep 'GHOST mip scene . square|GHOST mip scene .:'; sync" | tee "$L/mip.log"
echo "== G4-5 scene C: LINEAR_MIPMAP_NEAREST (knob all -> card; default knob -> software until measured)"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 5000)) GHOST_MIPC=1 RDNMesaMip=all ./ghostprobe19 0 0 0 $O/qc | egrep 'GHOST mipc'; RDNMesaSeed=$((SEEDBASE + 6000)) GHOST_MIPC=1 ./ghostprobe19 0 0 0 $O/qm | egrep 'GHOST mipc:'; GHOST_MIPC=1 ./ghostprobe_stock19 0 0 0 $O/kc | egrep 'GHOST mipc:'; sync" | tee "$L/mipc.log"
echo "== G4-5 scene D: the blend weight (knob all)"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 7000)) GHOST_MIPD=1 RDNMesaMip=all ./ghostprobe19 0 0 0 $O/qd | egrep 'GHOST mipd'; GHOST_MIPD=1 ./ghostprobe_stock19 0 0 0 $O/kd | egrep 'GHOST mipd:'; sync" | tee "$L/mipd.log"
echo "== G4-5 scene E: a lower level changes (default knob)"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 8000)) GHOST_MIPE=1 ./ghostprobe19 0 0 0 $O/qe | egrep 'GHOST mipe'; GHOST_MIPE=1 ./ghostprobe_stock19 0 0 0 $O/ke | egrep 'GHOST mipe:'; sync" | tee "$L/mipe.log"
echo "== G4-5 scene F: clamped / biased lambda goes to software (default knob)"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 9000)) GHOST_MIPF=1 ./ghostprobe19 0 0 0 $O/qf | egrep 'GHOST mipf'; GHOST_MIPF=1 ./ghostprobe_stock19 0 0 0 $O/kf | egrep 'GHOST mipf case'; sync" | tee "$L/mipf.log"
echo "== regressions: GHOST_UV, GHOST_TEXBIG, GHOST_ALPHA (accel + stock), q2"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 10000)) GHOST_UV=1 ./ghostprobe19 0 0 0 $O/ub | egrep 'GHOST uv|GHOST   tri'; sync" | tee "$L/uv.log"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 11000)) GHOST_TEXBIG=1 ./ghostprobe19 0 0 0 $O/tb | egrep 'texbig written|GHOST hook'; GHOST_TEXBIG=1 ./ghostprobe_stock19 0 0 0 $O/tk | egrep 'texbig written'; sync" | tee "$L/texbig.log"
mach "cd /tmp; RDNMesaSeed=$((SEEDBASE + 12000)) GHOST_ALPHA=1 ./ghostprobe19 0 0 0 $O/ab | egrep 'GHOST alpha'; GHOST_ALPHA=1 ./ghostprobe_stock19 0 0 0 $O/ak | egrep 'GHOST alpha'; sync" | tee "$L/alpha.log"
mach "sync; N=$N; cd /tmp; cc -O -m486 -D__OPENSTEP__ -I\$N/test/mgashim -I\$N/mesa -I\$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj -I/LocalDeveloper/Headers /ndrv/openstep-quake/test/q2-state-matrix.c $LIB -lm -o /tmp/q2matrix > /tmp/cc-q2.log 2>&1; echo CC=\$?; RDNMesaSeed=$((SEEDBASE + 13000)) ./q2matrix 2>&1 | tail -27" | tee "$L/q2.log"
echo "== judge"
timeout 600 python3 "$P/build/g4/judge_texbig.py" "$H" "$L/texbig.log" | tee "$L/judge_texbig.out"
timeout 600 python3 "$P/build/g43/judge_g43.py" "$H" "$L" | tee "$L/judge_g43.out"
timeout 600 python3 "$P/build/g42/judge_g42.py" "$H" "$L" | tee "$L/judge_g42.out"
timeout 600 python3 "$P/build/g44/judge_g44.py" "$H" "$L" | tee "$L/judge_g44.out"
timeout 600 python3 "$P/build/g45/judge_g45.py" "$H" "$L" | tee "$L/judge_g45.out"
