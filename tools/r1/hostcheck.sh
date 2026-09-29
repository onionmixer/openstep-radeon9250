#!/bin/sh
# hostcheck.sh -- check the R1 probe on the Linux host, with no target.
#
# The gate from docs/R1_INTERROGATION_PLAN.md section 7:
#
#   1. strict C89 against the target's own headers (gcc-12 -fnext-runtime,
#      clang as a second opinion) -- cc 2.7.2.1 rejects what modern gcc allows
#   2. NeXT headers only by #import (they carry no include guards)
#   3. every undefined symbol of the object exists in the i386 kernel
#   4. forbidden operations are absent:
#        source -- no config write helper, no port constant other than the
#                  PCI mechanism #1 pair, no assignment through a cast pointer,
#                  IOMapPhysicalIntoIOTask only with MMIO_MAP_LENGTH
#        object -- built -O0 -fno-inline, so ioPorts.h's inline helpers
#                  stay functions: `out' instructions only inside
#                  outb/outw/outl, those helpers called only from pciRead,
#                  and every such call immediately preceded by
#                  `push $0xcf8' (outl's first argument, the port); at least
#                  one such call must exist or the check saw nothing
#   5. Load_Commands.sect generated from the template calls radeonR1Entry
#      with one integer, WIREs, STARTs, and does not ADVERTISE
#   6. the probe's register table equals tools/r1/parse_r1.py REGS, and the
#      parser's self-test passes
#   7. MUTATIONS: copies of the source with one forbidden operation each, and
#      a load command with ADVERTISE, must each make steps 4/5 FAIL in this
#      same run -- a checker that cannot fail proves nothing (PLAN section 4)
#   8. tools/r1/sim_r1.py: the unchanged source compiled 32-bit against a fake
#      PCI bus and MMIO, its log judged by parse_r1.py, with its own mutations
#   9. tools/r1/check_target_scripts.py: target-build.sh and target-run.sh
#      under /bin/sh with fake make/nm/sum/kl_util, good and broken cases
#
# What this cannot prove: that cc 2.7.2.1 generates the same code, or that
# kl_ld links it.  The target build and `nm -u' there have the last word.

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$(dirname "$(dirname "$HERE")")
WS=$(dirname "$PROJ")
R="$WS/ref/openstep/headers/NextDeveloper/Headers"
KERNEL="$WS/ref/openstep/ps2/mach_kernel"
SRC="$PROJ/probe/RDNR1Probe/RDNR1Probe_reloc.tproj"
HOST="$PROJ/tools/host"
GCC=${GCC:-gcc-12}
CLANG=${CLANG:-clang}

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
if common -x objective-c -fnext-runtime $STRICT -fsyntax-only "$SRC/RDNR1Probe.m"; then
    echo "  ok   RDNR1Probe.m ($GCC)"
else
    echo "  FAIL RDNR1Probe.m ($GCC)"; rc=1
fi
if command -v "$CLANG" >/dev/null 2>&1; then
    if "$CLANG" -m32 -nostdinc -fno-pic -ffreestanding -fno-builtin \
        -I"$SRC" -I"$HOST/hostshim" \
        -isystem "$R" -isystem "$R/ansi" -isystem "$R/bsd" -isystem "$R/mach" \
        -isystem "$R/kernserv" -isystem "$R/architecture" \
        -DKERNEL -DMACH_USER_API -DMACH -DNeXT=1 -D__NeXT__ -D_NEXT_SOURCE \
        -Di386 -D__ARCHITECTURE__='"i386"' \
        -x objective-c -std=c89 -fgnu-keywords -Wno-long-long \
        -Werror=implicit-function-declaration -Werror=declaration-after-statement \
        -fsyntax-only "$SRC/RDNR1Probe.m" 2>"$W/clang.err"; then
        echo "  ok   RDNR1Probe.m ($CLANG)"
    else
        # clang does not know NeXT's asm volatile() in ioPorts.h; report
        # only diagnostics that are not from the header mirror
        if grep -v "^$R" "$W/clang.err" | grep -q "RDNR1Probe.m:[0-9]*:[0-9]*: error"; then
            grep "RDNR1Probe.m" "$W/clang.err" | head -5
            echo "  FAIL RDNR1Probe.m ($CLANG)"; rc=1
        else
            echo "  note $CLANG rejects only the header mirror (asm volatile); probe itself clean"
        fi
    fi
fi

echo "== 2. NeXT headers by #import =="
if grep -n '^#include <\(driverkit\|kernserv\)/' "$SRC"/*.m; then
    echo "  FAIL #include of an unguarded NeXT header"; rc=1
else
    echo "  ok   driverkit headers are #imported"
fi

# cc 2.7.2.1 is an Objective-C front end even here: a variable named `id'
# becomes a cast after an operator (`(id & m)'), and `in'/`out' are macros in
# kernel builds.  Host gcc accepts all three, so this is a text rule.
cc_names() {
    python3 - "$1" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
# comments and string/char literals out, newlines kept so line numbers stay
def blank(m):
    return re.sub(r'[^\n]', ' ', m.group(0))
code = re.sub(r'/\*.*?\*/|//[^\n]*|"(\\.|[^"\\\n])*"|\'(\\.|[^\'\\\n])*\'', blank, src, flags=re.S)
hits = [(n, l) for n, l in enumerate(code.splitlines(), 1) if re.search(r'(?<![A-Za-z0-9_.])(id|in|out)(?![A-Za-z0-9_])', l)]
for n, l in hits:
    print('%d:%s' % (n, src.splitlines()[n - 1].strip()))
sys.exit(0 if hits else 1)
PY
}
# The kernel sprintf ignores a field width on a long conversion (target,
# 2026-09-15: an 8-wide long hex printed "303"), and the host simulator's
# emulation only covers what it was told; so a width with the long modifier
# is a text rule too.  Comments are stripped first.
long_width() {
    python3 - "$1" <<'PY'
import re, sys
code = re.sub(r'/\*.*?\*/', '', open(sys.argv[1]).read(), flags=re.S)
hits = re.findall(r'%[-+ #0]*[0-9]+l[a-zA-Z]', code)
print(' '.join(hits))
sys.exit(0 if hits else 1)
PY
}
if long_width "$SRC/RDNR1Probe.m" >/dev/null; then
    echo "  FAIL a field width with the long modifier (kernel sprintf ignores it)"; rc=1
else
    echo "  ok   no field width with the long modifier"
fi
if cc_names "$SRC/RDNR1Probe.m"; then
    echo "  FAIL identifier id/in/out (cc 2.7.2.1 cast or macro)"; rc=1
else
    echo "  ok   no identifier named id, in or out"
fi

echo "== 3. object, and the kernel's symbol table =="
if common -x objective-c -fnext-runtime -O0 -fno-inline -DR1_BUILD=0x1234abcd \
        -c "$SRC/RDNR1Probe.m" -o "$W/probe.o"; then
    (cd "$W" && nm -u probe.o | sed -n 's/^ *U //p' | sort -u > undef.txt)
    (cd "$W" && nm --defined-only probe.o | awk '{print $NF}' | sort -u > defined.txt)
    if grep -qx 'radeonR1Entry' "$W/defined.txt"; then
        echo "  ok   radeonR1Entry defined"
    else
        echo "  FAIL radeonR1Entry not defined"; rc=1
    fi
    python3 "$HOST/check_symbols.py" "$KERNEL" "$W/undef.txt" "$W/defined.txt" --prefix r1 || rc=1
else
    echo "  FAIL compiling the object"; rc=1
fi

# ---- step 4 as a function so the mutations can run it on copies ----------
forbidden_source() {
    f=$1
    bad=0
    # a configuration write helper, or any write through a cast pointer
    if grep -n 'pciWrite\|WriteConfig' "$f" >/dev/null; then bad=1; fi
    if grep -nE '\*\s*\(\s*volatile[^)]*\*\s*\)\s*\([^;]*\)\s*=[^=]' "$f" >/dev/null; then bad=1; fi
    if grep -nE '\*\s*\([^)]*\*\s*\)\s*\([^;]*\)\s*=[^=]' "$f" >/dev/null; then bad=1; fi
    # port constants other than 0xCF8/0xCFC, and any out* outside pciRead
    if grep -noiE '\b0x0?3[bcd][0-9a-f]\b' "$f" >/dev/null; then bad=1; fi
    if python3 - "$f" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
# every call of outb/outw/outl must sit inside the body of pciRead
bodies = [(m.start(), m.end()) for m in re.finditer(r'\npciRead\([^)]*\)\s*\{.*?\n\}', src, re.S)]
bad = 0
for m in re.finditer(r'\bout[bwl]\s*\(', src):
    if not any(a <= m.start() < b for a, b in bodies):
        bad = 1
for m in re.finditer(r'IOMapPhysicalIntoIOTask\s*\(([^;]*)\)', src):
    if 'MMIO_MAP_LENGTH' not in m.group(1):
        bad = 1
sys.exit(bad)
PY
    then :; else bad=1; fi
    return $bad
}

forbidden_object() {
    o=$1
    objdump -d --no-show-raw-insn "$o" > "$W/dis.txt" 2>/dev/null || return 1
    python3 - "$W/dis.txt" <<'PY'
import re, sys
func = None
bad = 0
prev = ''
calls = 0
for line in open(sys.argv[1]):
    m = re.match(r'^[0-9a-f]+ <([^>]+)>:', line)
    if m:
        func = m.group(1)
        prev = ''
        continue
    insn = line.split(':', 1)[1].strip() if ':' in line else ''
    if not insn:
        continue
    if re.match(r'out[bwl]?\s', insn):
        if func not in ('outb', 'outw', 'outl'):
            print('  out instruction in', func)
            bad = 1
    m = re.match(r'call\s+\S+\s+<(out[bwl])>', insn)
    if m:
        calls += 1
        if func != 'pciRead':
            print('  %s called from %s' % (m.group(1), func))
            bad = 1
        elif not re.match(r'push\s+\$0xcf8$', prev):
            print('  %s in pciRead not preceded by push $0xcf8 (was: %s)' % (m.group(1), prev))
            bad = 1
    prev = insn
if calls == 0:
    print('  no call to an out helper at all -- the check saw nothing')
    bad = 1
sys.exit(bad)
PY
}

load_commands_ok() {
    lc=$1
    body=$(grep -v '^#' "$lc" | sed '/^[[:space:]]*$/d')
    expect=$(printf 'CALL radeonR1Entry 123456\nWIRE\nSTART')
    [ "$body" = "$expect" ]
}

echo "== 4. forbidden operations absent =="
if forbidden_source "$SRC/RDNR1Probe.m"; then
    echo "  ok   source: no config write, no cast-pointer write, no VGA port, out* only in pciRead, map length fixed"
else
    echo "  FAIL source"; rc=1
fi
if [ -f "$W/probe.o" ] && forbidden_object "$W/probe.o"; then
    echo "  ok   object: out only in the port helpers, called only by pciRead, port 0xcf8"
else
    echo "  FAIL object"; rc=1
fi

echo "== 5. load commands =="
sed 's/@RUNID@/123456/' "$SRC/Load_Commands.sect.in" > "$W/Load_Commands.sect"
if load_commands_ok "$W/Load_Commands.sect"; then
    echo "  ok   CALL radeonR1Entry <runid>, WIRE, START, nothing else"
else
    echo "  FAIL generated Load_Commands.sect"; rc=1
fi

echo "== 6. register table agrees with the parser =="
if python3 - "$SRC/RDNR1Probe.m" "$PROJ/tools/r1/parse_r1.py" <<'PY'
import importlib.util, re, sys
probe = dict((n, int(o, 16)) for n, o in
             re.findall(r'\{\s*"([A-Z0-9_]+)",\s*(0x[0-9a-fA-F]+)\s*\}', open(sys.argv[1]).read()))
spec = importlib.util.spec_from_file_location('p', sys.argv[2])
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
if probe != p.REGS or len(probe) == 0:
    print('  probe-only', sorted(set(probe) - set(p.REGS)), 'parser-only', sorted(set(p.REGS) - set(probe)),
          'offset differs', sorted(n for n in probe if n in p.REGS and probe[n] != p.REGS[n]))
    sys.exit(1)
print('  ok   %d registers, same names and offsets' % len(probe))
PY
then :; else rc=1; fi
python3 "$PROJ/tools/r1/parse_r1.py" --self-test | tail -1 | grep -q 'PASS' \
    && echo "  ok   parse_r1 self-test" || { echo "  FAIL parse_r1 self-test"; rc=1; }

echo "== 7. mutations must fail =="
# A mutation is only evidence if the unmutated source passed the same checks.
base_src=0; base_obj=0
forbidden_source "$SRC/RDNR1Probe.m" || base_src=1
if [ -f "$W/probe.o" ]; then forbidden_object "$W/probe.o" >/dev/null || base_obj=1; else base_obj=1; fi
if [ $base_src = 1 ] || [ $base_obj = 1 ]; then
    echo "  FAIL baseline does not pass (source=$base_src object=$base_obj): mutations prove nothing"; rc=1
fi
# mutate <label> <which checks must catch it: src|obj|both> <statement>
mutate() {
    label=$1; want=$2; expr=$3
    cp "$SRC/RDNR1Probe.m" "$W/m.m"
    python3 - "$W/m.m" "$expr" <<'PY'
import sys
p, expr = sys.argv[1], sys.argv[2]
s = open(p).read()
anchor = '    r1RunId = runId;\n'
assert s.count(anchor) == 1
s = s.replace(anchor, anchor + '    ' + expr + '\n')
open(p, 'w').write(s)
PY
    src_fail=0; obj_fail=0
    forbidden_source "$W/m.m" || src_fail=1
    if common -x objective-c -fnext-runtime -O0 -fno-inline -w -c "$W/m.m" -o "$W/m.o" 2>"$W/m.err"; then
        forbidden_object "$W/m.o" >/dev/null || obj_fail=1
    else
        echo "  FAIL mutation '$label' did not compile -- not a test"; rc=1; return
    fi
    ok=1
    case $want in
        src)  [ $src_fail = 1 ] || ok=0 ;;
        obj)  [ $obj_fail = 1 ] || ok=0 ;;
        both) [ $src_fail = 1 ] && [ $obj_fail = 1 ] || ok=0 ;;
    esac
    if [ $ok = 1 ]; then
        echo "  ok   mutation '$label' caught by $want (source=$src_fail object=$obj_fail)"
    else
        echo "  FAIL mutation '$label' not caught by $want (source=$src_fail object=$obj_fail)"; rc=1
    fi
}
mutate "VGA sequencer write"  both 'outb((IOEISAPortAddress)0x3c4, 1);'
mutate "port write via macro" both 'outl((IOEISAPortAddress)(PCI_CFG_DATA), 0);'
mutate "MMIO write"           src  '*(volatile unsigned long *)(r1Regs[0].offset) = 0;'
mutate "config write helper"  src  '{ extern void pciWriteConfig(int); pciWriteConfig(0); }'
mutate "bigger mapping"       src  '{ vm_address_t v; (void)IOMapPhysicalIntoIOTask(0, 0x100000, &v); }'
sed 's/@RUNID@/123456/' "$SRC/Load_Commands.sect.in" > "$W/lc.sect"
echo 'ADVERTISE RDNR1Probe' >> "$W/lc.sect"
if load_commands_ok "$W/lc.sect"; then
    echo "  FAIL mutation 'ADVERTISE' passed the load-command check"; rc=1
else
    echo "  ok   mutation 'ADVERTISE' is caught"
fi
sed 's/val=%08x", r1Regs\[i\].name/val=%08lx", r1Regs[i].name/' "$SRC/RDNR1Probe.m" > "$W/w.m"
if ! grep -F 'val=%08lx' "$W/w.m" >/dev/null; then
    echo "  FAIL long-width mutation not inserted"; rc=1
elif long_width "$W/w.m" >/dev/null; then
    echo "  ok   mutation 'val=%08lx' is caught"
else
    echo "  FAIL mutation 'val=%08lx' passed the long-width rule"; rc=1
fi
for decl in 'unsigned long id = 0; if (!(id == 0UL)) id = 1;' 'int out = 0; (void)out;' 'int in = 0; (void)in;'; do
    sed "s/^    r1RunId = runId;\$/    r1RunId = runId; { $decl }/" "$SRC/RDNR1Probe.m" > "$W/n.m"
    if ! grep -F "$decl" "$W/n.m" >/dev/null; then
        echo "  FAIL identifier mutation not inserted: $decl"; rc=1
    elif cc_names "$W/n.m" >/dev/null; then
        echo "  ok   mutation '$decl' is caught"
    else
        echo "  FAIL mutation '$decl' passed the identifier rule"; rc=1
    fi
done

echo "== 8. the probe's own source run against fake PCI worlds (sim_r1.py) =="
if TMPDIR="$W" python3 "$PROJ/tools/r1/sim_r1.py" > "$W/sim.log" 2>&1; then
    grep -c '^  ok ' "$W/sim.log" | sed 's/^/  ok   sim checks passed: /'
else
    grep -v '^  ok ' "$W/sim.log" | sed 's/^/  /'
    echo "  FAIL sim_r1.py"; rc=1
fi

echo "== 9. target scripts on fake target tools (check_target_scripts.py) =="
if TMPDIR="$W" python3 "$PROJ/tools/r1/check_target_scripts.py" > "$W/tgt.log" 2>&1; then
    grep -c '^  ok ' "$W/tgt.log" | sed 's/^/  ok   target-script checks passed: /'
else
    grep -v '^  ok ' "$W/tgt.log" | sed 's/^/  /'
    echo "  FAIL check_target_scripts.py"; rc=1
fi

echo
[ $rc = 0 ] && echo "hostcheck: PASS" || echo "hostcheck: FAIL"
exit $rc
