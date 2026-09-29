#!/bin/sh
# Unpack a built acceleration package and check what is actually inside it.
#
#   sh .../pkg/verify-accel-pkg.sh [package-dir] [source-root] [mesa-repo]
#
# The shape is openstep-matrox-remade's pkg/verify-accel-pkg.sh.  Every file
# that has a source copy is compared with it byte for byte, not only found:
# a package built before an edit passes a presence check and ships stale text.
PKGDIR="${1:-/tmp/pkgout}"
SRC="${2:-/ndrv/openstep-radeon9250}"
MESA="${3:-/ndrv/openstep-mesa342}"
NAME=OSRDNMesaAccel
PKG="$PKGDIR/$NAME.pkg"
UNPACK=/tmp/_rdnaccelverify
MESADOCS="$MESA/upstream/Mesa-3.4.2/docs"
DOC=Documentation/OpenStep-Radeon9250-Accel
HEADERS="OSRDNMesaClass.h OSRDNMesaDepth.h OSRDNMesaHook.h OSRDNMesaPresent.h
OSRDNMesaProbe.h OSRDNMesaSurface.h OSRDNMesaTex.h OSRDNMesaTime.h
OSRDNMesaTri.h OSRDNMesaTriTable.h"

# This shell runs functions in a subshell, so failures go to a file.
FAILS=/tmp/_rdnaccelverify.fails
rm -f "$FAILS"; : > "$FAILS"

note() { echo "  $1"; }
bad()  { echo "  FAIL: $1"; echo "$1" >> "$FAILS"; }

if [ ! -d "$PKG" ]; then echo "verify: no $PKG" >&2; exit 2; fi

echo "package structure"
for f in "$NAME.tar.Z" "$NAME.bom" "$NAME.info" "$NAME.sizes" \
         "$NAME.pre_install" "$NAME.post_install"; do
    if [ -r "$PKG/$f" ]; then note "ok   $f"; else bad "$f missing"; fi
done
for f in "$NAME.pre_install" "$NAME.post_install"; do
    if [ -x "$PKG/$f" ]; then note "ok   $f is executable"
    else bad "$f is not executable"; fi
done
for k in Title Version Description DefaultLocation DiskName; do
    if grep "^$k " "$PKG/$NAME.info" > /dev/null; then note "ok   info $k"
    else bad "$k missing from $NAME.info -- Installer will refuse to open it"; fi
done

rm -rf "$UNPACK"; /bin/mkdirs "$UNPACK"
( cd "$UNPACK" && /usr/ucb/zcat "$PKG/$NAME.tar.Z" | tar xf - )

echo "payload"
for f in Libraries/libGL_radeon.a \
         $DOC/Mesa-3.4.2/COPYRIGHT $DOC/Mesa-3.4.2/COPYING $DOC/Mesa-3.4.2/README.Mesa \
         $DOC/PORT-NOTES.md $DOC/LICENSE $DOC/NOTICE Tools/OSRDNAccel-Intel; do
    if [ -r "$UNPACK/$f" ]; then note "ok   $f"; else bad "$f missing"; fi
done
for h in $HEADERS; do
    if [ ! -r "$UNPACK/Headers/$h" ]; then
        bad "Headers/$h missing -- a program built against the prefix fails"
    elif cmp -s "$SRC/mesa/$h" "$UNPACK/Headers/$h"; then
        note "ok   Headers/$h is byte-for-byte with mesa/$h"
    else
        bad "Headers/$h differs from mesa/$h -- rebuild the package"
    fi
done

echo "it adds a library, it does not replace one"
for f in Libraries/libGL.a Libraries/libGLU.a; do
    if [ -f "$UNPACK/$f" ]; then bad "$f is in the payload -- that is Mesa's to ship"
    else note "ok   no $f"; fi
done

echo "the archive is the accelerated one, and the one the host judged"
A="$UNPACK/Libraries/libGL_radeon.a"
n=`ar t "$A" | grep osrdnaccel | wc -l`
if [ $n -ge 1 ]; then note "ok   osrdnaccel.o is a member"
else bad "no osrdnaccel.o member -- this may be a renamed stock libGL.a"; fi
n=`ar t "$A" | grep osmesa | wc -l`
if [ $n -ge 1 ]; then note "ok   osmesa.o is a member"
else bad "no osmesa.o member"; fi
for h in UpdateState Buffer DepthBuffer ReleaseBuffer BoundTo AppBuffer \
         CopyDepth Mirror Stride ClearPixel; do
    if nm "$A" | grep " T _OpenStepMesaAccel$h\$" > /dev/null; then
        note "ok   OpenStepMesaAccel$h is defined"
    else
        bad "OpenStepMesaAccel$h is not defined -- not the accelerated archive"
    fi
done
if [ -r "$PKGDIR/$NAME.pkg.buildid" ]; then
    run=`awk '{print $1}' "$PKGDIR/$NAME.pkg.buildid"`
    want=`cat "$SRC/build/m1b/$run/M1B_PASS" 2>/dev/null`
    have=`/usr/bin/sum "$A" | awk '{print $1, $2}'`
    if [ -n "$want" ] && [ "$want" = "$have" ]; then
        note "ok   the archive is the bytes the host judged (runid $run)"
    else
        bad "the archive ($have) is not what M1B_PASS names for runid $run ($want)"
    fi
else
    bad "no $NAME.pkg.buildid beside the package -- cannot tie it to a judged build"
fi

echo "architecture"
X="$UNPACK/_rdnverify_members"
rm -rf "$X"; /bin/mkdirs "$X"
( cd "$X" && ar x "$A" osmesa.o osrdnaccel.o )
for o in osmesa.o osrdnaccel.o; do
    if [ ! -r "$X/$o" ]; then
        bad "could not extract $o"
    elif file "$X/$o" | grep i386 > /dev/null; then
        note "ok   $o is i386"
    else
        bad "$o is not i386: `file $X/$o`"
    fi
done
if file "$UNPACK/Tools/OSRDNAccel-Intel" | grep i386 > /dev/null; then
    note "ok   the Installer architecture marker is i386"
else
    bad "the architecture marker is not i386"
fi
if lsbom "$PKG/$NAME.bom" | grep m68k > /dev/null; then
    bad "the BOM mentions m68k"
else
    note "ok   the BOM does not mention m68k"
fi

echo "licence gate"
M="$UNPACK/$DOC/Mesa-3.4.2"
if cmp -s "$MESADOCS/COPYRIGHT" "$M/COPYRIGHT"; then note "ok   Mesa COPYRIGHT is byte-for-byte"
else bad "Mesa COPYRIGHT differs from the port's own copy"; fi
if cmp -s "$MESADOCS/COPYING" "$M/COPYING"; then note "ok   Mesa COPYING is byte-for-byte"
else bad "Mesa COPYING differs from the port's own copy"; fi
if cmp -s "$MESADOCS/README" "$M/README.Mesa"; then note "ok   Mesa README.Mesa is byte-for-byte"
else bad "Mesa README.Mesa differs from the port's own copy"; fi
if grep 'not a licensed OpenGL' "$M/README.Mesa" > /dev/null; then
    note "ok   Mesa's not-a-licensed-OpenGL statement travelled"
else
    bad "Mesa's not-a-licensed-OpenGL statement is missing"
fi
for probe in 'Advanced Micro Devices' 'Silicon Graphics' 'Kilgard'; do
    if grep "$probe" "$UNPACK/$DOC/NOTICE" > /dev/null; then
        note "ok   NOTICE keeps: $probe"
    else
        bad "NOTICE lost: $probe"
    fi
done
for f in LICENSE NOTICE PORT-NOTES.md; do
    case "$f" in
    PORT-NOTES.md) srcf="$SRC/release-packaging/PORT-NOTES.md" ;;
    *)             srcf="$SRC/$f" ;;
    esac
    if cmp -s "$srcf" "$UNPACK/$DOC/$f"; then
        note "ok   $f is byte-for-byte with the source copy"
    else
        bad "$f differs from the source copy -- rebuild the package"
    fi
done

n=`wc -l < "$FAILS"`
if [ $n -eq 0 ]; then
    echo "VERIFY_ACCEL_PKG=PASS"
else
    echo "VERIFY_ACCEL_PKG=FAIL ($n)"
    exit 1
fi
