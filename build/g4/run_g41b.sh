#!/bin/sh
# G4-1b target run (docs/G4_GLQUAKE_PLAN.md 8-1): the probe scenes, accelerated and stock, and
# the Matrox state matrix through the shim.  sh, not csh.  Usage: sh run_g41b.sh <librun>
R=$1
N=/ndrv/openstep-radeon9250; O=$N/build/g3c; M=/ndrv/openstep-mesa342/upstream/Mesa-3.4.2
cd /tmp
cc -O -m486 -D__OPENSTEP__ -I/tmp -I$N/mesa -I$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj -I$M/src -I$M/include $N/build/g3c/ghostprobe_v13.c $N/build/m1b/$R/libGL_radeon.a -lm -o /tmp/ghostprobe13b > /tmp/cc-g13b.log 2>&1
echo CC=$?
cc -O -m486 -D__OPENSTEP__ -DGHOST_STOCK -I/tmp -I/LocalDeveloper/Headers $N/build/g3c/ghostprobe_v13.c -L/LocalDeveloper/Libraries -lGL -lm -o /tmp/ghostprobe_stock13 > /tmp/cc-gs13.log 2>&1
echo CCS=$?
GHOST_TEXBIG=1 ./ghostprobe13b 0 0 0 $O/tb | egrep 'texbig written|GHOST hook'
GHOST_UV=1 ./ghostprobe13b 0 0 0 $O/ub | egrep 'GHOST uv'
GHOST_UV=1 ./ghostprobe_stock13 0 0 0 $O/uk | egrep 'GHOST uv' | head -2
echo ==== Q2
wc -c $N/test/mgashim/osrdn-mga-shim.h
cc -O -m486 -D__OPENSTEP__ -I$N/test/mgashim -I$N/mesa -I$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj -I/LocalDeveloper/Headers /ndrv/openstep-quake/test/q2-state-matrix.c $N/build/m1b/$R/libGL_radeon.a -lm -o /tmp/q2matrix > /tmp/cc-q2.log 2>&1
echo CC=$?
grep error /tmp/cc-q2.log | head -3
./q2matrix 2>&1 | tail -27
sync
