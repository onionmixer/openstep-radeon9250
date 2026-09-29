# OSRDNMesaAccel — what this package adds, and what it does not

This package puts the ATI Radeon 9250 back end for the OPENSTEP Mesa 3.4.2
port on a development prefix.  It is a library and its headers; the driver
it talks to is the separate `OSRDNDisplay` package.

## It adds a second library; it replaces nothing

`Libraries/libGL_radeon.a` is a COMPLETE alternative libGL: the stock
`libGL.a` with `osmesa.o` replaced by one compiled with the hook macro
(`-DOPENSTEP_MESA_ACCEL_HOOK`) and one object of this project's added,
`osrdnaccel.o`.  It sits beside `libGL.a` and `libGLU.a`, never over them.
A program that links `-lGL` gets stock Mesa exactly as before; a program
that links `libGL_radeon.a` gets the card.

## The Mesa source carries the hook points, dormant

The hook sites are in the Mesa port's own `src/OSmesa/osmesa.c`, behind the
macro above, which the port's own build never defines -- so its released
libraries contain none of them.  The same hooks serve the Matrox G450 back
end (`libGL_mga.a`).  This release was built from the port at commit
`f2ab89f`, which offers a back end a video-memory surface only for the three
four-byte pixel formats (RGBA, BGRA, ARGB); an RGB, BGR or colour-index
context draws in its own buffer, in software.

## What an application does

Link the archive instead of `-lGL`:

```
cc -m486 -I/LocalDeveloper/Headers prog.c \
   /LocalDeveloper/Libraries/libGL_radeon.a -lm -o prog
```

An offscreen OSMesa program needs nothing else: the picture is copied back
into its buffer at the points it could look.  An SDL2 program (SDL2
openstep.4) should also register the present functions from
`OSRDNMesaPresent.h` with `SDL_SetWindowData(window,
SDL_OPENSTEP_GLPRESENT_KEY, ...)`; each frame then reaches the screen by one
video-memory blit instead of a read-back.  `INSTALL.md` in the driver's
documentation shows the four lines.

## What the card draws

| | |
|---|---|
| shading | flat, Gouraud |
| depth | LESS, LEQUAL, GEQUAL, ALWAYS; writes on or off |
| blending | (SRC_ALPHA, 1-SRC_ALPHA), (ZERO, 1-SRC_COLOR), (ONE, ONE) |
| alpha test | all eight functions |
| texture | one 2D texture, RGB or RGBA, 8 to 512 and a power of two, REPEAT, REPLACE or MODULATE, NEAREST or LINEAR |
| mipmaps | all four MIN modes; the two level-BLENDING ones are sent as the level-selecting mode with the same texel filter |

Anything else -- fog, stencil, scissor, logic op, polygon smooth or
stipple, other blend pairs, other environments, wraps or sizes -- is drawn
by Mesa's software rasteriser, correctly and more slowly.

The mipmap substitution is a documented approximation: on this card the
level-blending modes stop the machine within a few submissions.

## Environment variables

| variable | |
|---|---|
| `RDNMesaAccelOff` | any value turns the card off (no value turns it on) |
| `RDNMesaSync=1` | wait for each submission to finish instead of only for its acceptance |
| `RDNMesaMip=0` | every mipmap mode in software |
| `RDNMesaMip=all` | **stops the machine** -- the level-blending modes as they are; a reproducer only |
| `RDNMesaTexVerify=1` | read every texture upload back in full (the default samples four corners) |
| `RDNMesaTime=1` | a per-frame time budget on stderr; `RDNMesaTimeSplit=N` splits it at the Nth present |
| `RDNMesaBatchWords=N` | a smaller batch ceiling (N >= 256), for measurement |

The library reads a few more, which exist for this project's own
measurements and are not meant for use.

## Known limits

- **Command processor stalls.**  In about 93,000 accepted submissions the CP
  stopped three times; the driver recovered each time (engine reset and CP
  restart) and one batch was lost, a hitch of about 110 ms.  The cause is
  open.
- **Present mode draws the scene upside down, on purpose**, so that one blit
  delivers a frame.  Anything that falls back to Mesa's software while
  present mode is on -- a refused triangle, a point, a line, a bitmap --
  lands upside down too.  In GLQuake's ordinary path there are none.
  `glReadPixels` reads the turned surface correctly.
- **3D needs 128 MiB** on the board; see the driver's `INSTALL.md`.

## Requirements

`OSRDNDisplay` installed and active; the Mesa port's Libraries and Headers
packages (`3.4.2-openstep.1`) at the same prefix; for the SDL2 path, SDL2
openstep.4.

## Licensing, and where the sources are

`libGL_radeon.a` contains Mesa code, so Mesa's own terms travel with it:
`Documentation/OpenStep-Radeon9250-Accel/Mesa-3.4.2/COPYRIGHT`, `COPYING`
and `README.Mesa` are copied byte for byte from the Mesa port's upstream
tree.

Which of those terms applies was checked member by member.  Mesa 3.4.2 is
not under one licence: `COPYRIGHT` records that the core library moved off
the GNU LGPL at Mesa 3.1 onto the XFree86 (MIT-style) grant, while GLU and
some drivers stayed LGPL.  The archive holds 84 members: the archive's own
symbol table, and 83 objects, every one of which comes from the port's
`src/`, `src/X86/` or `src/OSmesa/` except this project's `osrdnaccel.o`.
The Mesa ones fall under the Main Mesa Copyright (Brian Paul): notice
retention, discharged by the copied `COPYRIGHT`.  **No LGPL component is in
the archive** -- GLU is `libGLU.a`, which this package neither ships nor
touches.  `COPYING` ships anyway, because `COPYRIGHT` names it.  Mesa's
statement that it is not a licensed OpenGL implementation is in
`README.Mesa`.

The sources: the Mesa side is the Mesa port's own tree
(github.com/onionmixer/openstep-mesa342); this project's side is
github.com/onionmixer/openstep-radeon9250, BSD 2-Clause (`LICENSE`).
`NOTICE` carries what must travel with it -- the R200 CP microcode's MIT
notice (AMD), the provenance of the Configure inspector nib, and SGI's grant
covering the teapot geometry compiled into the demo binaries.
