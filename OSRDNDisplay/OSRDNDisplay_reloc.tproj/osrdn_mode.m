/*
 * osrdn_mode.m - the R2b first mode set.  Plain C89; no logging, no floating
 * point, no 64-bit division.  See osrdn_mode.h for the contract.
 *
 * Register order and bit composition follow xf86's legacy CRTC path
 * (RADEONRestoreCrtcRegisters, RADEONRestorePLLRegisters) with NetBSD's
 * radeonfb as the cross-check.  The values come from the host oracle through
 * osrdn_mode_expect.h; everything else is this boot's snapshot.
 */

#import <driverkit/generalFuncs.h>       /* IOGetTimestamp, IOSleep, ns_time_t */
#import <kernserv/machine/spl.h>         /* splhigh/splx, for the sequence claim */
/* This unit instantiates the FIFO and divider tables.  Defined before the
   FIRST import that reaches osrdn_mode_expect.h: #import reads a file once. */
#define OSRDN_MODE_TABLES_R3
#import "osrdn_mode.h"
#import "osrdn_r7b.h"                   /* G3: the present request handed down under the claim */
#import "RDNR2aMMIO.h"

/* ---- bit definitions, from the reference headers -------------------------- */
#define CRTC_EN                 0x02000000UL    /* radeon_reg.h RADEON_CRTC_EN */
#define CRTC_DISP_REQ_EN_B      0x04000000UL
#define CRTC_EXT_DISP_EN        0x01000000UL
#define CRTC_HSYNC_DIS          0x00000100UL
#define CRTC_VSYNC_DIS          0x00000200UL
#define CRTC_DISPLAY_DIS        0x00000400UL
#define CRTC_CRT_ON             0x00008000UL
#define VGA_ATI_LINEAR          0x00000008UL
#define XCRT_CNT_EN             0x00000040UL
#define CRTC_DIS_ALL            (CRTC_HSYNC_DIS | CRTC_VSYNC_DIS | CRTC_DISPLAY_DIS)

#define PPLL_RESET              0x00000001UL
#define PPLL_SLEEP              0x00000002UL
#define PPLL_ATOMIC_UPDATE_EN   0x00010000UL
#define PPLL_VGA_ATOMIC_EN      0x00020000UL
#define PPLL_ATOMIC_UPDATE_BIT  0x00008000UL    /* _R and _W are the same bit */
#define PPLL_REF_DIV_MASK       0x000003ffUL
#define PPLL_FB3_DIV_MASK       0x000007ffUL
#define PPLL_POST3_DIV_MASK     0x00070000UL

#define VCLK_SRC_SEL_MASK       0x00000003UL
#define VCLK_SRC_SEL_CPUCLK     0x00000000UL
#define VCLK_SRC_SEL_PPLLCLK    0x00000003UL
#define PIXCLK_DAC_ALWAYS_ONb   0x00000080UL

#define PLL_DIV_SEL_MASK        0x00000300UL
#define PLL_DIV_SEL_3           0x00000300UL

#define DAC_RANGE_CNTL          0x00000003UL
#define DAC_BLANKING            0x00000004UL
#define DAC_MASK_ALL            0xff000000UL
#define DAC_8BIT_EN             0x00000100UL

#define DISP_RGB_OFFSET_EN      0x00000100UL

/* step-0 conditions (docs/R2_CLOSEOUT.md 11); the number after each is the
   line of ref/upstream/unpacked/xf86-video-ati-6.14.6/src/radeon_reg.h */
#define CRTC2_EN                0x02000000UL    /* 414, CRTC2_GEN_CNTL bit 25 */
#define FP_FPON                 0x00000001UL    /* 840, FP_GEN_CNTL bit 0 */
#define CSQ_MODE_MASK           0xf0000000UL    /* 3141-3143, CP_CSQ_CNTL mode nibble; 0 = PRIDIS_INDDIS */
#define RBBM_ACTIVE             0x80000000UL    /* 1487, RBBM_STATUS bit 31 */
#define PCIGART_TRANSLATE_EN    0x00000001UL    /* 3164, AIC_CNTL bit 0 */
#define SCALER_ENABLE           0x40000000UL    /* 1264, OV0_SCALE_CNTL */
#define I2C_EN                  0x00020000UL    /* 1014, I2C_CNTL_1 bit 17 */
#define VIPH_EN                 0x00200000UL    /* 1692, VIPH_CONTROL bit 21 */
#define DISP_DAC_SOURCE_MASK    0x00000003UL    /* 614, DISP_OUTPUT_CNTL; 0 = CRTC1 */
#define SURF_TRANSLATION_DIS    0x00000100UL    /* 1592, SURFACE_CNTL bit 8 */
#define SURF_AP_SWAP_MASK       0x00f00000UL    /* 1593-1596, NONSURF_AP0/1_SWP_16/32BPP */
#define HDP_SOFT_RESET          0x04000000UL    /* 993, HOST_PATH_CNTL bit 26 */

#define CRTC_PIX_WIDTH_SHIFT    8                       /* CRTC_GEN_CNTL bits 8-11, the pixel format */
#define CRTC_PIX_WIDTH_MASK     0x00000f00UL
#define LUT_TOP_BITS            0x3fcff3fcUL            /* the top 8 of each 10-bit component */

/* ---- time ----------------------------------------------------------------- */
/*
 * The same shape as osrdn_record.m's elapsedUs (the AC97 driver's): no 64-bit
 * division, a backward clock reads as zero, and the 32-bit truncation happens
 * before the divide.  IOGetTimestamp is never read at raised spl.
 */
static unsigned long
modeElapsedUs(ns_time_t t0, ns_time_t t1)
{
    ns_time_t       d;
    unsigned int    low;

    if (t1 <= t0)
        return 0;
    d = t1 - t0;
    if (d > 0xffffffffULL)
        return 0xffffffffUL;
    low = (unsigned int)d;
    return (unsigned long)(low / 1000U);
}

/* ---- bounded waits ---------------------------------------------------------
 *
 * Every wait here has TWO bounds.  The elapsed-time bound is the real one.
 * The turn bound is there because nothing promises IOGetTimestamp advances in
 * every context this code is called from: the kernel calls -revertToVGAMode at
 * shutdown and we do not know its spl, and a for(;;) that never exits at
 * shutdown never finishes shutting down.  Before 2026-09-16 all five waits in
 * this file had the time bound alone.
 *
 * How a turn passes depends on the caller.  IOSleep yields; IODelay spins.
 * doc/driverkit.md 293-309 measured IOSleep stopping this machine inside a
 * network-stack ioctl (the stack lock and spl held) and says IODelay is safe
 * at any spl, so a caller that cannot sleep sets mode->noSleep and pays in CPU.
 */

static void
modeWaitTick(const osrdn_mode_state *mode)
{
    if (mode->noSleep)
        IODelay((unsigned)MODE_TICK_US);
    else
        IOSleep((unsigned)MODE_TICK_MS);
}

static unsigned long
modeWaitUs(const osrdn_mode_state *mode, unsigned long limitUs, osrdn_wait *w)
{
    ns_time_t       t0, t1;
    unsigned long   turns = 0, tickUs, maxTurns;

    /* The turn cap exists only for a clock that does not advance, so it is
     * deliberately generous: twice the nominal turns.  A cap of limit/tick + 8
     * FIRED on this machine in normal running -- its IODelay runs short
     * (IODelay(2000) measured 1872-1881 us, docs/R2B0_RESULT.md 2), so 207
     * IODelay(500) came to ~96.9 ms of clock and the 100 ms wait ended on the
     * cap (logged 208/1, docs/R2_CLOSEOUT.md 14).  A cap of maxTurns allows
     * maxTurns - 1 ticks: the cap is tested before each tick. */
    tickUs = mode->noSleep ? MODE_TICK_US : (MODE_TICK_MS * 1000UL);
    maxTurns = (limitUs / tickUs) * MODE_TURN_FACTOR + MODE_SETTLE_SLACK;
    w->evals = 0;
    w->limit = 0;
    IOGetTimestamp(&t0);
    for (;;) {
        IOGetTimestamp(&t1);
        w->evals++;                     /* counted before the test: "it ran" */
        if (modeElapsedUs(t0, t1) >= limitUs)
            break;
        turns++;
        if (turns >= maxTurns) {
            w->limit = 1;               /* the turn bound, not the clock, ended it */
            break;
        }
        modeWaitTick(mode);
    }
    return modeElapsedUs(t0, t1);
}

/* ---- the PLL block, shared by the entry and the revert (12-5) ------------- */
/*
 * xf86 RADEONRestorePLLRegisters, 6a..6m of the plan.  refdiv is written back
 * unchanged whatever the caller passes -- PPLL_REF_DIV is shared by all four
 * divider slots, so changing it would move the console's slot too (plan 2-8).
 * PVG is NOT in the clear mask: this card locks the target VCO with the gain
 * the firmware left, and no reference preserves or restores PVG the same way
 * twice (docs/R2B_IMPL_PLAN.md 12-1).
 */
static void
pllProgram(osrdn_mode_state *mode, vm_address_t base,
           unsigned long div3, unsigned long htotal, int isRevert)
{
    ns_time_t       t0, t1;
    unsigned long   v, loops;
    osrdn_wait     *w;

    /* 6a: take the CRTC off the PPLL before touching it */
    v = osrdn_pll_get(base, SNAP_VCLK_ECP_CNTL);
    osrdn_pll_put(base, SNAP_VCLK_ECP_CNTL, (v & ~VCLK_SRC_SEL_MASK) | VCLK_SRC_SEL_CPUCLK);

    /* 6b: reset and open the atomic update window.  PVG untouched. */
    v = osrdn_pll_get(base, SNAP_PPLL_CNTL);
    osrdn_pll_put(base, SNAP_PPLL_CNTL, v | PPLL_RESET | PPLL_ATOMIC_UPDATE_EN | PPLL_VGA_ATOMIC_EN);

    /* 6c: select divider slot 3 */
    v = osrdn_mmio_get(base, SNAP_CLOCK_CNTL_INDEX);
    osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, (v & ~PLL_DIV_SEL_MASK) | PLL_DIV_SEL_3);

    /* 6d: the reference divider, written back with the value that is there */
    v = osrdn_pll_get(base, SNAP_PPLL_REF_DIV);
    osrdn_pll_put(base, SNAP_PPLL_REF_DIV,
                  (v & ~PPLL_REF_DIV_MASK) | (mode->refdiv & PPLL_REF_DIV_MASK));

    /* 6e, 6f: feedback then post, two writes as the reference does */
    v = osrdn_pll_get(base, SNAP_PPLL_DIV_3);
    osrdn_pll_put(base, SNAP_PPLL_DIV_3, (v & ~PPLL_FB3_DIV_MASK) | (div3 & PPLL_FB3_DIV_MASK));
    v = osrdn_pll_get(base, SNAP_PPLL_DIV_3);
    osrdn_pll_put(base, SNAP_PPLL_DIV_3, (v & ~PPLL_POST3_DIV_MASK) | (div3 & PPLL_POST3_DIV_MASK));

    /* 6g: wait for the previous atomic update to finish, bounded */
    w = isRevert ? &mode->wRevAtomicW : &mode->wAtomicW;
    w->evals = 0;
    w->limit = 0;
    IOGetTimestamp(&t0);
    loops = 0;
    for (;;) {
        v = osrdn_pll_get(base, SNAP_PPLL_REF_DIV);
        w->evals++;
        if (!(v & PPLL_ATOMIC_UPDATE_BIT))
            break;
        loops++;
        if (loops >= MODE_POLL_LOOPS)
            break;
        IOGetTimestamp(&t1);
        if (modeElapsedUs(t0, t1) >= MODE_ATOMIC_US)
            break;
    }
    IOGetTimestamp(&t1);
    w->limit = (v & PPLL_ATOMIC_UPDATE_BIT) ? 1 : 0;
    if (isRevert)
        mode->revAtomicReadSkipped = w->limit;
    else
        mode->atomicReadSkipped = w->limit;
    if (isRevert) {
        mode->atomicWriteLoops = loops;
    } else {
        mode->atomicWriteUs = modeElapsedUs(t0, t1);
        mode->atomicWriteLoops = loops;
        mode->atomicWriteLimit = (v & PPLL_ATOMIC_UPDATE_BIT) ? 1 : 0;
    }

    /* 6h: trigger it */
    if (!(v & PPLL_ATOMIC_UPDATE_BIT)) {
        v = osrdn_pll_get(base, SNAP_PPLL_REF_DIV);
        osrdn_pll_put(base, SNAP_PPLL_REF_DIV, v | PPLL_ATOMIC_UPDATE_BIT);

        /* 6i: wait for it to clear, bounded */
        w = isRevert ? &mode->wRevAtomicR : &mode->wAtomicR;
        w->evals = 0;
        w->limit = 0;
        IOGetTimestamp(&t0);
        loops = 0;
        for (;;) {
            v = osrdn_pll_get(base, SNAP_PPLL_REF_DIV);
            w->evals++;
            if (!(v & PPLL_ATOMIC_UPDATE_BIT))
                break;
            loops++;
            if (loops >= MODE_POLL_LOOPS)
                break;
            IOGetTimestamp(&t1);
            if (modeElapsedUs(t0, t1) >= MODE_ATOMIC_US)
                break;
        }
        IOGetTimestamp(&t1);
        w->limit = (v & PPLL_ATOMIC_UPDATE_BIT) ? 1 : 0;
        if (!isRevert) {
            mode->atomicReadUs = modeElapsedUs(t0, t1);
            mode->atomicReadLoops = loops;
            mode->atomicReadLimit = (v & PPLL_ATOMIC_UPDATE_BIT) ? 1 : 0;
        }
    }

    /* 6j: HTOTAL_CNTL as a whole word */
    osrdn_pll_put(base, SNAP_HTOTAL_CNTL, htotal);

    /* 6k: leave reset and the update window */
    v = osrdn_pll_get(base, SNAP_PPLL_CNTL);
    osrdn_pll_put(base, SNAP_PPLL_CNTL,
                  v & ~(PPLL_RESET | PPLL_SLEEP | PPLL_ATOMIC_UPDATE_EN | PPLL_VGA_ATOMIC_EN));

    /* 6l: let it lock */
    if (!isRevert)
        mode->settleUs = modeWaitUs(mode, MODE_PLL_SETTLE_US, &mode->wSettle);
    else
        mode->revertSettleUs = modeWaitUs(mode, MODE_PLL_SETTLE_US, &mode->wRevSettle);

    /* 6m: the CRTC runs off the PPLL again */
    v = osrdn_pll_get(base, SNAP_VCLK_ECP_CNTL);
    osrdn_pll_put(base, SNAP_VCLK_ECP_CNTL, (v & ~VCLK_SRC_SEL_MASK) | VCLK_SRC_SEL_PPLLCLK);
}

/* ---- entry steps ---------------------------------------------------------- */

static int
modeRefuse(osrdn_mode_state *mode, int which, unsigned long value)
{
    mode->why = MODE_WHY_CLIENT;
    mode->clientWhich = which;
    mode->clientValue = value;
    return 0;
}

/* (value & mask) must equal want */
static int
modeGate(osrdn_mode_state *mode, int which, unsigned long value,
         unsigned long mask, unsigned long want)
{
    if ((value & mask) != want)
        return modeRefuse(mode, which, value);
    return 1;
}

static int
modeCheck(osrdn_mode_state *mode, vm_address_t base)
{
    unsigned long v;

    if (base == 0) {
        mode->why = MODE_WHY_NO_BASE;
        return 0;
    }
    if (mode->latched) {
        mode->why = MODE_WHY_LATCHED;
        return 0;
    }
    mode->clientWhich = 0;
    mode->clientValue = 0;

    /* Step 0, every entry (docs/R2_CLOSEOUT.md 7, 10, 11): what must be off or
     * true for this mode set to be safe, as semantic conditions -- never a boot
     * value copied into the code (H5).  Every one held on both measured boots
     * (R2a 789467668, R2b-0 789526262).  None of them is anything this driver
     * writes, which is why re-entry checks them too.  When CP or engine work
     * begins (PLAN.md R4, R5) cpmode and rbbm will reflect our own activity
     * and must be revisited. */
    if (!modeGate(mode, GATE_CRTC2, osrdn_peek(base, PEEK_CRTC2_GEN_CNTL), CRTC2_EN, 0))
        return 0;
    if (!modeGate(mode, GATE_FPON, osrdn_peek(base, PEEK_FP_GEN_CNTL), FP_FPON, 0))
        return 0;
    if (!modeGate(mode, GATE_CPMODE, osrdn_peek(base, PEEK_CP_CSQ_CNTL), CSQ_MODE_MASK, 0))
        return 0;
    if (!modeGate(mode, GATE_RBBM, osrdn_peek(base, PEEK_RBBM_STATUS), RBBM_ACTIVE, 0))
        return 0;
    if (!modeGate(mode, GATE_GART, osrdn_peek(base, PEEK_AIC_CNTL), PCIGART_TRANSLATE_EN, 0))
        return 0;
    if (!modeGate(mode, GATE_INTCNTL, osrdn_peek(base, PEEK_GEN_INT_CNTL), 0xffffffffUL, 0))
        return 0;
    if (!modeGate(mode, GATE_SCALER, osrdn_peek(base, PEEK_OV0_SCALE_CNTL), SCALER_ENABLE, 0))
        return 0;
    if (!modeGate(mode, GATE_I2C, osrdn_peek(base, PEEK_I2C_CNTL_1), I2C_EN, 0))
        return 0;
    if (!modeGate(mode, GATE_VIPH, osrdn_peek(base, PEEK_VIPH_CONTROL), VIPH_EN, 0))
        return 0;
    if (!modeGate(mode, GATE_DACSRC, osrdn_peek(base, PEEK_DISP_OUTPUT_CNTL),
                  DISP_DAC_SOURCE_MASK, 0))
        return 0;
    /* step 8 leaves DAC_CNTL2 alone BECAUSE it is 0 */
    if (!modeGate(mode, GATE_DAC2, osrdn_peek(base, PEEK_DAC_CNTL2), 0xffffffffUL, 0))
        return 0;
    /* F5: translation disabled, and no aperture byte swap -- the pattern and the
       window server write little-endian 32-bit pixels straight into BAR0 */
    if (!modeGate(mode, GATE_SURFACE, osrdn_peek(base, PEEK_SURFACE_CNTL),
                  SURF_TRANSLATION_DIS | SURF_AP_SWAP_MASK, SURF_TRANSLATION_DIS))
        return 0;
    if (!modeGate(mode, GATE_HOSTPATH, osrdn_peek(base, PEEK_HOST_PATH_CNTL), HDP_SOFT_RESET, 0))
        return 0;
    /* the aperture the class mapped is the one the card decodes, and it is
       big enough; the displayed base follows the memory map */
    if (!modeGate(mode, GATE_APER0, osrdn_peek(base, PEEK_CONFIG_APER_0_BASE),
                  0xffffffffUL, mode->bar0))
        return 0;
    v = osrdn_peek(base, PEEK_CONFIG_APER_SIZE);
    if (v < mode->mappedLength)
        return modeRefuse(mode, GATE_APERSIZE, v);
    v = osrdn_peek(base, PEEK_CONFIG_MEMSIZE);
    if (v < mode->mappedLength)
        return modeRefuse(mode, GATE_MEMSIZE, v);
    v = (osrdn_peek(base, PEEK_MC_FB_LOCATION) & 0xffffUL) << 16;
    if (!modeGate(mode, GATE_DISPLAYBASE, osrdn_peek(base, PEEK_DISPLAY_BASE_ADDR),
                  0xffffffffUL, v))
        return 0;
    /* H1: the divider slot the boot selected is one we have seen, {1, 3}.
       Entry selects 3 and the revert puts back what it read, so our own state
       is always inside the set too. */
    v = (osrdn_mmio_get(base, SNAP_CLOCK_CNTL_INDEX) & PLL_DIV_SEL_MASK) >> 8;
    if (v != 1UL && v != 3UL)
        return modeRefuse(mode, GATE_DIVSEL, v);

    /* The gate below describes the state the KERNEL CONSOLE leaves, so it only
     * applies while we have written nothing.  On a second -enterLinearMode the
     * card carries our own mode -- extended display enabled -- which this gate
     * would refuse; what has to hold there is that the snapshot we will revert
     * to is still the console's (modeSnapshot keeps it and re-checks the live
     * PLL instead). */
    if (mode->snapshotValid)
        return 1;
    /* semantic conditions only: the boot state differs between boots (H5, H6) */
    v = osrdn_mmio_get(base, SNAP_CRTC_GEN_CNTL);
    if (!(v & CRTC_EN) || (v & CRTC_EXT_DISP_EN)) {
        mode->why = MODE_WHY_CRTC_STATE;
        return 0;
    }
    return 1;
}

static int
modeSnapshot(osrdn_mode_state *mode, vm_address_t base)
{
    unsigned long index, cntl, vclk;

    /* Once per boot.  -enterLinearMode can be asked for a second time (the
     * window server may give up on the first and ask again, and the class
     * counts every call).  A second snapshot would read back the mode WE
     * programmed and the revert would then put THAT on the card at shutdown
     * instead of what the kernel console left -- the one thing the snapshot
     * exists to prevent.  So keep the first one and only re-check the live
     * gates, which our own programming satisfies. */
    if (mode->snapshotValid) {
        /* the two PLL reads move the index byte: put the word back, so a
           refusal leaves the card as it was (docs/R3_MULTIMODE_PLAN.md 23-12) */
        index = osrdn_mmio_get(base, SNAP_CLOCK_CNTL_INDEX);
        cntl = osrdn_pll_get(base, SNAP_PPLL_CNTL);
        vclk = osrdn_pll_get(base, SNAP_VCLK_ECP_CNTL);
        osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, index);
        if (cntl & (PPLL_RESET | PPLL_SLEEP)) {
            mode->why = MODE_WHY_PLL_STATE;
            return 0;
        }
        if ((vclk & VCLK_SRC_SEL_MASK) != VCLK_SRC_SEL_PPLLCLK) {
            mode->why = MODE_WHY_PLL_STATE;
            return 0;
        }
        return 1;
    }

    if (!osrdn_snap_take(base, &mode->snap)) {
        mode->why = MODE_WHY_SNAPSHOT;
        return 0;
    }
    mode->snapshotValid = 1;

    /* The console must have been in a GRAPHICS mode.  A text console keeps
     * glyphs in the character generator planes, and the snapshot holds no
     * planes -- so a revert built on it would bring the timing back and still
     * show nothing readable.  The reference driver refuses its RESTORE for
     * this reason (OpenStepMGAReplacementDisplay.m 7622-7629).  We refuse the
     * ENTRY instead: a mode we cannot leave is worse than no mode.  Attribute
     * mode control bit 0 is the graphics bit; this machine has measured 01 on
     * every boot so far (R2b-0, R2b and the two R2c boots). */
    if ((mode->snap.vgaAttr[0x10] & 0x01) == 0) {
        mode->why = MODE_WHY_TEXT_CONSOLE;
        return 0;
    }

    /* the PLL must be in the shape the revert assumes it can put back */
    if (mode->snap.pll[SNAP_PPLL_CNTL] & (PPLL_RESET | PPLL_SLEEP)) {
        mode->why = MODE_WHY_PLL_STATE;
        return 0;
    }
    if ((mode->snap.pll[SNAP_VCLK_ECP_CNTL] & VCLK_SRC_SEL_MASK) != VCLK_SRC_SEL_PPLLCLK) {
        mode->why = MODE_WHY_PLL_STATE;
        return 0;
    }

    /* the reference divider this boot has: never written by us (plan 2-8),
       so the divider row is chosen from it, per resolution, by modeRow */
    mode->refdiv = mode->snap.pll[SNAP_PPLL_REF_DIV] & PPLL_REF_DIV_MASK;
    return 1;
}

/*
 * Step 3, every entry, BEFORE the first write: the chosen resolution's
 * divider row for this boot's reference divider (docs/R3_MULTIMODE_PLAN.md
 * 12-3 D1, 23-4).  Two holes exist in the tables (640x480 has no row for
 * refdiv 8, 1024x768 none for 3), so a boot can have a divider that one
 * resolution cannot use; that is refused here, while nothing has been written.
 *
 * The live PPLL_REF_DIV must still be the snapshot's: the re-entry path does
 * not take a second snapshot, and pllProgram writes mode->refdiv back, so a
 * value that had changed would be moved silently (23-9 B1).
 */
static int
modeRow(osrdn_mode_state *mode, vm_address_t base)
{
    const osrdn_res_row *r;
    unsigned int         k, end;
    unsigned long        index, live;

    r = osrdn_res(mode->res);
    if (!mode->selected || r == 0 || osrdn_fmt(mode->fmt) == 0) {
        mode->why = MODE_WHY_NOT_SELECTED;
        return 0;
    }
    /* a PLL read writes the index byte: put the word back as it was, so a
       refusal here leaves the card exactly as the snapshot found it
       (docs/R3_MULTIMODE_PLAN.md 23-12 B1, the way modePllRead does) */
    index = osrdn_mmio_get(base, SNAP_CLOCK_CNTL_INDEX);
    live = osrdn_pll_get(base, SNAP_PPLL_REF_DIV) & PPLL_REF_DIV_MASK;
    osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, index);
    if (live != mode->refdiv) {
        mode->why = MODE_WHY_REFDIV;
        return 0;
    }
    mode->div3 = 0;
    end = r->pllFirst + r->pllCount;
    if (end > OSRDN_PLL_ALL_COUNT)
        end = OSRDN_PLL_ALL_COUNT;
    for (k = r->pllFirst; k < end; k++)
        if ((unsigned long)osrdnPllAll[k].refdiv == mode->refdiv) {
            mode->div3 = (unsigned long)osrdnPllAll[k].div3;
            break;
        }
    if (mode->div3 == 0) {
        mode->why = MODE_WHY_REFDIV;
        return 0;
    }
    return 1;
}

/* CRTC_GEN_CNTL as the mode wants it: extended display, the format's field */
static unsigned long
modeGenCntl(const osrdn_mode_state *mode)
{
    return CRTC_EXT_DISP_EN |
           ((unsigned long)osrdn_fmt(mode->fmt)->crtcFormat << CRTC_PIX_WIDTH_SHIFT);
}

/* the FIFO table's column for a pixel size: 4 bytes 0, 2 bytes 1, 1 byte 2 */
static const osrdn_fifo_row *
modeFifoRow(const osrdn_mode_state *mode)
{
    unsigned int bytes = osrdn_fmt(mode->fmt)->bytes;
    int          col = (bytes == 4) ? 0 : ((bytes == 2) ? 1 : 2);

    return &osrdnFifoAll[mode->res][col];
}

static void
modeBlank(osrdn_mode_state *mode, vm_address_t base)
{
    unsigned long v;

    mode->modeWritten = 1;              /* the first write is the next line */
    v = osrdn_mmio_get(base, SNAP_CRTC_GEN_CNTL);
    osrdn_mmio_put(base, SNAP_CRTC_GEN_CNTL, (v & ~CRTC_EN) | CRTC_DISP_REQ_EN_B);
    v = osrdn_mmio_get(base, SNAP_CRTC_EXT_CNTL);
    osrdn_mmio_put(base, SNAP_CRTC_EXT_CNTL, v | CRTC_DIS_ALL);
}

static void
modeCrtc(osrdn_mode_state *mode, vm_address_t base)
{
    const osrdn_res_row *r = osrdn_res(mode->res);
    unsigned long        v;

    osrdn_mmio_put(base, SNAP_CRTC_GEN_CNTL, modeGenCntl(mode) | CRTC_DISP_REQ_EN_B);
    osrdn_mmio_put(base, SNAP_CRTC_EXT_CNTL,
                   CRTC_DIS_ALL | XCRT_CNT_EN | VGA_ATI_LINEAR | CRTC_CRT_ON);
    osrdn_mmio_put(base, SNAP_CRTC_H_TOTAL_DISP, r->hTotalDisp);
    osrdn_mmio_put(base, SNAP_CRTC_H_SYNC, r->hSync);
    osrdn_mmio_put(base, SNAP_CRTC_V_TOTAL_DISP, r->vTotalDisp);
    osrdn_mmio_put(base, SNAP_CRTC_V_SYNC, r->vSync);
    osrdn_mmio_put(base, SNAP_CRTC_OFFSET_CNTL, 0);
    osrdn_mmio_put(base, SNAP_CRTC_OFFSET, 0);
    osrdn_mmio_put(base, SNAP_CRTC_PITCH, r->pitch);
    v = osrdn_mmio_get(base, SNAP_DISP_MERGE_CNTL);
    osrdn_mmio_put(base, SNAP_DISP_MERGE_CNTL, v & ~DISP_RGB_OFFSET_EN);
    osrdn_mmio_put(base, SNAP_CRTC_GEN_CNTL, modeGenCntl(mode));
}

static void
modeFifo(osrdn_mode_state *mode, vm_address_t base)
{
    const osrdn_fifo_row *f = modeFifoRow(mode);
    unsigned long         v;

    v = osrdn_mmio_get(base, SNAP_GRPH_BUFFER_CNTL);
    osrdn_mmio_put(base, SNAP_GRPH_BUFFER_CNTL, (v & f->preserve) | f->set);
}

static void
modeDac(osrdn_mode_state *mode, vm_address_t base)
{
    unsigned long v;

    (void)mode;
    v = osrdn_mmio_get(base, SNAP_DAC_CNTL);
    osrdn_mmio_put(base, SNAP_DAC_CNTL,
                   (v & (DAC_RANGE_CNTL | DAC_BLANKING)) | DAC_MASK_ALL | DAC_8BIT_EN);
}

/*
 * The palette.  The DAC pixel clock is gated off for the writes and put back
 * on EVERY exit path: leaving it gated is a black screen after an otherwise
 * good revert (docs/R2B_IMPL_PLAN.md 12-6).
 */
static void
modePalette(osrdn_mode_state *mode, vm_address_t base, const unsigned long *values)
{
    unsigned long saved;
    int           k;

    (void)mode;
    saved = osrdn_pll_get(base, SNAP_VCLK_ECP_CNTL);
    osrdn_pll_put(base, SNAP_VCLK_ECP_CNTL, saved & ~PIXCLK_DAC_ALWAYS_ONb);
    for (k = 0; k < OSRDN_SNAP_PALETTE; k++)
        osrdn_palette_put(base, k, 1, &values[k]);
    osrdn_pll_put(base, SNAP_VCLK_ECP_CNTL, saved);
}

static void
modeUnblank(osrdn_mode_state *mode, vm_address_t base)
{
    unsigned long v;

    (void)mode;
    v = osrdn_mmio_get(base, SNAP_CRTC_GEN_CNTL);
    osrdn_mmio_put(base, SNAP_CRTC_GEN_CNTL, (v & ~CRTC_DISP_REQ_EN_B) | CRTC_EN);
    v = osrdn_mmio_get(base, SNAP_CRTC_EXT_CNTL);
    osrdn_mmio_put(base, SNAP_CRTC_EXT_CNTL, v & ~CRTC_DIS_ALL);
}

/* Read the five PLL words without changing what the card is left selecting.
 *
 * osrdn_pll_get WRITES the index byte before every read, so a bare read loop
 * leaves the index at whatever it read last -- osrdn_snap_take knows this and
 * puts the index back (and verifies it) after its own loop.  modeVerify did
 * not, so every entry since R2b has ended with the index on HTOTAL_CNTL while
 * the line it logged showed the value from BEFORE the loop.  Harmless so far,
 * because the next PLL access sets the index again, but it made the log say
 * one thing and the card hold another -- and putting the same loop at the end
 * of the revert would have carried it onto the shutdown path, where nothing
 * comes after to set it right (codex cross-review 3, 2026-09-16).
 */
static void
modePllRead(vm_address_t base, unsigned long *out)
{
    unsigned long   index;
    int             k;

    index = osrdn_mmio_get(base, SNAP_CLOCK_CNTL_INDEX);
    for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
        out[k] = osrdn_pll_get(base, k);
    osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, index);
}

/* ---- the LUT (docs/R3_MULTIMODE_PLAN.md 24-3) ------------------------------
 *
 * File scope, not locals: 256 longs are a kilobyte and this runs on a kernel
 * stack.  Only the claim holder touches them.  modeLutTake copies the stored
 * inputs and clears the pending flag in ONE splhigh section, so a change that
 * arrives afterwards sets the flag again and is applied when the holder lets
 * go (24-4).
 */
#define LUT_CSPACE_ONE_IS_WHITE 1       /* IO_OneIsWhiteColorSpace (the generator checks it) */
#define LUT_CSPACE_RGB          2       /* IO_RGBColorSpace (OSRDNDisplay.m's enum check) */
#define LUT_BPP_15              3       /* IO_15BitsPerPixel (likewise) */
#define LUT_FULL                64UL    /* EV_SCREEN_MAX_BRIGHTNESS */

static unsigned long modeLut[OSRDN_SNAP_PALETTE];
static unsigned long modeLutBack[OSRDN_SNAP_PALETTE];
static unsigned char lutRgb[OSRDN_SNAP_PALETTE * 3];
static int           lutCount, lutDim, lutGray;

static void
modeLutTake(osrdn_mode_state *mode)
{
    int s, k;

    s = splhigh();
    for (k = 0; k < OSRDN_SNAP_PALETTE * 3; k++)
        lutRgb[k] = mode->xferRgb[k];
    lutCount = mode->xferCount;
    lutDim = mode->dim;
    lutGray = mode->grayLevels;
    mode->lutPending = 0;
    splx(s);
}

/* 1. BW with 16/4/2 grey levels: the quantized ramp, whatever the table says
 *    (OpenStepMGAReplacementDisplay.m:4784-4787, the override 7556-7562);
 * 2. a table, on RGB:256/8 and BW:8 ONLY: entry k over 256/count slots, the
 *    tail given the last entry.  A direct-colour format (888/32, 555/16)
 *    keeps the table stored and never puts it on the LUT: the window server's
 *    table is a gamma-2.2 lift, and through an 8-bit LUT it posterizes the
 *    picture ("looks like 16 bpp" -- docs/G2_LUT_PLAN.md 2-5, the identity
 *    table looked "like Matrox" on the machine).  The Matrox replacement
 *    driver draws the same line (OpenStepMGAReplacementDisplay.m:4751);
 * 3. no table, or a direct-colour format: the linear ramp -- for 555/16 the
 *    5-bit component finds LUT entries v*8..v*8+7 (radeon_driver.c:3326-3334),
 *    so the ramp is ((k >> 3) * 255) / 31, not k (k would top out at 248);
 * 4. every component scaled by the brightness, EV_SCALE_BRIGHTNESS (ev_types.h:170). */
static void
modeLutMake(const osrdn_mode_state *mode)
{
    const osrdn_fmt_row *f = osrdn_fmt(mode->fmt);
    unsigned long        k, n, lvl, rep, src, level, r, g, b;
    int                  direct;

    direct = (f != 0 && f->ioColorSpace == LUT_CSPACE_RGB && !f->pseudo);
    n = (unsigned long)lutGray;
    level = LUT_FULL - (unsigned long)lutDim;
    if (lutDim < 0 || lutDim > (int)LUT_FULL)
        level = LUT_FULL;
    for (k = 0; k < OSRDN_SNAP_PALETTE; k++) {
        if (f != 0 && f->ioColorSpace == LUT_CSPACE_ONE_IS_WHITE && (n == 16 || n == 4 || n == 2)) {
            lvl = (k * n) / 256UL;
            r = (lvl * 255UL) / (n - 1UL);
            g = r;
            b = r;
        } else if (lutCount > 0 && lutCount <= OSRDN_SNAP_PALETTE && !direct) {
            rep = 256UL / (unsigned long)lutCount;
            src = k / rep;
            if (src >= (unsigned long)lutCount)
                src = (unsigned long)lutCount - 1UL;
            r = lutRgb[src * 3];
            g = lutRgb[src * 3 + 1];
            b = lutRgb[src * 3 + 2];
        } else if (direct && f->ioBpp == LUT_BPP_15) {
            r = ((k >> 3) * 255UL) / 31UL;
            g = r;
            b = r;
        } else {
            r = k;
            g = k;
            b = k;
        }
        r = (r * level) >> 6;
        g = (g * level) >> 6;
        b = (b * level) >> 6;
        modeLut[k] = (r << 22) | (g << 12) | (b << 2);
    }
}

/* read the LUT back; the count of entries whose top 8 bits differ */
static int
modeLutCheck(vm_address_t base, int *index, unsigned long *got, unsigned long *want)
{
    int k, bad = 0;

    osrdn_palette_get(base, 0, OSRDN_SNAP_PALETTE, modeLutBack);
    *index = -1;
    *got = 0;
    *want = 0;
    for (k = 0; k < OSRDN_SNAP_PALETTE; k++) {
        if ((modeLutBack[k] & LUT_TOP_BITS) == (modeLut[k] & LUT_TOP_BITS))
            continue;
        if (bad == 0) {
            *index = k;
            *got = modeLutBack[k];
            *want = modeLut[k];
        }
        bad++;
    }
    return bad;
}

/* a stored change onto a live mode, under the claim.  The read-back is
   evidence only: a brightness call is no reason to take the mode away. */
static void
modeLutApply(osrdn_mode_state *mode, vm_address_t base)
{
    unsigned long index;

    modeLutTake(mode);
    if (!mode->modeWritten || mode->kernelRevertSeen)
        return;
    modeLutMake(mode);
    index = osrdn_mmio_get(base, SNAP_CLOCK_CNTL_INDEX);
    modePalette(mode, base, modeLut);
    mode->applyLutBad = modeLutCheck(base, &mode->applyLutIndex, &mode->applyLutGot,
                                     &mode->applyLutWant);
    osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, index);    /* 24-9 B8 */
    mode->lutApplied++;
}

static void
modeVerify(osrdn_mode_state *mode, vm_address_t base)
{
    const osrdn_res_row  *r = osrdn_res(mode->res);
    const osrdn_fifo_row *f = modeFifoRow(mode);
    int                   k;

    mode->verifyBad = 0;
    for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
        mode->verifyGot[k] = osrdn_mmio_get(base, k);
    modePllRead(base, mode->verifyPll);

    if (mode->verifyGot[SNAP_CRTC_H_TOTAL_DISP] != r->hTotalDisp)
        mode->verifyBad++;
    if (mode->verifyGot[SNAP_CRTC_H_SYNC] != r->hSync)
        mode->verifyBad++;
    if (mode->verifyGot[SNAP_CRTC_V_TOTAL_DISP] != r->vTotalDisp)
        mode->verifyBad++;
    if (mode->verifyGot[SNAP_CRTC_V_SYNC] != r->vSync)
        mode->verifyBad++;
    if (mode->verifyGot[SNAP_CRTC_PITCH] != r->pitch)
        mode->verifyBad++;
    if (!(mode->verifyGot[SNAP_CRTC_GEN_CNTL] & CRTC_EN))
        mode->verifyBad++;
    if (!(mode->verifyGot[SNAP_CRTC_GEN_CNTL] & CRTC_EXT_DISP_EN))
        mode->verifyBad++;
    /* R3b-2: the pixel format the card took (23-4, 23-9 E1) */
    mode->verifyFormat = (mode->verifyGot[SNAP_CRTC_GEN_CNTL] & CRTC_PIX_WIDTH_MASK) >> CRTC_PIX_WIDTH_SHIFT;
    if (mode->verifyFormat != (unsigned long)osrdn_fmt(mode->fmt)->crtcFormat)
        mode->verifyBad++;
    /* the FIFO fields this entry sets, and the DAC bits it sets (12-2 H2) */
    if ((mode->verifyGot[SNAP_GRPH_BUFFER_CNTL] & f->clear) != f->set)
        mode->verifyBad++;
    if ((mode->verifyGot[SNAP_DAC_CNTL] & (DAC_MASK_ALL | DAC_8BIT_EN)) != (DAC_MASK_ALL | DAC_8BIT_EN))
        mode->verifyBad++;
    if ((mode->verifyPll[SNAP_PPLL_DIV_3] & (PPLL_FB3_DIV_MASK | PPLL_POST3_DIV_MASK)) !=
        (mode->div3 & (PPLL_FB3_DIV_MASK | PPLL_POST3_DIV_MASK)))
        mode->verifyBad++;
    if ((mode->verifyPll[SNAP_PPLL_REF_DIV] & PPLL_REF_DIV_MASK) != mode->refdiv)
        mode->verifyBad++;
    /* the PLL gain must still be the one the firmware left (12-1) */
    if ((mode->verifyPll[SNAP_PPLL_CNTL] & 0x00003800UL) !=
        (mode->snap.pll[SNAP_PPLL_CNTL] & 0x00003800UL))
        mode->verifyBad++;
    /* the divider selector is ours now, and the write-enable bit is clear */
    if ((mode->verifyGot[SNAP_CLOCK_CNTL_INDEX] & PLL_DIV_SEL_MASK) != PLL_DIV_SEL_3)
        mode->verifyBad++;
    if (mode->verifyGot[SNAP_CLOCK_CNTL_INDEX] & 0x00000080UL)
        mode->verifyBad++;

    /* The LUT, all 256 entries, read the way the snapshot reads (the card
     * takes the read index from the low byte, 21-7), against the LUT this
     * entry built.  Only the top 8 bits of each component are compared: the
     * entry writes 8-bit values shifted into 10-bit fields.  A GATE since
     * R3b-2b: three live boots read back clean (23-14, 23-15, 23-16). */
    mode->verifyLutBad = modeLutCheck(base, &mode->verifyLutIndex, &mode->verifyLutGot,
                                      &mode->verifyLutWant);
    if (mode->verifyLutBad)
        mode->verifyBad++;
}

/*
 * Step 10, the test pattern, for the chosen resolution and format.  Written
 * into the framebuffer the class mapped, while the CRTC is still blanked.
 * Four bands top to bottom with a left-to-right ramp, and a mark in each
 * corner: a wrong pitch shears the bands, a wrong offset moves the marks, a
 * wrong byte order swaps the colours.
 *
 * Every write is a 32-bit word (the one framebuffer accessor this module has,
 * RDNR2aMMIO.m): a 16-bit pixel format packs two pixels into a word and an
 * 8-bit one four, the first pixel in the low half -- the aperture does no
 * byte swap (step 0's SURFACE_CNTL gate) and the CPU is little-endian.  Every
 * width is a multiple of 8, so a word never crosses the end of a row, and the
 * last write ends exactly at memorySize (python, docs/R3_MULTIMODE_PLAN.md 23-9).
 *
 * Pixels: 32 bpp 0x00RRGGBB; 16 bpp 555 (-RRRRRGGGGGBBBBB); 8 bpp the index,
 * which is a grey level under the linear LUT R3b-2a loads.
 */
static unsigned long
modePixel(unsigned int bytes, unsigned long x, unsigned long y,
          unsigned long width, unsigned long height)
{
    unsigned long ramp, band, r = 0, g = 0, b = 0;

    ramp = (x * 255UL) / (width - 1UL);             /* 0..255 for every width */
    band = y / (height / 4UL);
    if ((x < 16UL || x >= width - 16UL) && (y < 16UL || y >= height - 16UL)) {
        r = 255UL;                                  /* the corner marks: magenta */
        b = 255UL;
        if (bytes == 1)
            return 255UL;                           /* 8 bpp: the brightest index */
    } else if (bytes == 1) {
        return (band == 1UL) ? (255UL - ramp) : ramp;   /* the second band runs backwards */
    } else if (band == 0UL) {
        r = ramp;
    } else if (band == 1UL) {
        g = ramp;
    } else if (band == 2UL) {
        b = ramp;
    } else {
        r = ramp;
        g = ramp;
        b = ramp;
    }
    if (bytes == 2)
        return ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3);
    return (r << 16) | (g << 8) | b;
}

void
osrdn_mode_pattern(const osrdn_mode_state *mode, vm_address_t fb)
{
    const osrdn_res_row *res = osrdn_res(mode->res);
    const osrdn_fmt_row *fmt = osrdn_fmt(mode->fmt);
    unsigned long        x, y, width, height, rowBytes, word;
    unsigned int         bytes, per, i;

    if (res == 0 || fmt == 0)
        return;
    width = res->width;
    height = res->height;
    bytes = fmt->bytes;
    per = 4U / bytes;                               /* pixels in one 32-bit word */
    rowBytes = width * bytes;
    for (y = 0; y < height; y++) {
        for (x = 0; x < width; x += per) {
            word = 0;
            for (i = 0; i < per; i++)
                word |= modePixel(bytes, x + i, y, width, height) << (i * bytes * 8U);
            rdnMmioWrite32(fb, (unsigned int)(y * rowBytes + x * bytes), word);
        }
    }
}

/* ---- one sequence at a time ------------------------------------------------
 *
 * The kernel does not serialize -enterLinearMode, -revertToVGAMode and the
 * setIntValues path against each other (Q13 verdict).  Without a claim the
 * cycle has a window between its revert and its re-entry where a kernel
 * revert sees modeWritten == 0, does nothing, and the cycle then re-enters --
 * leaving the card in linear mode for a shutdown that already happened
 * (codex cross-review 5, 2026-09-16).
 *
 * Only the flag is touched at raised spl.  The waits are not: this driver
 * reads IOGetTimestamp, and _splusclock forces spl to 6, so a wait inside
 * splhigh would be reading a clock it has stopped.
 */
static void modeRevertBody(osrdn_mode_state *mode, vm_address_t base);

static int
modeClaim(osrdn_mode_state *mode)
{
    int s, got;

    s = splhigh();
    if (mode->inSequence) {
        got = 0;
    } else {
        mode->inSequence = 1;
        got = 1;
    }
    splx(s);
    return got;
}

/* Let go, putting the per-sequence settings back to what the next claimant
 * expects to find (each entry point also sets its own right after claiming,
 * 24-9 A3).  Written in the same splhigh section as the release: after it,
 * they would belong to whoever claims next. */
static void
modeRelease(osrdn_mode_state *mode)
{
    int s;

    s = splhigh();
    mode->noSleep = 0;
    mode->skipShow = 0;
    mode->wantRevertCheck = 0;
    mode->inSequence = 0;
    splx(s);
}

/* Let go of the card -- unless there is work the holder must do first:
 *   1  the kernel asked for VGA while we held it and our mode is on the card
 *      (H1, internal cross-review of docs/R3_MULTIMODE_PLAN.md 12-2);
 *   2  a transfer table or brightness was stored while we held it and the
 *      mode is live (24-4 -- otherwise that change would wait for the next
 *      call that happens to come);
 *   0  released, the settings put back in the same section.
 * The test and the release are one splhigh section, so nothing can slip in
 * between them. */
#define MODE_WORK_NONE          0
#define MODE_WORK_REVERT        1
#define MODE_WORK_LUT           2

static int
modeReleaseOrWork(osrdn_mode_state *mode)
{
    int s, work;

    s = splhigh();
    if (mode->kernelRevertSeen && mode->modeWritten) {
        work = MODE_WORK_REVERT;
    } else if (mode->lutPending && mode->modeWritten && !mode->kernelRevertSeen) {
        work = MODE_WORK_LUT;
    } else {
        work = MODE_WORK_NONE;
        mode->noSleep = 0;
        mode->skipShow = 0;
        mode->wantRevertCheck = 0;
        mode->inSequence = 0;
    }
    splx(s);
    return work;
}

/* finish a sequence: revert as many times as the kernel asked meanwhile, and
 * apply what was stored meanwhile.  Neither blocks, so a change can only
 * arrive while the holder sleeps -- the entry's waits -- and the loop ends
 * after at most a revert and an apply (24-9 B9). */
static void
modeFinish(osrdn_mode_state *mode, vm_address_t base)
{
    int work;

    while ((work = modeReleaseOrWork(mode)) != MODE_WORK_NONE) {
        if (work == MODE_WORK_REVERT) {
            mode->wantRevertCheck = 0;  /* keep the cycle's own read-back */
            modeRevertBody(mode, base); /* clears modeWritten */
        } else {
            modeLutApply(mode, base);
        }
    }
}

/* ---- entry ---------------------------------------------------------------- */

static int
modeEnterBody(osrdn_mode_state *mode, vm_address_t base, vm_address_t fb)
{
    mode->enterCount++;
    mode->why = MODE_WHY_NONE;
    mode->step = 0;

    if (!modeCheck(mode, base))
        return 0;
    mode->step = 1;
    if (!modeSnapshot(mode, base))
        return 0;
    mode->step = 3;
    if (!modeRow(mode, base))
        return 0;

    /* from here every failure reverts: -enterLinearMode cannot report one */
    mode->step = 4;
    modeBlank(mode, base);
    mode->step = 5;
    modeCrtc(mode, base);
    mode->step = 6;
    /* HTOTAL_CNTL is (HTotal & 7), from the resolution's row */
    pllProgram(mode, base, mode->div3, osrdn_res(mode->res)->htotalCntl, 0);
    mode->step = 7;
    modeFifo(mode, base);
    mode->step = 8;
    modeDac(mode, base);
    mode->step = 9;
    /* the stored table and brightness, the pending flag cleared in the same
       section as the copy; written unconditionally -- the entry holds the
       card (24-9, 21-2 B4) */
    modeLutTake(mode);
    modeLutMake(mode);
    modePalette(mode, base, modeLut);
    mode->step = 10;
    if (fb != 0 && !mode->skipShow)
        osrdn_mode_pattern(mode, fb);
    mode->step = 11;
    modeUnblank(mode, base);

    /* Read back BEFORE the operator's look, not after (12-8).  Two reasons:
     * the evidence is then already in the state struct if the caller gives up
     * on us during the wait, and a mode that did not take is not left on the
     * screen for two seconds -- it is reverted at once. */
    mode->step = 12;
    modeVerify(mode, base);
    if (mode->verifyBad) {
        mode->why = MODE_WHY_VERIFY;
        mode->latched = 1;
        modeRevertBody(mode, base);
        return 0;
    }

    mode->step = 13;
    if (!mode->skipShow)
        (void)modeWaitUs(mode, MODE_SHOW_US, &mode->wShow);
    mode->step = 14;
    return 1;
}

/* ---- the revert's own read-back (R2c) -------------------------------------
 *
 * Take a second snapshot the same way the first one was taken and compare it,
 * byte for byte, with what the revert was supposed to put back.  Whole-snapshot
 * on purpose: the 13 MMIO and 5 PLL words are the smaller half, and the VGA
 * core and the palette are where "we lost the console" actually happens
 * (codex cross-review 2, 2026-09-16).
 *
 * Its evidence may not go in verifyGot/verifyPll: a re-entry runs modeVerify,
 * which zeroes verifyBad and overwrites both arrays, so the log would describe
 * the re-entry and call it the revert (cross-review 1).
 *
 * osrdn_snap_take puts the PLL index back and verifies it, so this leaves the
 * card selecting what the revert left it selecting.  It does leave the palette
 * INDEX at the last entry read, exactly as the boot snapshot did.
 */
static osrdn_snap   modeCheckSnap;          /* file scope: 1 KB of palette is not stack */

/* Let CRTC_OFFSET's trigger bit clear, and RECORD what happens.
 *
 * This is the separating measurement, not a fix (docs/R2C_REVERT_PLAN.md 13-2).
 * The first cycle on the machine read both offset words back as "snapshot value
 * | bit 30" and a later read showed them clear -- but the re-entry writes zero
 * to both registers on its way through modeCrtc, so that later read cannot say
 * whether the revert's update ever completed or the re-entry simply replaced it.
 * Reading here, before the wait and before any re-entry, is what tells those
 * two apart.  The turn count is the evidence: 0 means it was never pending.
 */
static void
modeOffsetSettle(osrdn_mode_state *mode, vm_address_t base)
{
    ns_time_t       t0, t1;
    unsigned long   v, turns = 0;

    mode->revertOffsetFirst[0] = osrdn_mmio_get(base, SNAP_CRTC_OFFSET);
    mode->revertOffsetFirst[1] = osrdn_mmio_get(base, SNAP_CRTC_OFFSET_CNTL);
    mode->revertOffsetTurns = 0;
    mode->revertOffsetPending = 0;

    mode->wRevTrig.evals = 0;
    mode->wRevTrig.limit = 0;
    IOGetTimestamp(&t0);
    for (;;) {
        v = osrdn_mmio_get(base, SNAP_CRTC_OFFSET);
        mode->wRevTrig.evals++;
        if (!(v & CRTC_OFFSET_GUI_TRIG))
            break;
        turns++;
        if (turns >= MODE_POLL_LOOPS) {
            mode->revertOffsetPending = 1;
            break;
        }
        IOGetTimestamp(&t1);
        if (modeElapsedUs(t0, t1) >= MODE_OFFSET_US) {
            mode->revertOffsetPending = 1;
            break;
        }
        modeWaitTick(mode);
    }
    mode->revertOffsetTurns = turns;
    mode->wRevTrig.limit = mode->revertOffsetPending;
}

/* Count a VGA byte that did not come back, and name the first few.  A count
 * alone cannot be acted on. */
static void
modeVgaDiff(osrdn_mode_state *mode, int kind, int index,
            unsigned char want, unsigned char got)
{
    int n;

    if (want == got)
        return;
    n = mode->revertVgaBad;
    if (n < OSRDN_VGA_NAMED) {
        mode->revertVgaKind[n] = (unsigned char)kind;
        mode->revertVgaIndex[n] = (unsigned char)index;
        mode->revertVgaWant[n] = want;
        mode->revertVgaGot[n] = got;
    }
    mode->revertVgaBad++;
}

static void
modeRevertCheck(osrdn_mode_state *mode, vm_address_t base)
{
    int k, onlyOffset;

    mode->revertChecked = 0;
    mode->revertCheckWhy = 0;
    mode->revertBad = 0;
    mode->revertVgaBad = 0;
    mode->revertPaletteBad = 0;
    mode->revertVerdict = 0;

    modeOffsetSettle(mode, base);

    if (!osrdn_snap_take(base, &modeCheckSnap)) {
        mode->revertCheckWhy = modeCheckSnap.why;
        return;
    }
    mode->revertChecked = 1;

    for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++) {
        mode->revertGot[k] = modeCheckSnap.mmio[k];
        if (modeCheckSnap.mmio[k] != mode->snap.mmio[k])
            mode->revertBad++;
    }
    for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++) {
        mode->revertPll[k] = modeCheckSnap.pll[k];
        if (modeCheckSnap.pll[k] != mode->snap.pll[k])
            mode->revertBad++;
    }
    for (k = 0; k < OSRDN_SNAP_PALETTE; k++)
        if (modeCheckSnap.palette[k] != mode->snap.palette[k])
            mode->revertPaletteBad++;

    modeVgaDiff(mode, 1, 0, mode->snap.vgaMisc, modeCheckSnap.vgaMisc);
    for (k = 0; k < OSRDN_SNAP_SEQ; k++)
        modeVgaDiff(mode, 2, k, mode->snap.vgaSeq[k], modeCheckSnap.vgaSeq[k]);
    for (k = 0; k < OSRDN_SNAP_CRTC; k++)
        modeVgaDiff(mode, 3, k, mode->snap.vgaCrtc[k], modeCheckSnap.vgaCrtc[k]);
    for (k = 0; k < OSRDN_SNAP_GR; k++)
        modeVgaDiff(mode, 4, k, mode->snap.vgaGr[k], modeCheckSnap.vgaGr[k]);
    for (k = 0; k < OSRDN_SNAP_ATTR; k++)
        modeVgaDiff(mode, 5, k, mode->snap.vgaAttr[k], modeCheckSnap.vgaAttr[k]);

    /* The raw counts above stay raw -- nothing is masked out of them, so a real
     * value difference always shows.  The VERDICT is the separate thing: a
     * difference that is only the two offset words, each off by exactly the
     * trigger bit, is not "the revert failed", it is "the card had not caught
     * up yet".  It is not a pass either (cross-review 6, 13-2). */
    if (mode->revertBad != 0 || mode->revertVgaBad != 0 || mode->revertPaletteBad != 0) {
        onlyOffset = (mode->revertVgaBad == 0 && mode->revertPaletteBad == 0);
        for (k = 0; onlyOffset && k < OSRDN_SNAP_MMIO_COUNT; k++) {
            if (modeCheckSnap.mmio[k] == mode->snap.mmio[k])
                continue;
            if ((k == SNAP_CRTC_OFFSET || k == SNAP_CRTC_OFFSET_CNTL) &&
                (modeCheckSnap.mmio[k] ^ mode->snap.mmio[k]) == CRTC_OFFSET_GUI_TRIG)
                continue;
            onlyOffset = 0;
        }
        for (k = 0; onlyOffset && k < OSRDN_SNAP_PLL_COUNT; k++)
            if (modeCheckSnap.pll[k] != mode->snap.pll[k])
                onlyOffset = 0;
        mode->revertVerdict = onlyOffset ? 1 : 2;
    }
}

/* ---- revert --------------------------------------------------------------- */

static void
modeRevertBody(osrdn_mode_state *mode, vm_address_t base)
{
    unsigned long v;

    /* R5: whatever reverts the card, the CP stops first -- before the test
       below, so it runs whether or not a mode is on the card (docs/R5_PLAN.md
       7-2 B2); a latched CP only has CSQ written off */
    if (mode->cp != 0)
        osrdn_cp_quiesce(mode->cp, base);
    mode->revertCount++;
    if (!mode->snapshotValid || !mode->modeWritten)
        return;

    /* 4.1 blank */
    v = osrdn_mmio_get(base, SNAP_CRTC_GEN_CNTL);
    osrdn_mmio_put(base, SNAP_CRTC_GEN_CNTL, (v & ~CRTC_EN) | CRTC_DISP_REQ_EN_B);
    v = osrdn_mmio_get(base, SNAP_CRTC_EXT_CNTL);
    osrdn_mmio_put(base, SNAP_CRTC_EXT_CNTL, v | CRTC_DIS_ALL);

    /* 4.2 FIFO, 4.3 palette */
    osrdn_mmio_put(base, SNAP_GRPH_BUFFER_CNTL, mode->snap.mmio[SNAP_GRPH_BUFFER_CNTL]);
    modePalette(mode, base, mode->snap.palette);

    /* 4.4 CRTC, from the snapshot */
    osrdn_mmio_put(base, SNAP_CRTC_GEN_CNTL,
                   mode->snap.mmio[SNAP_CRTC_GEN_CNTL] | CRTC_DISP_REQ_EN_B);
    osrdn_mmio_put(base, SNAP_CRTC_EXT_CNTL,
                   mode->snap.mmio[SNAP_CRTC_EXT_CNTL] | CRTC_DIS_ALL);
    osrdn_mmio_put(base, SNAP_CRTC_H_TOTAL_DISP, mode->snap.mmio[SNAP_CRTC_H_TOTAL_DISP]);
    osrdn_mmio_put(base, SNAP_CRTC_H_SYNC, mode->snap.mmio[SNAP_CRTC_H_SYNC]);
    osrdn_mmio_put(base, SNAP_CRTC_V_TOTAL_DISP, mode->snap.mmio[SNAP_CRTC_V_TOTAL_DISP]);
    osrdn_mmio_put(base, SNAP_CRTC_V_SYNC, mode->snap.mmio[SNAP_CRTC_V_SYNC]);
    osrdn_mmio_put(base, SNAP_CRTC_OFFSET_CNTL, mode->snap.mmio[SNAP_CRTC_OFFSET_CNTL]);
    osrdn_mmio_put(base, SNAP_CRTC_OFFSET, mode->snap.mmio[SNAP_CRTC_OFFSET]);
    osrdn_mmio_put(base, SNAP_CRTC_PITCH, mode->snap.mmio[SNAP_CRTC_PITCH]);
    osrdn_mmio_put(base, SNAP_DISP_MERGE_CNTL, mode->snap.mmio[SNAP_DISP_MERGE_CNTL]);
    osrdn_mmio_put(base, SNAP_CRTC_GEN_CNTL, mode->snap.mmio[SNAP_CRTC_GEN_CNTL]);

    /* 4.5 the PLL, same code as the entry, snapshot values */
    pllProgram(mode, base, mode->snap.pll[SNAP_PPLL_DIV_3],
               mode->snap.pll[SNAP_HTOTAL_CNTL], 1);

    /* 4.6 the 32-bit index word, exactly as it was read: this is what puts the
       console's divider slot back.  It must come before 4.7 and 4.8. */
    osrdn_mmio_put(base, SNAP_CLOCK_CNTL_INDEX, mode->snap.mmio[SNAP_CLOCK_CNTL_INDEX]);

    /* 4.7 let the slot the console uses re-acquire */
    (void)modeWaitUs(mode, MODE_REVERT_SETTLE_US, &mode->wRevSlot);

    /* 4.8 CRTC back on */
    osrdn_mmio_put(base, SNAP_CRTC_GEN_CNTL, mode->snap.mmio[SNAP_CRTC_GEN_CNTL]);
    osrdn_mmio_put(base, SNAP_CRTC_EXT_CNTL, mode->snap.mmio[SNAP_CRTC_EXT_CNTL]);

    /* 4.9 standard VGA, 4.10 DAC last */
    osrdn_vga_put(&mode->snap);
    osrdn_mmio_put(base, SNAP_DAC_CNTL, mode->snap.mmio[SNAP_DAC_CNTL]);

    mode->modeWritten = 0;

    /* 4.11 only when asked (the cycle), never on the shutdown path */
    if (mode->wantRevertCheck)
        modeRevertCheck(mode, base);
}

/* ---- the public entry points ----------------------------------------------
 *
 * Each of the three claims the card, does its work and releases.  The bodies
 * never claim, so the cycle can hold the claim across a revert and a re-entry.
 */

int
osrdn_mode_enter(osrdn_mode_state *mode, vm_address_t base, vm_address_t fb)
{
    int live;

    if (!modeClaim(mode)) {
        mode->why = MODE_WHY_BUSY;
        return 0;
    }
    mode->kernelRevertSeen = 0;
    mode->noSleep = 0;                  /* the entry may wait with IOSleep */
    mode->skipShow = 0;
    mode->wantRevertCheck = 0;
    live = modeEnterBody(mode, base, fb);
    modeFinish(mode, base);
    if (mode->kernelRevertSeen && !mode->modeWritten)
        live = 0;
    return live;
}

void
osrdn_mode_revert(osrdn_mode_state *mode, vm_address_t base)
{
    int s, got;

    /* claim, or -- if a sequence holds the card -- tell it, in one section
       (21-2 B5): do not touch hardware underneath it; it leaves the card
       reverted rather than re-entering a mode for a shutdown that has begun */
    s = splhigh();
    if (mode->inSequence) {
        mode->kernelRevertSeen = 1;
        mode->revertCount++;
        got = 0;
    } else {
        mode->inSequence = 1;
        got = 1;
    }
    splx(s);
    if (!got)
        return;
    mode->noSleep = 0;                  /* the path the machine has proved */
    mode->skipShow = 0;
    mode->wantRevertCheck = 0;
    modeRevertBody(mode, base);
    modeRelease(mode);
}

/* One revert-and-come-back, on demand, once per boot.
 *
 * Why it exists: the revert otherwise runs only at shutdown, where IOLog never
 * reaches the disk, and the next boot cannot tell a good revert from a missing
 * one because the VGA BIOS reprograms the card anyway (docs/R2C_REVERT_PLAN.md
 * section 1).  This runs the same revert body with the read-back turned on.
 *
 * What it proves and what it does not: that the RESTORE LOGIC puts the whole
 * snapshot back.  Not that the shutdown context behaves the same -- its spl is
 * not ours to know, the superclass runs first there, and the window server is
 * gone (cross-review 4).
 *
 * It must not sleep: it is entered from setIntValues, whose lock and spl are
 * unmeasured, and doc/driverkit.md 293-309 measured IOSleep stopping this
 * machine in a context that held a stack lock.  IODelay is a spin -- roughly
 * 200 ms typical, 600 ms worst case for one cycle -- which is why this is once
 * per boot and only when the operator asks.
 */
int
osrdn_mode_cycle(osrdn_mode_state *mode, vm_address_t base, vm_address_t fb)
{
    int live = 0;

    mode->cycleWhy = MODE_WHY_NONE;
    if (base == 0) {
        mode->cycleWhy = MODE_WHY_NO_BASE;
        return 0;
    }
    if (mode->latched) {
        mode->cycleWhy = MODE_WHY_LATCHED;
        return 0;
    }
    if (!mode->snapshotValid || !mode->modeWritten) {
        mode->cycleWhy = MODE_WHY_NOT_LIVE;
        return 0;
    }
    if (mode->cycleCount != 0) {
        mode->cycleWhy = MODE_WHY_CYCLE_DONE;
        return 0;
    }
    if (!modeClaim(mode)) {
        mode->cycleWhy = MODE_WHY_BUSY;
        return 0;
    }
    /* R5: step 0 refuses re-entry while the CP or the GART is on, so a cycle
       now would leave the card in VGA -- refuse before reverting (7-2 B3) */
    if (mode->cp != 0 && !osrdn_cp_allows_mode(mode->cp)) {
        mode->cycleWhy = MODE_WHY_CP;
        modeFinish(mode, base);
        return 0;
    }

    mode->cycleCount++;
    mode->kernelRevertSeen = 0;
    mode->noSleep = 1;
    mode->skipShow = 1;
    mode->wantRevertCheck = 1;

    modeRevertBody(mode, base);

    if (mode->kernelRevertSeen) {
        /* the kernel asked for VGA while we held the card: leave it there */
        mode->cycleWhy = MODE_WHY_KERNEL_CAME;
    } else {
        live = modeEnterBody(mode, base, fb);
    }

    /* a revert that arrived DURING the re-entry is honoured here, with the
       claim still held (modeFinish) */
    modeFinish(mode, base);
    if (mode->kernelRevertSeen) {
        mode->cycleWhy = MODE_WHY_KERNEL_CAME;
        live = 0;
    }
    /* noSleep, skipShow and wantRevertCheck went back to 0 as the claim was
       released (modeReleaseOrWork), so the shutdown path keeps the behaviour
       the machine has already proved */
    return live;
}

int
osrdn_mode_engine(osrdn_mode_state *mode, vm_address_t base,
                  osrdn_engine_state *eng, int op, unsigned long arg,
                  osrdn_engine_state *copy)
{
    int rc;

    if (base == 0)
        return ENG_RC_NOT_LIVE;
    if (!modeClaim(mode))
        return ENG_RC_BUSY;
    mode->kernelRevertSeen = 0;
    mode->noSleep = 1;                  /* setIntValues must not sleep, and a revert
                                           owed at modeFinish waits (modeWaitUs) */
    mode->skipShow = 1;
    mode->wantRevertCheck = 0;
    /* checked under the claim: nothing can revert the card between the test
       and the engine's first write */
    if (!mode->snapshotValid || !mode->modeWritten)
        rc = ENG_RC_NOT_LIVE;
    else
        rc = (mode->cp != 0 && !osrdn_cp_allows_mode(mode->cp))
                 ? ENG_RC_CP                /* R5: the CP holds the card (7-2 B10) */
                 : osrdn_engine_run(eng, base, op, arg);
    *copy = *eng;                       /* while the claim is still ours */
    modeFinish(mode, base);
    return rc;
}

/* R5 (docs/R5_PLAN.md 8): the same claim protocol as the engine's.  STOP and
   RECORD need no live mode (a STOP must run however the card is); the rest
   do.  A revert the kernel asks for meanwhile is owed at modeFinish, and
   modeRevertBody stops the CP first. */
int
osrdn_mode_cp(osrdn_mode_state *mode, vm_address_t base, osrdn_cp_state *cp,
              int engineLatched, int op, unsigned long arg, unsigned long len,
              osrdn_cp_state *copy, int quiet)
{
    int rc;

    if (base == 0)
        return CP_RC_NOT_LIVE;
    if (!modeClaim(mode))
        return CP_RC_BUSY;
    mode->kernelRevertSeen = 0;
    mode->noSleep = 1;                  /* setIntValues must not sleep (R5, as the engine's) */
    mode->skipShow = 1;
    mode->wantRevertCheck = 0;
    if (op != CP_OP_STOP && op != CP_OP_RECORD && op != CP_OP_REC3D && (!mode->snapshotValid || !mode->modeWritten))
        rc = CP_RC_NOT_LIVE;
    else {
        /*
         * M2g: WHETHER THIS OPERATION IS A QUIET CLIENT SUBMISSION is decided by
         * the caller and lives only while the claim is held.  Setting it in the
         * caller, around this call, left two windows: a staging failure that
         * returns before the call left it set, and a second caller (setIntValues
         * races the character device, OSRDNDisplay.m:85-87) could take the
         * claim between our modeFinish and the caller's reset and see it.  An
         * R6 diagnostic that saw it would skip the digest its oracles judge
         * (docs/M2G_PLAN.md 10, R2-1 and R2-4).
         */
        cp->subQuiet = quiet;
        rc = osrdn_cp_run(cp, base, op, arg, len, engineLatched);
        cp->subQuiet = 0;
    }
    *copy = *cp;                        /* while the claim is still ours */
    modeFinish(mode, base);
    return rc;
}

int
osrdn_mode_present(osrdn_mode_state *mode, vm_address_t base, osrdn_cp_state *cp,
                   int engineLatched, const void *req)
{
    int rc;

    if (base == 0)
        return CP_RC_NOT_LIVE;
    if (!modeClaim(mode))
        return CP_RC_BUSY;              /* G3: a busy card is this row's E_BUSY, SDL retries next frame */
    mode->kernelRevertSeen = 0;
    mode->noSleep = 1;                  /* an ioctl on a kernel thread, as the submissions are */
    mode->skipShow = 1;
    mode->wantRevertCheck = 0;
    if (!mode->snapshotValid || !mode->modeWritten)
        rc = CP_RC_NOT_LIVE;
    else {
        osrdn_cp_present_req *pq = (osrdn_cp_present_req *)req;

        cp->presentReq = req;           /* set and cleared under the claim: no staging outside it */
        cp->subQuiet = 1;               /* G3: SDL sends a frame a row at a time -- no per-call lines */
        rc = osrdn_cp_run(cp, base, CP_OP_PRESENT, 0UL, 0UL, engineLatched);
        cp->subQuiet = 0;               /* G3: put back before the claim goes */
        cp->presentReq = 0;
        /* this operation's verdict, before the claim goes.  A refusal by the unit's
           common gates (key, block, a latched CP: cpPresent never ran) carries no
           present verdict, so name it here rather than hand back a stale one */
        if (rc == CP_RC_REFUSED && cp->why != CP_WHY_PRESENT)
            pq->verdict = cp->latched ? OSRDN_PRESENT_E_LATCH : OSRDN_PRESENT_E_MODE;
        else
            pq->verdict = cp->presentVerdict;
    }
    modeFinish(mode, base);
    return rc;
}

int
osrdn_mode_clear(osrdn_mode_state *mode, vm_address_t base, osrdn_cp_state *cp,
                 int engineLatched, const void *req)
{
    int rc;

    if (base == 0)
        return CP_RC_NOT_LIVE;
    if (!modeClaim(mode))
        return CP_RC_BUSY;              /* G3b: a busy card is this clear's E_BUSY; the caller falls back */
    mode->kernelRevertSeen = 0;
    mode->noSleep = 1;                  /* an ioctl on a kernel thread, as the submissions are */
    mode->skipShow = 1;
    mode->wantRevertCheck = 0;
    if (!mode->snapshotValid || !mode->modeWritten)
        rc = CP_RC_NOT_LIVE;
    else {
        osrdn_cp_clear_req *cq = (osrdn_cp_clear_req *)req;

        cp->clearReq = req;             /* set and cleared under the claim: no staging outside it */
        cp->subQuiet = 1;               /* G3b: one clear a frame -- no per-call lines */
        rc = osrdn_cp_run(cp, base, CP_OP_CLEAR, 0UL, 0UL, engineLatched);
        cp->subQuiet = 0;               /* G3b: put back before the claim goes */
        cp->clearReq = 0;
        if (rc == CP_RC_REFUSED && cp->why != CP_WHY_PRESENT)
            cq->verdict = cp->latched ? OSRDN_PRESENT_E_LATCH : OSRDN_PRESENT_E_MODE;
        else
            cq->verdict = cp->clearVerdict;
    }
    modeFinish(mode, base);
    return rc;
}

void
osrdn_mode_cp_stop(osrdn_mode_state *mode, vm_address_t base)
{
    if (base == 0 || mode->cp == 0)
        return;
    if (!modeClaim(mode))
        return;                         /* the holder's modeFinish stops it */
    mode->kernelRevertSeen = 0;
    mode->noSleep = 1;                  /* the CP stop never sleeps (R5) */
    mode->skipShow = 1;
    mode->wantRevertCheck = 0;
    osrdn_cp_quiesce(mode->cp, base);
    modeFinish(mode, base);
}

/* ---- the transfer table and the brightness (R3b-2b) -----------------------
 *
 * Both come from kernel threads: the table through the superclass's
 * setIntValues (it checks the count per depth, 24-9 A2), the brightness from
 * the event driver with its lock held (24-9 A1).  So: store, then try to
 * claim; short work, no sleeping.
 */
static int
modeLutKick(osrdn_mode_state *mode, vm_address_t base)
{
    unsigned long before;

    if (base == 0 || !mode->selected) {
        mode->lutStored++;
        return MODE_LUT_STORED;
    }
    if (!modeClaim(mode)) {
        mode->lutDeferred++;            /* the holder applies it as it lets go */
        return MODE_LUT_DEFERRED;
    }
    mode->noSleep = 1;                  /* a revert owed here must not sleep */
    mode->skipShow = 1;
    mode->wantRevertCheck = 0;
    before = mode->lutApplied;
    modeFinish(mode, base);
    if (mode->lutApplied != before)
        return MODE_LUT_APPLIED;
    mode->lutStored++;
    return MODE_LUT_STORED;
}

int
osrdn_mode_set_transfer(osrdn_mode_state *mode, vm_address_t base,
                        const unsigned int *table, int count)
{
    const osrdn_fmt_row *f;
    unsigned long        v;
    int                  s, k, n, mono;

    f = osrdn_fmt(mode->fmt);
    if (table == 0 || count <= 0 || !mode->selected || f == 0)
        return MODE_LUT_IGNORED;
    n = (count > OSRDN_SNAP_PALETTE) ? OSRDN_SNAP_PALETTE : count;
    mono = (f->ioColorSpace == LUT_CSPACE_ONE_IS_WHITE);
    s = splhigh();
    for (k = 0; k < n; k++) {
        v = (unsigned long)table[k];
        if (mono) {
            mode->xferRgb[k * 3] = (unsigned char)(v & 0xffUL);
            mode->xferRgb[k * 3 + 1] = (unsigned char)(v & 0xffUL);
            mode->xferRgb[k * 3 + 2] = (unsigned char)(v & 0xffUL);
        } else {
            mode->xferRgb[k * 3] = (unsigned char)((v >> 24) & 0xffUL);
            mode->xferRgb[k * 3 + 1] = (unsigned char)((v >> 16) & 0xffUL);
            mode->xferRgb[k * 3 + 2] = (unsigned char)((v >> 8) & 0xffUL);
        }
    }
    mode->xferCount = n;
    mode->lutPending = 1;
    mode->xferCalls++;
    splx(s);
    return modeLutKick(mode, base);
}

int
osrdn_mode_set_brightness(osrdn_mode_state *mode, vm_address_t base, int level)
{
    int s;

    if (level < 0 || level > (int)LUT_FULL)
        return MODE_LUT_IGNORED;
    s = splhigh();
    mode->dim = (int)LUT_FULL - level;  /* a zero-filled state is full brightness */
    mode->lutPending = 1;
    mode->brightCalls++;
    splx(s);
    return modeLutKick(mode, base);
}
