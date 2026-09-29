/*
 * world4.c - a fake RV280 2D engine for osrdn_engine.m (docs/R4_ENGINE_PLAN.md
 * 12-4 #2).  THIS PROVES "THE DRIVER MATCHES OUR MODEL", NOT THE HARDWARE: the
 * engine below is written from the same references the driver was, so a rule
 * both have wrong passes here.  Only the machine judges the hardware.
 *
 * The model:
 *   - MMIO is 0x4000 bytes; any access past it is recorded as a failure (the
 *     8 KiB map would have faulted, docs 9-1 E1);
 *   - RBBM_STATUS: FIFO free slots (engine register writes use one; a write
 *     with none free is an overflow = a hung bus on the machine) and ACTIVE,
 *     held for simBusyReads status reads after a trigger;
 *   - the operation's pixels go into a pending buffer and reach VRAM only when
 *     the chosen dest cache (simCache 2 = RB2D 0x342c, 3 = RB3D 0x325c) is
 *     flushed; the flush write must keep the register's other bits;
 *   - DP_GUI_MASTER_CNTL: DST/SRC_PITCH_OFFSET_CNTL select the per-op
 *     registers, otherwise DEFAULT_OFFSET is used (the decoy); AUX_CLIP_DIS
 *     clear with an aux scissor on clips everything; the default scissor always
 *     applies; the copy is pixel by pixel in the order the direction bits say,
 *     from the start coordinate as the first pixel processed;
 *   - PLL: an index byte at 0x08, data at 0x0c.
 */

#include <stdio.h>
#include <driverkit/generalFuncs.h>
#include "osrdn_engine.h"
#include "osrdn_snap.h"
#include "osrdn_port.h"

/* the user tool's expectations (R4c), compared here with what the driver and
   this engine actually leave; check_tool_r4map.py points this at mutants */
#ifndef R4MAP_WANT
#define R4MAP_WANT "../r4map_want.c"
#endif
#include R4MAP_WANT

void exit(int);

#define MMIO_BYTES      0x4000
#define VRAM_BYTES      0x1000000UL     /* 16 MiB of the card is enough for the test block */
#define WIN             0x00400000UL    /* 1024x768x32's window start (python: 4194304) */

static unsigned long    mmio[MMIO_BYTES / 4];
static unsigned long    vram[VRAM_BYTES / 4];
static unsigned long    pend[VRAM_BYTES / 4];
static unsigned char    pendSet[VRAM_BYTES / 4];
static int              pending;
static unsigned long    pll[0x40];
static int              pllIndex;

int     simBad;                 /* model violations */
int     simCache = 2;           /* which dest cache holds the result */
int     simBusyReads = 5;       /* status reads the engine stays active after a trigger */
int     simNeverIdle, simFifoStuck, simFrozenClock, simAuxClip, simDropRow, simActiveAtBoot, simDropHead;
int     busyLeft, fifoFree = 64, triggered, writesAfterTimeoutWatch, flushPending;
unsigned long engWrites, engWritesAfterTrigger, statusReads, sleepCalls;
static unsigned long long simClock;

/* ---- time ------------------------------------------------------------------ */
void IOGetTimestamp(ns_time_t *t) { if (!simFrozenClock) simClock += 1000ULL; *t = simClock; }
void IODelay(unsigned us) { if (!simFrozenClock) simClock += (unsigned long long)us * 1000ULL; }
void IOSleep(unsigned ms) { (void)ms; sleepCalls++; }
void IOLog(const char *f, ...) { (void)f; }
int splhigh(void) { return 0; }
int splx(int s) { (void)s; return 0; }
/* osrdn_snap.m's port accessors are not reached by the engine */
unsigned char osrdn_inb(IOEISAPortAddress p) { (void)p; return 0xff; }
void osrdn_outb(IOEISAPortAddress p, unsigned char d) { (void)p; (void)d; }
unsigned long osrdn_inl(IOEISAPortAddress p) { (void)p; return 0xffffffffUL; }
void osrdn_outl(IOEISAPortAddress p, unsigned long d) { (void)p; (void)d; }

/* ---- the engine ------------------------------------------------------------ */
#define R(o)    mmio[(o) / 4]

static int
inScissor(long x, long y)
{
    unsigned long br = R(0x16e8);       /* DEFAULT_SC_BOTTOM_RIGHT: x 12:0, y 28:16 */
    return x >= 0 && y >= 0 && (unsigned long)x <= (br & 0x1fffUL) && (unsigned long)y <= ((br >> 16) & 0x1fffUL);
}

static void
put(unsigned long card, unsigned long v)
{
    if (card >= VRAM_BYTES) {
        printf("  FAIL model: engine write outside the modelled VRAM at %08lx\n", card);
        simBad++;
        return;
    }
    pend[card / 4] = v;
    pendSet[card / 4] = 1;
    pending = 1;
}

static unsigned long
get(unsigned long card)
{
    if (card >= VRAM_BYTES)
        return 0;
    return pendSet[card / 4] ? pend[card / 4] : vram[card / 4];
}

static void
decode(unsigned long po, unsigned long *card, unsigned long *pitch)
{
    *card = (po & 0x3fffffUL) << 10;
    *pitch = ((po >> 22) & 0xffUL) * 64UL;
}

static void
execute(void)
{
    unsigned long gmc = R(0x146c), dir = R(0x16c0), wh = R(0x1598);
    unsigned long w = (wh >> 16) & 0x3fffUL, h = wh & 0x3fffUL;
    unsigned long dcard, dpitch, scard, spitch;
    long dx0 = (long)(R(0x1438) & 0x3fffUL), dy0 = (long)((R(0x1438) >> 16) & 0x3fffUL);
    long sx0 = (long)(R(0x1434) & 0x3fffUL), sy0 = (long)((R(0x1434) >> 16) & 0x3fffUL);
    long i, j, xs = (dir & 1UL) ? 1 : -1, ys = (dir & 2UL) ? 1 : -1;
    int blit = ((gmc >> 16) & 0xffUL) == 0xccUL;

    if (((gmc >> 8) & 0xfUL) != 6UL) {
        printf("  FAIL model: destination datatype %lu, the test surfaces are 32 bpp\n", (gmc >> 8) & 0xfUL);
        simBad++;
    }
    decode((gmc & 2UL) ? R(0x142c) : R(0x16e0), &dcard, &dpitch);
    decode((gmc & 1UL) ? R(0x1428) : R(0x16e0), &scard, &spitch);
    if (simAuxClip && !(gmc & 0x20000000UL))
        return;                                     /* an aux scissor the driver did not turn off */
    for (j = 0; j < (long)h; j++) {
        if (simDropRow && j == (long)h - 1)
            break;
        for (i = 0; i < (long)w; i++) {
            long dx = dx0 + xs * i, dy = dy0 + ys * j;
            if (simDropHead && j == 0 && i < 16)
                continue;                   /* the first 64 bytes of the rectangle never land */
            unsigned long v;
            if (!inScissor(dx, dy))
                continue;
            if (blit)
                v = get(scard + (unsigned long)(sy0 + ys * j) * spitch + (unsigned long)(sx0 + xs * i) * 4UL);
            else
                v = R(0x147c);
            put(dcard + (unsigned long)dy * dpitch + (unsigned long)dx * 4UL, v);
        }
    }
}

static void
land(void)
{
    unsigned long k;

    for (k = 0; k < VRAM_BYTES / 4; k++)
        if (pendSet[k]) {
            vram[k] = pend[k];
            pendSet[k] = 0;
        }
    pending = 0;
}

/* ---- MMIO -------------------------------------------------------------------- */
unsigned long
rdnMmioRead32(vm_address_t base, unsigned int off)
{
    (void)base;
    if (off + 4 > MMIO_BYTES) {
        printf("  FAIL model: MMIO read at %04x is outside the map\n", off);
        simBad++;
        return 0xffffffffUL;
    }
    if (off == 0x0e40) {
        unsigned long v = mmio[off / 4] & ~0x8000007fUL;
        int stuck = simFifoStuck && statusReads > 0;    /* the gate's own read sees it full */
        statusReads++;
        if (flushPending > 0) {
            flushPending--;                 /* a flush queued in the FIFO: the engine is busy */
            if (flushPending > 0)
                v |= 0x80000000UL;
            else
                land();
            return v | (unsigned long)(flushPending > 0 ? 63 : 64);
        }
        if ((triggered && simNeverIdle) || simActiveAtBoot) {
            v |= 0x80000000UL;
        } else if (busyLeft > 0) {
            busyLeft--;                     /* ACTIVE, then two reads with ACTIVE clear but the */
            if (busyLeft > 2)               /* FIFO not yet drained, then the work lands */
                v |= 0x80000000UL;
            if (busyLeft == 0) {
                execute();
                fifoFree = 64;
            }
        }
        return v | (unsigned long)(stuck ? 5 : (busyLeft > 0 ? 40 : fifoFree));
    }
    if (off == 0x000c)
        return pll[pllIndex & 0x3f];
    return mmio[off / 4];
}

void
rdnMmioWrite32(vm_address_t base, unsigned int off, unsigned long v)
{
    (void)base;
    if (off + 4 > MMIO_BYTES) {
        printf("  FAIL model: MMIO write at %04x is outside the map\n", off);
        simBad++;
        return;
    }
    if ((off >= 0x1400 && off < 0x1800) || off == 0x1c3c) {
        engWrites++;
        if (triggered)
            engWritesAfterTrigger++;
        if (fifoFree == 0 || (simFifoStuck && statusReads > 0 && !triggered)) {
            printf("  FAIL model: FIFO overflow at %04x (a hung bus on the machine)\n", off);
            simBad++;
        } else {
            fifoFree--;
        }
    }
    if (off == 0x342c || off == 0x325c) {
        if ((v & ~0xfUL) != (mmio[off / 4] & ~0x8000000fUL)) {
            printf("  FAIL model: the flush of %04x changed its other bits (%08lx over %08lx)\n",
                   off, v, mmio[off / 4]);
            simBad++;
        }
        if ((v & 0xfUL) == 0xfUL && ((off == 0x342c && simCache == 2) || (off == 0x325c && simCache == 3)))
            flushPending = 3;               /* lands after it is processed, not at the write */
        mmio[off / 4] = v & ~0x8000000fUL;  /* flushed: not busy, flush bits not stored */
        return;
    }
    mmio[off / 4] = v;
    if (off == 0x1598) {                    /* DST_WIDTH_HEIGHT: the trigger */
        if (R(0x1c3c) != 0UL) {
            printf("  FAIL model: the engine ran with RB3D_CNTL %08lx (3D not cleared, docs 17)\n", R(0x1c3c));
            simBad++;
        }
        triggered = 1;
        busyLeft = simBusyReads;
        if (busyLeft == 0) {
            execute();
            fifoFree = 64;
        }
    }
}

void
rdnMmioWrite8(vm_address_t base, unsigned int off, unsigned char v)
{
    (void)base;
    if (off == 0x0008) {
        pllIndex = v & 0x3f;
        mmio[0x0008 / 4] = (mmio[0x0008 / 4] & ~0xffUL) | v;
        return;
    }
    printf("  FAIL model: byte write at %04x\n", off);
    simBad++;
}

/* ---- the world ---------------------------------------------------------------- */
static osrdn_engine_state E;

static void
boot(void)
{
    unsigned long k;

    for (k = 0; k < MMIO_BYTES / 4; k++)
        mmio[k] = 0;
    for (k = 0; k < VRAM_BYTES / 4; k++) {
        vram[k] = 0x11111111UL;
        pendSet[k] = 0;
    }
    pending = 0;
    R(0x00f8) = 0x08000000UL;               /* CONFIG_MEMSIZE, R1 */
    R(0x0108) = 0x08000000UL;               /* CONFIG_APER_SIZE, R1 */
    R(0x0e40) = 0x00000140UL;               /* RBBM_STATUS, R1: FIFO 64, idle */
    R(0x0740) = 0x02010080UL;               /* CP_CSQ_CNTL, R2: mode 0 */
    R(0x0b00) = 0x00000100UL;               /* SURFACE_CNTL, R1 */
    R(0x342c) = 0x00000010UL;               /* a bit of its own the flush must keep */
    R(0x325c) = 0x00000020UL;
    R(0x16e0) = 0x00123456UL;               /* DEFAULT_OFFSET as the BIOS left it */
    R(0x16e8) = 0x00100010UL;               /* a small default scissor: the op must set its own */
    R(0x1c3c) = 0x00001800UL;               /* RB3D_CNTL as the machine read it (boot 027d9173) */
    R(0x0008) = 0x00000300UL;               /* CLOCK_CNTL_INDEX: PLL_DIV_SEL 3, index 0 */
    pllIndex = 0;
    pll[0x0d] = 0x00007ffaUL;
    pll[0x35] = 0x0000abcdUL;
    pll[0x14] = 0x00001234UL;
    fifoFree = 64;
    busyLeft = 0;
    triggered = 0;
    flushPending = 0;
    engWrites = engWritesAfterTrigger = 0;
    statusReads = 0;
    simNeverIdle = simFifoStuck = simFrozenClock = simAuxClip = simDropRow = simActiveAtBoot = simDropHead = 0;
    simCache = 2;
    simBusyReads = 5;
    for (k = 0; k < sizeof E; k++)
        ((unsigned char *)&E)[k] = 0;
    E.keyOn = 1;
    E.winStart = WIN;
    E.alias = (vm_address_t)&vram[WIN / 4];
}

static int bad;

#define EXPECT(cond, ...) do { if (!(cond)) { printf("  FAIL "); printf(__VA_ARGS__); printf("\n"); bad++; } } while (0)

static void
clean(const char *what, int rc)
{
    EXPECT(rc == ENG_RC_RAN, "%s: rc %d why %d gv %08lx", what, rc, E.why, E.gateValue);
    EXPECT(E.inBad == 0 && E.outBad == 0 && E.decoyBad == 0 && E.guardBad == 0,
           "%s: in %lu (not %lu) out %lu decoy %lu guard %lu first %ld", what, E.inBad, E.notBad,
           E.outBad, E.decoyBad, E.guardBad, E.first);
    EXPECT(R(0x16e0) == 0x00123456UL, "%s: DEFAULT_OFFSET left at %08lx", what, R(0x16e0));
    EXPECT(!E.wFifo.limit && !E.wIdle.limit && !E.wDc2.limit && !E.wDc3.limit,
           "%s: a wait hit its limit", what);
}

/* the world's own expectation of the fill, independent of the driver's judge */
static void
worldFill(unsigned long colour)
{
    unsigned long off, x, y, want, got;
    int wrong = 0;

    for (off = 0; off < ENG_ALIAS_BYTES; off += 4) {
        want = 0x5a5a5a5aUL;
        if (off >= ENG_S0_OFF && off < ENG_S0_OFF + 1024UL * 64UL) {
            y = (off - ENG_S0_OFF) / 1024UL;
            x = ((off - ENG_S0_OFF) % 1024UL) / 4UL;
            if (x >= 16 && x < 216 && y >= 8 && y < 48)
                want = colour;
        }
        got = vram[(WIN + off) / 4];
        if (got != want && !wrong++)
            printf("  FAIL world: fill word %lu is %08lx, want %08lx\n", off, got, want);
    }
    bad += wrong ? 1 : 0;
}

/* Time passes between two setIntValues calls (milliseconds on the machine),
   and the one register write after the last idle -- DEFAULT_OFFSET put back --
   is processed in it.  The model does not drain the FIFO on its own, so a test
   that runs two operations without boot() says so here.  (R4 ran fourteen
   operations in a row on the machine, every gate saw FIFO 64: docs/R4_ENGINE_PLAN.md 18.) */
static void
settle(void)
{
    fifoFree = 64;
    triggered = 0;
}

/* R4c: what a user task writes through its mapping (docs/R4C_VMAP_PLAN.md 11-4) */
static void
userWrites(unsigned long seed)
{
    unsigned long off;

    for (off = 0; off < ENG_ALIAS_BYTES; off += 4)
        vram[(WIN + off) / 4] = seed | (off >> 2);
}

/* the tool's expectation (r4map_want.c) against VRAM, every word, and its sorting */
static void
toolAgrees(int op, unsigned long arg)
{
    unsigned long off, want, got;
    int wrong = 0;

    for (off = 0; off < ENG_ALIAS_BYTES; off += 4) {
        want = (op == ENG_OP_UBLIT) ? r4mWantUblit(arg, off) : r4mWantFill(arg, off);
        got = vram[(WIN + off) / 4];
        if (got != want && !wrong++)
            printf("  FAIL tool: r4map_want says %08lx at %lu, VRAM holds %08lx\n", want, off, got);
    }
    bad += wrong ? 1 : 0;
}

/* the world's own expectation of UBLIT: case 0 is S1 (32,32) 64x64, pitch 512,
   onto S2 (8,0), pitch 512; S1 keeps the user's words, the rest is the marker */
static void
worldUblit(unsigned long seed)
{
    unsigned long off, x, y, want, got;
    int wrong = 0;

    for (off = 0; off < ENG_ALIAS_BYTES; off += 4) {
        want = 0x5a5a5a5aUL;
        if (off >= 98304UL && off < 98304UL + 512UL * 128UL)
            want = seed | (off >> 2);
        if (off >= 180224UL && off < 180224UL + 512UL * 64UL) {
            y = (off - 180224UL) / 512UL;
            x = ((off - 180224UL) % 512UL) / 4UL;
            if (x >= 8 && x < 72 && y < 64)
                want = seed | ((98304UL + (32UL + y) * 512UL + (32UL + x - 8UL) * 4UL) >> 2);
        }
        got = vram[(WIN + off) / 4];
        if (got != want && !wrong++)
            printf("  FAIL world: ublit word %lu is %08lx, want %08lx\n", off, got, want);
    }
    bad += wrong ? 1 : 0;
}

__attribute__((force_align_arg_pointer))
void
_start(void)
{
    int rc, k;
    unsigned long idx;

    /* RECORD reads, writes no engine register, puts the PLL index back */
    boot();
    idx = R(0x0008);
    rc = osrdn_engine_run(&E, 1, ENG_OP_RECORD, 0);
    EXPECT(rc == ENG_RC_RAN && engWrites == 0, "record: rc %d, %lu engine writes", rc, engWrites);
    EXPECT(R(0x0008) == idx, "record: PLL index %08lx, was %08lx", R(0x0008), idx);
    EXPECT(E.rec[ENG_REC_SCLK_CNTL] == 0x7ffaUL && E.rec[ENG_REC_SCLK_MORE_CNTL] == 0xabcdUL &&
           E.rec[ENG_REC_CLK_PWRMGT_CNTL] == 0x1234UL, "record: PLL words %08lx %08lx %08lx",
           E.rec[ENG_REC_SCLK_CNTL], E.rec[ENG_REC_SCLK_MORE_CNTL], E.rec[ENG_REC_CLK_PWRMGT_CNTL]);
    EXPECT(E.rec[ENG_REC_DEFAULT_OFFSET] == 0x00123456UL, "record: DEFAULT_OFFSET %08lx",
           E.rec[ENG_REC_DEFAULT_OFFSET]);
    printf("  %-4s record: reads, no engine write, the PLL index put back\n", bad ? "FAIL" : "ok");

    /* FILL, both caches, both colours; the world checks VRAM on its own */
    for (k = 0; k < 4; k++) {
        unsigned long colour = (k & 1) ? 0UL : 0xdeadbeefUL;
        int before = bad;
        boot();
        simCache = (k < 2) ? 2 : 3;
        rc = osrdn_engine_run(&E, 1, ENG_OP_FILL, colour);
        clean("fill", rc);
        worldFill(colour);
        toolAgrees(ENG_OP_FILL, colour);
        printf("  %-4s fill %08lx, result in the RB%dD cache\n", bad != before ? "FAIL" : "ok", colour, simCache);
    }

    /* BLIT 0..8 clean; 9..12 (a wrong direction bit) must show mismatches */
    for (k = 0; k < ENG_BLIT_CASES; k++) {
        int before = bad;
        boot();
        simCache = (k & 1) ? 3 : 2;
        rc = osrdn_engine_run(&E, 1, ENG_OP_BLIT, (unsigned long)k);
        if (k <= 8) {
            clean("blit", rc);
        } else {
            EXPECT(rc == ENG_RC_RAN && E.inBad > 0 && E.outBad == 0 && E.guardBad == 0 && E.decoyBad == 0,
                   "blit %d (wrong direction on purpose): in %lu out %lu guard %lu", k, E.inBad, E.outBad,
                   E.guardBad);
        }
        printf("  %-4s blit case %2d: in %lu not %lu\n", bad != before ? "FAIL" : "ok", k, E.inBad, E.notBad);
    }

    /* the driver's judge sees what the engine got wrong */
    boot();
    simDropRow = 1;
    rc = osrdn_engine_run(&E, 1, ENG_OP_FILL, 0xdeadbeefUL);
    EXPECT(rc == ENG_RC_RAN && E.inBad == 200 && E.notBad == 200 && E.rereadDone,
           "a dropped row: in %lu not %lu reread %d", E.inBad, E.notBad, E.rereadDone);
    boot();
    simDropHead = 1;
    rc = osrdn_engine_run(&E, 1, ENG_OP_FILL, 0xdeadbeefUL);
    EXPECT(rc == ENG_RC_RAN && E.inBad == 16 && E.f64 == 16 && E.first == (long)(ENG_S0_OFF + 8 * 1024 + 16 * 4),
           "the rectangle's first 64 bytes stale: in %lu f64 %lu first %ld", E.inBad, E.f64, E.first);
    boot();
    rc = osrdn_engine_run(&E, 1, ENG_OP_FILL, 0x5a5a5a5aUL);
    EXPECT(rc == ENG_RC_REFUSED && E.why == ENG_WHY_MARK_COLOUR && engWrites == 0,
           "a fill with the marker colour: rc %d why %d writes %lu", rc, E.why, engWrites);
    boot();
    simAuxClip = 1;
    rc = osrdn_engine_run(&E, 1, ENG_OP_FILL, 0xdeadbeefUL);
    clean("fill with an aux scissor left on", rc);
    printf("  %-4s the judge counts a dropped row; an aux scissor left on is turned off\n", bad ? "FAIL" : "ok");

    /* waits: never idle -> latched, nothing written after; a stuck FIFO -> nothing written */
    {
        int before = bad;
        unsigned long vramBefore;
        boot();
        simNeverIdle = 1;
        rc = osrdn_engine_run(&E, 1, ENG_OP_FILL, 0xdeadbeefUL);
        EXPECT(rc == ENG_RC_POST_TIMEOUT && E.latched && E.defaultLeft && engWritesAfterTrigger == 0,
               "never idle: rc %d latched %d left %d writes after the trigger %lu", rc, E.latched,
               E.defaultLeft, engWritesAfterTrigger);
        vramBefore = engWrites;
        rc = osrdn_engine_run(&E, 1, ENG_OP_RECORD, 0);
        EXPECT(rc == ENG_RC_REFUSED && E.why == ENG_WHY_LATCHED && engWrites == vramBefore,
               "after the latch: rc %d why %d", rc, E.why);
        boot();
        simFifoStuck = 1;                   /* full at the gate, stuck at 5 from then on */
        rc = osrdn_engine_run(&E, 1, ENG_OP_FILL, 0xdeadbeefUL);
        EXPECT(rc == ENG_RC_PRE_TIMEOUT && engWrites == 0 && E.wFifo.limit && simBad == 0,
               "stuck FIFO after the gate: rc %d, %lu engine writes, limit %d", rc, engWrites, E.wFifo.limit);
        boot();
        simFrozenClock = 1;
        simNeverIdle = 1;
        rc = osrdn_engine_run(&E, 1, ENG_OP_FILL, 0xdeadbeefUL);
        EXPECT(rc == ENG_RC_POST_TIMEOUT && E.wIdle.limit && E.wIdle.evals > 1,
               "frozen clock: rc %d idle evals %lu limit %d", rc, E.wIdle.evals, E.wIdle.limit);
        EXPECT(sleepCalls == 0, "the engine slept %lu times", sleepCalls);
        printf("  %-4s waits: never idle latches with no write after, a frozen clock still ends, no sleep\n",
               bad != before ? "FAIL" : "ok");
    }

    /* R4c UBLIT (docs/R4C_VMAP_PLAN.md 11-2): the user's words are the source */
    {
        int before = bad, n;
        unsigned long w0, off;
        unsigned long badSeeds[4] = { 0xc3120001UL, 0x5a120000UL, 0xff120000UL, 0x96120000UL };

        boot();
        userWrites(0xc3120000UL);
        rc = osrdn_engine_run(&E, 1, ENG_OP_UBLIT, 0xc3120000UL);
        clean("ublit", rc);
        worldUblit(0xc3120000UL);
        toolAgrees(ENG_OP_UBLIT, 0xc3120000UL);
        /* the same seed again, with the user's words written again: refused, nothing written */
        settle();
        userWrites(0xc3120000UL);
        w0 = engWrites;
        rc = osrdn_engine_run(&E, 1, ENG_OP_UBLIT, 0xc3120000UL);
        EXPECT(rc == ENG_RC_REFUSED && E.why == ENG_WHY_SEED && engWrites == w0,
               "ublit, the seed again: rc %d why %d writes %lu", rc, E.why, engWrites - w0);
        /* a new seed runs */
        settle();
        userWrites(0x3c120000UL);
        rc = osrdn_engine_run(&E, 1, ENG_OP_UBLIT, 0x3c120000UL);
        clean("ublit, a second seed", rc);
        worldUblit(0x3c120000UL);
        /* the user never wrote: refused before any write, the block untouched */
        boot();
        rc = osrdn_engine_run(&E, 1, ENG_OP_UBLIT, 0xc3340000UL);
        EXPECT(rc == ENG_RC_REFUSED && E.why == ENG_WHY_USER && E.gateValue == ENG_ALIAS_BYTES / 4 &&
               engWrites == 0 && E.first == 0, "ublit, no user write: rc %d why %d gv %lu writes %lu first %ld",
               rc, E.why, E.gateValue, engWrites, E.first);
        for (off = 0, n = 0; off < ENG_ALIAS_BYTES; off += 4)
            n += (vram[(WIN + off) / 4] != 0x11111111UL);
        EXPECT(n == 0, "ublit, no user write: %d words of the block changed", n);
        /* one page the user's mapping missed, outside S1: still refused */
        boot();
        userWrites(0xc3560000UL);
        for (off = 0x2000UL; off < 0x4000UL; off += 4)
            vram[(WIN + off) / 4] = 0x11111111UL;
        rc = osrdn_engine_run(&E, 1, ENG_OP_UBLIT, 0xc3560000UL);
        EXPECT(rc == ENG_RC_REFUSED && E.why == ENG_WHY_USER && E.gateValue == 2048UL &&
               E.first == 0x2000L && engWrites == 0,
               "ublit, one page missed: rc %d why %d gv %lu first %ld", rc, E.why, E.gateValue, E.first);
        /* seeds whose words could be mistaken for the marker, the pattern or the colour */
        for (n = 0; n < 4; n++) {
            boot();
            userWrites(badSeeds[n] & 0xffff0000UL);
            rc = osrdn_engine_run(&E, 1, ENG_OP_UBLIT, badSeeds[n]);
            EXPECT(rc == ENG_RC_REFUSED && E.why == ENG_WHY_BAD_OP && engWrites == 0,
                   "ublit seed %08lx: rc %d why %d", badSeeds[n], rc, E.why);
        }
        printf("  %-4s ublit: the user's words copied; a reused seed, a missing write, a missed page, a bad seed refused\n",
               bad != before ? "FAIL" : "ok");
    }

    /* the tool's sorting of a wrong word (r4map_want.c r4mClass) */
    {
        int before = bad;
        unsigned long src = 0, spotOff = 180224UL + 8UL * 4UL;     /* S2 (8,0): the copy's first word */
        EXPECT(r4mUblitSpot(spotOff, &src) && src == 98304UL + 32UL * 512UL + 32UL * 4UL,
               "tool: the copy's first word maps to %lu", src);
        EXPECT(!r4mUblitSpot(180224UL + 7UL * 4UL, &src), "tool: S2 (7,0) is not in the copy");
        EXPECT(r4mClass(5, 5, 7, 1) == R4M_OK && r4mClass(7, 5, 7, 1) == R4M_STALE &&
               r4mClass(0x5a5a5a5aUL, 5, 7, 1) == R4M_MARKED && r4mClass(0x5a5a5a5aUL, 5, 7, 0) == R4M_OTHER &&
               r4mClass(9, 5, 7, 1) == R4M_OTHER, "tool: r4mClass sorts wrongly");
        EXPECT(r4mFillSpot(16384UL + 8UL * 1024UL + 16UL * 4UL) && !r4mFillSpot(16384UL + 8UL * 1024UL + 15UL * 4UL) &&
               !r4mFillSpot(16384UL + 48UL * 1024UL + 16UL * 4UL), "tool: the fill rectangle's edges");
        printf("  %-4s the tool's expectations equal VRAM after ublit and fill, its sorting holds\n",
               bad != before ? "FAIL" : "ok");
    }

    /* every gate refuses with no engine write */
    {
        struct { unsigned int off; unsigned long v; int why; } g[] = {
            { 0x0e40, 0x00000130UL, ENG_WHY_FIFO },
            { 0x0e40, 0x80000140UL, ENG_WHY_ACTIVE },
            { 0x0740, 0x12010080UL, ENG_WHY_CPMODE },
            { 0x342c, 0x80000010UL, ENG_WHY_DC2_BUSY },
            { 0x325c, 0x80000020UL, ENG_WHY_DC3_BUSY },
            { 0x0b00, 0x00200100UL, ENG_WHY_SURFACE },
            { 0x00f8, 0x00400000UL, ENG_WHY_REACH },
            { 0x0108, 0x00400000UL, ENG_WHY_REACH }
        };
        int before = bad, n;
        for (n = 0; n < (int)(sizeof g / sizeof g[0]); n++) {
            boot();
            R(g[n].off) = g[n].v;
            if (g[n].off == 0x0e40 && (g[n].v & 0x7fUL) != 0x40UL)
                fifoFree = (int)(g[n].v & 0x7fUL);
            if (g[n].off == 0x0e40 && (g[n].v & 0x80000000UL))
                simActiveAtBoot = 1;
            if (g[n].off == 0x342c || g[n].off == 0x325c)
                mmio[g[n].off / 4] = g[n].v;
            rc = osrdn_engine_run(&E, 1, ENG_OP_FILL, 0xdeadbeefUL);
            EXPECT(rc == ENG_RC_REFUSED && E.why == g[n].why && engWrites == 0,
                   "gate %04x=%08lx: rc %d why %d (want %d) writes %lu", g[n].off, g[n].v, rc, E.why,
                   g[n].why, engWrites);
        }
        boot();
        E.keyOn = 0;
        rc = osrdn_engine_run(&E, 1, ENG_OP_FILL, 0);
        EXPECT(rc == ENG_RC_REFUSED && E.why == ENG_WHY_KEY, "key off: why %d", E.why);
        boot();
        E.alias = 0;
        rc = osrdn_engine_run(&E, 1, ENG_OP_FILL, 0);
        EXPECT(rc == ENG_RC_REFUSED && E.why == ENG_WHY_NO_ALIAS, "no alias: why %d", E.why);
        boot();
        rc = osrdn_engine_run(&E, 1, ENG_OP_BLIT, ENG_BLIT_CASES);
        EXPECT(rc == ENG_RC_REFUSED && E.why == ENG_WHY_BAD_OP && engWrites == 0, "bad case: why %d", E.why);
        printf("  %-4s every gate refuses with no engine write\n", bad != before ? "FAIL" : "ok");
    }

    EXPECT(simBad == 0, "the model recorded %d violations", simBad);
    printf("%s\n", bad ? "world4: FAIL" : "world4: PASS");
    exit(bad ? 1 : 0);
}
