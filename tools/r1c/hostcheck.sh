#!/bin/sh
# hostcheck.sh -- the R1c host gate (docs/R1C_R2A_IMPL_PLAN.md section 1-3).
#
#   1. rdnbios.c is strict C89 against the target's headers (gcc-12, and clang
#      as a second opinion) -- cc 2.7.2.1 rejects what modern compilers allow
#   2. NeXT headers only by #import
#   3. text rules, each with a mutation that must make it fail in this run:
#        two open() calls, one exactly (RDN_MEM_PATH, O_RDONLY), the other
#        exactly O_WRONLY | O_CREAT | O_EXCL; the physical address 0xC0000 once;
#        one lseek with SEEK_SET; no mmap, ioctl, O_RDWR, long long, //
#        comments, identifiers id/in/out, or a field width with the long modifier
#   4. sim_r1c.py -- the unchanged source under strace against a fake device
#   5. parse_bios.py --self-test
#   6. check_target_r1c.py -- target-r1c.sh under /bin/sh with fake tools
#
# What this cannot prove: how cc 2.7.2.1 compiles the file or what the target
# kernel's /dev/mem does; the first real run has the last word on both.

set -u
HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$(dirname "$(dirname "$HERE")")
WS=$(dirname "$PROJ")
R="$WS/ref/openstep/headers/NextDeveloper/Headers"
SHIM="$PROJ/tools/host/hostshim"
SRC="$HERE/rdnbios.c"
GCC=${GCC:-gcc-12}
CLANG=${CLANG:-clang}

[ -d "$R/bsd" ] || { echo "header mirror not found at $R" >&2; exit 2; }
command -v "$GCC" >/dev/null 2>&1 || { echo "$GCC not found" >&2; exit 2; }

W=$(mktemp -d)
trap 'rm -rf "$W"' 0
rc=0

TARGET_FLAGS="-m32 -nostdinc -fno-builtin -I$SHIM -isystem $R -isystem $R/ansi -isystem $R/bsd \
 -isystem $R/mach -isystem $R/architecture -DNeXT=1 -D__NeXT__ -D_NEXT_SOURCE -Di386 \
 -D__ARCHITECTURE__=\"i386\""

echo "== 1. strict C89 against the target's headers =="
# only diagnostics about rdnbios.c count; the header mirror itself is not ours
if $GCC $TARGET_FLAGS -x objective-c -std=c89 -fasm -pedantic-errors -Wall -Wno-long-long \
    -Werror=implicit-function-declaration -Werror=declaration-after-statement \
    -fsyntax-only "$SRC" 2>"$W/gcc.err" && ! grep -q 'rdnbios\.c:[0-9]*:[0-9]*: warning' "$W/gcc.err"; then
    echo "  ok   rdnbios.c ($GCC, -Wall clean)"
else
    grep 'rdnbios\.c' "$W/gcc.err" | head -5
    echo "  FAIL rdnbios.c ($GCC)"; rc=1
fi
if command -v "$CLANG" >/dev/null 2>&1; then
    if $CLANG $TARGET_FLAGS -x objective-c -std=c89 -fgnu-keywords -Wno-long-long \
        -Werror=implicit-function-declaration -Werror=declaration-after-statement \
        -fsyntax-only "$SRC" 2>"$W/clang.err"; then
        echo "  ok   rdnbios.c ($CLANG)"
    elif grep -q 'rdnbios\.c:[0-9]*:[0-9]*: error' "$W/clang.err"; then
        grep 'rdnbios\.c' "$W/clang.err" | head -5
        echo "  FAIL rdnbios.c ($CLANG)"; rc=1
    else
        echo "  note $CLANG rejects only the header mirror (asm volatile); rdnbios.c itself clean"
    fi
fi

echo "== 2. NeXT headers by #import =="
if grep -n '^[[:space:]]*#[[:space:]]*include' "$SRC"; then
    echo "  FAIL #include in rdnbios.c (NeXT headers carry no include guards)"; rc=1
else
    echo "  ok   headers are #imported"
fi

echo "== 3. text rules, with their mutations =="
python3 - "$SRC" <<'PY' || rc=1
import re, sys

def rules(src):
    """Return the list of rule violations of one source text."""
    blank = lambda m: re.sub(r'[^\n]', ' ', m.group(0))
    code = re.sub(r'/\*.*?\*/|"(\\.|[^"\\\n])*"|\'(\\.|[^\'\\\n])*\'', blank, src, flags=re.S)
    with_defines = code
    # preprocessor lines (#import <sys/fcntl.h>) are not code for the word rules
    code = re.sub(r'(?m)^[ \t]*#.*$', lambda m: ' ' * len(m.group(0)), code)
    nocomment = re.sub(r'/\*.*?\*/', lambda m: re.sub(r'[^\n]', ' ', m.group(0)), src, flags=re.S)
    bad = []
    opens = re.findall(r'\bopen\s*\(([^;]*)\)\s*;', nocomment)
    dev = [a for a in opens if re.fullmatch(r'\s*RDN_MEM_PATH\s*,\s*O_RDONLY\s*', a)]
    outf = [a for a in opens if re.fullmatch(r'\s*path\s*,\s*O_WRONLY \| O_CREAT \| O_EXCL\s*,\s*0644\s*', a)]
    if len(opens) != 2 or len(dev) != 1 or len(outf) != 1:
        bad.append('open() calls %r' % opens)
    if re.findall(r'O_RDWR|O_TRUNC|O_APPEND', code) or len(re.findall(r'O_WRONLY', code)) != 1:
        bad.append('open flags other than the two allowed forms')
    if len(re.findall(r'0[xX]0*[cC]0000\b', with_defines)) != 1:
        bad.append('the physical address 0xC0000 must appear exactly once')
    if len(re.findall(r'\blseek\s*\(', code)) != 1 or not re.search(r'lseek\s*\(\s*dfd\s*,\s*\(off_t\)BIOS_PHYS\s*,\s*SEEK_SET\s*\)', code):
        bad.append('lseek must be called once, as lseek(dfd, (off_t)BIOS_PHYS, SEEK_SET)')
    for word in ('mmap', 'ioctl', 'pwrite', 'long long', 'dup', 'fcntl'):
        if re.search(r'\b%s\b' % word, code):
            bad.append('forbidden: %s' % word)
    if re.search(r'//', code):
        bad.append('// comment')
    if re.search(r'(?<![A-Za-z0-9_.])(id|in|out)(?![A-Za-z0-9_])', code):
        bad.append('identifier id/in/out')
    if re.search(r'%[-+ #0]*[0-9]+l[a-zA-Z]', nocomment):
        bad.append('field width with the long modifier')
    if len(re.findall(r'\bwrite\s*\(', code)) != 1 or not re.search(r'write\s*\(\s*ofd\s*,', code):
        bad.append('write must be called once, on ofd')
    return bad

src = open(sys.argv[1]).read()
failures = 0
base = rules(src)
print('  %s unchanged source%s' % ('ok  ' if not base else 'FAIL', '' if not base else ': ' + '; '.join(base)))
failures += bool(base)
mutations = [
    ('device O_RDWR', 'open(RDN_MEM_PATH, O_RDONLY)', 'open(RDN_MEM_PATH, O_RDWR)', 'open() calls'),
    ('output without O_EXCL', 'O_WRONLY | O_CREAT | O_EXCL', 'O_WRONLY | O_CREAT', 'open() calls'),
    ('a third open', '    dfd = open(RDN_MEM_PATH, O_RDONLY);\n', '    dfd = open(RDN_MEM_PATH, O_RDONLY);\n    (void)open("/dev/kmem", O_RDONLY);\n', 'open() calls'),
    ('second address literal', '#define MAX_LENGTH', '#define OTHER 0xc0000\n#define MAX_LENGTH', '0xC0000'),
    ('lseek to a variable', '(off_t)BIOS_PHYS, SEEK_SET', '(off_t)length, SEEK_SET', 'lseek must'),
    ('mmap', '    got = 0;\n    while', '    (void)mmap(0, 1, 1, 1, dfd, 0);\n    got = 0;\n    while', 'forbidden: mmap'),
    ('ioctl', '    got = 0;\n    while', '    (void)ioctl(dfd, 0, 0);\n    got = 0;\n    while', 'forbidden: ioctl'),
    ('long long', '    off_t where;', '    off_t where;\n    long long wide;', 'forbidden: long long'),
    ('// comment', '    got = 0;\n    while', '    got = 0; // start\n    while', '// comment'),
    ('identifier out', '    int ofd;', '    int out;', 'identifier'),
    ('width with l', '"RDNBIOS runid=%u', '"RDNBIOS runid=%08lu', 'long modifier'),
    ('write to the device', '    if (close(dfd) != 0)', '    (void)write(dfd, image, 1);\n    if (close(dfd) != 0)', 'write must'),
    ('fcntl call', '    got = 0;\n    while', '    (void)fcntl(dfd, 0);\n    got = 0;\n    while', 'forbidden: fcntl'),
]
for label, old, new, want in mutations:
    if src.count(old) != 1:
        print('  FAIL mutation %r: anchor found %d times' % (label, src.count(old)))
        failures += 1
        continue
    caught = [c for c in rules(src.replace(old, new)) if want in c]
    print('  %s mutation %s%s' % ('ok  ' if caught else 'FAIL', label,
                                  ' -> ' + caught[0] if caught else ' NOT caught by its rule (%r)' % want))
    failures += not caught
sys.exit(1 if failures else 0)
PY

echo "== 4. dynamic rules under strace (sim_r1c.py) =="
if python3 "$HERE/sim_r1c.py" > "$W/sim.log" 2>&1; then
    tail -1 "$W/sim.log" | sed 's/^/  /'
else
    cat "$W/sim.log"; rc=1
fi

echo "== 5. BIOS parser self-test =="
if python3 "$HERE/parse_bios.py" --self-test > "$W/parse.log" 2>&1; then
    tail -1 "$W/parse.log" | sed 's/^/  /'
else
    cat "$W/parse.log"; rc=1
fi

echo "== 6. target script on fake tools (check_target_r1c.py) =="
if python3 "$HERE/check_target_r1c.py" > "$W/target.log" 2>&1; then
    tail -1 "$W/target.log" | sed 's/^/  /'
else
    cat "$W/target.log"; rc=1
fi

# the value target-r1c.sh read takes as <sum> <blocks> (tools/r1/pack_probe.py bsdsum)
python3 -c "
import importlib.util as u, sys
s = u.spec_from_file_location('p', '$PROJ/tools/r1/pack_probe.py'); m = u.module_from_spec(s); s.loader.exec_module(m)
print('  rdnbios.c BSD sum (for target-r1c.sh read): ' + m.bsdsum(open('$SRC', 'rb').read()))
"
if [ "$rc" = 0 ]; then echo "hostcheck-r1c: PASS"; else echo "hostcheck-r1c: FAIL"; fi
exit $rc
