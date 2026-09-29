/*
 * osrdn-mesa-surface.c - M1c gate C: the eight steps, in ONE run
 * (docs/M1C_PLAN.md 6-C).
 *
 * Splitting these across runs is what the review found wrong with the first
 * draft: an implementation that behaved differently per run would pass every
 * gate separately.  So one process walks all four (wasBound, accelBuf)
 * combinations, draws between them, and prints the counters and the pixels at
 * the end -- and the host judges the whole transcript together.
 *
 * Build on the target:
 *   cc -O -Wall -DRDN_ACCEL -I<prefix>/Headers -I<mesa dir> \
 *      -o rdnsurface osrdn-mesa-surface.c libGL_radeon.a -lm
 *
 * Every line starts "RDNSURF ".
 */

#include <GL/osmesa.h>
#include <GL/gl.h>

/* No #ifdef here on purpose: the stock link gets the same calls, answered by
   osrdn-mesa-nocount.c with zeroes.  One source, two links -- a difference in
   the pixels then has one possible cause. */
#include "OSRDNMesaHook.h"
#include "OSRDNMesaSurface.h"

int printf(const char *, ...);

#define W       64
#define H       64
#define W2      32          /* the other size, to force a refused rebind */

static unsigned long pixA[W * H];
static unsigned long pixB[W * H];
static unsigned long pixC[W2 * W2];

static void
scene(int w, int h)
{
    glViewport(0, 0, w, h);
    glMatrixMode(GL_PROJECTION);
    glLoadIdentity();
    glOrtho(0.0, (double)w, 0.0, (double)h, -1.0, 1.0);
    glMatrixMode(GL_MODELVIEW);
    glLoadIdentity();
    glClearColor(0.0f, 0.0f, 0.0f, 0.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glShadeModel(GL_FLAT);
    glBegin(GL_TRIANGLES);
    glColor3f(1.0f, 0.0f, 0.0f);
    glVertex3f(w * 0.06f, h * 0.06f, 0.0f);
    glVertex3f(w * 0.62f, h * 0.12f, 0.0f);
    glVertex3f(w * 0.16f, h * 0.70f, 0.0f);
    glColor3f(0.0f, 1.0f, 0.0f);
    glVertex3f(w * 0.30f, h * 0.30f, 0.0f);
    glVertex3f(w * 0.94f, h * 0.38f, 0.0f);
    glVertex3f(w * 0.40f, h * 0.94f, 0.0f);
    glEnd();
    glFinish();
}

static void
say(const char *runid, const char *step)
{
    const osrdn_hook_counts *h = OSRDNMesaHookCounts();
    const osrdn_surf_counts *s = OSRDNMesaSurfaceCounts();
    int i;

    printf("RDNSURF run=%s step=%s taken=%lu maps=%lu unmaps=%lu live=%lu livemax=%lu "
           "mirrors=%lu idle=%lu\n",
           runid, step, s->taken, s->maps, s->unmaps, s->live, s->liveMax,
           s->mirrors, s->mirrorIdle);
    printf("RDNSURF run=%s step=%s-refused", runid, step);
    for (i = 0; i < OSRDN_SURF_REASONS; i++)
        printf(" %s=%lu", OSRDNMesaSurfaceWhyName(i), s->refused[i]);
    printf("\n");
    printf("RDNSURF run=%s step=%s-hooks", runid, step);
    for (i = 0; i < OSRDN_HOOKS; i++)
        printf(" %s=%lu", OSRDNMesaHookName(i), h->hook[i]);
    printf("\n");
    printf("RDNSURF run=%s step=%s-raster seen=%08lx declined=%08lx last=%08lx\n",
           runid, step, h->rasterSeen, h->rasterDeclined, h->rasterLast);
}

static void
dump(const char *runid, const char *tag, unsigned long *p, int n)
{
    int i;

    printf("RDNSURF run=%s step=pixels tag=%s n=%d\n", runid, tag, n);
    for (i = 0; i < n; i++) {
        if ((i % 8) == 0)
            printf("RDNSURF px %s %05d", tag, i);
        printf(" %08lx", p[i]);
        if ((i % 8) == 7)
            printf("\n");
    }
}

int
main(int argc, char **argv)
{
    OSMesaContext c1, c2;
    const char *runid;

    if (argc != 2) {
        printf("RDNSURF usage: rdnsurface <runid>\n");
        return 2;
    }
    runid = argv[1];
    say(runid, "before");

    c1 = OSMesaCreateContext(OSMESA_RGBA, 0);
    if (!c1) {
        printf("RDNSURF run=%s step=context1 failed\n", runid);
        return 3;
    }

    /* 1. first bind: wasBound was 0, and the surface must be taken */
    if (!OSMesaMakeCurrent(c1, (void *)pixA, GL_UNSIGNED_BYTE, W, H)) {
        printf("RDNSURF run=%s step=bind1 failed\n", runid);
        return 3;
    }
    say(runid, "bind1");

    /* 2. draw into it */
    scene(W, H);
    say(runid, "draw1");

    /* 4. rebind at the SAME size: wasBound is 1 and it must be taken again */
    if (!OSMesaMakeCurrent(c1, (void *)pixB, GL_UNSIGNED_BYTE, W, H)) {
        printf("RDNSURF run=%s step=bind2 failed\n", runid);
        return 3;
    }
    say(runid, "bind2");
    scene(W, H);
    say(runid, "draw2");

    /* 5. the two paths that reach Stride and AppBuffer are BOTH behind
          BoundTo(ctx) -- a pixel-store change (osmesa.c 741-744) and a colour
          buffer query (888-890).  So they have to be exercised WHILE the
          surface is held; doing them after the release, as the first draft
          did, left Stride=0 AppBuffer=0 and the claim "six hooks are real"
          was a claim about four. */
    {
        void *qbuf = 0;
        GLint qw = 0, qh = 0, qfmt = 0;

        OSMesaGetColorBuffer(c1, &qw, &qh, &qfmt, &qbuf);
        printf("RDNSURF run=%s step=getcolour w=%d h=%d fmt=%d buf=%d\n",
               runid, (int)qw, (int)qh, (int)qfmt, qbuf != 0);
        say(runid, "getcolour");
        /* and a pixel store the surface cannot serve: it ends the substitution
           through the OTHER path, which is what Stride is asked for */
        OSMesaPixelStore(OSMESA_ROW_LENGTH, W + 8);
        say(runid, "pixelstore");
        /* take it back for the steps below */
        if (!OSMesaMakeCurrent(c1, (void *)pixB, GL_UNSIGNED_BYTE, W, H)) {
            printf("RDNSURF run=%s step=retake failed\n", runid);
            return 3;
        }
        OSMesaPixelStore(OSMESA_ROW_LENGTH, 0);
        say(runid, "retake");
    }

    /* 6. a second context WHILE THE FIRST STILL OWNS IT.  The order matters and
          the first draft got it wrong: after the size refusal below, the leave
          path releases the surface, so a second context asking then would be
          given it -- correctly -- and the OWNED refusal would never be seen. */
    c2 = OSMesaCreateContext(OSMESA_RGBA, 0);
    if (!c2) {
        printf("RDNSURF run=%s step=context2 failed\n", runid);
        return 3;
    }
    if (!OSMesaMakeCurrent(c2, (void *)pixB, GL_UNSIGNED_BYTE, W, H)) {
        printf("RDNSURF run=%s step=bind-second failed\n", runid);
        return 3;
    }
    say(runid, "bind-second-refused");
    scene(W, H);
    say(runid, "draw-second");

    /* put the first context back, so the size refusal below is ITS refusal */
    if (!OSMesaMakeCurrent(c1, (void *)pixA, GL_UNSIGNED_BYTE, W, H)) {
        printf("RDNSURF run=%s step=rebind1 failed\n", runid);
        return 3;
    }
    say(runid, "rebind1");

    /* 6. rebind at a DIFFERENT size: the surface cannot be that, so it is
          refused -- and osmesa.c then runs its leave path, which mirrors and
          releases without asking whether anything was bound */
    if (!OSMesaMakeCurrent(c1, (void *)pixC, GL_UNSIGNED_BYTE, W2, W2)) {
        printf("RDNSURF run=%s step=bind3 failed\n", runid);
        return 3;
    }
    say(runid, "bind3-refused");

    /* 6. and drawing still works, now into the application's own buffer */
    scene(W2, W2);
    say(runid, "draw3");

    /* 8. destruction gives the surface back */
    OSMesaDestroyContext(c2);
    say(runid, "destroy2");
    OSMesaDestroyContext(c1);
    say(runid, "destroy1");

    dump(runid, "A", pixA, W * H);
    dump(runid, "B", pixB, W * H);
    dump(runid, "C", pixC, W2 * W2);
    printf("RDNSURF run=%s step=done\n", runid);
    return 0;
}
