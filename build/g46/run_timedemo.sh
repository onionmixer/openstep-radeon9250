#!/bin/sh
# run_timedemo.sh -- GLQuake timedemo, radeon against the software control (docs/G4_GLQUAKE_PLAN.md
# G4-4; the acceleration is complete for the states GLQuake uses: q2-state-matrix, G4-5 run 3).
# NEEDS THE USER'S gcdsd: the game opens an SDL window, and the telnet gcdsd has no window server
# (measured: the SDL teapot died with "DPS Error: Can't connect to server").
#   bash build/g46/run_timedemo.sh [w] [h]
# Every radeon process gets its own RDNMesaSeed (a process without one starts at 1 and collides
# with a previous one-submission run: CP_WHY_SEED, which looks like EIO).
# Each run is capped at 120 s (user rule 2026-09-27: on-screen runs about two minutes): a timedemo that
# has not finished by then is killed and its partial log is what it left.
W=${1:-640}; H=${2:-480}
P=$(cd "$(dirname "$0")/../.." && pwd); G=$(cd "$P/.." && pwd)
mach() { (cd "$G" && GCDS_CONF=etc/gcds.cnf timeout 590 ./bin/gcds next "$1") | sed 's/.*mach: //'; }
S=$(python3 -c "import time;print(int(time.time())-1000000000)")
SEED=$(( (S % 40000) * 100000 ))
L=$P/build/g46; mkdir -p "$L"
for B in glquake_radeon glquake_sw; do
    mach "sync; RDNMesaSeed=$SEED sh /ndrv/openstep-quake/test/run-glquake-timedemo.sh $B $W $H 120; sync" | tee "$L/td-$B-${W}x$H.log"
    SEED=$((SEED + 50000))
done
echo "== timedemo ${W}x$H"; grep -h "frames" "$L"/td-*-${W}x$H.log
