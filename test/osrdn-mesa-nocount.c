/*
 * osrdn-mesa-nocount.c - M1c: what the stock link needs so that ONE source can
 * be built both ways (docs/M1C_PLAN.md 6-C).
 *
 * osrdn-mesa-surface.c prints counters from the accelerated library.  The stock
 * library has none, so the stock build gets these: every counter zero, every
 * name still answering.  The alternative -- two test sources -- would mean the
 * pixels being compared came from two programs, and then a difference would
 * have two possible causes.
 */

#include "OSRDNMesaHook.h"
#include "OSRDNMesaSurface.h"
#include "OSRDNMesaTri.h"
#include "OSRDNMesaTex.h"
#include "OSRDNMesaDepth.h"
/* the texture SIZE lives in the generated table, not in the unit header:
   it is the prologue that fixes it, and the header deliberately does not
   repeat a number the generator owns */
#include "OSRDNMesaTriTable.h"

static osrdn_hook_counts noneHook;
static osrdn_surf_counts noneSurf;
static osrdn_tri_counts  noneTri;       /* M1d */
static osrdn_tri_sent    noneSent;
static osrdn_tri_failed  noneFailed;    /* M3d */
static osrdn_tex_counts  noneTex;       /* M1g */
static osrdn_depth_counts noneDepth;    /* M1i */
static unsigned long     noneImage[OSRDN_TEX_W * OSRDN_TEX_H];

const osrdn_hook_counts *OSRDNMesaHookCounts(void) { return &noneHook; }
const osrdn_surf_counts *OSRDNMesaSurfaceCounts(void) { return &noneSurf; }
/* M3h: no window without the card -- the teapot's fence then checks nothing */
void *osrdn_surf_window(unsigned long *bytes) { if (bytes != 0) *bytes = 0UL; return 0; }
const osrdn_tri_counts *OSRDNMesaTriCounts(void) { return &noneTri; }
const osrdn_tri_sent *OSRDNMesaTriSent(void) { return &noneSent; }
const osrdn_tri_failed *OSRDNMesaTriFailed(void) { return &noneFailed; }
const osrdn_tex_counts *OSRDNMesaTexCounts(void) { return &noneTex; }
const unsigned long *OSRDNMesaTexImage(void) { return noneImage; }
const osrdn_depth_counts *OSRDNMesaDepthCounts(void) { return &noneDepth; }
/* the stock link prints the depth dump too -- one source, two links -- and it
   has no card, so every pixel is "outside" */
long osrdn_depth_get(int x, int y) { (void)x; (void)y; return -1L; }
long osrdn_depth_at(int x, int y) { (void)x; (void)y; return -1L; }

const char *
OSRDNMesaHookName(int hook)
{
    static const char *names[OSRDN_HOOKS] = {
        "UpdateState", "Buffer", "DepthBuffer", "ReleaseBuffer", "BoundTo",
        "AppBuffer", "CopyDepth", "Mirror", "Stride", "ClearPixel"
    };

    if (hook < 0 || hook >= OSRDN_HOOKS)
        return "?";
    return names[hook];
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

const char *
OSRDNMesaTriWhyName(int why)
{
    static const char *names[OSRDN_TRI_REASONS] = {
        "-", "NO_ACCEL", "NOT_RUNNING", "NO_WINDOW", "ARGS",
        "IOCTL", "REFUSED", "NOT_DRAWN"
    };

    if (why < 0 || why >= OSRDN_TRI_REASONS)
        return "?";
    return names[why];
}

const char *
OSRDNMesaTexWhyName(int why)
{
    static const char *names[OSRDN_TEX_REASONS] = {
        "-", "NO_WINDOW", "ARGS", "READBACK"
    };

    if (why < 0 || why >= OSRDN_TEX_REASONS)
        return "?";
    return names[why];
}

/*
 * osrdn-mesa-tri.c also prints the classifier's reason names, and the stock
 * link has no classifier either.  The names still have to answer, because the
 * two transcripts are compared line for line.
 */
const char *
OSRDNMesaDepthWhyName(int why)
{
    static const char *names[OSRDN_DEPTH_REASONS] = {
        "-", "NO_WINDOW", "ARGS", "READBACK"
    };

    if (why < 0 || why >= OSRDN_DEPTH_REASONS)
        return "?";
    return names[why];
}

const char *
osrdn_class_why_name(int why)
{
    static const char *names[OSRDN_WHY_REASONS] = {
        "-", "FORMAT", "SMOOTH", "STIPPLE", "TEXTURE", "RASTER", "DEPTH_WIDTH",
        "SHADE_MODEL", "TRI_SETUP", "BLEND_MODE", "DEPTH"
    };

    if (why < 0 || why >= OSRDN_WHY_REASONS)
        return "?";
    return names[why];
}

/*
 * M1l.  In the stock link there is no batch to enable and no submission to
 * batch -- every triangle is drawn by Mesa.  This returns 1 so the timing
 * sweep walks the SAME points it walks in the accelerated link: the stock arm
 * is the software baseline for every n, and a baseline measured at different
 * points is not a baseline.
 */
int
osrdn_tri_batch_enabled(void)
{
    return 1;
}

/*
 * M1r.  There is no sent-triangle ring in the stock link either, but the test
 * prints the knob's state on both arms so a transcript says which way it ran.
 * One, because "on" is the default and the stock arm never turns it off.
 */
int
osrdn_tri_sentlog_enabled(void)
{
    return 1;
}

/*
 * M1s.  The stock link has no send to skip, and the sweep prints the knob on
 * both arms so a transcript says which way it ran.  Zero: the stock arm never
 * turns it on.
 */
int
osrdn_tri_nullsend_enabled(void)
{
    return 0;
}

/* M1t.  The stock link has no vertex to write; zero, like the knob's default. */
int
osrdn_tri_inline_enabled(void)
{
    return 0;
}

/* M1v.  The stock link has no table to install; zero, like the knob's default. */
int
osrdn_tri_group_enabled(void)
{
    return 0;
}

/*
 * M1p.  The stock link has no submission at all, so there is no buffer to
 * choose; the sweep still calls this so both links walk the same points and
 * print the same shape of line.
 */
void
osrdn_tri_set_copyin(int on)
{
    (void)on;
}
