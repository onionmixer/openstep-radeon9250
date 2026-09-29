# Installing the Radeon 9250 driver on OPENSTEP 4.2

Three packages, and you do not need all of them.

| Package | What it gives you | Needed for |
| --- | --- | --- |
| `OSRDNDisplay` | the display driver: 640x480 through 1600x1200, 8/16/32-bit, and the command processor the 3D path uses | a working screen on a Radeon 9250 |
| `OSRDNMesaAccel` | `libGL_radeon.a` and its headers, into `/LocalDeveloper` | building programs that draw 3D on the card |
| `OpenStepMesa342DemosRDN` | the Mesa demos plus the Radeon teapot demos | seeing it work, and having an example to copy |

The driver is complete on its own.  The other two are for development, and
both need the driver installed **and active** before the card draws
anything for them.

## Before you start

- **A Radeon 9250, PCI.**  The driver matches `1002:5960` only.  It was
  developed and tested on one card, revision 1, with 128 MiB, in one machine.
  AGP cards are not a target.
- **128 MiB for 3D.**  The 3D window is laid out for 128 MiB; on a board
  that reports less, the driver declines the window at boot (the reason is
  in the log), the screen still works, and OpenGL programs draw in software.
- **Intel.**  Every package refuses to install on anything but i386.
- **Root.**  The driver package asks for authorisation.
- **A way back in.**  Read the recovery section below BEFORE you activate
  anything.  Activating a display driver is the one step here that can cost
  you the screen.

## 1. The driver

Open `OSRDNDisplay.pkg` in `/NextAdmin/Installer.app`, authorise, install.
It writes one bundle:

```
/private/Drivers/i386/OSRDNDisplay.config/
```

and its licence, notice and this guide under
`/usr/local/Documentation/OpenStep-Radeon9250/`.

**Installing does not activate.**  Nothing changes until you do step 2.

### The switches ship ON

The instance table carries five switches whose names are historical --
`RDN R2B0 Record`, `RDN Engine Test`, `RDN VRAM Mmap`, `RDN CP Test`,
`RDN 3D Test` -- and all five are `Yes`.  They are feature switches, not
diagnostics: the first is the master switch (without it the driver owns the
display and programs nothing), and the others bring up the engine window,
the video-memory device, the command processor and the 3D path.  Every
measurement behind this release ran with all five on, so that is what ships.
`Display Mode` ships as 1024x768 at 60 Hz, 32-bit.

### The 3D node, and who may use the card

The package makes `/dev/rdnvram0` (character, major 38, minor 0), which is
how programs reach the card, and makes it **readable and writable by every
user** (`crw-rw-rw-`): anyone logged in can run a program that draws with the
card.  The major comes from the bundle's `"Character Major"`, and the node is
remade on every install so the two always agree.

Know the price: OPENSTEP's kernel skips its own checks for a memory mapping of
2 GB or more, so **any user who can open this node can also crash the
machine**.  On a machine whose local users you do not trust, make the node
root's alone after installing (`chmod 600 /dev/rdnvram0`); programs run by
other users then draw in software.  Installing the package again remakes the
node with mode 666, so repeat the `chmod` after an upgrade.

### Installing again keeps your settings

The package preserves the instance tables already on the machine, byte for
byte, and then rewrites only the six keys that belong to the package
(`Driver Name`, `Server Name`, `Class Names`, `Family`, `Version`,
`Character Major`).  Your resolution, your switches and your `Location`
survive an upgrade.

## 2. Activating it, and getting back if it goes wrong

### First, save the file that decides

```
cp /private/Drivers/i386/System.config/Instance0.table \
   /private/Drivers/i386/System.config/Instance0.table.before-radeon
```

That file holds `"Active Drivers"`, the list of drivers the system loads at
boot.  Do the copy from a shell, before you touch anything.

**If the machine is on a network, know how to reach it now** -- `telnet` as
root, or another way in that does not involve looking at the screen.

### Then activate

In `Configure.app`, choose Display, add `OpenStep Radeon 9250 Display`,
save, and reboot.

### If the screen comes up black or scrambled

Nothing is damaged.  In order of preference:

1. **Type `config=Default` at the `boot:` prompt.**  The machine comes up on
   its original display configuration.
2. **Log in over the network**, restore the saved file, reboot:
   ```
   cp /private/Drivers/i386/System.config/Instance0.table.before-radeon \
      /private/Drivers/i386/System.config/Instance0.table
   reboot
   ```
3. **Boot from install media** and edit the file on the disk.

The bundle can stay installed; it is inert once its name is out of
`"Active Drivers"`.

### Choosing a resolution

`Display.modes` offers 20 combinations -- 640x480, 800x600, 1024x768,
1280x1024 and 1600x1200, each in 32-bit colour, 16-bit colour, 8-bit colour
and 8-bit greyscale, all at 60 Hz.  Greyscale additionally takes a **Gray
Levels** setting of 256, 16, 4 or 2 from the radio buttons in the same
inspector; all four are the same 8bpp scanout and only the palette differs.

Booted and checked on this card: 800x600 in all four formats, 640x480 32-bit,
1024x768 32-bit and 1024x768 greyscale (16 levels).  **1280x1024 and
1600x1200 were never tried** -- there was no monitor for them -- although
their timings were checked against NetBSD's independently.  If a mode does
not come up, the way back is the same as above.

## 3. The acceleration package

Only after the driver is active and the screen is working.

Install `OSRDNMesaAccel.pkg`.  It is **relocatable**; `/LocalDeveloper` is
the default, matching the Mesa port's Libraries and Headers packages -- put
it where those went.  It adds `Libraries/libGL_radeon.a` BESIDE the stock
`libGL.a`; nothing of Mesa's is replaced.

A program chooses the card by linking the archive instead of `-lGL`:

```
cc -m486 -I/LocalDeveloper/Headers myprog.c \
   /LocalDeveloper/Libraries/libGL_radeon.a -lm -o myprog
```

It draws with whatever it can on the card and the rest in Mesa's software,
and runs without the driver too (everything in software).  Setting
`RDNMesaAccelOff` to any value turns the card off for one run.

Nothing has to be started by hand: the first program that opens the card
after a boot makes the driver bring its command processor up (one line,
`RDN-R5 autostart ... state=3`, in the system log says it did).  If it
cannot, programs draw in software and that line says why.

An SDL2 program (SDL2 openstep.4) gets the frame to the screen from video
memory by registering the present functions once:

```c
#include <SDL_openstepglpresent.h>
#include "OSRDNMesaPresent.h"

static const SDL_OpenStepGLPresent hooks = {
    SDL_OPENSTEP_GLPRESENT_ABI, sizeof(hooks),
    OSRDNMesaBufferOrigin, OSRDNMesaBufferPresentMode,
    OSRDNMesaBufferPresentRect
};
SDL_SetWindowData(window, SDL_OPENSTEP_GLPRESENT_KEY, (void *)&hooks);
```

What the card draws, the environment variables and the known limits are in
`Documentation/OpenStep-Radeon9250-Accel/PORT-NOTES.md`.  One of them bears
repeating here: **`RDNMesaMip=all` stops the machine** within a few
submissions on this card; it exists as a reproducer only.

## 4. The demos

`OpenStepMesa342DemosRDN.pkg` is the Mesa port's Demos package with two
directories added under `Examples/Mesa342/`: `RDNTeapot` (a file-writing
teapot, prebuilt twice -- stock and hybrid) and `RDNSDLTeapot` (an SDL2
window demo, as source and build script).  Install it instead of the plain
Demos package or the Matrox variant, not beside them: all three carry the
same Mesa demos.

## Removing

In Installer, delete the packages in the reverse order.  Take
`OSRDNDisplay` out of `"Active Drivers"` with Configure.app BEFORE deleting
the driver package, or the machine boots without a display driver.
