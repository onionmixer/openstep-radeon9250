#!/bin/bash
# M1a gate C, the HARDWARE half (docs/M1A_PLAN.md 6, 11).
#
#   bash build/m1a/run_m1a.sh
#
# The other four gates (C's second-call half, D, E, F) were taken on boot
# ece379a7 with the CP stopped.  HARDWARE needs the CP running, and the CP is
# ONE LOAD..STOP cycle per boot -- so this must run on a FRESH boot, before
# anything else spends that cycle.  It does not draw and it does not stop the
# CP, so the cycle is still available to whatever runs next.
#
# The driver is not reinstalled: the probe asks the installed one, and the
# tools live in the build directory below.
set -u
P=$(cd "$(dirname "$0")/../.." && pwd)
G=$(cd "$P/.." && pwd)
B=${BUILDDIR:-/ndrv/openstep-radeon9250/build/r2b0/790016206}
OP=$P/build/r7b/r5op.sh

say() { echo "== $*"; }

say "before the CP is up, the verdict must NOT be HARDWARE"
R=$(python3 -c "import time;print(int(time.time())-1000000000)")
(cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next \
    "sync; $B/osrdnprobe ${R}pre > $B/m1a-$R.out 2>&1; sync; sleep 1; cat $B/m1a-$R.out") \
    | sed 's/.*mach: //' | grep RDNPROBE

say "bringing the CP up (the preamble, no draw, no stop)"
for op in record rec3d load map reset start; do
    printf '   %-8s ' "$op"
    bash "$OP" "$op" 2>&1 | sed 's/.*mach: //' | grep -o 'op=[a-z0-9]* r=-\?[0-9]*' | tail -1
done

say "now the verdict must be HARDWARE, twice, with the caps filled in"
R=$(python3 -c "import time;print(int(time.time())-1000000000)")
(cd "$G" && GCDS_CONF=etc/gcds.cnf ./bin/gcds next \
    "sync; $B/osrdncaps ${R}c > $B/m1a-$R.out 2>&1; $B/osrdnprobe ${R}h >> $B/m1a-$R.out 2>&1; sync; sleep 1; cat $B/m1a-$R.out") \
    | sed 's/.*mach: //' | grep -E 'RDNCAPS|RDNPROBE'
echo M1A-DONE
