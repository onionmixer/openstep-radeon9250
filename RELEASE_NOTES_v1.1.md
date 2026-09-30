# OPENSTEP Radeon 9250 display driver 1.1

A fix release of the driver.  **With 1.0, a GL program that was the first
to use the card after a boot and never cleared on the card — GLQuake is
exactly that — kept running, played its sound, answered its keys, and never
changed on screen after its loading console.**  Every present was counted
as done.

| Asset | Package |
| --- | --- |
| `OpenStep-Radeon9250-1.1-i486-Display.pkg.tar.gz` | `OSRDNDisplay` 1.1 -- the driver |
| `OpenStep-Radeon9250-1.0-i486-MesaAccel.pkg.tar.gz` | `OSRDNMesaAccel` 1.0 -- unchanged, `libGL_radeon.a` 790662776 |
| `OpenStep-Mesa-3.4.2-openstep.1-rdn.1-i486-Demos.pkg.tar.gz` | `OpenStepMesa342DemosRDN` -- unchanged |

Install `OSRDNDisplay` 1.1 over 1.0 with `Installer.app` and reboot; your
settings are kept (`INSTALL.md`).  The library and demos are the 1.0
packages, byte for byte.

## What was wrong

The present blit puts a frame from the 3D window onto the screen through
the command processor.  It carried the blit itself — source, destination,
size, the GMC word — but not the 2D state such a blit depends on: the
default scissor, the write mask, the direction.  That is the reference's
shape: the DRM's swap (`radeon_cp_dispatch_swap`) sends the same words and
leaves the rest to the X server, and the X driver writes that state again
after `DRM_RADEON_CP_INIT`, because, in its own words, the CP init "does an
engine reset, which resets some engine registers back to their default
values" (xf86-video-ati `radeon_dri.c` 1219–1221).  There is no X server
here, and this driver's own command-processor start resets the engine.  The
one thing that wrote the state back was the card clear — so a program that
cleared (the teapot, the SDL demos) made every later present work, and a
program that did not presented into a scissor of nothing.

Every measurement behind 1.0 had run the teapot earlier in the same boot,
which is why none of them saw it.

## What changed

The present blit now carries the three itself, before the GMC word, with
the values the clear already used and the X driver's EXA copy writes before
every copy (`radeon_exa_funcs.c` 107–114): `DEFAULT_SC_BOTTOM_RIGHT` at its
maximum, `DP_WRITE_MASK` all ones, `DP_CNTL` left-to-right, top-to-bottom.
13 words become 19 (32 on the ring).  Because every present carries them, a
recovery that resets the engine mid-run is covered too.

Nothing else in the driver changed: the relocatable differs from 1.0's by
the present words and its build stamp (fb454446, runid 790754867), the
version tables say 1.1, and the undefined symbols
are 1.0's, the same 21.

## Checked on the machine

After installing 1.1 and rebooting, with no teapot and no clear in that
boot, GLQuake (`glquake_radeon`, sdl2quake 1.4) as the first program to use
the card: it reached the game screen.  Under 1.0, the same start stayed on
the loading console every time, including straight after a reboot and with
builds linked against two different SDL2 releases.  Then the teapot, then
GLQuake again: the game screen, as before.

## Known limits

As 1.0 (`RELEASE_NOTES_v1.0.md`): the rare command-processor stall (cause
open, recovered by the driver), present mode's upside-down software
fallbacks, 128 MiB for 3D, one card tested, 1280x1024 and 1600x1200 never
booted.
