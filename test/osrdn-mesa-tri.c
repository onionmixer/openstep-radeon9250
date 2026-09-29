/*
 * osrdn-mesa-tri.c - M1d: the first hardware triangle, as ONE approval run
 * (docs/M1D_PLAN.md 5).
 *
 * One process walks four states and prints, at each of them, the counters and
 * the vertices that actually went to the card.  Splitting these across runs is
 * what the M1c review found wrong with its first draft: an implementation that
 * behaved differently per run would pass every gate separately.
 *
 * READING THE PICTURE BACK IS NOT FREE.  The surface is mirrored into the
 * application's array at exactly three places (osmesa.c 576, 746, 892) and
 * OSMesaDestroyContext is not one of them -- a context destroyed after drawing
 * takes the drawing with it.  This test therefore reads through
 * OSMesaGetColorBuffer (892), which mirrors and leaves the substitution
 * standing, so the next state can be drawn without rebinding.
 *
 * Build on the target:
 *   cc -O -Wall -DRDN_ACCEL -I<prefix>/Headers -I<mesa dir> \
 *      -o rdntri osrdn-mesa-tri.c libGL_radeon.a -lm
 *
 * Every line starts "RDNTRI ".
 */

#include <sys/time.h>          /* M1l: gettimeofday, the only clock here */
#include <GL/osmesa.h>
#include <GL/gl.h>

/* No #ifdef: the stock link gets the same calls, answered with zeroes by
   osrdn-mesa-nocount.c.  One source, two links. */
#include "OSRDNMesaHook.h"
#include "OSRDNMesaClass.h"
#include "OSRDNMesaSurface.h"
#include "OSRDNMesaTri.h"
#include "OSRDNMesaTex.h"
#include "OSRDNMesaDepth.h"

int printf(const char *, ...);
extern char *getenv(const char *);

#define W       64
#define H       64
/* M1h: how many the multi scene draws -- printed, so the host can check that
   the number the library sent is the number this file meant to draw */
#define MULTI_TRIS 3
#define DEPTH_TRIS 2

/*
 * THE BOUND BUFFER AND THE SNAPSHOTS ARE DIFFERENT ARRAYS.
 *
 * The first version bound pixFlat and then snapshotted into pixFlat, so the
 * "flat" snapshot was the live buffer: every later step wrote through it and
 * what got dumped at the end was the picture after the LAST scene.  The card's
 * triangle really had been drawn and mirrored -- the test overwrote it.
 */
static unsigned long appBuf[(W + 8) * H];       /* room for the padded row length */
static unsigned long pixDraw[W * H];
static unsigned long pixCull[W * H];

/*
 * Two triangles, at coordinates the host can predict.  They are asymmetric on
 * purpose: a mirrored or transposed picture has to look different from a
 * correct one, and a symmetric scene would hide exactly the mistake most worth
 * catching the first time anything reaches the card.
 */
/*
 * ntri = 1 for the accelerated state.  The driver carries a client stream as a
 * CP_OP_ZCLEAR and refuses a ZCLEAR that has no ZPREP before it
 * (CP_WHY_NOT_PREPPED, measured on boot ed7bef6a -- docs/M1D_PLAN.md 4e), and
 * the runner can only issue one ZPREP before the process starts.  So one
 * triangle is what M1d claims: one triangle reaches the card.
 */
/* the M1e vertex colours: every channel varies widely, alpha included, so a
   run that forgot ALPHA_SHADE_GOURAUD or sent one colour three times cannot
   look like a correct one (docs/M1E_PLAN.md 5b).  k/255 round-trips exactly. */
#define C255    1.0f
#define C170    (170.0f / 255.0f)
#define C128    (128.0f / 255.0f)
#define C85     (85.0f / 255.0f)
#define C64     (64.0f / 255.0f)
#define C32     (32.0f / 255.0f)
#define C16     (16.0f / 255.0f)
#define C200    (200.0f / 255.0f)
/*
 * M1f.  The clear is NOT black: with a black destination almost every blend
 * term is zero and the gate could not tell blending from no blending.  And the
 * source alpha is below 255 for the same reason -- at alpha 255 the measured
 * factors are (256>>8)=1 and (1>>8)=0, so the result is the source exactly
 * (docs/M1F_PLAN.md 5c).
 */
#define CLR_R   (64.0f / 255.0f)
#define CLR_G   (128.0f / 255.0f)
#define CLR_B   (191.0f / 255.0f)
#define CLR_A   1.0f

/*
 * M1g.  The 8 x 8 map R6h measured with: every texel distinct, so a transposed
 * row or a wrong stride cannot look like a correct picture, and alpha 0xff so
 * no texel can be mistaken for a ZPREP pattern word.
 *
 * GL_REPLACE, NOT the default.  Mesa's default env mode is GL_MODULATE
 * (Mesa-3.4.2/src/context.c 602) and the card's prologue is a replace
 * (out = R0).  With a white vertex colour the two agree, which is exactly why
 * the classifier now refuses MODULATE instead of trusting the scene.
 */
#define TEXW    8
#define TEXH    8
static GLubyte texImg[TEXH][TEXW][4];

static void
maketex(void)
{
    int u, v;

    for (v = 0; v < TEXH; v++) {
        for (u = 0; u < TEXW; u++) {
            texImg[v][u][0] = (GLubyte)(u * 32);
            texImg[v][u][1] = (GLubyte)(v * 32);
            texImg[v][u][2] = (GLubyte)0x55;
            texImg[v][u][3] = (GLubyte)0xff;
        }
    }
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, TEXW, TEXH, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, (const GLvoid *)texImg);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
    glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE);
}

static void
scene(int ntri, int smooth, int blend, int tex, int multi, int depth)
{
    glViewport(0, 0, W, H);
    glMatrixMode(GL_PROJECTION);
    glLoadIdentity();
    glOrtho(0.0, (double)W, 0.0, (double)H, -1.0, 1.0);
    glMatrixMode(GL_MODELVIEW);
    glLoadIdentity();
    glClearColor(CLR_R, CLR_G, CLR_B, CLR_A);
    /*
     * M1i: THE DEPTH BUFFER IS CLEARED TOO, because a GL program clears it.
     *
     * Without this the STOCK link drew nothing at all: Mesa's allocator says in
     * its own comment that it does not initialise the depth buffer, so the
     * software depth test compared against whatever malloc returned and
     * rejected every pixel.  Our accelerated path did draw -- the library
     * clears the card's depth when it installs -- so the two pictures differed
     * in every pixel and the difference looked like an acceleration bug.
     *
     * (That difference is worth remembering: the library's clear-at-install is
     * NOT what GL says happens.  It is this rung's simplification, and the
     * general glClear path is named as out of scope in docs/M1I_PLAN.md 6.)
     */
    glClearDepth(1.0);
    glClear(GL_COLOR_BUFFER_BIT | (depth ? GL_DEPTH_BUFFER_BIT : 0));
    if (blend) {
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    } else {
        glDisable(GL_BLEND);
    }
    if (depth) {
        glEnable(GL_DEPTH_TEST);
        glDepthFunc(GL_LESS);
        glDepthMask(GL_TRUE);
    } else {
        glDisable(GL_DEPTH_TEST);
    }
    glShadeModel(smooth ? GL_SMOOTH : GL_FLAT);
    /*
     * M1i: TWO OVERLAPPING TRIANGLES AT DIFFERENT DEPTHS, each its own
     * submission.
     *
     * This asks the question nobody has measured: R6g showed that two draws
     * INSIDE ONE SUBMISSION see each other's depth, and M1h made every triangle
     * a submission of its own.  Whether depth survives ACROSS submissions -- a
     * cache purge and a fresh prologue in between -- is what this scene finds
     * out (docs/M1I_PLAN.md 8, Q6).
     *
     * The FAR one is drawn SECOND on purpose.  If depth works, it loses where
     * they overlap and the near colour stays; if depth silently does nothing,
     * the far one wins there, and the two pictures differ in exactly the
     * overlap.  Drawing the near one second would look the same either way.
     */
    if (depth) {
        glBegin(GL_TRIANGLES);
        glColor4f(C255, C64, C32, 1.0f);            /* NEAR, z = 0.25 */
        glVertex3f(4.0f, 4.0f, -0.5f);
        glVertex3f(36.0f, 4.0f, -0.5f);
        glVertex3f(4.0f, 36.0f, -0.5f);
        glColor4f(C32, C85, C255, 1.0f);            /* FAR, z = 0.75, drawn after */
        glVertex3f(12.0f, 12.0f, 0.5f);
        glVertex3f(44.0f, 12.0f, 0.5f);
        glVertex3f(12.0f, 44.0f, 0.5f);
        glEnd();
        glFinish();
        return;
    }
    /*
     * M1h: THREE TRIANGLES IN ONE FRAME.
     *
     * Until the driver stopped demanding a ZPREP per client submission, a
     * frame's second triangle fell back to software and the picture still came
     * out right -- Mesa drew it into the same surface.  That is why this scene
     * is not "one triangle again, twice": the three OVERLAP, in a known order,
     * so a triangle that was drawn by the wrong party at the wrong moment moves
     * pixels.  T3 is drawn last and must cover part of T1.
     *
     * Flat, unblended, untextured on purpose: this rung is about HOW MANY reach
     * the card, and every other feature is one already measured.
     */
    if (multi) {
        glDisable(GL_TEXTURE_2D);
        glBegin(GL_TRIANGLES);
        glColor4f(C255, C64, C32, 1.0f);            /* T1 */
        glVertex3f(4.0f, 4.0f, 0.0f);
        glVertex3f(28.0f, 4.0f, 0.0f);
        glVertex3f(4.0f, 28.0f, 0.0f);
        glColor4f(C32, C255, C85, 1.0f);            /* T2, clear of the others */
        glVertex3f(34.0f, 36.0f, 0.0f);
        glVertex3f(58.0f, 40.0f, 0.0f);
        glVertex3f(38.0f, 59.0f, 0.0f);
        glColor4f(C64, C85, C255, 1.0f);            /* T3, over part of T1 */
        glVertex3f(16.0f, 16.0f, 0.0f);
        glVertex3f(40.0f, 16.0f, 0.0f);
        glVertex3f(16.0f, 40.0f, 0.0f);
        glEnd();
        glFinish();
        return;
    }
    if (tex)
        glEnable(GL_TEXTURE_2D);
    else
        glDisable(GL_TEXTURE_2D);
    glBegin(GL_TRIANGLES);
    if (tex) {
        /*
         * ST 0 and 1 at the ends, so eight texels span twenty-four pixels and a
         * sample sits a third of a texel from its neighbours -- the closest any
         * of them comes to a texel boundary is a SIXTH of a texel (computed on
         * the host, tools/mesa/judge_m1d.py).  On a boundary the hardware's own
         * fixed point picks the side and nothing here could predict it, so the
         * margin is the point of these numbers, not the span.
         *
         * The colour is white and deliberately so: under GL_REPLACE it must not
         * reach the buffer, and white is the value that would hide the mistake
         * if it did -- so the transcript records the vertex words and the host
         * checks the pixels are texels, not that they merely look right.
         */
        glColor4f(1.0f, 1.0f, 1.0f, 1.0f);
        glTexCoord2f(0.0f, 0.0f); glVertex3f(4.0f, 4.0f, 0.0f);
        glTexCoord2f(1.0f, 0.0f); glVertex3f(28.0f, 4.0f, 0.0f);
        glTexCoord2f(0.0f, 1.0f); glVertex3f(4.0f, 28.0f, 0.0f);
    } else if (smooth) {
        /* three different colours, every channel including alpha */
        glColor4f(C255, C64,  C32,  C200); glVertex3f(4.0f, 4.0f, 0.0f);
        glColor4f(C16,  C255, C128, C170); glVertex3f(28.0f, 4.0f, 0.0f);
        glColor4f(C64,  C32,  C255, C85);  glVertex3f(4.0f, 28.0f, 0.0f);
    } else {
        /* alpha 128, not 255: see the note above the clear colour */
        glColor4f(1.0f, 0.0f, 0.0f, C128);
        glVertex3f(4.0f, 4.0f, 0.0f);
        glVertex3f(28.0f, 4.0f, 0.0f);
        glVertex3f(4.0f, 28.0f, 0.0f);
    }
    /*
     * The second triangle lies OUTSIDE the top-left 32 x 32 that R6e's oracle
     * can predict.  That is safe because it is drawn only in the steps where
     * nothing is submitted (culling is declined; the surface is not ours), and
     * the transcript records only what was sent -- but it is written down here
     * so that moving it into the submitting step is a deliberate act.
     */
    if (ntri > 1) {
        glColor3f(0.0f, 1.0f, 0.0f);
        glVertex3f(34.0f, 36.0f, 0.0f);
        glVertex3f(58.0f, 40.0f, 0.0f);
        glVertex3f(38.0f, 59.0f, 0.0f);
    }
    glEnd();
    glFinish();
}

static void
say(const char *runid, const char *step)
{
    const osrdn_hook_counts *h = OSRDNMesaHookCounts();
    const osrdn_tri_counts *t = OSRDNMesaTriCounts();
    unsigned long sum = 0UL;
    int i;

    printf("RDNTRI run=%s step=%s installs=%lu leaves=%lu triangles=%lu "
           "delegated=%lu nosw=%lu notbound=%lu slotsfull=%lu caps=%08lx shade=%04lx "
           "tex=%lu texup=%lu texbad=%lu texproj=%lu rmask=%08lx "
           "zclear=%lu zclearbad=%lu cli=%lu clc=%lu clp=%lu\n",
           runid, step, h->installs, h->leaves, h->triangles, h->delegated,
           h->noSoftware, h->notBound, h->slotsFull, h->caps, h->shade,
           h->tex, h->texUploads, h->texUploadBad, h->texProjective, h->rmask,
           h->depthClears, h->depthClearBad,
           h->clearInstalls, h->clearCalls, h->clearPassed);
    printf("RDNTRI run=%s step=%s-tri entered=%lu submitted=%lu maps=%lu opens=%lu "
           "words=%lu seed=%lu smoothsent=%lu blendsent=%lu texsent=%lu depthsent=%lu "
           "why=%lu at=%lu word=%08lx status=%lu\n",
           runid, step, t->entered, t->submitted, t->maps, t->opens, t->words,
           t->seed, t->smoothSent, t->blendSent, t->texSent, t->depthSent,
           t->lastWhy,
           t->lastAt, t->lastWord, t->lastStatus);
    /*
     * M1k.  Its own line, because it answers its own question: did the batch
     * happen, and did anything fall out of it.  Folding these into the -tri
     * line would have made a judge that matched the old shape stop seeing it.
     */
    printf("RDNTRI run=%s step=%s-batch adds=%lu flushes=%lu flushed=%lu "
           "failed=%lu replayed=%lu outside=%lu flushout=%lu desync=%lu "
           "rs=%lu rf=%lu rinst=%lu tbatched=%lu tflushes=%lu tfailed=%lu\n",
           runid, step, h->batchAdds, h->flushes, h->flushed, h->flushFailed,
           h->replayed, h->outsideRender, h->flushOutside, h->batchDesync,
           h->renderStarts, h->renderFinishes, h->renderInstalls,
           t->batched, t->flushes, t->flushFailed);
    /*
     * M1v: its own line.  A judge picks a line by its shape, so the group
     * numbers do not go on an existing one.  `lost` must be 0.
     */
    printf("RDNTRI run=%s step=%s-group groups=%lu declined=%lu lost=%lu "
           "tris=%lu installs=%lu\n", runid, step, h->groups, h->groupsDeclined,
           h->groupsLost, h->groupTris, h->groupInstalls);
    printf("RDNTRI run=%s step=%s-refused", runid, step);
    for (i = 0; i < OSRDN_TRI_REASONS; i++) {
        printf(" %s=%lu", OSRDNMesaTriWhyName(i), t->refused[i]);
        sum += t->refused[i];
    }
    /* The promise of this rung, as a number: everything this unit refused, the
       hook drew itself.  A difference here is a lost triangle. */
    printf(" SUM=%lu\n", sum);
    printf("RDNTRI run=%s step=%s-why", runid, step);
    for (i = 0; i < OSRDN_WHY_REASONS; i++)
        printf(" %s=%lu", osrdn_class_why_name(i), h->why[i]);
    printf("\n");
}

/* the vertices that really went out, so the host predicts from those and not
   from what this file meant to draw */
static void
sent(const char *runid, const char *step)
{
    const osrdn_tri_sent *s = OSRDNMesaTriSent();
    unsigned long k, n;
    int i;

    n = (s->n < (unsigned long)OSRDN_TRI_LOG) ? s->n : (unsigned long)OSRDN_TRI_LOG;
    /* `words` is how wide the last vertex really was -- five words, or SEVEN
       when the texture unit was on.  Printing a fixed fifteen would have cut a
       textured triangle in half and left the host to predict from the pieces,
       so the WIDTH is reported and the host reads it rather than assuming. */
    printf("RDNTRI run=%s step=%s-sent n=%lu kept=%lu words=%lu\n",
           runid, step, s->n, n, s->words);
    for (k = 0UL; k < n; k++) {
        printf("RDNTRI run=%s tri %lu", runid, k);
        for (i = 0; i < (int)s->words && i < OSRDN_TRI_LOG_WORDS; i++)
            printf(" %08lx", s->v[k][i]);
        printf("\n");
    }
}

/* the texels that really went into the card, for the same reason as the
   vertices: they are not in the CP stream, so the host cannot read them from
   anywhere else */
static void
texrows(const char *runid)
{
    const unsigned long *img = OSRDNMesaTexImage();
    const osrdn_tex_counts *t = OSRDNMesaTexCounts();
    int u, v;

    printf("RDNTRI run=%s step=tex uploads=%lu texels=%lu readbad=%lu first=%08lx\n",
           runid, t->uploads, t->texels, t->readBad, t->lastWord);
    for (v = 0; v < TEXH; v++) {
        printf("RDNTRI run=%s tex row=%d", runid, v);
        for (u = 0; u < TEXW; u++)
            printf(" %08lx", img[v * TEXW + u]);
        printf("\n");
    }
}

/* M1i: what the card left in the depth buffer, every fourth pixel.  A picture
   that is missing a corner cannot say whether the depth READ was wrong or the
   depth WRITE was; this can. */
static void
zdump(const char *runid)
{
    int x, y;

    for (y = 0; y < 64; y += 4) {
        printf("RDNTRI run=%s zrow %02d", runid, y);
        for (x = 0; x < 64; x += 4)
            printf(" %04lx", (unsigned long)(osrdn_depth_get(x, y) & 0xffffL));
        printf("\n");
    }
}

static void
grab(const char *runid, const char *tag, OSMesaContext c, unsigned long *into)
{
    void *buf = 0;
    GLint w = 0, h = 0, f = 0;
    int i;

    /* This is the mirror (osmesa.c 892): it walks the card surface back into
       the application's array and leaves the substitution in place. */
    if (!OSMesaGetColorBuffer(c, &w, &h, &f, &buf) || buf == 0) {
        printf("RDNTRI run=%s step=grab-%s failed\n", runid, tag);
        return;
    }
    for (i = 0; i < W * H; i++)
        into[i] = ((unsigned long *)buf)[i];
    printf("RDNTRI run=%s step=grab-%s w=%d h=%d\n", runid, tag, (int)w, (int)h);
}

static void
dump(const char *runid, const char *tag, unsigned long *p)
{
    int i;

    printf("RDNTRI run=%s step=pixels tag=%s n=%d\n", runid, tag, W * H);
    for (i = 0; i < W * H; i++) {
        if ((i % 8) == 0)
            printf("RDNTRI px %s %05d", tag, i);
        printf(" %08lx", p[i]);
        if ((i % 8) == 7)
            printf("\n");
    }
}

/*
 * M1l: THE TIMING SWEEP.
 *
 * What is NOT measured in the SWEEP, and why the grid arm below exists anyway:
 * how long the card makes us wait.  The driver times its own spin and logs it,
 * and 118 client submissions from M1d..M1k give a median of 0 us and a maximum
 * of 6 (docs/M1L_PLAN.md 6).
 *
 * M1q RE-READ THOSE 118.  Every one carried 17..57 words -- one to three
 * triangles.  At n=72 the stream is 1,082 words and nothing has ever timed the
 * wait there; the whole M1 ladder's logs carry no `RDN-R5 wait` line at all.
 * So "the card does not make us wait" is true where it was measured and unknown
 * where this sweep runs, and profile()'s grid arm goes and measures it.
 *
 * THE CLOCK IS READ AROUND A BLOCK, NEVER AROUND A SUBMISSION.  gettimeofday
 * on this machine resolves 4 us and a pair costs about 4 us, so 1% needs an
 * interval of at least 400 us.  K is chosen so a block carries at least eight
 * submissions, which also divides the pair's own cost by eight.
 *
 * The points straddle a boundary on purpose.  The user-side stream crosses a
 * 4 KiB page between n=65 (4092 B) and n=66 (4152 B); {1,18,36,60} fit a line
 * below it and {66,72} test that line's prediction above it.
 */
#define PROF_PTS    6
#define PROF_REPS   9
#define PROF_MIN_SUBMITS 8

static const int profN[PROF_PTS] = { 1, 18, 36, 60, 66, 72 };
/* batching off makes each triangle its own submission, so a handful of points
   is a whole answer there -- and 72 of them per block would be 72 ioctls */
static const int profNoff[2] = { 1, 36 };

/*
 * M1q: THE LEG, AND WHY THE TILE SPACING IS A CONSTANT.
 *
 * The sweep varies one thing -- how many PIXELS a triangle covers -- while the
 * stream stays fifteen words a triangle (OSRDNMesaTri.c:49 holds that).  The
 * first draft scaled the tile spacing with the leg, `(63-leg)/11`, so that the
 * tiles would not overlap.  That moves the ORIGINS, the sub-pixel phase and the
 * overlap pattern along with the leg, and then a time difference cannot be read
 * as an area difference (docs/M1Q_PLAN.md 10, cross-review #1).
 *
 * A constant 2 keeps the seventy-two origins LITERALLY THE SAME at every leg.
 * Checked in python over all 72 origins x 5 legs with the measured raster rule:
 * every origin covers the same count, and every triangle is wholly inside the
 * 64x64 buffer (docs/M1Q_PLAN.md 5).  Overlap is fine -- depth and blending are
 * off, so a later triangle overwrites pixels and no triangle does less work.
 */
#define PROF_STEP   2
#define PROF_LEGS   5
/* M1q grid: submissions per cell.  Two, because the driver prints about 2 KB
   of log a submission and the kernel's message buffer is 4 KB (recorded). */
#define PROF_GRID_SUBS 2
#define PROF_GRID_PTS  4

static const int profLeg[PROF_LEGS] = { 2, 4, 8, 16, 32 };
/* what tri_oracle.cover(MEASURED) says each one covers, so the target reports a
   number the host can check instead of the host assuming one */
static const int profLegPx[PROF_LEGS] = { 3, 10, 36, 136, 528 };
/* M1q grid: the n axis.  Words are 15n+2 and pixels are n*profLegPx,
   so the two legs at the same n differ in pixels ONLY. */
static const int profGridN[PROF_GRID_PTS] = { 1, 18, 36, 72 };

static unsigned long
profElapsed(struct timeval a, struct timeval b)
{
    return (unsigned long)(b.tv_sec - a.tv_sec) * 1000000UL +
           (unsigned long)(b.tv_usec - a.tv_usec);
}

/* n right isosceles triangles with legs `leg`, tiled on a FIXED grid: equal
   work each, and the only thing `leg` changes is the pixels (M1q) */
static void
profTris(int n, int leg)
{
    int i, x, y;
    float e = (float)leg;

    glBegin(GL_TRIANGLES);
    for (i = 0; i < n; i++) {
        x = (i % 12) * PROF_STEP;
        y = (i / 12) * PROF_STEP;
        glVertex3f((float)x + 0.5f,     (float)y + 0.5f,     0.0f);
        glVertex3f((float)x + 0.5f + e, (float)y + 0.5f,     0.0f);
        glVertex3f((float)x + 0.5f,     (float)y + 0.5f + e, 0.0f);
    }
    glEnd();
    /*
     * glEnd DOES NOT SUBMIT.  Mesa keeps filling one vertex buffer across many
     * glBegin/glEnd pairs and renders it when the buffer is full, so the first
     * version of this sweep drew 18,216 triangles in 254 submissions -- about
     * 72 each, whatever n said.  n controlled nothing and the numbers were the
     * cost of the VB filling up.
     *
     * glFlush is what closes a pass: _mesa_Flush's first act is FLUSH_VB
     * (context.c:2029, types.h:2103-2105), which runs the pipeline, which calls
     * our RenderFinish, which sends the batch.  With it, one call here is one
     * submission carrying exactly n triangles.
     */
    glFlush();
}

/*
 * M1q: THE GEOMETRY GATE, AND WHY IT IS A PICTURE AND NOT A CLOCK.
 *
 * The sweep's whole claim is that `leg` changes the pixels and nothing else.
 * The first draft proposed to check that by watching the software arm's time
 * grow -- which is not a check: a software rasteriser has a per-triangle setup
 * cost that can swamp ten pixels, and a software arm that grows says nothing
 * about what the CARD received (docs/M1Q_PLAN.md 10, cross-review #3 and #4).
 *
 * So the gate counts PIXELS.  One triangle per leg, cleared before and grabbed
 * after, counting the words that changed.  `grab` walks the card's surface back
 * (osmesa.c 892), so on the accelerated link this counts what the CARD drew --
 * exactly the thing a clock cannot see.  The host compares each count with
 * tri_oracle.cover(MEASURED); `want=` carries this file's copy of that number so
 * a mismatch is visible in the transcript itself.
 *
 * It runs OUTSIDE the timed blocks, so it cannot contribute to any `us=`.
 */
static void
profCover(const char *runid, OSMesaContext c, unsigned long *before,
          unsigned long *after)
{
    int li, i, px;

    for (li = 0; li < PROF_LEGS; li++) {
        glClear(GL_COLOR_BUFFER_BIT);
        glFlush();
        grab(runid, "cover-bg", c, before);
        profTris(1, profLeg[li]);
        grab(runid, "cover-fg", c, after);
        px = 0;
        for (i = 0; i < W * H; i++)
            if (before[i] != after[i])
                px++;
        printf("RDNTRI run=%s step=prof-cover leg=%d px=%d want=%d\n",
               runid, profLeg[li], px, profLegPx[li]);
    }
}

static void
profile(const char *runid, OSMesaContext ctx, unsigned long *b1,
        unsigned long *b2)
{
    struct timeval t0, t1;
    const int *pts;
    int npts, p, r, k, kk, on, li;
    unsigned long us;

    int gridLeg = 0, gridN = 0;
    const char *e;

    on = osrdn_tri_batch_enabled();
    pts = on ? profN : profNoff;
    npts = on ? PROF_PTS : 2;

    /*
     * M1q: the cell comes from the environment, so the runner names it and the
     * program stays one binary.
     *
     * The variables carry an INDEX, one character, not a number.  No atoi, for
     * the reason the library has none either -- and because an index cannot name
     * a leg the oracle has no pixel count for.  Both or neither: half a cell
     * would run the whole sweep with the driver's log on and drown the message
     * buffer.
     */
    e = getenv("RDNProfGridLeg");
    if (e != 0 && e[0] >= '0' && e[0] < ('0' + PROF_LEGS) && e[1] == 0) {
        const char *f = getenv("RDNProfGridN");

        if (f != 0 && f[0] >= '0' && f[0] < ('0' + PROF_GRID_PTS) && f[1] == 0) {
            gridLeg = profLeg[e[0] - '0'];
            gridN = profGridN[f[0] - '0'];
        }
    }

    /* the clock's own cost, measured in this run rather than assumed */
    gettimeofday(&t0, (struct timezone *)0);
    gettimeofday(&t1, (struct timezone *)0);
    printf("RDNTRI run=%s step=prof-clock pair_us=%lu batch=%d pts=%d reps=%d\n",
           runid, profElapsed(t0, t1), on, npts, PROF_REPS);

    /*
     * M1q: THE GRID ARM -- ONE CELL A PROCESS, DRIVER LOG ON.
     *
     * The sweep above reads the WALL CLOCK, which cannot see how much of a
     * submission the card owns.  The driver can: cpWait times its own spin and
     * osrdn_modelog.m prints `idle=evals/limit/us rptr=...`.  So one cell of the
     * (leg x n) grid runs here with only a couple of submissions, the driver's
     * log left ON, and the host pairs each `RDN-R7B stage words=` with the
     * `RDN-R5 wait` line that follows it.
     *
     * A CELL A PROCESS, not a loop: 25 log lines a submission is about 2 KB and
     * the kernel's msgbuf is 4 KB (recorded), so a long loop would throw the
     * early lines away.  The runner reads the log between cells.
     */
    if (gridLeg > 0) {
        int gk;

        printf("RDNTRI run=%s step=prof-grid leg=%d n=%d subs=%d\n",
               runid, gridLeg, gridN, PROF_GRID_SUBS);
        for (gk = 0; gk < PROF_GRID_SUBS; gk++)
            profTris(gridN, gridLeg);
        printf("RDNTRI run=%s step=prof-grid-done leg=%d n=%d\n",
               runid, gridLeg, gridN);
        return;
    }

    /* AFTER the grid returns, never before it: the cover gate is five more
       submissions, and with the driver's log on those 10 KB would push the
       grid's own lines out of a 4 KB message buffer. */
    profCover(runid, ctx, b1, b2);

    /*
     * M1q REPLACES M1p's A B B A DIMENSION WITH THE LEG.
     *
     * M1p asked whether writing the words to the cache-inhibited window costs
     * anything and measured -7 us against a predicted +593.  It does not.  So
     * the path is nailed to the window here -- `copyin=` stays in the line so
     * older judges keep reading it -- and the block-adjacent slot the A B B A
     * used goes to the leg, which is the live question.
     *
     * The ROTATION is what A B B A was for: a linear drift over a run must not
     * land on one leg.  Starting the inner loop at `r % PROF_LEGS` gives every
     * leg every position in the order across the repetitions.
     */
    osrdn_tri_set_copyin(0);
    for (r = 0; r < PROF_REPS; r++) {
        for (p = 0; p < npts; p++) {
            /* submissions per block: K with batching, K*n without */
            if (on)
                kk = PROF_MIN_SUBMITS;
            else
                kk = (PROF_MIN_SUBMITS + pts[p] - 1) / pts[p];
            for (li = 0; li < PROF_LEGS; li++) {
                int leg = profLeg[(li + r) % PROF_LEGS];

                gettimeofday(&t0, (struct timezone *)0);
                for (k = 0; k < kk; k++)
                    profTris(pts[p], leg);
                gettimeofday(&t1, (struct timezone *)0);
                us = profElapsed(t0, t1);
                printf("RDNTRI run=%s step=prof n=%d k=%d subs=%d rep=%d "
                       "copyin=%d leg=%d us=%lu\n",
                       runid, pts[p], kk, on ? kk : kk * pts[p], r, 0, leg, us);
            }
        }
    }
}

int
main(int argc, char **argv)
{
    OSMesaContext c1;
    const char *runid;
    int smooth, blend, tex, multi, depth, prof, i;

    if (argc < 3 || argc > 7) {
        printf("RDNTRI usage: rdntri <runid> flat|smooth [blend] [tex] [multi] "
               "[depth]\n");
        return 2;
    }
    runid = argv[1];
    /*
     * ONE PROCESS SUBMITS ONCE.  The driver carries a client stream as a
     * CP_OP_ZCLEAR and refuses one with no ZPREP since the last
     * (docs/M1D_PLAN.md 4e), and the runner can only issue a ZPREP before the
     * process starts.  So flat and Gouraud are two runs, not two steps.
     */
    smooth = (argv[2][0] == 's') ? 1 : 0;
    blend = tex = multi = depth = prof = 0;
    for (i = 3; i < argc; i++) {
        if (argv[i][0] == 'b')
            blend = 1;
        else if (argv[i][0] == 't')
            tex = 1;
        else if (argv[i][0] == 'm')
            multi = 1;
        else if (argv[i][0] == 'd')
            depth = 1;
        else if (argv[i][0] == 'p')
            prof = 1;
    }
    printf("RDNTRI run=%s step=mode smooth=%d blend=%d tex=%d multi=%d tris=%d "
           "depth=%d\n", runid, smooth, blend, tex, multi,
           multi ? MULTI_TRIS : (depth ? DEPTH_TRIS : 1), depth);
    /* M1r: its own line, not a field bolted onto step=mode -- a judge picks a
       line by its shape, and widening an existing one makes every older judge
       stop seeing it. */
    printf("RDNTRI run=%s step=knobs sentlog=%d batch=%d nullsend=%d\n", runid,
           osrdn_tri_sentlog_enabled(), osrdn_tri_batch_enabled(),
           osrdn_tri_nullsend_enabled());
    say(runid, "before");

    c1 = OSMesaCreateContext(OSMESA_RGBA, 0);
    if (!c1) {
        printf("RDNTRI run=%s step=context failed\n", runid);
        return 3;
    }
    if (!OSMesaMakeCurrent(c1, (void *)appBuf, GL_UNSIGNED_BYTE, W, H)) {
        printf("RDNTRI run=%s step=bind failed\n", runid);
        return 3;
    }
    say(runid, "bind");

    /* The image goes in before anything is drawn.  It cannot go in earlier:
       there is no context to hold it, and the runner's ZPREP -- which fills the
       whole window, texels included -- happens before this process starts
       (mesa/OSRDNMesaTex.h). */
    if (tex)
        maketex();

    /* 1. the one state this mode is about.  This is the rung. */
    scene(1, smooth, blend, tex, multi, depth);
    say(runid, "draw");
    /*
     * M1l.  The sweep runs in the state the rung above just PROVED accelerated
     * -- same context, same classifier verdict, same hook installed -- and then
     * the process ends.  Timing a state nobody judged would time software.
     */
    if (prof) {
        /* the two pixel arrays are free here: the profiling branch returns
           before the draw/cull pictures are ever grabbed into them */
        profile(runid, c1, pixDraw, pixCull);
        say(runid, "end");
        /*
         * M1t: THE WORDS THAT WENT, so a knob that claims to change nothing can
         * be checked on what it actually produced.  The sweep draws the same
         * triangles whatever the knob says, so the last OSRDN_TRI_LOG rows must
         * match word for word between two runs that differ only in a knob.
         * Counters cannot show this -- they agree while the contents differ.
         */
        sent(runid, "end");
        OSMesaDestroyContext(c1);
        return 0;
    }
    sent(runid, "draw");
    if (tex)
        texrows(runid);
    if (depth)
        zdump(runid);
    grab(runid, "draw", c1, pixDraw);

    /* 2. the same mode WITH culling: declined for TRI_SETUP, and the reason is
          not squeamishness -- with our function installed nothing would cull at
          all (docs/M1D_PLAN.md 3b, D12).  `triangles` must not grow here. */
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    scene(2, smooth, blend, tex, multi, depth);
    say(runid, "cull");
    grab(runid, "cull", c1, pixCull);
    glDisable(GL_CULL_FACE);

    /* 3. the surface goes away while our function may still be installed.
          Every triangle must then be delegated and none lost. */
    OSMesaPixelStore(OSMESA_ROW_LENGTH, W + 8);
    scene(2, smooth, blend, tex, multi, depth);
    say(runid, "unbound");
    OSMesaPixelStore(OSMESA_ROW_LENGTH, 0);

    OSMesaDestroyContext(c1);
    say(runid, "end");
    sent(runid, "end");

    dump(runid, "draw", pixDraw);
    dump(runid, "cull", pixCull);
    printf("RDNTRI run=%s step=done\n", runid);
    return 0;
}
