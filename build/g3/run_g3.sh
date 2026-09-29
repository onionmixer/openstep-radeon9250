#!/bin/bash
# G3 boot (docs/G3_PRESENT_PLAN.md 2-5): the SDL2 teapot three ways, through the
# user's gcdsd (a window on the screen), 40 frames each at 800x600.
#
#   LIBRUN=<library runid> BOOT=<nonce> BUILD=<driver stamp> [FRAMES=40] bash build/g3/run_g3.sh
#
# Builds the demo on the target first (SDL2 headers live there), then runs
#   1. the stock link (software)            -> sw.out
#   2. the radeon link, SDL swap (readback) -> rb.out
#   3. the radeon link, PRESENT=3 (hooks)   -> pr.out
# and keeps the kernel's RDN-G3 lines.  The user watches the screen.
set -u
: "${LIBRUN:?LIBRUN=<library runid>}"; : "${BOOT:?BOOT=<boot nonce>}"; : "${BUILD:?BUILD=<driver stamp>}"
FRAMES=${FRAMES:-40}
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
N=/ndrv/openstep-radeon9250; LIB=$N/build/m1b/$LIBRUN/libGL_radeon.a
CAPS=$N/build/r2b0/790016206/osrdncaps
say() { echo "== $*"; }
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "$1") | sed 's/.*mach: //'; }
S=$(python3 -c "import time;print(int(time.time())-1000000000)"); O=$P/build/g3/run-$S; mkdir "$O" || exit 2
say "run $S, out build/g3/run-$S, frames $FRAMES, library $LIBRUN"
CAPLINE=$(mach "sync; $CAPS ${S}q 2>&1 | head -1"); echo "   $CAPLINE"
case "$CAPLINE" in *build=$BUILD*) ;; *) say "the running driver is not build $BUILD -- stopping"; exit 3 ;; esac
OP=$P/build/r7b/r5op.sh
op() { line=`bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`; echo "   $* -> $line"; case "$line" in *"r=0") return 0 ;; *) return 1 ;; esac; }
case "$CAPLINE" in
  *cprunning=0*) say "bringing the CP up"; for o in record rec3d load map reset start; do op "$o" || { say "$o failed"; exit 4; }; done ;;
  *cprunning=1*) say "the CP is running" ;;
  *) say "CAPS did not answer"; exit 3 ;;
esac
say "building the demo on the target"
mach "sync; cd /tmp; sed -n '581,730p' /ndrv/openstep-mesa342/upstream/Mesa-3.4.2/widgets-mesa/demos/tea.c > /tmp/teapot-geometry.h; cc -O -m486 -D__OPENSTEP__ -I/tmp -I/LocalDeveloper/Headers/SDL2 -I/LocalDeveloper/Headers -DOSMGA_SDLTEAPOT_PLAIN $N/test/osrdn-sdl-teapot.c /LocalDeveloper/Libraries/libSDL2.a /LocalDeveloper/Libraries/libGL.a -lm -framework AppKit -framework Foundation -framework SoundKit -o /tmp/sdlteapot_sw > /tmp/cc-sw.log 2>&1; echo CCSW=\$?; cc -O -m486 -D__OPENSTEP__ -I/tmp -I/LocalDeveloper/Headers/SDL2 -I/LocalDeveloper/Headers -I$N/mesa -I$N/OSRDNDisplay/OSRDNDisplay_reloc.tproj $N/test/osrdn-sdl-teapot.c /LocalDeveloper/Libraries/libSDL2.a $LIB -lm -framework AppKit -framework Foundation -framework SoundKit -o /tmp/sdlteapot_radeon > /tmp/cc-radeon.log 2>&1; echo CCRD=\$?; grep -c error /tmp/cc-radeon.log" | tail -3
for arm in "sw:./sdlteapot_sw:" "rb:./sdlteapot_radeon:" "pr:./sdlteapot_radeon:OSRDN_SDLTEAPOT_PRESENT=3"; do
    name=${arm%%:*}; rest=${arm#*:}; exe=${rest%%:*}; env=${rest#*:}
    say "arm $name ($exe $env)"
    mach "sync; cd /tmp; $env OSRDN_SDLTEAPOT_FRAMES=$FRAMES $exe 800 600 > $N/build/g3/run-$S/$name.out 2>&1; echo RC=\$?; sync" | tail -1
    grep "render\|swap\|stamp\|wall\|present (G3)\|refused\|stood down\|surface is\|drawn by" "$O/$name.out" | sed 's/^/   /'
done
mach "sed -n '/boot=$BOOT/,\$p' /usr/adm/messages | grep 'RDN-G3'" > "$O/g3.drv"
echo "   RDN-G3 lines: $(wc -l < "$O/g3.drv")"; sed 's/^/   /' "$O/g3.drv" | head -8
say "G3-RUN-DONE $S"
