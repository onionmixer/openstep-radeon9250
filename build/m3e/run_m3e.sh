#!/bin/bash
# M3e: content or accumulated state? (docs/M3E_PLAN.md 3).  One boot, after the
# M3e driver (build 2d45136c) is live.  Everything goes through gcdsd.
#
#   BOOT=<nonce> BUILD=<stamp> [R=200] bash build/m3e/run_m3e.sh
#
#   A  the captured 108-word batch alone, R times, on a CP that has done nothing
#      else since ZPREP.  A latch here = the content.
#   T  only if A drew all R: the teapot, plain then culled (run_m3c.sh's round),
#      to re-latch for the kept record.
#   K  RECORD once the latch is in (the card is not read; the driver re-prints
#      the first failure it kept), then the boot's log.
set -u
: "${BOOT:?BOOT=<boot nonce>}"
: "${BUILD:?BUILD=<driver build stamp>}"
R=${R:-200}
P=$(cd "$(dirname "$0")/../.." && pwd)
G=$(cd "$P/.." && pwd)
OP=$P/build/r7b/r5op.sh
N=/ndrv/openstep-radeon9250
T=$N/build/m3a/1790272300
CAPS=$N/build/r2b0/790016206/osrdncaps
say() { echo "== $*"; }
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "$1") | sed 's/.*mach: //'; }
op() {
    line=`bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
    echo "   $* -> $line"
    case "$line" in *"r=0") return 0 ;; *) return 1 ;; esac
}

S=$(python3 -c "import time;print(int(time.time())-1000000000)")
O=$P/build/m3e/run-$S
mkdir "$O" || exit 2
say "run $S, out build/m3e/run-$S"

CAPLINE=$(mach "sync; $CAPS ${S}q 2>&1 | head -1")
echo "   $CAPLINE"
case "$CAPLINE" in
  *build=$BUILD*) ;;
  *) say "the running driver is not build $BUILD -- stopping"; exit 3 ;;
esac
case "$CAPLINE" in
  *cprunning=0*) say "bringing the CP up"
                 for o in record rec3d load map reset start; do op "$o" || { say "$o failed"; exit 4; }; done ;;
  *) say "the CP is not freshly down (cprunning is not 0) -- stopping: A needs a CP that did nothing else"; exit 3 ;;
esac

say "A: the captured batch alone, $R times"
op zprep || exit 4
mach "sync; cd /tmp; RDNMesaSeed=$((S + 100000)) $N/build/m3e/rdnreplay $N/build/m3e/latch148.words $R > $N/build/m3e/run-$S/a.out 2>&1; echo RC=\$?; sync" | tail -1
grep 'step=end\|step=flush-refused\|step=add-refused\|step=failed ' "$O/a.out"
if grep -q 'step=end rounds=' "$O/a.out"; then
    say "A drew all $R -- the content alone does not latch.  T: the teapot, to re-latch"
    for mode in plain cull; do
        arg=""; [ "$mode" = cull ] && arg="cull"
        op zprep || break
        mach "sync; cd /tmp; RDNMesaSeed=$((S + 200000 + ${#mode} * 50000)) $T/rdnteapot-accel 64 64 10 $N/build/m3e/run-$S/t-$mode.ppm $arg > $N/build/m3e/run-$S/t-$mode.out 2>&1; echo RC=\$?; sync" | tail -1
        grep -o 'submitted=[0-9]*\|culled=[0-9]*\|REFUSED=[0-9]*' "$O/t-$mode.out" | tr '\n' ' '; echo
        grep -q 'REFUSED=[1-9]' "$O/t-$mode.out" && break
    done
else
    say "A did NOT draw all $R -- the content latches (or something refused it: read a.out)"
fi

say "K: RECORD twice (the latch refuses both; the driver re-prints the kept record, then the fifo words -- M3i)"
op record
sleep 4
op record
sleep 4
mach "sed -n '/boot=$BOOT/,\$p' /usr/adm/messages" > "$O/boot.drv"
echo "   boot.drv: $(wc -l < "$O/boot.drv") lines, kept: $(grep -c 'RDN-R5 kept' "$O/boot.drv"), latch: $(grep -c 'RDN-R5 latch' "$O/boot.drv"), fifo: $(grep -c 'RDN-R5 fifo' "$O/boot.drv"), near: $(grep -c 'RDN-R5 near' "$O/boot.drv")"
say "M3E-RUN-DONE $S"
