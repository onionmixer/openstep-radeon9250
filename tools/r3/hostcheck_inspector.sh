#!/bin/sh
# hostcheck_inspector.sh -- H0 of docs/R3_MULTIMODE_PLAN.md 26-3: the
# Configure inspector's sources against the rules the machine's cc 2.7.2.1
# enforces, before the machine ever sees them.
#
#   sh tools/r3/hostcheck_inspector.sh
#
#   1. OSRDNDisplayInspector.m compiles as strict C89 Objective-C, -Wall
#      clean, against the target's header mirror.  compat/ is passed as a
#      SYSTEM directory: it stands in for the AppKit headers the developer
#      tree lacks, is the Matrox file with two names changed, and gcc's
#      -pedantic calls its ivar-less @interfaces "struct has no named
#      members", which cc 2.7.2.1 accepts (Matrox builds it on the machine).
#   2. No #include in the bundle's own top-level sources (NeXT headers have
#      no guards; mixing #include and #import redefines their typedefs).
#   3. Each rule catches a planted violation, in the same run.

HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$(dirname "$(dirname "$HERE")")
WS=$(dirname "$PROJ")
R="$WS/ref/openstep/headers/NextDeveloper/Headers"
B="$PROJ/OSRDNDisplay"
HOST="$PROJ/tools/host"
GCC=${GCC:-gcc-12}
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
rc=0

[ -d "$R/driverkit" ] || { echo "header mirror not found at $R" >&2; exit 2; }
command -v "$GCC" >/dev/null 2>&1 || { echo "$GCC not found" >&2; exit 2; }

# $1 = the .m, $2 = the directory holding the bundle headers
compile() {
    "$GCC" -m32 -nostdinc -fno-builtin -I"$HOST/hostshim" -isystem "$2/compat" \
        -isystem "$R" -isystem "$R/ansi" -isystem "$R/bsd" -isystem "$R/mach" -isystem "$R/architecture" \
        -DNeXT=1 -D__NeXT__ -D_NEXT_SOURCE -Di386 -D__ARCHITECTURE__='"i386"' -I"$2" \
        -x objective-c -fnext-runtime -std=c89 -fasm -pedantic-errors -Wno-long-long -Wall \
        -Werror=implicit-function-declaration -Werror=declaration-after-statement \
        -fsyntax-only "$1" > "$W/cc.err" 2>&1 && ! grep -q 'warning' "$W/cc.err"
}

# $1 = directory; succeeds when no top-level source there has an #include
no_include() {
    ! grep -n '^[ 	]*#[ 	]*include' "$1"/*.h "$1"/*.m > "$W/inc.out" 2>/dev/null
}

echo "== 1. strict C89 against the target's headers =="
if compile "$B/OSRDNDisplayInspector.m" "$B"; then
    echo "  ok   OSRDNDisplayInspector.m ($GCC, -Wall clean)"
else
    head -8 "$W/cc.err"; echo "  FAIL OSRDNDisplayInspector.m"; rc=1
fi

echo "== 2. NeXT headers by #import =="
if no_include "$B"; then
    echo "  ok   no #include in OSRDNDisplay/*.h *.m"
else
    cat "$W/inc.out"; echo "  FAIL #include in the bundle sources"; rc=1
fi

echo "== 3. each rule can fail =="
M="$W/mut"
mkdir "$M"
cp -r "$B/compat" "$M/"
cp "$B"/*.h "$B"/*.m "$M/"
sed 's|^    \[super setTable:instance\];|    [super setTable:instance];\n    int late = 0; (void)late;|' \
    "$B/OSRDNDisplayInspector.m" > "$M/OSRDNDisplayInspector.m"
if grep -q 'int late' "$M/OSRDNDisplayInspector.m" && ! compile "$M/OSRDNDisplayInspector.m" "$M"; then
    echo "  ok   a declaration after a statement is refused"
else
    echo "  FAIL a declaration after a statement passed"; rc=1
fi
cp "$B/OSRDNDisplayInspector.m" "$M/OSRDNDisplayInspector.m"
sed 's|^#import "osrdn_graypanel.h"|#include "osrdn_graypanel.h"|' "$B/OSRDNDisplayInspector.m" > "$M/OSRDNDisplayInspector.m"
if grep -q '^#include' "$M/OSRDNDisplayInspector.m" && ! no_include "$M"; then
    echo "  ok   an #include is refused"
else
    echo "  FAIL an #include passed"; rc=1
fi
cp "$B/OSRDNDisplayInspector.m" "$M/OSRDNDisplayInspector.m"
sed 's|NXCopyStringBuffer(|NXCopyStringBufferX(|' "$B/OSRDNDisplayInspector.m" > "$M/OSRDNDisplayInspector.m"
if grep -q 'BufferX' "$M/OSRDNDisplayInspector.m" && ! compile "$M/OSRDNDisplayInspector.m" "$M"; then
    echo "  ok   an undeclared function is refused"
else
    echo "  FAIL an undeclared function passed"; rc=1
fi

echo
[ $rc = 0 ] && echo "hostcheck-inspector: PASS" || echo "hostcheck-inspector: FAIL"
exit $rc
