/*
 * osrdn-mesa-render.c - M1b gate C: one scene, drawn twice, compared
 * (docs/M1B_PLAN.md 6-C).
 *
 * The same source is linked against the stock libGL.a and against
 * libGL_radeon.a.  The two runs must produce IDENTICAL pixels -- and the
 * accelerated run must, in that same run, show counters that are not zero.
 * Either half alone proves nothing: identical pixels are what a library whose
 * hooks were never called would also give, and non-zero counters are what a
 * library that wrecked the picture would also give.
 *
 * Build on the target (stock):
 *   cc -O -Wall -I<prefix>/Headers -o rdnrender osrdn-mesa-render.c \
 *      -L<prefix>/Libraries -lGL -lm
 * and with -lGL_radeon (plus -L pointing at the build) for the accelerated one.
 *
 * The scene is chosen so that BOTH classes occur: some state changes are ones
 * we would take (nothing enabled, and depth alone), some are ones we would
 * decline (blend on).  A scene that only produced one class would make gate D
 * unable to tell a narrow test from a broad one.
 *
 * Every line starts "RDNREND ".
 */

#include <GL/osmesa.h>
#include <GL/gl.h>

int printf(const char *, ...);

#define W   64
#define H   64

static unsigned long pix[W * H];

/* The counters, when this is the accelerated build.  A stock build has no such
   symbol, so it is reached weakly: the accelerated test program is compiled
   with -DRDN_ACCEL and the stock one without.  Nothing else differs. */
#ifdef RDN_ACCEL
#include "OSRDNMesaHook.h"
#endif

static void
tri(float x0, float y0, float x1, float y1, float x2, float y2,
    float r, float g, float b)
{
    glBegin(GL_TRIANGLES);
    glColor3f(r, g, b);
    glVertex3f(x0, y0, 0.0f);
    glVertex3f(x1, y1, -0.5f);
    glVertex3f(x2, y2, 0.5f);
    glEnd();
}

int
main(int argc, char **argv)
{
    OSMesaContext ctx;
    const char *runid;
    int i;

    if (argc != 2) {
        printf("RDNREND usage: rdnrender <runid>\n");
        return 2;
    }
    runid = argv[1];

#ifdef RDN_ACCEL
    {
        const osrdn_hook_counts *c = OSRDNMesaHookCounts();

        /* BEFORE anything: every counter must be zero.  Reading them after the
           fact only shows they moved at some point; reading them here and
           there shows they moved during THIS run. */
        printf("RDNREND run=%s step=before update=%lu take=%lu decline=%lu noaccel=%lu\n",
               runid, c->hook[OSRDN_HOOK_UPDATE_STATE], c->cls[OSRDN_CLASS_WOULD_TAKE],
               c->cls[OSRDN_CLASS_WOULD_DECLINE], c->cls[OSRDN_CLASS_NO_ACCEL]);
    }
#else
    printf("RDNREND run=%s step=before stock\n", runid);
#endif

    ctx = OSMesaCreateContext(OSMESA_RGBA, 0);
    if (!ctx) {
        printf("RDNREND run=%s step=context failed\n", runid);
        return 3;
    }
    if (!OSMesaMakeCurrent(ctx, (void *)pix, GL_UNSIGNED_BYTE, W, H)) {
        printf("RDNREND run=%s step=current failed\n", runid);
        return 3;
    }

    glViewport(0, 0, W, H);
    glMatrixMode(GL_PROJECTION);
    glLoadIdentity();
    glOrtho(0.0, (double)W, 0.0, (double)H, -1.0, 1.0);
    glMatrixMode(GL_MODELVIEW);
    glLoadIdentity();

    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    /* a state we would take: nothing enabled */
    glShadeModel(GL_FLAT);
    tri(4.0f, 4.0f, 40.0f, 8.0f, 10.0f, 44.0f, 1.0f, 0.0f, 0.0f);

    /* still a state we would take: depth alone */
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LESS);
    tri(20.0f, 20.0f, 60.0f, 24.0f, 26.0f, 60.0f, 0.0f, 1.0f, 0.0f);
    glDisable(GL_DEPTH_TEST);

    /* one we would decline: blending is a raster feature we have not built */
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    tri(8.0f, 30.0f, 48.0f, 34.0f, 14.0f, 58.0f, 0.0f, 0.0f, 1.0f);
    glDisable(GL_BLEND);

    /* and one more we would take, after the decline, so the order cannot be
       mistaken for "it stopped working once it declined" */
    glShadeModel(GL_SMOOTH);
    tri(30.0f, 4.0f, 60.0f, 10.0f, 34.0f, 30.0f, 1.0f, 1.0f, 0.0f);

    glFinish();

#ifdef RDN_ACCEL
    {
        const osrdn_hook_counts *c = OSRDNMesaHookCounts();

        printf("RDNREND run=%s step=after update=%lu take=%lu decline=%lu noaccel=%lu "
               "verdict=%lu row=%lu yup=%lu\n",
               runid, c->hook[OSRDN_HOOK_UPDATE_STATE], c->cls[OSRDN_CLASS_WOULD_TAKE],
               c->cls[OSRDN_CLASS_WOULD_DECLINE], c->cls[OSRDN_CLASS_NO_ACCEL],
               c->verdict, c->rowLength, c->yUp);
        printf("RDNREND run=%s step=raster seen=%08lx declined=%08lx\n",
               runid, c->rasterSeen, c->rasterDeclined);
        printf("RDNREND run=%s step=why", runid);
        for (i = 0; i < OSRDN_WHY_REASONS; i++)
            printf(" %s=%lu", osrdn_class_why_name(i), c->why[i]);
        printf("\n");
        printf("RDNREND run=%s step=hooks", runid);
        for (i = 0; i < OSRDN_HOOKS; i++)
            printf(" %s=%lu", OSRDNMesaHookName(i), c->hook[i]);
        printf("\n");
    }
#endif

    /* the picture, as words, for the host to compare byte for byte */
    printf("RDNREND run=%s step=pixels w=%d h=%d\n", runid, W, H);
    for (i = 0; i < W * H; i++) {
        if ((i % 8) == 0)
            printf("RDNREND px %05d", i);
        printf(" %08lx", pix[i]);
        if ((i % 8) == 7)
            printf("\n");
    }
    printf("RDNREND run=%s step=done\n", runid);
    OSMesaDestroyContext(ctx);
    return 0;
}
