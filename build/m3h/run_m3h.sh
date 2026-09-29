#!/bin/bash
# M3h: the teapot at sizes past 64 x 64, with the fence (docs/M3H_PLAN.md 2, H1-H2).
# Everything goes through gcdsd (the screen belongs to it).
#
#   RUNID=<teapot build runid> BOOT=<nonce> BUILD=<driver stamp> bash build/m3h/run_m3h.sh
#
# Then on the host:  python3 tools/mesa/judge_teapot.py build/m3h/run-<R>
set -u
: "${RUNID:?RUNID=<teapot build runid>}"
: "${BOOT:?BOOT=<boot nonce>}"
: "${BUILD:?BUILD=<driver build stamp>}"
P=$(cd "$(dirname "$0")/../.." && pwd)
G=$(cd "$P/.." && pwd)
OP=$P/build/r7b/r5op.sh
N=/ndrv/openstep-radeon9250
T=$N/build/m3a/$RUNID
CAPS=$N/build/r2b0/790016206/osrdncaps
say() { echo "== $*"; }
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "$1") | sed 's/.*mach: //'; }
op() {
    line=`bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
    echo "   $* -> $line"
    case "$line" in *"r=0") return 0 ;; *) return 1 ;; esac
}

[ -f "$P/build/m3a/$RUNID/rdnteapot-accel" ] || { say "no build/m3a/$RUNID"; exit 2; }
R=$(python3 -c "import time;print(int(time.time())-1000000000)")
O=run-$R
mkdir "$P/build/m3h/$O" || exit 2
say "run $R, out build/m3h/$O"

CAPLINE=$(mach "sync; $CAPS ${R}q 2>&1 | head -1")
echo "   $CAPLINE"
case "$CAPLINE" in *build=$BUILD*) ;; *) say "the running driver is not build $BUILD -- stopping"; exit 3 ;; esac
case "$CAPLINE" in
  *cprunning=0*) say "bringing the CP up"
                 for o in record rec3d load map reset start; do op "$o" || { say "$o failed"; exit 4; }; done ;;
  *cprunning=1*) say "the CP is running" ;;
  *) say "CAPS did not answer"; exit 3 ;;
esac

k=0
for spec in "64 64 64" "256 256 256" "640 480 640x480" "640 480 640x480c"; do
    set -- $spec
    w=$1; h=$2; name=$3; arg=""
    case "$name" in *c) arg="cull" ;; esac
    k=$((k + 1))
    say "teapot $name"
    op zprep || exit 4
    mach "sync; cd /tmp; RDNTeapotFence=1 RDNMesaSeed=$((R + k * 20000)) $T/rdnteapot-accel $w $h 10 $N/build/m3h/$O/accel-$name.ppm $arg > $N/build/m3h/$O/accel-$name.out 2>&1; echo RC=\$?; sync" | tail -1
    mach "sync; cd /tmp; $T/rdnteapot-stock $w $h 10 $N/build/m3h/$O/stock-$name.ppm $arg > $N/build/m3h/$O/stock-$name.out 2>&1; echo RC=\$?; sync" | tail -1
    grep -h "step=fence\|step=finish-sync\|REFUSED=[1-9]" "$P/build/m3h/$O/accel-$name.out" | cut -c1-160
    if grep -q 'REFUSED=[1-9]' "$P/build/m3h/$O/accel-$name.out"; then
        say "the kernel refused -- stopping"
        op record
        break
    fi
done
mach "sed -n '/boot=$BOOT/,\$p' /usr/adm/messages" > "$P/build/m3h/$O/boot.drv"
say "M3H-RUN-DONE $R"
