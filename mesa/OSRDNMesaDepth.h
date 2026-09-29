/*
 * OSRDNMesaDepth.h - M1i: the card's depth buffer, and clearing it
 * (docs/M1I_PLAN.md).
 *
 * This unit knows nothing about Mesa.  It fills the depth surface in the card's
 * window with one value, at the address the hardware reads.
 *
 * WHY IT IS NOT A LOOP OVER BYTES.  The R200's depth buffer is TILED: pixel
 * (x, y) is not at y * pitch + x.  The layout is the one R6f measured and it
 * matches Mesa's own r200_mba_z16.  There is no bit that turns it off -- the
 * colour buffer has R200_COLOR_TILE_ENABLE and the depth pitch register has
 * nothing of the sort (docs/M1I_PLAN.md 3).  So the address of every pixel is
 * GENERATED into osrdnDepthAt[] from the oracle, and this unit indexes it.
 *
 * Mesa's own depth buffer is linear, `array [Width*Height]` (types.h 1380), so
 * the two CANNOT share a pointer.  That is why the DepthBuffer hook still
 * declines: the card owns depth, and Mesa's copy is allocated and unused.
 */

#ifndef OSRDN_MESA_DEPTH_H
#define OSRDN_MESA_DEPTH_H

#define OSRDN_DEPTH_OK          0
#define OSRDN_DEPTH_NO_WINDOW   1   /* the mapping does not reach the surface */
#define OSRDN_DEPTH_ARGS        2   /* not the one size this rung clears */
#define OSRDN_DEPTH_READBACK    3   /* what we wrote is not what is there (the CPU path, gone with G3b) */
#define OSRDN_DEPTH_CARD        4   /* G3b: the kernel refused the clear, or the ioctl failed */
#define OSRDN_DEPTH_REASONS     5

typedef struct {
    unsigned long clears;       /* buffers cleared */
    unsigned long pixels;       /* and how many pixels that was */
    unsigned long readBad;      /* pixels that did not read back */
    unsigned long refused[OSRDN_DEPTH_REASONS];
    unsigned long lastValue;
    unsigned long colourClears;  /* G3b: colour clears the card did */
    unsigned long lastVerdict;   /* G3b: the kernel's last verdict (~0 = the ioctl failed) */    /* what was written */
} osrdn_depth_counts;

const osrdn_depth_counts *OSRDNMesaDepthCounts(void);
const char *OSRDNMesaDepthWhyName(int why);

/*
 * Fill the depth surface with `value` (a 16-bit depth) and read it back.
 * Returns 1 when it is there and verified, 0 otherwise; *why may be null.
 *
 * MUST be called AFTER any ZPREP, which fills the whole window with a pattern,
 * depth included -- the same ordering the texels need (mesa/OSRDNMesaTex.h).
 */
int osrdn_depth_clear(unsigned long value, int width, int height, int *why);
/* G3b (docs/G3B_CLEAR_PLAN.md 2-3): the same, and the colour, on the card in one
   ioctl -- flags are OSRDN_CLEAR_COLOUR | OSRDN_CLEAR_DEPTH (osrdn_r7b.h); the
   depth value is the 16-bit word the card should hold (floor(z * 2^16)) */
int osrdn_card_clear(unsigned long flags, unsigned long colour, unsigned long depth16,
                     int width, int height, int *why);
int osrdn_colour_clear(unsigned long colour, int width, int height, int *why);


/* what the hardware reads for pixel (x, y); -1 when it is outside the buffer */
long osrdn_depth_at(int x, int y);

/*
 * The depth VALUE at (x, y), read back out of the window; -1 when the pixel is
 * outside the buffer or the window does not reach it.
 *
 * This exists because the first depth run drew nothing below y = 32 and every
 * counter said the draw had happened.  The only way to tell "the card wrote a
 * depth we did not expect" from "the card read a depth we did not write" is to
 * look at the buffer, so the test looks.
 */
long osrdn_depth_get(int x, int y);

#endif /* OSRDN_MESA_DEPTH_H */
