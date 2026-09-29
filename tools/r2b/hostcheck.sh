#!/bin/sh
# hostcheck.sh -- the R2b (first mode set) host gate.  Grows as R2b is built.
#
#   sh tools/r2b/hostcheck.sh
#
# 1. the host oracle's own self-check (it carries the R2a console anchor and
#    the negative controls that prove each anchor depends on its input)
# 2. the generated mode header equals what the oracle would write, and every
#    value in it is written in a plan document (a generated file is never
#    checked against another generated file)
#
# docs/R2B_IMPL_PLAN.md section 7.

HERE=`dirname $0`
# 2026-09-24: these log paths were hard-coded /tmp and survived every run --
# the suite's scratch gate caught three of them.  TMPDIR is what check-all
# points at its own throwaway directory; /tmp only when run by hand.
T=${TMPDIR:-/tmp}
PROJ=$HERE/../..
rc=0

echo "== 1. host oracle (radeon_modeset.py) =="
if python3 "$PROJ/tools/oracle/radeon_modeset.py" > $T/rdn-r2b-oracle.log 2>&1; then
    grep '^self-check' $T/rdn-r2b-oracle.log | sed 's/^/  ok   /'
else
    sed 's/^/       /' $T/rdn-r2b-oracle.log
    echo "  FAIL radeon_modeset.py"; rc=1
fi

echo "== 2. generated mode header (gen_expect_r2b.py --check) =="
if python3 "$HERE/gen_expect_r2b.py" --check; then :; else rc=1; fi

echo "== 3. strict C89 against the target's headers =="
WS=$PROJ/..
R=$WS/ref/openstep/headers/NextDeveloper/Headers
SRC=$PROJ/OSRDNDisplay/OSRDNDisplay_reloc.tproj
GCC=${GCC:-gcc-12}
for f in osrdn_snap.m osrdn_mode.m; do
    if "$GCC" -m32 -nostdinc -fno-pic -ffreestanding -fno-builtin -I"$SRC" -I"$PROJ/tools/host/hostshim" \
        -isystem "$R" -isystem "$R/ansi" -isystem "$R/bsd" -isystem "$R/mach" \
        -isystem "$R/kernserv" -isystem "$R/architecture" \
        -DKERNEL -DMACH_USER_API -DMACH -DNeXT=1 -D__NeXT__ -D_NEXT_SOURCE \
        -Di386 -D__ARCHITECTURE__='"i386"' -x objective-c -fnext-runtime \
        -std=c89 -fasm -pedantic-errors -Wno-long-long -Wall \
        -Werror=implicit-function-declaration -Werror=declaration-after-statement \
        -fsyntax-only "$SRC/$f" 2>$T/rdn-r2b-c89.err &&
       ! grep -q "$f:[0-9]*:[0-9]*: warning" $T/rdn-r2b-c89.err; then
        echo "  ok   $f ($GCC, -Wall clean)"
    else
        grep "$f" $T/rdn-r2b-c89.err | head -5
        echo "  FAIL $f"; rc=1
    fi
done

echo "== 4. source rules and their mutations (check_r2b_src.py) =="
if python3 "$HERE/check_r2b_src.py" > $T/rdn-r2b-src.log 2>&1; then
    echo "  ok   source rules: `grep -c '^    ok ' $T/rdn-r2b-src.log` lines (rules and mutations)"
else
    sed 's/^/       /' $T/rdn-r2b-src.log
    echo "  FAIL check_r2b_src.py"; rc=1
fi

echo "== 5. the user tool's published mode (check_tool_mode.py) =="
if python3 "$HERE/check_tool_mode.py" > $T/rdn-r2b-tool.log 2>&1; then
    sed 's/^/  /' $T/rdn-r2b-tool.log | sed 's/^   */  /'
else
    sed 's/^/       /' $T/rdn-r2b-tool.log
    echo "  FAIL check_tool_mode.py"; rc=1
fi

echo "== 6. snapshot, entry and revert on a fake card (sim_r2b.py) =="
if python3 "$HERE/sim_r2b.py" > $T/rdn-r2b-sim.log 2>&1; then
    echo "  ok   simulator: `grep -c '^  ok ' $T/rdn-r2b-sim.log` checks (baseline and every mutation caught)"
else
    sed 's/^/       /' $T/rdn-r2b-sim.log
    echo "  FAIL sim_r2b.py"; rc=1
fi

if [ "$rc" = "0" ]; then echo; echo "hostcheck-r2b: PASS"; else echo; echo "hostcheck-r2b: FAIL"; fi
exit $rc
