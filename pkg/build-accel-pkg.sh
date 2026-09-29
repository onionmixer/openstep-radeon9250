#!/bin/sh
# Build the OPENSTEP Installer package for the Radeon Mesa acceleration.
#
#   sh .../pkg/build-accel-pkg.sh <library runid> [source-root] [outdir] [mesa-repo]
#
# Runs ON the target: the package tool is OPENSTEP's, and the payload is i386
# machine code.  The shape is openstep-matrox-remade's pkg/build-accel-pkg.sh.
#
# This package ADDS libGL_radeon.a beside the stock Mesa libraries.  It never
# ships, moves or shadows libGL.a.
#
# THE ARCHIVE IS ONE THE HOST HAS JUDGED.  tools/mesa/target-build-mesa.sh
# builds build/m1b/<runid>/libGL_radeon.a and carries gates B1, B2 and G; the
# host's tools/mesa/judge_m1b.py carries B3 (what our object may leave
# undefined) and F (the stock archive with exactly one member replaced and one
# added, from the source the stock archive was built from).  pkg/
# host-release-gates.sh writes M1B_PASS with the archive's sum only when that
# judge passes, and this script refuses any other bytes.
set -e
LIBRUN="${1:-}"
SRC="${2:-/ndrv/openstep-radeon9250}"
OUT="${3:-/tmp/pkgout}"
MESA="${4:-/ndrv/openstep-mesa342}"
NAME=OSRDNMesaAccel
PKGTOOL=/NextAdmin/Installer.app/package
LIBDIR="$SRC/build/m1b/$LIBRUN"
LIB="$LIBDIR/libGL_radeon.a"
MESADOCS="$MESA/upstream/Mesa-3.4.2/docs"
MARKSRC="$MESA/packaging/openstep/installer-architecture-marker.c"
DOC=OpenStep-Radeon9250-Accel
# The headers a program needs to build against the installed prefix: the
# include closure of the two shipped demos, computed from mesa/ (none of them
# reaches outside it).  docs/REL1_PACKAGING_PLAN.md 11-1.
HEADERS="OSRDNMesaClass.h OSRDNMesaDepth.h OSRDNMesaHook.h OSRDNMesaPresent.h
OSRDNMesaProbe.h OSRDNMesaSurface.h OSRDNMesaTex.h OSRDNMesaTime.h
OSRDNMesaTri.h OSRDNMesaTriTable.h"

# NOT `case ... *[!0-9]*)`: that bracket form refuses good values on this
# shell (recorded trap, tools/mesa/target-build-mesa.sh).  grep decides.
# `| wc -l`, not grep -c: under set -e a count of 0 exits the script with
# nothing said (recorded trap).  wc pads, so the test is numeric.
ok=`echo "$LIBRUN" | grep '^[0-9][0-9]*$' | wc -l`
if [ $ok -ne 1 ]; then
    echo "usage: build-accel-pkg.sh <library runid> [source-root] [outdir] [mesa-repo]" >&2
    exit 2
fi
if [ ! -x "$PKGTOOL" ]; then
    echo "build-accel-pkg: $PKGTOOL not found (run on OPENSTEP)" >&2
    exit 1
fi
if [ "`/usr/bin/arch`" != i386 ]; then
    echo "build-accel-pkg: the payload is i386; build it on i386" >&2
    exit 1
fi
for f in "$LIB" "$LIBDIR/M1B_PASS" \
         "$MESADOCS/COPYRIGHT" "$MESADOCS/COPYING" "$MESADOCS/README" \
         "$SRC/release-packaging/PORT-NOTES.md" "$SRC/LICENSE" "$SRC/NOTICE" \
         "$SRC/pkg/$NAME.info" "$SRC/pkg/$NAME.pre_install" \
         "$SRC/pkg/$NAME.post_install" "$MARKSRC"; do
    if [ ! -s "$f" ]; then
        echo "build-accel-pkg: missing or empty input: $f" >&2
        exit 1
    fi
done
for h in $HEADERS; do
    if [ ! -s "$SRC/mesa/$h" ]; then
        echo "build-accel-pkg: missing header: mesa/$h" >&2
        exit 1
    fi
done

# the host's verdict names these bytes
want=`cat "$LIBDIR/M1B_PASS"`
have=`/usr/bin/sum "$LIB" | awk '{print $1, $2}'`
if [ "$want" != "$have" ]; then
    echo "build-accel-pkg: M1B_PASS names '$want', the archive is '$have'" >&2
    exit 1
fi

# The archive has to be the ACCELERATED one: our member, the replaced
# osmesa.o, and the hook entry defined -- the stock archive has none of them.
n=`ar t "$LIB" | grep osrdnaccel | wc -l`
if [ $n -lt 1 ]; then
    echo "build-accel-pkg: $LIB has no osrdnaccel.o member" >&2
    exit 1
fi
if nm "$LIB" | grep ' T _OpenStepMesaAccelBuffer$' > /dev/null; then
    :
else
    echo "build-accel-pkg: $LIB does not define OpenStepMesaAccelBuffer -- osmesa.o without the hook" >&2
    exit 1
fi

STAGEPARENT=/tmp/_rdnaccelpkg
STAGE="$STAGEPARENT/p"
rm -rf "$STAGEPARENT" "$OUT/$NAME.pkg"
/bin/mkdirs "$STAGE/Libraries" "$STAGE/Headers" "$STAGE/Tools" \
            "$STAGE/Documentation/$DOC/Mesa-3.4.2"

cp "$LIB" "$STAGE/Libraries/libGL_radeon.a"
for h in $HEADERS; do
    cp "$SRC/mesa/$h" "$STAGE/Headers/$h"
done

# Mesa's terms travel with Mesa's code, byte for byte, under THIS package's
# directory (a path another package owns is not this package's to claim --
# openstep-matrox-remade release-packaging/PAYLOAD_MANIFEST.md 2a).
M="$STAGE/Documentation/$DOC/Mesa-3.4.2"
cp "$MESADOCS/COPYRIGHT" "$MESADOCS/COPYING" "$M/"
cp "$MESADOCS/README" "$M/README.Mesa"
cmp "$MESADOCS/COPYRIGHT" "$M/COPYRIGHT"
cmp "$MESADOCS/COPYING"   "$M/COPYING"
cmp "$MESADOCS/README"    "$M/README.Mesa"

cp "$SRC/release-packaging/PORT-NOTES.md" "$SRC/LICENSE" "$SRC/NOTICE" \
   "$STAGE/Documentation/$DOC/"

# The Installer decides a package's architecture from Mach-O files in the
# payload and does not look inside static archives.
cc -m486 -o "$STAGE/Tools/OSRDNAccel-Intel" "$MARKSRC"
chmod 555 "$STAGE/Tools/OSRDNAccel-Intel"

if [ -r "$STAGE/Libraries/libGL.a" ]; then
    echo "build-accel-pkg: stock libGL.a leaked into the payload" >&2
    exit 1
fi
long=`( cd "$STAGE" && find . -print ) | awk 'length($0) >= 100' | wc -l`
if [ $long -gt 0 ]; then
    echo "build-accel-pkg: $long payload paths reach the 100-char limit" >&2
    ( cd "$STAGE" && find . -print ) | awk 'length($0) >= 100' >&2
    exit 1
fi

test -d "$OUT" || /bin/mkdirs "$OUT"
"$PKGTOOL" "$STAGE" "$SRC/pkg/$NAME.info" -d "$OUT" < /dev/null

cp "$SRC/pkg/$NAME.pre_install"  "$OUT/$NAME.pkg/$NAME.pre_install"
cp "$SRC/pkg/$NAME.post_install" "$OUT/$NAME.pkg/$NAME.post_install"
chmod 555 "$OUT/$NAME.pkg/$NAME.pre_install" "$OUT/$NAME.pkg/$NAME.post_install"
echo "$LIBRUN $have" > "$OUT/$NAME.pkg.buildid"
echo "build-accel-pkg: PASS $OUT/$NAME.pkg (library runid $LIBRUN)"
