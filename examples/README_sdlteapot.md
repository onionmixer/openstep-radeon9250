# The Utah teapot through SDL2, on the Radeon 9250

The same teapot drawn through SDL2 in a window, to show what SDL2's delivery
costs on this card and what happens when a program stops paying it.

The source is `openstep-matrox-remade`'s SDL2 teapot with its library names
mapped onto this project's (the top of `osrdn-sdl-teapot.c` shows the
mapping). It uses no Matrox header or library; the `OSMGA_*` macro names in
it are that source's own.

## Building

```
csh -f build-sdl-teapot.csh [-sw | -hybrid] /LocalDeveloper /path/to/Mesa-3.4.2
```

| package at the prefix | why |
| --- | --- |
| `OpenStepSDL2Libraries`, `OpenStepSDL2Headers` | SDL2 openstep.4 was the one checked; it carries `SDL_openstepglpresent.h` |
| `OpenStepMesa342Libraries`, `OpenStepMesa342Headers` | `rdnsdlteapot_sw` |
| `OSRDNMesaAccel` | `rdnsdlteapot_hybrid` |

The Mesa source tree is needed only for the teapot's control points, cut at
build time; `NOTICE` says whose they are. The package ships this demo as
source and build script: the build is checked when the package is made.

## Running

```
./rdnsdlteapot_sw     [width height]
OSRDN_SDLTEAPOT_PRESENT=3 ./rdnsdlteapot_hybrid [width height]
```

`OSRDN_SDLTEAPOT_FRAMES=<n>` sets the number of frames. With
`OSRDN_SDLTEAPOT_PRESENT=3` the program registers the driver's present
functions with SDL2 and each frame goes to the screen by one video-memory blit
instead of being read back into system memory. The hybrid binary needs the
driver for that delivery.

Measured on this card at 800x600 (docs/G3B_CLEAR_PLAN.md, before the G5
improvements): software 11.66 frames a second, read-back delivery 0.85,
present delivery 32.07.
