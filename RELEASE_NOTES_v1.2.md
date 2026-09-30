# OPENSTEP Radeon 9250 display driver 1.2

A fix release of the driver, for two things seen on the screen with 1.1:

- **the boot's colour test pattern showed through** while the login panel
  came up;
- **the picture sat to the right**: a black band on the left and the
  rightmost pixels cut off, at 800x600 and 1024x768 alike.

| Asset | Package |
| --- | --- |
| `OpenStep-Radeon9250-1.2-i486-Display.pkg.tar.gz` | `OSRDNDisplay` 1.2 -- the driver |
| `OpenStep-Radeon9250-1.0-i486-MesaAccel.pkg.tar.gz` | `OSRDNMesaAccel` 1.0 -- unchanged, `libGL_radeon.a` 790662776 |
| `OpenStep-Mesa-3.4.2-openstep.1-rdn.1-i486-Demos.pkg.tar.gz` | `OpenStepMesa342DemosRDN` -- unchanged |

Install `OSRDNDisplay` 1.2 over 1.1 with `Installer.app` and reboot; your
settings are kept (`INSTALL.md`).  The library and demos are the 1.0
packages, byte for byte.

## The test pattern

The mode set drew a pattern of colour bands and corner marks over the whole
framebuffer and held it for two seconds -- a first-light check for the
operator, left in.  Nothing cleared it, so it stayed wherever the window
server had not drawn yet.  The boot now writes black instead, and does not
wait.  (Black is zero in every format at that point: 16 and 32 bpp are
direct colour, and the 8-bit table the mode set loads is the identity.)

## The horizontal position

The CRTC's sync start is the one every reference computes -- NetBSD
`radeonfb`, xf86-video-ati's legacy CRTC code and Linux KMS all write the
mode's sync start minus 8, and 1.1 wrote the same.  On this board, through
the same capture that showed a G450 centred, the picture still came out
about 13 pixels right at 800x600.  1.2 starts the sync later by a number of
pixels, the same for every mode:

- the default is **7**, set on the machine by moving the sync live while
  looking at the picture: 0 left a band on the left, 13 one on the right, 7
  neither;
- **Configure.app** has a new *H position* slider (-16 to 48) above *Gray
  levels*.  It writes `"RDN HSync Adjust"` to the instance table and takes
  effect at the next boot, like the other settings;
- a key that is not a whole number from -16 to 48 is refused and the default
  used (`RDN-REL3 hsync ... adj= kbad=1`); a value that would move the sync
  out of a mode's blanking is not applied to that mode, which then gets the
  reference's sync (the `hs=` field of `RDN-R2B waits enter` shows the value
  and whether it was refused).

A different monitor or capture may want another value; the slider is for
that.

The OPENSTEP boot and shutdown screens are not changed.  They are the VGA
mode the BIOS and the kernel set, before this driver loads and after it has
put the console back exactly as it found it; on the same capture they show
the same band as the 1.1 desktop did.

## Checked on the machine

The value was found live at 800x600 RGB:888/32 with a calibration tool
(0, 13, then 7), then held through a reboot with the table key set to 7:
login screen with no band on either side, boot and shutdown screens as
before.  Then this build, with default 7, installed over it with the key
removed: the driver logged `adj=7 kbad=0`, the card read back the sync
word as the table's plus 7 (`00100347`), and Configure's slider showed 7.

Build: stamp ddbbfa6c, runid 790772415, relocatable BSD sum `00799 535`.
The undefined symbols are 1.1's, the same 21.

## Known limits

As 1.0 (`RELEASE_NOTES_v1.0.md`): the rare command-processor stall (cause
open, recovered by the driver), present mode's upside-down software
fallbacks, 128 MiB for 3D, one card tested, 1280x1024 and 1600x1200 never
booted.  The horizontal default was set at 800x600 RGB:888/32 only; the
other modes use the same number of pixels, not yet looked at.
