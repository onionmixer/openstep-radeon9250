#!/bin/bash
# M3c: the teapot, plain and culled, alternating, until the CP latches or the
# rounds run out (docs/M3C_PLAN.md 7).  Everything runs through gcdsd (the
# screen belongs to it).  With the M3c driver a latch leaves its full record in
# the log even though the submit log is off.
#
#   RUNID=<teapot build runid> BOOT=<nonce> [ROUNDS=4] bash build/m3a/run_m3c.sh
set -u
: "${RUNID:?RUNID=<teapot build runid>}"
: "${BOOT:?BOOT=<boot nonce>}"
ROUNDS=${ROUNDS:-4}
P=$(cd "$(dirname "$0")/../.." && pwd)
G=$(cd "$P/.." && pwd)
OP=$P/build/r7b/r5op.sh
T=/ndrv/openstep-radeon9250/build/m3a/$RUNID
CAPS=/ndrv/openstep-radeon9250/build/r2b0/790016206/osrdncaps
say() { echo "== $*"; }
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "$1") | sed 's/.*mach: //'; }
op() {
    line=`bash "$OP" "$@" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1`
    echo "   $* -> $line"
    case "$line" in
      *"r=0") ;;
      *) say "$* did not return 0 ($line).  Stopping."; return 1 ;;
    esac
}

R=$(python3 -c "import time;print(int(time.time())-1000000000)")
O=m3c-$R
mkdir "$P/build/m3a/$RUNID/$O" || exit 2
say "run $R, out build/m3a/$RUNID/$O"

CAPLINE=$(mach "sync; $CAPS ${R}q 2>&1 | head -1")
echo "   $CAPLINE"
case "$CAPLINE" in
  *cprunning=1*) say "the CP is running" ;;
  *cprunning=0*) say "bringing the CP up"
                 for o in record rec3d load map reset start; do op "$o" || exit 4; done ;;
  *) say "CAPS did not answer"; exit 3 ;;
esac

k=0
stop=
while [ $k -lt $ROUNDS ] && [ -z "$stop" ]; do
    k=$((k + 1))
    for mode in plain cull; do
        arg=""; [ "$mode" = cull ] && arg="cull"
        say "round $k, $mode"
        op zprep || { stop=zprep; break; }
        mach "sync; cd /tmp; RDNMesaSeed=$((R + k * 10000 + ${#mode} * 1000)) $T/rdnteapot-accel 64 64 10 $T/$O/r$k-$mode.ppm $arg > $T/$O/r$k-$mode.out 2>&1; echo RC=\$?; sync" | tail -1
        f=$P/build/m3a/$RUNID/$O/r$k-$mode.out
        grep -o 'submitted=[0-9]*\|culled=[0-9]*\|replayed=[0-9]*\|REFUSED=[0-9]*' "$f" | tr '\n' ' '; echo
        if grep -q 'REFUSED=[1-9]' "$f"; then
            say "the kernel refused a batch in round $k ($mode) -- stopping: the CP is probably latched"
            stop="r$k-$mode"
            break
        fi
    done
done

say "fetching this boot's driver log"
(cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next "sed -n '/boot=$BOOT/,\$p' /usr/adm/messages") \
    | sed 's/.*mach: //' > "$P/build/m3a/$RUNID/$O/boot.drv"
echo "   boot.drv: $(wc -l < "$P/build/m3a/$RUNID/$O/boot.drv") lines"
say "M3C-RUN-DONE $R rounds=$k stopped=${stop:-no}"
