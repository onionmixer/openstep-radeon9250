/*
 * osrdn-mga-shim.h -- the Matrox library's names, on libGL_radeon.a (G4-0, docs/G4_GLQUAKE_PLAN.md 5).
 *
 * WHY.  The glquake port (openstep-quake/port/openstep/gl_vidsdl.c) and the Matrox test
 * programs (openstep-matrox-remade/test/openstep-mga-mesa-*.c, openstep-quake/test/
 * q2-state-matrix.c) name the Matrox library's functions.  Rather than a second copy of
 * each program, this directory carries the six header NAMES they include, and every one
 * of them is this file: compiled with -I<here> instead of -I<matrox>/mesa, the same source
 * links against libGL_radeon.a unchanged.  test/osrdn-sdl-teapot.c did this by hand for
 * the teapot demo; this is the same mapping for everything else.
 *
 * WHAT MAPS TO WHAT.  The radeon library has no WARP, no trapezoids, no eviction and no
 * revoke: those counters read 0 and their names say so below.  The Matrox "chooser"
 * counts state SELECTIONS (HardState/SoftState); the radeon hook counts the same event
 * as installs (our triangle function went in) and leaves (Mesa's stayed).  Forcing the
 * software path is not a flag here: a full-surface scissor does it, exactly as the Matrox
 * tests describe their own mechanism -- the radeon classifier refuses any raster bit
 * outside RM_KNOWN (OSRDNMesaClass.c 19), and a scissor that clips nothing changes the
 * path and not the picture.
 */
#ifndef OSRDN_MGA_SHIM_H
#define OSRDN_MGA_SHIM_H

/* LINKAGE.  A program that includes a Matrox header gets these as `static` copies; a program
   that declares the Matrox functions `extern` itself (depth-agree does) links
   osrdn-mga-shim.c instead, which defines the same bodies with external linkage. */
#ifndef OSRDN_MGA_SHIM_LINKAGE
#define OSRDN_MGA_SHIM_LINKAGE static
#endif

#include <GL/gl.h>
#include "OSRDNMesaHook.h"
#include "OSRDNMesaTri.h"
#include "OSRDNMesaSurface.h"
#include "OSRDNMesaProbe.h"
#include "OSRDNMesaPresent.h"
#include "OSRDNMesaDepth.h"
#include "OSRDNMesaTex.h"
#include "OSRDNMesaTexArena.h"
#include "OSRDNMesaTriTable.h"
#include "OSRDNMesaTime.h"          /* G5-0: the frame-budget instrument feeds the port's submit/bracket lines */
#include "OSRDNMesaClass.h"          /* G4-6: OSRDN_WHY_REASONS for the gate-why line */

/* ---- the probe ------------------------------------------------------------ */
typedef int OSMGAProbeVerdict;
#define OSMGA_HW3D_CAPS_COUNT 1
#define OSMGA_HW3D_CAP_VRAMLEN 0        /* G4-1b: the arena test reads the window's size here */
typedef struct {
    OSMGAProbeVerdict verdict;
    unsigned long caps[OSMGA_HW3D_CAPS_COUNT];
    unsigned long missing;
    unsigned long nodeMajor;
} OSMGAMesaProbe;
#define OSMGA_PROBE_HARDWARE OSRDN_PROBE_HARDWARE
OSRDN_MGA_SHIM_LINKAGE void OSMGAMesaProbeRun(OSMGAMesaProbe *p)
{
    p->verdict = OSRDNMesaProbeRun();
    {   unsigned long bytes = 0UL; (void) osrdn_surf_window(&bytes); p->caps[0] = bytes; }
    p->missing = 0UL; p->nodeMajor = 0UL;
}
static const char *OSMGAMesaProbeVerdictString(OSMGAProbeVerdict v) { return OSRDNMesaProbeName(v); }

/* ---- the surface (Matrox "Buffer") ------------------------------------------ */
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaBufferOrigin(void) { return OSRDNMesaBufferOrigin(); }
OSRDN_MGA_SHIM_LINKAGE void OSMGAMesaBufferPresentMode(int on) { OSRDNMesaBufferPresentMode(on); }
OSRDN_MGA_SHIM_LINKAGE int OSMGAMesaBufferPresentRect(unsigned long srcX, unsigned long srcY, unsigned long w, unsigned long h,
                                                      long dstX, long dstY, unsigned long *outVerdict)
{ return OSRDNMesaBufferPresentRect(srcX, srcY, w, h, dstX, dstY, outVerdict); }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaBufferCopies(void) { return OSRDNMesaSurfaceCounts()->mirrors; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaBufferPresentOnCount(void) { return OSRDNMesaPresentCounts()->modeOn; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaBufferPresentOffCount(void) { return OSRDNMesaPresentCounts()->modeOff; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaBufferPresentRefused(unsigned long v)
{
    return v < (unsigned long)OSRDN_PRESENT_VERDICT_COUNT ? OSRDNMesaPresentCounts()->refused[v] : 0UL;
}
/* the depth buffer: the window's fixed layout (OSRDNMesaTriTable.h), or 0 without a window */
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaBufferDepthOrigin(void)
{
    unsigned long bytes = 0UL;
    unsigned long w = (unsigned long)osrdn_surf_window(&bytes);
    return w ? w + (unsigned long)OSRDN_TRI_DEPTH_BYTE_OFF : 0UL;
}
/* the texture arena (G4-1b): the unit's own answer, as a WINDOW-RELATIVE origin plus the
   bytes it holds; "none" when the surface is not ours or the arena was never set */
OSRDN_MGA_SHIM_LINKAGE int OSMGAMesaBufferTextureArena(const void *ctx, unsigned long *origin, unsigned long *bytes)
{
    unsigned long n = 0UL, used = 0UL, room = 0UL;
    if (origin) *origin = 0UL;
    if (bytes) *bytes = 0UL;
    if (!osrdn_surf_bound_to(ctx)) return 0;
    osrdn_texarena_stat(&n, &used, &room);
    if (room == 0UL) return 0;
    if (origin) *origin = (unsigned long)OSRDN_TEX_BYTE_OFF;
    if (bytes) *bytes = room;
    return 1;
}

/* ---- the hook -------------------------------------------------------------- */
OSRDN_MGA_SHIM_LINKAGE unsigned long osrdnShimRefusedSum(void)
{
    const osrdn_tri_counts *t = OSRDNMesaTriCounts();
    unsigned long i, s = 0UL;
    for (i = 0UL; i < (unsigned long)OSRDN_TRI_REASONS; i++) s += t->refused[i];
    return s;
}
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookDrawn(void)      { return OSRDNMesaTriCounts()->submitted; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookBatches(void)    { return OSRDNMesaTriCounts()->opens; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookSoftware(void)   { return OSRDNMesaHookCounts()->delegated; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookDeclined(void)   { return OSRDNMesaHookCounts()->leaves; }
/* G4-1b: Matrox's gate re-decides at every UpdateState and its q2-state-matrix arms count on a
   decision landing inside each arm.  This hook decides at UpdateState too (installs), but an arm
   that changes no state gets no UpdateState -- so a batch OPENED under the hardware decision is
   counted as that decision in force (OSRDNMesaTri opens): drawn > 0 with no batch cannot happen. */
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookHardState(void)  { return OSRDNMesaHookCounts()->installs + OSRDNMesaTriCounts()->opens; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookSoftState(void)  { return OSRDNMesaHookCounts()->leaves; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookReplayed(void)   { return OSRDNMesaHookCounts()->replayed; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookUnsupported(void) { return osrdnShimRefusedSum(); }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookTexPersp(void)   { return OSRDNMesaHookCounts()->texProjective; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookTexAbsent(void)  { return OSRDNMesaHookCounts()->texUploadBad; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookClears(void)     { return OSRDNMesaHookCounts()->depthClears; }
OSRDN_MGA_SHIM_LINKAGE int           OSMGAMesaHookClearWhy(void)   { return (int)OSRDNMesaDepthCounts()->lastVerdict; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaTexUploads(void)     { return OSRDNMesaHookCounts()->texUploads; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaTexRefused(void)     { return OSRDNMesaHookCounts()->texUploadBad; }
/* not a radeon notion: WARP, trapezoids, eviction, revoke, narrowing, prevalidation */
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookWarp(void)       { return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookGated(void)      { return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookDropped(void)    { return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookDroppedClipped(void) { return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookNarrowed(void)   { return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookPrevalidated(void) { return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookRescued(void)    { return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookLastRefusalSite(void) { return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookLocalLastSite(void) { return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookLocalLastVerdict(void) { return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookLocalVerdictCount(unsigned long v) { (void)v; return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaHookVerdictCount(unsigned long v) { (void)v; return 0UL; }
OSRDN_MGA_SHIM_LINKAGE unsigned long OSMGAMesaTexEvicted(void)     { return 0UL; }
OSRDN_MGA_SHIM_LINKAGE int           OSMGAMesaHookDeadlineHit(void) { return 0; }
OSRDN_MGA_SHIM_LINKAGE void          OSMGAMesaHookInjectRefusal(int on) { (void)on; }
OSRDN_MGA_SHIM_LINKAGE void          OSMGAMesaHookInstrument(int on) { (void)on; }
typedef struct { unsigned long verdict, site; } OSMGAMesaRefusal;
static const OSMGAMesaRefusal *OSMGAMesaHookLastRefusal(void) { return 0; }
#define OSMGA_MESA_VERDICTS 32
#define OSMGA_MESA_GATE_WHY 16
#define OSMGA_MESA_BUILD_WHY 16
#define OSMGA_WARP_NO_COUNT 12
OSRDN_MGA_SHIM_LINKAGE void OSMGAMesaHookFlushCounts(unsigned long out[4]) { out[0] = out[1] = out[2] = out[3] = 0UL; }
/* G5-0: the port prints "submit: N calls, U us, W dwords, spins S (max M)" and "bracket: N opens, U us".
   Here: submit = the SUBMIT2 ioctl (calls, us, words), and the two Matrox spin fields carry the
   PRESENT rows (count, us) -- there is no spin here, and the row cost is the number G3 asked for.
   All zero unless RDNMesaTime is set (docs/G5_0_PERF_MEASURE_PLAN.md 2-3). */
OSRDN_MGA_SHIM_LINKAGE void OSMGAMesaHookSubmitStats(unsigned long out[6])
{
    out[0] = osrdn_time_calls(OSRDN_TIME_SUBMIT);
    out[1] = osrdn_time_us(OSRDN_TIME_SUBMIT);
    out[2] = osrdn_time_units(OSRDN_TIME_SUBMIT);
    out[3] = osrdn_time_calls(OSRDN_TIME_PRESENT);
    out[4] = osrdn_time_us(OSRDN_TIME_PRESENT);
    out[5] = 0UL;
}
OSRDN_MGA_SHIM_LINKAGE void OSMGAMesaHookBracketStats(unsigned long out[2])
{
    out[0] = osrdn_time_calls(OSRDN_TIME_BRACKET);
    out[1] = osrdn_time_us(OSRDN_TIME_BRACKET);
}
OSRDN_MGA_SHIM_LINKAGE void OSMGAMesaHookWhyBatch(unsigned long out[7]) { int i; for (i = 0; i < 7; i++) out[i] = 0UL; }
OSRDN_MGA_SHIM_LINKAGE void OSMGAMesaRebaseStats(unsigned long out[7]) { int i; for (i = 0; i < 7; i++) out[i] = 0UL; }
/* G4-6 diagnosis: the port prints this as "gate refused : Hook.c:<n> x<count>" -- on radeon <n> is
   the classifier's reason (OSRDN_WHY_*, OSRDNMesaClass.h: 4 TEXTURE, 5 RASTER, 7 SHADE_MODEL,
   8 TRI_SETUP, 9 BLEND_MODE, 10 DEPTH, 11 ALPHA_MODE, ...) and the count is how many state
   decisions declined for it.  The port is not touched; only what this shim hands back. */
OSRDN_MGA_SHIM_LINKAGE void OSMGAMesaHookGateWhy(unsigned long lines[OSMGA_MESA_GATE_WHY], unsigned long counts[OSMGA_MESA_GATE_WHY])
{
    int i, k = 0;
    for (i = 0; i < OSMGA_MESA_GATE_WHY; i++) lines[i] = counts[i] = 0UL;
    for (i = 1; i < OSRDN_WHY_REASONS && k < OSMGA_MESA_GATE_WHY; i++)
        if (OSRDNMesaHookCounts()->why[i] != 0UL) {
            lines[k] = (unsigned long)i;
            counts[k] = OSRDNMesaHookCounts()->why[i];
            k++;
        }
}
/* G4-6 diagnosis: the port prints this as "builder refused: Triangle.c:<n> x<count>" -- on radeon
   <n> = clause * 1000000 + the clause's last offending value (osrdn_class_tex_why: 1 not 2D unit 0,
   2 width, 3 height, 4 border, 5 format, 6 MIN, 7 MAG, 8 wrap S, 9 wrap T, 10 env) and the count
   is how many TEXTURE declines that clause made. */
OSRDN_MGA_SHIM_LINKAGE void OSMGAMesaBuildWhy(unsigned long lines[OSMGA_MESA_BUILD_WHY], unsigned long counts[OSMGA_MESA_BUILD_WHY])
{
    int i, k = 0;
    for (i = 0; i < OSMGA_MESA_BUILD_WHY; i++) lines[i] = counts[i] = 0UL;
    for (i = 1; i < OSRDN_TEXWHY_CLAUSES && k < OSMGA_MESA_BUILD_WHY; i++)
        if (OSRDNMesaHookCounts()->texWhy[i] != 0UL) {
            lines[k] = (unsigned long)i * 1000000UL + (OSRDNMesaHookCounts()->texWhyVal[i] % 1000000UL);
            counts[k] = OSRDNMesaHookCounts()->texWhy[i];
            k++;
        }
}
OSRDN_MGA_SHIM_LINKAGE void OSMGAMesaWarpNoCounts(unsigned long out[OSMGA_WARP_NO_COUNT]) { int i; for (i = 0; i < OSMGA_WARP_NO_COUNT; i++) out[i] = 0UL; }

/* forcing software: the full-surface scissor (the Matrox tests' own description of what
   their flag does); the viewport is the surface here, as the tests set it */
OSRDN_MGA_SHIM_LINKAGE void OSMGAMesaHookForceSoftware(int on)
{
    if (on) {
        GLint vp[4];
        glGetIntegerv(GL_VIEWPORT, vp);
        glScissor(0, 0, vp[2], vp[3]);
        glEnable(GL_SCISSOR_TEST);
    } else
        glDisable(GL_SCISSOR_TEST);
}

#endif /* OSRDN_MGA_SHIM_H */
