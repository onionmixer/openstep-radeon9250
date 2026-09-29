#!/bin/csh -f
#
# Build the Radeon teapot demo -- both binaries, or one of them.
#
#   csh -f build-teapot.csh [-sw | -hybrid] [prefix] <mesa-source-root>
#
# ONE SOURCE, TWO BINARIES (the shape of openstep-matrox-remade's teapot).
#
#   rdnteapot_sw       the STOCK Mesa library, plus osrdn-mesa-nocount.c --
#                      a file of counters that all read 0, so the one source
#                      can report without the accelerated library.  It
#                      contains no hook, no probe and no device code.  If this
#                      one draws a teapot, Mesa works.
#   rdnteapot_hybrid   libGL_radeon.a from OSRDNMesaAccel.  The card draws the
#                      triangles it can take and Mesa the rest, and the report
#                      says which.  Without the driver the probe answers "no
#                      device" and the whole scene goes to Mesa.
#
#   rdnteapot_* [width height [grid [file.ppm [cull]]]]   default 64 64 10 teapot.ppm
#
# THE GEOMETRY FILE IS NOT SHIPPED, but the geometry itself is -- inside both
# prebuilt binaries.  It is cut from Mesa 3.4.2's widgets-mesa/demos/tea.c,
# lines 581-730, which lie in the block under SGI's 1993 permissive grant
# (Copyright (c) Mark J. Kilgard, 1994); NOTICE reproduces the notice.  The
# prebuilt binaries beside this script need no Mesa tree.
#
set want = both
set prefix = /LocalDeveloper
set mesasrc = ""
set argi = 1
if ($#argv >= 1) then
    if ("$argv[1]" == "-sw") then
        set want = sw
        set argi = 2
    else if ("$argv[1]" == "-hybrid") then
        set want = hybrid
        set argi = 2
    endif
endif
if ($#argv >= $argi) set prefix = "$argv[$argi]"
@ argi = $argi + 1
if ($#argv >= $argi) set mesasrc = "$argv[$argi]"
# csh evaluates both sides of &&, so an unset variable inside a compound
# condition is an error rather than a false; and a one-line `if` substitutes
# the trailing command's variables before it tests.  Block form, own line.
if ("$mesasrc" == "") then
    if ($?MESASRC) then
        set mesasrc = "$MESASRC"
    endif
endif

if ("$mesasrc" == "" || ! -r "$mesasrc/widgets-mesa/demos/tea.c") then
    echo "build-teapot: need a Mesa 3.4.2 source tree for the teapot geometry"
    echo "build-teapot: usage: csh -f build-teapot.csh [-sw|-hybrid] [prefix] <mesa-source-root>"
    echo "build-teapot: (the prebuilt binaries beside this script need none)"
    exit 1
endif

sed -n '581,730p' "$mesasrc/widgets-mesa/demos/tea.c" > teapot-geometry.h
if ($status != 0) exit 1
grep cpdata teapot-geometry.h > /dev/null
if ($status != 0) then
    echo "build-teapot: the cut produced no control points -- is this Mesa 3.4.2?"
    exit 1
endif

if ("$want" == "both" || "$want" == "sw") then
    if (! -r $prefix/Libraries/libGL.a) then
        echo "build-teapot: no $prefix/Libraries/libGL.a"
        echo "build-teapot: install OpenStepMesa342Libraries at $prefix"
        exit 1
    endif
    cc -m486 -O -I$prefix/Headers -I. osrdn-mesa-teapot.c osrdn-mesa-nocount.c \
        -L$prefix/Libraries -lGL -lm -o rdnteapot_sw
    if ($status != 0) exit 1
    echo "build-teapot: PASS ./rdnteapot_sw (stock Mesa)"
endif

if ("$want" == "both" || "$want" == "hybrid") then
    if (! -r $prefix/Libraries/libGL_radeon.a) then
        echo "build-teapot: no $prefix/Libraries/libGL_radeon.a"
        echo "build-teapot: install OSRDNMesaAccel at $prefix, or use -sw"
        exit 1
    endif
    cc -m486 -O -I$prefix/Headers -I. osrdn-mesa-teapot.c \
        $prefix/Libraries/libGL_radeon.a -lm -o rdnteapot_hybrid
    if ($status != 0) exit 1
    echo "build-teapot: PASS ./rdnteapot_hybrid (the card where it can, Mesa where it cannot)"
endif
