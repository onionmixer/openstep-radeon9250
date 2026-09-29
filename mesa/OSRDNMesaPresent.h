/*
 * OSRDNMesaPresent.h - putting the card's picture on the screen without the
 * readback (G3, docs/G3_PRESENT_PLAN.md 2-2).
 *
 * The three functions are the SDL2 port's present contract
 * (SDL_openstepglpresent.h): an application that links this library hands
 * them to SDL once, and SDL then stamps each frame from video memory to the
 * screen instead of reading it back through the bus.  The names and shapes
 * are the Matrox library's (OpenStepMGAMesaBuffer.c 746-818) so a demo moves
 * between the two by relinking.
 *
 * ALL THREE ANSWER FOR THE CURRENT CONTEXT ONLY: the surface has one owner,
 * and a second context that fell back to software must not stamp the first
 * one's picture into its own window.  OSMesaGetCurrentContext() is the owner
 * key (osmesa.c 1994: the OSMesaContext IS ctx->DriverCtx).
 */
#ifndef OSRDN_MESA_PRESENT_H
#define OSRDN_MESA_PRESENT_H

#define OSRDN_PRESENT_VERDICT_COUNT 8

typedef struct {
    unsigned long modeOn, modeOff;          /* PresentMode(1) / (0) transitions */
    unsigned long rects;                    /* PresentRect calls that reached the kernel */
    unsigned long ok;                       /* ... and were drawn */
    unsigned long refused[OSRDN_PRESENT_VERDICT_COUNT];  /* by the kernel's verdict */
    unsigned long notOwner;                 /* calls from a context that does not own the surface */
    unsigned long noDevice;                 /* the node could not be opened */
    unsigned long ioctlFailed;              /* ioctl() itself returned -1 */
    unsigned long lastVerdict;
    /* G5-1b (docs/G5_1B_PRESENT_ONE_BLIT_PLAN.md 1): with the surface drawn top-down,
       a frame's first row call blits the whole surface (coalesced), the rest of the
       rows are answered without an ioctl (covered), and any other call in flipped
       mode blits its one row from H-1-srcY (rowFallback) */
    unsigned long coalesced;
    unsigned long covered;
    unsigned long rowFallback;
    /* G5-1c (docs/G5_1C_PRESENT_SERVER_POSITION_PLAN.md 1-1): the server's account of the window */
    unsigned long windowFinds;      /* our window (re)identified in the application's list */
    unsigned long windowLost;       /* a frame refused E_BUSY because it could not be */
    unsigned long calibrations;     /* SDL origin and server frame recorded together, at a steady moment */
    unsigned long shifted;          /* whole frames put where the server had the window, not where SDL said */
    unsigned long moving;           /* frames refused E_BUSY because the window was moving between two queries */
    unsigned long unsettled;        /* frames refused E_BUSY while waiting for a steady pair to calibrate on */
} osrdn_present_counts;

/* 1 while the current context draws into the card's surface; SDL uses it as
   a yes/no ("zero means the caller's own memory") -- the card address of the
   surface is 0 here, so the value is a flag, not an address */
unsigned long OSRDNMesaBufferOrigin(void);
/* on: glFinish stops copying the surface back (the caller's array goes
   stale, as the contract says) and the device stays open across the rows of
   a frame; off: the next glFinish refreshes the array again */
void OSRDNMesaBufferPresentMode(int on);
/* one rectangle of the surface to (dstX, dstY) on the screen, top-left
   origin; 0 on success, else -1 with the kernel's verdict in *outVerdict */
int OSRDNMesaBufferPresentRect(unsigned long srcX, unsigned long srcY,
                               unsigned long w, unsigned long h,
                               long dstX, long dstY, unsigned long *outVerdict);
const osrdn_present_counts *OSRDNMesaPresentCounts(void);
const char *OSRDNMesaPresentVerdictName(unsigned long verdict);

/* for the hook: 1 while a PresentMode(1) is in force for the surface's owner */
int osrdn_present_active(void);

#endif /* OSRDN_MESA_PRESENT_H */
