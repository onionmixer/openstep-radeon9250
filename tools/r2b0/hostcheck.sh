#!/bin/sh
# hostcheck.sh -- check OSRDNDisplay's R2b-0 build on the Linux host, with no target.
#
# The gate from docs/R2B0_IMPL_PLAN.md section 6:
#
#   1. strict C89 against the target's own headers: the five bundle units and
#      the user tool
#   2. NeXT headers only by #import
#   3. objects, and every symbol the module does not define is exported by
#      the i386 kernel (basicConsoleMode, IOGetTimestamp, splhigh/splx among them)
#   4. source and object rules with their mutations (check_r2b0_src.py)
#   5. Load_Commands.sect is WIRE alone (and an ADVERTISE mutation fails)
#   6. the gate expectation header equals its generator's output from the raw
#      R1/R2a logs (gen_expect_r2b0.py --check); parse_r2b0 self-test
#   7. sim_r2b0.py: the record's own source against fake worlds, with mutations
#   8. check_reloc_r2b0.py self-test (the target reloc gate)
#   9. check_drift_src.py: osrdn_pll.m differs from R2a's by reviewed hunks
#  10. check_cfgdiff.py self-test (the Configure.app snapshot judge)
#  11. check_target_r2b0.py: every target script on fake target tools, the
#      R-1 restore path end to end, the run script end to end
#
# What this cannot prove: what cc 2.7.2.1 generates (target build, nm -u
# there and check_reloc_r2b0.py on its reloc), how Configure.app behaves
# (R-1 measures it), or anything about the card.

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$(dirname "$(dirname "$HERE")")
WS=$(dirname "$PROJ")
R="$WS/ref/openstep/headers/NextDeveloper/Headers"
KERNEL="$WS/ref/openstep/ps2/mach_kernel"
SRC="$PROJ/OSRDNDisplay/OSRDNDisplay_reloc.tproj"
HOST="$PROJ/tools/host"
GCC=${GCC:-gcc-12}
# R2b added two units to the same module; the symbol check must see their
# definitions or it reports the module would not link (docs/R2B_IMPL_PLAN.md).
UNITS="OSRDNDisplay.m osrdn_record.m osrdn_pll.m osrdn_port.m RDNR2aMMIO.m osrdn_snap.m osrdn_mode.m osrdn_modelog.m osrdn_modesel.m osrdn_window.m osrdn_engine.m osrdn_vmap.m osrdn_cp.m osrdn_cpu.m"

[ -d "$R/driverkit" ] || { echo "header mirror not found at $R" >&2; exit 2; }
command -v "$GCC" >/dev/null 2>&1 || { echo "$GCC not found" >&2; exit 2; }

W=$(mktemp -d)
trap 'rm -rf "$W"' 0
rc=0

kernel_flags() {
    "$GCC" -m32 -nostdinc -fno-pic -ffreestanding -fno-builtin \
        -I"$SRC" -I"$HOST/hostshim" \
        -isystem "$R" -isystem "$R/ansi" -isystem "$R/bsd" -isystem "$R/mach" \
        -isystem "$R/kernserv" -isystem "$R/architecture" \
        -DKERNEL -DMACH_USER_API -DMACH -DNeXT=1 -D__NeXT__ -D_NEXT_SOURCE \
        -Di386 -D__ARCHITECTURE__='"i386"' "$@"
}
STRICT="-std=c89 -fasm -pedantic-errors -Wno-long-long -Wall \
 -Werror=implicit-function-declaration -Werror=declaration-after-statement"

echo "== 1. strict C89 against the target's headers =="
for f in $UNITS; do
    if kernel_flags -x objective-c -fnext-runtime $STRICT -fsyntax-only "$SRC/$f" 2>"$W/c89.err" &&
       ! grep -q "$f:[0-9]*:[0-9]*: warning" "$W/c89.err"; then
        echo "  ok   $f ($GCC, -Wall clean)"
    else
        grep "$f" "$W/c89.err" | head -5
        echo "  FAIL $f ($GCC)"; rc=1
    fi
done
for tool in "$HERE/rdnr2b0.m" "$PROJ/tools/r4/rdnr4map.m" "$PROJ/tools/r5/rdnr5cp.m"; do
    tn=$(basename "$tool")
    if "$GCC" -m32 -nostdinc -fno-builtin -I"$HOST/hostshim" -I"$(dirname "$tool")" -isystem "$R" -isystem "$R/ansi" \
            -isystem "$R/bsd" -isystem "$R/mach" -isystem "$R/architecture" -DNeXT=1 -D__NeXT__ -D_NEXT_SOURCE -Di386 \
            -D__ARCHITECTURE__='"i386"' -x objective-c -fnext-runtime $STRICT -fsyntax-only "$tool" 2>"$W/tool.err" &&
       ! grep -q ': warning' "$W/tool.err"; then
        echo "  ok   $tn (user tool, -Wall clean)"
    else
        grep -v '^In file included' "$W/tool.err" | head -8
        echo "  FAIL $tn"; rc=1
    fi
done

echo "== 2. NeXT headers by #import =="
if grep -n '^#include' "$SRC"/*.m "$SRC"/*.h "$HERE/rdnr2b0.m" "$PROJ/tools/r4/rdnr4map.m" "$PROJ/tools/r5/rdnr5cp.m"; then
    echo "  FAIL #include in the sources (NeXT headers carry no guards)"; rc=1
else
    echo "  ok   every header is #imported"
fi

echo "== 3. objects, and the kernel's symbol table =="
ok=1
for f in $UNITS; do
    b=$(basename "$f" .m)
    kernel_flags -x objective-c -fnext-runtime -O0 -fno-inline -w -DOSRDN_BUILD=0x1234abcd \
        -c "$SRC/$f" -o "$W/$b.o" || { echo "  FAIL compiling $f"; ok=0; rc=1; }
done
if [ $ok = 1 ]; then
    (cd "$W" && nm -u *.o | sed -n 's/^ *U //p' | sort -u > undef.txt)
    (cd "$W" && nm --defined-only *.o | awk 'NF == 3 {print $NF}' | sort -u > defined.txt)
    comm -23 "$W/undef.txt" "$W/defined.txt" > "$W/external.txt"
    for s in basicConsoleMode IOGetTimestamp splhigh splx; do
        if grep -qx "$s" "$W/external.txt"; then
            echo "  ok   $s is asked of the kernel (checked below)"
        else
            echo "  FAIL $s not referenced: the check would see nothing"; rc=1
        fi
    done
    for s in __udivdi3 __umoddi3 __divdi3 __moddi3; do
        if grep -qx "$s" "$W/undef.txt"; then echo "  FAIL $s referenced (the kernel has no 64-bit division)"; rc=1; fi
    done
    python3 "$HOST/check_symbols.py" "$KERNEL" "$W/external.txt" "$W/defined.txt" --prefix osrdn_ || rc=1
fi

echo "== 4. source and object rules (check_r2b0_src.py) =="
if python3 "$HERE/check_r2b0_src.py" "$W/src" > "$W/src.log" 2>&1; then
    grep -c '^  ok ' "$W/src.log" | sed 's/^/  ok   rule and mutation checks passed: /'
else
    grep -v '^  ok ' "$W/src.log" | sed 's/^/  /'
    echo "  FAIL check_r2b0_src.py"; rc=1
fi

load_commands_ok() {
    body=$(grep -v '^#' "$1" | sed '/^[[:space:]]*$/d')
    [ "$body" = "WIRE" ]
}

echo "== 5. load commands =="
if load_commands_ok "$SRC/Load_Commands.sect"; then
    echo "  ok   WIRE, nothing else"
else
    echo "  FAIL Load_Commands.sect"; rc=1
fi
cp "$SRC/Load_Commands.sect" "$W/lc.sect"
echo 'ADVERTISE OSRDNDisplay' >> "$W/lc.sect"
if load_commands_ok "$W/lc.sect"; then
    echo "  FAIL mutation 'ADVERTISE' passed the load-command check"; rc=1
else
    echo "  ok   mutation 'ADVERTISE' is caught"
fi

echo "== 6. expectations and the parser =="
python3 "$HERE/gen_expect_r2b0.py" --check > "$W/gen.log" 2>&1 \
    && sed 's/^/  ok   /' "$W/gen.log" || { cat "$W/gen.log"; echo "  FAIL gen_expect_r2b0.py --check"; rc=1; }
python3 "$HERE/parse_r2b0.py" --self-test > "$W/p.log" 2>&1 && tail -1 "$W/p.log" | grep -q 'PASS' \
    && grep -c '^ok ' "$W/p.log" | sed 's/^/  ok   parse_r2b0 self-test cases: /' \
    || { grep -v '^ok ' "$W/p.log"; echo "  FAIL parse_r2b0 self-test"; rc=1; }

echo "== 7. the record's own source against fake worlds (sim_r2b0.py) =="
if TMPDIR="$W" python3 "$HERE/sim_r2b0.py" > "$W/sim.log" 2>&1; then
    grep -c '^  ok ' "$W/sim.log" | sed 's/^/  ok   sim checks passed: /'
else
    grep -v '^  ok ' "$W/sim.log" | sed 's/^/  /'
    echo "  FAIL sim_r2b0.py"; rc=1
fi

echo "== 8. the target reloc gate (check_reloc_r2b0.py --self-test) =="
if TMPDIR="$W" python3 "$HERE/check_reloc_r2b0.py" --self-test > "$W/reloc.log" 2>&1; then
    grep -c '^ok ' "$W/reloc.log" | sed 's/^/  ok   check_reloc_r2b0 self-test cases passed: /'
else
    grep -v '^ok ' "$W/reloc.log" | sed 's/^/  /'
    echo "  FAIL check_reloc_r2b0.py self-test"; rc=1
fi

echo "== 9. PLL groups against R2a's (check_drift_src.py) =="
if python3 "$HERE/check_drift_src.py" > "$W/drift.log" 2>&1; then
    head -1 "$W/drift.log" | sed 's/^/  /'
else
    grep -v '^ok ' "$W/drift.log" | sed 's/^/  /'
    echo "  FAIL check_drift_src.py"; rc=1
fi

echo "== 10. the Configure.app snapshot judge (check_cfgdiff.py --self-test) =="
if TMPDIR="$W" python3 "$HERE/check_cfgdiff.py" --self-test > "$W/cfg.log" 2>&1; then
    grep -c '^ok ' "$W/cfg.log" | sed 's/^/  ok   check_cfgdiff self-test cases passed: /'
else
    grep -v '^ok ' "$W/cfg.log" | sed 's/^/  /'
    echo "  FAIL check_cfgdiff.py self-test"; rc=1
fi

echo "== 11. target scripts on fake target tools (check_target_r2b0.py) =="
if TMPDIR="$W" python3 "$HERE/check_target_r2b0.py" > "$W/tgt.log" 2>&1; then
    grep -c '^  ok ' "$W/tgt.log" | sed 's/^/  ok   target-script checks passed: /'
else
    grep -v '^  ok ' "$W/tgt.log" | sed 's/^/  /'
    echo "  FAIL check_target_r2b0.py"; rc=1
fi

echo
[ $rc = 0 ] && echo "hostcheck-r2b0: PASS" || echo "hostcheck-r2b0: FAIL"
exit $rc
