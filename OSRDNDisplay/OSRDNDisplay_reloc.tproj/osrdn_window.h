/*
 * osrdn_window.h - where the offscreen window starts and ends for a mode.
 *
 * docs/R4_ENGINE_PLAN.md 11 (operator decision: follow the Matrox driver).  The
 * Matrox replacement driver's rule, restated rather than linked
 * (openstep-matrox-remade OpenStepMGAWindowMath.c, OSMGAWindowGeometry and
 * OSMGAWindowCeiling):
 *
 *   start   = the visible image plus 256 guard rows, rounded UP to a page;
 *   ceiling = the VRAM size less a 4 MiB top-of-VRAM margin, rounded DOWN to
 *             a page.  Matrox keeps the margin because "that is where a
 *             board reserves things and nobody has established what"; nobody
 *             has established it for this card either, so it stays.
 *
 * VRAM is taken as 128 MiB (operator decision, PLAN.md V).  Plain C89, no
 * libc, no driverkit: tools/r4 compiles it on the host and holds all twenty
 * modes to an independent python computation.  The page size is an argument
 * -- this kernel's page is 8192 (Matrox S4A 10-1, measured) and the driver
 * passes the kernel's own page_size.
 */

#ifndef OSRDN_WINDOW_H
#define OSRDN_WINDOW_H

#define OSRDN_WIN_GUARD_ROWS    256UL
#define OSRDN_WIN_TOP_MARGIN    0x400000UL      /* 4 MiB */
#define OSRDN_WIN_VRAM          0x8000000UL     /* 128 MiB, the operator's assumption */

/* The first byte past the visible image and its guard rows, rounded up to a
   page; 0 if the arithmetic would not fit 32 bits or the page is not a power
   of two (no product is formed without first proving it fits). */
unsigned long osrdn_window_start(unsigned long width, unsigned long height,
                                 unsigned long bytesPerPixel, unsigned long pageBytes);

/* vram less the top margin, rounded down to a page; 0 if nothing is left */
unsigned long osrdn_window_ceiling(unsigned long vramBytes, unsigned long pageBytes);

#endif /* OSRDN_WINDOW_H */
