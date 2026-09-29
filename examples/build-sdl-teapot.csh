#!/bin/csh -f
#
# Build the Radeon SDL2 teapot -- both binaries, or one of them.
#
#   csh -f build-sdl-teapot.csh [-sw | -hybrid] [prefix] <mesa-source-root>
#
# The same Utah teapot through SDL2, and what SDL2's delivery costs:
#
#   rdnsdlteapot_sw       stock libGL.a.  No Radeon code at all
#                         (-DOSMGA_SDLTEAPOT_PLAIN: the counters are constants).
#   rdnsdlteapot_hybrid   libGL_radeon.a.  The card draws; with
#                         OSRDN_SDLTEAPOT_PRESENT=3 the program registers the
#                         driver's present functions with SDL2 and each frame
#                         goes to the screen by one video-memory blit.
#
#   rdnsdlteapot_* [width height]      OSRDN_SDLTEAPOT_FRAMES=<n> frames
#
# The source is openstep-matrox-remade's SDL2 teapot with its library names
# mapped onto this project's (see the top of osrdn-sdl-teapot.c); it uses no
# Matrox header or library.  The OSMGA_* macro names inside it are that
# source's own, kept so the two demos differ only in what they link.
#
# THIS ONE NEEDS SDL2 (openstep-sdl2, checked with openstep.4) at the same
# prefix: OpenStepSDL2Libraries and OpenStepSDL2Headers, which carry
# SDL_openstepglpresent.h.
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
if ("$mesasrc" == "") then
    if ($?MESASRC) then
        set mesasrc = "$MESASRC"
    endif
endif

if ("$mesasrc" == "" || ! -r "$mesasrc/widgets-mesa/demos/tea.c") then
    echo "build-sdl-teapot: need a Mesa 3.4.2 source tree for the teapot geometry"
    echo "build-sdl-teapot: usage: csh -f build-sdl-teapot.csh [-sw|-hybrid] [prefix] <mesa-source-root>"
    exit 1
endif
if (! -r $prefix/Libraries/libSDL2.a || ! -r $prefix/Headers/SDL2/SDL.h) then
    echo "build-sdl-teapot: no SDL2 at $prefix"
    echo "build-sdl-teapot: install OpenStepSDL2Libraries and OpenStepSDL2Headers"
    exit 1
endif

sed -n '581,730p' "$mesasrc/widgets-mesa/demos/tea.c" > teapot-geometry.h
if ($status != 0) exit 1
grep cpdata teapot-geometry.h > /dev/null
if ($status != 0) then
    echo "build-sdl-teapot: the cut produced no control points -- is this Mesa 3.4.2?"
    exit 1
endif

# -m486 and -D__OPENSTEP__ are SDL2's: its public headers do not parse for
# this compiler without the second, and the archive is built with the first.
set sdlflags = "-m486 -D__OPENSTEP__ -I$prefix/Headers/SDL2"
set frameworks = "-framework AppKit -framework Foundation -framework SoundKit"

if ("$want" == "both" || "$want" == "sw") then
    if (! -r $prefix/Libraries/libGL.a) then
        echo "build-sdl-teapot: no $prefix/Libraries/libGL.a"
        echo "build-sdl-teapot: install OpenStepMesa342Libraries at $prefix"
        exit 1
    endif
    cc -O $sdlflags -I$prefix/Headers -I. -DOSMGA_SDLTEAPOT_PLAIN \
        osrdn-sdl-teapot.c $prefix/Libraries/libSDL2.a \
        $prefix/Libraries/libGL.a -lm $frameworks -o rdnsdlteapot_sw
    if ($status != 0) exit 1
    echo "build-sdl-teapot: PASS ./rdnsdlteapot_sw (stock Mesa)"
endif

if ("$want" == "both" || "$want" == "hybrid") then
    if (! -r $prefix/Libraries/libGL_radeon.a) then
        echo "build-sdl-teapot: no $prefix/Libraries/libGL_radeon.a"
        echo "build-sdl-teapot: install OSRDNMesaAccel at $prefix, or use -sw"
        exit 1
    endif
    cc -O $sdlflags -I$prefix/Headers -I. osrdn-sdl-teapot.c \
        $prefix/Libraries/libSDL2.a $prefix/Libraries/libGL_radeon.a -lm \
        $frameworks -o rdnsdlteapot_hybrid
    if ($status != 0) exit 1
    echo "build-sdl-teapot: PASS ./rdnsdlteapot_hybrid (the card draws)"
endif
