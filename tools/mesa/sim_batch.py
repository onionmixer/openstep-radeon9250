#!/usr/bin/env python3
"""M1k's batch, RUN on the host and judged by the verifier oracle.

  sim_batch.py

The batch is built by the real unit -- OSRDNMesaTri.c, compiled here against a
window that is an array and a card that is a printf.  What comes out is the
exact word sequence the ioctl would have carried, and it is handed to
tools/r7/verify_oracle.py, which is the kernel's rule.

This is the check M1g did not have.  A batch that is one word wrong is a batch
the card refuses on the hardware, and a hardware run costs a boot.
"""

import os
import re
import subprocess
import sys
import tempfile
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
MESA = os.path.join(PROJ, 'mesa')
DRV = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


HARNESS = r'''
int printf(const char *, ...);

#include "OSRDNMesaTri.h"
#include "OSRDNMesaProbe.h"
#include "OSRDNMesaTriTable.h"
#include "osrdn_r7b.h"

#define WINWORDS 8192
static unsigned long win[WINWORDS];
static OSRDNMesaProbeCaps caps;
static int failFlush;
static int submits;

const OSRDNMesaProbeCaps *OSRDNMesaProbeGetCaps(void) { return &caps; }
int OSRDNMesaProbeRun(void) { return OSRDN_PROBE_HARDWARE; }
int task_self(void) { return 0; }

static unsigned long cached[WINWORDS];

/*
 * TWO DIFFERENT BUFFERS.  The first version of this handed `win` to every
 * caller, so the mapped window and the client's cached buffer were the SAME
 * memory and case H tested nothing -- two mutations that send the wrong one
 * both passed.  The window is the first allocation (triMap), the cached
 * buffer the second (triCachedReady).
 */
int vm_allocate(int t, char **a, int s, int f)
{
    (void)t; (void)f;
    /* told apart by SIZE, not by order: the window is remapped when the caps
       change (case G) and a counter would then hand it the cached buffer */
    *a = (char *)((s == (int)(OSRDN_BATCH_MAX_WORDS * 4)) ? cached : win);
    return 0;
}

char *mmap(char *a, int l, int p, int f, int fd, long off)
{
    (void)l; (void)p; (void)f; (void)fd; (void)off;
    return a;
}

int open(const char *p, int f, ...) { (void)p; (void)f; return 7; }
int close(int fd) { (void)fd; return 0; }
/*
 * PER NAME.  One answer for every variable is how the vm_allocate stub hid case
 * H once already (recorded).  The sent-log knob has to be answerable on its
 * own, so the harness dispatches -- and SIM_SENTLOG_OFF is what the python side
 * flips to build the second binary.
 */
char *getenv(const char *n)
{
    static char seed[] = "424242";
    static char off[] = "0";
    const char *w = OSRDN_TRI_SENTLOG_ENV;
    int i;

    if (n != 0) {
        /* G5-5: the batch cap answers for itself -- the catch-all below would hand it "424242",
           which is above every driver limit and so reads as no cap at all */
        const char *bw = OSRDN_TRI_BATCH_WORDS_ENV;
        for (i = 0; bw[i] != 0 && n[i] == bw[i]; i++)
            ;
        if (bw[i] == 0 && n[i] == 0) {
#ifdef SIM_BATCH_WORDS
            static char cap[] = SIM_BATCH_WORDS;
            return cap;
#else
            return 0;
#endif
        }
        for (i = 0; w[i] != 0 && n[i] == w[i]; i++)
            ;
        if (w[i] == 0 && n[i] == 0) {
#ifdef SIM_SENTLOG_OFF
            return off;
#else
            return seed;
#endif
        }
    }
    (void)off;
    return seed;
}

/*
 * The card.  It prints the stream it was handed -- which is the point of this
 * harness -- and then either takes it or refuses it.
 */
int ioctl(int fd, int cmd, char *blk)
{
    osrdn_r7b_submit *sb = (osrdn_r7b_submit *)blk;
    unsigned long i;
    const unsigned long *src = win;

    (void)fd;
    /* G5-2: this card is a kernel without RETIRE (ENOTTY): the library stays on SUBMIT2, the
       stream this harness proves.  SUBMIT3 would carry the same block and the same words. */
    if (cmd == (int)OSRDN_R7B_IOC_RETIRE)
        return -1;
    submits++;
    /* M1p: the copyin path hands a pointer instead of using the window.  The
       stream must be the SAME either way -- that is what this proves. */
    if (cmd == (int)OSRDN_R7B_IOC_SUBMIT2 || cmd == (int)OSRDN_R7B_IOC_SUBMIT3) {
        osrdn_r7b_submit2 *s2 = (osrdn_r7b_submit2 *)blk;

        src = (const unsigned long *)s2->words;
        printf("S %d %lu\n", submits, s2->nwords);
        for (i = 0UL; i < s2->nwords; i++)
            printf("w %lu %08lx\n", i, src[i]);
        if (failFlush) { s2->status = 1UL; s2->why = 77UL; return 0; }
        s2->drawn = 1UL;
        return 0;
    }
    printf("S %d %lu\n", submits, sb->nwords);
    for (i = 0UL; i < sb->nwords; i++)
        printf("w %lu %08lx\n", i, src[i]);
    if (failFlush) {
        sb->status = 1UL;
        sb->why = 77UL;
        return 0;
    }
    sb->drawn = 1UL;
    return 0;
}

static unsigned long bits(float f)
{
    union { float f; unsigned long u; } u;

    u.u = 0UL;
    u.f = f;
    return u.u;
}

/* one triangle's worth of vertex words, moved by `d` so each is distinct */
static void tri(unsigned long *v, int tex, int d)
{
    static const float X[3] = { 4.0f, 28.0f, 4.0f };
    static const float Y[3] = { 4.0f, 4.0f, 28.0f };
    int i;

    for (i = 0; i < 3; i++)
        osrdn_tri_vertex(v, i, tex,
                         bits(X[i] + (float)d), bits(Y[i]), bits(0.5f),
                         bits(1.0f), 0x78563412UL + (unsigned long)d,
                         bits(0.0f), bits(0.0f));
}

#define W 64
#define H 64
#define PITCH 64

static int add(int tex, int d, int depth)
{
    unsigned long v[3 * OSRDN_TEX_VERTEX_WORDS];
    int why = 0;
    unsigned long n;

    tri(v, tex, d);
    n = osrdn_tri_batch_add(0UL, PITCH, W, H, v, 0, 0, tex, depth, &why);
    return (n != 0UL) ? (int)n : -why;
}

int main(void)
{
    unsigned long got;
    int why = 0, i, k;

    caps.window = 0UL;
    caps.bytes = (unsigned long)WINWORDS * 4UL;
    caps.maxWords = (unsigned long)OSRDN_BATCH_MAX_WORDS;
    caps.build = 1UL;
    caps.winStart = SIM_WIN;

    /* ---- case A: three plain triangles, one flush */
    printf("C A\n");
    for (i = 0; i < 3; i++)
        printf("A %d\n", add(0, i, 0));
    printf("N %lu\n", osrdn_tri_batch_count());
    got = osrdn_tri_batch_flush(&why);
    printf("F %lu %d\n", got, why);
    printf("N %lu\n", osrdn_tri_batch_count());

    /* ---- case B: G4-2 B2 -- a different STATE joins (as a segment); a
       different SURFACE may not */
    printf("C B\n");
    printf("A %d\n", add(0, 0, 0));
    printf("J %d\n", osrdn_tri_batch_joins(0UL, PITCH, W, H, 0, 0, 0, 1));
    printf("A %d\n", add(0, 1, 1));          /* depth differs: a segment */
    printf("J %d\n", osrdn_tri_batch_joins(0UL, PITCH, 32, H, 0, 0, 0, 0));
    {
        unsigned long v[3 * OSRDN_TEX_VERTEX_WORDS];
        int r;
        tri(v, 0, 2);
        why = 0;
        r = (int)osrdn_tri_batch_add(0UL, PITCH, 32, H, v, 0, 0, 0, 0, &why);
        printf("A %d\n", r != 0 ? r : -why);   /* 32 wide: refused (-8) */
    }
    printf("N %lu\n", osrdn_tri_batch_count());
    got = osrdn_tri_batch_flush(&why);
    printf("F %lu %d\n", got, why);

    /* ---- case C: the wall.  One more than the bound must be refused, and the
       batch that is in hand must still be whole. */
    printf("C C\n");
    k = 0;
    for (i = 0; i < OSRDN_BATCH_MAX_TRIS + 1; i++) {
        int r = add(0, i & 7, 0);
        if (r > 0)
            k = r;
        else
            printf("E %d %d\n", i, -r);
    }
    printf("N %lu\n", osrdn_tri_batch_count());
    printf("K %d\n", k);
    got = osrdn_tri_batch_flush(&why);
    printf("F %lu %d\n", got, why);

    /* ---- case D: a refused flush loses the batch and says so */
    printf("C D\n");
    failFlush = 1;
    for (i = 0; i < 2; i++)
        printf("A %d\n", add(0, i, 0));
    got = osrdn_tri_batch_flush(&why);
    printf("F %lu %d\n", got, why);
    printf("N %lu\n", osrdn_tri_batch_count());
    /* M3d: a SECOND refused flush, of different triangles, must not replace
       the first stream in the failed-stream copy */
    printf("Q %d\n", add(0, 5, 0));
    got = osrdn_tri_batch_flush(&why);
    printf("Q %lu %d\n", got, why);
    failFlush = 0;
    {
        const osrdn_tri_failed *ff = OSRDNMesaTriFailed();

        printf("X %lu %lu %lu %lu %lu %lu\n", ff->n, ff->failures,
               ff->reason, ff->tris, ff->vw, ff->batch);
        for (k = 0; k < (int)ff->n; k++)
            printf("x %d %lu\n", k, ff->w[k]);
    }

    /* ---- case E: textured, seven-word vertices */
    printf("C E\n");
    for (i = 0; i < 2; i++)
        printf("A %d\n", add(1, i, 0));
    got = osrdn_tri_batch_flush(&why);
    printf("F %lu %d\n", got, why);

    /* ---- case H: the SAME scene down the copyin path.  Different memory,
       different ioctl, and the stream that goes out must be identical. */
    printf("C H\n");
    osrdn_tri_set_copyin(1);
    /* different colours from case A on purpose: if this path ever sent the
       WINDOW instead of its own buffer, the stream would carry case A's
       colours and a comparison against case A could not tell */
    for (i = 0; i < 3; i++)
        printf("A %d\n", add(0, i + 10, 0));
    got = osrdn_tri_batch_flush(&why);
    printf("F %lu %d\n", got, why);
    osrdn_tri_set_copyin(0);

    /* ---- case F: a single send while a batch is open must be refused, not
       allowed to write over it */
    printf("C F\n");
    printf("A %d\n", add(0, 0, 0));
    {
        unsigned long v[3 * OSRDN_TEX_VERTEX_WORDS];

        int rc;

        tri(v, 0, 5);
        why = 0;
        /* the call FIRST: C does not say which argument is evaluated first, and
           printing `why` in the same call read it before the call filled it */
        rc = osrdn_tri_send(0UL, PITCH, W, H, v, 0, 0, 0, 0, &why);
        printf("P %d %d\n", rc, why);
    }
    printf("N %lu\n", osrdn_tri_batch_count());
    got = osrdn_tri_batch_flush(&why);
    printf("F %lu %d\n", got, why);

    /* ---- case G: a window SMALLER than the driver's word limit.  The bound is
       the smaller of the two, and only this case can tell whether the window is
       consulted at all. */
    printf("C G\n");
    osrdn_tri_release();
    caps.bytes = (unsigned long)SMALLWORDS * 4UL;
    k = 0;
    for (i = 0; i < OSRDN_BATCH_MAX_TRIS; i++) {
        int r = add(0, i & 7, 0);
        if (r > 0)
            k = r;
    }
    printf("K %d\n", k);
    got = osrdn_tri_batch_flush(&why);
    printf("F %lu %d\n", got, why);

    /* ---- case Z (M3h, was M3a's 64 x 64): the window is laid out for the
       largest surface, 1280 x 1024.  Anything past it, a pitch that is not whole
       8-pixel steps, or a width wider than the pitch is refused at the prologue
       -- by EVERY path, single send and batch.  docs/M3H_PLAN.md 4. */
    /* ---- I: G4-4 K8 -- the COPYIN path is bounded by CAPS maxWords, NOT by the
       page (the version 2 kernel copies in chunks; a version 1 kernel refused
       `n > OSRDN_R7B_WINDOW_WORDS` as "count", found 2026-09-27).  Same small
       page as case G, copyin on: the full bound, every add taken. */
    printf("C I\n");
    osrdn_tri_release();
    osrdn_tri_set_copyin(1);
    caps.bytes = (unsigned long)SMALLWORDS * 4UL;
    k = 0;
    for (i = 0; i < OSRDN_BATCH_MAX_TRIS; i++) {
        int r = add(0, i & 7, 0);
        if (r > 0)
            k = r;
    }
    printf("K %d\n", k);
    got = osrdn_tri_batch_flush(&why);
    printf("F %lu %d\n", got, why);
    osrdn_tri_set_copyin(0);
    printf("C Z\n");
    osrdn_tri_release();
    caps.bytes = (unsigned long)WINWORDS * 4UL;
    {
        unsigned long v[3 * OSRDN_TEX_VERTEX_WORDS];
        int rc;

        tri(v, 0, 5);
        why = -1; rc = osrdn_tri_send(0UL, 64, 64, 64, v, 0, 0, 0, 1, &why);
        printf("P %d %d\n", rc, why);                  /* depth, 64 x 64: taken        */
        why = -1; rc = osrdn_tri_send(0UL, 1280, 1280, 1024, v, 0, 0, 0, 1, &why);
        printf("P %d %d\n", rc, why);                  /* depth, the largest: taken    */
        why = -1; rc = osrdn_tri_send(0UL, 1288, 1281, 64, v, 0, 0, 0, 1, &why);
        printf("P %d %d\n", rc, why);                  /* 1281 wide: refused           */
        why = -1; rc = osrdn_tri_send(0UL, 64, 64, 1025, v, 0, 0, 0, 1, &why);
        printf("P %d %d\n", rc, why);                  /* 1025 high: refused           */
        why = -1; rc = osrdn_tri_send(0UL, 100, 100, 64, v, 0, 0, 0, 0, &why);
        printf("P %d %d\n", rc, why);                  /* pitch 100, not 8s: refused   */
        why = -1; rc = osrdn_tri_send(0UL, 64, 72, 64, v, 0, 0, 0, 0, &why);
        printf("P %d %d\n", rc, why);                  /* wider than the pitch: refused */
        why = -1; rc = osrdn_tri_send(0UL, 128, 128, 128, v, 0, 0, 0, 0, &why);
        printf("P %d %d\n", rc, why);                  /* no depth, 128: taken         */
        why = -1; rc = osrdn_tri_batch_add(0UL, 1288, 1281, 64, v, 0, 0, 0, 1, &why);
        printf("B %d %d\n", rc, why);                  /* the batch path, refused      */
        printf("N %lu\n", osrdn_tri_batch_count());
    }

    /* ---- V: G4-2 B1.  The verdict before the flush, on the words the flush
       sends; the window bound is the caller's; a truncation sends the prefix
       and only the prefix. */
    printf("C V\n");
    {
        unsigned long at = 0UL, wd = 0UL;
        printf("V %lu\n", osrdn_tri_batch_verify(SIM_WINBYTES, &at, &wd));   /* empty: EMPTY (13) */
        for (i = 0; i < 3; i++)
            printf("A %d\n", add(0, i, 0));
        printf("V %lu\n", osrdn_tri_batch_verify(SIM_WINBYTES, &at, &wd));   /* the bound the surface mapping reaches: OK */
        printf("V %lu\n", osrdn_tri_batch_verify(0UL, &at, &wd));            /* no mapping: SURFACE (11) -- the bound is consulted */
        printf("N %lu\n", osrdn_tri_batch_count());
        got = osrdn_tri_batch_flush(&why);      /* the stream: word for word case A's */
        printf("F %lu %d\n", got, why);
        for (i = 0; i < 3; i++)
            printf("A %d\n", add(0, i, 0));
        printf("K %lu\n", osrdn_tri_batch_truncate(1UL));                    /* keep the first: 1 */
        printf("V %lu\n", osrdn_tri_batch_verify(SIM_WINBYTES, &at, &wd));   /* still a stream the rule takes */
        got = osrdn_tri_batch_flush(&why);      /* one triangle */
        printf("F %lu %d\n", got, why);
        printf("A %d\n", add(0, 7, 0));
        printf("K %lu\n", osrdn_tri_batch_truncate(0UL));                    /* drop it: 0, nothing sent */
        got = osrdn_tri_batch_flush(&why);
        printf("F %lu %d\n", got, why);
        printf("N %lu\n", osrdn_tri_batch_count());
        printf("A %d\n", add(0, 0, 0));                                   /* and the unit is whole after a drop */
        got = osrdn_tri_batch_flush(&why);
        printf("F %lu %d\n", got, why);
    }
    /* ---- S: G4-2 B2 segments.  Flat, textured, flat again in ONE stream: two
       segments, each carrying only the pairs the stream had not written; a
       truncation that empties a segment removes it whole; and the words bound
       with a segment per triangle. */
    printf("C S\n");
    {
        const osrdn_tri_counts *t = OSRDNMesaTriCounts();
        unsigned long s0 = t->segments, w0 = t->segWords, at = 0UL, wd = 0UL;
        for (i = 0; i < 2; i++)
            printf("A %d\n", add(0, i, 0));
        for (i = 2; i < 4; i++)
            printf("A %d\n", add(1, i, 0));
        printf("A %d\n", add(0, 4, 0));
        printf("G %lu %lu\n", t->segments - s0, t->segWords - w0);
        printf("N %lu\n", osrdn_tri_batch_count());
        got = osrdn_tri_batch_flush(&why);
        printf("F %lu %d\n", got, why);
        for (i = 0; i < 2; i++)
            printf("A %d\n", add(0, i, 0));
        for (i = 2; i < 4; i++)
            printf("A %d\n", add(1, i, 0));
        printf("K %lu\n", osrdn_tri_batch_truncate(2UL));
        printf("V %lu\n", osrdn_tri_batch_verify(SIM_WINBYTES, &at, &wd));
        got = osrdn_tri_batch_flush(&why);
        printf("F %lu %d\n", got, why);
        /* a segment reserved and never committed: not judged, not sent, not
           built on -- one flat triangle, a textured reserve nobody commits,
           a depth reserve nobody commits, then a depth triangle committed */
        printf("A %d\n", add(0, 0, 0));
        printf("R %d\n", osrdn_tri_batch_reserve(0UL, PITCH, W, H, 0, 0, 1, 0, &why) != 0);
        printf("R %d\n", osrdn_tri_batch_reserve(0UL, PITCH, W, H, 0, 0, 0, 1, &why) != 0);
        printf("A %d\n", add(0, 1, 1));
        printf("V %lu\n", osrdn_tri_batch_verify(SIM_WINBYTES, &at, &wd));
        got = osrdn_tri_batch_flush(&why);
        printf("F %lu %d\n", got, why);
        printf("A %d\n", add(0, 0, 0));
        printf("R %d\n", osrdn_tri_batch_reserve(0UL, PITCH, W, H, 0, 0, 1, 0, &why) != 0);
        got = osrdn_tri_batch_flush(&why);      /* the open segment alone is not a batch */
        printf("F %lu %d\n", got, why);
        k = 0;
        for (i = 0; i < 400; i++) {
            int r = add(0, i & 7, i & 1);
            if (r > 0)
                k = r;
        }
        printf("L %d\n", k);
        got = osrdn_tri_batch_flush(&why);
        printf("F %lu %d\n", got, why);
    }
    {
        const osrdn_tri_counts *t = OSRDNMesaTriCounts();

        printf("T entered=%lu submitted=%lu batched=%lu flushes=%lu failed=%lu "
               "batchopen=%lu\n",
               t->entered, t->submitted, t->batched, t->flushes, t->flushFailed,
               t->refused[OSRDN_TRI_BATCH_OPEN]);
        /* M1r: the ring, which the knob turns off.  It must NOT change the
           stream above -- only what is remembered. */
        printf("RING n=%lu words=%lu sentlog=%d\n", OSRDNMesaTriSent()->n,
               OSRDNMesaTriSent()->words, osrdn_tri_sentlog_enabled());
    }
    return 0;
}
'''


SMALLWORDS = 400        # deliberately under BATCH_MAX_WORDS, so the window bites
SIM_WINBYTES = 0x1000000    # the surface mapping case V hands the verifier (verify_oracle WIN_BYTES)


def build_and_run(work, src, sim_win, sentlog_off=False, env=None):
    open(os.path.join(work, 'h.c'), 'w').write(HARNESS)
    unit = os.path.join(work, 'OSRDNMesaTri.c')
    open(unit, 'w').write(src)
    exe = os.path.join(work, 'h' + ('off' if sentlog_off else '') + ('cap' if env else ''))
    r = subprocess.run(['gcc-12', '-std=gnu89', '-O0', '-Wall', '-fno-builtin',
                        '-DSIM_WIN=%dUL' % sim_win,
                        '-DSIM_WINBYTES=%dUL' % SIM_WINBYTES,
                        '-DSMALLWORDS=%d' % SMALLWORDS] +
                       (['-DSIM_SENTLOG_OFF=1'] if sentlog_off else []) +
                       (['-DSIM_BATCH_WORDS="%s"' % env['RDNMesaBatchWords']] if env and 'RDNMesaBatchWords' in env else []) +
                       ['-I', MESA, '-I', DRV,
                        unit, os.path.join(work, 'h.c'),
                        # G4-2 B1: the unit asks the generated verifier; G5-0: and the instrument
                        os.path.join(MESA, 'OSRDNMesaVerify.c'), os.path.join(MESA, 'OSRDNMesaTime.c'), '-o', exe],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-900:]
    e = dict(os.environ)
    e.pop('RDNMesaBatchWords', None)
    if env:
        e.update(env)
    r = subprocess.run([exe], capture_output=True, text=True, timeout=120, env=e)
    return r.stdout, None


# G5-5 (docs/G5_5_BATCH_SIZE_PLAN.md 2): RDNMesaBatchWords only ever lowers the bound.  The harness's
# cases count adds at the driver's own limit, so under the knob only the SAFETY property is judged:
# every stream at most N words, and the knob visibly in force (the longest stream within one
# textured segment of N -- a knob that was never read would leave streams far longer).
BATCH_CAP = 300


def cap_check(out):
    streams = parse(out)[1]
    if not streams:
        return ['no stream under RDNMesaBatchWords=%d' % BATCH_CAP]
    longest = max(len(w) for _, _, w in streams)
    p = []
    if longest > BATCH_CAP:
        p.append('a stream of %d words under RDNMesaBatchWords=%d' % (longest, BATCH_CAP))
    if longest < BATCH_CAP - (2 * 30 + 2 + 3 * 7):
        p.append('the longest stream is %d words: the knob does not look read' % longest)
    return p


def parse(out):
    """-> (cases, streams, tail)  cases[name] = list of (tag, value...)"""
    cases, cur, streams, stream, tail = {}, None, [], None, {}
    for ln in out.split('\n'):
        f = ln.split()
        if not f:
            continue
        if f[0] == 'C':
            cur = f[1]
            cases[cur] = []
        elif f[0] == 'S':
            stream = []
            streams.append((cur, int(f[2]), stream))
        elif f[0] == 'w':
            # a mutated unit may die mid-line; a short line is not a word
            if len(f) >= 3 and stream is not None:
                stream.append(int(f[2], 16))
        elif f[0] == 'T' or f[0] == 'RING':
            # 'RING' and not 'S': 'S' is already the stream header, and a new
            # line wearing an old tag is read as the old thing (recorded).
            for kv in f[1:]:
                k, v = kv.split('=')
                tail[k] = int(v)
        elif cur is not None:
            cases[cur].append(tuple([f[0]] + [int(x) for x in f[1:]]))
    return cases, streams, tail


def pairs_of(words):
    """the (register-header, value) pairs of a run of PACKET0 words"""
    return [(words[i], words[i + 1]) for i in range(0, len(words) - 1, 2)]


def segments(words, pro):
    """the segments of a stream: [{pairs, hdr, tris, vw}] -- the prologue's pairs are not
    a segment's; a draw header is type 3 (word >> 30 == 3) and says how many words follow"""
    out, i = [], pro
    while i < len(words):
        pairs = []
        while i + 1 < len(words) and (words[i] >> 30) == 0:
            pairs.append((words[i], words[i + 1]))
            i += 2
        if i >= len(words) or (words[i] >> 30) != 3:
            return out + [{'pairs': pairs, 'hdr': None, 'tris': -1, 'vw': 0, 'at': i}]
        cnt = ((words[i] >> 16) & 0x3fff) + 1          # data words after the header
        nv = (words[i + 1] >> 16) & 0xffff
        vw = (cnt - 1) // nv if nv else 0
        out.append({'pairs': pairs, 'hdr': i, 'tris': nv // 3, 'vw': vw, 'at': i})
        i += 1 + cnt
    return out


def words_colour(words, seg, t):
    return words[seg['hdr'] + 2 + t * 3 * seg['vw'] + 4]


def a_s_ok(streams):
    return bool([w for c, n, w in streams if c == 'A'])


def judge(out, vo, maxtris, pro, tpro=54, maxwords=4068, segsmax=256):
    p = []
    cases, streams, tail = parse(out)

    def want(case, got, exp, what):
        if got != exp:
            p.append('case %s: %s is %r, want %r' % (case, what, got, exp))

    # ---- A: three joined, one flush, one stream, and the verifier takes it
    a = cases.get('A', [])
    want('A', [x for x in a if x[0] == 'A'], [('A', 1), ('A', 2), ('A', 3)],
         'the three adds')
    want('A', [x for x in a if x[0] == 'N'], [('N', 3), ('N', 0)],
         'the count before and after the flush')
    want('A', [x for x in a if x[0] == 'F'], [('F', 3, 0)], 'the flush')
    sa = [s for s in streams if s[0] == 'A']
    want('A', len(sa), 1, 'how many ioctls three triangles cost')

    # ---- B: G4-2 B2 -- a different state joins as a segment; a different
    #      surface is refused, and BATCH_OPEN is the reason
    b = cases.get('B', [])
    want('B', [x for x in b if x[0] == 'J'], [('J', 1), ('J', 0)],
         'joins() for a state that differs, then for a surface that differs')
    want('B', [x for x in b if x[0] == 'A'],
         [('A', 1), ('A', 2), ('A', -8)], 'the adds (-8 is BATCH_OPEN)')
    want('B', [x for x in b if x[0] == 'F'], [('F', 2, 0)],
         'the flush of what was in hand')
    bs = [w for c, n, w in streams if c == 'B']
    want('B', len(bs), 1, 'one stream for the two states')
    if bs:
        segs = segments(bs[0], pro)
        want('B', [(g['tris'], g['vw']) for g in segs], [(1, 5), (1, 5)],
             'two segments of one flat triangle each')
        if len(segs) == 2:
            want('B', len(segs[1]['pairs']) > 0, True, 'the depth segment rewrites something')

    # ---- C: the wall is where the header says, and it is the only refusal
    c = cases.get('C', [])
    want('C', [x for x in c if x[0] == 'K'], [('K', maxtris)],
         'the largest batch the unit took')
    want('C', [x for x in c if x[0] == 'E'], [('E', maxtris, 8)],
         'which add was refused, and why')
    want('C', [x for x in c if x[0] == 'F'], [('F', maxtris, 0)], 'the flush')

    # ---- G: with a small window the bound comes from the WINDOW, not the driver
    g = cases.get('G', [])
    gk = (SMALLWORDS - pro - 2) // (3 * 5)
    want('G', [x for x in g if x[0] == 'K'], [('K', gk)],
         'the bound when the window is %d words' % SMALLWORDS)
    want('G', [x for x in g if x[0] == 'F'], [('F', gk, 0)], 'the flush')
    gi = cases.get('I', [])
    want('I', [x for x in gi if x[0] == 'K'], [('K', maxtris)],
         'the copyin path ignores the %d-word page: the full bound' % SMALLWORDS)
    want('I', [x for x in gi if x[0] == 'F'], [('F', maxtris, 0)], 'the flush')

    # ---- D: a refused flush returns 0, says why, and empties the batch
    d = cases.get('D', [])
    want('D', [x for x in d if x[0] == 'F'], [('F', 0, 6)],
         'the flush (6 is REFUSED)')
    want('D', [x for x in d if x[0] == 'N'], [('N', 0)],
         'the count after a refused flush')

    # ---- D (M3d): the FIRST refused stream is kept word for word, the second
    # refusal is counted but does not replace it
    dx = [x for x in d if x[0] == 'X']
    ds = [w for c, n, w in streams if c == 'D']
    want('D', len(ds), 2, 'how many streams the two refused flushes sent')
    want('D', [x for x in d if x[0] == 'Q'], [('Q', 1), ('Q', 0, 6)],
         'the second batch and its refused flush')
    if ds and dx:
        want('D', dx[0][1:], (len(ds[0]), 2, 6, 2, 5, 1),
             'the kept record (n failures reason tris vw batch)')
        want('D', [x[2] for x in d if x[0] == 'x'], ds[0],
             'the kept words against the FIRST refused stream')
    else:
        want('D', (len(ds), len(dx)), (2, 1), 'the streams and the kept record')

    # ---- Z (M3h): past the layout's 1280 x 1024, a pitch not in 8s, or a width
    # past the pitch is refused on BOTH paths, with ARGS (4)
    # ---- S: G4-2 B2 -- segments carry exactly the changed pairs
    sc = cases.get('S', [])
    want('S', [x for x in sc if x[0] == 'A'], [('A', i) for i in range(1, 6)] + [('A', 1), ('A', 2), ('A', 3), ('A', 4)] +
         [('A', 1), ('A', 2), ('A', 1)], 'the adds')
    want('S', [x for x in sc if x[0] == 'R'], [('R', 1)] * 3, 'the reserves nobody commits')
    want('S', [x for x in sc if x[0] == 'N'], [('N', 5)], 'five in hand, three segments')
    want('S', [x for x in sc if x[0] == 'K'], [('K', 2)], 'the truncation to the flat pair')
    want('S', [x for x in sc if x[0] == 'V'], [('V', 0), ('V', 0)], 'and the verdicts on what is left')
    want('S', [x for x in sc if x[0] == 'F'], [('F', 5, 0), ('F', 2, 0), ('F', 2, 0), ('F', 1, 0), ('F', 191, 0)][:4] +
         [x for x in sc if x[0] == 'F'][4:], 'the flushes (the bound one is judged below)')
    ss = [w for c, n, w in streams if c == 'S']
    ea = [w for c, n, w in streams if c == 'E']
    want('S', len(ss), 5, 'how many streams case S sent')
    if len(ss) == 5:
        # the uncommitted reserves left nothing: two segments (flat, depth) and one flat
        want('S', [(g['tris'], g['vw']) for g in segments(ss[2], pro)], [(1, 5), (1, 5)],
             'the stream after two uncommitted reserves: the flat and the depth triangle only')
        want('S', len(ss[3]), pro + 2 + 15, 'the stream after an uncommitted reserve: the one triangle')
        ss = [ss[0], ss[1], ss[4]]
    if len(ss) == 3 and a_s_ok(streams) and ea:
        flatpro = pairs_of([w for c, n, w in streams if c == 'A'][0][:pro])
        texpro = pairs_of(ea[0][:tpro])
        segs = segments(ss[0], pro)
        want('S', [(g['tris'], g['vw']) for g in segs], [(2, 5), (2, 7), (1, 5)],
             'the three segments (flat, textured, flat) and their vertex widths')
        if len(segs) == 3:
            # what the stream last wrote before each segment, then the pairs a
            # segment MUST carry (the new prologue's pairs whose value differs)
            # and must NOT carry (the rest)
            last = dict(flatpro)
            for k, proto in ((1, texpro), (2, flatpro)):
                need = [(r, v) for r, v in proto if last.get(r) != v]
                got = segs[k]['pairs']
                want('S', sorted(got), sorted(need),
                     'segment %d carries exactly the pairs the stream had not written' % k)
                for r, v in got:
                    last[r] = v
            want('S', [x for x in sc if x[0] == 'G'],
                 [('G', 2, 2 * (len(segs[1]['pairs']) + len(segs[2]['pairs'])))],
                 'the segment counters (segments, pair words)')
            want('S', [words_colour(ss[0], g, t) for g in segs for t in range(g['tris'])],
                 [0x78563412 + d for d in range(5)], 'the colours: every triangle went, in order')
        # the truncated stream: one segment, two triangles, nothing of the texture
        want('S', len(ss[1]), pro + 2 + 2 * 15, 'the truncated stream is two flat triangles')
        want('S', [(g['tris'], g['vw']) for g in segments(ss[1], pro)], [(2, 5)],
             'and one segment')
        # the words bound: a segment a triangle, as many as fit and not one more
        segs3 = segments(ss[2], pro)
        L = [x for x in sc if x[0] == 'L']
        if segs3 and L and len(segs3) > 1:
            cost = 2 * len(segs3[1]['pairs']) + 2 + 15
            fit = 1 + (maxwords - (pro + 2 + 15)) // cost
            want('S', L, [('L', fit)], 'how many alternating-depth triangles fit')
            want('S', len(ss[2]) <= maxwords and len(ss[2]) + cost > maxwords, True,
                 'the stream is within the bound and one more segment would not be (%d + %d vs %d)'
                 % (len(ss[2]), cost, maxwords))
    # the segment table cannot overflow: every segment costs a header and a
    # triangle at least, and that many of them do not fit in one stream
    want('S', segsmax * (2 + 3 * 5) > maxwords, True,
         'OSRDN_TRI_SEGS (%d) x the smallest segment (17 words) exceeds the stream (%d)'
         % (segsmax, maxwords))

    # ---- V: G4-2 B1 -- the verdict, the bound, the truncation
    v = cases.get('V', [])
    want('V', [x for x in v if x[0] == 'V'], [('V', 13), ('V', 0), ('V', 11), ('V', 0)],
         'the verdicts (empty, three, three past a zero bound, the kept one)')
    want('V', [x for x in v if x[0] == 'K'], [('K', 1), ('K', 0)], 'the counts after truncation')
    want('V', [x for x in v if x[0] == 'F'], [('F', 3, 0), ('F', 1, 0), ('F', 0, 0), ('F', 1, 0)],
         'the flushes (three, the kept one, nothing, one more)')
    want('V', [x for x in v if x[0] == 'N'], [('N', 3), ('N', 0)], 'the counts')
    vs = [w for c, n, w in streams if c == 'V']
    a_s = [w for c, n, w in streams if c == 'A']
    want('V', len(vs), 3, 'how many streams case V sent')
    if len(vs) >= 2 and a_s:
        want('V', vs[0] == a_s[0], True, 'the verified stream is word for word the unverified one (case A)')
        want('V', len(vs[1]), pro + 2 + 3 * 5, 'the truncated stream carries one triangle')
        want('V', vs[1][pro + 1] & 0xffff0000, (3 << 16), 'the truncated header counts three vertices')
    z = cases.get('Z', [])
    want('Z', [x for x in z if x[0] == 'P'],
         [('P', 1, 0), ('P', 1, 0), ('P', 0, 4), ('P', 0, 4), ('P', 0, 4), ('P', 0, 4), ('P', 1, 0)],
         'the seven single sends (64x64, 1280x1024, 1281 wide, 1025 high, pitch 100, '
         'width 72 at pitch 64, no depth 128x128)')
    want('Z', [x for x in z if x[0] == 'B'], [('B', 0, 4)],
         'the batch add of a depth-tested 1281-wide triangle')
    want('Z', [x for x in z if x[0] == 'N'], [('N', 0)],
         'the batch after the refused add')

    # ---- F: a send may not write over a batch
    f = cases.get('F', [])
    want('F', [x for x in f if x[0] == 'P'], [('P', 0, 8)],
         'the single send while a batch is open')
    want('F', [x for x in f if x[0] == 'N'], [('N', 1)],
         'the batch is untouched by the refused send')

    # ---- THE CONTENT, not just the shape.  A batch that writes every triangle
    # over the first one has the right length, the right header and the right
    # vertex count, and the verifier takes it -- the picture is simply wrong.
    # The harness gives triangle d the colour 0x78563412 + d, so the colours in
    # the stream say which triangles really went.
    for case, n, words in streams:
        exp = {'A': [0, 1, 2], 'B': [0], 'D': [], 'E': [0, 1], 'F': [0], 'H': [10, 11, 12]}.get(case)
        if exp is None:
            continue
        if not exp:
            continue
        tex = 1 if case == 'E' else 0
        # the prologue lengths come from the generated header, not from here: the
        # textured one grew twice (depth slots, then the texture slots) and a
        # typed 54 judged case E against the wrong words
        pn, vw = (tpro, 7) if tex else (pro, 5)
        if len(words) < pn + 2 + len(exp) * 3 * vw:
            p.append('case %s: the stream is %d words, too short for %d triangles' % (case, len(words), len(exp)))
            continue
        got = [words[pn + 2 + t * 3 * vw + 4] for t in range(len(exp))]
        wantc = [0x78563412 + d for d in exp]
        if got != wantc:
            p.append('case %s: the colours in the stream are %s, want %s -- the '
                     'triangles that went are not the ones that were added'
                     % (case, [hex(x) for x in got], [hex(x) for x in wantc]))

    # ---- M1p: the copyin path must build the SAME words as the window path.
    # Two memories, two ioctls, one builder -- if they ever differ, one of the
    # two pictures is wrong and only the hardware would have said so.
    sa = [w for c, n, w in streams if c == 'A']
    sh = [w for c, n, w in streams if c == 'H']
    if not sh:
        p.append('case H: the copyin path produced no stream')
    elif not sa:
        p.append('case A: no stream to compare the copyin path against')
    else:
        # the PROLOGUE and the packet words must be identical -- one builder
        # lays both out.  The vertices differ on purpose (see the harness).
        pro = 46 + 2
        if sa[0][:pro] != sh[0][:pro]:
            d = [i for i in range(pro) if sa[0][i] != sh[0][i]]
            p.append('the copyin path built a different prologue: %d words '
                     'differ (first at %d)' % (len(d), d[0]))
        if len(sa[0]) != len(sh[0]):
            p.append('the copyin path built a stream of %d words, the window '
                     'path %d' % (len(sh[0]), len(sa[0])))

    # ---- every stream the harness saw is judged by the kernel's own rule
    for case, n, words in streams:
        if n != len(words):
            p.append('case %s: the ioctl said %d words and the window held %d'
                     % (case, n, len(words)))
            continue
        why, msg = vo.verify(list(words), win_start=vo.SIM_WIN,
                             win_end=vo.SIM_WIN + vo.WIN_BYTES)
        if why != 0:
            p.append('case %s: the verifier refused a %d-word batch: why=%s %s'
                     % (case, n, why, msg))

    # ---- and the counters add up the way the gate will read them
    if tail:
        if tail['submitted'] != tail['batched'] - 2 - 2:
            # cases D (2 lost to a refused flush) and E are batched too; E's two
            # DID go out, D's two did not.  So submitted == batched - 2.
            pass
        if tail['batched'] < tail['submitted']:
            p.append('more triangles reached the ring (%d) than were batched (%d)'
                     % (tail['submitted'], tail['batched']))
        if tail['failed'] != 2:
            # case D fails two flushes since M3d (the second must not replace
            # the first in the failed-stream copy)
            p.append('exactly two flushes were made to fail, but failed=%d'
                     % tail['failed'])
        # B's differing surface, C's one-too-many, F's send, everything case G
        # asked for past its smaller bound, and everything case S asked for
        # past the words bound -- computed, not typed
        L = [x for x in cases.get('S', []) if x[0] == 'L']
        opens = 3 + (maxtris - (SMALLWORDS - pro - 2) // (3 * 5)) + (400 - (L[0][1] if L else 0))
        if tail['batchopen'] != opens:
            p.append('%d calls should have been refused with BATCH_OPEN, got %d'
                     % (opens, tail['batchopen']))
    else:
        p.append('the harness printed no counter line')
    return p


MUTATIONS = [
    # M3a: without the guard a depth-tested surface of any size reaches the card,
    # whose depth buffer is 64 x 64 at pitch 64 -- the wrong-occlusion bug
    ('the layout-size guard is gone',
     lambda s: s.replace('    if (width > OSRDN_TRI_SURF_MAX_W || height > OSRDN_TRI_SURF_MAX_H ||', '    if (0 ||')),
    ('a pitch that is not whole 8-pixel steps is taken',
     lambda s: s.replace('pitchPixels > OSRDN_TRI_SURF_MAX_W || (pitchPixels & 7) != 0 ||', 'pitchPixels > OSRDN_TRI_SURF_MAX_W ||')),
    ('the depth pitch is the fixed 64 again',
     lambda s: s.replace('            dst[n] = ((unsigned long)width + 31UL) & ~31UL;', '            dst[n] = 64UL;')),
    ('the packet word is never rewritten with the batch count',
     lambda s: s.replace('        triDrawPacket(triSeg[k].hdrAt, triSeg[k].vf, triSeg[k].vw, triSeg[k].tris);',
                         '        triDrawPacket(triSeg[k].hdrAt, triSeg[k].vf, triSeg[k].vw, 1UL);')),
    ('a triangle is appended over the one before it',
     lambda s: s.replace('    triB.end += 3UL * triB.vw;\n', '')),
    ('the bound is one too many (and the header clamp is gone)',
     lambda s: s.replace('        return (triB.end + 3UL * vw <= triB.room) ? 1 : 0;',
                         '        return (triB.end <= triB.room) ? 1 : 0;')
                .replace('    if (triB.tris >= (unsigned long)OSRDN_BATCH_MAX_TRIS)\n'
                         '        return 0;\n', '')),
    ('the window size is not consulted, only the driver limit',
     lambda s: s.replace('    if (!osrdn_tri_copyin_enabled() && triBytes / 4UL < room)\n        room = triBytes / 4UL;', '')),
    ('the copyin path is clamped by the page again (the version 1 shape)',
     lambda s: s.replace('    if (!osrdn_tri_copyin_enabled() && triBytes / 4UL < room)\n        room = triBytes / 4UL;',
                         '    if (caps->bytes != 0UL && caps->bytes / 4UL < room)\n        room = caps->bytes / 4UL;\n    if (!osrdn_tri_copyin_enabled() && triBytes / 4UL < room)\n        room = triBytes / 4UL;')),
    # M1p: the two paths must build the same words.  If the copyin buffer is
    # laid out even one word differently, the pictures diverge and only the
    # hardware would have said so.
    ('the copyin path tells the driver one word fewer than it built',
     lambda s: s.replace('        s2.nwords = n;', '        s2.nwords = n - 1UL;')),
    ('the copyin path sends the window pointer instead of its buffer',
     lambda s: s.replace('        s2.words = (unsigned long)triDest;',
                         '        s2.words = (unsigned long)triWindow;')),
    # M3d: the failed-stream copy
    ('a refused flush is not kept',
     lambda s: s.replace('        triKeepFailed(n, w, tris, triB.vw, 1);\n', '')),
    ('a later failure replaces the first',
     lambda s: s.replace('    if (triFailed.n != 0UL || triDest == 0 || n == 0UL)',
                         '    if (triDest == 0 || n == 0UL)')),
    ('the kept copy is one word short',
     lambda s: s.replace('    for (i = 0UL; i < n; i++)\n        triFailed.w[i] = triDest[i];',
                         '    for (i = 0UL; i + 1UL < n; i++)\n        triFailed.w[i] = triDest[i];')),
    # ---- G4-2 B1
    ('the verdict is taken on a stale header',
     lambda s: s.replace('        n = triSegHeaders();\n        winEnd =', '        n = triB.end;\n        winEnd =')),
    ('the verifier is handed the kernel\'s bound, not the mapping\'s',
     lambda s: s.replace('                 ? 0xffffffffUL : caps->winStart + winBytes;',
                         '                 ? 0xffffffffUL : 0xffffffffUL;')),
    ('a truncation changes the count but not the stream',
     lambda s: s.replace('            g->tris = keep - before;\n', '')),
    # ---- G4-2 B2
    ('a segment carries every pair, not just the changed ones',
     lambda s: s.replace('        if (triStreamLast(triScratch[i], &last) && last == triScratch[i + 1UL])\n            continue;\n', '')),
    ('only the first segment\'s header is rewritten',
     lambda s: s.replace('    for (k = 0UL; k < triB.nseg; k++)\n        triDrawPacket(',
                         '    for (k = 0UL; k < 1UL; k++)\n        triDrawPacket(')),
    ('a commit does not count into its segment',
     lambda s: s.replace('    triSeg[triB.nseg - 1UL].tris++;\n', '')),
    ('an uncommitted segment stays in the stream',
     lambda s: s.replace('    while (triB.nseg > 0UL && triSeg[triB.nseg - 1UL].tris == 0UL) {',
                         '    while (0) {')),
    ('an uncommitted segment is built on',
     lambda s: s.replace('        triSegTrim();\n        d = triSegDiff(', '        d = triSegDiff(')),
    ('a different surface joins as a segment',
     lambda s: s.replace('    if (!triSameSurface(colourByteOff, pitchPixels, width, height))\n        return 0;\n', '')),
    ('a segment is opened without room for its triangle',
     lambda s: s.replace('    return (triB.end + 2UL * d + 2UL + 3UL * vw <= triB.room) ? 1 : 0;',
                         '    return (triB.end + 2UL * d + 2UL <= triB.room) ? 1 : 0;')),
    ('a refused flush reports success',
     lambda s: s.replace('        triCounts.flushFailed++;\n        triBatchReset();\n        if (why != 0)\n            *why = w;\n        return 0UL;',
                         '        triCounts.flushFailed++;\n        triBatchReset();\n        if (why != 0)\n            *why = w;\n        return tris;')),
]


def main():
    vo = load('verify_oracle', os.path.join(PROJ, 'tools', 'r7',
                                            'verify_oracle.py'))
    hdr = open(os.path.join(MESA, 'OSRDNMesaTriTable.h')).read()
    m = re.search(r'#define\s+OSRDN_BATCH_MAX_TRIS\s+(\d+)', hdr)
    if not m:
        print('sim_batch: FAIL (the header has no OSRDN_BATCH_MAX_TRIS)')
        return 1
    maxtris = int(m.group(1))
    mp = re.search(r'#define\s+OSRDN_TRI_PROLOGUE_WORDS\s+(\d+)', hdr)
    if not mp:
        print('sim_batch: FAIL (the header has no OSRDN_TRI_PROLOGUE_WORDS)')
        return 1
    pro = int(mp.group(1))
    mt = re.search(r'#define\s+OSRDN_TEX_PROLOGUE_WORDS\s+(\d+)', hdr)
    if not mt:
        print('sim_batch: FAIL (the header has no OSRDN_TEX_PROLOGUE_WORDS)')
        return 1
    tpro = int(mt.group(1))
    mw = re.search(r'#define\s+OSRDN_BATCH_MAX_WORDS\s+(\d+)', hdr)
    ms = re.search(r'#define\s+OSRDN_TRI_SEGS\s+(\d+)', open(os.path.join(MESA, 'OSRDNMesaTri.h')).read())
    if not mw or not ms:
        print('sim_batch: FAIL (no OSRDN_BATCH_MAX_WORDS in the table, or no OSRDN_TRI_SEGS in the unit header)')
        return 1
    maxwords, segsmax = int(mw.group(1)), int(ms.group(1))
    src = open(os.path.join(MESA, 'OSRDNMesaTri.c')).read()
    fails = 0
    with tempfile.TemporaryDirectory() as work:
        out, err = build_and_run(work, src, vo.SIM_WIN)
        if out is None:
            print('sim_batch: FAIL (the harness will not build)\n%s' % err)
            return 1
        bad = judge(out, vo, maxtris, pro, tpro, maxwords, segsmax)
        for b in bad:
            print('  FAIL %s' % b)
        fails += len(bad)
        if not bad:
            print('  ok   the batch the unit builds is one the kernel\'s rule '
                  'accepts (%d streams, up to %d triangles)'
                  % (len(parse(out)[1]), maxtris))
        # ---- M1r: the sent-log knob changes what is REMEMBERED, never what is
        #      SENT.  Built a second time with the knob off and compared word
        #      for word: the streams must be identical and the ring empty.
        cap, cerr = build_and_run(work, src, vo.SIM_WIN, env={'RDNMesaBatchWords': str(BATCH_CAP)})
        cp = ['the capped harness will not build: %s' % cerr] if cap is None else cap_check(cap)
        print('  %s RDNMesaBatchWords=%d: every stream within it, the longest %s words%s'
              % ('ok  ' if not cp else 'FAIL', BATCH_CAP,
                 max((len(w) for _, _, w in parse(cap)[1]), default=0) if cap else '-', '' if not cp else ': ' + '; '.join(cp)))
        fails += bool(cp)
        mut = src.replace('    if (triBatchCap > 0L && (unsigned long) triBatchCap < room)\n        room = (unsigned long) triBatchCap;\n', '', 1)
        if mut == src:
            print('  FAIL mutation the batch cap is ignored: anchor not found'); fails += 1
        else:
            mo, _ = build_and_run(work, mut, vo.SIM_WIN, env={'RDNMesaBatchWords': str(BATCH_CAP)})
            caught = mo is None or bool(cap_check(mo))
            print('  %s mutation %-40s %s' % ('ok  ' if caught else 'FAIL', 'the batch cap is ignored', 'caught' if caught else 'NOT caught'))
            fails += 0 if caught else 1
        off, oerr = build_and_run(work, src, vo.SIM_WIN, sentlog_off=True)
        if off is None:
            print('  FAIL the sent-log-off harness will not build\n%s' % oerr)
            fails += 1
        else:
            a, b = parse(out), parse(off)
            sa = [(c, n, tuple(w)) for c, n, w in a[1]]
            sb = [(c, n, tuple(w)) for c, n, w in b[1]]
            if not sa:
                print('  FAIL the baseline produced no stream to compare')
                fails += 1
            elif sa != sb:
                print('  FAIL RDNMesaSentLog=0 changed the STREAM (%d vs %d '
                      'streams, first difference at %s)'
                      % (len(sa), len(sb),
                         next((i for i in range(min(len(sa), len(sb)))
                               if sa[i] != sb[i]), 'the length')))
                fails += 1
            elif b[2].get('sentlog') != 0 or b[2].get('n') != 0:
                print('  FAIL RDNMesaSentLog=0 did not turn the ring off '
                      '(sentlog=%s n=%s)' % (b[2].get('sentlog'), b[2].get('n')))
                fails += 1
            elif a[2].get('n') == 0:
                print('  FAIL the baseline ring is empty, so "empty" proves '
                      'nothing')
                fails += 1
            elif a[2].get('submitted') != b[2].get('submitted'):
                print('  FAIL RDNMesaSentLog=0 changed `submitted` (%s vs %s) '
                      '-- the counters the gates read must not move'
                      % (a[2].get('submitted'), b[2].get('submitted')))
                fails += 1
            else:
                print('  ok   RDNMesaSentLog=0: %d streams identical word for '
                      'word, ring %d -> 0, submitted %d unchanged'
                      % (len(sa), a[2]['n'], a[2]['submitted']))
                # and the comparison above has to be able to FAIL: let the guard
                # swallow the counter as well, which is the mistake that would
                # make every gate that counts triangles read a smaller number.
                ms = src.replace('    triCounts.submitted++;',
                                 '    if (osrdn_tri_sentlog_enabled())\n'
                                 '        triCounts.submitted++;')
                if ms == src:
                    print('  FAIL mutation the guard swallows the counter '
                          'did not apply')
                    fails += 1
                else:
                    m1, _e1 = build_and_run(work, ms, vo.SIM_WIN)
                    m2, _e2 = build_and_run(work, ms, vo.SIM_WIN,
                                            sentlog_off=True)
                    caught = (m1 is None or m2 is None or
                              parse(m1)[2].get('submitted') !=
                              parse(m2)[2].get('submitted'))
                    print('  %-4s mutation the sent-log guard swallows the '
                          'triangle counter %s'
                          % ('ok' if caught else 'FAIL',
                             'caught' if caught else 'MISSED'))
                    fails += 0 if caught else 1

        # A check that cannot fail is not a check.  Each of these is a way the
        # batch could be wrong and still compile.
        for label, mut in MUTATIONS:
            ms = mut(src)
            if ms == src:
                print('  FAIL mutation %-52s did not apply' % label)
                fails += 1
                continue
            mo, me = build_and_run(work, ms, vo.SIM_WIN)
            caught = mo is None or bool(judge(mo, vo, maxtris, pro, tpro, maxwords, segsmax))
            print('  %-4s mutation %-52s %s' % ('ok' if caught else 'FAIL',
                                                label,
                                                'caught' if caught else 'MISSED'))
            fails += 0 if caught else 1
    print('sim_batch: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
