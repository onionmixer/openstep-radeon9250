/*
 * osrdn_cp.m - see osrdn_cp.h.  Plain C89 over the RDNR2aMMIO accessors, the
 * CPU unit and the block; no log, no sleep.
 *
 * Register offsets and bits: FreeBSD radeon_drv.h (and the tables in
 * docs/R5_CP_SEQUENCE.md 3, checked against NetBSD, xf86 and Linux);
 * DIS_OUT_OF_PCI_GART_ACCESS from Linux 3.10 radeon_reg.h 3366, the only header
 * that names it.  Every value written is in docs/R5_PLAN.md 8 and 9.
 */

#import <driverkit/generalFuncs.h>      /* IODelay, IOGetTimestamp */
#import "RDNR2aMMIO.h"
#import "osrdn_snap.h"                  /* osrdn_pll_peek (SCLK_CNTL, read only) */
#import "osrdn_cpu.h"
#import "osrdn_cp.h"
#import "osrdn_cp_ucode.h"
#import "osrdn_r7b.h"                   /* G3: the present block and the request the class hands down */

/* R5d (docs/R5D_PLAN.md 7): every MMIO access this unit makes is counted, so
   the log shows what an operation touched -- a latched STOP must read "wr=1
   rd=1".  The macros keep the calls' own text (the source rules and the reloc
   gate see the same names); a function-like macro is not expanded again inside
   itself, so each one reaches the real accessor.  osrdn_pll_peek (RECORD's SCLK
   word) is another unit's and is not counted. */
static unsigned long cpIoRd, cpIoWr;
#define rdnMmioRead32(b, o)         (cpIoRd++, rdnMmioRead32((b), (o)))
#define rdnMmioWrite32(b, o, v)     (cpIoWr++, rdnMmioWrite32((b), (o), (v)))
#define rdnMmioWrite8(b, o, v)      (cpIoWr++, rdnMmioWrite8((b), (o), (v)))

/* ---- registers ------------------------------------------------------------- */
#define C_CLOCK_CNTL_INDEX      0x0008
#define C_CLOCK_CNTL_DATA       0x000c
#define C_BUS_CNTL              0x0030
#define C_GEN_INT_CNTL          0x0040
#define C_GEN_INT_STATUS        0x0044
#define C_RBBM_SOFT_RESET       0x00f0
#define C_MC_FB_LOCATION        0x0148
#define C_MC_AGP_LOCATION       0x014c
#define C_AGP_BASE_2            0x015c
#define C_AGP_BASE              0x0170
#define C_AIC_CNTL              0x01d0
#define C_AIC_STAT              0x01d4
#define C_AIC_PT_BASE           0x01d8
#define C_AIC_LO_ADDR           0x01dc
#define C_AIC_HI_ADDR           0x01e0
#define C_CP_RB_BASE            0x0700
#define C_CP_RB_CNTL            0x0704
#define C_CP_RB_RPTR_ADDR       0x070c
#define C_CP_RB_RPTR            0x0710
#define C_CP_RB_WPTR            0x0714
#define C_CP_RB_WPTR_DELAY      0x0718
#define C_CP_CSQ_CNTL           0x0740
#define C_CP_CSQ_MODE           0x0744
#define C_CP_RB_RPTR_WR         0x071c          /* M3j: Linux radeon_reg.h 3309, the read pointer forced */
#define C_RB_RPTR_WR_ENA        0x80000000UL    /* M3j: Linux radeon_reg.h 3305 */
#define C_CP_STAT               0x07c0          /* M3i: r100.c R_0007C0_CP_STAT; layout undocumented */
#define C_CP_CSQ_ADDR           0x07f0          /* M3i: Linux radeon_reg.h 3350 */
#define C_CP_CSQ_DATA           0x07f4          /* M3i: Linux radeon_reg.h 3351 */
#define C_SCRATCH_UMSK          0x0770
#define C_SCRATCH_ADDR          0x0774
#define C_CP_ME_RAM_ADDR        0x07d4
#define C_CP_ME_RAM_DATAH       0x07dc
#define C_CP_ME_RAM_DATAL       0x07e0
#define C_CP_CSQ_STAT           0x07f8
#define C_CP_CSQ2_STAT          0x07fc          /* Linux 3.10 radeon_reg.h 3349; read only, a record */
#define C_RBBM_STATUS           0x0e40
#define C_AGP_COMMAND           0x0f60
#define C_SCRATCH_REG0          0x15e0
#define C_SCRATCH_REG5          0x15f4
#define C_ISYNC_CNTL            0x1724
#define C_RB3D_DEPTHOFFSET      0x1c24
#define C_RB3D_COLOROFFSET      0x1c40
#define C_RB3D_DSTCACHE_CTLSTAT 0x325c
/* R6a (docs/R6_PLAN.md 7; FreeBSD radeon_drv.h, PP_TXMULTI_CTL_0 from Mesa r200_reg.h) */
#define C_SURFACE_CNTL          0x0b00
#define C_SE_TCL_STATE_FLUSH    0x2284
#define C_SE_VAP_CNTL_STATUS    0x2140
#define C_PP_CNTL_X             0x2cc4
#define C_PP_TXMULTI_CTL_0      0x2c1c
/* G4-7 (docs/G4_7_TRIPERF_PLAN.md 1 P2-P3): the two the reference writes 0 for every context and this
   driver never wrote -- TRI_CUTOFF (bits 0-4, "brilinear") and its companion; r200_reg.h 1074-1076 */
#define C_PP_TRI_PERF           0x2cf8
#define C_PP_PERF_CNTL          0x2cfc
/* G4-9 (docs/G4_8_REPLAY_PLAN.md 11-12): the r200 DRI's "texture cache LRU hang workaround" register -- it writes 0x6
   on R200 for every context with a texture unit on (r200_texstate.c 1577-1620); r200_reg.h 1122.  MEASURED ON THIS
   RV280 (boot 13, 2026-09-28): 0x6 makes the blend-mip stream hang the machine on its FIRST submission (0 hangs it on
   the 6th-7th).  So the prefix writes the reference's non-R200 value, 0, and the read-back keeps recording it. */
#define C_PP_TAM_DEBUG3         0x2d9c
#define C_PP_TAM_DEBUG3_LRU     0x0UL           /* was 0x6 for one boot; see above */
#define C_SE_VTX_STATE_CNTL     0x2180
#define C_RB3D_DEPTHPITCH       0x1c28
#define C_RB3D_COLORPITCH       0x1c48
#define C_RB3D_CNTL             0x1c3c
#define C_RB3D_ZSTENCILCNTL     0x1c2c          /* R6g: the second draw's compare and write bits */
#define C_RB3D_BLENDCNTL        0x1c20          /* R6j: the blend unit (docs/R6J_PLAN.md 1) */
#define C_RB3D_ZCACHE_CTLSTAT   0x3254
#define C_WAIT_UNTIL            0x1720
#define C_RE_AUX_SCISSOR_CNTL   0x26f0          /* R6k: the three auxiliary rectangles (docs/R6K_PLAN.md 1) */
#define C_RE_SCISSOR_TL_0       0x1cd8          /* the three TL/BR pairs, named one by one: a */
#define C_RE_SCISSOR_BR_0       0x1cdc          /* computed register offset never reaches the ring */
#define C_RE_SCISSOR_TL_1       0x1ce0
#define C_RE_SCISSOR_BR_1       0x1ce4
#define C_RE_SCISSOR_TL_2       0x1ce8
#define C_RE_SCISSOR_BR_2       0x1cec
#define C_RE_TOP_LEFT           0x26c0
#define C_RE_WIDTH_HEIGHT       0x1c44
#define C_RB3D_DEPTHXY_OFFSET   0x1d60          /* FreeBSD radeon_drv.h R200_RB3D_DEPTHXY_OFFSET */
/* R6c: blend stage 0 (Mesa 6.5.3 r200_reg.h 1132, 1231, 1282, 1378) */
#define C_PP_TXCBLEND_0         0x2f00
#define C_PP_TXCBLEND2_0        0x2f04
#define C_PP_TXABLEND_0         0x2f08
#define C_PP_TXABLEND2_0        0x2f0c

#define C_PLL_MCLK_CNTL         0x12
#define C_PLL_WR_EN             0x80UL
#define C_PLL_INDEX_MASK        0x3fUL

#define C_FIFO_MASK             0x7fUL
#define C_FIFO_DEPTH            64UL
#define C_RBBM_ACTIVE           0x80000000UL
#define C_CSQ_MODE_MASK         0xf0000000UL
#define C_BUS_MASTER_DIS        0x40UL          /* BUS_CNTL bit 6 */
#define C_TRANSLATE_EN          0x1UL
#define C_DIS_OUT_OF_GART       0x2UL
#define C_DC_FLUSH_ALL          0x0000000fUL
#define C_DC_BUSY               0x80000000UL
#define C_MCLK_FORCEON          0x003f0000UL    /* MCLKA MCLKB YCLKA YCLKB MC AIC */
#define C_SOFT_RESET_BITS       0x0000007fUL    /* CP HI SE RE PP E2 RB */
#define C_RPTR_MASK             (CP_RING_WORDS - 1UL)

/* the reference start stream (docs/R5_CP_SEQUENCE.md 3 table B) */
static const unsigned long cpStartStream[8] = {
    0x000005c9UL, 0x00000033UL,         /* ISYNC_CNTL */
    0x00000c97UL, 0x0000000fUL,         /* RB3D_DSTCACHE_CTLSTAT: DC_FLUSH|DC_FREE */
    0x00000c95UL, 0x00000005UL,         /* RB3D_ZCACHE_CTLSTAT: ZC_FLUSH|ZC_FREE */
    0x000005c8UL, 0x00070000UL          /* WAIT_UNTIL: 2D|3D|HOST idleclean */
};

/* waits: nominal limits in microseconds, spun in ticks of IODelay, with a turn
   cap for a clock that does not advance (the R4 rule) */
#define C_TICK_US               10UL
#define C_FIFO_US               10000UL
#define C_IDLE_US               100000UL
#define C_RPTR_US               100000UL
/* G4-3 K1: an idle wait is asked this many C_IDLE_US rounds before it is a stall -- xorg's
   RADEON_IDLE_RETRY (radeon.h 237), the count it retries the DRM's idle ioctl on EBUSY.  A batch of
   big minified triangles drew for longer than one round (docs/G4_GLQUAKE_PLAN.md 6-9: VRAM held the
   finished picture while the driver called it a stall). */
#define C_IDLE_RETRY            CP_IDLE_RETRY
#define C_KICK_US               10000UL         /* M3i D3: how long the kick waits for rptr to move */
#define C_DC_US                 10000UL
#define C_NEG_US                2000UL          /* NEGCTL: how long nothing must happen */
#define C_TURN_FACTOR           2UL
#define C_TURN_SLACK            8UL

#define W_FIFO                  1
#define W_IDLE                  2
#define W_RPTR                  3
#define W_DC                    4

/* the block's own patterns (host checkers compute the same) */
#define C_SPARE_WORD(i)         (0x5b000000UL | (i))
#define C_CANARY_WORD(i)        (0xc4000000UL | (i))

/* what the driver last wrote to each ring word: the GPU only reads the ring,
   so the ring must always equal it (plan 7-2 B11).  One copy for the one card. */
static unsigned long cpShadow[CP_RING_WORDS];
/* M2b: extra cpCond polls before each IODelay.  A file static like cpShadow and
   the MMIO counters, because cpWait is called from 21 places and threading a
   parameter through all of them would be 21 chances to get it wrong for a knob
   that is off by default.  Written only by cpSpinSet, read only by cpWait. */
static unsigned long cpSpin;

/* ---- time and waits ------------------------------------------------------- */

static unsigned long
cpElapsedUs(ns_time_t t0, ns_time_t t1)
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

static int
cpCond(vm_address_t base, int kind, unsigned long need)
{
    unsigned long v;

    switch (kind) {
    case W_FIFO:
        v = rdnMmioRead32(base, C_RBBM_STATUS);
        return (v & C_FIFO_MASK) >= need;
    case W_IDLE:
        v = rdnMmioRead32(base, C_RBBM_STATUS);
        if ((v & C_FIFO_MASK) != C_FIFO_DEPTH)
            return 0;
        return (v & C_RBBM_ACTIVE) == 0UL;
    case W_RPTR:
        return (rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK) == need;
    case W_DC:
        return (rdnMmioRead32(base, C_RB3D_DSTCACHE_CTLSTAT) & C_DC_BUSY) == 0UL;
    }
    return 0;
}

/* 1 when the condition held, 0 when a bound ended the wait (w->limit = 1) */
static int
cpWait(vm_address_t base, int kind, unsigned long need, unsigned long limitUs, osrdn_cp_wait *w)
{
    ns_time_t       t0, t1;
    unsigned long   turns = 0, maxTurns, k;

    unsigned long   last = 0UL, cur;
    int             held;
    maxTurns = (limitUs / C_TICK_US) * C_TURN_FACTOR + C_TURN_SLACK;
    w->evals = 0;
    w->turns = 0;
    w->us = 0;
    w->limit = 0;
    w->resets = 0;
    w->retries = 0;
    IOGetTimestamp(&t0);
    for (;;) {
        w->evals++;
        /*
         * G4-3 K1: A W_RPTR WAIT IS BOUNDED BY LACK OF PROGRESS, NOT BY THE CLOCK.  The reference's
         * ring wait restarts its count whenever the head moved (radeon_wait_ring, radeon_cp.c
         * 1911-1919): a CP still fetching is not stalled however long the fetch takes.  The one
         * read that decides the condition is also the progress sample, so this costs no extra
         * MMIO read over cpCond -- the latched-stop rule (world5) counts those.
         */
        if (kind == W_RPTR) {
            cur = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;
            held = (cur == need);
            if (!held && w->evals == 1UL)
                last = cur;
            else if (!held && cur != last) {
                last = cur;
                IOGetTimestamp(&t0);
                turns = 0;
                w->resets++;
            }
        } else
            held = cpCond(base, kind, need);
        if (held) {
            IOGetTimestamp(&t1);
            w->us = cpElapsedUs(t0, t1);
            return 1;
        }
        IOGetTimestamp(&t1);
        w->us = cpElapsedUs(t0, t1);
        if (w->us >= limitUs)
            break;
        turns++;
        w->turns = turns;
        if (turns >= maxTurns)
            break;
        /*
         * M2b: ask a few more times before sleeping.  One IODelay throws away
         * 10 us; one cpCond costs 0.83.  Both bounds are already behind us for
         * this turn, so this cannot make the loop skip either -- what it does
         * is lengthen the interval between two time checks by spin*0.83 us,
         * which is recorded (docs/M2B_PLAN.md 2-3 e).
         *
         * THE TIMESTAMP IS REFRESHED ON THE WAY OUT.  Returning without it
         * would leave w->us at the last FAILED evaluation, so a spinning arm
         * would report a smaller wait than it really had -- the measurement
         * flattering itself.
         */
        for (k = 0; k < cpSpin; k++) {
            w->evals++;
            if (cpCond(base, kind, need)) {
                IOGetTimestamp(&t1);
                w->us = cpElapsedUs(t0, t1);
                return 1;
            }
        }
        IODelay((unsigned)C_TICK_US);
    }
    w->limit = 1;
    return 0;
}
/*
 * G4-3 K1: the same wait, asked `rounds` times.  The reference has no progress signal for "the
 * engine is still drawing" once the CP has fetched everything, so it re-asks a whole timeout's
 * worth (xorg: RADEON_IDLE_RETRY of the DRM's 100 ms idle).  The counters are the sums over the
 * rounds, `retries` says how many rounds beyond the first it took, and `limit` is set only when
 * every round ran out.
 */
static int
cpWaitRetry(vm_address_t base, int kind, unsigned long need, unsigned long limitUs,
            unsigned long rounds, osrdn_cp_wait *w)
{
    osrdn_cp_wait   one;
    unsigned long   r, evals = 0UL, turns = 0UL, us = 0UL, resets = 0UL;
    int             ok = 0;

    for (r = 0UL; r < rounds && !ok; r++) {
        ok = cpWait(base, kind, need, limitUs, &one);
        evals += one.evals;
        turns += one.turns;
        us += one.us;
        resets += one.resets;
    }
    w->evals = evals;
    w->turns = turns;
    w->us = us;
    w->resets = resets;
    w->retries = ok ? r - 1UL : rounds;
    w->limit = ok ? 0 : 1;
    return ok;
}

/*
 * G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 1-5, 2-2): ROOM FOR `len` WORDS AT c->wptr.
 *
 * FreeBSD's radeon_wait_ring (radeon_cp.c 1901-1926): space = head - tail, plus the
 * ring size when that is <= 0, and there is room when space > n.  In words that is
 * (rptr - wptr - 1) & mask >= len -- one word always stays empty, so a full ring can
 * never read as an empty one (python: the two agree over all 4096 x 4096 pointer
 * pairs).  The clock restarts whenever rptr moves, as the reference's i = 0 and
 * cpWait's W_RPTR do: a CP that is still fetching -- at the engine's pace, G5-2 3-1 --
 * is not stalled however long the drawing takes.  An empty ring answers on the first
 * read, so a synchronous caller pays one MMIO read for this.
 */
static int
cpWaitSpace(osrdn_cp_state *c, vm_address_t base, unsigned long len)
{
    osrdn_cp_wait  *w = &c->wSpace;
    ns_time_t       t0, t1, tAll;
    unsigned long   turns = 0, maxTurns, cur, last = 0UL, room;

    maxTurns = (C_RPTR_US / C_TICK_US) * C_TURN_FACTOR + C_TURN_SLACK;
    w->evals = 0;
    w->turns = 0;
    w->us = 0;
    w->limit = 0;
    w->resets = 0;
    w->retries = 0;
    IOGetTimestamp(&t0);
    tAll = t0;
    for (;;) {
        w->evals++;
        cur = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;
        room = (cur - c->wptr - 1UL) & C_RPTR_MASK;
        if (room >= len) {
            IOGetTimestamp(&t1);
            w->us = cpElapsedUs(t0, t1);
            if (w->evals > 1UL) {
                c->spaceWaits++;
                c->spaceUs += cpElapsedUs(tAll, t1);
            }
            return 1;
        }
        if (w->evals == 1UL)
            last = cur;
        else if (cur != last) {
            last = cur;
            IOGetTimestamp(&t0);
            turns = 0;
            w->resets++;
        }
        IOGetTimestamp(&t1);
        w->us = cpElapsedUs(t0, t1);
        if (w->us >= C_RPTR_US)
            break;
        w->turns = ++turns;
        if (turns >= maxTurns)
            break;
        IODelay((unsigned)C_TICK_US);
    }
    w->limit = 1;
    return 0;
}

/* with the CP on, a bound ran out: latch FIRST, in RAM, then one status word */
static void cpFence(vm_address_t base);         /* M3i: the kick uses it before it is defined */
static int cpResetPulse(osrdn_cp_state *c, vm_address_t base);   /* M3j: the recovery uses them before they are defined */
static int cpStartCore(osrdn_cp_state *c, vm_address_t base);

static void
cpLatchDump(osrdn_cp_state *c, vm_address_t base)
{
    unsigned long k, at;
    volatile unsigned long *ring = (volatile unsigned long *)(c->block + CP_RING_OFF);  /* = cpRing(c), defined below */

    c->postStatus = rdnMmioRead32(base, C_RBBM_STATUS);
    /*
     * M3i: THE CP'S OWN ACCOUNT, as Linux reads it from a stalled CP
     * (r100.c 2920-2990: no lock, no CP stop, CSQ_ADDR rewritten per entry).
     * Reads only, plus the CSQ_ADDR selector; nothing here moves a pointer or
     * touches the GART.  The RECORD a real latch refuses stays refused -- this
     * is taken once, here, and printed from the copy.
     */
    c->cpStat = rdnMmioRead32(base, C_CP_STAT);
    c->rbRptr = rdnMmioRead32(base, C_CP_RB_RPTR);
    c->rbWptr = rdnMmioRead32(base, C_CP_RB_WPTR);
    c->csqStat = rdnMmioRead32(base, C_CP_CSQ_STAT);
    c->csq2Stat = rdnMmioRead32(base, C_CP_CSQ2_STAT);
    c->csqMode = rdnMmioRead32(base, C_CP_CSQ_MODE);
    c->csqRead = 1;
    for (k = 0; k < CP_LATCH_FIFO_WORDS; k++) {
        rdnMmioWrite32(base, C_CP_CSQ_ADDR, k << 2);
        c->fifo[k] = rdnMmioRead32(base, C_CP_CSQ_DATA);
    }
    at = ((c->rbRptr & C_RPTR_MASK) + CP_RING_WORDS - 16UL) & C_RPTR_MASK;
    c->ringNearAt = at;
    c->ringNearBad = 0;
    for (k = 0; k < CP_LATCH_RING_WORDS; k++) {
        c->ringNear[k] = ring[(at + k) & C_RPTR_MASK];
        if (c->ringNear[k] != cpShadow[(at + k) & C_RPTR_MASK])
            c->ringNearBad++;
    }
    c->latchRead = 1;
    /*
     * M3i D3: THE REFERENCE'S KICK.  r100_gpu_is_lockup (r100.c 2499-2511) does not call
     * a busy engine locked until radeon_ring_force_activity has put a NOP on the ring,
     * written WPTR again and seen whether rptr moves.  Sixteen PACKET2 at wptr -- what
     * every submission pads with -- WPTR = wptr + 16, the same fence and posting read as
     * a submission, then C_KICK_US of watching rptr.  The latch stands whatever happens:
     * this boot's CP is evidence, not a drawing engine any more.
     */
    /*
     * G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-2, 9): ONLY WHERE SIXTEEN WORDS ARE FREE.  With a
     * submission still unfetched the ring past wptr is NOT free: sixteen NOPs there would
     * overwrite words the CP has not read, or bring WPTR onto RPTR so a full ring reads as an
     * empty one.  The free count is the space wait's own, from the rptr the dump just read.
     * Without the kick kickMoved stays 0 and cpFail goes straight to the reset.
     */
    if ((((c->rbRptr & C_RPTR_MASK) - c->wptr - 1UL) & C_RPTR_MASK) < 16UL) {
        c->kickSkipped++;
        c->kickMoved = 0;
    } else {
        unsigned long p = c->wptr, kt = (p + 16UL) & C_RPTR_MASK;

        for (k = 0; k < 16UL; k++) {
            ring[(p + k) & C_RPTR_MASK] = CP_PACKET2;
            cpShadow[(p + k) & C_RPTR_MASK] = CP_PACKET2;
        }
        cpFence(base);                      /* the unconditional fence: one kick a boot, not a submission */
        rdnMmioWrite32(base, C_CP_RB_WPTR, kt);
        (void)rdnMmioRead32(base, C_CP_RB_RPTR);
        c->kickWptr = kt;
        c->kickWptrRead = rdnMmioRead32(base, C_CP_RB_WPTR) & C_RPTR_MASK;
        c->wptr = kt;
        c->wptrAfter = kt;
        (void)cpWait(base, W_RPTR, kt, C_KICK_US, &c->wKick);
        c->kickRptr = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;
        c->kickMoved = (c->kickRptr != (c->rbRptr & C_RPTR_MASK)) ? 1 : 0;
    }
}

/* a wait ran out and nothing can be done about it: the CP is evidence for the rest of the boot */
static int
cpLatch(osrdn_cp_state *c, vm_address_t base)
{
    cpLatchDump(c, base);
    if (c->inflight) {                  /* G5-2: what was accepted and not yet drawn is gone */
        c->lostInflight++;
        c->inflight = 0;
    }
    c->latched = 1;
    return CP_RC_LATCHED;
}

/*
 * M3j (docs/M3J_PLAN.md 5): A SUBMISSION'S WAIT RAN OUT -- do what the references do.
 *
 * FreeBSD's radeon_wait_ring returns -EBUSY and nothing else; the hang is met by
 * radeon_do_engine_reset (the pulse cpReset already sends verbatim) and
 * radeon_do_cp_start.  Linux forces both ring pointers to 0 through
 * CP_RB_RPTR_WR before it restarts the CP (r100.c 2552-2558), which is taken
 * here over FreeBSD's WPTR := RPTR: with the CSQ off this card reads RPTR as 0
 * whatever the CP holds (boot eae3072b), and 0/0 is what the MAP gate expects.
 * The boot-long latch that R5 chose while the card was being learnt stays as
 * the last resort only.  Whatever happens, this submission is not drawn: the
 * caller refuses it and the library draws it in software.
 */
static int
cpFail(osrdn_cp_state *c, vm_address_t base)
{
    unsigned long v;

    cpLatchDump(c, base);
    c->recoverKind = 0;
    if (c->kickMoved &&
        cpWait(base, W_RPTR, c->kickWptr, C_KICK_US, &c->wKick) &&
        cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle2))
        c->recoverKind = 1;                 /* the doorbell rung again was enough */
    else {
        rdnMmioWrite32(base, C_CP_CSQ_CNTL, 0UL);       /* Linux r100_asic_reset: stop the CP first */
        if (cpResetPulse(c, base) == CP_RC_RAN) {
            v = rdnMmioRead32(base, C_CP_RB_CNTL);
            rdnMmioWrite32(base, C_CP_RB_CNTL, v | C_RB_RPTR_WR_ENA);
            rdnMmioWrite32(base, C_CP_RB_RPTR_WR, 0UL);
            rdnMmioWrite32(base, C_CP_RB_WPTR, 0UL);
            rdnMmioWrite32(base, C_CP_RB_CNTL, v);
            c->wptr = 0;
            c->resetDone = 1;
            if (cpStartCore(c, base) == CP_RC_RAN)
                c->recoverKind = 2;
        }
    }
    /* G5-2: the kick alone waited the ring and the engine out, so an accepted submission was drawn;
       a reset or a latch threw it away */
    if (c->inflight && c->recoverKind != 1)
        c->lostInflight++;
    c->inflight = 0;
    if (c->recoverKind != 0) {
        c->recovers++;
        return CP_RC_RECOVERED;
    }
    c->latched = 1;
    return CP_RC_LATCHED;
}

/* for the gates: record why, answer "no" (0) */
static int
cpRefuse(osrdn_cp_state *c, int why, unsigned long value)
{
    c->why = why;
    c->gateValue = value;
    return 0;
}

/* for the operations: record why, answer CP_RC_REFUSED (CP_RC_RAN is 0, so a
   gate's 0 must never be returned from an operation) */
static int
cpRefused(osrdn_cp_state *c, int why, unsigned long value)
{
    (void)cpRefuse(c, why, value);
    return CP_RC_REFUSED;
}

/* ---- the PLL: MCLK_CNTL only, the way osrdn_pll_put reaches its table (the
   index is a BYTE write, so PLL_DIV_SEL in bits 8-9 is never disturbed) ------ */

static unsigned long
cpMclkGet(vm_address_t base)
{
    rdnMmioWrite8(base, C_CLOCK_CNTL_INDEX, (unsigned char)(C_PLL_MCLK_CNTL & C_PLL_INDEX_MASK));
    return rdnMmioRead32(base, C_CLOCK_CNTL_DATA);
}

static void
cpMclkPut(vm_address_t base, unsigned long value)
{
    rdnMmioWrite8(base, C_CLOCK_CNTL_INDEX,
                  (unsigned char)((C_PLL_MCLK_CNTL & C_PLL_INDEX_MASK) | C_PLL_WR_EN));
    rdnMmioWrite32(base, C_CLOCK_CNTL_DATA, value);
    rdnMmioWrite8(base, C_CLOCK_CNTL_INDEX, (unsigned char)(C_PLL_MCLK_CNTL & C_PLL_INDEX_MASK));
}

/* ---- the block ------------------------------------------------------------- */

unsigned long
osrdn_cp_pte(unsigned long phys, unsigned long e)
{
    unsigned long off;

    if (e < 4UL)
        off = CP_RING_OFF + e * CP_PAGE;
    else if (e == 4UL)
        off = CP_SPARE_OFF;
    else
        off = CP_GUARD_OFF;
    return (phys + off) & 0xfffff000UL;
}

unsigned long
osrdn_cp_marker(unsigned long seed, int k)
{
    return seed ^ (0x9e3779b9UL * (unsigned long)(k + 1));
}

/* the word the block holds at byte offset off outside the ring, as MAP writes it */
static unsigned long
cpBlockWord(const osrdn_cp_state *c, unsigned long off)
{
    unsigned long i;

    if (off < CP_GUARD_OFF)
        return osrdn_cp_pte(c->phys, off / 4UL);
    if (off < CP_SPARE_OFF)
        return ((off / 4UL) & 1UL) ? CP_PACKET2 : CP_GUARD_HEAD;
    if (off < CP_RING_OFF) {
        i = (off - CP_SPARE_OFF) / 4UL;
        return C_SPARE_WORD(i);
    }
    i = (off - CP_CANARY_OFF) / 4UL;
    return C_CANARY_WORD(i);
}

static volatile unsigned long *
cpRing(const osrdn_cp_state *c)
{
    return (volatile unsigned long *)(c->block + CP_RING_OFF);
}

/* compare everything outside the ring with what MAP wrote; the ring with the
   shadow the driver keeps in the ring itself is the CPU's own view, so it is
   compared with the guard pattern only where nothing was written yet
   (ringBad counts words that are neither) */
/*
 * M1y (docs/M1Y_PLAN.md 8): four region loops, not one word loop.
 *
 * This ran once per submission over all 16,384 words and was MEASURED at
 * 153.5 us -- 31% of the kernel operation (docs/M1X_PLAN.md).  The cost was not
 * the comparisons: it was calling cpBlockWord() for each of the 12,288 non-ring
 * words, which branches four ways and, in the table, calls osrdn_cp_pte() again.
 *
 * NOT ONE COMPARISON IS REMOVED.  Every word is still read exactly once, in the
 * same order, and measured against the same expected value -- the expectation is
 * just carried in the loop instead of recomputed from the offset.  The seven
 * outputs (tableBad, guardBad, spareBad, canaryBad, pteSum, pteXor, ringBad) must
 * be bit-identical to what the word loop produced for every block content; that
 * is what tools/r5/sim/world5.c's adversarial blocks check, against a model
 * written from the layout rather than from this code.
 *
 * The expectations, from cpBlockWord above:
 *   table  [0, CP_GUARD_OFF)       osrdn_cp_pte(phys, e): FOUR values for e < 4,
 *                                  one for e == 4, and ONE for all 2,043 others
 *   guard  [CP_GUARD_OFF, SPARE)   CP_GUARD_HEAD / CP_PACKET2 by the ABSOLUTE
 *                                  word index's parity, as cpBlockWord uses off/4
 *   spare  [CP_SPARE_OFF, RING)    C_SPARE_WORD of the region-relative index
 *   ring   [CP_RING_OFF, CANARY)   skipped here; the shadow compare below has it
 *   canary [CP_CANARY_OFF, END)    C_CANARY_WORD of the region-relative index
 */
static unsigned long
cpCheckBlock(osrdn_cp_state *c)
{
    volatile unsigned long *b = (volatile unsigned long *)c->block;
    volatile unsigned long *r = cpRing(c);
    unsigned long i, v, sum = 0, xr = 0, bad, want;

    /* the table: every word accumulates into pteSum/pteXor whether it matches or
       not, exactly as the word loop did before its comparison */
    bad = 0;
    for (i = 0; i < 4UL; i++) {                 /* the four ring pages */
        v = b[i];
        sum += v;
        xr ^= v;
        if (v != ((c->phys + CP_RING_OFF + i * CP_PAGE) & 0xfffff000UL))
            bad++;
    }
    v = b[4];                                   /* the spare page */
    sum += v;
    xr ^= v;
    if (v != ((c->phys + CP_SPARE_OFF) & 0xfffff000UL))
        bad++;
    want = (c->phys + CP_GUARD_OFF) & 0xfffff000UL;     /* every entry above 4 */
    for (i = 5UL; i < CP_GUARD_OFF / 4UL; i++) {
        v = b[i];
        sum += v;
        xr ^= v;
        if (v != want)
            bad++;
    }
    c->tableBad = bad;
    c->pteSum = sum;
    c->pteXor = xr;

    bad = 0;
    for (i = CP_GUARD_OFF / 4UL; i < CP_SPARE_OFF / 4UL; i++)
        if (b[i] != ((i & 1UL) ? CP_PACKET2 : CP_GUARD_HEAD))
            bad++;
    c->guardBad = bad;

    bad = 0;
    for (i = 0; i < (CP_RING_OFF - CP_SPARE_OFF) / 4UL; i++)
        if (b[CP_SPARE_OFF / 4UL + i] != C_SPARE_WORD(i))
            bad++;
    c->spareBad = bad;

    bad = 0;
    for (i = 0; i < (CP_BLOCK_BYTES - CP_CANARY_OFF) / 4UL; i++)
        if (b[CP_CANARY_OFF / 4UL + i] != C_CANARY_WORD(i))
            bad++;
    c->canaryBad = bad;

    bad = 0;                                    /* the ring against the shadow */
    for (i = 0; i < CP_RING_WORDS; i++)
        if (r[i] != cpShadow[i])
            bad++;
    c->ringBad = bad;

    return c->tableBad + c->guardBad + c->spareBad + c->canaryBad + c->ringBad;
}

/* write the whole block as MAP wants it, then read it all back */
static int
cpFillBlock(osrdn_cp_state *c)
{
    volatile unsigned long *b = (volatile unsigned long *)c->block;
    volatile unsigned long *r = cpRing(c);
    unsigned long off, k;

    for (off = 0; off < CP_BLOCK_BYTES; off += 4UL)
        if (off < CP_RING_OFF || off >= CP_RING_OFF + CP_RING_BYTES)
            b[off / 4UL] = cpBlockWord(c, off);
    for (k = 0; k < CP_RING_WORDS; k++) {
        r[k] = (k & 1UL) ? CP_PACKET2 : CP_GUARD_HEAD;
        cpShadow[k] = r[k];
    }
    for (k = 0; k < CP_RING_WORDS; k++)
        if (r[k] != ((k & 1UL) ? CP_PACKET2 : CP_GUARD_HEAD))
            return cpRefuse(c, CP_WHY_BLOCK, CP_RING_OFF + k * 4UL);
    if (cpCheckBlock(c) != 0UL)
        return cpRefuse(c, CP_WHY_BLOCK, c->tableBad);
    return 1;
}

/* the CPU's writes to the block reach memory before the GPU is told to look */
static void
cpFence(vm_address_t base)
{
    osrdn_cpu_wbinvd();
    osrdn_cpu_serialize();
    (void)rdnMmioRead32(base, C_RBBM_STATUS);
}

/*
 * M2a (docs/M2A_PLAN.md): the SUBMISSION path's fence, and only that path's.
 *
 * Every reference does a memory barrier here and no CPU cache operation at all:
 * radeon_commit_ring pads, calls DRM_MEMORYBARRIER(), writes WPTR and reads RPTR
 * back for posting (radeon_cp.c:2094-2130).  It can, because the PCI GART leaves
 * its entries snooped -- ati_pcigart.c adds flag bits for IGP and PCIe and none
 * at all for plain PCI, which is what osrdn_cp_pte builds.
 *
 * osrdn_cpu_serialize IS that barrier (a locked xchg).  So the only difference
 * between this and upstream is the WBINVD, and on this machine that instruction
 * was measured at 94.46 us a submission.
 *
 * WHAT THE REFERENCES CANNOT SHOW is whether this machine's IOMallocLow memory
 * really takes part in that snooping -- Linux establishes its pages with
 * pci_map_page(..., PCI_DMA_BIDIRECTIONAL) and this driver calls no such API.
 * Only the machine could answer, and it has: two runs in one boot saved 221 and
 * 227 us a submission with the picture identical word for word, so M2e made the
 * SKIP the default.  c->doWb is 1 only when someone asks for the old behaviour
 * with `nowb 0`; the zeroed state is the fast one, which is why the sense of
 * this flag is "do it" and not "skip it".  The six other cpFence call sites are
 * untouched.
 */
static void
cpSubmitFence(osrdn_cp_state *c, vm_address_t base)
{
    if (c->doWb)
        osrdn_cpu_wbinvd();
    osrdn_cpu_serialize();
    (void)rdnMmioRead32(base, C_RBBM_STATUS);
}

/* ---- gates ------------------------------------------------------------------ */

/* status first; GUI registers only once the engine is seen idle */
static int
cpIdleGate(osrdn_cp_state *c, vm_address_t base, int wantCsqOff)
{
    unsigned long v;

    v = rdnMmioRead32(base, C_RBBM_STATUS);
    if ((v & C_FIFO_MASK) != C_FIFO_DEPTH)
        return cpRefuse(c, CP_WHY_FIFO, v);
    if ((v & C_RBBM_ACTIVE) != 0UL)
        return cpRefuse(c, CP_WHY_ACTIVE, v);
    v = rdnMmioRead32(base, C_CP_CSQ_CNTL);
    if (wantCsqOff && (v & C_CSQ_MODE_MASK) != 0UL)
        return cpRefuse(c, CP_WHY_CPMODE, v);
    return 1;
}

/* every register MAP wrote, read back (plan 7-2 B14), all of them on every call
   so one boot answers for all (docs/R5_PLAN.md 12-5 G1); the order of the reads
   is the order of the old gate's */
static const unsigned long cpMgReg[CP_MG_COUNT] = {
    C_CP_RB_CNTL, C_SCRATCH_UMSK, C_AIC_PT_BASE, C_AIC_LO_ADDR, C_AIC_HI_ADDR,
    C_AIC_CNTL, C_CP_RB_BASE, C_CP_RB_RPTR_ADDR, C_CP_RB_RPTR, C_CP_RB_WPTR,
    C_GEN_INT_CNTL, C_MC_AGP_LOCATION, C_SCRATCH_REG5,
    C_AGP_COMMAND, C_AIC_STAT                   /* record only */
};

/* AIC_HI_ADDR: the value written, or it with its low k bits cleared, k <= 12 --
   a register that keeps fewer low bits (12-5 G2).  The window then ends inside
   the last GART page, the guard's; anything else is refused and logged. */
static int
cpHiOk(unsigned long v)
{
    unsigned long want = CP_GART_BASE + CP_GART_BYTES - 1UL;
    int k;

    for (k = 0; k <= 12; k++)
        if (v == (want & ~((1UL << k) - 1UL)))
            return 1;
    return 0;
}

static int
cpMapGate(osrdn_cp_state *c, vm_address_t base, int why)
{
    unsigned long *m = c->mg, bad = 0;
    int k;

    for (k = 0; k < CP_MG_COUNT; k++)
        m[k] = rdnMmioRead32(base, cpMgReg[k]);
    if (m[CP_MG_RB_CNTL] != CP_RB_CNTL_VALUE)
        bad |= 1UL << CP_MG_RB_CNTL;
    if (m[CP_MG_UMSK] != 0UL)
        bad |= 1UL << CP_MG_UMSK;
    if (m[CP_MG_PT_BASE] != c->phys + CP_TABLE_OFF)
        bad |= 1UL << CP_MG_PT_BASE;
    if (m[CP_MG_LO] != CP_GART_BASE)
        bad |= 1UL << CP_MG_LO;
    if (!cpHiOk(m[CP_MG_HI]))
        bad |= 1UL << CP_MG_HI;
    if ((m[CP_MG_AIC_CNTL] & (C_TRANSLATE_EN | C_DIS_OUT_OF_GART)) != (C_TRANSLATE_EN | C_DIS_OUT_OF_GART))
        bad |= 1UL << CP_MG_AIC_CNTL;
    if (m[CP_MG_RB_BASE] != CP_GART_BASE)
        bad |= 1UL << CP_MG_RB_BASE;
    if (m[CP_MG_RPTR_ADDR] != CP_RPTR_GPU)
        bad |= 1UL << CP_MG_RPTR_ADDR;
    if ((m[CP_MG_RPTR] & C_RPTR_MASK) != c->wptr)
        bad |= 1UL << CP_MG_RPTR;
    if ((m[CP_MG_WPTR] & C_RPTR_MASK) != c->wptr)
        bad |= 1UL << CP_MG_WPTR;
    if (m[CP_MG_INT_CNTL] != 0UL)
        bad |= 1UL << CP_MG_INT_CNTL;
    if (m[CP_MG_AGP_LOCATION] != CP_AGP_OFF)
        bad |= 1UL << CP_MG_AGP_LOCATION;
    if (m[CP_MG_REG5] != CP_REG5_POISON)
        bad |= 1UL << CP_MG_REG5;
    c->mgDone = 1;
    c->mgBad = bad;
    if (bad == 0UL)
        return 1;
    for (k = 0; k < CP_MG_JUDGED; k++)
        if (bad & (1UL << k))
            break;
    c->gateReg = cpMgReg[k];
    return cpRefuse(c, k == CP_MG_REG5 ? CP_WHY_POISON : why, m[k]);
}

/* ---- operations --------------------------------------------------------------- */

/* status first; the rest only once the GUI is seen idle (the R4 rule) */
static int
cpRecord(osrdn_cp_state *c, vm_address_t base)
{
    unsigned long *r = c->rec;

    r[CP_REC_RBBM_STATUS] = rdnMmioRead32(base, C_RBBM_STATUS);
    if ((r[CP_REC_RBBM_STATUS] & C_FIFO_MASK) != C_FIFO_DEPTH)
        return cpRefused(c, CP_WHY_FIFO, r[CP_REC_RBBM_STATUS]);
    if ((r[CP_REC_RBBM_STATUS] & C_RBBM_ACTIVE) != 0UL)
        return cpRefused(c, CP_WHY_ACTIVE, r[CP_REC_RBBM_STATUS]);
    r[CP_REC_CSQ_CNTL] = rdnMmioRead32(base, C_CP_CSQ_CNTL);
    r[CP_REC_CSQ_MODE] = rdnMmioRead32(base, C_CP_CSQ_MODE);
    r[CP_REC_CSQ_STAT] = rdnMmioRead32(base, C_CP_CSQ_STAT);
    r[CP_REC_RB_BASE] = rdnMmioRead32(base, C_CP_RB_BASE);
    r[CP_REC_RB_CNTL] = rdnMmioRead32(base, C_CP_RB_CNTL);
    r[CP_REC_RB_RPTR] = rdnMmioRead32(base, C_CP_RB_RPTR);
    r[CP_REC_RB_WPTR] = rdnMmioRead32(base, C_CP_RB_WPTR);
    r[CP_REC_RB_RPTR_ADDR] = rdnMmioRead32(base, C_CP_RB_RPTR_ADDR);
    r[CP_REC_RB_WPTR_DELAY] = rdnMmioRead32(base, C_CP_RB_WPTR_DELAY);
    r[CP_REC_SCRATCH_UMSK] = rdnMmioRead32(base, C_SCRATCH_UMSK);
    r[CP_REC_SCRATCH_ADDR] = rdnMmioRead32(base, C_SCRATCH_ADDR);
    r[CP_REC_SCRATCH_REG0] = rdnMmioRead32(base, C_SCRATCH_REG0);
    r[CP_REC_SCRATCH_REG1] = rdnMmioRead32(base, C_SCRATCH_REG0 + 4);
    r[CP_REC_SCRATCH_REG2] = rdnMmioRead32(base, C_SCRATCH_REG0 + 8);
    r[CP_REC_SCRATCH_REG5] = rdnMmioRead32(base, C_SCRATCH_REG5);
    r[CP_REC_AIC_CNTL] = rdnMmioRead32(base, C_AIC_CNTL);
    r[CP_REC_AIC_STAT] = rdnMmioRead32(base, C_AIC_STAT);
    r[CP_REC_AIC_PT_BASE] = rdnMmioRead32(base, C_AIC_PT_BASE);
    r[CP_REC_AIC_LO] = rdnMmioRead32(base, C_AIC_LO_ADDR);
    r[CP_REC_AIC_HI] = rdnMmioRead32(base, C_AIC_HI_ADDR);
    r[CP_REC_MC_AGP_LOCATION] = rdnMmioRead32(base, C_MC_AGP_LOCATION);
    r[CP_REC_AGP_BASE] = rdnMmioRead32(base, C_AGP_BASE);
    r[CP_REC_AGP_BASE_2] = rdnMmioRead32(base, C_AGP_BASE_2);
    r[CP_REC_BUS_CNTL] = rdnMmioRead32(base, C_BUS_CNTL);
    r[CP_REC_ISYNC_CNTL] = rdnMmioRead32(base, C_ISYNC_CNTL);
    r[CP_REC_GEN_INT_CNTL] = rdnMmioRead32(base, C_GEN_INT_CNTL);
    r[CP_REC_GEN_INT_STATUS] = rdnMmioRead32(base, C_GEN_INT_STATUS);
    r[CP_REC_RB3D_COLOROFFSET] = rdnMmioRead32(base, C_RB3D_COLOROFFSET);
    r[CP_REC_RB3D_DEPTHOFFSET] = rdnMmioRead32(base, C_RB3D_DEPTHOFFSET);
    r[CP_REC_ME_RAM_ADDR] = rdnMmioRead32(base, C_CP_ME_RAM_ADDR);
    r[CP_REC_MC_FB_LOCATION] = rdnMmioRead32(base, C_MC_FB_LOCATION);
    if (c->latched) {
        /* after a latch nothing but CSQ_CNTL is written -- not even the PLL
           index byte a read would need */
        r[CP_REC_SCLK_CNTL] = 0xffffffffUL;
        r[CP_REC_MCLK_CNTL] = 0xffffffffUL;
    } else {
        unsigned long idx;

        r[CP_REC_SCLK_CNTL] = osrdn_pll_peek(base, PLLPEEK_SCLK_CNTL);
        idx = rdnMmioRead32(base, C_CLOCK_CNTL_INDEX);
        r[CP_REC_MCLK_CNTL] = (idx & C_PLL_WR_EN) ? 0xffffffffUL : cpMclkGet(base);
        rdnMmioWrite8(base, C_CLOCK_CNTL_INDEX, (unsigned char)(idx & 0xffUL));
    }
    r[CP_REC_RBBM_SOFT_RESET] = rdnMmioRead32(base, C_RBBM_SOFT_RESET);
    r[CP_REC_AGP_COMMAND] = rdnMmioRead32(base, C_AGP_COMMAND);
    return CP_RC_RAN;
}

static int
cpLoad(osrdn_cp_state *c, vm_address_t base)
{
    int k;

    if (c->state != CP_ST_NONE)
        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);
    if (!cpIdleGate(c, base, 1))
        return CP_RC_REFUSED;
    rdnMmioWrite32(base, C_CP_ME_RAM_ADDR, 0UL);
    for (k = 0; k < OSRDN_CP_UCODE_PAIRS; k++) {
        rdnMmioWrite32(base, C_CP_ME_RAM_DATAH, osrdnCpUcode[k][1]);
        rdnMmioWrite32(base, C_CP_ME_RAM_DATAL, osrdnCpUcode[k][0]);
    }
    c->state = CP_ST_LOADED;
    return CP_RC_RAN;
}

/* translation off (bit 1 kept, KMS r100_pci_gart_disable), window zeroed, the
   AGP aperture put back -- only when nothing can be fetching (plan 7-1 E1) */
static void
cpUnmap(osrdn_cp_state *c, vm_address_t base)
{
    unsigned long v;

    v = rdnMmioRead32(base, C_AIC_CNTL);
    rdnMmioWrite32(base, C_AIC_CNTL, (v | C_DIS_OUT_OF_GART) & ~C_TRANSLATE_EN);
    rdnMmioWrite32(base, C_AIC_LO_ADDR, 0UL);
    rdnMmioWrite32(base, C_AIC_HI_ADDR, 0UL);
    if (c->agpSaved) {
        rdnMmioWrite32(base, C_MC_AGP_LOCATION, c->agpLocation);
        rdnMmioWrite32(base, C_AGP_COMMAND, c->agpCommand);
        c->agpSaved = 0;
    }
}

static int
cpMap(osrdn_cp_state *c, vm_address_t base)
{
    unsigned long v, rp;

    if (c->state != CP_ST_LOADED)
        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);
    if (!cpIdleGate(c, base, 1))
        return CP_RC_REFUSED;
    v = rdnMmioRead32(base, C_BUS_CNTL);                /* read only: R1 measured it clear */
    if ((v & C_BUS_MASTER_DIS) != 0UL)
        return cpRefused(c, CP_WHY_BUSMASTER, v);
    /* a card this boot's reset did not clear would hand MAP our own AGP value
       as "the original" (docs/R5D_PLAN.md 6 M1c): refuse, nothing written */
    if ((v = rdnMmioRead32(base, C_MC_AGP_LOCATION)) == CP_AGP_OFF)
        return cpRefused(c, CP_WHY_NOT_FRESH, v);
    if (((v = rdnMmioRead32(base, C_AIC_CNTL)) & C_TRANSLATE_EN) != 0UL)
        return cpRefused(c, CP_WHY_NOT_FRESH, v);
    if (!cpFillBlock(c))
        return CP_RC_REFUSED;
    cpFence(base);

    /* D3: the AGP aperture out of the window's way (FreeBSD radeon_set_pcigart) */
    c->agpLocation = rdnMmioRead32(base, C_MC_AGP_LOCATION);
    c->agpCommand = rdnMmioRead32(base, C_AGP_COMMAND);
    c->agpSaved = 1;
    rdnMmioWrite32(base, C_MC_AGP_LOCATION, CP_AGP_OFF);
    rdnMmioWrite32(base, C_AGP_COMMAND, 0UL);

    /* the GART, in KMS r100_pci_gart_enable's order: discard out-of-range
       requests, range, table, then translation */
    v = rdnMmioRead32(base, C_AIC_CNTL);
    rdnMmioWrite32(base, C_AIC_CNTL, v | C_DIS_OUT_OF_GART);
    rdnMmioWrite32(base, C_AIC_LO_ADDR, CP_GART_BASE);
    rdnMmioWrite32(base, C_AIC_HI_ADDR, CP_GART_BASE + CP_GART_BYTES - 1UL);
    rdnMmioWrite32(base, C_AIC_PT_BASE, c->phys + CP_TABLE_OFF);
    v = rdnMmioRead32(base, C_AIC_CNTL);
    rdnMmioWrite32(base, C_AIC_CNTL, v | C_TRANSLATE_EN);

    /* the ring, in FreeBSD radeon_cp_init_ring_buffer's order, writeback OFF */
    rdnMmioWrite32(base, C_CP_RB_BASE, CP_GART_BASE);
    rdnMmioWrite32(base, C_CP_RB_WPTR_DELAY, 0UL);
    rp = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;
    rdnMmioWrite32(base, C_CP_RB_WPTR, rp);
    c->wptr = rp;
    rdnMmioWrite32(base, C_CP_RB_RPTR_ADDR, CP_RPTR_GPU);
    rdnMmioWrite32(base, C_CP_RB_CNTL, CP_RB_CNTL_VALUE);
    rdnMmioWrite32(base, C_SCRATCH_ADDR, CP_SCRATCH_GPU);
    rdnMmioWrite32(base, C_SCRATCH_UMSK, 0UL);
    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle)) {
        cpUnmap(c, base);               /* CSQ is off: nothing is fetching */
        return CP_RC_POST;
    }
    rdnMmioWrite32(base, C_ISYNC_CNTL, CP_ISYNC_VALUE);
    if (!cpWait(base, W_FIFO, 1, C_FIFO_US, &c->wFifo)) {
        cpUnmap(c, base);
        return CP_RC_POST;
    }
    rdnMmioWrite32(base, C_SCRATCH_REG5, CP_REG5_POISON);
    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle2)) {
        cpUnmap(c, base);
        return CP_RC_POST;
    }
    if (!cpMapGate(c, base, CP_WHY_MAPGATE)) {
        cpUnmap(c, base);
        return CP_RC_POST;
    }
    c->state = CP_ST_MAPPED;
    return CP_RC_RAN;
}

/* FreeBSD radeon_do_engine_reset, verbatim in order (plan 9-1; prohibition 2:
   nothing inserted between the writes) */
static int
cpResetPulse(osrdn_cp_state *c, vm_address_t base)
{
    unsigned long v, idx, mclk, soft;

    /* radeon_do_engine_reset, verbatim (docs/R5_PLAN.md 9-1 D4); M3j: shared with cpFail */
    /* radeon_do_pixcache_flush */
    v = rdnMmioRead32(base, C_RB3D_DSTCACHE_CTLSTAT);
    rdnMmioWrite32(base, C_RB3D_DSTCACHE_CTLSTAT, v | C_DC_FLUSH_ALL);
    if (!cpWait(base, W_DC, 0, C_DC_US, &c->wDc))
        return CP_RC_POST;              /* the flush was written, the pulse was not */
    idx = rdnMmioRead32(base, C_CLOCK_CNTL_INDEX);
    mclk = cpMclkGet(base);
    c->indexBefore = idx;
    c->mclkBefore = mclk;
    cpMclkPut(base, mclk | C_MCLK_FORCEON);
    soft = rdnMmioRead32(base, C_RBBM_SOFT_RESET);
    c->softBefore = soft;
    rdnMmioWrite32(base, C_RBBM_SOFT_RESET, soft | C_SOFT_RESET_BITS);
    (void)rdnMmioRead32(base, C_RBBM_SOFT_RESET);
    rdnMmioWrite32(base, C_RBBM_SOFT_RESET, soft & ~C_SOFT_RESET_BITS);
    (void)rdnMmioRead32(base, C_RBBM_SOFT_RESET);
    cpMclkPut(base, mclk);
    rdnMmioWrite32(base, C_CLOCK_CNTL_INDEX, idx);
    rdnMmioWrite32(base, C_RBBM_SOFT_RESET, soft);
    return CP_RC_RAN;
}

static int
cpReset(osrdn_cp_state *c, vm_address_t base)
{
    unsigned long idx, mclk, rp;
    int rc;

    if (c->state != CP_ST_MAPPED || c->resetDone)
        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);
    if (!cpIdleGate(c, base, 1))
        return CP_RC_REFUSED;
    if (!cpWait(base, W_FIFO, 1, C_FIFO_US, &c->wFifo))
        return CP_RC_PRE_TIMEOUT;
    if ((rc = cpResetPulse(c, base)) != CP_RC_RAN)
        return rc;
    idx = c->indexBefore;
    mclk = c->mclkBefore;
    /* radeon_do_cp_reset */
    rp = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;
    rdnMmioWrite32(base, C_CP_RB_WPTR, rp);
    c->wptr = rp;
    c->resetDone = 1;

    /* outside the window: what it left, for the log (prohibition 9) */
    c->mclkForced = mclk | C_MCLK_FORCEON;
    c->mclkAfter = cpMclkGet(base);
    rdnMmioWrite8(base, C_CLOCK_CNTL_INDEX, (unsigned char)(idx & 0xffUL));
    c->indexAfter = rdnMmioRead32(base, C_CLOCK_CNTL_INDEX);
    c->softAfter = rdnMmioRead32(base, C_RBBM_SOFT_RESET);
    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle))
        return CP_RC_POST;          /* the pulse happened (resetDone): STOP unmaps cleanly */
    if (!cpMapGate(c, base, CP_WHY_RESETGATE))
        return CP_RC_POST;          /* still MAPPED, CSQ off: STOP unmaps cleanly */
    return CP_RC_RAN;
}

/*
 * M1x: one checkpoint.  `mark` is the index of the interval that ENDS here, so
 * cpTMark(c, t, 0) closes the gates' interval and starts the preamble's.
 *
 * It uses the existing cpElapsedUs, which already handles the 64-bit subtract,
 * the 32-bit clamp and the cc 2.7.2.1 long-long comparison bug -- nothing new
 * is computed here.  The accumulation is why this can run under `quiet`: the
 * log costs about 1,085 us a submission and would treble what is measured.
 */
static void
cpTMark(osrdn_cp_state *c, ns_time_t *t, int mark)
{
    ns_time_t now;

    /* M1z: CP_T_CHAIN, not CP_T_STAGES.  The two accumulators above the chain
       are not checkpoints, and a chain mark that landed on one would add a walk's
       interval to a total gathered somewhere else entirely. */
    if (mark < 0 || mark >= CP_T_CHAIN)
        return;
    IOGetTimestamp(&now);
    c->tAcc[mark] += cpElapsedUs(*t, now);
    *t = now;
}

/* ring word k (mod the ring) */
static void
cpPut(osrdn_cp_state *c, unsigned long k, unsigned long v)
{
    cpRing(c)[k & C_RPTR_MASK] = v;
    cpShadow[k & C_RPTR_MASK] = v;
}

/* what the CP must see before it runs anything more: REG5 still the poison */
static int
cpPoisonHolds(osrdn_cp_state *c, vm_address_t base)
{
    c->reg5 = rdnMmioRead32(base, C_SCRATCH_REG5);
    return c->reg5 == CP_REG5_POISON;
}

static int
cpStart(osrdn_cp_state *c, vm_address_t base)
{
    if (c->state != CP_ST_MAPPED)
        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);
    if (!c->resetDone)
        return cpRefused(c, CP_WHY_NO_RESET, 0);
    if (!cpIdleGate(c, base, 1))
        return CP_RC_REFUSED;
    if (!cpMapGate(c, base, CP_WHY_MAPGATE))
        return CP_RC_REFUSED;
    return cpStartCore(c, base);
}

/* radeon_do_cp_start: the stream, CSQ on, then the R5 waits and checks (M3j: also the recovery's restart) */
static int
cpStartCore(osrdn_cp_state *c, vm_address_t base)
{
    unsigned long k, target;

    for (k = 0; k < 8UL; k++)
        cpPut(c, c->wptr + k, cpStartStream[k]);
    for (k = 8; k < 16UL; k++)
        cpPut(c, c->wptr + k, CP_PACKET2);
    cpFence(base);
    c->rptrBefore = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;
    rdnMmioWrite32(base, C_CP_CSQ_CNTL, CP_CSQ_ON);
    c->state = CP_ST_RUNNING;               /* from here the CP may be fetching */
    target = (c->wptr + 16UL) & C_RPTR_MASK;
    rdnMmioWrite32(base, C_CP_RB_WPTR, target);
    (void)rdnMmioRead32(base, C_CP_RB_RPTR);    /* posting, radeon_commit_ring */
    c->wptr = target;
    c->wptrAfter = target;
    /* M3i: did the doorbell take?  A lost WPTR write looks exactly like the
       latches M3c-M3h met (rptr at the submission start, CP idle). */
    c->wptrRead = rdnMmioRead32(base, C_CP_RB_WPTR) & C_RPTR_MASK;
    if (c->wptrRead != target) {
        (void)cpRefuse(c, CP_WHY_WPTR, c->wptrRead);
        return cpLatch(c, base);
    }
    if (!cpWait(base, W_RPTR, target, C_RPTR_US, &c->wRptr))
        return cpLatch(c, base);            /* a START that does not run: nothing to recover into */
    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle))
        return cpLatch(c, base);
    c->rptrAfter = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;
    /* REG5 unchanged: the CP read only what it was given (plan 8) */
    if (!cpPoisonHolds(c, base) || cpCheckBlock(c) != 0UL) {
        c->failed = 1;
        return CP_RC_CHECK_FAILED;
    }
    return CP_RC_RAN;
}

/* SUBMIT's words: REG0 at the start, REG2 at the end, REG1 straddling the first
   1 KiB ring boundary strictly inside, the rest PACKET2 (plan 7-2 B4) */
static void
cpBuild(osrdn_cp_state *c, unsigned long len)
{
    unsigned long p = c->wptr, k, b;

    for (k = 0; k < len; k++)
        cpPut(c, p + k, CP_PACKET2);
    cpPut(c, p, C_SCRATCH_REG0 >> 2);
    cpPut(c, p + 1UL, c->marker[0]);
    cpPut(c, p + len - 2UL, (C_SCRATCH_REG0 + 8) >> 2);
    cpPut(c, p + len - 1UL, c->marker[2]);
    c->straddle = 0;
    c->boundary = 0;
    b = (p / 1024UL + 1UL) * 1024UL;            /* the first boundary after p */
    if (b - 1UL >= p + 2UL && b + 1UL <= p + len - 3UL) {
        cpPut(c, b - 1UL, (C_SCRATCH_REG0 + 4) >> 2);   /* header on one page */
        cpPut(c, b, c->marker[1]);                      /* data on the next */
        c->straddle = 1;
        c->boundary = b & C_RPTR_MASK;
    } else {
        cpPut(c, p + 2UL, (C_SCRATCH_REG0 + 4) >> 2);
        cpPut(c, p + 3UL, c->marker[1]);
    }
}

/* the part SUBMIT and NEGCTL share: gates, sentinels, markers, the words.
   CP_RC_RAN when prepared, otherwise the operation's result */
static int
cpPrepare(osrdn_cp_state *c, vm_address_t base, unsigned long seed, unsigned long len)
{
    unsigned long rp;
    int k;

    if (c->state != CP_ST_RUNNING)
        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);
    if (c->failed)
        return cpRefused(c, CP_WHY_FAILED, 0);
    if (len < 16UL || len > CP_RING_WORDS - 16UL || (len & 15UL) != 0UL)
        return cpRefused(c, CP_WHY_LEN, len);
    if (seed == 0UL || (c->seedUsed && seed == c->lastSeed))
        return cpRefused(c, CP_WHY_SEED, seed);
    if (!cpIdleGate(c, base, 0))
        return CP_RC_REFUSED;
    rp = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;
    c->rptrBefore = rp;
    if (rp != c->wptr)
        return cpRefused(c, CP_WHY_NOT_CAUGHT_UP, rp);
    if (!cpPoisonHolds(c, base))
        return cpRefused(c, CP_WHY_POISON, c->reg5);
    c->lastSeed = seed;
    c->seedUsed = 1;
    for (k = 0; k < 3; k++) {
        c->marker[k] = osrdn_cp_marker(seed, k);
        c->sentinel[k] = ~c->marker[k];
    }
    if (!cpWait(base, W_FIFO, 3, C_FIFO_US, &c->wFifo))
        return cpLatch(c, base);        /* the CSQ is on (plan 7-2 B1) */
    for (k = 0; k < 3; k++)
        rdnMmioWrite32(base, C_SCRATCH_REG0 + 4 * k, c->sentinel[k]);
    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle2))
        return cpLatch(c, base);
    for (k = 0; k < 3; k++)
        if (rdnMmioRead32(base, C_SCRATCH_REG0 + 4 * k) != c->sentinel[k])
            return cpRefused(c, CP_WHY_SENTINEL, (unsigned long)k);
    cpBuild(c, len);
    cpFence(base);
    return CP_RC_RAN;
}

static void
cpReadBack(osrdn_cp_state *c, vm_address_t base)
{
    int k;

    for (k = 0; k < 3; k++)
        c->got[k] = rdnMmioRead32(base, C_SCRATCH_REG0 + 4 * k);
    c->rptrAfter = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;
    (void)cpPoisonHolds(c, base);
    (void)cpCheckBlock(c);
}

static int
cpSubmit(osrdn_cp_state *c, vm_address_t base, unsigned long seed, unsigned long len, int inject)
{
    unsigned long target;
    int rc, k;

    rc = cpPrepare(c, base, seed, len);
    if (rc != CP_RC_RAN)
        return rc;
    target = (c->wptr + len) & C_RPTR_MASK;
    rdnMmioWrite32(base, C_CP_RB_WPTR, target);
    (void)rdnMmioRead32(base, C_CP_RB_RPTR);    /* posting */
    c->wptr = target;
    c->wptrAfter = target;
    /* M3i/M3j: did the doorbell take? (docs/M3I_PLAN.md 3 D2); a wait that runs out recovers (docs/M3J_PLAN.md 5) */
    c->wptrRead = rdnMmioRead32(base, C_CP_RB_WPTR) & C_RPTR_MASK;
    if (c->wptrRead != target) {
        (void)cpRefuse(c, CP_WHY_WPTR, c->wptrRead);
        return cpFail(c, base);
    }
    if (!cpWait(base, W_RPTR, target, C_RPTR_US, &c->wRptr))
        return cpFail(c, base);
    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle))
        return cpFail(c, base);
    cpReadBack(c, base);
    for (k = 0; k < 3; k++)
        if (c->got[k] != c->marker[k])
            c->failed = 1;
    if (c->reg5 != CP_REG5_POISON || c->spareBad || c->guardBad || c->tableBad || c->canaryBad || c->ringBad)
        c->failed = 1;
    if (inject && !c->failed) {
        /* R5d: the submission ran and read back right; now the driver latches
           as a wait that ran out would -- RAM first, then cpLatch's one read */
        c->latchInjected = 1;
        c->injectCount++;
        (void)cpRefuse(c, CP_WHY_INJECTED, 0);
        return cpLatch(c, base);
    }
    return c->failed ? CP_RC_CHECK_FAILED : CP_RC_RAN;
}

/* SUBMIT without the WPTR write: the sentinels must survive (plan 7-2 B11) */
static int
cpNegctl(osrdn_cp_state *c, vm_address_t base, unsigned long seed)
{
    osrdn_cp_wait w;
    int rc, k;

    rc = cpPrepare(c, base, seed, 16UL);
    if (rc != CP_RC_RAN)
        return rc;
    /* a wait that must run out: nothing was asked of the CP */
    (void)cpWait(base, W_RPTR, (c->wptr + 16UL) & C_RPTR_MASK, C_NEG_US, &w);
    c->wRptr = w;
    c->wptrAfter = c->wptr;
    cpReadBack(c, base);
    for (k = 0; k < 3; k++)
        if (c->got[k] != c->sentinel[k])
            c->failed = 1;
    if (c->rptrAfter != c->wptr || c->reg5 != CP_REG5_POISON || c->ringBad || c->spareBad)
        c->failed = 1;
    return c->failed ? CP_RC_CHECK_FAILED : CP_RC_RAN;
}

/* latched: CSQ off, one status read, nothing else (plan 7-1 E1) */
static int
cpStopLatched(osrdn_cp_state *c, vm_address_t base)
{
    rdnMmioWrite32(base, C_CP_CSQ_CNTL, 0UL);
    c->postStatus = rdnMmioRead32(base, C_RBBM_STATUS);
    return CP_RC_LATCHED;
}

static int
cpStop(osrdn_cp_state *c, vm_address_t base)
{
    if (c->latched)
        return cpStopLatched(c, base);
    if (c->state != CP_ST_MAPPED && c->state != CP_ST_RUNNING)
        return CP_RC_RAN;                   /* nothing holds the card */
    if (c->state == CP_ST_RUNNING) {
        if (!cpWait(base, W_RPTR, c->wptr, C_RPTR_US, &c->wRptr)) {
            (void)cpLatch(c, base);
            return cpStopLatched(c, base);
        }
        if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle)) {
            (void)cpLatch(c, base);
            return cpStopLatched(c, base);
        }
        c->rptrAfter = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;     /* a record */
        c->inflight = 0;                /* G5-2: the ring caught up and the engine idle */
        rdnMmioWrite32(base, C_CP_CSQ_CNTL, 0UL);
        if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle2)) {
            (void)cpLatch(c, base);
            return cpStopLatched(c, base);
        }
        /* RPTR reads 0 once the CSQ is off (boot eae3072b, docs/R5_STOPFIX_PLAN.md):
           the pointers are recorded, never compared -- the catch-up wait above
           is what proved RPTR == WPTR, with the CSQ still on */
        c->rptrOff = rdnMmioRead32(base, C_CP_RB_RPTR);
        c->wptrOff = rdnMmioRead32(base, C_CP_RB_WPTR);
    }
    /* CSQ_STAT is not judged here: it read rptr != wptr on a boot before the CP
       ever ran (docs/R5_PLAN.md 12-4 B1 B2); osrdn_cp_run records it */
    cpUnmap(c, base);
    c->state = CP_ST_STOPPED;
    (void)cpCheckBlock(c);
    return CP_RC_RAN;
}

/* ---- R6a: the first 3D (docs/R6_PLAN.md 7) ------------------------------------
 *
 * The precedent is FreeBSD's R200 depth clear (radeon_state.c 1124-1247), word
 * for word as tools/oracle/r200_clear_oracle.py generates it; the prefix and the
 * tail are the plan's additions.  Every 3D register is written through the ring
 * only; the one MMIO write is the reference's own pixel-cache flush
 * (radeon_cp.c radeon_do_pixcache_flush).  No floating point: the vertex words
 * are the IEEE bits tools/r6/zclear_oracle.py computes. */

#define C_P0(reg)               ((unsigned long)(reg) >> 2)     /* PACKET0, one register */
#define C_SURF_TRANSLATION_DIS  0x00000100UL
#define C_WAIT_IDLE             0x00070000UL    /* 2D | 3D | HOST idleclean */
#define C_PURGE_DC              0x0000000fUL    /* DC_FLUSH | DC_FREE */
#define C_PURGE_ZC              0x00000005UL    /* ZC_FLUSH | ZC_FREE */
#define C_VTX_COLOR0            0x00001800UL    /* SE_VTX_FMT_0 colour 0 field (R6c: PK_RGBA = 1 << 11) */
#define C_TXBLEND_DIFFUSE       0x00001000UL    /* PP_TXCBLEND_0 / TXABLEND_0: 0 * 0 + diffuse, MADD */
#define C_TXBLEND2_R0           0x00011000UL    /* PP_TXCBLEND2_0 / TXABLEND2_0: 1X, clamp 0..1, to R0 */
#define C_PP_CNTL               0x1c38          /* R7a: only in cpR6State before this */
#define C_SE_VAP_CNTL           0x2080
#define C_SE_VTX_FMT_0          0x2088
#define C_FLOAT_ONE             0x3f800000UL
/* R7a (docs/R7_PLAN.md 4): the value masks, the vertex format's measured fields, and VF_CNTL.
   Every one of these names a field this project HAS measured; anything else is refused. */
#define CP_R7_PP_CNTL_TEX_1_5   0x000003e0UL    /* R200_TEX_1..5_ENABLE (r200_reg.h 157-176) */
#define CP_R7_VAP_TCL           0x00000001UL
#define CP_R7_TXFORMAT_CUBIC    0x08000000UL
/* G4-4 K5 (docs/G4_4_KERNEL_PLAN.md 4-1): PP_TXFILTER's fields this project has NOT measured, refused
   as a value rule -- the anisotropic MIN modes (r200_reg.h 835-838: 8..11 << 1, all carry bit 4), the
   bits the header does not name (8-15), and YUV (r200_reg.h 848-851: bits 20-21).  The mip MIN modes
   (bit 2, r200_reg.h 831-834) and MAX_MIP_LEVEL [19:16] are allowed: cpR7TextureBytes sizes the chain
   they name.  The mask this replaces, 0x1c000, was bits 14-16 -- neither the MIN field nor the whole
   level field (build/g44/model.py). */
#define CP_R7_TXFILTER_UNMEASURED 0x0030ff10UL
/* G4-3 K3 (docs/G4_3_KERNEL_PLAN.md 4): the words the card reads a texture's footprint from --
   Mesa-6.5.3 r200_reg.h 882/897 (FORMAT field, ARGB8888 = 6), 902-905 (log2 width at bit 8, log2
   height at bit 12), 846-847 (MAX_MIP_LEVEL at bit 16), 1071-1076 (the TXOFFSET low bits are endian
   swaps and tiling).  The oracle (tools/r7/verify_oracle.py) carries the same numbers. */
#define CP_R7_TXFORMAT_FMT_MASK 0x0000001fUL
#define CP_R7_TXFORMAT_ARGB8888 0x00000006UL
#define CP_R7_TXFORMAT_W_SHIFT  8
#define CP_R7_TXFORMAT_H_SHIFT  12
#define CP_R7_TXFORMAT_LOG2_MAX 11UL            /* 2048: the R200's largest side */
#define CP_R7_TXFILTER_MIP_SHIFT 16
#define CP_R7_TXO_LOW_MASK      0x0000001fUL    /* endian, macro/micro tile, and the 32-byte grain R6h measured */
/* G4-3 K2 (docs/G4_3_KERNEL_PLAN.md 3): the alpha test's reference byte [7:0] and compare [10:8]
   (r200_reg.h 33-43); the enable is PP_CNTL bit 23, already inside that register's rule */
#define C_PP_MISC               0x1c14
#define CP_R7_PP_MISC_FIELDS    0x000007ffUL
#define CP_R7_VTX0_ALLOWED      0x00001803UL    /* Z0 | W0 | the COLOR_0 field */
#define CP_R7_VF_PRIM_MASK      0x0000000fUL
#define CP_R7_VF_PRIM_TRIANGLES 0x00000004UL
#define CP_R7_VF_WALK_MASK      0x00000030UL
#define CP_R7_VF_WALK_RING      0x00000030UL
#define CP_R7_VF_ALLOWED        0xffff007fUL    /* prim, walk, COLOR_ORDER_RGBA, the vertex count */
#define CP_R7_PITCH_MASK        0x00001ff8UL    /* R200_COLORPITCH_MASK: the pitch is in pixels */
#define CP_R7_RB3D_XY_OFFSET    0x00000200UL    /* M3h: R200_DEPTH_XZ_OFFEST_ENABLE (Mesa-6.5.3 r200_reg.h 195) */
#define CP_R7_PREFIX_FMT0       0x00000003UL    /* what the R7 prefix leaves: Z0 | W0 */
#define CP_R7_PREFIX_FMT1       0x00000000UL
#define C_P3_IMMD(n)            (0xc0003500UL | ((n) << 16))    /* R6l: 3D_DRAW_IMMD_2, n data words */
#define C_VF_TRI                0x00000074UL    /* R6l: TRIANGLES | WALK_RING | COLOR_ORDER_RGBA */
#define C_WAIT_3D_HOST          0x00030000UL    /* R6l: 3D_IDLECLEAN | HOST_IDLECLEAN (docs/R6L_PLAN.md F9) */
#define C_WAIT_3D_IDLECLEAN     0x00020000UL    /* R6g: RADEON_WAIT_3D_IDLECLEAN (radeon_drv.h) */

/* ---- G3: the present blit (docs/G3_PRESENT_PLAN.md 1, 2-1) ----------------------
 * The reference's swap (radeon_state.c 1343-1400), register for register.  The
 * CP-side 2D registers, not the MMIO ones R4 used (SRC_X_Y 0x1590, not SRC_Y_X
 * 0x1434): radeon_reg.h 683, 784, 792, 797, 1580, 1585. */
#define C_DP_GUI_MASTER_CNTL    0x146c
#define C_SRC_PITCH_OFFSET      0x1428
#define C_DST_PITCH_OFFSET      0x142c
#define C_SRC_X_Y               0x1590
#define C_DST_X_Y               0x1594
#define C_DST_WIDTH_HEIGHT      0x1598
#define C_P0N(reg, n)           ((((unsigned long)(n)) << 16) | (((unsigned long)(reg)) >> 2))  /* PACKET0, n+1 registers (radeon_drv.h 1891) */
/* SRC_PITCH_OFFSET_CNTL | DST_PITCH_OFFSET_CNTL | BRUSH_NONE | DST_32BPP | SRC_DATATYPE_COLOR |
   ROP3_S | DP_SRC_SOURCE_MEMORY | CLR_CMP_CNTL_DIS | WR_MSK_DIS -- the GMC word of the reference's
   swap for a 32 bpp screen (radeon_reg.h 683-737, 705); the oracle rebuilds it from the bits */
#define C_PRESENT_GMC           0x52cc36f3UL
#define C_PRESENT_WAIT_PRE      0x00060000UL    /* 3D_IDLECLEAN | HOST_IDLECLEAN (radeon_drv.h 1914-1922) */
#define C_PRESENT_WAIT_POST     0x00050000UL    /* 2D_IDLECLEAN | HOST_IDLECLEAN (radeon_drv.h 1906-1913) */
#define C_PRESENT_WORDS         19      /* REL2: + scissor, write mask, direction -- the EXA copy's own state */
#define C_PRESENT_MAX_DIM       0xffffUL        /* the packed x/y and w/h fields are 16 bits */
#define C_PRESENT_MAX_STRIDE    0x8000UL        /* Matrox's bound: keeps every product below overflowing */

/* ---- G3b: the clear (docs/G3B_CLEAR_PLAN.md 2-1) -- radeon_cp_dispatch_clear, radeon_state.c 852-1262 */
#define C_DP_WRITE_MASK         0x16cc
#define C_CNTL_PAINT_MULTI      0x00009a00UL    /* radeon_drv.h 1178 -- NOT used since G3d: through this CP the
                                                   packet wrote nothing (boot 6, docs/G3B_CLEAR_PLAN.md 7-2) */
/* G3d: the X driver's solid fill, register by register (radeon_exa_funcs.c Emit2DState 90-131 and
   RADEONSolid 222-245; addresses radeon_reg.h 669-670, 774, 784, 800; DEFAULT_SC_BOTTOM_RIGHT as
   RADEONEngineRestore writes it) -- the same PACKET0 form the present blit is drawn with */
#define C_DEFAULT_SC_BOTTOM_RIGHT 0x16e8
#define C_SC_MAX                0x1fff1fffUL    /* DEFAULT_SC_RIGHT_MAX | DEFAULT_SC_BOTTOM_MAX */
#define C_DP_BRUSH_FRGD_CLR     0x147c
#define C_DP_BRUSH_BKGD_CLR     0x1478
#define C_DP_SRC_FRGD_CLR       0x15d8
#define C_DP_SRC_BKGD_CLR       0x15dc
#define C_DP_CNTL               0x16c0
#define C_DP_CNTL_L2R_T2B       0x00000003UL    /* DST_X_LEFT_TO_RIGHT | DST_Y_TOP_TO_BOTTOM (radeon_reg.h 671-672) */
#define C_DST_Y_X               0x1438
#define C_DST_HEIGHT_WIDTH      0x143c
#define C_P3(op, n)             (0xc0000000UL | (((unsigned long)(n)) << 16) | (unsigned long)(op))  /* CP_PACKET3 (radeon_drv.h 1899) */
/* DST_PITCH_OFFSET_CNTL | BRUSH_SOLID_COLOR | DST_32BPP | SRC_DATATYPE_COLOR | ROP3_P | CLR_CMP_CNTL_DIS
   (radeon_state.c 899-906, the bits radeon_reg.h 683-737); the oracle rebuilds it from the names */
#define C_CLEAR_GMC             0x10f036d2UL
#define C_CLEAR_PRIM            0x00030038UL    /* RECT_LIST | WALK_RING | 3 << NUM_VERTICES_SHIFT (radeon_drv.h 1207-1219) */
#define C_CLEAR_ONE             0x3f800000UL    /* 1.0f, the vertex w (radeon_state.c 1236-1244) */
#define C_CLEAR_WORDS           73              /* colour 26 + depth 47 (present_oracle.py clear_words) */
/* G3c: the depth rectangle's ZSTENCILCNTL carries the CLIENT's depth format, as the
   reference's does (radeon_state.c 1219-1221: tempRB3D_ZSTENCILCNTL comes from
   depth_clear->rb3d_zstencilcntl, the format the client drew with) -- 16-bit here
   (OSRDN_TRI_ZSTENCIL_LESS 0x42227010 has format 0; R6f D2 names 0x42227070 as the
   16-bit clear value).  Boot 5 sent cpR6State[9] = 0x42227072 instead: format 2,
   24-bit, so the clear wrote one 24-bit z per WORD across twice the buffer and the
   client's 16-bit LESS test then met half-words of the wrong layout -- the depth test
   failed, hidden surfaces showed, and the operator saw ghosts.  M1I_PLAN.md 11 (2)
   had already burned a boot on this exact field; G3b borrowed the word whole. */
#define C_CLEAR_ZSTENCIL        0x42227070UL    /* 16-bit int z, Z_TEST_ALWAYS, stencil ALWAYS, ops 0x0222, Z_WRITE_ENABLE */
#define C_CLEAR_MAX_PITCH       0x8000UL
#define CP_R6_GROWS             (sizeof cpR6G / sizeof cpR6G[0])

/* the precedent's state block: WAIT_UNTIL then 12 registers (r200_clear_oracle.py) */
static const unsigned long cpR6State[26] = {
    0x000005c8UL, 0x00050000UL,         /* WAIT_UNTIL 2D | HOST idleclean */
    0x0000070eUL, 0x00000000UL,         /* PP_CNTL */
    0x00000714UL, 0x00000000UL,         /* R200_RE_CNTL */
    0x0000070fUL, 0x00001902UL,         /* RB3D_CNTL: plane mask, ARGB8888, Z */
    0x0000070bUL, 0x42227072UL,         /* RB3D_ZSTENCILCNTL: 24 bit, always, write */
    0x0000075fUL, 0x00000000UL,         /* RB3D_STENCILREFMASK */
    0x00000761UL, 0x00000000UL,         /* RB3D_PLANEMASK: no colour */
    0x00000713UL, 0x480055deUL,         /* SE_CNTL */
    0x0000082cUL, 0x00000300UL,         /* R200_SE_VTE_CNTL: XY_FMT | Z_FMT */
    0x00000822UL, 0x00000003UL,         /* R200_SE_VTX_FMT_0: Z0 | W0 */
    0x00000823UL, 0x00000000UL,         /* R200_SE_VTX_FMT_1 */
    0x00000820UL, 0x00240000UL,         /* R200_SE_VAP_CNTL: 9 << 18, TCL off */
    0x000009bcUL, 0x00000000UL          /* R200_RE_AUX_SCISSOR_CNTL */
};

/* R6k (docs/R6K_PLAN.md 4): the auxiliary scissor state a case writes --
   R200_RE_AUX_SCISSOR_CNTL, then TL/BR for the three slots */
static const unsigned long cpR6S[13][7] = {
    { 0x10000000UL, 0x30006UL, 0xd0014UL, 0UL, 0UL, 0UL, 0UL }   /* M1 */,
    { 0x11000000UL, 0x30006UL, 0xd0014UL, 0UL, 0UL, 0UL, 0UL }   /* M2 */,
    { 0x30000000UL, 0x30006UL, 0xd0014UL, 0x8000aUL, 0x18001aUL, 0UL, 0UL }   /* M3 */,
    { 0x32000000UL, 0x30006UL, 0xd0014UL, 0x8000aUL, 0x18001aUL, 0UL, 0UL }   /* M4 */,
    { 0x40000000UL, 0UL, 0UL, 0UL, 0UL, 0x120002UL, 0x1d000eUL }   /* M5 */,
    { 0x10000000UL, 0xd0014UL, 0x30006UL, 0UL, 0UL, 0UL, 0UL }   /* M6 */,
    { 0x10000000UL, 0UL, 0x3f003fUL, 0UL, 0UL, 0UL, 0UL }   /* M7 */,
    { 0x10000000UL, 0x30006UL, 0xd0014UL, 0UL, 0UL, 0UL, 0UL }   /* M8 */,
    { 0x10000000UL, 0x5a305a6UL, 0x5ad05b4UL, 0UL, 0UL, 0UL, 0UL }   /* M9 */,
    { 0x10000000UL, 0x30806UL, 0xd0814UL, 0UL, 0UL, 0UL, 0UL }   /* M10 */,
    { 0x10000000UL, 0x30006UL, 0xd0014UL, 0UL, 0UL, 0UL, 0UL }   /* M12 */,
    { 0x10000000UL, 0x8030006UL, 0x80d0014UL, 0UL, 0UL, 0UL, 0UL }   /* M13 */,
    { 0x10000000UL, 0x7f007f0UL, 0xd0014UL, 0UL, 0UL, 0UL, 0UL }   /* M14 */
};
#define CP_R6_SROWS             (sizeof cpR6S / sizeof cpR6S[0])


/* R6l (docs/R6L_PLAN.md 4): the batch triangles -- x, y as float32 bits, three vertices */
static const unsigned long cpR6Poly[129][6] = {
    { 0UL, 0UL, 0x40800000UL, 0UL, 0UL, 0x40800000UL },
    { 0x40800000UL, 0UL, 0x41000000UL, 0UL, 0x40800000UL, 0x40800000UL },
    { 0x41000000UL, 0UL, 0x41400000UL, 0UL, 0x41000000UL, 0x40800000UL },
    { 0x41400000UL, 0UL, 0x41800000UL, 0UL, 0x41400000UL, 0x40800000UL },
    { 0x41800000UL, 0UL, 0x41a00000UL, 0UL, 0x41800000UL, 0x40800000UL },
    { 0x41a00000UL, 0UL, 0x41c00000UL, 0UL, 0x41a00000UL, 0x40800000UL },
    { 0x41c00000UL, 0UL, 0x41e00000UL, 0UL, 0x41c00000UL, 0x40800000UL },
    { 0x41e00000UL, 0UL, 0x42000000UL, 0UL, 0x41e00000UL, 0x40800000UL },
    { 0UL, 0x40800000UL, 0x40800000UL, 0x40800000UL, 0UL, 0x41000000UL },
    { 0x40800000UL, 0x40800000UL, 0x41000000UL, 0x40800000UL, 0x40800000UL, 0x41000000UL },
    { 0x41000000UL, 0x40800000UL, 0x41400000UL, 0x40800000UL, 0x41000000UL, 0x41000000UL },
    { 0x41400000UL, 0x40800000UL, 0x41800000UL, 0x40800000UL, 0x41400000UL, 0x41000000UL },
    { 0x41800000UL, 0x40800000UL, 0x41a00000UL, 0x40800000UL, 0x41800000UL, 0x41000000UL },
    { 0x41a00000UL, 0x40800000UL, 0x41c00000UL, 0x40800000UL, 0x41a00000UL, 0x41000000UL },
    { 0x41c00000UL, 0x40800000UL, 0x41e00000UL, 0x40800000UL, 0x41c00000UL, 0x41000000UL },
    { 0x41e00000UL, 0x40800000UL, 0x42000000UL, 0x40800000UL, 0x41e00000UL, 0x41000000UL },
    { 0UL, 0x41000000UL, 0x40800000UL, 0x41000000UL, 0UL, 0x41400000UL },
    { 0x40800000UL, 0x41000000UL, 0x41000000UL, 0x41000000UL, 0x40800000UL, 0x41400000UL },
    { 0x41000000UL, 0x41000000UL, 0x41400000UL, 0x41000000UL, 0x41000000UL, 0x41400000UL },
    { 0x41400000UL, 0x41000000UL, 0x41800000UL, 0x41000000UL, 0x41400000UL, 0x41400000UL },
    { 0x41800000UL, 0x41000000UL, 0x41a00000UL, 0x41000000UL, 0x41800000UL, 0x41400000UL },
    { 0x41a00000UL, 0x41000000UL, 0x41c00000UL, 0x41000000UL, 0x41a00000UL, 0x41400000UL },
    { 0x41c00000UL, 0x41000000UL, 0x41e00000UL, 0x41000000UL, 0x41c00000UL, 0x41400000UL },
    { 0x41e00000UL, 0x41000000UL, 0x42000000UL, 0x41000000UL, 0x41e00000UL, 0x41400000UL },
    { 0UL, 0x41400000UL, 0x40800000UL, 0x41400000UL, 0UL, 0x41800000UL },
    { 0x40800000UL, 0x41400000UL, 0x41000000UL, 0x41400000UL, 0x40800000UL, 0x41800000UL },
    { 0x41000000UL, 0x41400000UL, 0x41400000UL, 0x41400000UL, 0x41000000UL, 0x41800000UL },
    { 0x41400000UL, 0x41400000UL, 0x41800000UL, 0x41400000UL, 0x41400000UL, 0x41800000UL },
    { 0x41800000UL, 0x41400000UL, 0x41a00000UL, 0x41400000UL, 0x41800000UL, 0x41800000UL },
    { 0x41a00000UL, 0x41400000UL, 0x41c00000UL, 0x41400000UL, 0x41a00000UL, 0x41800000UL },
    { 0x41c00000UL, 0x41400000UL, 0x41e00000UL, 0x41400000UL, 0x41c00000UL, 0x41800000UL },
    { 0x41e00000UL, 0x41400000UL, 0x42000000UL, 0x41400000UL, 0x41e00000UL, 0x41800000UL },
    { 0UL, 0x41800000UL, 0x40800000UL, 0x41800000UL, 0UL, 0x41a00000UL },
    { 0x40800000UL, 0x41800000UL, 0x41000000UL, 0x41800000UL, 0x40800000UL, 0x41a00000UL },
    { 0x41000000UL, 0x41800000UL, 0x41400000UL, 0x41800000UL, 0x41000000UL, 0x41a00000UL },
    { 0x41400000UL, 0x41800000UL, 0x41800000UL, 0x41800000UL, 0x41400000UL, 0x41a00000UL },
    { 0x41800000UL, 0x41800000UL, 0x41a00000UL, 0x41800000UL, 0x41800000UL, 0x41a00000UL },
    { 0x41a00000UL, 0x41800000UL, 0x41c00000UL, 0x41800000UL, 0x41a00000UL, 0x41a00000UL },
    { 0x41c00000UL, 0x41800000UL, 0x41e00000UL, 0x41800000UL, 0x41c00000UL, 0x41a00000UL },
    { 0x41e00000UL, 0x41800000UL, 0x42000000UL, 0x41800000UL, 0x41e00000UL, 0x41a00000UL },
    { 0UL, 0UL, 0x40800000UL, 0UL, 0UL, 0x40800000UL },
    { 0x40800000UL, 0UL, 0x40800000UL, 0x40800000UL, 0UL, 0x40800000UL },
    { 0x40800000UL, 0UL, 0x41000000UL, 0UL, 0x40800000UL, 0x40800000UL },
    { 0x41000000UL, 0UL, 0x41000000UL, 0x40800000UL, 0x40800000UL, 0x40800000UL },
    { 0x41000000UL, 0UL, 0x41400000UL, 0UL, 0x41000000UL, 0x40800000UL },
    { 0x41400000UL, 0UL, 0x41400000UL, 0x40800000UL, 0x41000000UL, 0x40800000UL },
    { 0x41400000UL, 0UL, 0x41800000UL, 0UL, 0x41400000UL, 0x40800000UL },
    { 0x41800000UL, 0UL, 0x41800000UL, 0x40800000UL, 0x41400000UL, 0x40800000UL },
    { 0x41800000UL, 0UL, 0x41a00000UL, 0UL, 0x41800000UL, 0x40800000UL },
    { 0x41a00000UL, 0UL, 0x41a00000UL, 0x40800000UL, 0x41800000UL, 0x40800000UL },
    { 0x41a00000UL, 0UL, 0x41c00000UL, 0UL, 0x41a00000UL, 0x40800000UL },
    { 0x41c00000UL, 0UL, 0x41c00000UL, 0x40800000UL, 0x41a00000UL, 0x40800000UL },
    { 0x41c00000UL, 0UL, 0x41e00000UL, 0UL, 0x41c00000UL, 0x40800000UL },
    { 0x41e00000UL, 0UL, 0x41e00000UL, 0x40800000UL, 0x41c00000UL, 0x40800000UL },
    { 0x41e00000UL, 0UL, 0x42000000UL, 0UL, 0x41e00000UL, 0x40800000UL },
    { 0x42000000UL, 0UL, 0x42000000UL, 0x40800000UL, 0x41e00000UL, 0x40800000UL },
    { 0UL, 0x40800000UL, 0x40800000UL, 0x40800000UL, 0UL, 0x41000000UL },
    { 0x40800000UL, 0x40800000UL, 0x40800000UL, 0x41000000UL, 0UL, 0x41000000UL },
    { 0x40800000UL, 0x40800000UL, 0x41000000UL, 0x40800000UL, 0x40800000UL, 0x41000000UL },
    { 0x41000000UL, 0x40800000UL, 0x41000000UL, 0x41000000UL, 0x40800000UL, 0x41000000UL },
    { 0x41000000UL, 0x40800000UL, 0x41400000UL, 0x40800000UL, 0x41000000UL, 0x41000000UL },
    { 0x41400000UL, 0x40800000UL, 0x41400000UL, 0x41000000UL, 0x41000000UL, 0x41000000UL },
    { 0x41400000UL, 0x40800000UL, 0x41800000UL, 0x40800000UL, 0x41400000UL, 0x41000000UL },
    { 0x41800000UL, 0x40800000UL, 0x41800000UL, 0x41000000UL, 0x41400000UL, 0x41000000UL },
    { 0x41800000UL, 0x40800000UL, 0x41a00000UL, 0x40800000UL, 0x41800000UL, 0x41000000UL },
    { 0x41a00000UL, 0x40800000UL, 0x41a00000UL, 0x41000000UL, 0x41800000UL, 0x41000000UL },
    { 0x41a00000UL, 0x40800000UL, 0x41c00000UL, 0x40800000UL, 0x41a00000UL, 0x41000000UL },
    { 0x41c00000UL, 0x40800000UL, 0x41c00000UL, 0x41000000UL, 0x41a00000UL, 0x41000000UL },
    { 0x41c00000UL, 0x40800000UL, 0x41e00000UL, 0x40800000UL, 0x41c00000UL, 0x41000000UL },
    { 0x41e00000UL, 0x40800000UL, 0x41e00000UL, 0x41000000UL, 0x41c00000UL, 0x41000000UL },
    { 0x41e00000UL, 0x40800000UL, 0x42000000UL, 0x40800000UL, 0x41e00000UL, 0x41000000UL },
    { 0x42000000UL, 0x40800000UL, 0x42000000UL, 0x41000000UL, 0x41e00000UL, 0x41000000UL },
    { 0UL, 0x41000000UL, 0x40800000UL, 0x41000000UL, 0UL, 0x41400000UL },
    { 0x40800000UL, 0x41000000UL, 0x40800000UL, 0x41400000UL, 0UL, 0x41400000UL },
    { 0x40800000UL, 0x41000000UL, 0x41000000UL, 0x41000000UL, 0x40800000UL, 0x41400000UL },
    { 0x41000000UL, 0x41000000UL, 0x41000000UL, 0x41400000UL, 0x40800000UL, 0x41400000UL },
    { 0x41000000UL, 0x41000000UL, 0x41400000UL, 0x41000000UL, 0x41000000UL, 0x41400000UL },
    { 0x41400000UL, 0x41000000UL, 0x41400000UL, 0x41400000UL, 0x41000000UL, 0x41400000UL },
    { 0x41400000UL, 0x41000000UL, 0x41800000UL, 0x41000000UL, 0x41400000UL, 0x41400000UL },
    { 0x41800000UL, 0x41000000UL, 0x41800000UL, 0x41400000UL, 0x41400000UL, 0x41400000UL },
    { 0x41800000UL, 0x41000000UL, 0x41a00000UL, 0x41000000UL, 0x41800000UL, 0x41400000UL },
    { 0x41a00000UL, 0x41000000UL, 0x41a00000UL, 0x41400000UL, 0x41800000UL, 0x41400000UL },
    { 0x41a00000UL, 0x41000000UL, 0x41c00000UL, 0x41000000UL, 0x41a00000UL, 0x41400000UL },
    { 0x41c00000UL, 0x41000000UL, 0x41c00000UL, 0x41400000UL, 0x41a00000UL, 0x41400000UL },
    { 0x41c00000UL, 0x41000000UL, 0x41e00000UL, 0x41000000UL, 0x41c00000UL, 0x41400000UL },
    { 0x41e00000UL, 0x41000000UL, 0x41e00000UL, 0x41400000UL, 0x41c00000UL, 0x41400000UL },
    { 0x41e00000UL, 0x41000000UL, 0x42000000UL, 0x41000000UL, 0x41e00000UL, 0x41400000UL },
    { 0x42000000UL, 0x41000000UL, 0x42000000UL, 0x41400000UL, 0x41e00000UL, 0x41400000UL },
    { 0UL, 0x41400000UL, 0x40800000UL, 0x41400000UL, 0UL, 0x41800000UL },
    { 0x40800000UL, 0x41400000UL, 0x40800000UL, 0x41800000UL, 0UL, 0x41800000UL },
    { 0x40800000UL, 0x41400000UL, 0x41000000UL, 0x41400000UL, 0x40800000UL, 0x41800000UL },
    { 0x41000000UL, 0x41400000UL, 0x41000000UL, 0x41800000UL, 0x40800000UL, 0x41800000UL },
    { 0x41000000UL, 0x41400000UL, 0x41400000UL, 0x41400000UL, 0x41000000UL, 0x41800000UL },
    { 0x41400000UL, 0x41400000UL, 0x41400000UL, 0x41800000UL, 0x41000000UL, 0x41800000UL },
    { 0x41400000UL, 0x41400000UL, 0x41800000UL, 0x41400000UL, 0x41400000UL, 0x41800000UL },
    { 0x41800000UL, 0x41400000UL, 0x41800000UL, 0x41800000UL, 0x41400000UL, 0x41800000UL },
    { 0x41800000UL, 0x41400000UL, 0x41a00000UL, 0x41400000UL, 0x41800000UL, 0x41800000UL },
    { 0x41a00000UL, 0x41400000UL, 0x41a00000UL, 0x41800000UL, 0x41800000UL, 0x41800000UL },
    { 0x41a00000UL, 0x41400000UL, 0x41c00000UL, 0x41400000UL, 0x41a00000UL, 0x41800000UL },
    { 0x41c00000UL, 0x41400000UL, 0x41c00000UL, 0x41800000UL, 0x41a00000UL, 0x41800000UL },
    { 0x41c00000UL, 0x41400000UL, 0x41e00000UL, 0x41400000UL, 0x41c00000UL, 0x41800000UL },
    { 0x41e00000UL, 0x41400000UL, 0x41e00000UL, 0x41800000UL, 0x41c00000UL, 0x41800000UL },
    { 0x41e00000UL, 0x41400000UL, 0x42000000UL, 0x41400000UL, 0x41e00000UL, 0x41800000UL },
    { 0x42000000UL, 0x41400000UL, 0x42000000UL, 0x41800000UL, 0x41e00000UL, 0x41800000UL },
    { 0UL, 0x41800000UL, 0x40800000UL, 0x41800000UL, 0UL, 0x41a00000UL },
    { 0x40800000UL, 0x41800000UL, 0x40800000UL, 0x41a00000UL, 0UL, 0x41a00000UL },
    { 0x40800000UL, 0x41800000UL, 0x41000000UL, 0x41800000UL, 0x40800000UL, 0x41a00000UL },
    { 0x41000000UL, 0x41800000UL, 0x41000000UL, 0x41a00000UL, 0x40800000UL, 0x41a00000UL },
    { 0x41000000UL, 0x41800000UL, 0x41400000UL, 0x41800000UL, 0x41000000UL, 0x41a00000UL },
    { 0x41400000UL, 0x41800000UL, 0x41400000UL, 0x41a00000UL, 0x41000000UL, 0x41a00000UL },
    { 0x41400000UL, 0x41800000UL, 0x41800000UL, 0x41800000UL, 0x41400000UL, 0x41a00000UL },
    { 0x41800000UL, 0x41800000UL, 0x41800000UL, 0x41a00000UL, 0x41400000UL, 0x41a00000UL },
    { 0x41800000UL, 0x41800000UL, 0x41a00000UL, 0x41800000UL, 0x41800000UL, 0x41a00000UL },
    { 0x41a00000UL, 0x41800000UL, 0x41a00000UL, 0x41a00000UL, 0x41800000UL, 0x41a00000UL },
    { 0x41a00000UL, 0x41800000UL, 0x41c00000UL, 0x41800000UL, 0x41a00000UL, 0x41a00000UL },
    { 0x41c00000UL, 0x41800000UL, 0x41c00000UL, 0x41a00000UL, 0x41a00000UL, 0x41a00000UL },
    { 0x41c00000UL, 0x41800000UL, 0x41e00000UL, 0x41800000UL, 0x41c00000UL, 0x41a00000UL },
    { 0x41e00000UL, 0x41800000UL, 0x41e00000UL, 0x41a00000UL, 0x41c00000UL, 0x41a00000UL },
    { 0x41e00000UL, 0x41800000UL, 0x42000000UL, 0x41800000UL, 0x41e00000UL, 0x41a00000UL },
    { 0x42000000UL, 0x41800000UL, 0x42000000UL, 0x41a00000UL, 0x41e00000UL, 0x41a00000UL },
    { 0x40800000UL, 0x40800000UL, 0x41c00000UL, 0x40800000UL, 0x40800000UL, 0x41c00000UL },
    { 0x40a00000UL, 0x40800000UL, 0x41c00000UL, 0x40800000UL, 0x40a00000UL, 0x41c00000UL },
    { 0x40c00000UL, 0x40800000UL, 0x41c00000UL, 0x40800000UL, 0x40c00000UL, 0x41c00000UL },
    { 0x40e00000UL, 0x40800000UL, 0x41c00000UL, 0x40800000UL, 0x40e00000UL, 0x41c00000UL },
    { 0x41000000UL, 0x40800000UL, 0x41c00000UL, 0x40800000UL, 0x41000000UL, 0x41c00000UL },
    { 0x41100000UL, 0x40800000UL, 0x41c00000UL, 0x40800000UL, 0x41100000UL, 0x41c00000UL },
    { 0x41200000UL, 0x40800000UL, 0x41c00000UL, 0x40800000UL, 0x41200000UL, 0x41c00000UL },
    { 0x41300000UL, 0x40800000UL, 0x41c00000UL, 0x40800000UL, 0x41300000UL, 0x41c00000UL },
    { 0x40800000UL, 0x40800000UL, 0x41e00000UL, 0x40800000UL, 0x40800000UL, 0x41e00000UL }
};
/* R6l: one row per packet -- 1 + the first cpR6Poly row, triangles, colour, and
   (the clip a packet moves to, after a WAIT_UNTIL -- docs/R6L_PLAN.md F9) */
static const unsigned long cpR6Pack[19][6] = {
    { 1UL, 40UL, 0x78563412UL, 0UL, 0UL, 0UL },
    { 41UL, 80UL, 0x78563412UL, 0UL, 0UL, 0UL },
    { 121UL, 1UL, 0x78563412UL, 0UL, 0UL, 0UL },
    { 122UL, 1UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL },
    { 123UL, 1UL, 0x78563412UL, 0UL, 0UL, 0UL },
    { 124UL, 1UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL },
    { 125UL, 1UL, 0x78563412UL, 0UL, 0UL, 0UL },
    { 126UL, 1UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL },
    { 127UL, 1UL, 0x78563412UL, 0UL, 0UL, 0UL },
    { 128UL, 1UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL },
    { 121UL, 1UL, 0x78563412UL, 0UL, 0UL, 0UL },
    { 122UL, 1UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL },
    { 123UL, 1UL, 0x78563412UL, 0UL, 0UL, 0UL },
    { 124UL, 1UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL },
    { 125UL, 1UL, 0x78563412UL, 1UL, 0xc000cUL, 0x1f001fUL },
    { 126UL, 1UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL },
    { 127UL, 1UL, 0x78563412UL, 0UL, 0UL, 0UL },
    { 128UL, 1UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL },
    { 129UL, 1UL, 0x78563412UL, 0UL, 0UL, 0UL }
};
#define CP_R6_POLYS             (sizeof cpR6Poly / sizeof cpR6Poly[0])
#define CP_R6_PACKS             (sizeof cpR6Pack / sizeof cpR6Pack[0])

/* the cases: clip box (integers), geometry box and z (IEEE bits), and the value
   R200_RE_CNTL gets in the precedent's state block (docs/R6B_PLAN.md 5: rule H,
   RE_TOP_LEFT clips only with SCISSOR_ENABLE, bit 1); then the colour path
   (docs/R6C_PLAN.md 6): PP_CNTL, RB3D_PLANEMASK and SE_VTX_FMT_0 go into the state
   block, vsc is the prefix's SE_VTX_STATE_CNTL, hdr/vf open the draw, and a vertex
   carries the colour word when fmt has colour 0.  A-E are the R6a/R6b streams, bit for bit. */
typedef struct {
    unsigned long cx1, cy1, cx2, cy2;
    unsigned long gx1, gy1, gx2, gy2, z;
    unsigned long recntl;
    unsigned long ppcntl, planemask, fmt, vsc, hdr, vf, colour;
    unsigned long tri, covp1, covp2;    /* R6d: 1 + index into cpR6Tris (0: the box above), and
                                           the two pixels the coverage map names 1 and 2 */
    unsigned long secntl;               /* R6e: SE_CNTL's value word (the precedent 0x480055de; Gouraud 0x48005ade) */
    unsigned long lanes, gconst, gvary; /* R6e: lanes to read back (bit l = byte l), the constant lanes' pixel,
                                           the varying lanes (bit l) -- all 0 before R6e */
    unsigned long zcntl;                /* R6f: RB3D_ZSTENCILCNTL's value word (the precedent 0x42227072; 16-bit 0x42227070) */
    unsigned long zrow, grid, dsrc;     /* R6f: 1 + a cpR6Zv row (a z per vertex; 0: every vertex cs->z), 1 + a
                                           cpR6GridZ row (the 16-cell grid instead of a triangle row; 0: none),
                                           the planes' source (0 colour, 1 24-bit depth, 2 16-bit depth) */
    unsigned long rb3d;                 /* R6g: RB3D_CNTL's value word (the precedent 0x1902; Z_ENABLE off 0x1802) */
    unsigned long gidx;                 /* R6g: 0, or 1 + a cpR6G row (the CPU prefill and the second draw) */
    unsigned long tidx;                 /* R6h: 0, or 1 + a cpR6T row (the texture and its ST) */
    unsigned long widx, vte;            /* R6i: 0, or 1 + a cpR6W row (a W per vertex; 0: every vertex 1.0),
                                           and 0, or SE_VTE_CNTL's value word (0: the state block's 0x300) */
    unsigned long sidx;                 /* R6k: 0, or 1 + a cpR6S row (the auxiliary scissor's seven
                                           registers; the state block always clears the control word) */
    unsigned long bfirst, bcount;       /* R6l: 0, or 1 + the first cpR6Pack row and how many packets
                                           this case submits (docs/R6L_PLAN.md 4) */
    unsigned long coff, zoff, toff;     /* R6m: 0, or where this case's colour, depth and texture
                                           surfaces sit in the window (docs/R6M_PLAN.md 4) */
} cpR6Case;

/* R6d (docs/R6D_PLAN.md 10): a triangle case's vertices in packet order -- x, y (float32
   bits) and the colour word; nv is 3 or 6 (TRIANGLES wants a multiple of 3) */
typedef struct {
    unsigned long nv;
    unsigned long v[6][3];
} cpR6Tri;

/* R6d: the triangles, generated from tools/r6/tri_oracle.py (x, y as float32 bits, the colour word);
   tools/r6/sim_r6.py proves the ring words equal the oracle's */
static const cpR6Tri cpR6Tris[CP_R6_TRIS] = {
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0x78563412UL }, { 0x41e00000UL, 0x40800000UL, 0x78563412UL }, { 0x40800000UL, 0x41e00000UL, 0x78563412UL } } }   /* T1 */,
    { 3UL, { { 0x40900000UL, 0x40900000UL, 0x78563412UL }, { 0x41e40000UL, 0x40900000UL, 0x78563412UL }, { 0x40900000UL, 0x41e40000UL, 0x78563412UL } } }   /* T2 */,
    { 6UL, { { 0x41000000UL, 0x41000000UL, 0x78563412UL }, { 0x41c00000UL, 0x41000000UL, 0x78563412UL }, { 0x41000000UL, 0x41c00000UL, 0x78563412UL }, { 0x41c00000UL, 0x41000000UL, 0x3cdebc9aUL }, { 0x41c00000UL, 0x41c00000UL, 0x3cdebc9aUL }, { 0x41000000UL, 0x41c00000UL, 0x3cdebc9aUL } } }   /* T3 */,
    { 6UL, { { 0x41080000UL, 0x41080000UL, 0x78563412UL }, { 0x41c40000UL, 0x41080000UL, 0x78563412UL }, { 0x41080000UL, 0x41c40000UL, 0x78563412UL }, { 0x41c40000UL, 0x41080000UL, 0x3cdebc9aUL }, { 0x41c40000UL, 0x41c40000UL, 0x3cdebc9aUL }, { 0x41080000UL, 0x41c40000UL, 0x3cdebc9aUL } } }   /* T4 */,
    { 3UL, { { 0x40533333UL, 0x40266666UL, 0x78563412UL }, { 0x41eb999aUL, 0x40f9999aUL, 0x78563412UL }, { 0x4121999aUL, 0x41f1999aUL, 0x78563412UL } } }   /* T5 */,
    { 3UL, { { 0x4081eb85UL, 0x407c28f6UL, 0x78563412UL }, { 0x41d9851fUL, 0x40c9eb85UL, 0x78563412UL }, { 0x41170a3dUL, 0x41e08f5cUL, 0x78563412UL } } }   /* T6 */,
    { 3UL, { { 0x41db0000UL, 0x40940000UL, 0x78563412UL }, { 0x408a0000UL, 0x40440000UL, 0x78563412UL }, { 0x41270000UL, 0x41de0000UL, 0x78563412UL } } }   /* X1 */,
    { 3UL, { { 0x40140000UL, 0x419a8000UL, 0x78563412UL }, { 0x41b00000UL, 0x40e80000UL, 0x78563412UL }, { 0x419d8000UL, 0x41a38000UL, 0x78563412UL } } }   /* X2 */,
    { 3UL, { { 0x40b9d2f2UL, 0x40dbced9UL, 0x78563412UL }, { 0x41e18d50UL, 0x4153ae14UL, 0x78563412UL }, { 0x41411687UL, 0x41a870a4UL, 0x78563412UL } } }   /* X3 */,
    { 3UL, { { 0x41eabe77UL, 0x417efdf4UL, 0x78563412UL }, { 0x409b8d50UL, 0x419b374cUL, 0x78563412UL }, { 0x41ee1eb8UL, 0x41151aa0UL, 0x78563412UL } } }   /* X4 */,
    { 3UL, { { 0x418cb22dUL, 0x41306e98UL, 0x78563412UL }, { 0x410cc8b4UL, 0x41b7fdf4UL, 0x78563412UL }, { 0x4156872bUL, 0x41db2b02UL, 0x78563412UL } } }   /* X5 */,
    { 3UL, { { 0x41bc0000UL, 0x41200000UL, 0x78563412UL }, { 0x41940000UL, 0x41c80000UL, 0x78563412UL }, { 0x41310000UL, 0x40740000UL, 0x78563412UL } } }   /* X6 */,
    { 3UL, { { 0x41c3c000UL, 0x407e0000UL, 0x78563412UL }, { 0x41aac000UL, 0x41398000UL, 0x78563412UL }, { 0x40520000UL, 0x4185c000UL, 0x78563412UL } } }   /* X7 */,
    { 3UL, { { 0x41208000UL, 0x40b10000UL, 0x78563412UL }, { 0x41e34000UL, 0x41418000UL, 0x78563412UL }, { 0x40c50000UL, 0x41d54000UL, 0x78563412UL } } }   /* X8 */,
    { 3UL, { { 0x41d5fc00UL, 0x414ff800UL, 0x78563412UL }, { 0x4017e000UL, 0x41a3fc00UL, 0x78563412UL }, { 0x4144a7f0UL, 0x4137fc00UL, 0x78563412UL } } }   /* Y1 */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0x3cdebc9aUL }, { 0x41e00000UL, 0x40800000UL, 0x44332211UL }, { 0x40800000UL, 0x41e00000UL, 0x78563412UL } } }   /* T7 */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0x78563412UL }, { 0x40800000UL, 0x41e00000UL, 0x78563412UL }, { 0x41e00000UL, 0x40800000UL, 0x78563412UL } } }   /* T1r */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0x3cdebc9aUL }, { 0x41e00000UL, 0x40800000UL, 0x3cdebc9aUL }, { 0x40800000UL, 0x41e00000UL, 0x3cdebc9aUL } } }   /* G0 */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0x00563400UL }, { 0x41e00000UL, 0x40800000UL, 0xf05634f0UL }, { 0x40800000UL, 0x41e00000UL, 0x00563400UL } } }   /* G1 */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0x00563400UL }, { 0x41e00000UL, 0x40800000UL, 0x00563400UL }, { 0x40800000UL, 0x41e00000UL, 0xf05634f0UL } } }   /* G2 */,
    { 3UL, { { 0x40b9d2f2UL, 0x40dbced9UL, 0x11563411UL }, { 0x41e18d50UL, 0x4153ae14UL, 0xc95634c9UL }, { 0x41411687UL, 0x41a870a4UL, 0x5a56345aUL } } }   /* G3 */,
    { 3UL, { { 0x41e63127UL, 0x41e9ba5eUL, 0xbb5634bbUL }, { 0x41c91893UL, 0x415676c9UL, 0xce5634ceUL }, { 0x40a4624eUL, 0x41d0b22dUL, 0xe35634e3UL } } }   /* S1 */,
    { 3UL, { { 0x41dad0e5UL, 0x41500000UL, 0x7a56347aUL }, { 0x40ad26e9UL, 0x41ec72b0UL, 0x74563474UL }, { 0x41240000UL, 0x4034dd2fUL, 0x75563475UL } } }   /* S2 */,
    { 3UL, { { 0x400da1cbUL, 0x40ad6873UL, 0x46563446UL }, { 0x41d45604UL, 0x40a5eb85UL, 0xf55634f5UL }, { 0x41ee45a2UL, 0x41ce1aa0UL, 0x45563445UL } } }   /* S3 */,
    { 3UL, { { 0x405820c5UL, 0x41de8b44UL, 0xdc5634dcUL }, { 0x41e2cccdUL, 0x419f8d50UL, 0x75563475UL }, { 0x41e95e35UL, 0x40616873UL, 0x00563400UL } } }   /* S4 */,
    { 3UL, { { 0x408774bcUL, 0x41eae560UL, 0x4e56344eUL }, { 0x40e43127UL, 0x40ca3d71UL, 0x45563445UL }, { 0x41b120c5UL, 0x41c822d1UL, 0x47563447UL } } }   /* S5 */,
    { 3UL, { { 0x41d2f1aaUL, 0x41c2b22dUL, 0x47563447UL }, { 0x408f6c8bUL, 0x4050b439UL, 0x45563445UL }, { 0x41b3b439UL, 0x4026b852UL, 0x43563443UL } } }   /* S6 */,
    { 3UL, { { 0x41e76042UL, 0x419de76dUL, 0x2a56342aUL }, { 0x409a3d71UL, 0x41cd5810UL, 0x28563428UL }, { 0x41188b44UL, 0x41260c4aUL, 0x2e56342eUL } } }   /* S7 */,
    { 3UL, { { 0x40d37ceeUL, 0x41e40831UL, 0x5e56345eUL }, { 0x413522d1UL, 0x40860419UL, 0x61563461UL }, { 0x41df72b0UL, 0x4069db23UL, 0x62563462UL } } }   /* S8 */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0x00563400UL }, { 0x41e00000UL, 0x40800000UL, 0x18563418UL }, { 0x40800000UL, 0x41e00000UL, 0x00563400UL } } }   /* H1 */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0x00563400UL }, { 0x41e00000UL, 0x40800000UL, 0x00563400UL }, { 0x40800000UL, 0x41e00000UL, 0x18563418UL } } }   /* H2 */,
    { 3UL, { { 0x41c91893UL, 0x415676c9UL, 0xce5634ceUL }, { 0x40a4624eUL, 0x41d0b22dUL, 0xe35634e3UL }, { 0x41e63127UL, 0x41e9ba5eUL, 0xbb5634bbUL } } }   /* P1 */,
    { 3UL, { { 0x41da3127UL, 0x41ddba5eUL, 0xbb5634bbUL }, { 0x41bd1893UL, 0x413e76c9UL, 0xce5634ceUL }, { 0x4068c49cUL, 0x41c4b22dUL, 0xe35634e3UL } } }   /* M1 */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0xc85634c8UL }, { 0x40800000UL, 0x41e00000UL, 0x00563400UL }, { 0x41e00000UL, 0x40800000UL, 0x38563438UL } } }   /* E1 */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0xc85634c8UL }, { 0x40800000UL, 0x41e00000UL, 0x50563450UL }, { 0x41e00000UL, 0x40800000UL, 0x28563428UL } } }   /* E2 */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0xf85634f8UL }, { 0x40800000UL, 0x41e00000UL, 0x50563450UL }, { 0x41e00000UL, 0x40800000UL, 0x00563400UL } } }   /* E3 */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0xf85634f8UL }, { 0x40800000UL, 0x41e00000UL, 0x28563428UL }, { 0x41e00000UL, 0x40800000UL, 0xc85634c8UL } } }   /* E4 */,
    { 3UL, { { 0x40b9d2f2UL, 0x40dbced9UL, 0x78561112UL }, { 0x41e18d50UL, 0x4153ae14UL, 0x7856c912UL }, { 0x41411687UL, 0x41a870a4UL, 0x78565a12UL } } }   /* G4 */,
    { 3UL, { { 0x40b9d2f2UL, 0x40dbced9UL, 0x78113412UL }, { 0x41e18d50UL, 0x4153ae14UL, 0x78c93412UL }, { 0x41411687UL, 0x41a870a4UL, 0x785a3412UL } } }   /* G5 */,
    { 3UL, { { 0x4081eb85UL, 0x407c28f6UL, 0xbe3cf00dUL }, { 0x41d9851fUL, 0x40c9eb85UL, 0x1e3d05c9UL }, { 0x41170a3dUL, 0x41e08f5cUL, 0x6efa824dUL } } }   /* G7 */,
    { 3UL, { { 0x4081eb85UL, 0x407c28f6UL, 0x0dbe3cf0UL }, { 0x41d9851fUL, 0x40c9eb85UL, 0xc91e3d05UL }, { 0x41170a3dUL, 0x41e08f5cUL, 0x4d6efa82UL } } }   /* G7p */,
    { 3UL, { { 0x4111b22dUL, 0x4115df3bUL, 0x0e56340eUL }, { 0x418f8b44UL, 0x41d5e979UL, 0x35563435UL }, { 0x41e6dd2fUL, 0x41c67ae1UL, 0xc75634c7UL } } }   /* V1 */,
    { 3UL, { { 0x41c2e979UL, 0x40cac8b4UL, 0x6d56346dUL }, { 0x417f126fUL, 0x40c9a9fcUL, 0x61563461UL }, { 0x41c9cac1UL, 0x41aa353fUL, 0x8a56348aUL } } }   /* V2 */,
    { 3UL, { { 0x419124ddUL, 0x40a20c4aUL, 0x3d56343dUL }, { 0x40af5c29UL, 0x410378d5UL, 0xf15634f1UL }, { 0x40f1d2f2UL, 0x41a51893UL, 0xd95634d9UL } } }   /* V3 */,
    { 3UL, { { 0x41e91aa0UL, 0x41988312UL, 0x77563477UL }, { 0x41218937UL, 0x40fff7cfUL, 0x19563419UL }, { 0x4098bc6aUL, 0x41ae7ae1UL, 0xd15634d1UL } } }   /* V4 */,
    { 3UL, { { 0x41ab645aUL, 0x41e80000UL, 0x9b56349bUL }, { 0x413f0e56UL, 0x41e0374cUL, 0xc35634c3UL }, { 0x40ab8d50UL, 0x40981062UL, 0x65563465UL } } }   /* V5 */,
    { 3UL, { { 0x412c24ddUL, 0x41490625UL, 0x44563444UL }, { 0x41b7d0e5UL, 0x40fbef9eUL, 0xdb5634dbUL }, { 0x41e824ddUL, 0x418e9ba6UL, 0xd55634d5UL } } }   /* V6 */,
    { 3UL, { { 0x4122cccdUL, 0x41d23333UL, 0x9a56349aUL }, { 0x4035e354UL, 0x417ab439UL, 0xff5634ffUL }, { 0x41ebef9eUL, 0x41ed2b02UL, 0xce5634ceUL } } }   /* V7 */,
    { 3UL, { { 0x4187ced9UL, 0x40e2b021UL, 0x731f8aeeUL }, { 0x40622d0eUL, 0x416ac49cUL, 0x3586fd7aUL }, { 0x4012c083UL, 0x41d43333UL, 0x44c49710UL } } }   /* V8 */,
    { 3UL, { { 0x41d30000UL, 0x41e78000UL, 0xaf5634afUL }, { 0x40900000UL, 0x41cf0000UL, 0x8f56348fUL }, { 0x40f00000UL, 0x41060000UL, 0xa45634a4UL } } }   /* D1 */,
    { 3UL, { { 0x40be0000UL, 0x414b0000UL, 0xbe5634beUL }, { 0x41898000UL, 0x41550000UL, 0x0b56340bUL }, { 0x40be0000UL, 0x41e58000UL, 0x05563405UL } } }   /* D2 */,
    /* R6f: flat C1, the depth cases' geometries (tools/r6/depth_oracle.py) */
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0x78563412UL }, { 0x41e00000UL, 0x40800000UL, 0x78563412UL }, { 0x40800000UL, 0x41e00000UL, 0x78563412UL } } }   /* T1z */,
    { 3UL, { { 0x40b9d2f2UL, 0x40dbced9UL, 0x78563412UL }, { 0x41e18d50UL, 0x4153ae14UL, 0x78563412UL }, { 0x41411687UL, 0x41a870a4UL, 0x78563412UL } } }   /* X3z */,
    { 3UL, { { 0x41e63127UL, 0x41e9ba5eUL, 0x78563412UL }, { 0x41c91893UL, 0x415676c9UL, 0x78563412UL }, { 0x40a4624eUL, 0x41d0b22dUL, 0x78563412UL } } }   /* S1z */,
    { 3UL, { { 0x4111b22dUL, 0x4115df3bUL, 0x78563412UL }, { 0x418f8b44UL, 0x41d5e979UL, 0x78563412UL }, { 0x41e6dd2fUL, 0x41c67ae1UL, 0x78563412UL } } }   /* V1z */,
    { 3UL, { { 0x41e91aa0UL, 0x41988312UL, 0x78563412UL }, { 0x41218937UL, 0x40fff7cfUL, 0x78563412UL }, { 0x4098bc6aUL, 0x41ae7ae1UL, 0x78563412UL } } }   /* V4z */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0x78563412UL }, { 0x41a00000UL, 0x40800000UL, 0x78563412UL }, { 0x40800000UL, 0x41a00000UL, 0x78563412UL } } }   /* T2p */,
    { 3UL, { { 0x40800000UL, 0x40800000UL, 0x40f02010UL }, { 0x41a00000UL, 0x40800000UL, 0xc03090e0UL }, { 0x40800000UL, 0x41a00000UL, 0x2080f070UL } } }   /* T2j */,
    { 6UL, { { 0UL, 0UL, 0x78563412UL }, { 0x42000000UL, 0UL, 0x78563412UL }, { 0UL, 0x42000000UL, 0x78563412UL }, { 0x42000000UL, 0UL, 0x78563412UL }, { 0x42000000UL, 0x42000000UL, 0x78563412UL }, { 0UL, 0x42000000UL, 0x78563412UL } } }   /* S1: the 32 x 32 map */,
    { 6UL, { { 0UL, 0UL, 0x78563412UL }, { 0x42200000UL, 0UL, 0x78563412UL }, { 0UL, 0x42200000UL, 0x78563412UL }, { 0x42200000UL, 0UL, 0x78563412UL }, { 0x42200000UL, 0x42200000UL, 0x78563412UL }, { 0UL, 0x42200000UL, 0x78563412UL } } }   /* S2: 40 x 40, wider than the clip */
};

/* R6f (docs/R6F_PLAN.md 3-2): the grid's cells, the anchors, the z per vertex -- generated by
   tools/r6/depth_oracle.py --c-tables */
static const unsigned long cpR6Cells[16][4] = {     /* x0, y0, x0 + 3, y0 + 3 (float32) */
    { 0x40000000UL, 0x40000000UL, 0x40a00000UL, 0x40a00000UL },
    { 0x41200000UL, 0x40000000UL, 0x41500000UL, 0x40a00000UL },
    { 0x41900000UL, 0x40000000UL, 0x41a80000UL, 0x40a00000UL },
    { 0x41d00000UL, 0x40000000UL, 0x41e80000UL, 0x40a00000UL },
    { 0x40000000UL, 0x41200000UL, 0x40a00000UL, 0x41500000UL },
    { 0x41200000UL, 0x41200000UL, 0x41500000UL, 0x41500000UL },
    { 0x41900000UL, 0x41200000UL, 0x41a80000UL, 0x41500000UL },
    { 0x41d00000UL, 0x41200000UL, 0x41e80000UL, 0x41500000UL },
    { 0x40000000UL, 0x41900000UL, 0x40a00000UL, 0x41a80000UL },
    { 0x41200000UL, 0x41900000UL, 0x41500000UL, 0x41a80000UL },
    { 0x41900000UL, 0x41900000UL, 0x41a80000UL, 0x41a80000UL },
    { 0x41d00000UL, 0x41900000UL, 0x41e80000UL, 0x41a80000UL },
    { 0x40000000UL, 0x41d00000UL, 0x40a00000UL, 0x41e80000UL },
    { 0x41200000UL, 0x41d00000UL, 0x41500000UL, 0x41e80000UL },
    { 0x41900000UL, 0x41d00000UL, 0x41a80000UL, 0x41e80000UL },
    { 0x41d00000UL, 0x41d00000UL, 0x41e80000UL, 0x41e80000UL }
};
static const unsigned long cpR6GridZ[4][16] = {       /* the 64 anchors (float32) */
    { 0x3cd54000UL, 0x3f419601UL, 0x3f0007ffUL, 0x3cb63000UL, 0x3ce990e9UL, 0x3f08cd00UL, 0x3f00c68aUL, 0x3f102891UL, 0x3ef0aef0UL, 0x3ce981d2UL, 0x3d95e095UL, 0x3ec230c3UL, 0x3cafffffUL, 0x3ce99001UL, 0x3f00d17fUL, 0x3e746203UL },
    { 0x3ef942ffUL, 0x3f000800UL, 0x3ec1d5c2UL, 0x3ef0aff1UL, 0x3d56f8d7UL, 0x3f72a873UL, 0x3f732ef3UL, 0x3cb00001UL, 0x3cb40000UL, 0x3cd00000UL, 0x3e387002UL, 0x3e42b9fdUL, 0x3ee0ffffUL, 0x3f00d180UL, 0x3cb62fffUL, 0x3ce99000UL },
    { 0x3ce991d2UL, 0x3e746204UL, 0x3ebe4ffeUL, 0x3e56d6d7UL, 0x3f5a7f3eUL, 0x3cc076d0UL, 0x3d086b37UL, 0x3cf50000UL, 0x3cc076d1UL, 0x377f1dfbUL, 0x38d00b9dUL, 0x358401b3UL, 0x3a11f203UL, 0x3584473dUL, 0x36ba0076UL, 0x36e601b3UL },
    { 0x35dffc1aUL, 0x36aaff66UL, 0x3eccea02UL, 0x3f07e348UL, 0x3f25b44eUL, 0x3e947a9fUL, 0x3ec61708UL, 0x3eac5920UL, 0x3e5fb5ffUL, 0x3dbc9d98UL, 0x3ea9bf97UL, 0x3e7dde01UL, 0x3f6c8d12UL, 0x3e96fc07UL, 0x3e353f32UL, 0x3dbe9294UL }
};
static const unsigned long cpR6Zv[7][3] = {           /* I1-I7: z per vertex (float32) */
    { 0x3e800000UL, 0x3f400000UL, 0x3e800000UL }   /* I1 */,
    { 0x3e800000UL, 0x3e800000UL, 0x3f400000UL }   /* I2 */,
    { 0x3f0f5455UL, 0x3ecd9065UL, 0x3f523f1aUL }   /* I3 */,
    { 0x3f48a4ebUL, 0x3f0d2317UL, 0x3dff6d84UL }   /* I4 */,
    { 0x3f000000UL, 0x3f001000UL, 0x3effd000UL }   /* I5 */,
    { 0x3cf5c28fUL, 0x3f7851ecUL, 0x3f000000UL }   /* I6 */,
    { 0x3f0019ebUL, 0x3d8dc548UL, 0x3e1bf7f9UL }   /* I7 */
};

/* R6g (docs/R6G_PLAN.md 2-1, 6): each case's CPU prefill (A + B*x + C*y, two's complement) and its
   second draw -- generated by tools/r6/depth_oracle.py --c-tables */
static const unsigned long cpR6G[30][12] = {   /* pf, A, B, C, d2 zcntl, d2 z0, z1, z2, colour, wait, R6j: BLENDCNTL, the second RB3D_CNTL */
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GN */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GL */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GLE */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GE */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GGE */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GG */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GNE */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GA */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GLW */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GAW */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GZE */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GF */,
    { 1UL, 0x3c00UL, 0x400UL, 0x200UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GFG */,
    { 1UL, 0x8000UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* GI */,
    { 1UL, 0x3c0000UL, 0x40000UL, 0x20000UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }   /* G24 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227010UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL }   /* GH1 */,
    { 1UL, 0xc000UL, 0UL, 0UL, 0x42227010UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL }   /* GH2 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227030UL, 0x3f000080UL, 0x3f000080UL, 0x3f000080UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL }   /* GH3 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227010UL, 0x3f400000UL, 0x3e800000UL, 0x3f400000UL, 0x3cdebc9aUL, 0UL, 0UL, 0UL }   /* GH4 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227010UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x3cdebc9aUL, 1UL, 0UL, 0UL }   /* GH1w */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227072UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x379b2ac1UL, 0UL, 0x20210000UL, 0x1903UL }   /* J1 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227072UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x379b2ac1UL, 0UL, 0x21200000UL, 0x1903UL }   /* J2 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227072UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x379b2ac1UL, 0UL, 0x21210000UL, 0x1903UL }   /* J3 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227072UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x379b2ac1UL, 0UL, 0x27260000UL, 0x1903UL }   /* J4 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227072UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x379b2ac1UL, 0UL, 0x20240000UL, 0x1903UL }   /* J5 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227072UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x379b2ac1UL, 0UL, 0x21260000UL, 0x1903UL }   /* J6 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227072UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x379b2ac1UL, 0UL, 0x27260000UL, 0x190bUL }   /* J7 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227072UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x379b2ac1UL, 0UL, 0x21212000UL, 0x1903UL }   /* J8 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227072UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x379b2ac1UL, 1UL, 0x27260000UL, 0x1903UL }   /* J9 */,
    { 0UL, 0UL, 0UL, 0UL, 0x42227072UL, 0x3f000000UL, 0x3f000000UL, 0x3f000000UL, 0x379b2ac1UL, 0UL, 0UL, 0UL }   /* J0 */
};

static const unsigned long cpR6T[32][15] = {
    { 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* XA */,
    { 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0x3d800000UL, 0x3d800000UL, 0x3f880000UL, 0x3d800000UL, 0x3d800000UL, 0x3f880000UL, 0UL, 0UL }   /* XB */,
    { 8UL, 8UL, 32UL, 0UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0UL, 0x40000000UL, 0UL, 0UL, 0x40000000UL, 0UL, 0UL }   /* XC */,
    { 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0xbe800000UL, 0xbe800000UL, 0x3fa00000UL, 0xbe800000UL, 0xbe800000UL, 0x3fa00000UL, 0UL, 0UL }   /* XD */,
    { 8UL, 8UL, 64UL, 0x11000000UL, 0x3346UL, 0x70007UL, 32UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* XE */,
    { 4UL, 4UL, 16UL, 0x11000000UL, 0x2246UL, 0x30003UL, 32UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* XF */,
    { 8UL, 8UL, 32UL, 0UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0x3f080000UL, 0x3f800000UL, 0x3f080000UL, 0UL, 0x3f080000UL, 0UL, 0UL }   /* XG */,
    { 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* PA */,
    { 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* PB */,
    { 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* PC */,
    { 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* PD */,
    { 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* PF */,
    { 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0x30000UL }   /* PH */,
    { 2UL, 2UL, 32UL, 0x11000003UL, 0x1146UL, 0x10001UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 1UL, 0UL }   /* LA */,
    { 2UL, 2UL, 32UL, 0x11000000UL, 0x1146UL, 0x10001UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 1UL, 0UL }   /* LB */,
    { 2UL, 2UL, 32UL, 3UL, 0x1146UL, 0x10001UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 1UL, 0UL }   /* LC */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3e000000UL, 0x3e000000UL, 0x3e800000UL, 0x3e000000UL, 0x3e000000UL, 0x3e800000UL, 2UL, 0UL }   /* LD */,
    { 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0x3e000000UL, 0x3e000000UL, 0x3e800000UL, 0x3e000000UL, 0x3e000000UL, 0x3e800000UL, 2UL, 0UL }   /* LE */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3e000000UL, 0x3e200000UL, 0x3e800000UL, 0x3e200000UL, 0x3e0c0000UL, 0x3e200000UL, 2UL, 0UL }   /* LF */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3e000000UL, 0x3e000000UL, 0x3e800000UL, 0x3e000000UL, 0x3e000000UL, 0x3e800000UL, 2UL, 0UL }   /* PL */,
    { 2UL, 8UL, 32UL, 0x11000000UL, 0x3146UL, 0x70001UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* LN */,
    { 8UL, 8UL, 32UL, 0x11000000UL, 0x3346UL, 0x70007UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL, 0x3f800000UL, 0UL, 0UL }   /* Q0 */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3e004000UL, 0x3e400000UL, 0x3e802000UL, 0x3e400000UL, 0x3e084000UL, 0x3e400000UL, 2UL, 0UL }   /* Q1 */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3e004000UL, 0x3e800000UL, 0x3e802000UL, 0x3e800000UL, 0x3e084000UL, 0x3e800000UL, 2UL, 0UL }   /* Q2 */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3ea00000UL, 0x3e404000UL, 0x3ea00000UL, 0x3e484000UL, 0x3ea00000UL, 0x3ea02000UL, 2UL, 0UL }   /* Q3 */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3e004000UL, 0x3e400000UL, 0x3e802000UL, 0x3e400000UL, 0x3e084000UL, 0x3e400000UL, 2UL, 0UL }   /* Q4 */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3e004000UL, 0x3e400000UL, 0x3e802000UL, 0x3e400000UL, 0x3e084000UL, 0x3e400000UL, 2UL, 0UL }   /* Q5 */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3d808000UL, 0x3e400000UL, 0x3e384000UL, 0x3e400000UL, 0x3d908000UL, 0x3e400000UL, 3UL, 0UL }   /* N1 */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3ea00000UL, 0x3d808000UL, 0x3ea00000UL, 0x3d908000UL, 0x3ea00000UL, 0x3e384000UL, 3UL, 0UL }   /* N2 */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3ea02000UL, 0x3e400000UL, 0x3edc2000UL, 0x3e400000UL, 0x3ea42000UL, 0x3e400000UL, 2UL, 0UL }   /* N3 */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3ea00000UL, 0x3ea02000UL, 0x3ea00000UL, 0x3ea42000UL, 0x3ea00000UL, 0x3edc2000UL, 2UL, 0UL }   /* N4 */,
    { 8UL, 8UL, 32UL, 0x11000003UL, 0x3346UL, 0x70007UL, 0UL, 0x3ea02000UL, 0x3e400000UL, 0x3edc2000UL, 0x3e400000UL, 0x3ea42000UL, 0x3e400000UL, 2UL, 0UL }   /* N5 */
};

/* R6i (docs/R6I_PLAN.md 2-1): a W per vertex, float32 bits -- 0 is refused (a perspective
   divide by zero); tools/r6/persp_oracle.py cpR6W */
static const unsigned long cpR6W[3][3] = {
    { 0x3f800000UL, 0x3e000000UL, 0x3f000000UL }   /* WB */,
    { 0x3f800000UL, 0x3e800000UL, 0x3e800000UL }   /* WC */,
    { 0x3f800000UL, 0x41000000UL, 0x40000000UL }   /* WF */
};

static const cpR6Case cpR6Cases[CP_R6_CASES] = {
    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, 0x3f800000UL, 0UL,     /* A: z 1.0 */
      0UL, 0UL, 3UL, 0UL, 0xc00c3500UL, 0x00030038UL, 0UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, 0x3f000000UL, 0UL,     /* B: z 0.5 */
      0UL, 0UL, 3UL, 0UL, 0xc00c3500UL, 0x00030038UL, 0UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 5, 3, 37, 21, 0x00000000UL, 0x00000000UL, 0x42800000UL, 0x42000000UL, 0x3f800000UL, 0UL,     /* C: geometry 0,0-64,32 */
      0UL, 0UL, 3UL, 0UL, 0xc00c3500UL, 0x00030038UL, 0UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 5, 3, 37, 21, 0x00000000UL, 0x00000000UL, 0x42800000UL, 0x42000000UL, 0x3f800000UL, 2UL,     /* D: C with SCISSOR_ENABLE */
      0UL, 0UL, 3UL, 0UL, 0xc00c3500UL, 0x00030038UL, 0UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 20, 12, 37, 21, 0x00000000UL, 0x00000000UL, 0x42800000UL, 0x42000000UL, 0x3f800000UL, 0UL,   /* E: TL 20,12, RE_CNTL 0 */
      0UL, 0UL, 3UL, 0UL, 0xc00c3500UL, 0x00030038UL, 0UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, 0x3f800000UL, 2UL,     /* F: A + colour, RGBA order */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030078UL, 0x78563412UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, 0x3f800000UL, 2UL,     /* G: F, order bit off */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030038UL, 0x78563412UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 5, 3, 37, 21, 0x40a00000UL, 0x40400000UL, 0x42140000UL, 0x41a80000UL, 0x3f800000UL, 2UL,     /* H: F, SE_VTX_STATE_CNTL 0 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0UL, 0xc00f3500UL, 0x00030078UL, 0x78563412UL, 0UL, 0UL, 0UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* T1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 1UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* T2 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 2UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* T3 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x00060074UL, 0UL, 3UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* T4 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x00060074UL, 0UL, 4UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* T5 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 5UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* T6 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 6UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* X1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 7UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* X2 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 8UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* X3 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 9UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* X4 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 10UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* X5 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 11UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* X6 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 12UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* X7 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 13UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* X8 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 14UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* Y1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 15UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* T7 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 16UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* T1r */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 17UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* G0 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 18UL, 0UL, 0UL, 0x48005adeUL, 0xfUL, 0x3c9abcdeUL, 0x0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* G1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 19UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* G2 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 20UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* G3 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 21UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* S1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 22UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* S2 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 23UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* S3 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 24UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* S4 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 25UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* S5 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 26UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* S6 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 27UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* S7 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 28UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* S8 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 29UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* H1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 30UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* H2 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 31UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* P1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 32UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 33UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* E1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 34UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* E2 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 35UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* E3 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 36UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* E4 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 37UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* G4 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 38UL, 0UL, 0UL, 0x48005adeUL, 0x2UL, 0x78120056UL, 0x2UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* G5 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 39UL, 0UL, 0UL, 0x48005adeUL, 0x1UL, 0x78123400UL, 0x1UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* G7 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 40UL, 0UL, 0UL, 0x48005adeUL, 0xfUL, 0x00000000UL, 0xfUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* G7p */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 41UL, 0UL, 0UL, 0x48005adeUL, 0xfUL, 0x00000000UL, 0xfUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* V1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 42UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* V2 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 43UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* V3 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 44UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* V4 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 45UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* V5 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 46UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* V6 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 47UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* V7 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 48UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* V8 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 49UL, 0UL, 0UL, 0x48005adeUL, 0xfUL, 0x00000000UL, 0xfUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* D1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 50UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* D2 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x00030074UL, 0UL, 51UL, 0UL, 0UL, 0x48005adeUL, 0xcUL, 0x00003456UL, 0xcUL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* K16a */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0f03500UL, 0x300074UL, 0x78563412UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 0UL, 1UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* K16b */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0f03500UL, 0x300074UL, 0x78563412UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 0UL, 2UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* K16c */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0f03500UL, 0x300074UL, 0x78563412UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 0UL, 3UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* K16d */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0f03500UL, 0x300074UL, 0x78563412UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 0UL, 4UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* K24a */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0f03500UL, 0x300074UL, 0x78563412UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 0UL, 1UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* K24b */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0f03500UL, 0x300074UL, 0x78563412UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 0UL, 2UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* K24c */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0f03500UL, 0x300074UL, 0x78563412UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 0UL, 3UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* K24d */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0f03500UL, 0x300074UL, 0x78563412UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 0UL, 4UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I1_24 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 1UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I2_24 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 2UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I3_24 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 53UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 3UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I4_24 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 54UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 4UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I5_24 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 55UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 5UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I6_24 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 56UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 6UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I7_24 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 55UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 7UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I1_16 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 1UL, 0UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I2_16 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 2UL, 0UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I3_16 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 53UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 3UL, 0UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I4_16 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 54UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 4UL, 0UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I5_16 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 55UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 5UL, 0UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I6_16 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 56UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 6UL, 0UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* I7_16 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 55UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 7UL, 0UL, 2UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* GN */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227000UL, 0UL, 0UL, 2UL, 0x1902UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* GL */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227010UL, 0UL, 0UL, 2UL, 0x1902UL, 2UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* GLE */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227020UL, 0UL, 0UL, 2UL, 0x1902UL, 3UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* GE */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227030UL, 0UL, 0UL, 2UL, 0x1902UL, 4UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* GGE */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227040UL, 0UL, 0UL, 2UL, 0x1902UL, 5UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* GG */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227050UL, 0UL, 0UL, 2UL, 0x1902UL, 6UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* GNE */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227060UL, 0UL, 0UL, 2UL, 0x1902UL, 7UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* GA */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 0UL, 0UL, 2UL, 0x1902UL, 8UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* GLW */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x2227010UL, 0UL, 0UL, 2UL, 0x1902UL, 9UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* GAW */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x2227070UL, 0UL, 0UL, 2UL, 0x1902UL, 10UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* GZE */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227010UL, 0UL, 0UL, 2UL, 0x1802UL, 11UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000080UL, 2UL,     /* GF */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227030UL, 0UL, 0UL, 2UL, 0x1902UL, 12UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000080UL, 2UL,     /* GFG */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227050UL, 0UL, 0UL, 2UL, 0x1902UL, 13UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* GI */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227010UL, 1UL, 0UL, 2UL, 0x1902UL, 14UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* G24 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227012UL, 0UL, 0UL, 1UL, 0x1902UL, 15UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f666666UL, 2UL,     /* GH1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 0UL, 0UL, 2UL, 0x1902UL, 16UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3e800000UL, 2UL,     /* GH2 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x2227010UL, 0UL, 0UL, 2UL, 0x1902UL, 17UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000080UL, 2UL,     /* GH3 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 0UL, 0UL, 2UL, 0x1902UL, 18UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL,     /* GH4 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 1UL, 0UL, 2UL, 0x1902UL, 19UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f666666UL, 2UL,     /* GH1w */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 3UL, 0UL, 0UL, 0x42227070UL, 0UL, 0UL, 2UL, 0x1902UL, 20UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* XA */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* XB */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 2UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* XC */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 3UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* XD */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 4UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* XE */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 5UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* XF */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 6UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* XG */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 7UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 10UL,     /* PA */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 8UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 10UL,     /* PB */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 9UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 10UL,     /* PC */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 10UL, 2UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* PD */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 11UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 10UL,     /* PF */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 12UL, 3UL, 0x700UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* PH */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 13UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 10UL,     /* PE */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 49UL, 0UL, 0UL, 0x48005adeUL, 15UL, 0UL, 15UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* LA */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 14UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* LB */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 15UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* LC */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 16UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* LD */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 17UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* LE */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 18UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* LF */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 19UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 10UL,     /* PL */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 20UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0UL, 10UL,     /* PZ */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 52UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 1UL, 0UL, 1UL, 0x1902UL, 0UL, 0UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* LN */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 21UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* Q0 */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 22UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* Q1 */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 23UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* Q2 */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 24UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* Q3 */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 25UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 10UL,     /* Q4 */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 26UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* Q5 */
      0x1410UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 27UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* N1 */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 28UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* N2 */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 29UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* N3 */
      0x1410UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 30UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* N4 */
      0x1410UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 31UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* N5 */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 57UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 32UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* J1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 58UL, 0UL, 0UL, 0x48005adeUL, 15UL, 0UL, 15UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 21UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* J2 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 58UL, 0UL, 0UL, 0x48005adeUL, 15UL, 0UL, 15UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 22UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* J3 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 58UL, 0UL, 0UL, 0x48005adeUL, 15UL, 0UL, 15UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 23UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* J4 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 58UL, 0UL, 0UL, 0x48005adeUL, 15UL, 0UL, 15UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 24UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* J5 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 58UL, 0UL, 0UL, 0x48005adeUL, 15UL, 0UL, 15UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 25UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* J6 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 58UL, 0UL, 0UL, 0x48005adeUL, 15UL, 0UL, 15UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 26UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* J7 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 58UL, 0UL, 0UL, 0x48005adeUL, 15UL, 0UL, 15UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 27UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* J8 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 58UL, 0UL, 0UL, 0x48005adeUL, 15UL, 0UL, 15UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 28UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* J9 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 58UL, 0UL, 0UL, 0x48005adeUL, 15UL, 0UL, 15UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 29UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* J0 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc00f3500UL, 0x30074UL, 0UL, 58UL, 0UL, 0UL, 0x48005adeUL, 15UL, 0UL, 15UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 30UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    /* R6k (docs/R6K_PLAN.md 4): the auxiliary scissor */
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M0 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M1 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M2 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 2UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M3 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 3UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M4 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 4UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M5 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 5UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M6 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 6UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 32, 32, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M7 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 60UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 7UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000001UL, 2UL,     /* M8 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 7UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 1UL, 0x1902UL, 15UL, 0UL, 0UL, 0UL, 8UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M9 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 9UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M10 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 10UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 20, 13, 7, 4, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M11 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 0UL,     /* M12 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 11UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M13 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 12UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* M14 */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc01e3500UL, 0x60074UL, 0UL, 59UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 13UL, 0UL, 0UL, 0UL, 0UL, 0UL },
    /* R6l (docs/R6L_PLAN.md 4): batching */
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* BA */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0UL, 0UL, 0UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 1UL, 1UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* BB */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0UL, 0UL, 0UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 2UL, 1UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* BC */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0UL, 0UL, 0UL, 0UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 3UL, 8UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* BD */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0UL, 0UL, 0UL, 0UL, 0x78123456UL, 0x3c9abcdeUL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 11UL, 8UL, 0UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* BF */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0UL, 0UL, 0UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 19UL, 1UL, 0UL, 0UL, 0UL },
    /* R6m (docs/R6M_PLAN.md 4): buffer reuse -- the same draws, the surfaces moved */
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* MA -- the colour surface moved */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0UL, 0UL, 0UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 19UL, 1UL, 0x8010UL, 0UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* MB -- the depth surface moved */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0UL, 0UL, 0UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 19UL, 1UL, 0UL, 0x10000UL, 0UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* MC -- the texture surface moved */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0x14020UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f000000UL, 2UL,     /* MD -- all three moved at once */
      0x1010UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0xc0153500UL, 0x30074UL, 0UL, 52UL, 0UL, 0UL, 0x480055deUL, 15UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 1UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0x8010UL, 0x10000UL, 0x14020UL },
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* ME -- nothing moved (the regression) */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0UL, 0UL, 0UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 19UL, 1UL, 0UL, 0UL, 0UL },
    /* R7a (docs/R7_PLAN.md 4): the client's stream.  The row carries only the READ-BACK
       parameters -- T1's colour and clip, so the coverage map means what it did for T1 --
       and no geometry at all: hdr, vf and tri are zero because the words come from the
       client's staging buffer. */
    { 0, 0, 64, 64, 0UL, 0UL, 0UL, 0UL, 0x3f800000UL, 2UL,     /* UC */
      0x1000UL, 0xffffffffUL, 0x803UL, 0x10000UL, 0UL, 0UL, 0UL, 0UL, 0x78123456UL, 0x78123456UL, 0x480055deUL, 0UL, 0UL, 0UL, 0x42227072UL, 0UL, 0UL, 0UL, 0x1902UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL, 0UL }
};

/* REC3D: surface and 3D registers, read only (the log prints their offsets from here) */
const unsigned short osrdnCpR3Regs[CP_R6_REC_COUNT] = {
    0x0b00, 0x0b04, 0x0b08, 0x0b0c, 0x0b14, 0x0b18, 0x0b1c, 0x0b24, 0x0b28, 0x0b2c, 0x0b34, 0x0b38,
    0x0b3c, 0x0b44, 0x0b48, 0x0b4c, 0x0b54, 0x0b58, 0x0b5c, 0x0b64, 0x0b68, 0x0b6c, 0x0b74, 0x0b78,
    0x0b7c, 0x1c14, 0x1c18, 0x1c1c, 0x1c20, 0x1c24, 0x1c28, 0x1c2c, 0x1c38, 0x1c3c, 0x1c40, 0x1c44,
    0x1c48, 0x1c4c, 0x1c50, 0x1cd8, 0x1cdc, 0x1d60, 0x1d7c, 0x1d80, 0x1d84, 0x2080, 0x2088, 0x208c,
    0x20b0, 0x2140, 0x2180, 0x26c0, 0x26c4, 0x26f0, 0x2c1c, 0x2cc4, 0x3250, 0x3254, 0x3258, 0x325c,
    0x2f00, 0x2f04, 0x2f08, 0x2f0c,                                     /* R6c: blend stage 0, recorded */
    0x2cf8, 0x2cfc, 0x2c00, 0x2c04,                                     /* G4-7: TRI_PERF, PERF_CNTL; TXFILTER_0, TXFORMAT_0 */
    0x2d9c, 0x2c08, 0x2c0c, 0x2c10                                      /* G4-9: TAM_DEBUG3; TXFORMAT_X_0, TXSIZE_0, TXPITCH_0 */
};

/* R6m (docs/R6M_PLAN.md 7): where a case's surfaces are.  Every read-back and every register that
   names a surface goes through these three, so moving a surface moves BOTH the draw and the check;
   a zero in the row means the place the whole ladder used before R6m. */
static unsigned long
cpR6ColorOff(const cpR6Case *cs)
{
    return (cs != 0 && cs->coff != 0UL) ? cs->coff : CP_R6_COLOR_OFF;
}

static unsigned long
cpR6DepthOff(const cpR6Case *cs)
{
    return (cs != 0 && cs->zoff != 0UL) ? cs->zoff : CP_R6_DEPTH_OFF;
}

static unsigned long
cpR6TexOff(const cpR6Case *cs)
{
    return (cs != 0 && cs->toff != 0UL) ? cs->toff : CP_R6_TEX_OFF;
}

/* the prefix registers ZCLEAR reads back before it draws (zclear_oracle.py prefix_expect) */
static const unsigned short cpR6PreRegs[CP_R6_PRE_COUNT] = {
    C_RB3D_DEPTHOFFSET, C_RB3D_DEPTHPITCH, C_RB3D_COLOROFFSET, C_RB3D_COLORPITCH,
    C_SE_VAP_CNTL_STATUS, C_PP_CNTL_X, C_PP_TXMULTI_CTL_0, C_SE_VTX_STATE_CNTL,
    C_RB3D_DEPTHXY_OFFSET,
    C_PP_TRI_PERF, C_PP_PERF_CNTL,     /* G4-7: at the END, so bits 0-8 and CP_R6_PRE_GATE keep their meaning;
                                          recorded (bits 9, 10), never gated -- cpR6PreWant answers 0 */
    C_PP_TAM_DEBUG3                     /* G4-9: bit 11, recorded; cpR6PreWant answers C_PP_TAM_DEBUG3_LRU */
};

static unsigned long
cpR6Pattern(unsigned long i)
{
    return 0xa5000000UL | (i & 0xffffUL);
}

/* R6h: the texel the CPU writes (tools/r6/tex_oracle.py texel(), R6i persp_oracle.py texel()) --
   distinct, and never a pattern word because the alpha byte is 0xff (docs/R6H_PLAN.md 2-1).
   R6i patterns (docs/R6I_PLAN.md 2-1): 1 tells the four corners of a 2x2 apart, 2 puts u in R and
   v in G so one channel carries one axis' weight */
static unsigned long
cpR6Texel(unsigned long pat, unsigned long u, unsigned long v)
{
    if (pat == 1UL)
        return 0xff000000UL | ((255UL * (u & 1UL)) << 16) | ((255UL * (v & 1UL)) << 8) |
               (255UL * (u & 1UL) * (v & 1UL));
    if (pat == 2UL)
        return 0xff000000UL | ((255UL * (u & 1UL)) << 16) | ((255UL * (v & 1UL)) << 8) | 0x55UL;
    if (pat == 3UL)                             /* R6i-3: pattern 2 transposed (docs/R6I3_PLAN.md 2-1) */
        return 0xff000000UL | ((255UL * (v & 1UL)) << 16) | ((255UL * (u & 1UL)) << 8) | 0x55UL;
    return 0xff000000UL | ((u * 32UL) << 16) | ((v * 32UL) << 8) | 0x55UL;
}

/* no switch: cc makes a dense one a jump table, which the reloc gate refuses */
static unsigned long
cpR6PreWant(const osrdn_cp_state *c, int k)
{
    const cpR6Case *cs = (c->zcase >= 1 && c->zcase <= CP_R6_CASES) ? &cpR6Cases[c->zcase - 1] : 0;

    if (k == 0)
        return c->winStart + cpR6DepthOff(cs);      /* R6m: the case's depth surface */
    if (k == 2)
        return c->winStart + cpR6ColorOff(cs);      /* R6m: the case's colour surface */
    if (k == 1 || k == 3)
        return CP_R6_PITCH;
    if (k == 7 && c->zcase >= 1 && c->zcase <= CP_R6_CASES)
        return cpR6Cases[c->zcase - 1].vsc;     /* SE_VTX_STATE_CNTL (R6c H) */
    if (k == 11)
        return C_PP_TAM_DEBUG3_LRU;            /* G4-9: what the prefix wrote, read back for the record */
    return 0UL;
}

/* words to the ring at wptr, padded with PACKET2 to a multiple of 16, then the
   R5 waits; a bound with the CSQ on latches.

   M3f (docs/M3F_PLAN.md): THE SUBMISSION WRAPS PAST THE RING'S END, as FreeBSD's
   OUT_RING (write &= mask) and radeon_commit_ring (PACKET2 to 16-word
   alignment only) do.  This used to fill the rest of the ring with PACKET2 and
   start again at 0, out of caution -- no 3D packet had crossed the end on the
   machine.  M3e measured that path latch the CP on its first word: a 48-word
   fill at 4048 (docs/M3E_PLAN.md 8), while the machine's own R5 run had
   already wrapped 1024 words from 3088 to 16 with nothing filled
   (docs/R5_PLAN.md 13).  cpPut masks the index, so the words land in order. */
static int
cpR6Submit(osrdn_cp_state *c, vm_address_t base, const unsigned long *w, unsigned long n)
{
    unsigned long p = c->wptr, k, len, target;
    ns_time_t f0, f1;                   /* M1z: the fence's OWN clock */
    ns_time_t q0, q1;                   /* M2b: the put loops' own clock */
    unsigned long qUs, fUs;             /* M2c: held until the submission survives */

    f0 = 0;
    f1 = 0;
    q0 = 0;
    q1 = 0;
    qUs = 0;
    fUs = 0;
    len = (n + 15UL) & ~15UL;
    /* G5-2: an accepted submission may still be in the ring -- wait for room, not for empty */
    if (!cpWaitSpace(c, base, len))
        return cpFail(c, base);
    /* M2b: what the ring stages still hold after the fence and the waits was
       44.12 us that nobody had measured -- a subtraction.  This is the half of
       it that writes words; the doorbell and the posting read are then the only
       thing left unnamed. */
    if (c->tOn)
        IOGetTimestamp(&q0);
    for (k = 0; k < len; k++)
        cpPut(c, p + k, (k < n) ? w[k] : CP_PACKET2);
    if (c->tOn) {
        IOGetTimestamp(&q1);
        qUs = cpElapsedUs(q0, q1);          /* M2c: held, not committed yet */
    }
    /*
     * M1z (docs/M1Z_PLAN.md 5-1): cpFence is one WBINVD (osrdn_cpu.m), and on
     * this machine -- a Celeron 2.66 GHz, not the 486 hostinfo names -- that is
     * the biggest unexplained piece of the 113 us a ring submission costs.
     *
     * It is timed with ITS OWN pair of timestamps, NOT with cpTMark: cpTMark
     * ends one interval and starts the next by writing through its `t` argument,
     * so using the caller's chain clock here would move time between cpZclear's
     * existing buckets and silently rewrite the numbers M1x measured.
     */
    if (c->tOn)
        IOGetTimestamp(&f0);
    cpSubmitFence(c, base);
    if (c->tOn) {
        IOGetTimestamp(&f1);
        fUs = cpElapsedUs(f0, f1);          /* M2c: held, not committed yet */
    }
    target = (p + len) & C_RPTR_MASK;
    rdnMmioWrite32(base, C_CP_RB_WPTR, target);
    (void)rdnMmioRead32(base, C_CP_RB_RPTR);    /* posting */
    c->wptr = target;
    c->wptrAfter = target;
    /* M3i: did the doorbell take? (docs/M3I_PLAN.md 3 D2); M3j: a wait that runs out recovers */
    c->wptrRead = rdnMmioRead32(base, C_CP_RB_WPTR) & C_RPTR_MASK;
    if (c->wptrRead != target) {
        (void)cpRefuse(c, CP_WHY_WPTR, c->wptrRead);
        return cpFail(c, base);
    }
    /* G5-2: accepted.  The next ring contact queues behind it; RETIRE waits for it */
    if (c->noWait)
        return CP_RC_RAN;
    if (!cpWait(base, W_RPTR, target, C_RPTR_US, &c->wRptr))
        return cpFail(c, base);
    if (!cpWaitRetry(base, W_IDLE, 0, C_IDLE_US, C_IDLE_RETRY, &c->wIdle))     /* G4-3 K1 */
        return cpFail(c, base);
    /*
     * M1z: the two waits ALREADY measured themselves (cpWait fills w->us), so
     * this total costs an add and not one more clock read.
     *
     * M2c: AND THE OTHER TWO ARE COMMITTED HERE TOO.  The comment that used to
     * sit here said a latched submission "is not counted" -- true of the waits,
     * FALSE of the put and the fence, which were added further up and stayed
     * there when a failed wait returned.  tAccN counts only submissions that
     * reach the end, so an accumulator that counted more was a numerator
     * without its denominator.  Now all three are committed on the one path
     * that also reaches tAccN.
     */
    if (c->tOn) {
        c->tAcc[CP_T_PUT] += qUs;
        c->tAcc[CP_T_FENCE] += fUs;
        c->tAcc[CP_T_WAIT] += c->wRptr.us + c->wIdle.us;
    }
    c->inflight = 0;                    /* G5-2: the ring and the engine drained -- everything accepted is done */
    c->rptrAfter = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;
    return CP_RC_RAN;
}

/* digest of alias words [first, first + count): what tools/r6/zclear_oracle.py
   digest() computes from the expected block */
static void
cpR6Digest(const osrdn_cp_state *c, unsigned long first, unsigned long count, osrdn_cp_digest *d)
{
    volatile unsigned long *a = (volatile unsigned long *)c->alias;
    unsigned long k, w;
    int j, seen;

    d->xr = d->wsum = d->changed = d->ixor = d->isum = 0;
    d->nvals = 0;
    for (j = 0; j < 4; j++)
        d->vals[j] = 0;
    for (k = 0; k < count; k++) {
        w = a[first + k];
        d->xr ^= w;
        d->wsum += w * (2UL * k + 1UL);
        if (w == cpR6Pattern(first + k))
            continue;
        d->changed++;
        d->ixor ^= k;
        d->isum += k;
        seen = 0;
        for (j = 0; j < d->nvals; j++)
            if (d->vals[j] == w)
                seen = 1;
        if (!seen && d->nvals < 4)
            d->vals[d->nvals++] = w;
    }
}

static int
cpRec3d(osrdn_cp_state *c, vm_address_t base)
{
    int k;

    if (!c->key3d)
        return cpRefused(c, CP_WHY_NO_3D, 0);
    if (!cpIdleGate(c, base, 0))
        return CP_RC_REFUSED;
    for (k = 0; k < CP_R6_REC_COUNT; k++)
        c->r3[k] = rdnMmioRead32(base, osrdnCpR3Regs[k]);
    c->surfaceCntl = c->r3[0];
    return CP_RC_RAN;
}

/* the CPU fills the block with the pattern and reads it back; the GPU must be idle */
static int
cpZprep(osrdn_cp_state *c, vm_address_t base)
{
    volatile unsigned long *a = (volatile unsigned long *)c->alias;
    unsigned long i;

    if (!c->key3d || c->alias == 0)
        return cpRefused(c, CP_WHY_NO_3D, 0);
    if (c->state != CP_ST_RUNNING)          /* R4 engine operations are refused meanwhile (8-2 m5) */
        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);
    if (!cpIdleGate(c, base, 0))
        return CP_RC_REFUSED;
    for (i = 0; i < CP_R6_ALIAS_BYTES / 4UL; i++)
        a[i] = cpR6Pattern(i);
    cpFence(base);
    c->prepBad = 0;
    for (i = 0; i < CP_R6_ALIAS_BYTES / 4UL; i++)
        if (a[i] != cpR6Pattern(i))
            c->prepBad++;
    c->zprepped = (c->prepBad == 0UL);
    return c->zprepped ? CP_RC_RAN : cpRefused(c, CP_WHY_PATTERN, c->prepBad);
}

/* R6f (docs/R6F_PLAN.md 3-2): ZCLEAR's words -- a file static, not the stack (the grid case needs
   290); only cpZclear touches it, and cpZclear runs only under the mode claim (plan 4: its one
   caller osrdn_cp_run is called only by osrdn_mode_cp after modeClaim) */
static unsigned long cpR6Words[CP_R6_WORDS];

/* R6f: Mesa 6.5.3 r200_span.c r200_mba_z32 / r200_mba_z16 (depthHasSurface false), byte
   offsets in the depth buffer; tools/r6/depth_oracle.py and the simulator compute the same */
static unsigned long
cpMbaZ32(unsigned long pitch, unsigned long x, unsigned long y)
{
    unsigned long b = ((y & 0x7ffUL) >> 4) * ((pitch & 0xfffUL) >> 5) + ((x & 0x7ffUL) >> 5);
    unsigned long par = (pitch & 0x20UL) ? (b & 1UL) : ((b & 1UL) ^ ((y >> 4) & 1UL));

    return (((x >> 0) & 1UL) << 2) | (((y >> 0) & 1UL) << 3) | (((x >> 1) & 1UL) << 4) | (((y >> 1) & 1UL) << 5) |
           (((x >> 3) & 1UL) << 6) | (((x >> 4) & 1UL) << 7) | (((x >> 2) & 1UL) << 8) | (((y >> 2) & 1UL) << 9) |
           (((y >> 3) & 1UL) << 10) | (par << 11) | ((b >> 1) << 12);
}

static unsigned long
cpMbaZ16(unsigned long pitch, unsigned long x, unsigned long y)
{
    unsigned long b = ((y & 0x7ffUL) >> 4) * ((pitch & 0xfffUL) >> 6) + ((x & 0x7ffUL) >> 6);
    unsigned long par = (pitch & 0x40UL) ? (b & 1UL) : ((b & 1UL) ^ ((y >> 4) & 1UL));

    return (((x >> 0) & 1UL) << 1) | (((y >> 0) & 1UL) << 2) | (((x >> 1) & 1UL) << 3) | (((y >> 1) & 1UL) << 4) |
           (((x >> 2) & 1UL) << 5) | (((x >> 4) & 1UL) << 6) | (((x >> 5) & 1UL) << 7) | (((x >> 3) & 1UL) << 8) |
           (((y >> 2) & 1UL) << 9) | (((y >> 3) & 1UL) << 10) | (par << 11) | ((b >> 1) << 12);
}

#define CP_R6_GRIDS     (sizeof cpR6GridZ / sizeof cpR6GridZ[0])
#define CP_R6_ZROWS     (sizeof cpR6Zv / sizeof cpR6Zv[0])
#define CP_R6_CELLS     (sizeof cpR6Cells / sizeof cpR6Cells[0])
#define CP_R6_TROWS     (sizeof cpR6T / sizeof cpR6T[0])
#define CP_R6_WROWS     (sizeof cpR6W / sizeof cpR6W[0])
/* R6h: the texture registers (Mesa r200_reg.h; docs/R6H_PLAN.md X1) */
#define C_PP_TXFILTER_0         0x2c00
#define C_PP_TXFORMAT_0         0x2c04
#define C_PP_TXFORMAT_X_0       0x2c08
#define C_PP_TXSIZE_0           0x2c0c
#define C_PP_TXPITCH_0          0x2c10
#define C_PP_TXOFFSET_0         0x2d00
#define C_SE_VTX_FMT_1          0x208c
#define C_VTX_FMT_1_ST          0x00000002UL    /* R6h: two components on texture unit 0 */
#define C_TXBLEND_TEXTURE       0x0010000aUL    /* R6h: MADD, arg A = R0 (the texel), arg B = ~0 (docs/R6H_PLAN.md X3) */

/* R7a (docs/R7_PLAN.md 4): the registers a client may write -- the 49 the R6 ladder
   measured, less the 7 the driver keeps for itself.  GENERATED by
   tools/r7/verify_oracle.py --c-tables; check_r7_src.py compares the two. */
static const unsigned short cpR7Allow[42] = {
    0x1c14, 0x1c20, 0x1c24, 0x1c28, 0x1c2c, 0x1c38, 0x1c3c, 0x1c40,
    0x1c44, 0x1c48, 0x1c4c, 0x1c50, 0x1cd8, 0x1cdc, 0x1ce0, 0x1ce4,
    0x1ce8, 0x1cec, 0x1d60, 0x1d7c, 0x1d84, 0x2080, 0x2088, 0x208c,
    0x20b0, 0x2140, 0x2180, 0x2284, 0x26c0, 0x26f0, 0x2c00, 0x2c04,
    0x2c08, 0x2c0c, 0x2c10, 0x2c1c, 0x2cc4, 0x2d00, 0x2f00, 0x2f04,
    0x2f08, 0x2f0c
};
#define CP_R7_ALLOW_COUNT        42

/* the 7 a client may NOT write, named so the reason is readable in review */
/*   0x15e0 SCRATCH_REG0 */
/*   0x1720 WAIT_UNTIL */
/*   0x2cf8 PP_TRI_PERF (G4-7) */
/*   0x2cfc PP_PERF_CNTL (G4-7) */
/*   0x2d9c PP_TAM_DEBUG3 (G4-9) */
/*   0x3254 RB3D_ZCACHE_CTLSTAT */
/*   0x325c RB3D_DSTCACHE_CTLSTAT */


/* R7a (docs/R7_PLAN.md 4): the client's staged stream, and the verifier that decides whether any
   of it may reach the ring.

   Nothing here touches the hardware.  It reads the staged words, and either returns 0 -- after
   which cpZclear copies them -- or a CP_R7_WHY_* saying which rule refused, with c->r7At holding
   the word it stopped at.  The whole stream is judged before one word is copied, so a refusal
   leaves the surfaces exactly as ZPREP left them (docs/R7_PLAN.md 2-1 C).

   The register allow-list is GENERATED from the registers the R6 ladder measured
   (tools/r7/verify_oracle.py --c-tables); check_r7_src.py compares the two, so a register nobody
   measured cannot become legal by being typed in here. */

static unsigned long cpR7Buf[CP_R7_BATCH_MAX];

static int
cpR7RegAllowed(unsigned long reg)
{
    unsigned long k;

    for (k = 0; k < (unsigned long)CP_R7_ALLOW_COUNT; k++)
        if ((unsigned long)cpR7Allow[k] == reg)
            return 1;
    return 0;
}

/* An allowed register is not an allowed VALUE.  These four values reach state the verifier cannot
   check: texture units whose offsets it never sees, an execution path nobody measured, and
   samplers that read past the area it did check (docs/R7_PLAN.md 4 rule 4). */
static int
cpR7ValueAllowed(unsigned long reg, unsigned long val)
{
    /*
     * M3h (docs/M3H_PLAN.md 3-4): the three ways an allowed register moves or widens what the card
     * writes past offset + pitch x rows.  A pitch word carrying anything but the pitch -- colour
     * tiling and microtiling, depth HyperZ, the endian fields -- and the depth XY offset with the
     * RB3D_CNTL bit that switches it on.  The footprint below is only true without them.
     */
    if ((reg == C_RB3D_COLORPITCH || reg == C_RB3D_DEPTHPITCH) && (val & ~CP_R7_PITCH_MASK) != 0UL)
        return 0;
    if (reg == C_RB3D_CNTL && (val & CP_R7_RB3D_XY_OFFSET) != 0UL)
        return 0;
    if (reg == C_RB3D_DEPTHXY_OFFSET && val != 0UL)
        return 0;
    if (reg == C_PP_CNTL && (val & CP_R7_PP_CNTL_TEX_1_5) != 0UL)
        return 0;                       /* units 1-5 would sample PP_TXOFFSET_1..5, never validated */
    if (reg == C_SE_VAP_CNTL && (val & CP_R7_VAP_TCL) != 0UL)
        return 0;                       /* TCL on: a path this project has never measured */
    if (reg == C_PP_TXFORMAT_0 && (val & CP_R7_TXFORMAT_CUBIC) != 0UL)
        return 0;                       /* a cube map reads five more faces */
    if (reg == C_PP_TXFILTER_0 && (val & CP_R7_TXFILTER_UNMEASURED) != 0UL)
        return 0;                       /* G4-4 K5: anisotropy, unnamed bits, YUV -- never measured */
    if (reg == C_PP_TXFORMAT_0 && (val & CP_R7_TXFORMAT_FMT_MASK) != CP_R7_TXFORMAT_ARGB8888)
        return 0;                       /* G4-3 K3: 4 bytes a texel is the only layout measured (R6h) */
    if (reg == C_PP_MISC && (val & ~CP_R7_PP_MISC_FIELDS) != 0UL)
        return 0;                       /* G4-3 K2: only the alpha reference and compare */
    return 1;
}

/*
 * G4-3 K3: the bytes a texture occupies, from the registers the card reads it with.  Level i of a
 * non-tiled 2D ARGB8888 texture is ((w >> i) * 4 rounded to 32) x (h >> i) bytes, each level starts
 * 32-byte aligned and the chain is contiguous from TXOFFSET (r200SetTexImages, r200_texstate.c
 * 271-278; no per-level offset register exists on the R200).  0 when the words describe something
 * this driver has not measured.
 */
static unsigned long
cpR7TextureBytes(unsigned long tfmt, unsigned long tfil)
{
    unsigned long lw = (tfmt >> CP_R7_TXFORMAT_W_SHIFT) & 15UL, lh = (tfmt >> CP_R7_TXFORMAT_H_SHIFT) & 15UL;
    unsigned long levels = ((tfil >> CP_R7_TXFILTER_MIP_SHIFT) & 15UL) + 1UL;
    unsigned long i, w, h, row, bytes = 0UL;

    if ((tfmt & CP_R7_TXFORMAT_FMT_MASK) != CP_R7_TXFORMAT_ARGB8888)
        return 0UL;
    if (lw > CP_R7_TXFORMAT_LOG2_MAX || lh > CP_R7_TXFORMAT_LOG2_MAX)
        return 0UL;
    if (levels > (lw > lh ? lw : lh) + 1UL)
        return 0UL;                     /* more levels than the base can halve into */
    for (i = 0UL; i < levels; i++) {
        w = (lw > i) ? (1UL << (lw - i)) : 1UL;
        h = (lh > i) ? (1UL << (lh - i)) : 1UL;
        row = (w * 4UL + 31UL) & ~31UL;
        bytes = ((bytes + 31UL) & ~31UL) + row * h;
    }
    return bytes;
}

/* the texture at toff, described by tfmt/tfil, lies inside the client's window */
static int
cpR7TextureFits(const osrdn_cp_state *c, unsigned long toff, unsigned long tfmt, unsigned long tfil)
{
    unsigned long bytes = cpR7TextureBytes(tfmt, tfil);

    if (bytes == 0UL || (toff & CP_R7_TXO_LOW_MASK) != 0UL)
        return 0;
    if (toff < c->r7WinStart || toff > c->r7WinEnd)
        return 0;
    return (c->r7WinEnd - toff) >= bytes;
}

/* Words per vertex, from SE_VTX_FMT_0/1.  0 means "a field whose width this project has never
   measured" -- a normal, a weight count, a floating colour.  Guessing one wrong either refuses a
   legal stream or, worse, lets a short one through and the CP reads past the vertices
   (docs/R7_PLAN.md 4-1 b). */
static unsigned long
cpR7VertexWords(unsigned long fmt0, unsigned long fmt1)
{
    unsigned long n, unit, k, colour;

    if ((fmt0 & ~CP_R7_VTX0_ALLOWED) != 0UL)
        return 0UL;
    colour = (fmt0 >> 11) & 3UL;
    if (colour > 1UL)                   /* NOT_PRESENT or PK_RGBA; FP_RGB(A) unmeasured */
        return 0UL;
    n = 2UL;                            /* R200_VTX_XY: always there */
    if ((fmt0 & 1UL) != 0UL)
        n++;                            /* Z0 */
    if ((fmt0 & 2UL) != 0UL)
        n++;                            /* W0 */
    n += colour;
    for (unit = 0; unit < 6UL; unit++) {
        k = (fmt1 >> (3UL * unit)) & 7UL;
        if (k != 0UL && k != 2UL)       /* only two ST components have been measured */
            return 0UL;
        n += k;
    }
    if ((fmt1 >> 18) != 0UL)
        return 0UL;
    return n;
}

/* A surface's footprint, not its width and height: the pitch is the client's to set, so a small
   picture at a large pitch runs off the window from the second row on (docs/R7_PLAN.md 4 rule 7).

   M3h: THE ROWS ARE THE STREAM'S OWN CLIP, not 64.  The card draws rows 0 .. height of
   RE_WIDTH_HEIGHT and nothing below (the scissors only take away), and a width wider than the
   pitch would carry the last row on into the next -- so it is refused.  Four bytes a pixel is the
   widest colour format (ARGB8888) and covers 16- and 32-bit depth; depth is tiled, so its rows
   go up to the next 16 and its pitch must be whole 32-pixel tiles, as the reference allocates it
   (xf86 radeon_accel.c 1187-1189).  COLOROFFSET's low four bits are dropped by the card. */
static int
cpR7SurfaceFits(const osrdn_cp_state *c, unsigned long off, unsigned long pitch,
                unsigned long rows, unsigned long cols, int depth)
{
    unsigned long p = pitch & CP_R7_PITCH_MASK, r = rows, span;

    off &= ~0xfUL;
    if (p == 0UL || cols > p || r == 0UL)
        return 0;
    if (depth) {
        if ((p & 31UL) != 0UL)
            return 0;
        r = (r + 15UL) & ~15UL;
    }
    if (p > 0xFFFFFFFFUL / 4UL / r)
        return 0;
    span = p * 4UL * r;
    if (off < c->r7WinStart || off > c->r7WinEnd)
        return 0;
    return (c->r7WinEnd - off) >= span;
}

/*
 * G4-4 K7 (docs/G4_4_KERNEL_PLAN.md 3): the surfaces a draw would touch, judged with the values
 * in force AT THAT DRAW.  Until K7 this ran once after the loop, on the last values, so a stream
 * that pointed a surface outside the window, drew, and pointed it back again passed (found by
 * the G4-2 plan's review).  It still runs after the loop as well: the last draw's judgement is
 * then made twice, and there is no way for the two to disagree.
 *
 * M3h: the clip must be the stream's own -- the card keeps the last one it was given, and that
 * may be another client's -- and it is read as the whole half-word, not the 11 bits a scissor
 * field was measured to use: a wider guess only makes the footprint larger.
 * G4-3 K3: a texture's footprint is what its format says it is, not a fixed 1 KiB (which let a
 * 512 x 512 image read a megabyte past the window unseen); a stream that points at texels
 * without stating their shape has no footprint to judge and is refused.
 */
static int
cpR7SurfacesOk(const osrdn_cp_state *c, unsigned long coff, unsigned long cpitch,
               unsigned long zoff, unsigned long zpitch, unsigned long wh, int haveWH,
               unsigned long toff, unsigned long tfmt, unsigned long tfil, int haveT, int haveTF)
{
    if (!haveWH)
        return 0;
    if (!cpR7SurfaceFits(c, coff, cpitch, ((wh >> 16) & 0xffffUL) + 1UL, (wh & 0xffffUL) + 1UL, 0))
        return 0;
    if (!cpR7SurfaceFits(c, zoff, zpitch, ((wh >> 16) & 0xffffUL) + 1UL, (wh & 0xffffUL) + 1UL, 1))
        return 0;
    if (haveT && (!haveTF || !cpR7TextureFits(c, toff, tfmt, tfil)))
        return 0;
    return 1;
}

static unsigned long
cpR7Verify(osrdn_cp_state *c, const unsigned long *w, unsigned long n,
           unsigned long defC, unsigned long defZ, unsigned long defPitch)
{
    unsigned long i, hdr, t, cnt, reg, val, vf, nv, vw;
    unsigned long fmt0, fmt1, coff, cpitch, zoff, zpitch, toff, wh, tfmt, tfil;
    int haveT, haveWH, drew, sawFmt, haveTF;

    c->r7At = 0UL;
    c->r7Word = 0UL;
    if (n == 0UL)
        return CP_R7_WHY_EMPTY;
    if (n > (unsigned long)CP_R7_BATCH_MAX)
        return CP_R7_WHY_WORDS;
    /* what the prefix leaves, so "the client never set the format" is still a defined state and
       never means "whatever the last client left" (docs/R7_PLAN.md 4-1 c) */
    fmt0 = CP_R7_PREFIX_FMT0;
    fmt1 = CP_R7_PREFIX_FMT1;
    /* M3h: and the surfaces the prefix points at -- the card draws into them unless the client
       moves them, so they are judged too rather than skipped */
    coff = defC; cpitch = defPitch; zoff = defZ; zpitch = defPitch; toff = 0UL; wh = 0UL;
    tfmt = 0UL; tfil = 0UL;
    haveT = 0; haveWH = 0; drew = 0; sawFmt = 0; haveTF = 0;
    i = 0UL;
    while (i < n) {
        c->r7At = i;
        hdr = w[i];
        c->r7Word = hdr;
        /* The packet type is the TOP TWO BITS and nothing else, so it is taken as a 0..3 number
           rather than compared against three 32-bit constants.  The first version did the latter
           and the target's cc disagreed with the host compiler about it: a type-3 header took the
           PACKET0 path on the hardware (boot ebfec1ec, U4 refused as P0_REG instead of P3_OP)
           while gcc-12 took the right one.  A two-bit switch leaves nothing to disagree about. */
        t = hdr >> 30;
        if (t == 1UL || t == 2UL)
            return CP_R7_WHY_TYPE;      /* type 1 carries TWO registers in the header; type 2 is ours */
        if (t == 0UL) {
            if ((hdr & 0x8000UL) != 0UL || ((hdr >> 16) & 0x3fffUL) != 0UL)
                return CP_R7_WHY_P0_COUNT;  /* one header, many registers: it would walk off the list */
            if (i + 1UL >= n)
                return CP_R7_WHY_TRUNC;
            reg = (hdr & 0x3fffUL) * 4UL;
            val = w[i + 1UL];
            if (!cpR7RegAllowed(reg))
                return CP_R7_WHY_P0_REG;
            if (!cpR7ValueAllowed(reg, val))
                return CP_R7_WHY_P0_VALUE;
            if (reg == C_SE_VTX_FMT_0) {
                fmt0 = val; sawFmt = 1;
            }
            else if (reg == C_SE_VTX_FMT_1)
                fmt1 = val;
            else if (reg == C_RB3D_COLOROFFSET)
                coff = val;
            else if (reg == C_RB3D_COLORPITCH)
                cpitch = val;
            else if (reg == C_RB3D_DEPTHOFFSET)
                zoff = val;
            else if (reg == C_RB3D_DEPTHPITCH)
                zpitch = val;
            else if (reg == C_RE_WIDTH_HEIGHT) {
                wh = val; haveWH = 1;
            } else if (reg == C_PP_TXOFFSET_0) {
                toff = val; haveT = 1;
            } else if (reg == C_PP_TXFORMAT_0) {
                tfmt = val; haveTF = 1;             /* G4-3 K3: the footprint's shape */
            } else if (reg == C_PP_TXFILTER_0)
                tfil = val;                         /* and its level count */
            i += 2UL;
            continue;
        }
        cnt = ((hdr >> 16) & 0x3fffUL) + 1UL;   /* data words after the header */
        if ((hdr & 0xff00UL) != 0x3500UL)
            return CP_R7_WHY_P3_OP;             /* 3D_DRAW_IMMD_2 is the only one we have measured */
        if (i + 1UL + cnt > n)
            return CP_R7_WHY_TRUNC;
        vf = w[i + 1UL];
        if ((vf & ~CP_R7_VF_ALLOWED) != 0UL ||
            (vf & CP_R7_VF_WALK_MASK) != CP_R7_VF_WALK_RING ||
            (vf & CP_R7_VF_PRIM_MASK) != CP_R7_VF_PRIM_TRIANGLES)
            return CP_R7_WHY_VF;                /* a non-ring walk reads the following words otherwise */
        nv = (vf >> 16) & 0xffffUL;
        if (nv == 0UL || (nv % 3UL) != 0UL)
            return CP_R7_WHY_VF;
        if (!sawFmt)
            return CP_R7_WHY_VTX_UNSET; /* the prefix defines it, but a client must still say so */
        vw = cpR7VertexWords(fmt0, fmt1);
        if (vw == 0UL)
            return CP_R7_WHY_VTX_FMT;
        if (cnt - 1UL != vw * nv)               /* cnt counts VF_CNTL as well */
            return CP_R7_WHY_COUNT;
        /* G4-4 K7: this draw reads and writes the surfaces as they are NOW */
        if (!cpR7SurfacesOk(c, coff, cpitch, zoff, zpitch, wh, haveWH, toff, tfmt, tfil, haveT, haveTF))
            return CP_R7_WHY_SURFACE;
        drew = 1;
        i += 1UL + cnt;
    }
    c->r7At = n;
    if (!drew)
        return CP_R7_WHY_EMPTY;
    if (!cpR7SurfacesOk(c, coff, cpitch, zoff, zpitch, wh, haveWH, toff, tfmt, tfil, haveT, haveTF))
        return CP_R7_WHY_SURFACE;
    return CP_R7_WHY_OK;
}

/* RESET and APPEND.  The kernel copies every word into its own buffer as it arrives, so the words
   the verifier judges are the words that run: the client cannot reach them again
   (docs/R7_PLAN.md 3-2).  A stream longer than the limit is refused here rather than at submit,
   so the client learns at the append that overran. */
static int
cpR7Stage(osrdn_cp_state *c, unsigned long op, unsigned long token,
          unsigned long nwords, const unsigned *words)
{
    unsigned long k;

    if (op == (unsigned long)CP_R7_OP_RESET) {
        c->subWords = 0UL;
        c->subDropped = 0UL;
        c->subToken = token;
        c->r7Why = CP_R7_WHY_OK;
        c->r7At = 0UL;
        return 1;
    }
    if (op != (unsigned long)CP_R7_OP_APPEND)
        return 0;
    if (token != c->subToken || c->subToken == 0UL) {
        c->subDropped++;                        /* someone else's words: not ours to stage */
        return 0;
    }
    if (nwords == 0UL || nwords > (unsigned long)CP_R7_APPEND_MAX ||
        c->subWords + nwords > (unsigned long)CP_R7_BATCH_MAX) {
        c->subDropped++;
        return 0;
    }
    for (k = 0; k < nwords; k++)
        cpR7Buf[c->subWords + k] = (unsigned long)words[k];
    c->subWords += nwords;
    return 1;
}

/*
 * M1x.  Hands back the accumulated stage times and zeroes them.  Like cpQuiet
 * it draws nothing, touches no register and does not log -- rule r5-quiet
 * forbids IOLog in this unit, so osrdn_cp_lines prints the line for this op.
 *
 * ZEROING HERE is what makes a second measurement a second measurement: two
 * runs that both dumped would otherwise report the first run's sum plus the
 * second's, and the average would be of neither.
 */
static int
cpTDump(osrdn_cp_state *c)
{
    int k;

    c->tDumpN = c->tAccN;
    for (k = 0; k < CP_T_STAGES; k++) {
        c->tDump[k] = c->tAcc[k];
        c->tAcc[k] = 0;
    }
    c->tAccN = 0;
    return CP_RC_RAN;
}

/*
 * M1n.  Sets the flag and the lease; it draws nothing and touches no register,
 * so it needs no base.  It does not log -- rule r5-quiet forbids IOLog here,
 * and the state line reports `quiet=` and `swallowed=` instead.
 */
static int
cpQuiet(osrdn_cp_state *c, unsigned long lease)
{
    /*
     * ONE NUMBER, not a flag and a count.  The tool puts a seed in `arg` for
     * the operations that need one and zero everywhere else, so an on/off in
     * `arg` would always have read "off".  The lease says everything: N means
     * swallow N submissions, 0 means speak now.  Two fields could disagree;
     * one cannot.
     */
    c->quiet = (lease != 0UL) ? 1 : 0;
    c->quietBudget = lease;
    c->loudBudget = 0UL;                /* M2g: quiet of any N cancels loud (exclusive) */
    return CP_RC_RAN;
}

/*
 * M2g: speak for `lease` client submissions, then go quiet by itself.  0 goes
 * quiet now -- the runner ends every loud arm with it, so an arm's unspent
 * lease cannot make the NEXT arm's first submissions loud.  It cancels a quiet
 * lease for the same reason quiet cancels it: one of the two, never both.
 */
static int
cpLoud(osrdn_cp_state *c, unsigned long lease)
{
    c->loudBudget = lease;
    c->quiet = 0;
    c->quietBudget = 0UL;
    return CP_RC_RAN;
}

/* M2a: the submission path's WBINVD, on or off.  A flag, not a lease: the arm
   that turns it on turns it off again, and a boot that ends with it on is a boot
   whose transcript says so. */
static int
cpNoWb(osrdn_cp_state *c, unsigned long on)
{
    c->doWb = (on != 0UL) ? 0 : 1;   /* M2e: `nowb 1` means DO NOT write back */
    return CP_RC_RAN;
}

/* M2b: how many extra polls before a sleep.  Bounded here, not by the caller:
   an unbounded spin would hold the mode claim (noSleep) for an unbounded time. */
/* M2c: the stage instrument, on or off.  Persistent, like doWb and spin -- the
   per-operation clear touches tOn and must not touch this. */
static int
cpTimeSet(osrdn_cp_state *c, unsigned long on)
{
    c->timeOn = (on != 0UL) ? 1 : 0;
    return CP_RC_RAN;
}

static int
cpSpinSet(osrdn_cp_state *c, unsigned long n)
{
    if (n > CP_SPIN_MAX)
        return cpRefused(c, CP_WHY_SPIN, n);
    cpSpin = n;
    c->spin = (unsigned int)n;
    return CP_RC_RAN;
}

/*
 * One call per client submission, and the ONLY reader of the flag on that
 * path: the answer is taken once and used for every log line of that
 * submission, so the two cannot disagree if the flag changes between them.
 * It also spends the lease, and hands the log back when the lease runs out.
 */
int
osrdn_cp_quiet_take(osrdn_cp_state *c)
{
    /*
     * M2g: SILENCE IS THE DEFAULT.  A submission speaks only while a `loud`
     * lease has units left, and each one it speaks spends one; at zero the
     * next submission is quiet again by itself.  Nothing else makes one speak.
     *
     * c->quiet is no longer consulted here -- it only records what `quiet N`
     * last asked, for the RDN-R6 zq line -- and quietBudget is not spent.
     */
    if (c == 0)
        return 0;
    if (c->loudBudget != 0UL) {
        c->loudBudget--;
        return 0;
    }
    c->quietSwallowed++;
    return 1;
}

static int
cpZclear(osrdn_cp_state *c, vm_address_t base, unsigned long seed, unsigned long zc)
{
    unsigned long *w = cpR6Words, n, v, i, need, nvert, vw, st, dw;
    const cpR6Case *cs;
    const cpR6Tri *tr;
    const unsigned long *wv;
    int k, rc, drawn;
    /* M1x: the running mark.  Set just after cpR7Verify, which is where
       t-poison turns back, so the intervals cover exactly the 366 us bucket. */
    ns_time_t tmark;
    int timing = 0;

    if (c->state != CP_ST_RUNNING)
        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);
    if (c->failed)
        return cpRefused(c, CP_WHY_FAILED, 0);
    if (!c->key3d || c->alias == 0)
        return cpRefused(c, CP_WHY_NO_3D, 0);
    if (zc < 1UL || zc > (unsigned long)CP_R6_CASES)
        return cpRefused(c, CP_WHY_CASE, zc);
    /* R6d: a triangle case's table: at most 6 vertices, TRIANGLES (a multiple of 3) */
    tr = 0;
    if (cpR6Cases[zc - 1UL].tri != 0UL) {
        if (cpR6Cases[zc - 1UL].tri > (unsigned long)CP_R6_TRIS)
            return cpRefused(c, CP_WHY_CASE, zc);
        tr = &cpR6Tris[cpR6Cases[zc - 1UL].tri - 1UL];
        if (tr->nv == 0UL || tr->nv > 6UL || tr->nv % 3UL != 0UL)
            return cpRefused(c, CP_WHY_CASE, zc);
    }
    /* R6f: a grid is not a triangle row; a z row needs one triangle; the plane source names
       lanes the source has (docs/R6F_PLAN.md 3-2) */
    cs = &cpR6Cases[zc - 1UL];
    if (cs->grid > CP_R6_GRIDS || (cs->grid != 0UL && tr != 0) || cs->zrow > CP_R6_ZROWS ||
        (cs->zrow != 0UL && (tr == 0 || tr->nv != 3UL)) || cs->dsrc > 2UL ||
        (cs->dsrc == 1UL && (cs->lanes & ~7UL) != 0UL) || (cs->dsrc == 2UL && (cs->lanes & ~3UL) != 0UL))
        return cpRefused(c, CP_WHY_CASE, zc);
    if (cs->gidx > CP_R6_GROWS || (cs->gidx != 0UL && (tr == 0 || cs->grid != 0UL)))
        return cpRefused(c, CP_WHY_CASE, zc);       /* R6g: a triangle row, no grid */
    if (cs->gidx != 0UL && cpR6G[cs->gidx - 1UL][4] != 0UL && tr->nv != 3UL)
        return cpRefused(c, CP_WHY_CASE, zc);       /* R6g: a second draw repeats one triangle */
    if (cs->sidx > CP_R6_SROWS)
        return cpRefused(c, CP_WHY_CASE, zc);       /* R6k: the auxiliary scissor's row */
    if (cs->bfirst > CP_R6_PACKS || cs->bcount > CP_R6_PACKS ||
        (cs->bfirst != 0UL && (cs->bcount == 0UL || cs->bfirst - 1UL + cs->bcount > CP_R6_PACKS)) ||
        (cs->bfirst != 0UL && (tr != 0 || cs->grid != 0UL || cs->gidx != 0UL || cs->tidx != 0UL)))
        return cpRefused(c, CP_WHY_CASE, zc);       /* R6l: the packets, and nothing else draws */
    {                                               /* R6m: the three surfaces (docs/R6M_PLAN.md 3) */
        unsigned long co = cpR6ColorOff(cs), zf = cpR6DepthOff(cs), tf = cpR6TexOff(cs);
        unsigned long bb = CP_R6_BUF_WORDS * 4UL;

        if (((cs->coff | cs->zoff | cs->toff) & 3UL) != 0UL)
            return cpRefused(c, CP_WHY_CASE, zc);   /* whole words only */
        if (co + bb > CP_R6_ALIAS_BYTES || zf + bb > CP_R6_ALIAS_BYTES ||
            tf + CP_R6_TEX_BYTES > CP_R6_ALIAS_BYTES)
            return cpRefused(c, CP_WHY_CASE, zc);   /* inside the window */
        if (co < zf + bb && zf < co + bb)
            return cpRefused(c, CP_WHY_CASE, zc);   /* colour and depth must not overlap */
        if (cs->tidx != 0UL && co < tf + CP_R6_TEX_BYTES && tf < co + bb)
            return cpRefused(c, CP_WHY_CASE, zc);
        if (cs->tidx != 0UL && zf < tf + CP_R6_TEX_BYTES && tf < zf + bb)
            return cpRefused(c, CP_WHY_CASE, zc);
    }
    if (cs->bfirst != 0UL) {                        /* R6l: every packet inside the triangle table */
        unsigned long b;

        for (b = 0; b < cs->bcount; b++) {
            const unsigned long *pk = cpR6Pack[cs->bfirst - 1UL + b];

            if (pk[0] == 0UL || pk[1] == 0UL || pk[0] - 1UL + pk[1] > CP_R6_POLYS)
                return cpRefused(c, CP_WHY_CASE, zc);
        }
    }
    if (cs->tidx > CP_R6_TROWS ||
        (cs->tidx != 0UL && (tr == 0 || tr->nv != 3UL || cs->grid != 0UL || cs->gidx != 0UL)))
        return cpRefused(c, CP_WHY_CASE, zc);       /* R6h: one triangle, no grid, no second draw */
    /* R6i: a W row needs one triangle (the grid and the box write 1.0), and no W is zero */
    if (cs->widx > CP_R6_WROWS || (cs->widx != 0UL && (tr == 0 || tr->nv != 3UL)))
        return cpRefused(c, CP_WHY_CASE, zc);
    wv = (cs->widx != 0UL) ? cpR6W[cs->widx - 1UL] : 0;
    if (wv != 0 && (wv[0] == 0UL || wv[1] == 0UL || wv[2] == 0UL))
        return cpRefused(c, CP_WHY_CASE, zc);
    drawn = (tr != 0 || cs->grid != 0UL || cs->bfirst != 0UL || zc == (unsigned long)CP_R7_CASE);
    /* R6f: the draw submission's length, known before anything is sent: state, blend stage, clip,
       header and VF, the vertices, the tail */
    nvert = (cs->grid != 0UL) ? 3UL * CP_R6_CELLS : (tr != 0) ? tr->nv : 3UL;
    vw = (tr != 0 || cs->grid != 0UL || (cs->fmt & C_VTX_COLOR0)) ? 5UL : 4UL;
    if (cs->tidx != 0UL)
        vw = 7UL;                               /* R6h: x, y, z, w, colour, s, t (docs/R6H_PLAN.md X4) */
    need = 26UL + ((cs->ppcntl != 0UL) ? 8UL : 0UL) + 4UL + 2UL + nvert * vw + 10UL;
    if (cs->tidx != 0UL)
        need += 12UL;                           /* R6h: six texture registers */
    if (cs->sidx != 0UL)
        need += 14UL;                           /* R6k: the control word and three TL/BR pairs */
    if (cs->bfirst != 0UL) {                    /* R6l: the packets replace the single draw */
        unsigned long b;

        need -= 2UL + nvert * vw;               /* the header, VF and vertices counted above */
        for (b = 0; b < cs->bcount; b++) {
            const unsigned long *pk = cpR6Pack[cs->bfirst - 1UL + b];

            need += 2UL + 15UL * pk[1] + ((pk[3] != 0UL) ? 6UL : 0UL);
        }
    }
    if (cs->gidx != 0UL) {                      /* R6g: the purge before the draw, and the second draw */
        const unsigned long *g = cpR6G[cs->gidx - 1UL];

        if (g[0] != 0UL)
            need += 4UL;
        if (g[4] != 0UL)
            need += 2UL + (g[10] ? 4UL : 0UL) + (g[9] ? 2UL : 0UL) + 2UL + 3UL * 5UL;
    }
    if (zc == (unsigned long)CP_R7_CASE) {
        /* R7a: the client's words replace everything the tables would have built; our own tail
           still goes on the end, and it is counted here because that is what design3 sized the
           limit against (docs/R7_PLAN.md 3-2) */
        c->zcase = (int)zc;             /* so the verdict is logged even when the stream is
                                           refused: the refusal happens long before the ordinary
                                           place this is set, and without it the log says nothing */
        c->r7WinStart = c->winStart;
        /* M3h: the window the client can already map and write with the CPU (osrdn_vmap_window,
           [winStart, winCeiling)) -- the card drawing there gives it nothing it did not have.
           The 256 KiB alias stays the driver's test block. */
        c->r7WinEnd = (c->winEnd > c->winStart) ? c->winEnd : c->winStart + CP_R6_ALIAS_BYTES;
        c->r7Why = cpR7Verify(c, cpR7Buf, c->subWords, c->winStart + cpR6ColorOff(cs),
                              c->winStart + cpR6DepthOff(cs), CP_R6_PITCH);
        if (c->r7Why != (unsigned long)CP_R7_WHY_OK)
            return cpRefused(c, CP_WHY_R7, c->r7Why);
        /*
         * M1x mark 0: the client path starts being timed HERE and nowhere else,
         * because this is the point t-poison returns from.
         *
         * M2c: AND ONLY WHEN ASKED.  All three lines are inside the knob, the
         * first clock read included -- leaving that one outside would make the
         * on/off difference exclude its own cost, and it is one of seventeen.
         */
        if (c->timeOn) {
            IOGetTimestamp(&tmark);
            timing = 1;
            c->tOn = 1;                     /* M1z: cpR6Submit reads this one */
        }
        need = c->subWords + 2UL + 10UL;    /* our WAIT_UNTIL, its words, our tail */
    }
    if (need > (unsigned long)CP_R6_WORDS)
        return cpRefused(c, CP_WHY_WORDS, need);
    /*
     * M1h: THE CLIENT'S STREAM DOES NOT NEED THE PATTERN.
     *
     * `zprepped` is R6a's precondition: ZPREP fills the 256 KiB alias with a
     * known pattern so that the R6 read-backs can say which words a draw
     * changed.  Every place inside this function that reads the pattern feeds a
     * MEASUREMENT (the digests, the "rest" scan, the coverage map) and none of
     * them decides anything -- after stage 3 the only failure paths are the
     * scratch-register markers (docs/M1H_PLAN.md 7, enumerated from the source).
     *
     * Requiring it of a client submission made the ring one triangle per ZPREP,
     * and ZPREP is a driver operation the library cannot call: a frame's second
     * triangle fell back to software.  That is harmless for a per-pixel feature
     * and wrong for depth, where two triangles must be judged against ONE
     * buffer (docs/M1_NEXT_DECISION.md H1-H3).
     *
     * The CONSUMPTION below is left alone on purpose: any ZCLEAR dirties the
     * window, so an R6 case that follows client draws must prep again rather
     * than measure against a pattern the client overwrote.
     */
    if (zc != (unsigned long)CP_R7_CASE && !c->zprepped)
        return cpRefused(c, CP_WHY_NOT_PREPPED, 0);
    if (seed == 0UL || (c->seedUsed && seed == c->lastSeed))
        return cpRefused(c, CP_WHY_SEED, seed);
    if (!cpIdleGate(c, base, 0))
        return CP_RC_REFUSED;
    v = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;
    c->rptrBefore = v;
    if (v != c->wptr)
        return cpRefused(c, CP_WHY_NOT_CAUGHT_UP, v);
    if (!cpPoisonHolds(c, base))
        return cpRefused(c, CP_WHY_POISON, c->reg5);
    c->surfaceCntl = rdnMmioRead32(base, C_SURFACE_CNTL);
    if (c->surfaceCntl != C_SURF_TRANSLATION_DIS)
        return cpRefused(c, CP_WHY_SURFACE, c->surfaceCntl);
    if (timing)
        cpTMark(c, &tmark, 0);              /* M1x: the gates */
    c->zcase = (int)zc;
    c->lastSeed = seed;
    c->seedUsed = 1;
    c->zprepped = 0;                    /* one ZCLEAR per ZPREP */

    /* sentinels the markers must replace */
    if (!cpWait(base, W_FIFO, 2, C_FIFO_US, &c->wFifo))
        return cpLatch(c, base);
    rdnMmioWrite32(base, C_SCRATCH_REG0, ~seed);
    rdnMmioWrite32(base, C_SCRATCH_REG0 + 8, seed);
    if (!cpWait(base, W_IDLE, 0, C_IDLE_US, &c->wIdle2))
        return cpLatch(c, base);
    if (rdnMmioRead32(base, C_SCRATCH_REG0) != ~seed || rdnMmioRead32(base, C_SCRATCH_REG0 + 8) != seed)
        return cpRefused(c, CP_WHY_SENTINEL, 0);
    if (timing)
        cpTMark(c, &tmark, 1);              /* M1x: the preamble */

    /* 1: the prefix, then its read-back -- nothing is drawn unless all of it holds */
    n = 0;
    w[n++] = C_P0(C_SE_TCL_STATE_FLUSH);    w[n++] = 0UL;
    w[n++] = C_P0(C_SE_VAP_CNTL_STATUS);    w[n++] = 0UL;
    w[n++] = C_P0(C_PP_CNTL_X);             w[n++] = 0UL;
    w[n++] = C_P0(C_PP_TXMULTI_CTL_0);      w[n++] = 0UL;
    w[n++] = C_P0(C_SE_VTX_STATE_CNTL);     w[n++] = cs->vsc;
    w[n++] = C_P0(C_RB3D_DEPTHXY_OFFSET);   w[n++] = 0UL;       /* Mesa's init value (8-2 M1) */
    w[n++] = C_P0(C_RB3D_DEPTHOFFSET);      w[n++] = c->winStart + cpR6DepthOff(cs);
    w[n++] = C_P0(C_RB3D_DEPTHPITCH);       w[n++] = CP_R6_PITCH;
    w[n++] = C_P0(C_RB3D_COLOROFFSET);      w[n++] = c->winStart + cpR6ColorOff(cs);
    w[n++] = C_P0(C_RB3D_COLORPITCH);       w[n++] = CP_R6_PITCH;
    if (zc == (unsigned long)CP_R7_CASE) {      /* R7a (docs/R7_PLAN.md 4-1 c) */
        w[n++] = C_P0(C_SE_VTX_FMT_0);      w[n++] = CP_R7_PREFIX_FMT0;
        w[n++] = C_P0(C_SE_VTX_FMT_1);      w[n++] = CP_R7_PREFIX_FMT1;
    }
    /* G4-7 (docs/G4_7_TRIPERF_PLAN.md 2-3): what the reference writes for every context (r200_state_init.c
       748, 984-986: prf state "always", TRI_PERF = 0x1f - 0x1f * quality(1.0) = 0, PERF_CNTL = 0).  Last, so
       zclear_oracle.prefix_words()[9] stays SE_VTX_STATE_CNTL. */
    w[n++] = C_P0(C_PP_TRI_PERF);           w[n++] = 0UL;
    w[n++] = C_P0(C_PP_PERF_CNTL);          w[n++] = 0UL;
    /* G4-9: the LRU workaround, before the client's texture state as the DRI emits its tam atom before the
       tex atoms (r200_cmdbuf.c 80-84); recorded by the read-back, not gated */
    w[n++] = C_P0(C_PP_TAM_DEBUG3);         w[n++] = C_PP_TAM_DEBUG3_LRU;
    w[n++] = C_P0(C_SCRATCH_REG0);          w[n++] = seed;
    c->zstage = 1;
    if ((rc = cpR6Submit(c, base, w, n)) != CP_RC_RAN)
        return rc;
    if (timing)
        cpTMark(c, &tmark, 2);              /* M1x: stage 1's ring submit */
    c->zreg0 = rdnMmioRead32(base, C_SCRATCH_REG0);
    c->prefixBad = 0;
    for (k = 0; k < CP_R6_PRE_COUNT; k++) {
        c->pre[k] = rdnMmioRead32(base, cpR6PreRegs[k]);
        if (c->pre[k] != cpR6PreWant(c, k))
            c->prefixBad |= 1UL << k;
    }
    if (c->zreg0 != seed) {
        c->failed = 1;
        (void)cpRefuse(c, CP_WHY_MARKER, c->zreg0);
        return CP_RC_CHECK_FAILED;
    }
    if ((c->prefixBad & CP_R6_PRE_GATE) != 0UL) {
        c->failed = 1;
        (void)cpRefuse(c, CP_WHY_PREFIX, c->prefixBad);
        return CP_RC_CHECK_FAILED;
    }
    if (timing)
        cpTMark(c, &tmark, 3);              /* M1x: stage 1's read-backs (1 + 12) */

    /* R6g (docs/R6G_PLAN.md 2-1): the CPU writes the depth the test will read, then reads it back */
    c->pfBad = 0;
    if (cs->gidx != 0UL && cpR6G[cs->gidx - 1UL][0] != 0UL) {
        const unsigned long *g = cpR6G[cs->gidx - 1UL];
        volatile unsigned long *al = (volatile unsigned long *)c->alias;
        long va = (long)g[1], vb = (long)g[2], vc = (long)g[3], top = (cs->dsrc == 2UL) ? 65535L : 16777215L;

        for (i = 0; i < 1024UL; i++) {
            unsigned long x = i & 31UL, y = i >> 5, a, k;
            long val = va + vb * (long)x + vc * (long)y;

            if (val < 0L)
                val = 0L;
            if (val > top)
                val = top;
            if (cs->dsrc == 2UL) {
                a = cpMbaZ16(CP_R6_PITCH, x, y);
                k = (cpR6DepthOff(cs) + a) / 4UL;
                al[k] = (al[k] & ~(0xffffUL << (16UL * ((a >> 1) & 1UL)))) |
                        (((unsigned long)val & 0xffffUL) << (16UL * ((a >> 1) & 1UL)));
            } else {
                k = (cpR6DepthOff(cs) + cpMbaZ32(CP_R6_PITCH, x, y)) / 4UL;
                al[k] = (al[k] & 0xff000000UL) | ((unsigned long)val & 0xffffffUL);
            }
        }
        cpFence(base);
        for (i = 0; i < 1024UL; i++) {
            unsigned long x = i & 31UL, y = i >> 5, a, got;
            long val = va + vb * (long)x + vc * (long)y;

            if (val < 0L)
                val = 0L;
            if (val > top)
                val = top;
            if (cs->dsrc == 2UL) {
                a = cpMbaZ16(CP_R6_PITCH, x, y);
                got = (al[(cpR6DepthOff(cs) + a) / 4UL] >> (16UL * ((a >> 1) & 1UL))) & 0xffffUL;
            } else {
                got = al[(cpR6DepthOff(cs) + cpMbaZ32(CP_R6_PITCH, x, y)) / 4UL] & 0xffffffUL;
            }
            if (got != (unsigned long)val)
                c->pfBad++;
        }
        if (c->pfBad != 0UL) {
            c->failed = 1;
            return cpRefused(c, CP_WHY_PREFILL, c->pfBad);
        }
    }

    /* R6h (docs/R6H_PLAN.md 2-1): the CPU writes the texture the sampler will read, then reads it back */
    if (cs->tidx != 0UL) {
        const unsigned long *tx = cpR6T[cs->tidx - 1UL];
        volatile unsigned long *al = (volatile unsigned long *)c->alias;
        unsigned long tw = tx[0], th = tx[1], stride = tx[2], pat = tx[13], u, vv;

        for (vv = 0; vv < th; vv++)
            for (u = 0; u < tw; u++)
                al[(cpR6TexOff(cs) + vv * stride) / 4UL + u] = cpR6Texel(pat, u, vv);
        cpFence(base);
        for (vv = 0; vv < th; vv++)
            for (u = 0; u < tw; u++)
                if (al[(cpR6TexOff(cs) + vv * stride) / 4UL + u] != cpR6Texel(pat, u, vv))
                    c->pfBad++;
        if (c->pfBad != 0UL) {
            c->failed = 1;
            return cpRefused(c, CP_WHY_PREFILL, c->pfBad);
        }
    }

    /* 2: the precedent, verbatim, then the tail */
    n = 0;
    if (zc == (unsigned long)CP_R7_CASE) {
        /* R7a: the driver's own WAIT_UNTIL first -- the same word the state block starts with, in
           the same place, so the stream the hardware sees has the order the R6 ladder measured.
           A client may not send it itself: a wait on a condition that never comes hangs the engine,
           which is why WAIT_UNTIL is one of the four reserved registers (docs/R7_PLAN.md 4 rule 5). */
        w[n++] = C_P0(C_WAIT_UNTIL);            w[n++] = cpR6State[1];
        /* then its words, verified above, word for word; nothing here interprets them again */
        for (i = 0; i < c->subWords; i++)
            w[n++] = cpR7Buf[i];
    } else {
    if (cs->gidx != 0UL && cpR6G[cs->gidx - 1UL][0] != 0UL) {
        /* R6g: the caches go before the state block's WAIT_UNTIL, as the precedent's idle path does
           (PURGE_CACHE, PURGE_ZCACHE, WAIT_UNTIL_IDLE -- radeon_cp.c 559-561) */
        w[n++] = C_P0(C_RB3D_DSTCACHE_CTLSTAT); w[n++] = C_PURGE_DC;
        w[n++] = C_P0(C_RB3D_ZCACHE_CTLSTAT);   w[n++] = C_PURGE_ZC;
    }
    st = n;                                     /* R6g: the state block starts after the purge, if any */
    for (i = 0; i < 26UL; i++)
        w[n++] = cpR6State[i];
    w[st + 3] = cs->ppcntl;                     /* PP_CNTL (R6c) */
    w[st + 5] = cs->recntl;                     /* R200_RE_CNTL's value word (R6b) */
    w[st + 7] = cs->rb3d;                       /* RB3D_CNTL (R6g: Z_ENABLE) */
    w[st + 9] = cs->zcntl;                      /* RB3D_ZSTENCILCNTL (R6f: the depth format; R6g: the test and the write bit) */
    w[st + 13] = cs->planemask;                 /* RB3D_PLANEMASK (R6c) */
    w[st + 15] = cs->secntl;                    /* SE_CNTL (R6e: shading fields) */
    w[st + 19] = cs->fmt;                       /* R200_SE_VTX_FMT_0 (R6c) */
    if (cs->vte != 0UL)
        w[st + 17] = cs->vte;                   /* R6i: SE_VTE_CNTL (docs/R6I_PLAN.md Y2-Y3) */
    if (cs->ppcntl != 0UL) {                    /* R6c: blend stage 0 passes the vertex colour;
                                                   R6h: with a texture it passes the texel (R0) */
        unsigned long pass = (cs->tidx != 0UL) ? C_TXBLEND_TEXTURE : C_TXBLEND_DIFFUSE;

        w[n++] = C_P0(C_PP_TXCBLEND_0);     w[n++] = pass;
        w[n++] = C_P0(C_PP_TXCBLEND2_0);    w[n++] = C_TXBLEND2_R0;
        w[n++] = C_P0(C_PP_TXABLEND_0);     w[n++] = pass;
        w[n++] = C_P0(C_PP_TXABLEND2_0);    w[n++] = C_TXBLEND2_R0;
    }
    if (cs->tidx != 0UL) {                      /* R6h: the texture unit, the precedent's six registers */
        const unsigned long *tx = cpR6T[cs->tidx - 1UL];

        w[st + 21] = C_VTX_FMT_1_ST;            /* SE_VTX_FMT_1: two components on unit 0 */
        w[n++] = C_P0(C_PP_TXFILTER_0);     w[n++] = tx[3];
        w[n++] = C_P0(C_PP_TXFORMAT_0);     w[n++] = tx[4];
        w[n++] = C_P0(C_PP_TXFORMAT_X_0);   w[n++] = tx[14];   /* R6i: TEXCOORD_PROJ in PH */
        w[n++] = C_P0(C_PP_TXSIZE_0);       w[n++] = tx[5];
        w[n++] = C_P0(C_PP_TXPITCH_0);      w[n++] = tx[6];
        w[n++] = C_P0(C_PP_TXOFFSET_0);     w[n++] = c->winStart + cpR6TexOff(cs);
    }
    if (cs->sidx != 0UL) {                      /* R6k: the auxiliary scissor, after the state block
                                                   cleared its control word (docs/R6K_PLAN.md 1 F7) */
        const unsigned long *sc = cpR6S[cs->sidx - 1UL];

        w[n++] = C_P0(C_RE_AUX_SCISSOR_CNTL);   w[n++] = sc[0];
        w[n++] = C_P0(C_RE_SCISSOR_TL_0);       w[n++] = sc[1];
        w[n++] = C_P0(C_RE_SCISSOR_BR_0);       w[n++] = sc[2];
        w[n++] = C_P0(C_RE_SCISSOR_TL_1);       w[n++] = sc[3];
        w[n++] = C_P0(C_RE_SCISSOR_BR_1);       w[n++] = sc[4];
        w[n++] = C_P0(C_RE_SCISSOR_TL_2);       w[n++] = sc[5];
        w[n++] = C_P0(C_RE_SCISSOR_BR_2);       w[n++] = sc[6];
    }
    w[n++] = C_P0(C_RE_TOP_LEFT);           w[n++] = (cs->cy1 << 16) | cs->cx1;
    w[n++] = C_P0(C_RE_WIDTH_HEIGHT);       w[n++] = ((cs->cy2 - 1UL) << 16) | (cs->cx2 - 1UL);
    if (cs->bfirst != 0UL) {                    /* R6l: this case's packets, in the table's order */
        unsigned long b;

        for (b = 0; b < cs->bcount; b++) {
            const unsigned long *pk = cpR6Pack[cs->bfirst - 1UL + b];
            unsigned long t;

            if (pk[3] != 0UL) {                 /* the clip moves: the precedent waits first (F9) */
                w[n++] = C_P0(C_WAIT_UNTIL);        w[n++] = C_WAIT_3D_HOST;
                w[n++] = C_P0(C_RE_TOP_LEFT);       w[n++] = pk[4];
                w[n++] = C_P0(C_RE_WIDTH_HEIGHT);   w[n++] = pk[5];
            }
            w[n++] = C_P3_IMMD(15UL * pk[1]);
            w[n++] = C_VF_TRI | ((3UL * pk[1]) << 16);
            for (t = 0; t < pk[1]; t++) {
                const unsigned long *po = cpR6Poly[pk[0] - 1UL + t];
                unsigned long v;

                for (v = 0; v < 3UL; v++) {
                    w[n++] = po[2UL * v]; w[n++] = po[2UL * v + 1UL];
                    w[n++] = C_FLOAT_ONE; w[n++] = C_FLOAT_ONE;
                    w[n++] = pk[2];
                }
            }
        }
    } else {
    w[n++] = cs->hdr;
    w[n++] = cs->vf;
    if (cs->grid != 0UL) {                      /* R6f: 16 cells (x0,y0) (x0+3,y0) (x0,y0+3), a z each */
        const unsigned long *gz = cpR6GridZ[cs->grid - 1UL];

        for (i = 0; i < CP_R6_CELLS; i++) {
            const unsigned long *cl = cpR6Cells[i];

            w[n++] = cl[0]; w[n++] = cl[1]; w[n++] = gz[i]; w[n++] = C_FLOAT_ONE; w[n++] = cs->colour;
            w[n++] = cl[2]; w[n++] = cl[1]; w[n++] = gz[i]; w[n++] = C_FLOAT_ONE; w[n++] = cs->colour;
            w[n++] = cl[0]; w[n++] = cl[3]; w[n++] = gz[i]; w[n++] = C_FLOAT_ONE; w[n++] = cs->colour;
        }
    } else if (tr != 0) {                       /* R6d: the triangles, colour after W */
        for (i = 0; i < tr->nv; i++) {
            w[n++] = tr->v[i][0]; w[n++] = tr->v[i][1];
            w[n++] = (cs->zrow != 0UL) ? cpR6Zv[cs->zrow - 1UL][i] : cs->z;    /* R6f: a z per vertex */
            w[n++] = (wv != 0) ? wv[i] : C_FLOAT_ONE;       /* R6i: a W per vertex */
            w[n++] = tr->v[i][2];
            if (cs->tidx != 0UL) {              /* R6h: s and t after the colour (docs/R6H_PLAN.md X4) */
                w[n++] = cpR6T[cs->tidx - 1UL][7 + 2UL * i];
                w[n++] = cpR6T[cs->tidx - 1UL][8 + 2UL * i];
            }
        }
    } else {                                    /* the box: (x1,y1) (x1,y2) (x2,y2) */
        w[n++] = cs->gx1; w[n++] = cs->gy1; w[n++] = cs->z; w[n++] = C_FLOAT_ONE;
        if (cs->fmt & C_VTX_COLOR0)
            w[n++] = cs->colour;
        w[n++] = cs->gx1; w[n++] = cs->gy2; w[n++] = cs->z; w[n++] = C_FLOAT_ONE;
        if (cs->fmt & C_VTX_COLOR0)
            w[n++] = cs->colour;
        w[n++] = cs->gx2; w[n++] = cs->gy2; w[n++] = cs->z; w[n++] = C_FLOAT_ONE;
        if (cs->fmt & C_VTX_COLOR0)
            w[n++] = cs->colour;
    }
    }
    /* R6g (docs/R6G_PLAN.md 6): the second draw -- a new ZSTENCILCNTL (and, for H1w, a WAIT_UNTIL)
       in the same submission, with no cache flush between the draws */
    if (cs->gidx != 0UL && cpR6G[cs->gidx - 1UL][4] != 0UL) {
        const unsigned long *g = cpR6G[cs->gidx - 1UL];

        w[n++] = C_P0(C_RB3D_ZSTENCILCNTL);     w[n++] = g[4];
        if (g[10] != 0UL) {                     /* R6j: the blend unit for the second draw */
            w[n++] = C_P0(C_RB3D_BLENDCNTL);    w[n++] = g[10];
            w[n++] = C_P0(C_RB3D_CNTL);         w[n++] = g[11];
        }
        if (g[9] != 0UL) {
            w[n++] = C_P0(C_WAIT_UNTIL);        w[n++] = C_WAIT_3D_IDLECLEAN;
        }
        w[n++] = cs->hdr;
        w[n++] = cs->vf;
        for (i = 0; i < 3UL; i++) {
            w[n++] = tr->v[i][0]; w[n++] = tr->v[i][1]; w[n++] = g[5 + i]; w[n++] = C_FLOAT_ONE;
            w[n++] = g[8];
        }
    }
    }
    w[n++] = C_P0(C_RB3D_DSTCACHE_CTLSTAT); w[n++] = C_PURGE_DC;
    w[n++] = C_P0(C_RB3D_ZCACHE_CTLSTAT);   w[n++] = C_PURGE_ZC;
    w[n++] = C_P0(C_WAIT_UNTIL);            w[n++] = C_WAIT_IDLE;
    w[n++] = C_P0(C_RB3D_CNTL);             w[n++] = 0UL;               /* operator D1 */
    w[n++] = C_P0(C_SCRATCH_REG0 + 8);      w[n++] = ~seed;
    if (n != need) {                            /* R6f: the count above is the one checked before the prefix */
        c->failed = 1;
        return cpRefused(c, CP_WHY_WORDS, n);
    }
    c->zstage = 2;
    if (timing)
        cpTMark(c, &tmark, 4);              /* M1x: assembling stage 2's words */
    if ((rc = cpR6Submit(c, base, w, n)) != CP_RC_RAN)
        return rc;
    if (timing)
        cpTMark(c, &tmark, 5);              /* M1x: stage 2's ring submit */
    /* radeon_do_pixcache_flush, as radeon_do_cp_idle's wait does */
    v = rdnMmioRead32(base, C_RB3D_DSTCACHE_CTLSTAT);
    rdnMmioWrite32(base, C_RB3D_DSTCACHE_CTLSTAT, v | C_DC_FLUSH_ALL);
    if (!cpWait(base, W_DC, 0, C_DC_US, &c->wDc))
        return cpLatch(c, base);
    c->zreg2 = rdnMmioRead32(base, C_SCRATCH_REG0 + 8);
    if (timing)
        cpTMark(c, &tmark, 6);              /* M1x: the pixcache flush and its read-back */

    /* 3: the block, twice (the second pass judges; a difference is recorded) */
    c->zstage = 3;
    /* M1m: the client samples, the R6 cases scan.  See CP_R7_DIGEST_WORDS. */
    dw = (zc == (unsigned long)CP_R7_CASE) ? CP_R7_DIGEST_WORDS : CP_R6_BUF_WORDS;
    /*
     * M1o: UNDER QUIET THE ANALYSIS HAS NO EXIT.
     *
     * Both the digests and the coverage map leave this driver only through
     * osrdn_cp_lines (osrdn_modelog.m:291, :322-323), and the client path
     * skips that whole function when quiet (OSRDNDisplay.m:898).  So a quiet
     * submission was computing 1,344 uncached reads and throwing them away --
     * measured at 830 ns each, that was 89% of a submission.
     *
     * TWO READS ARE KEPT, not 256.  A cross-review put it plainly: if a
     * completed uncached read is what drains earlier GPU writes, one is
     * enough; if it is not, 256 prove nothing about the other 1,088.  One per
     * buffer is the smallest shape that satisfies both readings, and it costs
     * about two microseconds.  The documented fence -- DC_FLUSH_ALL and the
     * W_DC wait -- is untouched and still runs above.
     */
    c->digestWords = c->subQuiet ? 0UL : dw;
    for (k = 0; k < 2; k++) {
        if (c->subQuiet) {
            c->qTouch[0] = ((volatile unsigned long *)c->alias)[cpR6ColorOff(cs) / 4UL];
            c->qTouch[1] = ((volatile unsigned long *)c->alias)[cpR6DepthOff(cs) / 4UL];
        } else {
        cpR6Digest(c, cpR6DepthOff(cs) / 4UL, dw, &c->dDepth[k]);
        cpR6Digest(c, cpR6ColorOff(cs) / 4UL, dw, &c->dColor[k]);
        }
        c->restChanged[k] = 0;
        /*
         * M1h: not for the client's stream.  This scan reads the whole 256 KiB
         * alias, uncached, once per pass -- half a megabyte a submission -- to
         * answer a question only the R6 cases ask ("what ELSE changed?").  With
         * one submission a frame it was invisible; this rung's whole purpose is
         * to make submissions many.  Skipped, not deleted: the cases that
         * measured with it still measure with it.
         */
        if (zc == (unsigned long)CP_R7_CASE) {
            c->restSkipped = 1;
            continue;
        }
        for (i = 0; i < CP_R6_ALIAS_BYTES / 4UL; i++) {
            if (i >= cpR6DepthOff(cs) / 4UL && i < cpR6DepthOff(cs) / 4UL + CP_R6_BUF_WORDS)
                continue;
            if (i >= cpR6ColorOff(cs) / 4UL && i < cpR6ColorOff(cs) / 4UL + CP_R6_BUF_WORDS)
                continue;
            if (cs->tidx != 0UL && i >= cpR6TexOff(cs) / 4UL &&
                i < (cpR6TexOff(cs) + CP_R6_TEX_BYTES) / 4UL)
                continue;                       /* R6h: the CPU's texture, checked by its own read-back */
            v = ((volatile unsigned long *)c->alias)[i];
            if (v == cpR6Pattern(i))
                continue;
            if (c->restChanged[k]++ == 0UL && k == 1) {
                c->restFirst = i;
                c->restFirstVal = v;
            }
        }
    }
    /* R6d: the coverage map of the colour buffer's top-left 32 x 32 (docs/R6D_PLAN.md 10).
       M1h LEFT THIS ALONE, having first taken it away: the client case's map IS
       read -- tools/r6/sim_r6.py judges case UC against T1's coverage, and
       skipping it failed that check at once ("the coverage map is not T1's").
       It is 1024 reads, not the 128 K-word scan above; the cost was never here. */
    /* M1o: 1,088 uncached reads whose only exit is a log line quiet suppresses */
    if (drawn && !c->subQuiet) {
        for (i = 0; i < CP_R6_COV_WORDS; i++)
            c->cov[i] = 0;
        for (i = 0; i < 1024UL; i++) {
            unsigned long at = cpR6ColorOff(cs) / 4UL + (i >> 5) * CP_R6_PITCH + (i & 31UL), code;

            v = ((volatile unsigned long *)c->alias)[at];
            if (v == cpR6Pattern(at))
                code = 0;
            else if (v == cs->covp1)
                code = 1;
            else if (v == cs->covp2)
                code = 2;
            else
                code = 3;
            c->cov[i >> 4] |= code << (2UL * (i & 15UL));
        }
        c->covValid = 1;
    }
    /* R6e: the byte planes of the lanes the case names, and the constant lanes' misses
       (docs/R6E_PLAN.md 9) -- covered = not the pattern, as the map */
    if (drawn && cs->lanes != 0UL) {
        unsigned long l;

        for (l = 0; l < 4UL; l++) {
            c->laneOff[l] = 0;
            for (i = 0; i < CP_R6_PLANE_WORDS; i++)
                c->plane[l][i] = 0;
        }
        /* R6f (docs/R6F_PLAN.md 3-2): a depth source -- every pixel of the 32 x 32, what the depth
           buffer holds at Mesa's address: 24-bit lanes 0-2 of the word, 16-bit the halfword */
        for (i = 0; i < 1024UL && cs->dsrc != 0UL; i++) {
            unsigned long a;

            if (cs->dsrc == 1UL) {
                a = cpMbaZ32(CP_R6_PITCH, i & 31UL, i >> 5);
                v = ((volatile unsigned long *)c->alias)[(cpR6DepthOff(cs) + a) / 4UL] & 0xffffffUL;
            } else {
                a = cpMbaZ16(CP_R6_PITCH, i & 31UL, i >> 5);
                v = (((volatile unsigned long *)c->alias)[(cpR6DepthOff(cs) + a) / 4UL] >> (16UL * ((a >> 1) & 1UL))) & 0xffffUL;
            }
            for (l = 0; l < 4UL; l++)
                if (cs->lanes & (1UL << l))
                    c->plane[l][i >> 2] |= ((v >> (8UL * l)) & 0xffUL) << (8UL * (i & 3UL));
        }
        for (i = 0; i < 1024UL && cs->dsrc == 0UL; i++) {
            unsigned long at = cpR6ColorOff(cs) / 4UL + (i >> 5) * CP_R6_PITCH + (i & 31UL), b;

            v = ((volatile unsigned long *)c->alias)[at];
            if (v == cpR6Pattern(at))
                continue;
            for (l = 0; l < 4UL; l++) {
                b = (v >> (8UL * l)) & 0xffUL;
                if (cs->lanes & (1UL << l))
                    c->plane[l][i >> 2] |= b << (8UL * (i & 3UL));
                if (!(cs->gvary & (1UL << l)) && b != ((cs->gconst >> (8UL * l)) & 0xffUL))
                    c->laneOff[l]++;
            }
        }
    }
    /* R6m (docs/R6M_PLAN.md 5 N3): the texture surface AFTER the draw.  The "rest" loop above
       skips the texture on purpose, so nothing else would see a draw that spilled into it.  This is
       a RECORD, not a refusal: the judge gates on it (the driver must not turn a measurement into a
       failure it cannot explain). */
    c->texPost = 0;
    c->texPostAt = 0;
    c->texPostVal = 0;
    if (cs->tidx != 0UL) {
        const unsigned long *tx = cpR6T[cs->tidx - 1UL];
        volatile unsigned long *al = (volatile unsigned long *)c->alias;
        unsigned long tw = tx[0], th = tx[1], stride = tx[2], pat = tx[13];

        for (i = 0; i < CP_R6_TEX_BYTES / 4UL; i++) {
            unsigned long row = (i * 4UL) / stride, col = i - (row * stride) / 4UL, want;

            if (row < th && col < tw)
                want = cpR6Texel(pat, col, row);
            else
                want = cpR6Pattern(cpR6TexOff(cs) / 4UL + i);
            v = al[cpR6TexOff(cs) / 4UL + i];
            if (v != want && c->texPost++ == 0UL) {
                c->texPostAt = i;
                c->texPostVal = v;
            }
        }
    }
    c->zColorOff = cpR6ColorOff(cs);         /* R6m: what the prefix and every read-back used */
    c->zDepthOff = cpR6DepthOff(cs);
    c->zTexOff = (cs->tidx != 0UL) ? cpR6TexOff(cs) : 0UL;
    c->planeLanes = cs->lanes;               /* what this case asks for, whether or not it publishes */
    c->planeSrc = cs->dsrc;
    if (c->zreg2 != ~seed) {
        c->failed = 1;
        (void)cpRefuse(c, CP_WHY_MARKER, c->zreg2);
    }
    if (!cpPoisonHolds(c, base) || cpCheckBlock(c) != 0UL)
        c->failed = 1;
    if (!c->failed && drawn && cs->lanes != 0UL) {       /* R6e: publish the planes with their source */
        c->planeZop = c->ops;
        c->planeZcase = (int)zc;
        c->planeValid = 1;
    }
    /*
     * M1x: the last interval, and the only place tAccN moves.
     *
     * It is stepped HERE and not at mark 0 on purpose: an operation that turned
     * back early contributed to some intervals and not others, and dividing by
     * a count that included it would spread its absence over all eight.  Only
     * operations that reached the end are counted, and they are the ones whose
     * intervals are all present.
     */
    if (timing) {
        cpTMark(c, &tmark, 7);              /* M1x: the analysis and the tail */
        c->tAccN++;
    }
    return c->failed ? CP_RC_CHECK_FAILED : CP_RC_RAN;
}

/* ---- G5-2: the accepted submission (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-1) -----------------------
 *
 * cpZclear's client case with everything that waited taken out.  What the CARD sees is the
 * same: the prefix as one ring write, then our WAIT_UNTIL, the verified stream and the tail as
 * the second -- the very lines cpZclear builds, which check_r5_src g52-same-words holds to each
 * other word for word.  What is gone is every question the CPU asked of the card on the way:
 * the idle gate and the caught-up gate (the card drawing the previous batch is the normal state
 * now), the sentinels and their idle wait, the prefix read-back, the pixel cache flush, the
 * digest and the block check.  The scratch markers stay in the stream -- REG0 takes the seed in
 * the prefix, REG2 its complement in the tail -- so RETIRE can record whether the last accepted
 * submission ran to its end.
 */
static int
cpAsubmit(osrdn_cp_state *c, vm_address_t base, unsigned long seed)
{
    unsigned long *w = cpR6Words, n, i, need;
    const cpR6Case *cs = &cpR6Cases[CP_R7_CASE - 1];
    int rc;

    if (c->state != CP_ST_RUNNING)
        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);
    if (c->failed)
        return cpRefused(c, CP_WHY_FAILED, 0);
    if (!c->key3d || c->alias == 0)
        return cpRefused(c, CP_WHY_NO_3D, 0);
    c->zcase = CP_R7_CASE;
    c->r7WinStart = c->winStart;
    c->r7WinEnd = (c->winEnd > c->winStart) ? c->winEnd : c->winStart + CP_R6_ALIAS_BYTES;
    c->r7Why = cpR7Verify(c, cpR7Buf, c->subWords, c->winStart + cpR6ColorOff(cs),
                          c->winStart + cpR6DepthOff(cs), CP_R6_PITCH);
    if (c->r7Why != (unsigned long)CP_R7_WHY_OK)
        return cpRefused(c, CP_WHY_R7, c->r7Why);
    need = c->subWords + 2UL + 10UL;    /* our WAIT_UNTIL, its words, our tail -- as cpZclear counts */
    if (need > (unsigned long)CP_R6_WORDS)
        return cpRefused(c, CP_WHY_WORDS, need);
    if (seed == 0UL || (c->seedUsed && seed == c->lastSeed))
        return cpRefused(c, CP_WHY_SEED, seed);
    c->rptrBefore = rdnMmioRead32(base, C_CP_RB_RPTR) & C_RPTR_MASK;     /* a record, not a gate */
    if (!cpPoisonHolds(c, base))
        return cpRefused(c, CP_WHY_POISON, c->reg5);
    c->surfaceCntl = rdnMmioRead32(base, C_SURFACE_CNTL);
    if (c->surfaceCntl != C_SURF_TRANSLATION_DIS)
        return cpRefused(c, CP_WHY_SURFACE, c->surfaceCntl);
    c->lastSeed = seed;
    c->seedUsed = 1;
    c->zprepped = 0;                    /* the client draws into the window, as after any ZCLEAR */

    /* 1: the prefix, cpZclear's words */
    n = 0;
    w[n++] = C_P0(C_SE_TCL_STATE_FLUSH);    w[n++] = 0UL;
    w[n++] = C_P0(C_SE_VAP_CNTL_STATUS);    w[n++] = 0UL;
    w[n++] = C_P0(C_PP_CNTL_X);             w[n++] = 0UL;
    w[n++] = C_P0(C_PP_TXMULTI_CTL_0);      w[n++] = 0UL;
    w[n++] = C_P0(C_SE_VTX_STATE_CNTL);     w[n++] = cs->vsc;
    w[n++] = C_P0(C_RB3D_DEPTHXY_OFFSET);   w[n++] = 0UL;       /* Mesa's init value (8-2 M1) */
    w[n++] = C_P0(C_RB3D_DEPTHOFFSET);      w[n++] = c->winStart + cpR6DepthOff(cs);
    w[n++] = C_P0(C_RB3D_DEPTHPITCH);       w[n++] = CP_R6_PITCH;
    w[n++] = C_P0(C_RB3D_COLOROFFSET);      w[n++] = c->winStart + cpR6ColorOff(cs);
    w[n++] = C_P0(C_RB3D_COLORPITCH);       w[n++] = CP_R6_PITCH;
    w[n++] = C_P0(C_SE_VTX_FMT_0);      w[n++] = CP_R7_PREFIX_FMT0;
    w[n++] = C_P0(C_SE_VTX_FMT_1);      w[n++] = CP_R7_PREFIX_FMT1;
    w[n++] = C_P0(C_PP_TRI_PERF);           w[n++] = 0UL;
    w[n++] = C_P0(C_PP_PERF_CNTL);          w[n++] = 0UL;
    w[n++] = C_P0(C_PP_TAM_DEBUG3);         w[n++] = C_PP_TAM_DEBUG3_LRU;
    w[n++] = C_P0(C_SCRATCH_REG0);          w[n++] = seed;
    c->zstage = 1;
    c->noWait = 1;
    rc = cpR6Submit(c, base, w, n);
    c->noWait = 0;
    if (rc != CP_RC_RAN)
        return rc;
    c->inflight = 1;

    /* 2: the driver's WAIT_UNTIL, the client's words, the tail -- cpZclear's words */
    n = 0;
    w[n++] = C_P0(C_WAIT_UNTIL);            w[n++] = cpR6State[1];
    for (i = 0; i < c->subWords; i++)
        w[n++] = cpR7Buf[i];
    w[n++] = C_P0(C_RB3D_DSTCACHE_CTLSTAT); w[n++] = C_PURGE_DC;
    w[n++] = C_P0(C_RB3D_ZCACHE_CTLSTAT);   w[n++] = C_PURGE_ZC;
    w[n++] = C_P0(C_WAIT_UNTIL);            w[n++] = C_WAIT_IDLE;
    w[n++] = C_P0(C_RB3D_CNTL);             w[n++] = 0UL;               /* operator D1 */
    w[n++] = C_P0(C_SCRATCH_REG0 + 8);      w[n++] = ~seed;
    if (n != need) {
        c->failed = 1;
        return cpRefused(c, CP_WHY_WORDS, n);
    }
    c->zstage = 2;
    c->noWait = 1;
    rc = cpR6Submit(c, base, w, n);
    c->noWait = 0;
    if (rc != CP_RC_RAN)
        return rc;
    c->asubmits++;
    return CP_RC_RAN;
}

/*
 * G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-3): EVERYTHING ACCEPTED IS DONE.  The reference's idle
 * path: the ring caught up, the engine idle (re-asked, G4-3 K1), then the pixel cache flushed --
 * radeon_do_wait_for_idle ends in radeon_do_pixcache_flush (radeon_cp.c 378-392).  The library
 * asks this before the CPU touches the window.  It always waits the whole way, in flight or not:
 * an idle card answers in a few reads, and "nothing in flight" is the caller's belief, not the
 * card's.
 */
static int
cpRetire(osrdn_cp_state *c, vm_address_t base)
{
    ns_time_t t0, t1;
    unsigned long v;
    int was = c->inflight;

    if (c->state != CP_ST_RUNNING)
        return cpRefused(c, CP_WHY_STATE, (unsigned long)c->state);
    IOGetTimestamp(&t0);
    if (!cpWait(base, W_RPTR, c->wptr, C_RPTR_US, &c->wRptr))
        return cpFail(c, base);
    if (!cpWaitRetry(base, W_IDLE, 0, C_IDLE_US, C_IDLE_RETRY, &c->wIdle))
        return cpFail(c, base);
    v = rdnMmioRead32(base, C_RB3D_DSTCACHE_CTLSTAT);
    rdnMmioWrite32(base, C_RB3D_DSTCACHE_CTLSTAT, v | C_DC_FLUSH_ALL);
    if (!cpWait(base, W_DC, 0, C_DC_US, &c->wDc))
        return cpLatch(c, base);
    IOGetTimestamp(&t1);
    c->inflight = 0;
    c->retireLastUs = cpElapsedUs(t0, t1);
    c->retires++;
    if (was) {
        c->retireWaited++;
        c->retireUs += c->retireLastUs;
    }
    c->zreg2 = rdnMmioRead32(base, C_SCRATCH_REG0 + 8);    /* a record: the last tail's marker */
    if (c->seedUsed && c->zreg2 != ~c->lastSeed)
        c->retireMarkBad++;
    return CP_RC_RAN;
}

/* R6e: PLANE -- nothing touches the hardware; the log prints 64 words of the stored plane
   (docs/R6E_PLAN.md 13-14) */
static int
cpPlane(osrdn_cp_state *c, unsigned long len)
{
    if (len >= 16UL || !c->planeValid || !(c->planeLanes & (1UL << (len >> 2))))
        return cpRefused(c, CP_WHY_NO_PLANE, len);
    c->planeChunk = len;
    return CP_RC_RAN;
}

/* ---- the entries ------------------------------------------------------------ */

int
osrdn_cp_allows_mode(const osrdn_cp_state *c)
{
    if (c->latched)
        return 0;
    return c->state == CP_ST_NONE || c->state == CP_ST_LOADED || c->state == CP_ST_STOPPED;
}

/* R7a: the public face of cpR7Stage (docs/R7_PLAN.md 3-2). */
int
osrdn_cp_stage(osrdn_cp_state *c, unsigned long op, unsigned long token,
               unsigned long nwords, const unsigned *words)
{
    return cpR7Stage(c, op, token, nwords, words);
}


/* ---- G3: present (docs/G3_PRESENT_PLAN.md 2-1) -----------------------------------
 *
 * The kernel's own blit of one rectangle of the client's surface onto the
 * screen: gates in the Matrox driver's order (OpenStepMGAReplacementDisplay.m
 * 6360-6500), then the reference's words down the ordinary ring (cpR6Submit
 * pads to a multiple of 16 and waits twice, as for everything else).
 *
 * REL2 (docs/REL2_PRESENT_STATE_PLAN.md): nineteen words, not the DRM swap's
 * thirteen.  The swap leans on 2D state the X server left behind -- the default
 * scissor, the write mask, the direction -- and the X driver writes them again
 * after DRM_RADEON_CP_INIT "does an engine reset, which resets some engine
 * registers back to their default values" (xf86-video-ati radeon_dri.c
 * 1219-1221); its EXA copy writes all three before every copy (radeon_exa_funcs.c
 * 107-114).  There is no X server here, and the CP's own start resets the
 * engine: a client that never cleared on the card presented into a zero
 * scissor and nothing reached the screen (GLQuake stuck on its loading console
 * after every boot, 2026-09-30).  So the blit carries the three itself, with
 * the clear's values (cpClear below).  Nothing of
 * the client's is a packet here, so the verifier has nothing to look at -- the
 * same trust boundary as cpZclear's own words.  The screen is card address 0
 * (CRTC_OFFSET 0) and the window is [winStart, winEnd); srcOrg is an offset
 * into the window, and the offset field of PITCH_OFFSET counts 1 KiB units, so
 * the card address must be 1 KiB aligned.
 */
static int
cpPresentRefuse(osrdn_cp_state *c, unsigned long verdict)
{
    c->presentVerdict = verdict;
    if (verdict < (unsigned long)OSRDN_PRESENT_VERDICTS)
        c->presentRefused[verdict]++;
    return cpRefused(c, CP_WHY_PRESENT, verdict);
}

static int
cpPresent(osrdn_cp_state *c, vm_address_t base)
{
    const osrdn_cp_present_req *q = (const osrdn_cp_present_req *)c->presentReq;
    const osrdn_r7b_present *b;
    unsigned long wd[C_PRESENT_WORDS], n = 0, winBytes, rowBytes, avail, lastRow, tail, srcPO, dstPO;
    int rc;

    c->presentVerdict = OSRDN_PRESENT_E_MODE;
    if (q == 0 || q->blk == 0)
        return cpPresentRefuse(c, OSRDN_PRESENT_E_MODE);
    b = q->blk;
    if (b->magic != OSRDN_PRESENT_MAGIC || b->version != OSRDN_PRESENT_VERSION)
        return cpPresentRefuse(c, OSRDN_PRESENT_E_MAGIC);
    if (c->latched || c->failed)
        return cpPresentRefuse(c, OSRDN_PRESENT_E_LATCH);
    if (c->state != CP_ST_RUNNING || c->winEnd <= c->winStart || (c->winStart & 1023UL) != 0UL)
        return cpPresentRefuse(c, OSRDN_PRESENT_E_MODE);
    if (q->bytesPerPixel != 4UL || q->modeW == 0UL || q->modeH == 0UL ||
        q->rowBytes == 0UL || (q->rowBytes & 63UL) != 0UL)
        return cpPresentRefuse(c, OSRDN_PRESENT_E_MODE);
    if (b->w == 0UL || b->h == 0UL || b->w > C_PRESENT_MAX_DIM || b->h > C_PRESENT_MAX_DIM ||
        b->srcStride == 0UL || b->srcStride > C_PRESENT_MAX_STRIDE || ((b->srcStride * 4UL) & 63UL) != 0UL)
        return cpPresentRefuse(c, OSRDN_PRESENT_E_GEOM);
    if (b->w > q->modeW || b->dstX > q->modeW - b->w || b->h > q->modeH || b->dstY > q->modeH - b->h)
        return cpPresentRefuse(c, OSRDN_PRESENT_E_DST);
    winBytes = c->winEnd - c->winStart;
    if (b->srcOrg >= winBytes || (b->srcOrg & 1023UL) != 0UL)
        return cpPresentRefuse(c, OSRDN_PRESENT_E_SRC);
    if (b->w > b->srcStride || b->srcX > b->srcStride - b->w)
        return cpPresentRefuse(c, OSRDN_PRESENT_E_SRC);
    avail = winBytes - b->srcOrg;
    rowBytes = b->srcStride * 4UL;              /* srcStride <= 0x8000: no overflow */
    lastRow = b->srcY + b->h - 1UL;             /* both <= 0xffff: no overflow */
    if (lastRow > (avail - 1UL) / rowBytes)
        return cpPresentRefuse(c, OSRDN_PRESENT_E_SRC);
    tail = avail - lastRow * rowBytes;
    if ((b->srcX + b->w) * 4UL > tail)
        return cpPresentRefuse(c, OSRDN_PRESENT_E_SRC);

    srcPO = ((rowBytes / 64UL) << 22) | ((c->winStart + b->srcOrg) >> 10);
    dstPO = (q->rowBytes / 64UL) << 22;         /* the screen: card address 0 */
    wd[n++] = C_P0N(C_WAIT_UNTIL, 0);           wd[n++] = C_PRESENT_WAIT_PRE;
    wd[n++] = C_P0N(C_DEFAULT_SC_BOTTOM_RIGHT, 0); wd[n++] = C_SC_MAX;              /* REL2 */
    wd[n++] = C_P0N(C_DP_WRITE_MASK, 0);        wd[n++] = 0xffffffffUL;          /* REL2 */
    wd[n++] = C_P0N(C_DP_CNTL, 0);              wd[n++] = C_DP_CNTL_L2R_T2B;     /* REL2 */
    wd[n++] = C_P0N(C_DP_GUI_MASTER_CNTL, 0);   wd[n++] = C_PRESENT_GMC;
    wd[n++] = C_P0N(C_SRC_PITCH_OFFSET, 1);     wd[n++] = srcPO;    wd[n++] = dstPO;
    wd[n++] = C_P0N(C_SRC_X_Y, 2);              wd[n++] = (b->srcX << 16) | b->srcY;
                                                wd[n++] = (b->dstX << 16) | b->dstY;
                                                wd[n++] = (b->w << 16) | b->h;
    wd[n++] = C_P0N(C_WAIT_UNTIL, 0);           wd[n++] = C_PRESENT_WAIT_POST;
    if (n != (unsigned long)C_PRESENT_WORDS) {
        c->failed = 1;
        return cpRefused(c, CP_WHY_WORDS, n);
    }
    rc = cpR6Submit(c, base, wd, n);
    if (rc == CP_RC_RAN) {
        c->presentVerdict = OSRDN_PRESENT_OK;
        c->presentOk++;
    } else {
        c->presentVerdict = OSRDN_PRESENT_E_LATCH;
        c->presentRefused[OSRDN_PRESENT_E_LATCH]++;
    }
    return rc;
}

/* ---- G3b: clear (docs/G3B_CLEAR_PLAN.md 2-1) ---------------------------------------
 *
 * The reference's radeon_cp_dispatch_clear, as the kernel's own words: the 3D
 * stream idle, then a 2D solid fill of the colour surface; the 2D stream
 * idle, then the precedent's depth state (cpR6State, word for word) and one
 * rectangle over the depth buffer at the clear depth.  Nothing of the client's
 * is a packet here either.  The card writes the depth as floor(z * 2^16)
 * (R6f), so the caller hands the float it means.
 */
static unsigned long
cpFloatBits(unsigned long n)                /* the IEEE 754 single of a small integer, no FPU in here */
{
    unsigned long e = 0, m;

    if (n == 0UL)
        return 0UL;
    m = n;
    while (m >= 2UL) {
        m >>= 1;
        e++;
    }
    m = (e <= 23UL) ? (n << (23UL - e)) : (n >> (e - 23UL));
    return ((127UL + e) << 23) | (m & 0x7fffffUL);
}

static int
cpClearRefuse(osrdn_cp_state *c, unsigned long verdict)
{
    c->clearVerdict = verdict;
    if (verdict < (unsigned long)OSRDN_PRESENT_VERDICTS)
        c->clearRefused[verdict]++;
    return cpRefused(c, CP_WHY_PRESENT, verdict);
}

static int
cpClear(osrdn_cp_state *c, vm_address_t base)
{
    const osrdn_cp_clear_req *q = (const osrdn_cp_clear_req *)c->clearReq;
    const osrdn_r7b_clear *b;
    unsigned long wd[C_CLEAR_WORDS], n = 0, winBytes, avail, rowBytes, lastRow, tail, k, fw, fh;
    int rc;

    c->clearVerdict = OSRDN_PRESENT_E_MODE;
    if (q == 0 || q->blk == 0)
        return cpClearRefuse(c, OSRDN_PRESENT_E_MODE);
    b = q->blk;
    if (b->magic != OSRDN_CLEAR_MAGIC || b->version != OSRDN_CLEAR_VERSION)
        return cpClearRefuse(c, OSRDN_PRESENT_E_MAGIC);
    if (c->latched || c->failed)
        return cpClearRefuse(c, OSRDN_PRESENT_E_LATCH);
    if (c->state != CP_ST_RUNNING || c->winEnd <= c->winStart || (c->winStart & 1023UL) != 0UL)
        return cpClearRefuse(c, OSRDN_PRESENT_E_MODE);
    if (q->bytesPerPixel != 4UL)
        return cpClearRefuse(c, OSRDN_PRESENT_E_MODE);
    if (b->flags == 0UL || (b->flags & ~(OSRDN_CLEAR_COLOUR | OSRDN_CLEAR_DEPTH)) != 0UL ||
        b->w == 0UL || b->h == 0UL || b->w > C_PRESENT_MAX_DIM || b->h > C_PRESENT_MAX_DIM ||
        b->depthZ > C_CLEAR_ONE)                /* 0.0 .. 1.0 as float bits, sign clear */
        return cpClearRefuse(c, OSRDN_PRESENT_E_GEOM);
    winBytes = c->winEnd - c->winStart;
    if (b->flags & OSRDN_CLEAR_COLOUR) {
        if (b->colourPitch == 0UL || b->colourPitch > C_CLEAR_MAX_PITCH || ((b->colourPitch * 4UL) & 63UL) != 0UL)
            return cpClearRefuse(c, OSRDN_PRESENT_E_GEOM);
        if (b->colourOff >= winBytes || (b->colourOff & 1023UL) != 0UL || b->w > b->colourPitch)
            return cpClearRefuse(c, OSRDN_PRESENT_E_SRC);
        avail = winBytes - b->colourOff;
        rowBytes = b->colourPitch * 4UL;
        lastRow = b->h - 1UL;
        if (lastRow > (avail - 1UL) / rowBytes)
            return cpClearRefuse(c, OSRDN_PRESENT_E_SRC);
        tail = avail - lastRow * rowBytes;
        if (b->w * 4UL > tail)
            return cpClearRefuse(c, OSRDN_PRESENT_E_SRC);
    }
    if (b->flags & OSRDN_CLEAR_DEPTH) {
        unsigned long rows = (b->h + 15UL) & ~15UL;     /* the layout's rounding (OSRDNMesaDepth.c 75-77) */

        if (b->depthPitch == 0UL || b->depthPitch > C_CLEAR_MAX_PITCH || (b->depthPitch & 31UL) != 0UL)
            return cpClearRefuse(c, OSRDN_PRESENT_E_GEOM);
        if (b->depthOff >= winBytes || (b->depthOff & 31UL) != 0UL || b->w > b->depthPitch)
            return cpClearRefuse(c, OSRDN_PRESENT_E_SRC);
        avail = winBytes - b->depthOff;
        rowBytes = b->depthPitch * 2UL;
        if (rows > avail / rowBytes)
            return cpClearRefuse(c, OSRDN_PRESENT_E_SRC);
    }
    fw = cpFloatBits(b->w);
    fh = cpFloatBits(b->h);
    if (b->flags & OSRDN_CLEAR_COLOUR) {
        /* G3d: the X driver's solid fill (Emit2DState, then Solid), register by register.  Boot 6
           measured the DRM's PAINT_MULTI packet writing NOTHING through this CP (a red clear left
           no red word in the whole window), while the register-driven present blit draws -- and
           nobody in this stack had ever written DP_CNTL, which the X server always sets.  So the
           fill is the blit's shape now, with DP_CNTL in it. */
        wd[n++] = C_P0N(C_WAIT_UNTIL, 0);           wd[n++] = C_PRESENT_WAIT_PRE;    /* 3D idle before the 2D fill */
        wd[n++] = C_P0N(C_DEFAULT_SC_BOTTOM_RIGHT, 0); wd[n++] = C_SC_MAX;
        wd[n++] = C_P0N(C_DP_GUI_MASTER_CNTL, 0);   wd[n++] = C_CLEAR_GMC;
        wd[n++] = C_P0N(C_DP_BRUSH_FRGD_CLR, 0);    wd[n++] = b->colourValue;
        wd[n++] = C_P0N(C_DP_BRUSH_BKGD_CLR, 0);    wd[n++] = 0UL;
        wd[n++] = C_P0N(C_DP_SRC_FRGD_CLR, 0);      wd[n++] = 0xffffffffUL;
        wd[n++] = C_P0N(C_DP_SRC_BKGD_CLR, 0);      wd[n++] = 0UL;
        wd[n++] = C_P0N(C_DP_WRITE_MASK, 0);        wd[n++] = 0xffffffffUL;
        wd[n++] = C_P0N(C_DP_CNTL, 0);              wd[n++] = C_DP_CNTL_L2R_T2B;
        wd[n++] = C_P0N(C_DST_PITCH_OFFSET, 0);     wd[n++] = ((b->colourPitch * 4UL / 64UL) << 22) | ((c->winStart + b->colourOff) >> 10);
        wd[n++] = C_P0N(C_DST_Y_X, 0);              wd[n++] = 0UL;   /* y 0, x 0 */
        wd[n++] = C_P0N(C_DST_HEIGHT_WIDTH, 0);     wd[n++] = (b->h << 16) | b->w;
        wd[n++] = C_P0N(C_WAIT_UNTIL, 0);           wd[n++] = C_PRESENT_WAIT_POST;   /* 2D idle: the fill has landed */
    }
    if (b->flags & OSRDN_CLEAR_DEPTH) {
        for (k = 0; k < 26UL; k++)                  /* WAIT_UNTIL 2D|HOST and the twelve state pairs */
            wd[n++] = cpR6State[k];
        wd[n - 26UL + 9UL] = C_CLEAR_ZSTENCIL;      /* G3c: the client's 16-bit format, not the precedent's 24-bit */
        wd[n++] = C_P0N(C_RB3D_DEPTHOFFSET, 1);     wd[n++] = c->winStart + b->depthOff; wd[n++] = b->depthPitch;
        wd[n++] = C_P0N(C_RE_TOP_LEFT, 0);          wd[n++] = 0UL;
        wd[n++] = C_P0N(C_RE_WIDTH_HEIGHT, 0);      wd[n++] = ((b->h - 1UL) << 16) | (b->w - 1UL);
        wd[n++] = C_P3_IMMD(12);                    wd[n++] = C_CLEAR_PRIM;
        wd[n++] = 0UL; wd[n++] = 0UL; wd[n++] = b->depthZ; wd[n++] = C_CLEAR_ONE;
        wd[n++] = 0UL; wd[n++] = fh;  wd[n++] = b->depthZ; wd[n++] = C_CLEAR_ONE;
        wd[n++] = fw;  wd[n++] = fh;  wd[n++] = b->depthZ; wd[n++] = C_CLEAR_ONE;
    }
    if (n > (unsigned long)C_CLEAR_WORDS) {
        c->failed = 1;
        return cpRefused(c, CP_WHY_WORDS, n);
    }
    rc = cpR6Submit(c, base, wd, n);
    if (rc == CP_RC_RAN) {
        c->clearVerdict = OSRDN_PRESENT_OK;
        c->clearOk++;
    } else {
        c->clearVerdict = OSRDN_PRESENT_E_LATCH;
        c->clearRefused[OSRDN_PRESENT_E_LATCH]++;
    }
    return rc;
}

void
osrdn_cp_quiesce(osrdn_cp_state *c, vm_address_t base)
{
    if (base == 0)
        return;
    if (c->state == CP_ST_MAPPED || c->state == CP_ST_RUNNING)
        (void)cpStop(c, base);
    else if (c->latched)
        (void)cpStopLatched(c, base);
}

int
osrdn_cp_run(osrdn_cp_state *c, vm_address_t base, int op, unsigned long arg,
             unsigned long len, int engineLatched)
{
    ns_time_t t0, t1;
    int k;

    IOGetTimestamp(&t0);
    cpIoRd = cpIoWr = 0;
    c->ops++;
    c->op = op;
    c->arg = arg;
    c->len = len;
    c->rc = CP_RC_REFUSED;
    c->why = CP_WHY_NONE;
    c->gateValue = 0;
    c->gateReg = 0;
    c->mgDone = 0;
    c->mgBad = 0;
    for (k = 0; k < CP_MG_COUNT; k++)
        c->mg[k] = 0;
    for (k = 0; k < CP_REC_COUNT; k++)
        c->rec[k] = 0;
    for (k = 0; k < 3; k++)
        c->marker[k] = c->sentinel[k] = c->got[k] = 0;
    c->reg5 = 0;
    c->rptrBefore = c->rptrAfter = c->wptrAfter = 0;
    c->rptrOff = c->wptrOff = 0;
    for (k = 0; k < CP_R6_REC_COUNT; k++)
        c->r3[k] = 0;
    c->covValid = 0;
    if (op == CP_OP_ZPREP || op == CP_OP_ZCLEAR)
        c->planeValid = 0;                  /* R6e: before any refusal (docs/R6E_PLAN.md 14) */
    for (k = 0; k < CP_R6_PRE_COUNT; k++)
        c->pre[k] = 0;
    c->surfaceCntl = c->prefixBad = c->zreg0 = c->zreg2 = c->prepBad = 0;
    c->zcase = c->zstage = 0;
    c->tOn = 0;                 /* M1z: every operation starts untimed */
    c->noWait = 0;              /* G5-2: ... and synchronous; only cpAsubmit sets it, around its two writes */
    for (k = 0; k < 2; k++) {
        c->dDepth[k].xr = c->dDepth[k].wsum = c->dDepth[k].changed = c->dDepth[k].ixor = c->dDepth[k].isum = 0;
        c->dColor[k].xr = c->dColor[k].wsum = c->dColor[k].changed = c->dColor[k].ixor = c->dColor[k].isum = 0;
        c->dDepth[k].nvals = c->dColor[k].nvals = 0;
        c->dDepth[k].vals[0] = c->dDepth[k].vals[1] = c->dDepth[k].vals[2] = c->dDepth[k].vals[3] = 0;
        c->dColor[k].vals[0] = c->dColor[k].vals[1] = c->dColor[k].vals[2] = c->dColor[k].vals[3] = 0;
        c->restChanged[k] = 0;
    }
    c->restFirst = c->restFirstVal = 0;
    c->restSkipped = 0;
    c->straddle = 0;
    c->boundary = 0;
    c->tableBad = c->guardBad = c->spareBad = c->canaryBad = c->ringBad = 0;
    c->pteSum = c->pteXor = 0;
    c->wFifo.evals = c->wIdle.evals = c->wRptr.evals = c->wIdle2.evals = c->wDc.evals = 0;
    /* M2b: AND the turn counts.  The first M2b boot reported `rptr evals=0 turns=2`
       on refused submissions -- cpWait had not run, so nothing re-initialised the
       struct, and the line carried the PREVIOUS operation's turns as if they were
       this one's.  A counter that is not cleared reports an old run's number. */
    c->wFifo.turns = c->wIdle.turns = c->wRptr.turns = c->wIdle2.turns = c->wDc.turns = 0;
    c->wFifo.limit = c->wIdle.limit = c->wRptr.limit = c->wIdle2.limit = c->wDc.limit = 0;
    c->wFifo.us = c->wIdle.us = c->wRptr.us = c->wIdle2.us = c->wDc.us = 0;
    c->wFifo.resets = c->wIdle.resets = c->wRptr.resets = c->wIdle2.resets = c->wDc.resets = 0;      /* G4-3 K1 */
    c->wFifo.retries = c->wIdle.retries = c->wRptr.retries = c->wIdle2.retries = c->wDc.retries = 0;
    c->mclkBefore = c->mclkForced = c->mclkAfter = 0;
    c->indexBefore = c->indexAfter = c->softBefore = c->softAfter = 0;
    c->csqStat = c->csq2Stat = c->aicStat = 0;
    c->csqRead = 0;
    c->postStatus = 0;
    c->latchRead = 0;                   /* M3i: the fifo/ring arrays are left; latchRead says whether they are this op's */
    c->cpStat = c->rbRptr = c->rbWptr = c->csqMode = c->wptrRead = 0;
    c->kickWptr = c->kickWptrRead = c->kickRptr = 0; c->kickMoved = 0;
    c->recoverKind = 0;                 /* M3j: recovers is sticky */
    c->wKick.turns = 0; c->wKick.limit = 0; c->wKick.us = 0;

    if (!c->keyOn)
        (void)cpRefuse(c, CP_WHY_KEY, 0);
    else if (!c->blockOk)
        (void)cpRefuse(c, CP_WHY_NO_BLOCK, 0);
    else if (base == 0 || op < CP_OP_RECORD || op > CP_OP_LAST)
        (void)cpRefuse(c, CP_WHY_BAD_OP, (unsigned long)op);
    else if (op == CP_OP_STOP)
        c->rc = cpStop(c, base);            /* runs latched or not */
    else if (op == CP_OP_RECORD && c->latched && !c->latchInjected)
        (void)cpRefuse(c, CP_WHY_LATCHED, 0);   /* a real latch: nothing more is read (R5d 7) */
    else if (op == CP_OP_RECORD) {
        c->rc = cpRecord(c, base);
        if (c->state != CP_ST_NONE)
            (void)cpCheckBlock(c);
    } else if (c->latched)
        (void)cpRefuse(c, CP_WHY_LATCHED, 0);
    else if (engineLatched)
        (void)cpRefuse(c, CP_WHY_ENGINE, 0);
    else if (op == CP_OP_LOAD)
        c->rc = cpLoad(c, base);
    else if (op == CP_OP_MAP)
        c->rc = cpMap(c, base);
    else if (op == CP_OP_RESET)
        c->rc = cpReset(c, base);
    else if (op == CP_OP_START)
        c->rc = cpStart(c, base);
    else if (op == CP_OP_SUBMIT)
        c->rc = cpSubmit(c, base, arg, len, 0);
    else if (op == CP_OP_NEGCTL)
        c->rc = cpNegctl(c, base, arg);
    else if (op == CP_OP_REC3D)
        c->rc = cpRec3d(c, base);
    else if (op == CP_OP_ZPREP)
        c->rc = cpZprep(c, base);
    else if (op == CP_OP_ZCLEAR)
        c->rc = cpZclear(c, base, arg, len);
    else if (op == CP_OP_PLANE)
        c->rc = cpPlane(c, len);
    else if (op == CP_OP_QUIET)
        c->rc = cpQuiet(c, len);
    else if (op == CP_OP_TDUMP)
        c->rc = cpTDump(c);
    else if (op == CP_OP_NOWB)
        c->rc = cpNoWb(c, len);
    else if (op == CP_OP_SPIN)
        c->rc = cpSpinSet(c, len);
    else if (op == CP_OP_TIME)
        c->rc = cpTimeSet(c, len);
    else if (op == CP_OP_PRESENT)
        c->rc = cpPresent(c, base);
    else if (op == CP_OP_CLEAR)
        c->rc = cpClear(c, base);
    else if (op == CP_OP_ASUBMIT)
        c->rc = cpAsubmit(c, base, arg);
    else if (op == CP_OP_RETIRE)
        c->rc = cpRetire(c, base);
    else if (op == CP_OP_LOUD)
        c->rc = cpLoud(c, len);
    /*
     * M1n: INJECT IS NAMED NOW.
     *
     * This used to be the wildcard `else`: any in-range op with no branch of
     * its own became an INJECT.  Only 9 ever reached it, so nothing was wrong
     * -- but the next op added without a branch would have been submitted to
     * the card instead of refused.  A cross-review named it; the fix is one
     * test and a terminal refusal, and it costs nothing.
     */
    else if (op == CP_OP_INJECT) {
        if (!c->injectKey)
            (void)cpRefuse(c, CP_WHY_KEY, (unsigned long)op);
        else
            c->rc = cpSubmit(c, base, arg, len, 1);
    }
    else
        (void)cpRefuse(c, CP_WHY_BAD_OP, (unsigned long)op);
    /* the CSQ pointers after every operation, refused ones too, as a record
       (12-5 G3) -- never with a latch, the CP's or the R4 engine's: after one,
       only CSQ_CNTL and one status word are touched */
    if (c->keyOn && c->blockOk && base != 0 && !c->latched && !engineLatched && op >= CP_OP_RECORD && op <= CP_OP_LAST
        && cpCond(base, W_IDLE, 0)) {         /* status first, the R4 rule */
        c->csqStat = rdnMmioRead32(base, C_CP_CSQ_STAT);
        c->csq2Stat = rdnMmioRead32(base, C_CP_CSQ2_STAT);
        c->aicStat = rdnMmioRead32(base, C_AIC_STAT);
        c->csqRead = 1;
    }
    c->ioRd = cpIoRd;
    c->ioWr = cpIoWr;
    IOGetTimestamp(&t1);
    c->elapsedUs = cpElapsedUs(t0, t1);
    return c->rc;
}
