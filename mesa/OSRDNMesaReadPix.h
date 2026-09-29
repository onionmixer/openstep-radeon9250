/*
 * OSRDNMesaReadPix.h - G5-4 (docs/G5_4_READPIX_AND_CLEANUP_PLAN.md 1): glReadPixels from a
 * surface drawn TOP-DOWN (present mode, G5-1b), giving the bytes Mesa would give from the same
 * picture drawn bottom-up.  Plain C, no Mesa types, so a host simulator can run it against a
 * python oracle (tools/mesa/sim_readpix.py).
 */
#ifndef OSRDN_MESA_READPIX_H
#define OSRDN_MESA_READPIX_H

typedef struct {
    const unsigned long *surf;  /* the colour surface, row 0 at the TOP */
    unsigned long rowPixels;    /* words a surface row holds */
    long width, height;         /* the surface's size = the read buffer's */
    int rs, gs, bs, as;         /* component shifts in a word (osrdn_surf_shifts) */
    long xmin, xmax, ymin, ymax;/* the read buffer's bounds, INCLUSIVE (Mesa's Xmin..Xmax) */
} osrdn_readpix_src;

typedef struct {
    int alignment;              /* 1, 2, 4 or 8 */
    long rowLength;             /* 0 = the request's width */
    long skipPixels, skipRows;
} osrdn_readpix_pack;

/* comps 3 = GL_RGB, 4 = GL_RGBA, both GL_UNSIGNED_BYTE.  Returns 1 when the request was
   answered (clipped as Mesa's read_fast_rgba_pixels clips: slots outside the buffer are left
   alone -- GL leaves them undefined), 0 when it is not one this function takes (the caller
   then lets Mesa read, and counts it). */
int osrdn_readpix_flipped(const osrdn_readpix_src *s, long x, long y, long w, long h, int comps,
                          const osrdn_readpix_pack *pk, unsigned char *dest);

#endif /* OSRDN_MESA_READPIX_H */
