/*
 * OSRDNMesaSurface.h - M1c: the one surface, and who has it
 * (docs/M1C_PLAN.md).
 *
 * BINDING AND OWNERSHIP ARE TWO FIELDS, from the first line of this rung.
 * osmesa.c's own comment on BoundTo says why: "a refused rebind leaves the
 * owner set while Mesa goes back to the application's buffer".  One field
 * cannot say both, and the rung that discovers it needs two is the rung that
 * has already shipped the wrong answer.
 *
 * In M1c the surface is drawn into by SOFTWARE.  Mesa rasterises into video
 * memory instead of the application's buffer, and Mirror copies it back.  No
 * triangle reaches the card; that is M1d.
 */

#ifndef OSRDN_MESA_SURFACE_H
#define OSRDN_MESA_SURFACE_H

/* Why a request for the surface was refused.  Counting only "refused" would
   make a gate unable to tell a narrow test from a broad one. */
#define OSRDN_SURF_OK           0
#define OSRDN_SURF_NO_ACCEL     1   /* the probe did not say HARDWARE */
#define OSRDN_SURF_OWNED        2   /* another context has it */
#define OSRDN_SURF_SIZE         3   /* it does not fit the window we may map */
#define OSRDN_SURF_MAP          4   /* the mapping itself failed */
#define OSRDN_SURF_ARGS         5   /* a width, height or row length we cannot use */
#define OSRDN_SURF_REASONS      6

typedef struct {
    unsigned long maps;         /* how many times a window was mapped */
    unsigned long unmaps;       /* and unmapped */
    unsigned long live;         /* mapped minus unmapped -- must never exceed 1 */
    unsigned long liveMax;      /* the largest that ever was */
    unsigned long taken;        /* Buffer calls that handed the surface over */
    unsigned long refused[OSRDN_SURF_REASONS];
    unsigned long mirrors;      /* Mirror calls that copied something */
    unsigned long mirrorIdle;   /* Mirror calls with nothing bound (C3/C4) */
    unsigned long rshift, gshift, bshift;   /* the packing we were told, recorded */
    unsigned long width, height, rowPixels;
    unsigned long winBytes;     /* M1g: how far the one mapping reaches */
    unsigned long lateReserve;  /* reserve() calls that came after the mapping */
    unsigned long mirrorsFlipped;   /* G5-1b: mirrors that reversed the rows */
} osrdn_surf_counts;

const osrdn_surf_counts *OSRDNMesaSurfaceCounts(void);
const char *OSRDNMesaSurfaceWhyName(int why);

/*
 * Take the surface for this context, or refuse and say why.  Returns the
 * address Mesa should draw into, or null.  *rowPixels is set only on success.
 */
void *osrdn_surf_take(const void *ctx, void *appBuffer, int width, int height,
                      int rshift, int gshift, int bshift, int appRowPixels,
                      int *rowPixels, int *why);

/* Is THIS context the one drawing into the surface?  Not the same as owning it. */
int osrdn_surf_bound_to(const void *ctx);

/* The application's buffer, to put back when the substitution ends. */
void *osrdn_surf_app_buffer(void);

/*
 * The packing osmesa asked for, as it handed it to Buffer.  The card's colour
 * buffer is ARGB8888 and osmesa's OSMESA_RGBA is R,G,B,A in ascending bytes
 * (osmesa.c 191-194), so a triangle the CARD draws is not laid out the way one
 * SOFTWARE draws -- and M1c never saw it, because there software did the
 * drawing and the mirror copied its bytes back unchanged.  Whoever builds a
 * vertex colour needs these; nobody may assume them.
 */
void osrdn_surf_shifts(int *rshift, int *gshift, int *bshift, int *ashift);

/*
 * M1g.  Ask for the mapping to reach FURTHER than the colour surface, so a
 * texture can be written into the same window.  It is STILL ONE MAPPING -- the
 * invariant this rung inherited is "one window is mapped", not "the mapping is
 * exactly the surface".  Call before the first bind; a later, larger request is
 * refused rather than silently ignored, because a mapping that grew under a
 * live surface would move nothing and explain nothing.
 *
 * Returns the window base once something is mapped, else null.  The caller adds
 * its own offset; no address is written in the surface unit.
 */
void osrdn_surf_reserve(unsigned long bytes);
void *osrdn_surf_window(unsigned long *bytes);

/* How wide the surface's rows are, in pixels; 0 when there is no surface. */
unsigned long osrdn_surf_stride(void);
/* G5-4: the colour surface's first word (row 0 of memory), or 0 when nothing is bound */
const unsigned long *osrdn_surf_base(void);

/*
 * Copy what has been drawn back into the application's buffer.
 *
 * MUST be safe with nothing bound: osmesa_leave_accel calls this without
 * testing the binding, because its two callers ask at different moments
 * (osmesa.c 359-375).  With nothing bound it does nothing and says so.
 */
void osrdn_surf_mirror(void);
/*
 * G5-1b (docs/G5_1B_PRESENT_ONE_BLIT_PLAN.md 1): the hook says which way up it
 * drew the surface.  Set (1) while a present-mode context packs its vertices
 * with y flipped, so that surface row s is screen row s; the mirror then copies
 * the rows back reversed, and the application's array keeps its Y_UP contract.
 * The flag describes the LAST drawing, so it outlives present mode until the
 * next unflipped draw.
 */
void osrdn_surf_set_flipped(int on);
int osrdn_surf_flipped(void);

/* Give the surface back, if this context is the owner.  Called from BOTH
   osmesa_leave_accel (osmesa.c 406) and OSMesaDestroyContext (427), so it must
   be safe twice and safe when there is nothing to give back. */
void osrdn_surf_release(const void *ctx);

#endif /* OSRDN_MESA_SURFACE_H */
