/*
 * osrdn-mesa-teapot.c - M3a: a real GL program, drawn through libGL_radeon.a.
 *
 * Every earlier M rung measured a scene this project wrote for itself
 * (osrdn-mesa-tri.c).  This one draws the Utah teapot the way a GL program
 * does -- lighting, evaluators, the depth test -- and writes the picture as a
 * PPM so the host can compare it with the same program linked against the
 * stock libGL (docs/M3A_PLAN.md 4-5).
 *
 * ONE SOURCE, TWO LINKS, like osrdn-mesa-tri.c:
 *   rdnteapot-stock   stock libGL.a + osrdn-mesa-nocount.c (the counters read 0)
 *   rdnteapot-accel   libGL_radeon.a
 *
 *   rdnteapot-* [width height [grid [file.ppm [cull]]]]   default 64 64 10 teapot.ppm
 *
 * `cull` (M3b) enables GL_CULL_FACE with glCullFace(GL_BACK) and NOTHING else --
 * no two-sided lighting, which would put render_triangle in front of us and
 * have it do the culling that this run exists to see us do (docs/M3B_PLAN.md 6, E3).
 *
 * The geometry is NOT in this file.  teapot-geometry.h is cut at build time
 * out of Mesa 3.4.2's own widgets-mesa/demos/tea.c, lines 581-730 (the patch
 * table, the control points and the evaluator loop), by
 * tools/mesa/target-build-teapot.sh.  That region carries SGI's 1993 and Mark
 * J. Kilgard's 1994 notice, which NOTICE reproduces.  Nothing here comes from,
 * or needs, any other driver project.
 *
 * The state is chosen so the card CAN take it (docs/M3A_PLAN.md 7-8): one-sided
 * lighting, no face culling, no polygon offset, depth GL_LESS with writes on.
 * Any of those three would put every triangle in software, which is a finding
 * of its own and not what this program is for.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <GL/osmesa.h>
#include <GL/gl.h>

#include "OSRDNMesaHook.h"
#include "OSRDNMesaClass.h"
#include "OSRDNMesaTri.h"
#include "OSRDNMesaSurface.h"
#include "OSRDNMesaTriTable.h"

#include "teapot-geometry.h"

static int
num(const char *s, int lo, int hi, int dflt)
{
    char *end;
    long v;

    if (s == 0)
        return dflt;
    v = strtol(s, &end, 10);
    if (*end != '\0' || v < lo || v > hi)
        return -1;
    return (int) v;
}

/* the counter lines, in the SAME shapes osrdn-mesa-tri.c prints, so one reader
   reads both */
static void
say(void)
{
    const osrdn_hook_counts *h = OSRDNMesaHookCounts();
    const osrdn_tri_counts *t = OSRDNMesaTriCounts();
    unsigned long sum = 0UL;
    int i;

    printf("RDNTEAPOT step=end installs=%lu leaves=%lu triangles=%lu "
           "delegated=%lu nosw=%lu notbound=%lu slotsfull=%lu texproj=%lu "
           "replayed=%lu zclear=%lu zclearbad=%lu culled=%lu\n",
           h->installs, h->leaves, h->triangles, h->delegated, h->noSoftware,
           h->notBound, h->slotsFull, h->texProjective, h->replayed,
           h->depthClears, h->depthClearBad, h->culled);
    printf("RDNTEAPOT step=end-tri entered=%lu submitted=%lu smoothsent=%lu "
           "depthsent=%lu\n",
           t->entered, t->submitted, t->smoothSent, t->depthSent);
    printf("RDNTEAPOT step=end-refused");
    for (i = 0; i < OSRDN_TRI_REASONS; i++) {
        printf(" %s=%lu", OSRDNMesaTriWhyName(i), t->refused[i]);
        sum += t->refused[i];
    }
    printf(" SUM=%lu\n", sum);
    printf("RDNTEAPOT step=end-why");
    for (i = 0; i < OSRDN_WHY_REASONS; i++)
        printf(" %s=%lu", osrdn_class_why_name(i), h->why[i]);
    printf("\n");
}

/* M3d: the first stream the card did not take, 8 words a line, so the host can
   decode it (docs/M3D_PLAN.md).  Nothing is printed when nothing failed. */
static void
sayFailed(void)
{
    const osrdn_tri_failed *f = OSRDNMesaTriFailed();
    unsigned long i;

    if (f->n == 0UL)
        return;
    printf("RDNTEAPOT step=failed n=%lu failures=%lu reason=%s tris=%lu vw=%lu "
           "batch=%lu seed=%lu why=%lu at=%lu word=%lu status=%lu\n",
           f->n, f->failures, OSRDNMesaTriWhyName((int)f->reason), f->tris,
           f->vw, f->batch, f->seed, f->why, f->at, f->word, f->status);
    for (i = 0UL; i < f->n; i++) {
        if (i % 8UL == 0UL)
            printf("RDNTEAPOT step=failed-w at=%lu", i);
        printf(" %lx", f->w[i]);   /* no width: the target cc ignores it */
        if (i % 8UL == 7UL || i + 1UL == f->n)
            printf("\n");
    }
}

/* P6, top row first.  OSMesa's buffer has its origin at the bottom. */
static int
writePpm(const char *path, const unsigned char *buf, int w, int h)
{
    FILE *f = fopen(path, "wb");
    int y, x;

    if (f == 0)
        return 0;
    fprintf(f, "P6\n%d %d\n255\n", w, h);
    for (y = h - 1; y >= 0; y--) {
        const unsigned char *row = buf + (size_t) y * (size_t) w * 4;

        for (x = 0; x < w; x++)
            fwrite(row + x * 4, 1, 3, f);   /* RGBA -> RGB */
    }
    return fclose(f) == 0;
}

int
main(int argc, char **argv)
{
    int w = num(argc > 1 ? argv[1] : 0, 1, 1024, 64);
    int h = num(argc > 2 ? argv[2] : 0, 1, 1024, 64);
    int grid = num(argc > 3 ? argv[3] : 0, 1, 64, 10);
    const char *out = argc > 4 ? argv[4] : "teapot.ppm";
    int cull = (argc > 5 && strcmp(argv[5], "cull") == 0) ? 1 : 0;
    OSMesaContext ctx;
    unsigned char *buf;
    unsigned char *snap;
    unsigned long *fwin = 0;
    unsigned long fbytes = 0UL;
    static const GLfloat lightPos[4] = { 1.0F, 1.0F, 1.0F, 0.0F };
    static const GLfloat diffuse[4] = { 0.8F, 0.6F, 0.2F, 1.0F };
    static const GLfloat ambient[4] = { 0.2F, 0.2F, 0.2F, 1.0F };

    if (w < 0 || h < 0 || grid < 0 || (argc > 5 && !cull)) {
        printf("usage: %s [width height [grid [file.ppm [cull]]]]\n", argv[0]);
        return 2;
    }
    buf = (unsigned char *) malloc((size_t) w * (size_t) h * 4);
    if (buf == 0) {
        printf("RDNTEAPOT FAIL no memory\n");
        return 1;
    }
    memset(buf, 0, (size_t) w * (size_t) h * 4);
    ctx = OSMesaCreateContext(OSMESA_RGBA, 0);
    if (ctx == 0 || !OSMesaMakeCurrent(ctx, (void *) buf, GL_UNSIGNED_BYTE, w, h)) {
        printf("RDNTEAPOT FAIL no context\n");
        return 1;
    }
    /* what the host needs to predict the triangle count (docs/M3A_PLAN.md 5 A):
       32 glEvalMesh2 calls, grid x grid cells each, two triangles a cell */
    printf("RDNTEAPOT step=begin w=%d h=%d grid=%d expected=%d cull=%d\n",
           w, h, grid, 64 * grid * grid, cull);

    glViewport(0, 0, w, h);
    glMatrixMode(GL_PROJECTION);
    glLoadIdentity();
    glOrtho(-2.0, 2.0, -2.0, 2.0, -10.0, 10.0);
    glMatrixMode(GL_MODELVIEW);
    glLoadIdentity();
    glRotatef(20.0F, 1.0F, 0.0F, 0.0F);
    glRotatef(-30.0F, 0.0F, 1.0F, 0.0F);

    glEnable(GL_LIGHTING);
    glEnable(GL_LIGHT0);
    glLightfv(GL_LIGHT0, GL_POSITION, lightPos);
    glMaterialfv(GL_FRONT_AND_BACK, GL_DIFFUSE, diffuse);
    glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT, ambient);
    glShadeModel(GL_SMOOTH);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    if (cull) {
        glCullFace(GL_BACK);
        glEnable(GL_CULL_FACE);
    }

    /*
     * M3h: THE FENCE (docs/M3H_PLAN.md 2, H1).  With RDNTeapotFence set, the
     * whole mapped window is filled with a pattern BEFORE anything is drawn,
     * and after glFinish every word outside the colour surface (w x 4 x h at 0)
     * and the depth buffer (rows up to 16 x pitch up to 32 x 2 at the depth
     * offset) must still hold it -- what the reference allocates for a tiled
     * depth buffer, measured on this card rather than assumed.  The stock link
     * has no window, so it checks nothing.
     */
    if (getenv("RDNTeapotFence") != 0) {
        fwin = (unsigned long *) osrdn_surf_window(&fbytes);
        if (fwin != 0) {
            unsigned long k;

            for (k = 0UL; k < fbytes / 4UL; k++)
                fwin[k] = 0xa5a50000UL | (k & 0xffffUL);
        }
    }

    glClearColor(0.1F, 0.1F, 0.3F, 1.0F);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
    teapot(grid, 1.0, GL_FILL);
    glFinish();

    /*
     * M3g: WHAT AN ORDINARY PROGRAM SEES.  Its own array, right after glFinish,
     * taken BEFORE OSMesaGetColorBuffer -- which copies the surface back itself
     * and would hide the answer.  It must equal the picture GetColorBuffer
     * returns (docs/M3G_PLAN.md 3).
     */
    snap = (unsigned char *) malloc((size_t) w * (size_t) h * 4);
    if (snap == 0) {
        printf("RDNTEAPOT FAIL no memory\n");
        return 1;
    }
    memcpy(snap, buf, (size_t) w * (size_t) h * 4);

    /*
     * READ THROUGH OSMesaGetColorBuffer, NOT `buf`.  The accelerated link draws
     * into a substituted surface and copies it into the application's array
     * only at osmesa.c 576, 746 and 892 -- glFinish is not one of them (see
     * osrdn-mesa-tri.c's header).  The first run of this program read `buf`
     * after glFinish and got 4096 black pixels: the clear colour was never
     * copied back either.  In the stock link this returns `buf` itself.
     *
     * An ordinary OSMesa program that reads its own array after glFinish
     * therefore sees nothing under libGL_radeon.a -- recorded as an open G1
     * item (docs/M3A_PLAN.md 13), not papered over here.
     */
    {
        GLint gw, gh, gf;
        void *gb = 0;

        if (!OSMesaGetColorBuffer(ctx, &gw, &gh, &gf, &gb) || gb == 0 ||
            gw != w || gh != h) {
            printf("RDNTEAPOT FAIL OSMesaGetColorBuffer\n");
            return 1;
        }
        say();
        sayFailed();
        if (fwin != 0) {
            unsigned long cEnd = (unsigned long) w * 4UL * (unsigned long) h;
            unsigned long zOff = (unsigned long) OSRDN_TRI_DEPTH_BYTE_OFF;
            unsigned long zEnd = zOff + (((unsigned long) h + 15UL) & ~15UL) *
                                 (((unsigned long) w + 31UL) & ~31UL) * 2UL;
            unsigned long k, a, changed = 0UL, first = ~0UL, last = 0UL;

            for (k = 0UL; k < fbytes / 4UL; k++) {
                a = k * 4UL;
                if (a < cEnd || (a >= zOff && a < zEnd))
                    continue;
                if (fwin[k] != (0xa5a50000UL | (k & 0xffffUL))) {
                    changed++;
                    if (first == ~0UL)
                        first = a;
                    last = a;
                }
            }
            printf("RDNTEAPOT step=fence window=%lu colourend=%lu depthoff=%lu depthend=%lu "
                   "changed=%lu first=%lu last=%lu\n", fbytes, cEnd, zOff, zEnd, changed,
                   first == ~0UL ? 0UL : first, last);
        }
        {
            const osrdn_hook_counts *hc = OSRDNMesaHookCounts();
            unsigned long differ = 0UL;
            size_t k;

            for (k = 0; k < (size_t) w * (size_t) h * 4; k++)
                if (snap[k] != ((const unsigned char *) gb)[k])
                    differ++;
            printf("RDNTEAPOT step=finish-sync same=%d differ=%lu finishes=%lu "
                   "fmirrors=%lu foreign=%lu notup=%lu\n",
                   differ == 0UL ? 1 : 0, differ, hc->finishes, hc->finishMirrors,
                   hc->finishForeign, hc->notUp);
        }
        if (!writePpm(out, (const unsigned char *) gb, w, h)) {
            printf("RDNTEAPOT FAIL cannot write %s\n", out);
            return 1;
        }
    }
    printf("RDNTEAPOT step=done file=%s\n", out);
    OSMesaDestroyContext(ctx);
    free(snap);
    free(buf);
    return 0;
}
