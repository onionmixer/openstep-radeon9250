# The Utah teapot, drawn by the Radeon 9250

Mesa's evaluators make the geometry, Mesa's lighting colours the vertices,
`libGL_radeon.a` sends the triangles to the RV280's 3D engine, and the
finished picture is written as a PPM file. It renders offscreen -- this Mesa
is from 2001 and its accelerated path is OSMesa, which has no window-system
binding. You run the program, it writes an image, you look at the image.

## Two binaries, one source

| | needs | what it proves |
| --- | --- | --- |
| **`rdnteapot_sw`** | Mesa only | Mesa works. It links the stock library and `osrdn-mesa-nocount.c`, a file of counters that all read 0 -- no hook, probe or device code. |
| **`rdnteapot_hybrid`** | nothing to RUN | the acceleration works, or says why it does not |

`rdnteapot_hybrid` draws each triangle on the card where it can and in Mesa
where it cannot, and prints the split. The library is statically linked into
it, so it also runs with no driver: the probe answers "no device" and Mesa
draws everything. Running both tells you at once whether a problem is Mesa's
or the driver's.

## Running

```
./rdnteapot_sw     [width height [grid [file.ppm [cull]]]]
./rdnteapot_hybrid [width height [grid [file.ppm [cull]]]]
```

Defaults are 64 64 10 teapot.ppm. `RDNMesaAccelOff=1` in the environment
turns the acceleration off in `rdnteapot_hybrid` (any value; no value turns it
on).

## Rebuilding

```
csh -f build-teapot.csh [-sw | -hybrid] /LocalDeveloper /path/to/Mesa-3.4.2
```

Needs `OpenStepMesa342Libraries` and `OpenStepMesa342Headers` (for `-sw`) and
`OSRDNMesaAccel` (for `-hybrid`) at the prefix, and a Mesa 3.4.2 SOURCE tree:
the teapot geometry is cut from `widgets-mesa/demos/tea.c`, lines 581-730, at
build time instead of being kept here. That block is under SGI's 1993
permissive grant (Copyright (c) Mark J. Kilgard, 1994); `NOTICE` reproduces
the notice the grant requires. The prebuilt binaries need no Mesa tree.
