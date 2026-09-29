#!/bin/sh
# hostcheck.sh -- check the R2a probe on the Linux host, with no target.
#
# The gate from docs/R1C_R2A_IMPL_PLAN.md section 2-6:
#
#   1. strict C89 against the target's own headers, both files
#   2. NeXT headers only by #import (they carry no include guards)
#   3. every undefined symbol of the two objects exists in the i386 kernel
#      (_splhigh, _splx among them); the module's rdnMmio* are defined by
#      RDNR2aMMIO.o; radeonR2aEntry is defined
#   4. source and object rules with their mutations (check_r2a_src.py): no
#      volatile/pointer cast/long long in the probe, the rdnMmioWrite8/32 call
#      sites, splhigh/splx pairing, constants, ports, map length, long widths,
#      cc 2.7.2.1 names, helpers-only, no -flto; helper store widths at -O0
#      and -O2; out instructions, call relocations and store provenance in
#      the probe object
#   5. Load_Commands.sect from the template: CALL radeonR2aEntry <runid>,
#      WIRE, START, nothing else (and an ADVERTISE mutation fails)
#   6. the probe's register and PLL tables equal parse_r2a.py's, in order;
#      parse_r2a.py and stores.py self-tests
#   7. sim_r2a.py: the probe's own source against fake worlds, R1's worlds
#      again, its mutations
#   8. check_reloc.py self-test (the target reloc gate)
#   9. check_target_r2a.py: target-build.sh and target-run.sh on fake tools
#  10. check_drift.py: the target scripts differ from R1's by reviewed hunks
#
# What this cannot prove: that cc 2.7.2.1 generates the same code (the
# target build, nm -u there and check_reloc.py on its reloc have the last
# word), or anything about the card.

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$(dirname "$(dirname "$HERE")")
WS=$(dirname "$PROJ")
R="$WS/ref/openstep/headers/NextDeveloper/Headers"
KERNEL="$WS/ref/openstep/ps2/mach_kernel"
SRC="$PROJ/probe/RDNR2aProbe/RDNR2aProbe_reloc.tproj"
HOST="$PROJ/tools/host"
GCC=${GCC:-gcc-12}

[ -d "$R/driverkit" ] || { echo "header mirror not found at $R" >&2; exit 2; }
command -v "$GCC" >/dev/null 2>&1 || { echo "$GCC not found" >&2; exit 2; }

W=$(mktemp -d)
trap 'rm -rf "$W"' 0
rc=0

common() {
    "$GCC" -m32 -nostdinc -fno-pic -ffreestanding -fno-builtin \
        -I"$SRC" -I"$HOST/hostshim" \
        -isystem "$R" -isystem "$R/ansi" -isystem "$R/bsd" -isystem "$R/mach" \
        -isystem "$R/kernserv" -isystem "$R/architecture" \
        -DKERNEL -DMACH_USER_API -DMACH -DNeXT=1 -D__NeXT__ -D_NEXT_SOURCE \
        -Di386 -D__ARCHITECTURE__='"i386"' "$@"
}
STRICT="-std=c89 -fasm -pedantic-errors -Wno-long-long \
 -Werror=implicit-function-declaration -Werror=declaration-after-statement"

echo "== 1. strict C89 against the target's headers =="
for f in RDNR2aProbe.m RDNR2aMMIO.m; do
    if common -x objective-c -fnext-runtime $STRICT -fsyntax-only "$SRC/$f" 2>"$W/c89.err"; then
        echo "  ok   $f ($GCC)"
    else
        grep "$f" "$W/c89.err" | head -5
        echo "  FAIL $f ($GCC)"; rc=1
    fi
done

echo "== 2. NeXT headers by #import =="
if grep -n '^#include' "$SRC"/*.m "$SRC"/*.h; then
    echo "  FAIL #include in the probe sources (NeXT headers carry no guards)"; rc=1
else
    echo "  ok   every header is #imported"
fi

echo "== 3. objects, and the kernel's symbol table =="
if common -x objective-c -fnext-runtime -O0 -fno-inline -w -DR2A_BUILD=0x1234abcd \
        -c "$SRC/RDNR2aProbe.m" -o "$W/probe.o" &&
   common -x objective-c -fnext-runtime -O0 -w -c "$SRC/RDNR2aMMIO.m" -o "$W/mmio.o"; then
    (cd "$W" && nm -u probe.o mmio.o | sed -n 's/^ *U //p' | sort -u > undef.txt)
    (cd "$W" && nm --defined-only probe.o mmio.o | awk 'NF == 3 {print $NF}' | sort -u > defined.txt)
    if grep -qx 'radeonR2aEntry' "$W/defined.txt"; then
        echo "  ok   radeonR2aEntry defined"
    else
        echo "  FAIL radeonR2aEntry not defined"; rc=1
    fi
    for s in splhigh splx; do
        if grep -qx "$s" "$W/undef.txt"; then
            echo "  ok   $s is an undefined symbol (checked against the kernel below)"
        else
            echo "  FAIL $s not referenced: the check would see nothing"; rc=1
        fi
    done
    python3 "$HOST/check_symbols.py" "$KERNEL" "$W/undef.txt" "$W/defined.txt" --prefix rdnMmio || rc=1
else
    echo "  FAIL compiling the objects"; rc=1
fi

echo "== 4. source and object rules (check_r2a_src.py) =="
if python3 "$HERE/check_r2a_src.py" "$W/src" > "$W/src.log" 2>&1; then
    grep -c '^  ok ' "$W/src.log" | sed 's/^/  ok   rule and mutation checks passed: /'
else
    grep -v '^  ok ' "$W/src.log" | sed 's/^/  /'
    echo "  FAIL check_r2a_src.py"; rc=1
fi

load_commands_ok() {
    body=$(grep -v '^#' "$1" | sed '/^[[:space:]]*$/d')
    expect=$(printf 'CALL radeonR2aEntry 123456\nWIRE\nSTART')
    [ "$body" = "$expect" ]
}

echo "== 5. load commands =="
sed 's/@RUNID@/123456/' "$SRC/Load_Commands.sect.in" > "$W/Load_Commands.sect"
if load_commands_ok "$W/Load_Commands.sect"; then
    echo "  ok   CALL radeonR2aEntry <runid>, WIRE, START, nothing else"
else
    echo "  FAIL generated Load_Commands.sect"; rc=1
fi
cp "$W/Load_Commands.sect" "$W/lc.sect"
echo 'ADVERTISE RDNR2aProbe' >> "$W/lc.sect"
if load_commands_ok "$W/lc.sect"; then
    echo "  FAIL mutation 'ADVERTISE' passed the load-command check"; rc=1
else
    echo "  ok   mutation 'ADVERTISE' is caught"
fi

echo "== 6. tables agree with the parser =="
if python3 - "$SRC/RDNR2aProbe.m" "$HERE/parse_r2a.py" <<'PY'
import importlib.util, re, sys
src = open(sys.argv[1]).read()
spec = importlib.util.spec_from_file_location('p', sys.argv[2])
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
def table(name):
    m = re.search(r'static const r2a_reg %s\[\] = \{(.*?)\n\};' % name, src, re.S)
    return [(n, int(o, 16)) for n, o in re.findall(r'\{\s*"([A-Z0-9_]+)",\s*(0x[0-9a-fA-F]+)\s*\}', m.group(1))]
regs, pll = table('r2aRegs'), table('r2aPll')
bad = 0
if dict(regs) != p.REGS or len(regs) != 50 or len(set(n for n, _ in regs)) != 50:
    print('  registers: probe-only', sorted(set(dict(regs)) - set(p.REGS)), 'parser-only',
          sorted(set(p.REGS) - set(dict(regs))), 'count', len(regs))
    bad = 1
if pll != p.PLL:
    print('  PLL table differs: probe %s parser %s' % (pll, p.PLL))
    bad = 1
if any(i & 0xc0 for _, i in pll):
    print('  a PLL index with bit 6 or 7 set')
    bad = 1
# R1's 35 first, in R1's order, then the 15
spec = importlib.util.spec_from_file_location('p1', sys.argv[2].replace('r2a/parse_r2a.py', 'r1/parse_r1.py'))
p1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p1)
if set(n for n, _ in regs[:35]) != set(p1.REGS):
    print('  the first 35 registers are not R1\'s')
    bad = 1
if not bad:
    print('  ok   %d registers and %d PLL indices, same names, offsets and order' % (len(regs), len(pll)))
sys.exit(bad)
PY
then :; else rc=1; fi
python3 "$HERE/parse_r2a.py" --self-test > "$W/p.log" 2>&1 && tail -1 "$W/p.log" | grep -q 'PASS' \
    && echo "  ok   parse_r2a self-test" || { grep -v '^ok ' "$W/p.log"; echo "  FAIL parse_r2a self-test"; rc=1; }
python3 "$HERE/stores.py" > "$W/s.log" 2>&1 \
    && echo "  ok   stores self-test" || { cat "$W/s.log"; echo "  FAIL stores self-test"; rc=1; }

echo "== 7. the probe's own source against fake worlds (sim_r2a.py) =="
if TMPDIR="$W" python3 "$HERE/sim_r2a.py" > "$W/sim.log" 2>&1; then
    grep -c '^  ok ' "$W/sim.log" | sed 's/^/  ok   sim checks passed: /'
else
    grep -v '^  ok ' "$W/sim.log" | sed 's/^/  /'
    echo "  FAIL sim_r2a.py"; rc=1
fi

echo "== 8. the target reloc gate (check_reloc.py --self-test) =="
if TMPDIR="$W" python3 "$HERE/check_reloc.py" --self-test > "$W/reloc.log" 2>&1; then
    grep -c '^ok ' "$W/reloc.log" | sed 's/^/  ok   check_reloc self-test cases passed: /'
else
    grep -v '^ok ' "$W/reloc.log" | sed 's/^/  /'
    echo "  FAIL check_reloc.py self-test"; rc=1
fi

echo "== 9. target scripts on fake target tools (check_target_r2a.py) =="
if TMPDIR="$W" python3 "$HERE/check_target_r2a.py" > "$W/tgt.log" 2>&1; then
    grep -c '^  ok ' "$W/tgt.log" | sed 's/^/  ok   target-script checks passed: /'
else
    grep -v '^  ok ' "$W/tgt.log" | sed 's/^/  /'
    echo "  FAIL check_target_r2a.py"; rc=1
fi

echo "== 10. target scripts against R1's (check_drift.py) =="
if python3 "$HERE/check_drift.py" > "$W/drift.log" 2>&1; then
    head -1 "$W/drift.log" | sed 's/^/  /'
else
    grep -v '^ok ' "$W/drift.log" | sed 's/^/  /'
    echo "  FAIL check_drift.py"; rc=1
fi

echo
[ $rc = 0 ] && echo "hostcheck-r2a: PASS" || echo "hostcheck-r2a: FAIL"
exit $rc
