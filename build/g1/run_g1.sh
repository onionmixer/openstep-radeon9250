#!/bin/bash
# G1 boot 1 (docs/G1_REMAINING.md): every size, plain and culled, R rounds, with the
# fence on, counting recoveries.  Everything runs through gcdsd (the screen is its).
#
#   RUNID=<teapot build> BOOT=<nonce> BUILD=<driver stamp> [R=2] bash build/g1/run_g1.sh
#
# Then on the host:  python3 tools/mesa/judge_teapot.py build/g1/run-<S>/r<k>
set -u
: "${RUNID:?RUNID=<teapot build runid>}"; : "${BOOT:?BOOT=<boot nonce>}"; : "${BUILD:?BUILD=<driver stamp>}"
R=${R:-2}
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
OP=$P/build/r7b/r5op.sh; N=/ndrv/openstep-radeon9250; T=$N/build/m3a/$RUNID
CAPS=$N/build/r2b0/790016206/osrdncaps
say() { echo "== $*"; }
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "$1") | sed 's/.*mach: //'; }
op() { line=`bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`; echo "   $* -> $line"; case "$line" in *"r=0") return 0 ;; *) return 1 ;; esac; }
[ -f "$P/build/m3a/$RUNID/rdnteapot-accel" ] || { say "no build/m3a/$RUNID"; exit 2; }
S=$(python3 -c "import time;print(int(time.time())-1000000000)"); O=$P/build/g1/run-$S; mkdir "$O" || exit 2
say "run $S, out build/g1/run-$S, rounds $R"
CAPLINE=$(mach "sync; $CAPS ${S}q 2>&1 | head -1"); echo "   $CAPLINE"
case "$CAPLINE" in *build=$BUILD*) ;; *) say "the running driver is not build $BUILD -- stopping"; exit 3 ;; esac
case "$CAPLINE" in
  *cprunning=0*) say "bringing the CP up"; for o in record rec3d load map reset start; do op "$o" || { say "$o failed"; exit 4; }; done ;;
  *cprunning=1*) say "the CP is running" ;;
  *) say "CAPS did not answer"; exit 3 ;;
esac
k=0; stop=
while [ $k -lt $R ] && [ -z "$stop" ]; do
    k=$((k + 1)); mkdir "$O/r$k"
    for spec in "64 64 64" "256 256 256" "640 480 640x480" "1024 768 1024x768" "64 64 64c" "256 256 256c" "640 480 640x480c" "1024 768 1024x768c"; do
        set -- $spec; w=$1; h=$2; name=$3; arg=""; case "$name" in *c) arg="cull" ;; esac
        say "round $k, teapot $name"
        op zprep || { stop=zprep; break; }
        mach "sync; cd /tmp; RDNTeapotFence=1 RDNMesaSeed=$((S + k * 100000 + ${#name} * 5000 + w)) $T/rdnteapot-accel $w $h 10 $N/build/g1/run-$S/r$k/accel-$name.ppm $arg > $N/build/g1/run-$S/r$k/accel-$name.out 2>&1; echo RC=\$?; sync" | tail -1
        if [ $k = 1 ]; then
            mach "sync; cd /tmp; $T/rdnteapot-stock $w $h 10 $N/build/g1/run-$S/r1/stock-$name.ppm $arg > $N/build/g1/run-$S/r1/stock-$name.out 2>&1; echo RC=\$?; sync" | tail -1
        else
            cp "$O/r1/stock-$name.ppm" "$O/r$k/stock-$name.ppm"     # deterministic: one software render a size
        fi
        grep -o 'submitted=[0-9]*\|culled=[0-9]*\|replayed=[0-9]*\|REFUSED=[0-9]*\|changed=[0-9]*\|same=[0-9]' "$O/r$k/accel-$name.out" | tr '\n' ' '; echo
        if grep -q 'NO_ACCEL=[1-9]\|NOT_RUNNING=[1-9]' "$O/r$k/accel-$name.out"; then say "the card went away -- stopping"; stop="r$k-$name"; break; fi
    done
done
say "log and counts"
op record; sleep 4; op record; sleep 4
mach "sed -n '/boot=$BOOT/,\$p' /usr/adm/messages" > "$O/boot.drv"
echo "   boot.drv $(wc -l < "$O/boot.drv") lines; recovered submissions: $(grep -c 'RDN-R7B submit.* rc=8 ' "$O/boot.drv"); latched: $(grep -c 'RDN-R7B submit.* rc=3 ' "$O/boot.drv"); kept: $(grep -c 'RDN-R5 kept' "$O/boot.drv"); fifo lines: $(grep -c 'RDN-R5 fifo' "$O/boot.drv")"
say "G1-RUN-DONE $S rounds=$k stopped=${stop:-no}"
