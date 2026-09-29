#!/bin/sh
# Stage the Radeon demos as an OVERLAY tree for the Mesa port's Demos variant.
#
#   sh .../pkg/build-demos-overlay.sh <library runid> [source-root] [mesa-repo] [out]
#
# The shape is openstep-matrox-remade's pkg/build-demos-overlay.sh.  The Mesa
# builder copies the tree into its Demos payload and packages it under
# OpenStepMesa342DemosRDN.info when MESA_DEMO_VARIANT=RDN.
#
# Both demos are BUILT here with the very scripts that ship beside them, from
# a private prefix laid out the way the packages lay out /LocalDeveloper --
# so a build script that drifted from its source, or a header the
# acceleration package forgot, fails the packaging instead of a user.
#
#   Examples/Mesa342/RDNTeapot     source, script, README, NOTICE, COPYRIGHT,
#                                  rdnteapot_sw and rdnteapot_hybrid
#   Examples/Mesa342/RDNSDLTeapot  source, script, README, NOTICE, COPYRIGHT
#                                  (built here to check it, shipped as source)
set -e
LIBRUN="${1:-}"
SRC="${2:-/ndrv/openstep-radeon9250}"
MESA="${3:-/ndrv/openstep-mesa342}"
OUT="${4:-/tmp/_rdnteapot/overlay}"
MESASRC="$MESA/upstream/Mesa-3.4.2"
PREFIX=/tmp/_rdnteapot/prefix
LD=/LocalDeveloper
LIB="$SRC/build/m1b/$LIBRUN/libGL_radeon.a"
T="$OUT/Examples/Mesa342/RDNTeapot"
S="$OUT/Examples/Mesa342/RDNSDLTeapot"
HEADERS="OSRDNMesaClass.h OSRDNMesaDepth.h OSRDNMesaHook.h OSRDNMesaPresent.h
OSRDNMesaProbe.h OSRDNMesaSurface.h OSRDNMesaTex.h OSRDNMesaTime.h
OSRDNMesaTri.h OSRDNMesaTriTable.h"

# `| wc -l`, not grep -c: under set -e a count of 0 exits the script with
# nothing said (recorded trap).  wc pads, so the test is numeric.
ok=`echo "$LIBRUN" | grep '^[0-9][0-9]*$' | wc -l`
if [ $ok -ne 1 ]; then
    echo "usage: build-demos-overlay.sh <library runid> [source-root] [mesa-repo] [out]" >&2
    exit 2
fi
if [ "`/usr/bin/arch`" != i386 ]; then
    echo "build-demos-overlay: the binaries are i386; build them on i386" >&2
    exit 1
fi
for f in "$SRC/test/osrdn-mesa-teapot.c" "$SRC/test/osrdn-mesa-nocount.c" \
         "$SRC/test/osrdn-sdl-teapot.c" \
         "$SRC/examples/build-teapot.csh" "$SRC/examples/README_teapot.md" \
         "$SRC/examples/build-sdl-teapot.csh" "$SRC/examples/README_sdlteapot.md" \
         "$SRC/NOTICE" "$LIB" "$SRC/build/m1b/$LIBRUN/M1B_PASS" \
         "$MESASRC/docs/COPYRIGHT" "$MESASRC/widgets-mesa/demos/tea.c" \
         "$LD/Libraries/libGL.a" "$LD/Libraries/libSDL2.a" \
         "$LD/Headers/SDL2/SDL.h" "$LD/Headers/SDL2/SDL_openstepglpresent.h"; do
    if [ ! -s "$f" ]; then
        echo "build-demos-overlay: missing input: $f" >&2
        exit 1
    fi
done
want=`cat "$SRC/build/m1b/$LIBRUN/M1B_PASS"`
have=`/usr/bin/sum "$LIB" | awk '{print $1, $2}'`
if [ "$want" != "$have" ]; then
    echo "build-demos-overlay: the library is not the bytes the host judged" >&2
    exit 1
fi

# the private prefix: what the three packages put at /LocalDeveloper
rm -rf "$PREFIX" "$OUT" "$OUT.library"
/bin/mkdirs "$PREFIX/Libraries" "$PREFIX/Headers/GL" "$PREFIX/Headers/SDL2" "$T" "$S"
cp "$LD/Libraries/libGL.a" "$LD/Libraries/libSDL2.a" "$PREFIX/Libraries/"
cp "$LIB" "$PREFIX/Libraries/libGL_radeon.a"
cp "$MESASRC/include/GL/gl.h" "$MESASRC/include/GL/glext.h" \
   "$MESASRC/include/GL/osmesa.h" "$PREFIX/Headers/GL/"
for h in $HEADERS; do cp "$SRC/mesa/$h" "$PREFIX/Headers/$h"; done
( cd "$LD/Headers/SDL2" && tar cf - . ) | ( cd "$PREFIX/Headers/SDL2" && tar xf - )
ranlib "$PREFIX/Libraries/libGL.a" "$PREFIX/Libraries/libGL_radeon.a" "$PREFIX/Libraries/libSDL2.a"

# --- the teapot ---
cp "$SRC/test/osrdn-mesa-teapot.c" "$SRC/test/osrdn-mesa-nocount.c" \
   "$SRC/examples/build-teapot.csh" "$SRC/examples/README_teapot.md" "$T/"
cp "$SRC/NOTICE" "$T/NOTICE"
cp "$MESASRC/docs/COPYRIGHT" "$T/COPYRIGHT"
cmp "$MESASRC/docs/COPYRIGHT" "$T/COPYRIGHT"
( cd "$T" && csh -f build-teapot.csh "$PREFIX" "$MESASRC" )
for b in rdnteapot_sw rdnteapot_hybrid; do
    if [ ! -x "$T/$b" ]; then
        echo "build-demos-overlay: $b was not built" >&2
        exit 1
    fi
    if file "$T/$b" | grep i386 > /dev/null; then :; else
        echo "build-demos-overlay: $b is not i386 Mach-O" >&2
        exit 1
    fi
    chmod 555 "$T/$b"
done
chmod 555 "$T/build-teapot.csh"
# The stock form carries no Radeon library.  NOT judged by OSRDN names: the
# stock form links osrdn-mesa-nocount.c, whose counter stubs carry them.  The
# library's own mark is the hook entry OSMesa calls, which stock osmesa.o
# (built without the hook macro) never defines or references.
if nm "$T/rdnteapot_sw" | grep ' T _OpenStepMesaAccelBuffer$' > /dev/null; then
    echo "build-demos-overlay: rdnteapot_sw carries the Radeon library" >&2
    exit 1
fi
if nm "$T/rdnteapot_hybrid" | grep ' T _OpenStepMesaAccelBuffer$' > /dev/null; then :; else
    echo "build-demos-overlay: rdnteapot_hybrid does not carry the Radeon library" >&2
    exit 1
fi
rm -f "$T/teapot-geometry.h"

# --- the SDL2 teapot: built to check the shipped script, shipped as source ---
cp "$SRC/test/osrdn-sdl-teapot.c" "$SRC/examples/build-sdl-teapot.csh" \
   "$SRC/examples/README_sdlteapot.md" "$S/"
cp "$SRC/NOTICE" "$S/NOTICE"
cp "$MESASRC/docs/COPYRIGHT" "$S/COPYRIGHT"
cmp "$MESASRC/docs/COPYRIGHT" "$S/COPYRIGHT"
chmod 555 "$S/build-sdl-teapot.csh"
( cd "$S" && csh -f build-sdl-teapot.csh "$PREFIX" "$MESASRC" )
for b in rdnsdlteapot_sw rdnsdlteapot_hybrid; do
    if [ ! -x "$S/$b" ]; then
        echo "build-demos-overlay: $b was not built" >&2
        exit 1
    fi
done
if nm "$S/rdnsdlteapot_sw" | grep ' T _OpenStepMesaAccelBuffer$' > /dev/null; then
    echo "build-demos-overlay: rdnsdlteapot_sw carries the Radeon library" >&2
    exit 1
fi
if nm "$S/rdnsdlteapot_hybrid" | grep ' T _OpenStepMesaAccelBuffer$' > /dev/null; then :; else
    echo "build-demos-overlay: rdnsdlteapot_hybrid does not carry the Radeon library" >&2
    exit 1
fi
rm -f "$S/rdnsdlteapot_sw" "$S/rdnsdlteapot_hybrid" "$S/teapot-geometry.h"

# the library the binaries were linked with -- OUTSIDE the overlay, which the
# Mesa builder copies into the payload whole
echo "$LIBRUN $have" > "$OUT.library"
echo "build-demos-overlay: PASS $OUT (library runid $LIBRUN)"
