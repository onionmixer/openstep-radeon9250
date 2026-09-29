/*
 * osrdn_engine.m - see osrdn_engine.h.  Plain C89 over the RDNR2aMMIO
 * accessors and the alias; no log, no sleep.
 *
 * Register offsets and bits: NetBSD radeonfbreg.h, xf86-video-ati 6.14.6
 * radeon_reg.h and FreeBSD radeon_drv.h agree on every value used here
 * (docs/R4_ENGINE_PLAN.md 1-1, 9, 13); tools/oracle/regtable.py holds the
 * offsets to the three headers.
 */

#import <driverkit/generalFuncs.h>      /* IODelay, IOGetTimestamp */
#import "RDNR2aMMIO.h"
#import "osrdn_snap.h"                  /* osrdn_pll_peek */
#import "osrdn_engine.h"

/* ---- registers ------------------------------------------------------------- */
#define E_CONFIG_MEMSIZE        0x00f8
#define E_CONFIG_APER_SIZE      0x0108
#define E_CP_CSQ_CNTL           0x0740
#define E_SURFACE_CNTL          0x0b00
#define E_RBBM_STATUS           0x0e40
#define E_SRC_PITCH_OFFSET      0x1428
#define E_DST_PITCH_OFFSET      0x142c
#define E_SRC_Y_X               0x1434
#define E_DST_Y_X               0x1438
#define E_DP_GUI_MASTER_CNTL    0x146c
#define E_DP_BRUSH_FRGD_CLR     0x147c
#define E_DST_WIDTH_HEIGHT      0x1598      /* w << 16 | h; the trigger, written last */
#define E_AUX_SC_CNTL           0x1660
#define E_DP_CNTL               0x16c0
#define E_DP_DATATYPE           0x16c4
#define E_DP_WRITE_MASK         0x16cc
#define E_DEFAULT_OFFSET        0x16e0      /* = DEFAULT_PITCH_OFFSET (radeonfbreg.h 689-690) */
#define E_DEFAULT_PITCH         0x16e4
#define E_DEFAULT_SC_BR         0x16e8
#define E_SC_TOP_LEFT           0x16ec
#define E_SC_BOTTOM_RIGHT       0x16f0
#define E_DSTCACHE_CTLSTAT      0x1714
#define E_RB3D_CNTL             0x1c3c
#define E_RB3D_DSTCACHE_CTLSTAT 0x325c
#define E_RB2D_DSTCACHE_MODE    0x3428
#define E_RB2D_DSTCACHE_CTLSTAT 0x342c

#define E_FIFO_MASK             0x7fUL          /* RBBM_FIFOCNT_MASK: free slots */
#define E_FIFO_DEPTH            64UL            /* "The FIFO has 64 slots" (radeon_accel.c) */
#define E_RBBM_ACTIVE           0x80000000UL
#define E_CSQ_MODE_MASK         0xf0000000UL    /* 0 = CSQ_PRIDIS_INDDIS: CP off */
#define E_SURF_SWAP_MASK        0x00f00000UL    /* NONSURF_AP0/AP1 SWP 16/32 BPP, bits 20-23 */
#define E_DC_FLUSH_ALL          0x0000000fUL
#define E_DC_BUSY               0x80000000UL

/* DP_GUI_MASTER_CNTL, 32 bpp (python, docs/R4_ENGINE_PLAN.md 9-2 #5):
 *   fill = DST_PITCH_OFFSET_CNTL | BRUSH_SOLID_COLOR | DST_32BPP | SRC_DATATYPE_COLOR
 *          | ROP3_P | CLR_CMP_CNTL_DIS | AUX_CLIP_DIS
 *   blit = SRC_ and DST_PITCH_OFFSET_CNTL | BRUSH_NONE | DST_32BPP | SRC_DATATYPE_COLOR
 *          | ROP3_S | DP_SRC_SOURCE_MEMORY | CLR_CMP_CNTL_DIS | AUX_CLIP_DIS */
#define E_GMC_FILL              0x30f036d2UL
#define E_GMC_BLIT              0x32cc36f3UL
#define E_DIR_X_LTR             0x1UL           /* DST_X_LEFT_TO_RIGHT */
#define E_DIR_Y_TTB             0x2UL           /* DST_Y_TOP_TO_BOTTOM */
#define E_SC_MAX                0x1fff1fffUL

/* ---- the test ------------------------------------------------------------- */
#define E_MARK                  ENG_MARK        /* the values live in osrdn_engine.h, */
#define E_FILL_X                ENG_FILL_X      /* where the R4c tool's copies are    */
#define E_FILL_Y                ENG_FILL_Y      /* checked against them               */
#define E_FILL_W                ENG_FILL_W
#define E_FILL_H                ENG_FILL_H
#define E_FILL_WRITES           12UL            /* RB3D_CNTL = 0 first (docs 17) */
#define E_BLIT_WRITES           13UL

/* waits: nominal limits in microseconds, spun in ticks of IODelay.  The turn
   cap is twice the nominal turns (this machine's IODelay runs short, R2
   closeout) plus slack, for a clock that does not advance. */
#define E_TICK_US               10UL
#define E_FIFO_US               10000UL
#define E_IDLE_US               100000UL
#define E_DC_US                 10000UL
#define E_TURN_FACTOR           2UL
#define E_TURN_SLACK            8UL
#define E_REREAD_US             1000UL

#define W_FIFO                  1
#define W_IDLE                  2
#define W_DC2                   3
#define W_DC3                   4

/* one blit case: from surface s at (sx, sy) to surface d at (dx, dy), w x h;
   flip 1 = the X bit deliberately wrong, 2 = the Y bit */
typedef struct {
    unsigned long   srcOff, srcPitch, sx, sy;
    unsigned long   dstOff, dstPitch, dstH, dx, dy;
    unsigned long   w, h;
    int             flip;
} engCase;

#define S1P                     (ENG_S1_W * 4UL)
#define S2P                     (ENG_S2_W * 4UL)
static const engCase engCases[ENG_BLIT_CASES] = {
    { ENG_S1_OFF, S1P, 32, 32, ENG_S2_OFF, S2P, ENG_S2_H,  8,  0, 64, 64, 0 },   /* 0: between surfaces */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 40, 40, 64, 64, 0 },   /* 1: (+8,+8) */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 24, 24, 64, 64, 0 },   /* 2: (-8,-8) */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 40, 24, 64, 64, 0 },   /* 3: (+8,-8) */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 24, 40, 64, 64, 0 },   /* 4: (-8,+8) */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 40, 32, 64, 64, 0 },   /* 5: (+8, 0) */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 24, 32, 64, 64, 0 },   /* 6: (-8, 0) */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 32, 40, 64, 64, 0 },   /* 7: ( 0,+8) */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 32, 24, 64, 64, 0 },   /* 8: ( 0,-8) */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 40, 32, 64, 64, 1 },   /* 9: case 5, X wrong */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 24, 32, 64, 64, 1 },   /* 10: case 6, X wrong */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 32, 40, 64, 64, 2 },   /* 11: case 7, Y wrong */
    { ENG_S1_OFF, S1P, 32, 32, ENG_S1_OFF, S1P, ENG_S1_H, 32, 24, 64, 64, 2 }    /* 12: case 8, Y wrong */
};

/* ---- small helpers --------------------------------------------------------- */

/* the one place a case is chosen: UBLIT's arg is a seed, never an index
   (docs/R4C_VMAP_PLAN.md 10-1 E5) */
static const engCase *
engCaseFor(int op, unsigned long arg)
{
    if (op == ENG_OP_UBLIT)
        return &engCases[0];
    return &engCases[arg];
}

static int
isBlit(int op)
{
    return op == ENG_OP_BLIT || op == ENG_OP_UBLIT;
}

static unsigned long
engElapsedUs(ns_time_t t0, ns_time_t t1)
{
    ns_time_t       d;
    unsigned int    low;

    /* one comparison per statement: cc 2.7.2.1 -O inverts long long tests
       joined by && or || */
    if (t1 <= t0)
        return 0;
    d = t1 - t0;
    if (d > 0xffffffffULL)
        return 0xffffffffUL;
    low = (unsigned int)d;
    return (unsigned long)(low / 1000U);
}

unsigned long
osrdn_engine_pitch_offset(unsigned long card, unsigned long pitchBytes)
{
    return ((pitchBytes / 64UL) << 22) | (card >> 10);
}

void
osrdn_engine_vram_reach(vm_address_t base, unsigned long *memsize, unsigned long *aperSize)
{
    *memsize = rdnMmioRead32(base, E_CONFIG_MEMSIZE);
    *aperSize = rdnMmioRead32(base, E_CONFIG_APER_SIZE);
}

/* a UBLIT seed whose words cannot be mistaken for the marker, the pattern or
   the tool's fill colour (docs/R4C_VMAP_PLAN.md 11-2) */
static int
engSeedOk(unsigned long seed)
{
    unsigned long top = seed >> 24;

    if ((seed & ENG_SEED_LOW_MASK) != 0UL)
        return 0;
    return top != ENG_SEED_BAD_TOP_1 && top != ENG_SEED_BAD_TOP_2 && top != ENG_SEED_BAD_TOP_3;
}

static int
engCond(vm_address_t base, int kind, unsigned long need)
{
    unsigned long v;

    switch (kind) {
    case W_FIFO:
        v = rdnMmioRead32(base, E_RBBM_STATUS);
        return (v & E_FIFO_MASK) >= need;
    case W_IDLE:
        v = rdnMmioRead32(base, E_RBBM_STATUS);
        if ((v & E_FIFO_MASK) != E_FIFO_DEPTH)
            return 0;
        return (v & E_RBBM_ACTIVE) == 0UL;
    case W_DC2:
        return (rdnMmioRead32(base, E_RB2D_DSTCACHE_CTLSTAT) & E_DC_BUSY) == 0UL;
    case W_DC3:
        return (rdnMmioRead32(base, E_RB3D_DSTCACHE_CTLSTAT) & E_DC_BUSY) == 0UL;
    }
    return 0;
}

/* 1 when the condition held, 0 when a bound ended the wait (w->limit = 1) */
static int
engWait(vm_address_t base, int kind, unsigned long need, unsigned long limitUs,
        osrdn_engine_wait *w)
{
    ns_time_t       t0, t1;
    unsigned long   turns = 0, maxTurns;

    maxTurns = (limitUs / E_TICK_US) * E_TURN_FACTOR + E_TURN_SLACK;
    w->evals = 0;
    w->us = 0;
    w->limit = 0;
    IOGetTimestamp(&t0);
    for (;;) {
        w->evals++;
        if (engCond(base, kind, need)) {
            IOGetTimestamp(&t1);
            w->us = engElapsedUs(t0, t1);
            return 1;
        }
        IOGetTimestamp(&t1);
        w->us = engElapsedUs(t0, t1);
        if (w->us >= limitUs)
            break;
        turns++;
        if (turns >= maxTurns)
            break;
        IODelay((unsigned)E_TICK_US);
    }
    w->limit = 1;
    return 0;
}

/* after the trigger a bound ran out: latch FIRST, in RAM, then one status word */
static int
engLatch(osrdn_engine_state *e, vm_address_t base)
{
    e->latched = 1;
    e->defaultLeft = 1;
    e->postStatus = rdnMmioRead32(base, E_RBBM_STATUS);
    return ENG_RC_POST_TIMEOUT;
}

/* ---- gate ---------------------------------------------------------------- */

static int
engRefuse(osrdn_engine_state *e, int why, unsigned long value)
{
    e->why = why;
    e->gateValue = value;
    return 0;
}

/* status first; 2D and 0x3xxx registers only once the engine is seen idle */
static int
engGate(osrdn_engine_state *e, vm_address_t base)
{
    unsigned long v, need, mem, aper;

    v = rdnMmioRead32(base, E_RBBM_STATUS);
    e->rec[ENG_REC_RBBM_STATUS] = v;
    if ((v & E_FIFO_MASK) != E_FIFO_DEPTH)
        return engRefuse(e, ENG_WHY_FIFO, v);
    if ((v & E_RBBM_ACTIVE) != 0UL)
        return engRefuse(e, ENG_WHY_ACTIVE, v);
    v = rdnMmioRead32(base, E_CP_CSQ_CNTL);
    e->rec[ENG_REC_CP_CSQ_CNTL] = v;
    if ((v & E_CSQ_MODE_MASK) != 0UL)
        return engRefuse(e, ENG_WHY_CPMODE, v);
    v = rdnMmioRead32(base, E_RB2D_DSTCACHE_CTLSTAT);
    e->rec[ENG_REC_RB2D_DC] = v;
    if ((v & E_DC_BUSY) != 0UL)
        return engRefuse(e, ENG_WHY_DC2_BUSY, v);
    v = rdnMmioRead32(base, E_RB3D_DSTCACHE_CTLSTAT);
    e->rec[ENG_REC_RB3D_DC] = v;
    if ((v & E_DC_BUSY) != 0UL)
        return engRefuse(e, ENG_WHY_DC3_BUSY, v);
    /* recorded, not refused: the batches write it to 0 first, as xf86's
       RADEONEngineInit and NetBSD's radeonfb_engine_init do (operator
       decision, docs/R4_ENGINE_PLAN.md 17; the machine read 0x1800, the
       ARGB8888 format field alone) */
    e->rec[ENG_REC_RB3D_CNTL] = rdnMmioRead32(base, E_RB3D_CNTL);
    v = rdnMmioRead32(base, E_SURFACE_CNTL);
    e->rec[ENG_REC_SURFACE_CNTL] = v;
    if ((v & E_SURF_SWAP_MASK) != 0UL)
        return engRefuse(e, ENG_WHY_SURFACE, v);
    /* the block must lie inside what the card reports: no product without
       proving it fits */
    if (e->winStart > 0xFFFFFFFFUL - ENG_ALIAS_BYTES)
        return engRefuse(e, ENG_WHY_REACH, e->winStart);
    need = e->winStart + ENG_ALIAS_BYTES;
    osrdn_engine_vram_reach(base, &mem, &aper);
    if (mem < need)
        return engRefuse(e, ENG_WHY_REACH, mem);
    if (aper < need)
        return engRefuse(e, ENG_WHY_REACH, aper);
    return 1;
}

static void
engRecord(osrdn_engine_state *e, vm_address_t base)
{
    e->rec[ENG_REC_DSTCACHE] = rdnMmioRead32(base, E_DSTCACHE_CTLSTAT);
    e->rec[ENG_REC_RB2D_DC_MODE] = rdnMmioRead32(base, E_RB2D_DSTCACHE_MODE);
    e->rec[ENG_REC_DEFAULT_OFFSET] = rdnMmioRead32(base, E_DEFAULT_OFFSET);
    e->rec[ENG_REC_DEFAULT_PITCH] = rdnMmioRead32(base, E_DEFAULT_PITCH);
    e->rec[ENG_REC_DEFAULT_SC_BR] = rdnMmioRead32(base, E_DEFAULT_SC_BR);
    e->rec[ENG_REC_SC_TOP_LEFT] = rdnMmioRead32(base, E_SC_TOP_LEFT);
    e->rec[ENG_REC_SC_BOTTOM_RIGHT] = rdnMmioRead32(base, E_SC_BOTTOM_RIGHT);
    e->rec[ENG_REC_AUX_SC_CNTL] = rdnMmioRead32(base, E_AUX_SC_CNTL);
    e->rec[ENG_REC_DP_DATATYPE] = rdnMmioRead32(base, E_DP_DATATYPE);
    e->rec[ENG_REC_GMC] = rdnMmioRead32(base, E_DP_GUI_MASTER_CNTL);
    e->rec[ENG_REC_DP_CNTL] = rdnMmioRead32(base, E_DP_CNTL);
    e->rec[ENG_REC_WRITE_MASK] = rdnMmioRead32(base, E_DP_WRITE_MASK);
    e->rec[ENG_REC_DST_PO] = rdnMmioRead32(base, E_DST_PITCH_OFFSET);
    e->rec[ENG_REC_SRC_PO] = rdnMmioRead32(base, E_SRC_PITCH_OFFSET);
    e->rec[ENG_REC_BRUSH] = rdnMmioRead32(base, E_DP_BRUSH_FRGD_CLR);
    e->rec[ENG_REC_SCLK_CNTL] = osrdn_pll_peek(base, PLLPEEK_SCLK_CNTL);
    e->rec[ENG_REC_SCLK_MORE_CNTL] = osrdn_pll_peek(base, PLLPEEK_SCLK_MORE_CNTL);
    e->rec[ENG_REC_CLK_PWRMGT_CNTL] = osrdn_pll_peek(base, PLLPEEK_CLK_PWRMGT_CNTL);
}

/* ---- the block ------------------------------------------------------------ */

/* 1 and (x, y) if byte offset off lies in the surface at soff, pitch x h */
static int
inSurface(unsigned long off, unsigned long soff, unsigned long pitch, unsigned long h,
          unsigned long *x, unsigned long *y)
{
    if (off < soff || off - soff >= pitch * h)
        return 0;
    *y = (off - soff) / pitch;
    *x = ((off - soff) % pitch) / 4UL;
    return 1;
}

static int
isGuard(unsigned long off)
{
    if (off < ENG_S0_OFF)
        return 1;
    if (off >= ENG_S0_OFF + ENG_S0_W * 4UL * ENG_S0_H && off < ENG_S1_OFF)
        return 1;
    if (off >= ENG_S1_OFF + ENG_S1_W * 4UL * ENG_S1_H && off < ENG_S2_OFF)
        return 1;
    if (off >= ENG_S2_OFF + ENG_S2_W * 4UL * ENG_S2_H && off < ENG_D_OFF)
        return 1;
    if (off >= ENG_D_OFF + ENG_D_W * 4UL * ENG_D_H)
        return 1;
    return 0;
}

static unsigned long
pattern(unsigned long x, unsigned long y)
{
    return 0xff000000UL | (y << 8) | x;
}

/* what the block holds before the operation: the marker, for a blit the
   position pattern in S1, for UBLIT the user's words in S1 */
static unsigned long
preValue(int op, unsigned long arg, unsigned long off)
{
    unsigned long x, y;

    if (op == ENG_OP_BLIT && inSurface(off, ENG_S1_OFF, S1P, ENG_S1_H, &x, &y))
        return pattern(x, y);
    if (op == ENG_OP_UBLIT && inSurface(off, ENG_S1_OFF, S1P, ENG_S1_H, &x, &y))
        return ENG_USER_VALUE(arg, off);
    return E_MARK;
}

/* 1 and the expected word if off lies in the operation's destination */
static int
destValue(int op, unsigned long arg, unsigned long off, unsigned long *want)
{
    unsigned long x, y;
    const engCase *c;

    if (op == ENG_OP_FILL) {
        if (!inSurface(off, ENG_S0_OFF, ENG_S0_W * 4UL, ENG_S0_H, &x, &y))
            return 0;
        if (x < E_FILL_X || x >= E_FILL_X + E_FILL_W || y < E_FILL_Y || y >= E_FILL_Y + E_FILL_H)
            return 0;
        *want = arg;
        return 1;
    }
    c = engCaseFor(op, arg);
    if (!inSurface(off, c->dstOff, c->dstPitch, c->dstH, &x, &y))
        return 0;
    if (x < c->dx || x >= c->dx + c->w || y < c->dy || y >= c->dy + c->h)
        return 0;
    /* the source as it was BEFORE the copy */
    *want = preValue(op, arg, c->srcOff + (c->sy + (y - c->dy)) * c->srcPitch + (c->sx + (x - c->dx)) * 4UL);
    return 1;
}

/* the byte offset of the destination rectangle's top-left pixel */
static unsigned long
destStart(int op, unsigned long arg)
{
    const engCase *c;

    if (op == ENG_OP_FILL)
        return ENG_S0_OFF + E_FILL_Y * ENG_S0_W * 4UL + E_FILL_X * 4UL;
    c = engCaseFor(op, arg);
    return c->dstOff + c->dy * c->dstPitch + c->dx * 4UL;
}

/* write the pre-operation contents, then read ALL of it back.  The read is
   also the fence: a PCI read cannot pass the posted writes before it, so the
   engine is not started until the pattern is in VRAM -- do not remove it. */
static int
engPrepare(osrdn_engine_state *e, int op, unsigned long arg)
{
    volatile unsigned long *a = (volatile unsigned long *)e->alias;
    unsigned long off, x, y, bad = 0;

    if (op == ENG_OP_UBLIT) {
        /* the whole block must hold the user's words before anything is
           written: every one of its 32 pages then lands where the alias's
           does (docs/R4C_VMAP_PLAN.md 10-2 B4) */
        for (off = 0; off < ENG_ALIAS_BYTES; off += 4UL)
            if (a[off / 4UL] != ENG_USER_VALUE(arg, off)) {
                if (bad == 0UL)
                    e->first = (long)off;
                bad++;
            }
        if (bad != 0UL)
            return engRefuse(e, ENG_WHY_USER, bad);
    }
    for (off = 0; off < ENG_ALIAS_BYTES; off += 4UL) {
        if (op == ENG_OP_UBLIT && inSurface(off, ENG_S1_OFF, S1P, ENG_S1_H, &x, &y))
            continue;                               /* the user's source stays */
        a[off / 4UL] = preValue(op, arg, off);
    }
    for (off = 0; off < ENG_ALIAS_BYTES; off += 4UL)
        if (a[off / 4UL] != preValue(op, arg, off))
            return engRefuse(e, isBlit(op) ? ENG_WHY_PATTERN : ENG_WHY_MARKER, off);
    return 1;
}

/* read the block and sort every wrong word */
static unsigned long
engJudge(osrdn_engine_state *e, int op, unsigned long arg, int count)
{
    volatile unsigned long *a = (volatile unsigned long *)e->alias;
    unsigned long off, v, want, dstart, bad = 0;

    dstart = destStart(op, arg);
    for (off = 0; off < ENG_ALIAS_BYTES; off += 4UL) {
        v = a[off / 4UL];
        if (destValue(op, arg, off, &want)) {
            if (v == want)
                continue;
            bad++;
            if (!count)
                continue;
            e->inBad++;
            if (v == preValue(op, arg, off))
                e->notBad++;
        } else {
            if (v == preValue(op, arg, off))
                continue;
            bad++;
            if (!count)
                continue;
            if (off >= ENG_D_OFF && off < ENG_D_OFF + ENG_D_W * 4UL * ENG_D_H)
                e->decoyBad++;
            else if (isGuard(off))
                e->guardBad++;
            else
                e->outBad++;
        }
        if (!count)
            continue;
        if (e->first < 0)
            e->first = (long)off;
        if (off >= dstart && off < dstart + 64UL)
            e->f64++;
    }
    return bad;
}

/* ---- the batches ----------------------------------------------------------- */

static void
engClip(vm_address_t base)
{
    rdnMmioWrite32(base, E_DEFAULT_SC_BR, E_SC_MAX);
    rdnMmioWrite32(base, E_SC_TOP_LEFT, 0UL);
    rdnMmioWrite32(base, E_SC_BOTTOM_RIGHT, E_SC_MAX);
}

static unsigned long
card(const osrdn_engine_state *e, unsigned long off)
{
    return e->winStart + off;
}

/* the decoy: DEFAULT_OFFSET points at D with its own pitch, so an engine that
   read the default register instead of DST_/SRC_PITCH_OFFSET writes D */
static unsigned long
decoy(const osrdn_engine_state *e)
{
    return osrdn_engine_pitch_offset(card(e, ENG_D_OFF), ENG_D_W * 4UL);
}

static void
engFillBatch(const osrdn_engine_state *e, vm_address_t base, unsigned long colour)
{
    rdnMmioWrite32(base, E_RB3D_CNTL, 0UL);                             /* no 3D (docs 17) */
    rdnMmioWrite32(base, E_DEFAULT_OFFSET, decoy(e));
    rdnMmioWrite32(base, E_DST_PITCH_OFFSET,
                   osrdn_engine_pitch_offset(card(e, ENG_S0_OFF), ENG_S0_W * 4UL));
    engClip(base);
    rdnMmioWrite32(base, E_DP_GUI_MASTER_CNTL, E_GMC_FILL);
    rdnMmioWrite32(base, E_DP_WRITE_MASK, 0xffffffffUL);
    rdnMmioWrite32(base, E_DP_BRUSH_FRGD_CLR, colour);
    rdnMmioWrite32(base, E_DP_CNTL, E_DIR_X_LTR | E_DIR_Y_TTB);
    rdnMmioWrite32(base, E_DST_Y_X, (E_FILL_Y << 16) | E_FILL_X);
    rdnMmioWrite32(base, E_DST_WIDTH_HEIGHT, (E_FILL_W << 16) | E_FILL_H);   /* last */
}

static void
engBlitBatch(const osrdn_engine_state *e, vm_address_t base, const engCase *c)
{
    unsigned long dir = 0, sx = c->sx, sy = c->sy, dx = c->dx, dy = c->dy;
    int ttb, ltr;

    /* NetBSD radeonfb.c 3732-3743: top-to-bottom when the destination is
       above the source, left-to-right when it is left of it */
    ttb = (c->dy < c->sy);
    ltr = (c->dx < c->sx);
    if (c->flip == 1)
        ltr = !ltr;
    if (c->flip == 2)
        ttb = !ttb;
    /* the start is the first pixel processed in the chosen direction, so a
       flipped case covers the same rectangle as the correct one */
    if (ttb)
        dir |= E_DIR_Y_TTB;
    else {
        sy += c->h - 1UL;
        dy += c->h - 1UL;
    }
    if (ltr)
        dir |= E_DIR_X_LTR;
    else {
        sx += c->w - 1UL;
        dx += c->w - 1UL;
    }
    rdnMmioWrite32(base, E_RB3D_CNTL, 0UL);                             /* no 3D (docs 17) */
    rdnMmioWrite32(base, E_DEFAULT_OFFSET, decoy(e));
    rdnMmioWrite32(base, E_SRC_PITCH_OFFSET,
                   osrdn_engine_pitch_offset(card(e, c->srcOff), c->srcPitch));
    rdnMmioWrite32(base, E_DST_PITCH_OFFSET,
                   osrdn_engine_pitch_offset(card(e, c->dstOff), c->dstPitch));
    engClip(base);
    rdnMmioWrite32(base, E_DP_GUI_MASTER_CNTL, E_GMC_BLIT);
    rdnMmioWrite32(base, E_DP_WRITE_MASK, 0xffffffffUL);
    rdnMmioWrite32(base, E_DP_CNTL, dir);
    rdnMmioWrite32(base, E_SRC_Y_X, (sy << 16) | sx);
    rdnMmioWrite32(base, E_DST_Y_X, (dy << 16) | dx);
    rdnMmioWrite32(base, E_DST_WIDTH_HEIGHT, (c->w << 16) | c->h);    /* last */
}

/* FIFO room, the batch, idle, both dest caches flushed, DEFAULT_OFFSET put
   back -- then the judgement.  Returns ENG_RC_*. */
static int
engDraw(osrdn_engine_state *e, vm_address_t base, int op, unsigned long arg)
{
    unsigned long need;

    if (op == ENG_OP_UBLIT) {
        e->lastSeed = arg;                  /* from here S1 may hold this seed's words */
        e->seedUsed = 1;
    }
    if (!engPrepare(e, op, arg))
        return ENG_RC_REFUSED;
    e->defaultSaved = rdnMmioRead32(base, E_DEFAULT_OFFSET);   /* idle: the gate saw it */
    need = (op == ENG_OP_FILL) ? E_FILL_WRITES : E_BLIT_WRITES;
    if (!engWait(base, W_FIFO, need, E_FIFO_US, &e->wFifo))
        return ENG_RC_PRE_TIMEOUT;                          /* nothing written */
    if (op == ENG_OP_FILL)
        engFillBatch(e, base, arg);
    else
        engBlitBatch(e, base, engCaseFor(op, arg));

    /* from here the engine may be writing */
    if (!engWait(base, W_IDLE, 0, E_IDLE_US, &e->wIdle))
        return engLatch(e, base);
    e->dc2Pre = rdnMmioRead32(base, E_RB2D_DSTCACHE_CTLSTAT);
    rdnMmioWrite32(base, E_RB2D_DSTCACHE_CTLSTAT, e->dc2Pre | E_DC_FLUSH_ALL);
    if (!engWait(base, W_DC2, 0, E_DC_US, &e->wDc2))
        return engLatch(e, base);
    e->dc3Pre = rdnMmioRead32(base, E_RB3D_DSTCACHE_CTLSTAT);
    rdnMmioWrite32(base, E_RB3D_DSTCACHE_CTLSTAT, e->dc3Pre | E_DC_FLUSH_ALL);
    if (!engWait(base, W_DC3, 0, E_DC_US, &e->wDc3))
        return engLatch(e, base);
    /* once more: if the flush writes went through the FIFO, BUSY could have
       been read before they started (code review 5) */
    if (!engWait(base, W_IDLE, 0, E_IDLE_US, &e->wIdle2))
        return engLatch(e, base);
    if (!engWait(base, W_FIFO, 1, E_FIFO_US, &e->wRestore))
        return engLatch(e, base);
    rdnMmioWrite32(base, E_DEFAULT_OFFSET, e->defaultSaved);

    if (engJudge(e, op, arg, 1) != 0UL) {
        IODelay((unsigned)E_REREAD_US);
        e->reread = engJudge(e, op, arg, 0);
        e->rereadDone = 1;
    }
    return ENG_RC_RAN;
}

/* ---- the entry ------------------------------------------------------------ */

int
osrdn_engine_run(osrdn_engine_state *e, vm_address_t base, int op, unsigned long arg)
{
    ns_time_t t0, t1;
    int k;

    IOGetTimestamp(&t0);
    e->ops++;
    e->op = op;
    e->arg = arg;
    e->rc = ENG_RC_REFUSED;
    e->why = ENG_WHY_NONE;
    e->gateValue = 0;
    for (k = 0; k < ENG_REC_COUNT; k++)
        e->rec[k] = 0;
    e->inBad = e->notBad = e->outBad = e->decoyBad = e->guardBad = 0;
    e->first = -1;
    e->f64 = 0;
    e->reread = 0;
    e->rereadDone = 0;
    e->wFifo.evals = e->wIdle.evals = e->wDc2.evals = e->wDc3.evals = e->wIdle2.evals = e->wRestore.evals = 0;
    e->wFifo.limit = e->wIdle.limit = e->wDc2.limit = e->wDc3.limit = e->wIdle2.limit = e->wRestore.limit = 0;
    e->dc2Pre = e->dc3Pre = 0;
    e->defaultSaved = 0;
    e->defaultLeft = 0;
    e->postStatus = 0;

    if (!e->keyOn)
        (void)engRefuse(e, ENG_WHY_KEY, 0);
    else if (e->alias == 0)
        (void)engRefuse(e, ENG_WHY_NO_ALIAS, 0);
    else if (e->latched)
        (void)engRefuse(e, ENG_WHY_LATCHED, 0);
    else if (base == 0 ||
             (op != ENG_OP_RECORD && op != ENG_OP_FILL && op != ENG_OP_BLIT && op != ENG_OP_UBLIT) ||
             (op == ENG_OP_BLIT && arg >= (unsigned long)ENG_BLIT_CASES) ||
             (op == ENG_OP_UBLIT && !engSeedOk(arg)))
        (void)engRefuse(e, ENG_WHY_BAD_OP, arg);
    else if (op == ENG_OP_FILL && arg == E_MARK)
        (void)engRefuse(e, ENG_WHY_MARK_COLOUR, arg);
    else if (op == ENG_OP_UBLIT && e->seedUsed && arg == e->lastSeed)
        (void)engRefuse(e, ENG_WHY_SEED, arg);
    else if (engGate(e, base)) {
        if (op == ENG_OP_RECORD) {
            engRecord(e, base);
            e->rc = ENG_RC_RAN;
        } else {
            e->rc = engDraw(e, base, op, arg);
        }
    }
    IOGetTimestamp(&t1);
    e->elapsedUs = engElapsedUs(t0, t1);
    return e->rc;
}
