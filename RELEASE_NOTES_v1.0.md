# OPENSTEP Radeon 9250 display driver 1.0

The first release: a DriverKit display driver for the PCI ATI Radeon 9250
(RV280) on OPENSTEP 4.2/Intel, and a Mesa 3.4.2 back end that draws on the
card's 3D engine.  Install with `Installer.app`; `release-packaging/INSTALL.md`
has the order and the recovery route.

| Asset | Package |
| --- | --- |
| `OpenStep-Radeon9250-1.0-i486-Display.pkg.tar.gz` | `OSRDNDisplay` 1.0 -- the driver |
| `OpenStep-Radeon9250-1.0-i486-MesaAccel.pkg.tar.gz` | `OSRDNMesaAccel` 1.0 -- `libGL_radeon.a` and its headers |
| `OpenStep-Mesa-3.4.2-openstep.1-rdn.1-i486-Demos.pkg.tar.gz` | `OpenStepMesa342DemosRDN` -- the Mesa port's demos plus two Radeon demos |

## What it does

- Five resolutions (640x480 to 1600x1200) in four formats (RGB:888/32,
  RGB:555/16, RGB:256/8, BW:8), with a Gray Levels setting for greyscale in
  the Configure inspector.
- A command processor on a ring with the chip's own PCI GART, and a kernel
  verifier every client stream passes before it reaches the ring.
- 3D through OSMesa: flat and Gouraud shading, four depth functions, three
  blend pairs, the alpha test, one 2D texture with REPLACE or MODULATE and
  all four mipmap filters (the two level-blending ones sent as their
  level-selecting counterparts -- a documented approximation; the card stops
  on the others).  Everything else falls back to Mesa, per triangle.
- For SDL2 programs, a present path that puts a frame on the screen with one
  video-memory blit.

## Measured

GLQuake (sdl2quake-openstep 1.3's `glquake_radeon`, LibreQuake data,
640x480): `timedemo demo1` 4,527 frames in 111.7 s -- **40.5 fps**; the
start map's world at 15.1 ms a frame.  The SDL2 teapot at 800x600: 32.07 fps
through the present path against 11.66 in software (before the G5 work).

## What the release is

- The driver (stamp `e09f4f8b`, build `790662775`) is the one every G5
  measurement ran on plus one method: the first program that opens the card
  after a boot makes the driver bring the command processor up
  (`RDN-R5 autostart`), with the six operations, in the order, that the
  measurements' privileged tool used.  Before that, an installed driver never
  accelerated anything for anyone who did not have that tool.
- `libGL_radeon.a` (build `790662776`) is the measured library plus one
  change: without `RDNMesaSeed` its submission seeds start from the clock
  instead of 1, so a program that follows one which submitted exactly once is
  no longer refused its first batch.
- The package makes `/dev/rdnvram0` (c 38 0) with mode 666 -- every user may
  draw with the card, and every user who can open it can also crash the
  machine through a defect in the kernel's mmap (`INSTALL.md`).
- Checked on the machine by installing the packages with Installer.app,
  rebooting, and using nothing else, the first client an ordinary user's:
  the command processor came up on that first open, the teapot put all 6,400
  triangles on the card, the seed probe ran three times back to back without
  a refusal, and `glquake_radeon` ran 300 frames with no triangle in software,
  none lost and no stall.
- The packaging verifiers compare every shipped document, header and demo
  source with its source copy, run the demo pair (the hybrid teapot with
  acceleration off writes the stock picture byte for byte), and check that no
  file is claimed by two packages across this project, the Matrox driver and
  the Mesa port.

## Known limits

- The command processor stopped three times in about 93,000 accepted
  submissions; the driver recovered each time, losing one batch (a ~110 ms
  hitch).  The cause is open.
- In present mode the scene is drawn upside down so one blit can deliver it;
  anything that falls back to Mesa's software then lands upside down too
  (none in GLQuake's ordinary path).
- 3D needs a board reporting 128 MiB; on a smaller one the driver declines
  the 3D window and the display still works.
- Tested on one card (1002:5960 rev 1, 128 MiB) in one machine.  1280x1024
  and 1600x1200 were never booted -- there was no monitor for them.

## Requirements

OPENSTEP 4.2 on Intel; the Mesa port's Libraries and Headers
(`3.4.2-openstep.1`) for building against the library; SDL2 openstep.4 for
the SDL2 path.
