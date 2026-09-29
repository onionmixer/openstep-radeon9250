/*
 * OSRDNMesaTime.c - G5-0: the frame-budget instrument (docs/G5_0_PERF_MEASURE_PLAN.md 2).
 * See the header for what and why.
 *
 * No system headers, as the rest of the library (OSRDNMesaTri.c declares what
 * it calls): the host check compiles every unit as 32-bit syntax and has no
 * 32-bit libc headers.  The report is written with write(2) from a buffer
 * formatted here -- decimal and eight-digit hex are all it needs.
 */
#include "OSRDNMesaTime.h"

struct osrdn_timeval { long sec; long usec; };      /* struct timeval: two longs, on the target as on the host */
extern int gettimeofday(struct osrdn_timeval *, void *);
extern char *getenv(const char *);
extern int atexit(void (*)(void));
extern int write(int, const void *, unsigned int);

int osrdn_time_in_render;
int osrdn_time_in_hook;

/* the two words are 32-bit words.  On the target `unsigned long` is one and
   the mask is ~0UL, a no-op the compiler folds; on the host it is 64 bits and
   the mask is what lets tools/mesa/sim_time.py run this very file with the
   target's arithmetic. */
#define TIME_WORD  0xffffffffUL

static int timeOn = -1;                         /* -1: not asked yet */
static osrdn_time_acc acc[OSRDN_TIME_SITES][OSRDN_TIME_TAGS];
static unsigned long units[OSRDN_TIME_SITES];
static unsigned long framesPresent, framesClear, lastDstY;
static osrdn_time_stamp t0;
static struct osrdn_timeval tv0;
static unsigned long gtodCycles;                /* what 1000 gettimeofday calls cost, cycles (low word) */
static int reported;
static void (*alsoReport)(void);               /* G5-1b: the hook's counts, after the times */
/* G5-3 (docs/G5_3_QUERY_CONSOLE_PLAN.md 2): RDNMesaTimeSplit=N prints the running totals once, as
   RDN-TS lines, when the N-th frame is counted -- so one run gives the console part and the world
   part separately (the judge subtracts).  0 = off */
static unsigned long splitAt;
static int splitDone;
static void timeBlock(const char *pfx);

void
osrdn_time_at_exit(void (*fn)(void))
{
    alsoReport = fn;
}

static const char *siteName[OSRDN_TIME_SITES] = {
    "tri", "bracket", "verify", "submit", "present", "clear", "upload", "query"
};
static const char *tagName[OSRDN_TIME_TAGS] = { "out", "br", "hook" };

void
osrdn_time_now(osrdn_time_stamp *t)
{
    unsigned long lo, hi;

    __asm__ __volatile__(".byte 0x0f, 0x31" : "=a"(lo), "=d"(hi));     /* rdtsc */
    t->lo = lo & TIME_WORD;
    t->hi = hi & TIME_WORD;
}

/* b - a as two words; the borrow is the one comparison */
static void
timeDiff(const osrdn_time_stamp *a, const osrdn_time_stamp *b, unsigned long *dlo, unsigned long *dhi)
{
    *dlo = (b->lo - a->lo) & TIME_WORD;
    *dhi = (b->hi - a->hi - ((b->lo < a->lo) ? 1UL : 0UL)) & TIME_WORD;
}

static void
timeStart(void)
{
    osrdn_time_stamp a, b;
    struct osrdn_timeval tv;
    int k;

    gettimeofday(&tv0, 0);
    osrdn_time_now(&t0);
    /* the cost of the clock this instrument refuses to use per triangle */
    osrdn_time_now(&a);
    for (k = 0; k < 1000; k++)
        gettimeofday(&tv, 0);
    osrdn_time_now(&b);
    gtodCycles = (b.lo - a.lo) & TIME_WORD;
    {
        const char *e = getenv("RDNMesaTimeSplit");

        splitAt = 0UL;
        while (e != 0 && *e >= '0' && *e <= '9') {
            splitAt = splitAt * 10UL + (unsigned long)(*e - '0');
            e++;
        }
    }
    atexit(osrdn_time_report);
}

int
osrdn_time_on(void)
{
    if (timeOn < 0) {
        timeOn = (getenv("RDNMesaTime") != 0) ? 1 : 0;
        if (timeOn)
            timeStart();
    }
    return timeOn;
}

void
osrdn_time_add(int site, const osrdn_time_stamp *start)
{
    osrdn_time_stamp now;
    osrdn_time_acc *a;
    unsigned long dlo, dhi;
    int tag;

    if (site < 0 || site >= OSRDN_TIME_SITES)
        return;
    osrdn_time_now(&now);
    timeDiff(start, &now, &dlo, &dhi);
    tag = osrdn_time_in_hook ? OSRDN_TIME_HOOK : (osrdn_time_in_render ? OSRDN_TIME_BR : OSRDN_TIME_OUT);
    a = &acc[site][tag];
    a->n++;
    a->lo = (a->lo + dlo) & TIME_WORD;
    if (a->lo < dlo)
        a->hi++;
    a->hi = (a->hi + dhi) & TIME_WORD;
    if (dhi != 0UL)
        a->huge++;
    else if (dlo > a->max)
        a->max = dlo;
}

void
osrdn_time_count(int site, unsigned long u)
{
    if (site >= 0 && site < OSRDN_TIME_SITES)
        units[site] += u;
}

void
osrdn_time_frame_present(unsigned long dstY)
{
    /* SDL stamps a frame's rows from the bottom of the destination up
       (SDL_openstepvideo.m 2578-2583), so the row that goes back DOWN the
       screen -- a larger dstY than the last -- is the first row of a frame */
    /* G5-1b: a coalesced frame is one call at the same dstY every frame, so
       "not below the last" is the boundary; a row run still strictly descends */
    if (framesPresent == 0UL || dstY >= lastDstY)
        framesPresent++;
    lastDstY = dstY;
    if (timeOn == 1 && splitAt != 0UL && !splitDone && framesPresent == splitAt) {
        splitDone = 1;
        timeBlock("RDN-TS");
    }
}

void
osrdn_time_frame_clear(void)
{
    framesClear++;
}

unsigned long
osrdn_time_calls(int site)
{
    unsigned long n = 0UL;
    int tag;

    if (site < 0 || site >= OSRDN_TIME_SITES)
        return 0UL;
    for (tag = 0; tag < OSRDN_TIME_TAGS; tag++)
        n += acc[site][tag].n;
    return n;
}

unsigned long
osrdn_time_units(int site)
{
    return (site >= 0 && site < OSRDN_TIME_SITES) ? units[site] : 0UL;
}

/* this run's calibration: cycles per microsecond from the two clocks over the
   same span, as a double -- the only floating point in the instrument, and
   only for the port's summary line; the report prints the raw words */
static double
cyclesPerUs(void)
{
    osrdn_time_stamp now;
    struct osrdn_timeval tv;
    unsigned long dlo, dhi;
    double cyc, us;

    gettimeofday(&tv, 0);
    osrdn_time_now(&now);
    timeDiff(&t0, &now, &dlo, &dhi);
    cyc = (double)dhi * 4294967296.0 + (double)dlo;
    us = (double)(tv.sec - tv0.sec) * 1000000.0 + (double)(tv.usec - tv0.usec);
    if (us <= 0.0)
        return 0.0;
    return cyc / us;
}

unsigned long
osrdn_time_us(int site)
{
    double cpu = cyclesPerUs();
    double cyc = 0.0;
    int tag;

    if (site < 0 || site >= OSRDN_TIME_SITES || cpu <= 0.0)
        return 0UL;
    for (tag = 0; tag < OSRDN_TIME_TAGS; tag++)
        cyc += (double)acc[site][tag].hi * 4294967296.0 + (double)acc[site][tag].lo;
    return (unsigned long)(cyc / cpu);
}

/* ---- the report: a line buffer and two number formats ---- */

static char lineBuf[256];
static unsigned int lineLen;
static int lineCut;

static void
putStr(const char *s)
{
    while (*s != '\0' && lineLen < sizeof lineBuf - 1U)
        lineBuf[lineLen++] = *s++;
    if (*s != '\0')
        lineCut = 1;                    /* G5-6: a line past the buffer is said, not silently cut */
}

static void
putDec(unsigned long v)
{
    char d[12];
    int k = 0;

    do {
        d[k++] = (char)('0' + (int)(v % 10UL));
        v /= 10UL;
    } while (v != 0UL && k < 11);
    while (k > 0 && lineLen < sizeof lineBuf - 1U)
        lineBuf[lineLen++] = d[--k];
}

static void
putHex8(unsigned long v)
{
    static const char hx[] = "0123456789abcdef";
    int k;

    for (k = 28; k >= 0; k -= 4)
        if (lineLen < sizeof lineBuf - 1U)
            lineBuf[lineLen++] = hx[(v >> k) & 15UL];
}

static void
lineEnd(void)
{
    if (lineLen < sizeof lineBuf - 1U)
        lineBuf[lineLen++] = '\n';
    else
        lineBuf[lineLen - 1U] = '\n';  /* the newline survives a full buffer */
    (void) write(2, lineBuf, lineLen);
    lineLen = 0;
    if (lineCut) {
        static const char cut[] = "RDN-CUT the line above lost its end\n";

        lineCut = 0;
        (void) write(2, cut, sizeof cut - 1U);
    }
}

void
osrdn_time_line_begin(const char *prefix)
{
    lineLen = 0;
    putStr(prefix);
}

void
osrdn_time_line_put(const char *key, unsigned long value)
{
    putStr(" ");
    putStr(key);
    putStr("=");
    putDec(value);
}

void
osrdn_time_line_end(void)
{
    lineEnd();
}

void
osrdn_time_report(void)
{
    if (timeOn != 1 || reported)
        return;
    reported = 1;
    timeBlock("RDN-T");
    if (alsoReport != 0)
        (*alsoReport)();
}

/* the totals so far, every line under one prefix (RDN-T at exit, RDN-TS at the split) */
static void
timeBlock(const char *pfx)
{
    osrdn_time_stamp now;
    struct osrdn_timeval tv;
    unsigned long dlo, dhi, wallUs;
    int site, tag;

    gettimeofday(&tv, 0);
    osrdn_time_now(&now);
    timeDiff(&t0, &now, &dlo, &dhi);
    wallUs = (unsigned long)(tv.sec - tv0.sec) * 1000000UL + (unsigned long)tv.usec - (unsigned long)tv0.usec;
    lineLen = 0;
    putStr(pfx); putStr(" wall us="); putDec(wallUs);
    putStr(" cyc="); putHex8(dhi); putHex8(dlo);
    putStr(" gtod1000cyc="); putDec(gtodCycles);
    putStr(" frames_present="); putDec(framesPresent);
    putStr(" frames_clear="); putDec(framesClear);
    lineEnd();
    for (site = 0; site < OSRDN_TIME_SITES; site++)
        for (tag = 0; tag < OSRDN_TIME_TAGS; tag++) {
            const osrdn_time_acc *a = &acc[site][tag];

            if (a->n == 0UL)
                continue;
            putStr(pfx); putStr(" site="); putStr(siteName[site]);
            putStr(" tag="); putStr(tagName[tag]);
            putStr(" n="); putDec(a->n);
            putStr(" cyc="); putHex8(a->hi); putHex8(a->lo);
            putStr(" max="); putDec(a->max);
            putStr(" huge="); putDec(a->huge);
            putStr(" units="); putDec(units[site]);      /* the site's total, on each of its lines */
            lineEnd();
        }
    putStr(pfx); putStr(" end");
    lineEnd();
}
