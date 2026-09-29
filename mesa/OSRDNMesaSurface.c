/*
 * OSRDNMesaSurface.c - see OSRDNMesaSurface.h.  Plain C89, no libc headers and
 * no Mesa headers: the calls it needs are declared here, as the probe's are.
 *
 * The surface is the card's OFFSCREEN window -- the one R4c opened and proved
 * mappable, not the visible framebuffer.  Putting the screen in the same rung
 * as the rendering would make a failure have two causes at once, which the
 * precedent says in as many words.
 *
 * Exactly one mapping is ever live.  That is not a convention here, it is what
 * the build gate counts: a library that could hold several windows would have
 * given up the property this rung is for.
 */

#include "OSRDNMesaSurface.h"
#include "OSRDNMesaTri.h"        /* G5-2: osrdn_tri_retire_if_inflight */
#include "OSRDNMesaProbe.h"

extern int open(const char *, int, ...);
extern int close(int);
extern char *mmap(char *, int, int, int, int, long);
extern int vm_allocate(int, char **, int, int);
extern int task_self(void);

#define NODE            "/dev/rdnvram0"
#define NODE_RDWR       2           /* bsd/sys/fcntl.h 36 */
#define PROT_RW         3           /* PROT_READ | PROT_WRITE */
#define MAP_SHARED_     1
#define PAGE            8192UL      /* R4c measured: page=8192 shift=13 */

static osrdn_surf_counts surfCounts;

/* The two fields the contract insists on being two (osmesa.c's BoundTo note). */
static const void *surfOwner;       /* whose surface it is */
static int         surfBound;       /* and whether that context is drawing into it */

static char       *surfBase;        /* the colour surface, inside the mapping */
static unsigned long surfBytes;
static char       *surfWin;         /* the mapping itself */
static unsigned long surfWinBytes;
static unsigned long surfWant;      /* M1g: how far the mapping must reach */
static unsigned long surfLateWant;  /* requests that arrived too late, counted */
static void       *surfApp;         /* the buffer the application gave */
static unsigned long surfRowPixels;

void
osrdn_surf_reserve(unsigned long bytes)
{
    if (surfWin != 0) {
        /* too late: something is already mapped.  Counted rather than obeyed --
           growing a live mapping would move the surface under Mesa's feet. */
        if (bytes > surfWinBytes) {
            surfLateWant++;
            surfCounts.lateReserve = surfLateWant;
        }
        return;
    }
    if (bytes > surfWant)
        surfWant = bytes;
}

void *
osrdn_surf_window(unsigned long *bytes)
{
    if (bytes != 0)
        *bytes = surfWinBytes;
    return surfWin;
}

const osrdn_surf_counts *
OSRDNMesaSurfaceCounts(void)
{
    return &surfCounts;
}

const char *
OSRDNMesaSurfaceWhyName(int why)
{
    static const char *names[OSRDN_SURF_REASONS] = {
        "-", "NO_ACCEL", "OWNED", "SIZE", "MAP", "ARGS"
    };

    if (why < 0 || why >= OSRDN_SURF_REASONS)
        return "?";
    return names[why];
}

/* round up to a whole number of the kernel's pages, without overflowing */
static unsigned long
surfPages(unsigned long n)
{
    if (n > 0xffffffffUL - (PAGE - 1UL))
        return 0UL;
    return ((n + PAGE - 1UL) / PAGE) * PAGE;
}

/*
 * Map the offscreen window.  The address comes from the probe's CAPS and from
 * nowhere else: there is no card address written in this file, which is what
 * lets the build gate say the library can reach one window and not the card.
 */
static char *
surfMap(unsigned long bytes)
{
    const OSRDNMesaProbeCaps *caps = OSRDNMesaProbeGetCaps();
    char *addr = 0;
    int fd;

    if (caps->winStart == 0UL)
        return 0;
    /* M1g: one mapping, but it may have to reach past the colour surface.  If
       the driver will not give that many pages the mmap fails and we are back
       to software -- a safe failure, not a wild pointer. */
    if (surfWant > bytes)
        bytes = surfPages(surfWant);
    if (bytes == 0UL)
        return 0;
    if ((fd = open(NODE, NODE_RDWR)) < 0)
        return 0;
    /* 4.2BSD mmap maps over memory the caller already owns, so the place is
       taken first (the same discovery R4c and the Matrox probe both record) */
    if (vm_allocate(task_self(), &addr, (int)bytes, 1) != 0) {
        (void)close(fd);
        return 0;
    }
    if (mmap(addr, (int)bytes, PROT_RW, MAP_SHARED_, fd, (long)caps->winStart)
        == (char *)-1) {
        (void)close(fd);
        return 0;
    }
    (void)close(fd);
    surfWin = addr;
    surfWinBytes = bytes;
    surfCounts.winBytes = bytes;
    surfCounts.maps++;
    surfCounts.live++;
    if (surfCounts.live > surfCounts.liveMax)
        surfCounts.liveMax = surfCounts.live;
    return addr;
}

static void
surfUnmap(void)
{
    if (surfBase == 0)
        return;
    /* The mapping is left in place and simply forgotten: this system's mmap
       put it over memory we vm_allocated, and nothing here frees that while a
       later bind may want the same window.  What the gate counts is that only
       ONE is ever live, which is why the counter moves here. */
    surfBase = 0;
    surfBytes = 0UL;
    surfWin = 0;
    surfWinBytes = 0UL;
    surfCounts.unmaps++;
    if (surfCounts.live > 0UL)
        surfCounts.live--;
}

void *
osrdn_surf_take(const void *ctx, void *appBuffer, int width, int height,
                int rshift, int gshift, int bshift, int appRowPixels,
                int *rowPixels, int *why)
{
    unsigned long need;
    int w = OSRDN_SURF_OK;

    if (OSRDNMesaProbeRun() != OSRDN_PROBE_HARDWARE)
        w = OSRDN_SURF_NO_ACCEL;
    else if (width <= 0 || height <= 0 || appRowPixels != width || rowPixels == 0)
        /* M3g: != and not <.  The surface is `width` words a row and
           osrdn_surf_mirror copies it back flat, so an application row longer
           than the width would get every row after the first at the wrong
           offset (docs/M3G_PLAN.md 4).  Refused, it draws in its own array. */
        w = OSRDN_SURF_ARGS;
    else if (surfOwner != 0 && surfOwner != ctx)
        /* Another context has it.  Ownership outlives a refused rebind, which
           is exactly why owner and bound are two fields. */
        w = OSRDN_SURF_OWNED;
    else {
        need = surfPages((unsigned long)width * (unsigned long)height * 4UL);
        if (need == 0UL)
            w = OSRDN_SURF_SIZE;
        else if (surfBase != 0 && need != surfBytes)
            /* A rebind at a size this surface cannot be.  Refusing here is
               what makes osmesa.c run its leave path (osmesa.c 570-571). */
            w = OSRDN_SURF_SIZE;
    }

    if (w != OSRDN_SURF_OK) {
        /* The binding goes, the ownership does not: Mesa is about to draw into
           the application's buffer again, but this context is still the one
           that would get the surface back. */
        if (surfOwner == ctx)
            surfBound = 0;
        surfCounts.refused[w]++;
        if (why != 0)
            *why = w;
        return 0;
    }

    if (surfBase == 0) {
        surfBase = surfMap(need);
        if (surfBase == 0) {
            surfCounts.refused[OSRDN_SURF_MAP]++;
            if (why != 0)
                *why = OSRDN_SURF_MAP;
            return 0;
        }
        surfBytes = need;
    }

    surfOwner = ctx;
    surfBound = 1;
    surfApp = appBuffer;
    surfRowPixels = (unsigned long)width;
    *rowPixels = width;

    surfCounts.taken++;
    surfCounts.rshift = (unsigned long)rshift;
    surfCounts.gshift = (unsigned long)gshift;
    surfCounts.bshift = (unsigned long)bshift;
    surfCounts.width = (unsigned long)width;
    surfCounts.height = (unsigned long)height;
    surfCounts.rowPixels = surfRowPixels;
    if (why != 0)
        *why = OSRDN_SURF_OK;
    return (void *)surfBase;
}

int
osrdn_surf_bound_to(const void *ctx)
{
    return (surfBound && surfOwner == ctx) ? 1 : 0;
}

void *
osrdn_surf_app_buffer(void)
{
    return surfApp;
}

void
osrdn_surf_shifts(int *rshift, int *gshift, int *bshift, int *ashift)
{
    int used;

    if (rshift != 0)
        *rshift = (int)surfCounts.rshift;
    if (gshift != 0)
        *gshift = (int)surfCounts.gshift;
    if (bshift != 0)
        *bshift = (int)surfCounts.bshift;
    if (ashift != 0) {
        /* osmesa hands Buffer three shifts, not four.  The fourth is the one of
           0, 8, 16, 24 the other three did not take -- derived rather than
           assumed to be 24, so an ARGB surface would not be packed as RGBA. */
        used = (1 << ((int)surfCounts.rshift / 8)) |
               (1 << ((int)surfCounts.gshift / 8)) |
               (1 << ((int)surfCounts.bshift / 8));
        if ((used & 1) == 0)        *ashift = 0;
        else if ((used & 2) == 0)   *ashift = 8;
        else if ((used & 4) == 0)   *ashift = 16;
        else                        *ashift = 24;
    }
}

unsigned long
osrdn_surf_stride(void)
{
    return surfBound ? surfRowPixels : 0UL;
}

const unsigned long *
osrdn_surf_base(void)
{
    return surfBound ? (const unsigned long *) surfBase : (const unsigned long *) 0;
}

static int surfFlipped;             /* G5-1b: the last drawing was top-down */

void
osrdn_surf_mirror(void)
{
    unsigned long *src, *dst;
    unsigned long n, i;

    /*
     * The condition is "is there anything to copy", NOT "is this context still
     * bound".  Measured: osmesa.c asks the allocator first and the allocator's
     * first act is to let the binding go (osmesa.c 546-553), so by the time the
     * leave path mirrors, bound is already 0 -- and a mirror that tested bound
     * copied NOTHING on the one path that exists to save the drawing.  The
     * first approval run showed mirrors=0 and idle=1 at exactly that step.
     *
     * Still safe with nothing to do: the leave path calls this without testing
     * anything (osmesa.c 359-375), so "no surface" is an ordinary outcome.
     */
    if (surfBase == 0 || surfApp == 0) {
        surfCounts.mirrorIdle++;
        return;
    }
    /* G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-4): the picture is what the card has FINISHED drawing */
    (void)osrdn_tri_retire_if_inflight();
    src = (unsigned long *)surfBase;
    dst = (unsigned long *)surfApp;
    n = surfCounts.width * surfCounts.height;
    if (surfFlipped && surfCounts.height > 1UL) {
        /* G5-1b: the card drew top-down (present mode); the application's
           array is bottom-up, so row r comes from row height-1-r */
        unsigned long w = surfCounts.width, row;

        for (row = 0UL; row < surfCounts.height; row++) {
            const unsigned long *s = src + (surfCounts.height - 1UL - row) * w;
            unsigned long *d = dst + row * w;

            for (i = 0UL; i < w; i++)
                d[i] = s[i];
        }
        surfCounts.mirrorsFlipped++;
    } else {
        for (i = 0UL; i < n; i++)
            dst[i] = src[i];
    }
    surfCounts.mirrors++;
}

void
osrdn_surf_set_flipped(int on)
{
    surfFlipped = on ? 1 : 0;
}

int
osrdn_surf_flipped(void)
{
    return surfFlipped;
}

void
osrdn_surf_release(const void *ctx)
{
    /* Called from the leave path AND from context destruction, so it has to be
       safe twice and safe with nothing held. */
    if (surfOwner != ctx)
        return;
    surfUnmap();
    surfOwner = 0;
    surfBound = 0;
    surfApp = 0;
    surfRowPixels = 0UL;
}
