#!/bin/sh
# Unpack the Mesa Demos RDN variant and check what is actually inside it.
#
#   sh .../pkg/verify-demos-rdn-pkg.sh [package-dir] [source-root] [mesa-repo]
#
# The shape is openstep-matrox-remade's pkg/verify-demos-mga-pkg.sh, plus one
# thing that one states as measured and this one runs every time: the hybrid
# teapot with acceleration switched off must write the same bytes as the
# stock one, so the pair really does separate a Mesa problem from a driver
# problem.
PKGDIR="${1:-/usr/local/mesastage/OpenStepMesa342/dist}"
SRC="${2:-/ndrv/openstep-radeon9250}"
MESA="${3:-/ndrv/openstep-mesa342}"
NAME=OpenStepMesa342DemosRDN
PKG="$PKGDIR/$NAME.pkg"
UNPACK=/tmp/_demosrdnverify
RUNDIR=/tmp/_demosrdnrun
MESADOCS="$MESA/upstream/Mesa-3.4.2/docs"
T=Examples/Mesa342/RDNTeapot
S=Examples/Mesa342/RDNSDLTeapot

FAILS=/tmp/_demosrdnverify.fails
rm -f "$FAILS"; : > "$FAILS"
note() { echo "  $1"; }
bad()  { echo "  FAIL: $1"; echo "$1" >> "$FAILS"; }

if [ ! -d "$PKG" ]; then
    echo "verify-demos-rdn-pkg: no $PKG" >&2
    echo "verify-demos-rdn-pkg: build it with pkg/build-demos-rdn-pkg.csh" >&2
    exit 1
fi

echo "package structure"
for f in "$NAME.tar.Z" "$NAME.bom" "$NAME.info" "$NAME.sizes" "$NAME.pre_install"; do
    if [ -r "$PKG/$f" ]; then note "ok   $f"; else bad "$f missing"; fi
done
if grep '^Version 3.4.2-openstep.1+rdn.1$' "$PKG/$NAME.info" > /dev/null; then
    note "ok   the .info version is the variant's"
else
    bad "the .info does not carry the variant's version"
fi
for f in $T/osrdn-mesa-teapot.c $T/osrdn-mesa-nocount.c $T/build-teapot.csh \
         $T/README_teapot.md $T/NOTICE $T/COPYRIGHT $T/rdnteapot_sw $T/rdnteapot_hybrid \
         $S/osrdn-sdl-teapot.c $S/build-sdl-teapot.csh $S/README_sdlteapot.md \
         $S/NOTICE $S/COPYRIGHT; do
    if lsbom -s "$PKG/$NAME.bom" | grep "^\./$f\$" > /dev/null; then
        note "ok   the BOM owns $f"
    else
        bad "the BOM does not own $f"
    fi
done
for f in $S/rdnsdlteapot_sw $S/rdnsdlteapot_hybrid $T/teapot-geometry.h $S/teapot-geometry.h; do
    if lsbom -s "$PKG/$NAME.bom" | grep "^\./$f\$" > /dev/null; then
        bad "the BOM owns $f -- it must not ship"
    else
        note "ok   no $f, as intended"
    fi
done
# egrep, not grep: this grep has no alternation (recorded trap)
if lsbom -s "$PKG/$NAME.bom" | /usr/bin/egrep 'Examples/Mesa342/(Teapot|GLWindow)/' > /dev/null; then
    bad "the Matrox demos are in the Radeon variant"
else
    note "ok   no Matrox demo directories"
fi

rm -rf "$UNPACK"; /bin/mkdirs "$UNPACK"
( cd "$UNPACK" && /usr/ucb/zcat "$PKG/$NAME.tar.Z" | tar xf - )

echo "the plain Demos payload is still all there"
for f in Examples/Mesa342/OSMesaClear/osmesa-clear \
         Examples/Mesa342/OSMesaClear/osmesa-clear.c \
         Examples/Mesa342/MesaView/MesaView.app/MesaView \
         Tools/OpenStepMesa342Demos-Intel; do
    if [ -r "$UNPACK/$f" ]; then note "ok   $f"; else bad "$f missing"; fi
done

echo "it adds demos, not a library"
for d in Libraries Headers; do
    if [ -d "$UNPACK/$d" ]; then bad "$d is in the Demos payload"
    else note "ok   no $d"; fi
done

echo "one source, two DIFFERENT binaries"
for b in rdnteapot_sw rdnteapot_hybrid; do
    if [ -x "$UNPACK/$T/$b" ]; then note "ok   $b is executable"
    else bad "$b is not executable"; fi
    if file "$UNPACK/$T/$b" | grep i386 > /dev/null; then note "ok   $b is i386"
    else bad "$b is not i386 Mach-O"; fi
done
if nm "$UNPACK/$T/rdnteapot_sw" | grep ' T _OpenStepMesaAccelBuffer$' > /dev/null; then
    bad "rdnteapot_sw carries the Radeon library"
else
    note "ok   rdnteapot_sw carries no Radeon library"
fi
if nm "$UNPACK/$T/rdnteapot_hybrid" | grep ' T _OpenStepMesaAccelBuffer$' > /dev/null; then
    note "ok   rdnteapot_hybrid carries the Radeon library"
else
    bad "rdnteapot_hybrid does not carry the Radeon library"
fi

echo "the pair separates Mesa from the driver (run here, offscreen)"
rm -rf "$RUNDIR"; /bin/mkdirs "$RUNDIR"
( cd "$RUNDIR" && "$UNPACK/$T/rdnteapot_sw" 64 64 10 sw.ppm > sw.log 2>&1 )
( cd "$RUNDIR" && RDNMesaAccelOff=1 "$UNPACK/$T/rdnteapot_hybrid" 64 64 10 off.ppm > off.log 2>&1 )
if [ -s "$RUNDIR/sw.ppm" ] && [ -s "$RUNDIR/off.ppm" ]; then
    if cmp -s "$RUNDIR/sw.ppm" "$RUNDIR/off.ppm"; then
        note "ok   hybrid with RDNMesaAccelOff=1 writes the stock picture byte for byte"
    else
        bad "hybrid with acceleration off differs from the stock picture"
    fi
else
    bad "a teapot run wrote no picture (see $RUNDIR/*.log)"
fi
( cd "$RUNDIR" && "$UNPACK/$T/rdnteapot_hybrid" 64 64 10 card.ppm > card.log 2>&1 )
echo "  (for the record) the hybrid run on this machine:"
tail -5 "$RUNDIR/card.log" | sed 's/^/      /'

echo "the licence travels"
for d in $T $S; do
    if cmp -s "$MESADOCS/COPYRIGHT" "$UNPACK/$d/COPYRIGHT"; then note "ok   $d/COPYRIGHT is byte-for-byte"
    else bad "$d/COPYRIGHT differs from the port's own copy"; fi
    if cmp -s "$SRC/NOTICE" "$UNPACK/$d/NOTICE"; then note "ok   $d/NOTICE is byte-for-byte"
    else bad "$d/NOTICE differs from the source copy"; fi
done
for probe in 'Silicon Graphics' 'Kilgard' 'Permission to use'; do
    if grep "$probe" "$UNPACK/$T/NOTICE" > /dev/null; then note "ok   NOTICE keeps: $probe"
    else bad "NOTICE lost: $probe"; fi
done
for r in "$T/README_teapot.md" "$S/README_sdlteapot.md"; do
    if /usr/bin/egrep 'Kilgard|NOTICE' "$UNPACK/$r" > /dev/null; then note "ok   $r points at the geometry's notice"
    else bad "$r does not state the geometry's licence"; fi
done

echo "the shipped sources are current"
for pair in "$T osrdn-mesa-teapot.c test" "$T osrdn-mesa-nocount.c test" \
            "$T build-teapot.csh examples" "$T README_teapot.md examples" \
            "$S osrdn-sdl-teapot.c test" "$S build-sdl-teapot.csh examples" \
            "$S README_sdlteapot.md examples"; do
    d=`echo "$pair" | awk '{print $1}'`
    f=`echo "$pair" | awk '{print $2}'`
    w=`echo "$pair" | awk '{print $3}'`
    if cmp -s "$SRC/$w/$f" "$UNPACK/$d/$f"; then
        note "ok   $d/$f is byte-for-byte with $w/$f"
    else
        bad "$d/$f differs from $w/$f -- rebuild the overlay and the package"
    fi
done

n=`wc -l < "$FAILS"`
if [ $n -eq 0 ]; then
    echo "VERIFY_DEMOS_RDN_PKG=PASS"
else
    echo "VERIFY_DEMOS_RDN_PKG=FAIL ($n)"
    exit 1
fi
