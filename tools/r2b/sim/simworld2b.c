/*
 * simworld2b.c - drive the real osrdn_snap.m and osrdn_mode.m against a fake card.
 *
 * docs/R2B_IMPL_PLAN.md 12-5 and 12-12.  What this proves, before any
 * hardware is touched:
 *
 *   1. osrdn_snap_take reads exactly the offsets in the tables (plus the two
 *      index registers) and leaves the PLL index as it found it;
 *   2. every register in the tables can be written back through the module's
 *      own accessors -- the coverage half of "the entry's write set is a
 *      subset of the revert's restore list";
 *   3. take -> perturb everything -> write the snapshot back gives a register
 *      file byte-identical to the start, for both measured boot states.
 *
 * It does NOT prove the ordering of the revert: that lives in osrdn_mode.m.
 */

#include <stdio.h>
#include <driverkit/generalFuncs.h>
#include "osrdn_snap.h"
#include "osrdn_port.h"
#include "osrdn_mode.h"
#include "simx_expect.h"          /* written by sim_r2b.py from the oracle, not the driver's header */


/* the 32-bit host libc has no headers here; these are the only two needed */
static void
simCopy(void *dst, const void *src, unsigned long n)
{
    unsigned char *a = (unsigned char *)dst;
    const unsigned char *b = (const unsigned char *)src;
    unsigned long k;
    for (k = 0; k < n; k++)
        a[k] = b[k];
}

static void
simZero(void *dst, unsigned long n)
{
    unsigned char *a = (unsigned char *)dst;
    unsigned long k;
    for (k = 0; k < n; k++)
        a[k] = 0;
}

#define MMIO_WORDS      0x2000

static unsigned long    mmio[MMIO_WORDS / 4];
/* a VGA core, not a byte array: index registers select what the data port
   reaches, and the attribute controller has a flip-flop.  Only a model like
   this can show that the restore put the CORE back, not just the ports. */
static unsigned char    vMisc;
static unsigned char    vSeq[8], vCrtc[32], vGr[16], vAttr[32];
static int              vSeqIdx, vCrtcIdx, vGrIdx, vAttrIdx, vAttrFlip, vAttrPas;
static unsigned long    palette[OSRDN_SNAP_PALETTE];
static int              pllIndex;                       /* what the index byte selects */
static int              pllWrEn;                        /* the write-enable bit in that byte */
static unsigned long    pll[0x40];
static int              readTrace[512], readCount;
static int              writeTrace[512], writeCount;
static int              vgaWrites;
static int              simLogCalls;
static unsigned long    sleepCallsNoSleep;
static unsigned long    delayCalls, delayUs;
/* the framebuffer: counted, not stored (1.9 MB would be pointless here) */
static unsigned long    fbWrites, fbLow, fbHigh, fbSum, fbMisaligned;
static int              simStickyAtomic;   /* 1: the atomic-update bit never clears */
static unsigned long    simDelayPermille = 1000;   /* how long a delay really takes, per
                                              thousand of what was asked: this machine's
                                              IODelay(2000) measured 1872-1881 us */
static int              simFrozenClock;    /* 1: the timestamp source stops advancing -- the
                                              thing the turn bounds exist for, since nothing
                                              promises the clock runs in every context this
                                              code is called from */

/* CRTC_OFFSET's trigger bit, the thing the first cycle on the machine saw set.
 * The card sets it when the offset is written and clears it when the offset is
 * picked up; this fake lets a world say how many reads that takes, and lets a
 * world keep the SAME bit position stuck in CRTC_OFFSET_CNTL, which no
 * reference header defines (docs/R2C_REVERT_PLAN.md 13-1). */
#define SIM_TRIG        0x40000000UL
static int              simTrigReads;      /* reads until CRTC_OFFSET's bit clears */
static int              simTrigLeft;
static int              simTrigForever;    /* 1: CRTC_OFFSET's bit never clears at all */
static int              simTrigCntlStuck;  /* 1: CRTC_OFFSET_CNTL keeps the bit for ever */
static int              simTrigCntlSet;
static int              simStuckCrtc = -1;  /* a CRTC index whose restore the card swallows */
static int              simVgaUndecoded;   /* 1: the legacy VGA ports are not decoded (bridge
                                              forwarding off): every read is 0xff and writes
                                              go nowhere */
static int              simStuckPitch;     /* 1: CRTC_PITCH ignores writes -- a register the
                                              card does not take, which is what a real revert
                                              failure looks like from the read-back */
static unsigned long    simPalDataWrites;
/* R3b-2: parts of the card that do not take a write, so each extended
   read-back check has a world that needs it (docs/R3_MULTIMODE_PLAN.md 23-6) */
static int              simStuckFormat;    /* CRTC_GEN_CNTL keeps the 32 bpp format */
static int              simStuckFifo;      /* GRPH_BUFFER_CNTL ignores writes */
static int              simStuckDac;       /* DAC_CNTL ignores writes */
static int              simStuckLut;       /* palette entry 15 ignores writes (G2: the 555 ramp is 0 over 0..7) */
static int              simStuckLutRed;    /* palette entry 15 keeps its red component */
/* R3b-2b: a transfer table (and maybe a kernel revert) arriving while an
   entry holds the card: 1 at the palette write of entry 100 (inside step 9),
   2 at the first framebuffer write (the pattern, after step 9) */
static int              simXferHook;
static int              simXferHookRevert;
static int              simXferHookResult = -1;
static osrdn_mode_state *simXferMode;  /* PALETTE_30_DATA writes, all of them */
static osrdn_mode_state *simHookMode;      /* the kernel's revert arrives on this state ... */
static int              simHookPhase;      /* 0 idle, 1 wait for the revert to finish (modeWritten 0),
                                              2 wait for the re-entry to start (modeWritten 1) */

/* ---- the fakes the driver links against ---------------------------------- */

unsigned long
rdnMmioRead32(vm_address_t base, unsigned int offset)
{
    (void)base;
    if (readCount < 512)
        readTrace[readCount++] = (int)offset;
    if (offset == 0x000c)                               /* CLOCK_CNTL_DATA */
        return pll[pllIndex & 0x3f];
    if (offset == 0x00b8)                               /* PALETTE_30_DATA */
        return palette[mmio[0x00b0 / 4] & 0xff];   /* the READ index is the low byte
                                                        too: measured on the machine,
                                                        docs/R3_MULTIMODE_PLAN.md 21-7 */
    if (offset == 0x0224 && (simTrigForever || simTrigLeft > 0)) {  /* update in flight */
        if (!simTrigForever)
            simTrigLeft--;
        return mmio[offset / 4] | SIM_TRIG;
    }
    if (offset == 0x0228 && simTrigCntlSet)             /* CRTC_OFFSET_CNTL, the bit no
                                                           reference header defines */
        return mmio[offset / 4] | SIM_TRIG;
    return mmio[offset / 4];
}

#define SIM_MMIO_BASE   0x1000
#define SIM_FB_BASE     0x900000

void
rdnMmioWrite32(vm_address_t base, unsigned int offset, unsigned long value)
{
    if (base == SIM_MMIO_BASE && simHookMode != 0) {
        if (simHookPhase == 1 && !simHookMode->modeWritten)
            simHookPhase = 2;                   /* the cycle's revert half is done */
        else if (simHookPhase == 2 && simHookMode->modeWritten) {
            osrdn_mode_state *m = simHookMode;  /* the re-entry has begun: now */
            simHookMode = 0;
            simHookPhase = 0;
            osrdn_mode_revert(m, SIM_MMIO_BASE); /* the claim is held: only flags */
        }
    }
    if (base == SIM_MMIO_BASE && offset == 0x022c && simStuckPitch)
        return;                                 /* the write is dropped */
    if (base == SIM_MMIO_BASE && offset == 0x0050 && simStuckFormat)
        value = (value & ~0x00000f00UL) | 0x00000600UL;
    if (base == SIM_MMIO_BASE && ((offset == 0x02f0 && simStuckFifo) || (offset == 0x0058 && simStuckDac)))
        return;
    /* GRPH_BUFFER_CNTL: the card keeps only multiples of 4 in GRPH_START_REQ
       and GRPH_STOP_REQ (measured, docs/R3_MULTIMODE_PLAN.md 24-14).  A
       hardware property, not a fault to inject: the critical-point field is
       left alone because we always write 0 there and its rule is unknown. */
    if (base == SIM_MMIO_BASE && offset == 0x02f0)
        value &= ~0x00000303UL;
    if (base == SIM_MMIO_BASE && offset == 0x0224) {
        simTrigLeft = simTrigReads;             /* writing the offset starts the update */
        if (simTrigCntlStuck)
            simTrigCntlSet = 1;
    }
    if (simXferHook && simXferMode != 0 &&
        ((simXferHook == 1 && base == SIM_MMIO_BASE && offset == 0x00b8 && (mmio[0x00b0 / 4] & 0xff) == 100) ||
         (simXferHook == 2 && base == SIM_FB_BASE))) {
        osrdn_mode_state *m = simXferMode;
        simXferHook = 0;
        simXferMode = 0;
        simXferHookResult = osrdn_mode_set_transfer(m, SIM_MMIO_BASE, simxT1, 256);
        if (simXferHookRevert)
            osrdn_mode_revert(m, SIM_MMIO_BASE);
    }
    if (base == SIM_FB_BASE) {                  /* the test pattern */
        fbWrites++;
        if (fbWrites == 1 || offset < fbLow) fbLow = offset;
        if (offset > fbHigh) fbHigh = offset;
        if (offset & 3UL) fbMisaligned++;
        fbSum += value;
        return;
    }
    if (writeCount < 512)
        writeTrace[writeCount++] = (int)offset;
    if (offset == 0x000c) {
        /* the hardware takes a PLL data write only with the write-enable bit
           set in the index byte, as RADEONOUTPLL writes it */
        if (pllWrEn) {
            /* PPLL_REF_DIV bit 15 is the atomic-update trigger: the hardware
               performs the update and clears it.  simStickyAtomic models a
               part that does not, so the bounded waits are exercised too. */
            if ((pllIndex & 0x3f) == 0x03 && (value & 0x8000UL) && !simStickyAtomic)
                value &= ~0x8000UL;
            pll[pllIndex & 0x3f] = value;
        }
        return;
    }
    if (offset == 0x00b8) {
        simPalDataWrites++;
        if (simStuckLut && (mmio[0x00b0 / 4] & 0xff) == 15)
            return;
        if (simStuckLutRed && (mmio[0x00b0 / 4] & 0xff) == 15)
            value = (value & ~0x3ff00000UL) | (palette[15] & 0x3ff00000UL);
        palette[mmio[0x00b0 / 4] & 0xff] = value;
        return;
    }
    mmio[offset / 4] = value;
}

void
rdnMmioWrite8(vm_address_t base, unsigned int offset, unsigned char value)
{
    (void)base;
    if (writeCount < 512)
        writeTrace[writeCount++] = (int)offset;
    mmio[offset / 4] = (mmio[offset / 4] & ~0xffUL) | value;
    if (offset == 0x0008) {
        pllIndex = value & 0x3f;
        pllWrEn = (value & 0x80) ? 1 : 0;
    }
}

unsigned char
osrdn_inb(IOEISAPortAddress p)
{
    if (simVgaUndecoded)
        return 0xff;                            /* a bus nobody answers on */
    switch (p) {
    case 0x3cc: return vMisc;
    case 0x3c4: return (unsigned char)vSeqIdx;
    case 0x3c5: return vSeq[vSeqIdx & 7];
    case 0x3d4: case 0x3b4: return (unsigned char)vCrtcIdx;
    case 0x3d5: case 0x3b5: return vCrtc[vCrtcIdx & 31];
    case 0x3ce: return (unsigned char)vGrIdx;
    case 0x3cf: return vGr[vGrIdx & 15];
    case 0x3c0: return (unsigned char)(vAttrIdx | (vAttrPas ? 0x20 : 0));
    case 0x3c1:
        /* and with pas = 1 a palette read is invalid; the specification's
           implementation returns all ones (same 12087) */
        if (vAttrPas && (vAttrIdx & 31) <= 0x0f)
            return 0xff;
        return vAttr[vAttrIdx & 31];
    case 0x3da: case 0x3ba: vAttrFlip = 0; return 0;
    default: return 0;
    }
}

void
osrdn_outb(IOEISAPortAddress p, unsigned char v)
{
    vgaWrites++;
    if (simVgaUndecoded)
        return;
    switch (p) {
    case 0x3c2: vMisc = v; break;
    case 0x3c4: vSeqIdx = v & 7; break;
    case 0x3c5: vSeq[vSeqIdx & 7] = v; break;
    case 0x3d4: case 0x3b4: vCrtcIdx = v & 31; break;
    case 0x3d5: case 0x3b5:
        /* CR11 bit 7 protects CR0-CR7, as the hardware does */
        if ((vCrtcIdx & 31) <= 7 && (vCrtc[0x11] & 0x80))
            break;
        if (simStuckCrtc >= 0 && (int)(vCrtcIdx & 31) == simStuckCrtc)
            break;                              /* the card does not take it */
        vCrtc[vCrtcIdx & 31] = v;
        break;
    case 0x3ce: vGrIdx = v & 15; break;
    case 0x3cf: vGr[vGrIdx & 15] = v; break;
    case 0x3c0:
        if (!vAttrFlip) {
            vAttrIdx = v & 0x1f;
            vAttrPas = (v & 0x20) ? 1 : 0;
            vAttrFlip = 1;
        } else {
            /* Palette address source, ref/G400SPEC_Jun1999.txt 12087 (the bit
               is marked "VGA.", i.e. the standard one): with pas = 1 the
               palette is in use by the video stream and CPU writes to entries
               0x00-0x0F are INHIBITED.  0x10-0x14 are not palette entries and
               are not gated -- this machine read them with pas set (R2b-0
               record, attri=20 attr=0100030000). */
            if (!(vAttrPas && (vAttrIdx & 31) <= 0x0f))
                vAttr[vAttrIdx & 31] = v;
            vAttrFlip = 0;
        }
        break;
    default: break;
    }
}

unsigned long osrdn_inl(IOEISAPortAddress p) { (void)p; return 0; }
void osrdn_outl(IOEISAPortAddress p, unsigned long v) { (void)p; (void)v; }

/* ---- time: a clock that only moves when the driver sleeps or polls ------- */
static unsigned long long simClock;             /* nanoseconds */
static unsigned long      sleepCalls, sleepMs;

void
IOGetTimestamp(ns_time_t *nsp)
{
    if (!simFrozenClock)
        simClock += 1000ULL;                    /* every read costs a microsecond */
    *nsp = simClock;
}

void
IOSleep(unsigned ms)
{
    sleepCalls++;
    sleepMs += ms;
    if (!simFrozenClock)                        /* a stopped timestamp source does not start
                                                   moving because someone waited on it */
        simClock += (unsigned long long)ms * 1000000ULL;
}

void
IODelay(unsigned us)
{
    delayCalls++;
    delayUs += us;
    if (!simFrozenClock)
        simClock += (unsigned long long)us * simDelayPermille;   /* us * 1000 ns, scaled */
}

/* the sequence claim raises spl around the flag only; the fake counts the
   nesting so a wait taken inside splhigh would be visible */
static int simSpl, simSplMax;
int splhigh(void) { simSpl++; if (simSpl > simSplMax) simSplMax = simSpl; return 0; }
int splx(int ipl) { (void)ipl; simSpl--; return 0; }
void IOLog(const char *f, ...) { (void)f; simLogCalls++; }



/* ---- the two measured boot states ---------------------------------------- */

typedef struct {
    const char     *name;
    unsigned long   clockIndex;         /* CLOCK_CNTL_INDEX */
    unsigned long   pllCntl, refDiv, div3, vclk, htotal;
    unsigned long   crtcGen, crtcExt;
} boot_state;

static const boot_state boots[] = {
    /* R2a boot: docs/R2A_RESULT.md -- PLL_DIV_SEL 3, refdiv 6, PPLL_DIV_3 00030047 */
    { "R2a", 0x00000303UL, 0x0000a700UL, 0x00000006UL, 0x00030047UL, 0x000000c3UL, 0x00000000UL,
      0x02000200UL, 0x36088040UL },
    /* R2b-0 activation boot: docs/R2B0_RESULT.md -- PLL_DIV_SEL 1, refdiv 12 */
    { "R2b-0", 0x00000103UL, 0x0000a700UL, 0x0000000cUL, 0x00030065UL, 0x000000c3UL, 0x00000000UL,
      0x02000200UL, 0x18008000UL }
};

static const unsigned long simPeekBoot[OSRDN_PEEK_COUNT] = {
    0x04000000UL,   /* CRTC2_GEN_CNTL     */
    0x00000000UL,   /* FP_GEN_CNTL        */
    0x02010080UL,   /* CP_CSQ_CNTL        */
    0x00000140UL,   /* RBBM_STATUS        */
    0x00000000UL,   /* AIC_CNTL           */
    0x00000000UL,   /* GEN_INT_CNTL       */
    0x807f0000UL,   /* OV0_SCALE_CNTL     */
    0x00000000UL,   /* I2C_CNTL_1         */
    0x00000000UL,   /* VIPH_CONTROL       */
    0x10000000UL,   /* DISP_OUTPUT_CNTL   */
    0x00000000UL,   /* DAC_CNTL2          */
    0x00000100UL,   /* SURFACE_CNTL       */
    0x70000000UL,   /* HOST_PATH_CNTL     */
    0xe0000000UL,   /* CONFIG_APER_0_BASE */
    0x08000000UL,   /* CONFIG_APER_SIZE   */
    0x08000000UL,   /* CONFIG_MEMSIZE     */
    0x00000000UL,   /* DISPLAY_BASE_ADDR  */
    0x1fff0000UL    /* MC_FB_LOCATION     */
};

#define SIM_BAR0            0xe0000000UL
#ifndef SIM_MAPPED_LENGTH                   /* sim_r2b.py passes OSRDN_FB_LENGTH, read from
                                               osrdn_record.h, so this cannot drift from it */
#error "SIM_MAPPED_LENGTH must come from osrdn_record.h (tools/r2b/sim_r2b.py)"
#endif

/* a fresh mode state with the two inputs the class sets from init */
static void
modeInit(osrdn_mode_state *m)
{
    simZero(m, sizeof *m);
    m->bar0 = SIM_BAR0;
    m->mappedLength = SIM_MAPPED_LENGTH;
    m->res = SIMX_RES_DEFAULT;                  /* what the class selects with no key */
    m->fmt = 0;
    m->selected = 1;
}

static void
seed(const boot_state *b)
{
    int k;

    simZero(mmio, sizeof mmio);
    simZero(pll, sizeof pll);
    readCount = writeCount = vgaWrites = 0;
    vSeqIdx = vCrtcIdx = vGrIdx = vAttrIdx = vAttrFlip = 0;
    vAttrPas = 1;

    for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
        /* distinct per register AND a multiple of 4: GRPH_BUFFER_CNTL's two
           request fields keep only multiples of 4 (24-14), so a seed with the
           low bits set could not round-trip on the card either */
        mmio[osrdnSnapMmio[k].offset / 4] = 0x11110000UL + ((unsigned long)k << 2);
    /* the read-only step-0 registers, as BOTH measured boots had them
       (R2a 789467668 and R2b-0 789526262 logged the same values) */
    for (k = 0; k < OSRDN_PEEK_COUNT; k++)
        mmio[osrdnPeek[k].offset / 4] = simPeekBoot[k];
    mmio[0x0008 / 4] = b->clockIndex;
    mmio[0x0050 / 4] = b->crtcGen;
    mmio[0x0054 / 4] = b->crtcExt;
    pllIndex = (int)(b->clockIndex & 0x3f);

    pll[0x02] = b->pllCntl;
    pll[0x03] = b->refDiv;
    pll[0x07] = b->div3;
    pll[0x08] = b->vclk;
    pll[0x09] = b->htotal;

    for (k = 0; k < OSRDN_SNAP_PALETTE; k++)
        palette[k] = ((unsigned long)k << 22) | ((unsigned long)k << 12) | ((unsigned long)k << 2);

    vMisc = 0x67;                                       /* bit 0 set -> CRTC at 0x3d4 */
    for (k = 0; k < 8; k++)  vSeq[k]  = (unsigned char)(0x10 + k);
    vSeq[0] = 0x13;                                     /* reset released, plus a spare bit:
                                                           a restore that writes a bare 0x03
                                                           loses the spare bit and fails */
    for (k = 0; k < 32; k++) vCrtc[k] = (unsigned char)(0x20 + k);
    for (k = 0; k < 16; k++) vGr[k]   = (unsigned char)(0x30 + k);
    for (k = 0; k < 32; k++) vAttr[k] = (unsigned char)(0x40 + k);
    vAttr[0x10] = 0x01;                                 /* attribute mode control: GRAPHICS.
                                                           The machine measured 01 on every boot
                                                           (R2b-0, R2b, the two R2c boots); the
                                                           entry refuses a text console because
                                                           the snapshot holds no glyph planes */
    vCrtc[0x11] = 0x8e;                                 /* CR0-7 write-protected, as a
                                                           BIOS-initialised console has it */
}

typedef struct {
    unsigned char misc, seq[8], crtc[32], gr[16], attr[32];
} vga_core;

static void
vgaSave(vga_core *v)
{
    v->misc = vMisc;
    simCopy(v->seq, vSeq, sizeof vSeq);
    simCopy(v->crtc, vCrtc, sizeof vCrtc);
    simCopy(v->gr, vGr, sizeof vGr);
    simCopy(v->attr, vAttr, sizeof vAttr);
}

/* write the snapshot back through the module's own accessors */
static void
putBack(const osrdn_snap *s)
{
    int k;

    for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
        osrdn_pll_put(0x1000, k, s->pll[k]);
    for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
        if (k != SNAP_CLOCK_CNTL_INDEX)
            osrdn_mmio_put(0x1000, k, s->mmio[k]);
    osrdn_palette_put(0x1000, 0, OSRDN_SNAP_PALETTE, s->palette);
    osrdn_vga_put(s);
    /* the 32-bit index word goes back last, as the revert does */
    osrdn_mmio_put(0x1000, SNAP_CLOCK_CNTL_INDEX, s->mmio[SNAP_CLOCK_CNTL_INDEX]);
}

void exit(int code);   /* libc exit: flushes stdio, unlike _exit */

/* ---- R4: a stand-in for the engine unit ------------------------------------
 * osrdn_mode.m's osrdn_mode_engine is tested here alone; the engine itself is
 * simulated in tools/r4.  The stand-in plays what can happen while it holds
 * the claim: the kernel reverting, a transfer table arriving
 * (docs/R4_ENGINE_PLAN.md 13 #8, 9-2 #10). */
static osrdn_mode_state *simEngMode;
static int               simEngRevert, simEngXfer, simEngCalls;

int
osrdn_engine_run(osrdn_engine_state *e, vm_address_t base, int op, unsigned long arg)
{
    (void)e;
    (void)op;
    (void)arg;
    simEngCalls++;
    if (simEngRevert && simEngMode != 0)
        osrdn_mode_revert(simEngMode, base);            /* the claim is held: only flags */
    if (simEngXfer && simEngMode != 0)
        (void)osrdn_mode_set_transfer(simEngMode, base, simxT2, 256);   /* deferred */
    return ENG_RC_RAN;
}

/* ---- R5: a stand-in for the CP unit ----------------------------------------
 * osrdn_mode.m's side of the CP (docs/R5_PLAN.md 7-2 B2 B3 B10) is tested here;
 * the CP itself is simulated in tools/r5.  simCpAllows plays "the CP holds the
 * card"; the stand-in can play the kernel reverting while it holds the claim. */
static osrdn_mode_state *simCpMode;
static int               simCpAllows = 1, simCpQuiesce, simCpRuns, simCpRevert;

int
osrdn_cp_allows_mode(const osrdn_cp_state *c)
{
    (void)c;
    return simCpAllows;
}

void
osrdn_cp_quiesce(osrdn_cp_state *c, vm_address_t base)
{
    (void)c;
    (void)base;
    simCpQuiesce++;
}

int
osrdn_cp_run(osrdn_cp_state *c, vm_address_t base, int op, unsigned long arg, unsigned long len,
             int engineLatched)
{
    (void)c;
    (void)op;
    (void)arg;
    (void)len;
    (void)engineLatched;
    simCpRuns++;
    if (simCpRevert && simCpMode != 0)
        osrdn_mode_revert(simCpMode, base);             /* the claim is held: only flags */
    return CP_RC_RAN;
}

__attribute__((force_align_arg_pointer))
void
_start(void)
{
    static unsigned long    before[MMIO_WORDS / 4], beforePll[0x40], beforePalette[OSRDN_SNAP_PALETTE];
    static vga_core         beforeVga, afterVga;
    osrdn_snap              snap;
    int                     b, k, bad = 0;

    for (b = 0; b < (int)(sizeof boots / sizeof boots[0]); b++) {
        seed(&boots[b]);
        simCopy(beforePll, pll, sizeof pll);
        simCopy(beforePalette, palette, sizeof palette);
        simCopy(before, mmio, sizeof mmio);
        vgaSave(&beforeVga);

        {
            int pasBefore = vAttrPas, idxBefore = vAttrIdx;

            if (!osrdn_snap_take(0x1000, &snap)) {
                printf("  FAIL %s: snapshot refused, why=%d\n", boots[b].name, snap.why);
                bad++;
                continue;
            }
            /* Reading ATTR 0x00-0x0F needs the palette address source clear,
               and while it is clear the display shows the overscan colour.
               The snapshot must put the index byte back as it found it, or it
               leaves the console blank (G400 spec 12087). */
            if (vAttrPas != pasBefore || vAttrIdx != idxBefore) {
                printf("  FAIL %s: the snapshot left the attribute index %02x/pas=%d, "
                       "found %02x/pas=%d\n", boots[b].name, vAttrIdx, vAttrPas,
                       idxBefore, pasBefore);
                bad++;
            }
            if (snap.vgaAttrPas != (unsigned char)(idxBefore | (pasBefore ? 0x20 : 0))) {
                printf("  FAIL %s: the snapshot recorded pas byte %02x, was %02x\n",
                       boots[b].name, snap.vgaAttrPas,
                       (unsigned char)(idxBefore | (pasBefore ? 0x20 : 0)));
                bad++;
            }
        }
        /* 1. the PLL index came back */
        if ((mmio[0x0008 / 4] & 0xff) != (before[0x0008 / 4] & 0xff)) {
            printf("  FAIL %s: PLL index left at %02lx, was %02lx\n", boots[b].name,
                   mmio[0x0008 / 4] & 0xff, before[0x0008 / 4] & 0xff);
            bad++;
        }
        /* 2. the snapshot holds what the file holds */
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (snap.mmio[k] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL %s: mmio[%s] %08lx, file %08lx\n", boots[b].name,
                       osrdnSnapMmio[k].name, snap.mmio[k], before[osrdnSnapMmio[k].offset / 4]);
                bad++;
            }
        for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
            if (snap.pll[k] != beforePll[osrdnSnapPll[k].offset]) {
                printf("  FAIL %s: pll[%s] %08lx, file %08lx\n", boots[b].name,
                       osrdnSnapPll[k].name, snap.pll[k], beforePll[osrdnSnapPll[k].offset]);
                bad++;
            }
        if (snap.crtcPort != 0x3d4) {
            printf("  FAIL %s: CRTC port %03x from MISC %02x\n", boots[b].name,
                   snap.crtcPort, snap.vgaMisc);
            bad++;
        }

        /* 3. perturb everything the entry would, then put the snapshot back */
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            mmio[osrdnSnapMmio[k].offset / 4] = 0xdeadbe00UL + ((unsigned long)k << 2);
        for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
            pll[osrdnSnapPll[k].offset] = 0xfeed0000UL + (unsigned long)k;
        for (k = 0; k < OSRDN_SNAP_PALETTE; k++)
            palette[k] = 0x3ffffffUL;
        vMisc = 0xa5;
        for (k = 0; k < 8; k++)  vSeq[k]  = 0xa5;
        for (k = 0; k < 32; k++) vCrtc[k] = 0xa5;
        for (k = 0; k < 16; k++) vGr[k]   = 0xa5;
        for (k = 0; k < 32; k++) vAttr[k] = 0xa5;
        putBack(&snap);

        /* 4. identity, byte for byte, over the snapshot's own set */
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL %s: %s restored %08lx, was %08lx\n", boots[b].name,
                       osrdnSnapMmio[k].name, mmio[osrdnSnapMmio[k].offset / 4],
                       before[osrdnSnapMmio[k].offset / 4]);
                bad++;
            }
        for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
            if (pll[osrdnSnapPll[k].offset] != beforePll[osrdnSnapPll[k].offset]) {
                printf("  FAIL %s: %s restored %08lx, was %08lx\n", boots[b].name,
                       osrdnSnapPll[k].name, pll[osrdnSnapPll[k].offset],
                       beforePll[osrdnSnapPll[k].offset]);
                bad++;
            }
        for (k = 0; k < OSRDN_SNAP_PALETTE; k++)
            if (palette[k] != beforePalette[k]) {
                printf("  FAIL %s: palette[%d] restored %08lx, was %08lx\n", boots[b].name,
                       k, palette[k], beforePalette[k]);
                bad++;
                break;
            }
        if (pllWrEn) {
            printf("  FAIL %s: PLL write-enable left set after the restore\n", boots[b].name);
            bad++;
        }
        /* the VGA core the snapshot covers: MISC, SEQ 0-4, CRTC 0-0x18, GR 0-8, ATTR 0-0x14 */
        vgaSave(&afterVga);
        if (afterVga.misc != beforeVga.misc) {
            printf("  FAIL %s: MISC restored %02x, was %02x\n", boots[b].name,
                   afterVga.misc, beforeVga.misc);
            bad++;
        }
        for (k = 0; k < OSRDN_SNAP_SEQ; k++)
            if (afterVga.seq[k] != beforeVga.seq[k]) {
                printf("  FAIL %s: SEQ[%d] %02x, was %02x\n", boots[b].name,
                       k, afterVga.seq[k], beforeVga.seq[k]); bad++; break;
            }
        for (k = 0; k < OSRDN_SNAP_CRTC; k++)
            if (afterVga.crtc[k] != beforeVga.crtc[k]) {
                printf("  FAIL %s: CRTC[%d] %02x, was %02x\n", boots[b].name,
                       k, afterVga.crtc[k], beforeVga.crtc[k]); bad++; break;
            }
        for (k = 0; k < OSRDN_SNAP_GR; k++)
            if (afterVga.gr[k] != beforeVga.gr[k]) {
                printf("  FAIL %s: GR[%d] %02x, was %02x\n", boots[b].name,
                       k, afterVga.gr[k], beforeVga.gr[k]); bad++; break;
            }
        for (k = 0; k < OSRDN_SNAP_ATTR; k++)
            if (afterVga.attr[k] != beforeVga.attr[k]) {
                printf("  FAIL %s: ATTR[%d] %02x, was %02x\n", boots[b].name,
                       k, afterVga.attr[k], beforeVga.attr[k]); bad++; break;
            }
        printf("  %-4s %s: snapshot and restore are the identity (%d mmio, %d pll, %d palette, "
               "%d VGA port writes)\n", bad ? "FAIL" : "ok", boots[b].name,
               OSRDN_SNAP_MMIO_COUNT, OSRDN_SNAP_PLL_COUNT, OSRDN_SNAP_PALETTE, vgaWrites);
    }

    /* ---- the entry and the revert, on both measured boots ---------------- */
    for (b = 0; b < (int)(sizeof boots / sizeof boots[0]); b++) {
        static osrdn_mode_state mode;
        int                     entered;

        seed(&boots[b]);
        simCopy(beforePll, pll, sizeof pll);
        simCopy(beforePalette, palette, sizeof palette);
        simCopy(before, mmio, sizeof mmio);
        vgaSave(&beforeVga);
        modeInit(&mode);
        writeCount = 0;
        fbWrites = fbSum = fbHigh = 0;
        simLogCalls = 0;

        entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (!entered) {
            printf("  FAIL %s: entry refused, why=%d step=%d verifyBad=%d\n",
                   boots[b].name, mode.why, mode.step, mode.verifyBad);
            bad++;
            continue;
        }
        /* What the entry LOGS for a register must be what the card holds when
         * the log is written.  modeVerify reads the five PLL words, and every
         * PLL read writes the index byte first, so a read loop that does not
         * put the index back leaves the card on HTOTAL_CNTL while the line it
         * printed shows the value from before the loop (cross-review 3). */
        if (mmio[0x0008 / 4] != mode.verifyGot[SNAP_CLOCK_CNTL_INDEX]) {
            printf("  FAIL %s: after entry CLOCK_CNTL_INDEX is %08lx, the log says %08lx\n",
                   boots[b].name, mmio[0x0008 / 4], mode.verifyGot[SNAP_CLOCK_CNTL_INDEX]);
            bad++;
        }
        /* the oracle row this boot selected */
        if (mode.refdiv != (boots[b].refDiv & 0x3ff)) {
            printf("  FAIL %s: refdiv %lu, boot has %lu\n", boots[b].name,
                   mode.refdiv, boots[b].refDiv & 0x3ff); bad++;
        }
        /* the PLL gain was not touched (12-1) */
        if ((pll[0x02] & 0x3800UL) != (beforePll[0x02] & 0x3800UL)) {
            printf("  FAIL %s: PVG changed %08lx -> %08lx\n", boots[b].name,
                   beforePll[0x02] & 0x3800UL, pll[0x02] & 0x3800UL); bad++;
        }
        /* the reference divider value was not changed (2-8) */
        if ((pll[0x03] & 0x3ffUL) != (beforePll[0x03] & 0x3ffUL)) {
            printf("  FAIL %s: PPLL_REF_DIV %08lx -> %08lx\n", boots[b].name,
                   beforePll[0x03] & 0x3ffUL, pll[0x03] & 0x3ffUL); bad++;
        }
        /* the console's own divider slot was never written */
        if (pll[0x04] != 0 || pll[0x05] != 0 || pll[0x06] != 0) {
            printf("  FAIL %s: a PPLL_DIV_0/1/2 slot was written\n", boots[b].name); bad++;
        }
        /* the mode is what the oracle says */
        if (mmio[0x0200 / 4] != simxRes[SIMX_RES_DEFAULT].hTot ||
            mmio[0x022c / 4] != simxRes[SIMX_RES_DEFAULT].pitch) {
            printf("  FAIL %s: CRTC words not the oracle's\n", boots[b].name); bad++;
        }
        /* the test pattern covered the framebuffer exactly once */
        if (fbWrites != simxRes[SIMX_RES_DEFAULT].w * simxRes[SIMX_RES_DEFAULT].h ||
            fbHigh != simxRes[SIMX_RES_DEFAULT].w * 4UL * simxRes[SIMX_RES_DEFAULT].h - 4UL) {
            printf("  FAIL %s: pattern wrote %lu stores, highest offset %lu\n",
                   boots[b].name, fbWrites, fbHigh); bad++;
        }
        /* nothing logged between the snapshot and here (12-9) */
        if (simLogCalls != 0) {
            printf("  FAIL %s: %d log calls inside the sequence\n", boots[b].name, simLogCalls);
            bad++;
        }

        osrdn_mode_revert(&mode, SIM_MMIO_BASE);

        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL %s: after revert %s %08lx, was %08lx\n", boots[b].name,
                       osrdnSnapMmio[k].name, mmio[osrdnSnapMmio[k].offset / 4],
                       before[osrdnSnapMmio[k].offset / 4]);
                bad++;
            }
        for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
            if (pll[osrdnSnapPll[k].offset] != beforePll[osrdnSnapPll[k].offset]) {
                printf("  FAIL %s: after revert %s %08lx, was %08lx\n", boots[b].name,
                       osrdnSnapPll[k].name, pll[osrdnSnapPll[k].offset],
                       beforePll[osrdnSnapPll[k].offset]);
                bad++;
            }
        for (k = 0; k < OSRDN_SNAP_PALETTE; k++)
            if (palette[k] != beforePalette[k]) {
                printf("  FAIL %s: after revert palette[%d] %08lx, was %08lx\n",
                       boots[b].name, k, palette[k], beforePalette[k]); bad++; break;
            }
        vgaSave(&afterVga);
        for (k = 0; k < OSRDN_SNAP_CRTC; k++)
            if (afterVga.crtc[k] != beforeVga.crtc[k]) {
                printf("  FAIL %s: after revert CRTC[%d] %02x, was %02x\n",
                       boots[b].name, k, afterVga.crtc[k], beforeVga.crtc[k]); bad++; break;
            }
        if (mode.modeWritten) {
            printf("  FAIL %s: modeWritten still set after the revert\n", boots[b].name);
            bad++;
        }
        printf("  %-4s %s: enter and revert return the boot state (refdiv %lu, div3 %08lx, "
               "%lu pattern stores)\n", bad ? "FAIL" : "ok", boots[b].name,
               mode.refdiv, mode.div3, fbWrites);
    }

    /* ---- the part that does not clear the atomic-update bit -------------- */
    {
        static osrdn_mode_state mode;
        int                     entered;

        simStickyAtomic = 1;
        seed(&boots[0]);
        simCopy(before, mmio, sizeof mmio);
        simCopy(beforePll, pll, sizeof pll);
        simCopy(beforePalette, palette, sizeof palette);
        vgaSave(&beforeVga);
        modeInit(&mode);

        entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        /* the waits must END (bounded), and the revert must still run and
           return the boot state -- stopping half way is what loses a console */
        if (!mode.atomicWriteLimit && !mode.atomicReadLimit) {
            printf("  FAIL sticky: neither bounded wait reported its limit\n");
            bad++;
        }
        osrdn_mode_revert(&mode, SIM_MMIO_BASE);
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL sticky: after revert %s %08lx, was %08lx\n",
                       osrdnSnapMmio[k].name, mmio[osrdnSnapMmio[k].offset / 4],
                       before[osrdnSnapMmio[k].offset / 4]);
                bad++;
                break;
            }
        printf("  %-4s sticky atomic bit: the waits end (entered=%d, limits %d/%d) and the "
               "revert still returns the boot state\n", bad ? "FAIL" : "ok", entered,
               mode.atomicWriteLimit, mode.atomicReadLimit);
        simStickyAtomic = 0;
    }

    /* ---- a TEXT console must be refused, with no write --------------------- */
    {
        static osrdn_mode_state mode;
        int                     entered;

        seed(&boots[1]);
        vAttr[0x10] = 0x00;                     /* the graphics bit clear */
        simCopy(before, mmio, sizeof mmio);
        simCopy(beforePll, pll, sizeof pll);
        modeInit(&mode);
        entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (entered || mode.why != MODE_WHY_TEXT_CONSOLE) {
            printf("  FAIL text console: entered=%d why=%d step=%d\n",
                   entered, mode.why, mode.step);
            bad++;
        }
        if (mode.modeWritten) {
            printf("  FAIL text console: it wrote the mode anyway\n");
            bad++;
        }
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL text console: %s was written\n", osrdnSnapMmio[k].name);
                bad++;
                break;
            }
        printf("  %-4s a text console is refused before any mode write\n", bad ? "FAIL" : "ok");
    }

    /* ---- every step-0 condition refuses on its own, with no write ------- */
    {
        static osrdn_mode_state mode;
        /* gate, register offset (0 = CLOCK_CNTL_INDEX's divider field), the
           value that must be refused */
        static const struct { int gate; unsigned int off; unsigned long bad; const char *name; } g[] = {
            { GATE_CRTC2,       0x03f8, 0x06000000UL, "crtc2"       },
            { GATE_FPON,        0x0284, 0x00000001UL, "fpon"        },
            { GATE_CPMODE,      0x0740, 0x12010080UL, "cpmode"      },
            { GATE_RBBM,        0x0e40, 0x80000140UL, "rbbm"        },
            { GATE_GART,        0x01d0, 0x00000001UL, "gart"        },
            { GATE_INTCNTL,     0x0040, 0x00000004UL, "intcntl"     },
            { GATE_SCALER,      0x0420, 0xc07f0000UL, "scaler"      },
            { GATE_I2C,         0x0094, 0x00020000UL, "i2c"         },
            { GATE_VIPH,        0x0c40, 0x00200000UL, "viph"        },
            { GATE_DACSRC,      0x0d64, 0x10000001UL, "dacsrc"      },
            { GATE_DAC2,        0x007c, 0x00000001UL, "dac2"        },
            { GATE_SURFACE,     0x0b00, 0x00200100UL, "surface swap"},
            { GATE_SURFACE,     0x0b00, 0x00000000UL, "surface translation"},
            { GATE_HOSTPATH,    0x0130, 0x74000000UL, "hostpath"    },
            { GATE_APER0,       0x0100, 0xd0000000UL, "aper0"       },
            { GATE_APERSIZE,    0x0108, 0x00200000UL, "apersize"    },
            { GATE_MEMSIZE,     0x00f8, 0x00200000UL, "memsize"     },
            /* just below the mapped length: these tell 8 MiB from the old 3 MiB
               (docs/R3_MULTIMODE_PLAN.md 22-2) */
            { GATE_APERSIZE,    0x0108, 0x007fffffUL, "apersize 8 MiB - 1" },
            { GATE_MEMSIZE,     0x00f8, 0x00700000UL, "memsize 7 MiB" },
            { GATE_DISPLAYBASE, 0x023c, 0x00010000UL, "displaybase" },
            { GATE_DIVSEL,      0x0008, 0x00000003UL, "divsel 0"    },
            { GATE_DIVSEL,      0x0008, 0x00000203UL, "divsel 2"    }
        };
        int j, entered, gatesSeen = 0;

        for (j = 0; j < (int)(sizeof g / sizeof g[0]); j++) {
            seed(&boots[1]);
            mmio[g[j].off / 4] = g[j].bad;
            if (g[j].off == 0x0008)
                pllIndex = (int)(g[j].bad & 0x3f);
            simCopy(before, mmio, sizeof mmio);
            simCopy(beforePll, pll, sizeof pll);
            modeInit(&mode);
            writeCount = 0;
            entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
            if (entered || mode.why != MODE_WHY_CLIENT || mode.clientWhich != g[j].gate) {
                printf("  FAIL gate %s: entered=%d why=%d which=%d want %d\n", g[j].name,
                       entered, mode.why, mode.clientWhich, g[j].gate);
                bad++;
                continue;
            }
            if (mode.modeWritten || mode.snapshotValid) {
                printf("  FAIL gate %s: refused but written=%d snapshot=%d\n", g[j].name,
                       mode.modeWritten, mode.snapshotValid);
                bad++;
            }
            for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
                if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                    printf("  FAIL gate %s: %s was written\n", g[j].name, osrdnSnapMmio[k].name);
                    bad++;
                    break;
                }
            gatesSeen++;
        }
        /* and on RE-entry: our own mode does not change these, so they still refuse */
        seed(&boots[1]);
        modeInit(&mode);
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        mmio[0x01d0 / 4] = 0x00000001UL;        /* GART translation turned on under us */
        entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (entered || mode.clientWhich != GATE_GART) {
            printf("  FAIL gate on re-entry: entered=%d which=%d\n", entered, mode.clientWhich);
            bad++;
        }
        /* the boundary: an aperture and a memory of exactly the mapped length pass */
        seed(&boots[1]);
        mmio[0x0108 / 4] = SIM_MAPPED_LENGTH;
        mmio[0x00f8 / 4] = SIM_MAPPED_LENGTH;
        modeInit(&mode);
        entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (!entered || mode.mappedLength != 0x800000UL) {
            printf("  FAIL gate boundary: entered=%d why=%d which=%d mapped=%08lx\n",
                   entered, mode.why, mode.clientWhich, mode.mappedLength);
            bad++;
        }
        printf("  %-4s step 0: %d refusal worlds, each named and each without a write; re-entry "
               "still checks; exactly the mapped length passes\n", bad ? "FAIL" : "ok", gatesSeen);
    }

    /* ---- legacy VGA ports not decoded: refuse, do not trust 0xff --------- */
    {
        static osrdn_mode_state mode;
        int entered;

        seed(&boots[1]);
        simCopy(before, mmio, sizeof mmio);
        modeInit(&mode);
        simVgaUndecoded = 1;
        entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        simVgaUndecoded = 0;
        /* 0xff would pass the text-console gate (bit 0 set), so the snapshot
           itself must refuse */
        if (entered || mode.why != MODE_WHY_SNAPSHOT || mode.snap.why != SNAP_WHY_VGA_DECODE) {
            printf("  FAIL vga decode: entered=%d why=%d snap.why=%d\n",
                   entered, mode.why, mode.snap.why);
            bad++;
        }
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL vga decode: %s was written\n", osrdnSnapMmio[k].name);
                bad++;
                break;
            }
        printf("  %-4s undecoded VGA ports: the snapshot refuses instead of trusting 0xff\n",
               bad ? "FAIL" : "ok");
    }

    /* ---- a short IODelay must not end a wait on its turn cap ------------- */
    {
        static osrdn_mode_state mode;
        static const unsigned long ratio[] = { 936, 900, 750, 600, 1000, 2050 };
        int j;

        for (j = 0; j < (int)(sizeof ratio / sizeof ratio[0]); j++) {
            seed(&boots[1]);
            modeInit(&mode);
            (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
            simDelayPermille = ratio[j];
            (void)osrdn_mode_cycle(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
            simDelayPermille = 1000;
            if (mode.wRevSettle.limit || mode.wRevSlot.limit || mode.wSettle.limit) {
                printf("  FAIL short delay %lu/1000: rps=%lu/%d rss=%lu/%d ps=%lu/%d\n", ratio[j],
                       mode.wRevSettle.evals, mode.wRevSettle.limit,
                       mode.wRevSlot.evals, mode.wRevSlot.limit,
                       mode.wSettle.evals, mode.wSettle.limit);
                bad++;
            }
        }
        printf("  %-4s IODelay at 0.60-2.05 of nominal: every settle wait ends on the clock\n",
               bad ? "FAIL" : "ok");
    }

    /* ---- every bounded wait shows that it ran, and none hit its limit ---- */
    {
        static osrdn_mode_state mode;

        seed(&boots[1]);
        modeInit(&mode);
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (mode.wAtomicW.evals == 0 || mode.wAtomicR.evals == 0 || mode.wSettle.evals == 0 ||
            mode.wShow.evals == 0 || mode.atomicReadSkipped) {
            printf("  FAIL waits: entry evals aw=%lu ar=%lu ps=%lu sh=%lu skipped=%d\n",
                   mode.wAtomicW.evals, mode.wAtomicR.evals, mode.wSettle.evals,
                   mode.wShow.evals, mode.atomicReadSkipped);
            bad++;
        }
        if (mode.wAtomicW.limit || mode.wAtomicR.limit || mode.wSettle.limit || mode.wShow.limit) {
            printf("  FAIL waits: an entry wait hit its limit\n");
            bad++;
        }
        (void)osrdn_mode_cycle(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (mode.wRevAtomicW.evals == 0 || mode.wRevAtomicR.evals == 0 ||
            mode.wRevSettle.evals == 0 || mode.wRevSlot.evals == 0 || mode.revAtomicReadSkipped) {
            printf("  FAIL waits: revert evals raw=%lu rar=%lu rps=%lu rss=%lu skipped=%d\n",
                   mode.wRevAtomicW.evals, mode.wRevAtomicR.evals, mode.wRevSettle.evals,
                   mode.wRevSlot.evals, mode.revAtomicReadSkipped);
            bad++;
        }
        if (mode.wRevAtomicW.limit || mode.wRevAtomicR.limit || mode.wRevSettle.limit ||
            mode.wRevSlot.limit) {
            printf("  FAIL waits: a revert wait hit its limit\n");
            bad++;
        }
        printf("  %-4s every wait ran (entry %lu/%lu/%lu/%lu, revert %lu/%lu/%lu/%lu) and none "
               "hit a limit\n", bad ? "FAIL" : "ok",
               mode.wAtomicW.evals, mode.wAtomicR.evals, mode.wSettle.evals, mode.wShow.evals,
               mode.wRevAtomicW.evals, mode.wRevAtomicR.evals, mode.wRevSettle.evals,
               mode.wRevSlot.evals);
    }

    /* ---- R3b-2: every resolution x format, on both measured boots -------- *
     * docs/R3_MULTIMODE_PLAN.md 23-6.  The expectations are the oracle's
     * (simx_expect.h), never the driver's own tables. */
    {
        static osrdn_mode_state mode;
        int                     b, r, f, entered, combos = 0, rbad = 0;
        unsigned long           rd, want, per, bytes, memSize;

        for (b = 0; b < 2; b++)
        for (r = 0; r < SIMX_RES; r++)
        for (f = 0; f < SIMX_FMT; f++) {
            rd = boots[b].refDiv & 0x3ffUL;
            want = simxDiv3[r][rd];
            bytes = simxFmt[f].bytes;
            per = 4UL / bytes;
            memSize = simxRes[r].w * bytes * simxRes[r].h;
            seed(&boots[b]);
            simCopy(before, mmio, sizeof mmio);
            modeInit(&mode);
            mode.res = r;
            mode.fmt = f;
            fbWrites = fbSum = fbHigh = fbLow = fbMisaligned = 0;
            entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
            if (want == 0 || !entered) {
                printf("  FAIL combo %s %lux%lu fmt %d: entered=%d why=%d step=%d bad=%d lut=%d at %d\n",
                       boots[b].name, simxRes[r].w, simxRes[r].h, f, entered, mode.why, mode.step,
                       mode.verifyBad, mode.verifyLutBad, mode.verifyLutIndex);
                rbad++;
                continue;
            }
            if (mmio[0x0200 / 4] != simxRes[r].hTot || mmio[0x0204 / 4] != simxRes[r].hSync ||
                mmio[0x0208 / 4] != simxRes[r].vTot || mmio[0x020c / 4] != simxRes[r].vSync ||
                mmio[0x022c / 4] != simxRes[r].pitch) {
                printf("  FAIL combo %lux%lu fmt %d: CRTC words\n", simxRes[r].w, simxRes[r].h, f);
                rbad++;
            }
            if ((mmio[0x0050 / 4] & 0x00000f00UL) != simxFmt[f].crtcFormat << 8 ||
                !(mmio[0x0050 / 4] & 0x01000000UL)) {
                printf("  FAIL combo %lux%lu fmt %d: CRTC_GEN_CNTL %08lx\n",
                       simxRes[r].w, simxRes[r].h, f, mmio[0x0050 / 4]);
                rbad++;
            }
            if ((mmio[0x02f0 / 4] & simxFifo[r][f].clear) != simxFifo[r][f].set ||
                (mmio[0x02f0 / 4] & simxFifo[r][f].preserve) != (before[0x02f0 / 4] & simxFifo[r][f].preserve)) {
                printf("  FAIL combo %lux%lu fmt %d: GRPH_BUFFER_CNTL %08lx\n",
                       simxRes[r].w, simxRes[r].h, f, mmio[0x02f0 / 4]);
                rbad++;
            }
            if ((mmio[0x0058 / 4] & 0xff000100UL) != 0xff000100UL) {
                printf("  FAIL combo fmt %d: DAC_CNTL %08lx\n", f, mmio[0x0058 / 4]);
                rbad++;
            }
            if ((pll[0x07] & 0x000707ffUL) != want || pll[0x09] != simxRes[r].htotalCntl ||
                (pll[0x03] & 0x3ffUL) != rd) {
                printf("  FAIL combo %lux%lu refdiv %lu: PPLL_DIV_3 %08lx want %08lx, HTOTAL %08lx\n",
                       simxRes[r].w, simxRes[r].h, rd, pll[0x07], want, pll[0x09]);
                rbad++;
            }
            if (fbWrites != simxRes[r].h * (simxRes[r].w / per) || fbLow != 0 ||
                fbHigh != memSize - 4UL || fbMisaligned != 0 || fbSum != simxPatSum[r][f]) {
                printf("  FAIL combo %lux%lu fmt %d: pattern %lu writes, %lu..%lu, %lu misaligned, sum %08lx want %08lx\n",
                       simxRes[r].w, simxRes[r].h, f, fbWrites, fbLow, fbHigh, fbMisaligned, fbSum,
                       simxPatSum[r][f]);
                rbad++;
            }
            for (k = 0; k < OSRDN_SNAP_PALETTE; k++)
                if ((palette[k] & 0x3fcff3fcUL) !=
                    ((f == 1 ? simxLutRamp15[k] : simxLutRamp[k]) & 0x3fcff3fcUL)) {   /* G2: 555 spreads the ramp */
                    printf("  FAIL combo fmt %d: LUT entry %d is %08lx\n", f, k, palette[k]);
                    rbad++;
                    break;
                }
            if (mode.verifyFormat != simxFmt[f].crtcFormat || mode.verifyLutBad != 0) {
                printf("  FAIL combo fmt %d: read-back format %lu lut %d\n", f, mode.verifyFormat,
                       mode.verifyLutBad);
                rbad++;
            }
            osrdn_mode_revert(&mode, SIM_MMIO_BASE);
            if (mmio[0x0200 / 4] != before[0x0200 / 4] || mmio[0x0050 / 4] != before[0x0050 / 4] ||
                mmio[0x02f0 / 4] != before[0x02f0 / 4]) {
                printf("  FAIL combo %lux%lu fmt %d: the revert did not bring the console back\n",
                       simxRes[r].w, simxRes[r].h, f);
                rbad++;
            }
            combos++;
        }
        bad += rbad;
        printf("  %-4s %d resolution x format entries on both boots match the oracle and revert\n",
               rbad ? "FAIL" : "ok", combos);
    }

    /* ---- R3b-2: a boot divider the chosen resolution has no row for ------ *
     * 640x480 has no row for refdiv 8, 1024x768 none for 3 (docs/R3_MULTIMODE_PLAN.md
     * 18-2): refused before any write. */
    {
        static osrdn_mode_state mode;
        static const struct { int res; unsigned long refdiv; } hole[] = { { 0, 8 }, { 2, 3 } };
        boot_state              hb;
        int                     j, entered, hbad = 0;

        for (j = 0; j < 2; j++) {
            if (simxDiv3[hole[j].res][hole[j].refdiv] != 0) {
                printf("  FAIL hole: the oracle has a row for %lux%lu refdiv %lu\n",
                       simxRes[hole[j].res].w, simxRes[hole[j].res].h, hole[j].refdiv);
                hbad++;
                continue;
            }
            hb = boots[1];
            hb.refDiv = hole[j].refdiv;
            hb.clockIndex = 0x00000108UL;       /* index 08, not 03: modeRow must put it back */
            seed(&hb);
            simCopy(before, mmio, sizeof mmio);
            modeInit(&mode);
            mode.res = hole[j].res;
            entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
            if (entered || mode.why != MODE_WHY_REFDIV || mode.modeWritten || mode.step != 3) {
                printf("  FAIL hole %d: entered=%d why=%d written=%d step=%d\n", j, entered, mode.why,
                       mode.modeWritten, mode.step);
                hbad++;
            }
            for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
                if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                    printf("  FAIL hole %d: %s was written\n", j, osrdnSnapMmio[k].name);
                    hbad++;
                    break;
                }
        }

        /* the class never chose: a zero-filled state must not mean 640x480 */
        seed(&boots[1]);
        simCopy(before, mmio, sizeof mmio);
        modeInit(&mode);
        mode.selected = 0;
        mode.res = 0;
        entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (entered || mode.why != MODE_WHY_NOT_SELECTED || mode.modeWritten) {
            printf("  FAIL unselected: entered=%d why=%d written=%d\n", entered, mode.why, mode.modeWritten);
            hbad++;
        }
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL unselected: %s was written\n", osrdnSnapMmio[k].name);
                hbad++;
                break;
            }

        /* the boot's divider changed between two entries: refused before a write */
        seed(&boots[1]);
        modeInit(&mode);
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        osrdn_mode_revert(&mode, SIM_MMIO_BASE);
        pll[0x03] = (pll[0x03] & ~0x3ffUL) | 6UL;
        simCopy(before, mmio, sizeof mmio);
        simCopy(beforePll, pll, sizeof pll);
        entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (entered || mode.why != MODE_WHY_REFDIV || mode.modeWritten || (pll[0x03] & 0x3ffUL) != 6UL) {
            printf("  FAIL refdiv moved: entered=%d why=%d written=%d refdiv now %lu\n", entered,
                   mode.why, mode.modeWritten, pll[0x03] & 0x3ffUL);
            hbad++;
        }
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL refdiv moved: %s was written\n", osrdnSnapMmio[k].name);
                hbad++;
                break;
            }
        bad += hbad;
        printf("  %-4s no row, no selection, a moved divider: each refused before any write\n",
               hbad ? "FAIL" : "ok");
    }

    /* ---- R3b-2b: the transfer table and the brightness (docs/R3_MULTIMODE_PLAN.md 24).
     *      Every expected LUT is simx_expect.h's, written from the rule in python. */
    {
        static osrdn_mode_state mode;
        int                     xbad = 0, r;
        unsigned long           idx;

#define LUT_IS(want, what) do { int q_; for (q_ = 0; q_ < 256; q_++) if ((palette[q_] & 0x3fcff3fcUL) != ((want)[q_] & 0x3fcff3fcUL)) { \
            printf("  FAIL xfer %s: LUT[%d] %08lx, want %08lx\n", what, q_, palette[q_], (want)[q_]); xbad++; break; } } while (0)
#define DEFAULTS_BACK(what) do { if (mode.noSleep || mode.skipShow || mode.wantRevertCheck || mode.inSequence) { \
            printf("  FAIL xfer %s: left noSleep=%d skipShow=%d check=%d held=%d\n", what, mode.noSleep, mode.skipShow, \
                   mode.wantRevertCheck, mode.inSequence); xbad++; } } while (0)

        /* no table yet, zero-filled brightness: the full ramp */
        seed(&boots[1]);
        modeInit(&mode);
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        LUT_IS(simxLutRamp, "zero-filled state");
        DEFAULTS_BACK("entry");

        /* G2 (docs/G2_LUT_PLAN.md 5): a direct-colour format never puts the
           table on the LUT.  32 bpp with a table: taken (APPLIED, stored),
           the LUT stays the ramp; brightness still scales the ramp; 555 gets
           the spread ramp whatever table arrives */
        r = osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT1, 256);
        if (r != MODE_LUT_APPLIED || mode.xferCount != 256 || mode.applyLutBad != 0) {
            printf("  FAIL G2 32 bpp table: result %d count %d lutbad %d\n", r, mode.xferCount, mode.applyLutBad);
            xbad++;
        }
        LUT_IS(simxLutRamp, "G2: 32 bpp keeps the ramp under a table");
        (void)osrdn_mode_set_brightness(&mode, SIM_MMIO_BASE, 32);
        LUT_IS(simxLutRampHalf, "G2: 32 bpp brightness 32 halves the ramp");
        seed(&boots[1]);
        modeInit(&mode);
        mode.fmt = 1;
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        LUT_IS(simxLutRamp15, "G2: 555 entry spreads the ramp over the 5-bit index");
        (void)osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT3, 32);
        LUT_IS(simxLutRamp15, "G2: 555 keeps the spread ramp under a table of 32");

        /* the table plumbing, on RGB:256/8 where the table IS the LUT (G2).
           A table onto the live mode: applied at once, no sleeping,
           the PLL index word as it was -- set to a register the palette gate
           does not use, so a write left behind shows */
        seed(&boots[1]);
        modeInit(&mode);
        mode.fmt = 2;
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        mmio[0x0008 / 4] = (mmio[0x0008 / 4] & ~0xffUL) | 0x03UL;
        pllIndex = 3;
        idx = mmio[0x0008 / 4];
        sleepCalls = 0;
        r = osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT1, 256);
        if (r != MODE_LUT_APPLIED || sleepCalls != 0 || mmio[0x0008 / 4] != idx || mode.applyLutBad != 0) {
            printf("  FAIL xfer 8 bpp: result %d sleeps %lu index %08lx->%08lx lutbad %d\n", r, sleepCalls,
                   idx, mmio[0x0008 / 4], mode.applyLutBad);
            xbad++;
        }
        LUT_IS(simxLutT1, "8 bpp table");
        DEFAULTS_BACK("table");
        r = osrdn_mode_set_brightness(&mode, SIM_MMIO_BASE, 32);
        LUT_IS(simxLutT1half, "brightness 32");
        if (r != MODE_LUT_APPLIED) { printf("  FAIL xfer brightness 32: result %d\n", r); xbad++; }
        if (osrdn_mode_set_brightness(&mode, SIM_MMIO_BASE, 65) != MODE_LUT_IGNORED ||
            osrdn_mode_set_brightness(&mode, SIM_MMIO_BASE, -1) != MODE_LUT_IGNORED) {
            printf("  FAIL xfer: a brightness outside 0..64 was taken\n");
            xbad++;
        }
        LUT_IS(simxLutT1half, "a refused brightness changes nothing");
        (void)osrdn_mode_set_brightness(&mode, SIM_MMIO_BASE, 0);
        LUT_IS(simxLutBlack, "brightness 0");
        (void)osrdn_mode_set_brightness(&mode, SIM_MMIO_BASE, 64);
        if (osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, 0, 256) != MODE_LUT_IGNORED ||
            osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT2, 0) != MODE_LUT_IGNORED) {
            printf("  FAIL xfer: an empty table was taken\n");
            xbad++;
        }
        (void)osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT1long, 257);   /* not via the kernel (24-9 A2) */
        LUT_IS(simxLutT1, "257 entries are cut to 256");
        if (mode.xferCount != 256) { printf("  FAIL xfer: count %d after 257\n", mode.xferCount); xbad++; }

        /* an apply whose read-back finds a LUT entry the card did not take:
           recorded, the mode stays (a brightness call is no reason to leave it) */
        seed(&boots[1]);
        modeInit(&mode);
        mode.fmt = 2;
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        simStuckLut = 1;
        r = osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT1, 256);
        simStuckLut = 0;
        if (r != MODE_LUT_APPLIED || mode.applyLutBad != 1 || mode.applyLutIndex != 15 || !mode.modeWritten) {
            printf("  FAIL xfer stuck apply: result %d bad %d at %d written %d\n", r, mode.applyLutBad,
                   mode.applyLutIndex, mode.modeWritten);
            xbad++;
        }
        /* 255 entries (not through the kernel, 24-9 A2): the tail is the last entry */
        (void)osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT1, 255);
        LUT_IS(simxLutT1short, "255 entries");

        /* a revert owed with the card free (not reachable through the claim --
           the defence in modeLutKick): done without sleeping */
        seed(&boots[1]);
        modeInit(&mode);
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        mode.kernelRevertSeen = 1;
        sleepCalls = 0;
        r = osrdn_mode_set_brightness(&mode, SIM_MMIO_BASE, 40);
        if (r != MODE_LUT_STORED || mode.modeWritten || sleepCalls != 0) {
            printf("  FAIL xfer with a revert owed: result %d written %d sleeps %lu\n", r, mode.modeWritten,
                   sleepCalls);
            xbad++;
        }
        DEFAULTS_BACK("owed revert");

        /* a grey format reads the low byte; Gray Levels 4 overrides the table
           there, and only there */
        seed(&boots[1]);
        modeInit(&mode);
        mode.fmt = 3;
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        (void)osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT2, 256);
        LUT_IS(simxLutT2, "BW:8 table");
        /* a short table on a format that shows it is spread, each entry over
           256/count slots (not through the kernel, 24-9 A2; the 555 table of
           32 that used to prove this is gone with G2) */
        (void)osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT2, 32);
        LUT_IS(simxLutT2spread, "BW:8 table of 32 spread over 8");
        seed(&boots[1]);
        modeInit(&mode);
        mode.fmt = 3;
        mode.grayLevels = 4;
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        (void)osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT2, 256);
        LUT_IS(simxLutGray4, "BW:8 with Gray Levels 4");
        /* 16 was confirmed on the machine (boot e1a3e7e2) and 2 never was; the
           same branch, held here to the rule written separately in sim_r2b.py
           (docs/R3_MULTIMODE_PLAN.md 27-7) */
        seed(&boots[1]);
        modeInit(&mode);
        mode.fmt = 3;
        mode.grayLevels = 16;
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        (void)osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT2, 256);
        LUT_IS(simxLutGray16, "BW:8 with Gray Levels 16");
        seed(&boots[1]);
        modeInit(&mode);
        mode.fmt = 3;
        mode.grayLevels = 2;
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        (void)osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT2, 256);
        LUT_IS(simxLutGray2, "BW:8 with Gray Levels 2");
        seed(&boots[1]);
        modeInit(&mode);
        mode.fmt = 2;
        mode.grayLevels = 4;
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        (void)osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT1, 256);
        LUT_IS(simxLutT1, "Gray Levels leaves a colour format alone");

        /* (the 555 table of 32 spread over 8 was here; G2 keeps 555 on the
           spread ramp, tested above -- simxLutT3 is what a table WOULD give) */

        /* stored with no mode on the card, used by the entry (8 bpp, G2) */
        seed(&boots[1]);
        modeInit(&mode);
        mode.fmt = 2;
        r = osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT1, 256);
        if (r != MODE_LUT_STORED || mode.modeWritten) { printf("  FAIL xfer stored: result %d\n", r); xbad++; }
        if (!osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE)) {
            printf("  FAIL xfer stored: the entry with a stored table failed (why %d lut %d)\n",
                   mode.why, mode.verifyLutBad);
            xbad++;
        }
        LUT_IS(simxLutT1, "the entry uses the stored table");
        if (mode.lutPending || mode.lutApplied != 0) {     /* the ENTRY put it there, not a later apply */
            printf("  FAIL xfer stored: pending %d applied %lu after the entry\n", mode.lutPending, mode.lutApplied);
            xbad++;
        }
        /* and the cycle's re-entry uses it again */
        (void)osrdn_mode_cycle(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        LUT_IS(simxLutT1, "the cycle's re-entry uses the stored table");
        if (mode.lutPending || mode.lutApplied != 0) {
            printf("  FAIL xfer cycle: pending %d applied %lu after the re-entry\n", mode.lutPending, mode.lutApplied);
            xbad++;
        }
        DEFAULTS_BACK("cycle");
        /* no selection yet: ignored; no MMIO: stored */
        modeInit(&mode);
        mode.selected = 0;
        if (osrdn_mode_set_transfer(&mode, SIM_MMIO_BASE, simxT1, 256) != MODE_LUT_IGNORED) {
            printf("  FAIL xfer: a table before the selection was taken\n");
            xbad++;
        }
        modeInit(&mode);
        if (osrdn_mode_set_brightness(&mode, 0, 10) != MODE_LUT_STORED || mode.dim != 54) {
            printf("  FAIL xfer: base 0 did not just store (dim %d)\n", mode.dim);
            xbad++;
        }

        /* the lost update: a table arrives while the entry holds the card,
           inside step 9 and after it -- it must be on the card when the entry
           lets go */
        for (r = 1; r <= 2; r++) {
            seed(&boots[1]);
            modeInit(&mode);
            mode.fmt = 2;                   /* G2: the table shows on 8 bpp only */
            simXferMode = &mode;
            simXferHook = r;
            simXferHookRevert = 0;
            simXferHookResult = -1;
            (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
            if (simXferHookResult != MODE_LUT_DEFERRED || mode.lutDeferred != 1 || mode.lutApplied != 1) {
                printf("  FAIL xfer during entry (%d): hook %d deferred %lu applied %lu\n", r,
                       simXferHookResult, mode.lutDeferred, mode.lutApplied);
                xbad++;
            }
            LUT_IS(simxLutT1, r == 1 ? "a table inside step 9" : "a table after step 9");
            DEFAULTS_BACK("deferred");
        }
        /* ... and with a kernel revert as well: the console palette, nothing applied */
        seed(&boots[1]);
        simCopy(beforePalette, palette, sizeof palette);
        modeInit(&mode);
        simXferMode = &mode;
        simXferHook = 2;
        simXferHookRevert = 1;
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        simXferHookRevert = 0;
        if (mode.modeWritten || mode.lutApplied != 0) {
            printf("  FAIL xfer + revert: written %d applied %lu\n", mode.modeWritten, mode.lutApplied);
            xbad++;
        }
        LUT_IS(beforePalette, "a table and a kernel revert: the console's palette");
        DEFAULTS_BACK("revert");
        simXferHook = 0;
        simXferMode = 0;
        bad += xbad;
        printf("  %-4s transfer tables and brightness: formats, levels, refusals, stored, deferred, "
               "with a revert, defaults put back\n", xbad ? "FAIL" : "ok");
#undef LUT_IS
#undef DEFAULTS_BACK
    }

    /* ---- R3b-2: a card that does not take the format, the FIFO or the DAC
     *      is caught by the read-back and the entry reverts; a LUT entry that
     *      does not come back is RECORDED only (advisory in R3b-2a, 23-12 B2) */
    {
        static osrdn_mode_state mode;
        static const struct { const char *name; int kind, fmt; } w[] = {
            { "format 555", 0, 1 }, { "fifo 555", 1, 1 }, { "fifo 8 bpp", 1, 2 },
            { "dac", 2, 1 }, { "lut entry", 3, 1 }, { "lut red only", 4, 2 }
        };
        int                     j, entered, vbad = 0, lut;

        for (j = 0; j < (int)(sizeof w / sizeof w[0]); j++) {
            seed(&boots[1]);
            modeInit(&mode);
            mode.fmt = w[j].fmt;
            palette[15] = 0;                    /* the seed equals the ramp: make a dropped write show */
            simStuckFormat = (w[j].kind == 0);
            simStuckFifo = (w[j].kind == 1);
            simStuckDac = (w[j].kind == 2);
            simStuckLut = (w[j].kind == 3);
            simStuckLutRed = (w[j].kind == 4);
            entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
            simStuckFormat = simStuckFifo = simStuckDac = simStuckLut = simStuckLutRed = 0;
            lut = (w[j].kind >= 3);
            if (entered || mode.why != MODE_WHY_VERIFY || !mode.latched || mode.modeWritten ||
                (w[j].kind == 0 && mode.verifyFormat != 6UL) ||
                (lut && (mode.verifyLutBad != 1 || mode.verifyLutIndex != 15))) {
                printf("  FAIL stuck %s: entered=%d why=%d bad=%d latched=%d written=%d lut %d at %d format %lu\n",
                       w[j].name, entered, mode.why, mode.verifyBad, mode.latched, mode.modeWritten,
                       mode.verifyLutBad, mode.verifyLutIndex, mode.verifyFormat);
                vbad++;
            }
        }
        bad += vbad;
        printf("  %-4s a card that drops the format, the FIFO, the DAC or a LUT entry (or only its "
               "red) is refused and reverted\n", vbad ? "FAIL" : "ok");
    }

    /* ---- every PPLL_REF_DIV in the table, and the ones just outside ------ */
    {
        static osrdn_mode_state mode;
        static const unsigned long inside[]  = { 5, 6, 12, 71, 172 };
        static const unsigned long outside[] = { 0, 4, 173, 512 };
        boot_state              b;
        int                     j, entered, rowsSeen = 0;

        /* The driver never writes PPLL_REF_DIV, so the boot's value decides
         * the row (docs/R2B_IMPL_PLAN.md 14).  These worlds are SYNTHETIC:
         * the R2b-0 measured state with only that register changed. */
        for (j = 0; j < (int)(sizeof inside / sizeof inside[0]); j++) {
            b = boots[1];
            b.refDiv = inside[j];
            seed(&b);
            simCopy(before, mmio, sizeof mmio);
            simCopy(beforePll, pll, sizeof pll);
            simCopy(beforePalette, palette, sizeof palette);
            vgaSave(&beforeVga);
            modeInit(&mode);
            entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
            if (!entered || mode.refdiv != inside[j] || mode.div3 == 0) {
                printf("  FAIL refdiv %lu: entered=%d refdiv=%lu div3=%08lx why=%d step=%d\n",
                       inside[j], entered, mode.refdiv, mode.div3, mode.why, mode.step);
                bad++;
                continue;
            }
            if (pll[0x07] != simxDiv3[SIMX_RES_DEFAULT][inside[j]]) {
                printf("  FAIL refdiv %lu: PPLL_DIV_3 is %08lx, the oracle says %08lx\n",
                       inside[j], pll[0x07], simxDiv3[SIMX_RES_DEFAULT][inside[j]]);
                bad++;
            }
            if ((pll[0x03] & 0x3ffUL) != inside[j]) {
                printf("  FAIL refdiv %lu: PPLL_REF_DIV changed to %08lx\n",
                       inside[j], pll[0x03]);
                bad++;
            }
            rowsSeen++;
            osrdn_mode_revert(&mode, SIM_MMIO_BASE);
            for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
                if (pll[osrdnSnapPll[k].offset] != beforePll[osrdnSnapPll[k].offset]) {
                    printf("  FAIL refdiv %lu: after revert %s %08lx, was %08lx\n",
                           inside[j], osrdnSnapPll[k].name, pll[osrdnSnapPll[k].offset],
                           beforePll[osrdnSnapPll[k].offset]);
                    bad++;
                    break;
                }
        }
        for (j = 0; j < (int)(sizeof outside / sizeof outside[0]); j++) {
            b = boots[1];
            b.refDiv = outside[j];
            seed(&b);
            simCopy(before, mmio, sizeof mmio);
            modeInit(&mode);
            entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
            if (entered || mode.why != MODE_WHY_REFDIV) {
                printf("  FAIL refdiv %lu outside the table: entered=%d why=%d\n",
                       outside[j], entered, mode.why);
                bad++;
            }
            if (mode.modeWritten) {
                printf("  FAIL refdiv %lu outside the table: it wrote the mode anyway\n",
                       outside[j]);
                bad++;
            }
            for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
                if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                    printf("  FAIL refdiv %lu outside the table: %s was written\n",
                           outside[j], osrdnSnapMmio[k].name);
                    bad++;
                    break;
                }
        }
        printf("  %-4s the divider table: %d refdivs inside enter and revert, %d outside "
               "refuse without a write\n", bad ? "FAIL" : "ok", rowsSeen,
               (int)(sizeof outside / sizeof outside[0]));
    }

    /* ---- a second entry must not take a second snapshot ------------------ */
    {
        static osrdn_mode_state mode;
        int first, second;

        seed(&boots[0]);
        simCopy(before, mmio, sizeof mmio);
        simCopy(beforePll, pll, sizeof pll);
        simCopy(beforePalette, palette, sizeof palette);
        vgaSave(&beforeVga);
        modeInit(&mode);

        first = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        second = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (!first || !second) {
            printf("  FAIL second: entry %d then %d, why=%d step=%d\n",
                   first, second, mode.why, mode.step);
            bad++;
        }
        osrdn_mode_revert(&mode, SIM_MMIO_BASE);
        /* the boot state, not the mode the first entry wrote */
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL second: after revert %s %08lx, was %08lx\n",
                       osrdnSnapMmio[k].name, mmio[osrdnSnapMmio[k].offset / 4],
                       before[osrdnSnapMmio[k].offset / 4]);
                bad++;
                break;
            }
        for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
            if (pll[osrdnSnapPll[k].offset] != beforePll[osrdnSnapPll[k].offset]) {
                printf("  FAIL second: after revert %s %08lx, was %08lx\n",
                       osrdnSnapPll[k].name, pll[osrdnSnapPll[k].offset],
                       beforePll[osrdnSnapPll[k].offset]);
                bad++;
                break;
            }
        for (k = 0; k < OSRDN_SNAP_PALETTE; k++)
            if (palette[k] != beforePalette[k]) {
                printf("  FAIL second: after revert palette[%d] %08lx, was %08lx\n",
                       k, palette[k], beforePalette[k]);
                bad++;
                break;
            }
        vgaSave(&afterVga);
        for (k = 0; k < OSRDN_SNAP_CRTC; k++)
            if (afterVga.crtc[k] != beforeVga.crtc[k]) {
                printf("  FAIL second: after revert CRTC[%d] %02x, was %02x\n",
                       k, afterVga.crtc[k], beforeVga.crtc[k]);
                bad++;
                break;
            }
        printf("  %-4s a second entry keeps the first snapshot: the revert still returns the "
               "boot state (enters %lu)\n", bad ? "FAIL" : "ok",
               (unsigned long)mode.enterCount);
    }

    /* ---- the cycle: revert, read the whole snapshot back, come back ------ */
    {
        static osrdn_mode_state mode;
        int first, cyc, again;

        seed(&boots[1]);
        simCopy(before, mmio, sizeof mmio);
        simCopy(beforePll, pll, sizeof pll);
        simCopy(beforePalette, palette, sizeof palette);
        vgaSave(&beforeVga);
        modeInit(&mode);

        first = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        sleepCalls = 0;
        delayCalls = 0;
        fbWrites = 0;
        cyc = osrdn_mode_cycle(&mode, SIM_MMIO_BASE, SIM_FB_BASE);

        if (!first || !cyc) {
            printf("  FAIL cycle: enter=%d cycle=%d why=%d step=%d\n",
                   first, cyc, mode.cycleWhy, mode.step);
            bad++;
        }
        /* the read-back ran and found the whole snapshot back */
        if (!mode.revertChecked || mode.revertBad || mode.revertVgaBad || mode.revertPaletteBad) {
            printf("  FAIL cycle: checked=%d why=%d bad=%d vga=%d palette=%d\n",
                   mode.revertChecked, mode.revertCheckWhy, mode.revertBad,
                   mode.revertVgaBad, mode.revertPaletteBad);
            bad++;
        }
        /* it must not sleep: setIntValues holds a lock and an spl we have not
           measured (docs/R2C_REVERT_PLAN.md 3-1) */
        if (sleepCalls != 0) {
            printf("  FAIL cycle: it slept %lu times\n", sleepCalls);
            bad++;
        }
        if (delayCalls == 0) {
            printf("  FAIL cycle: it never waited at all\n");
            bad++;
        }
        /* the picture is back */
        if (mmio[0x0200 / 4] != simxRes[SIMX_RES_DEFAULT].hTot || !mode.modeWritten) {
            printf("  FAIL cycle: the mode did not come back\n");
            bad++;
        }
        /* and it did NOT paint over what was on the screen: a mode change does
           not clear the framebuffer, so leaving it alone is what brings the
           desktop back.  The first cycle on the machine painted the test
           pattern and the window server never redrew it (2026-09-16). */
        if (fbWrites != 0) {
            printf("  FAIL cycle: it wrote %lu framebuffer words over the desktop\n", fbWrites);
            bad++;
        }
        /* the shutdown path gets its proved behaviour back */
        if (mode.noSleep || mode.skipShow || mode.wantRevertCheck) {
            printf("  FAIL cycle: it left noSleep=%d skipShow=%d check=%d set\n",
                   mode.noSleep, mode.skipShow, mode.wantRevertCheck);
            bad++;
        }
        /* once per boot */
        again = osrdn_mode_cycle(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (again || mode.cycleWhy != MODE_WHY_CYCLE_DONE) {
            printf("  FAIL cycle: a second cycle returned %d why=%d\n", again, mode.cycleWhy);
            bad++;
        }
        /* and the shutdown revert still returns the boot state */
        osrdn_mode_revert(&mode, SIM_MMIO_BASE);
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL cycle: after the shutdown revert %s %08lx, was %08lx\n",
                       osrdnSnapMmio[k].name, mmio[osrdnSnapMmio[k].offset / 4],
                       before[osrdnSnapMmio[k].offset / 4]);
                bad++;
                break;
            }
        vgaSave(&afterVga);
        for (k = 0; k < OSRDN_SNAP_CRTC; k++)
            if (afterVga.crtc[k] != beforeVga.crtc[k]) {
                printf("  FAIL cycle: after the shutdown revert CRTC[%d] %02x, was %02x\n",
                       k, afterVga.crtc[k], beforeVga.crtc[k]);
                bad++;
                break;
            }
        printf("  %-4s one cycle per boot: revert, whole-snapshot read-back, back to the mode "
               "(%lu delays, %lu sleeps)\n", bad ? "FAIL" : "ok", delayCalls, sleepCalls);
    }

    /* ---- the three ways the trigger bit can go --------------------------- */
    {
        static osrdn_mode_state mode;
        int j;
        /* reads-until-clear, CNTL stuck, wanted verdict, wanted pending, name */
        static const struct { int reads, cntl, verdict, pending; const char *name; } trig[] = {
            { 0,    0, 0, 0, "never pending" },
            { 3,    0, 0, 0, "clears after 3 reads" },
            { -1,   0, 1, 1, "never clears: pending, not failure" },
            { 0,    1, 1, 0, "only CRTC_OFFSET_CNTL keeps the bit" }
        };

        for (j = 0; j < (int)(sizeof trig / sizeof trig[0]); j++) {
            seed(&boots[1]);
            modeInit(&mode);
            simTrigReads = 0;
            simTrigCntlStuck = 0;
            simTrigCntlSet = 0;
            simTrigLeft = 0;
            (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
            simTrigForever = (trig[j].reads < 0);
            simTrigReads = simTrigForever ? 0 : trig[j].reads;
            simTrigCntlStuck = trig[j].cntl;
            (void)osrdn_mode_cycle(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
            if (mode.revertVerdict != trig[j].verdict ||
                mode.revertOffsetPending != trig[j].pending) {
                printf("  FAIL trig[%s]: verdict=%d want %d, pending=%d want %d, "
                       "turns=%lu bad=%d vga=%d palette=%d\n",
                       trig[j].name, mode.revertVerdict, trig[j].verdict,
                       mode.revertOffsetPending, trig[j].pending,
                       mode.revertOffsetTurns, mode.revertBad, mode.revertVgaBad,
                       mode.revertPaletteBad);
                bad++;
            }
            simTrigForever = 0;
            simTrigReads = 0;
            simTrigCntlStuck = 0;
            simTrigCntlSet = 0;
            simTrigLeft = 0;
        }
        /* and a real difference is still a real difference: a register the card
           refuses to take is what a revert failure looks like from a read-back */
        seed(&boots[1]);
        modeInit(&mode);
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        simStuckPitch = 1;
        (void)osrdn_mode_cycle(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        simStuckPitch = 0;
        if (mode.revertVerdict != 2) {
            printf("  FAIL trig: a real mismatch gave verdict %d, want 2 (bad=%d)\n",
                   mode.revertVerdict, mode.revertBad);
            bad++;
        }
        printf("  %-4s the trigger bit: %d worlds tell pending from failure, and a real "
               "mismatch still fails\n", bad ? "FAIL" : "ok",
               (int)(sizeof trig / sizeof trig[0]));
    }

    /* ---- a VGA byte that does not come back must be NAMED ---------------- */
    {
        static osrdn_mode_state mode;

        seed(&boots[1]);
        modeInit(&mode);
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        /* something changed a VGA byte while the mode was up -- the real case
           the machine showed on 2026-09-16 -- and the restore cannot put it
           back, so the read-back must name it rather than just count it */
        vCrtc[0x0e] = (unsigned char)(vCrtc[0x0e] ^ 0x5a);
        simStuckCrtc = 0x0e;
        (void)osrdn_mode_cycle(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        simStuckCrtc = -1;
        if (mode.revertVgaBad != 1 || mode.revertVerdict != 2) {
            printf("  FAIL vganame: vgaBad=%d verdict=%d, want 1 and 2\n",
                   mode.revertVgaBad, mode.revertVerdict);
            bad++;
        } else if (mode.revertVgaKind[0] != 3 || mode.revertVgaIndex[0] != 0x0e) {
            printf("  FAIL vganame: named kind=%d index=%02x, want 3 and 0e\n",
                   mode.revertVgaKind[0], mode.revertVgaIndex[0]);
            bad++;
        } else if (mode.revertVgaWant[0] == mode.revertVgaGot[0]) {
            printf("  FAIL vganame: want and got are both %02x\n", mode.revertVgaWant[0]);
            bad++;
        }
        printf("  %-4s a VGA byte that does not come back is named (kind=%d index=%02x "
               "snap=%02x got=%02x)\n", bad ? "FAIL" : "ok", mode.revertVgaKind[0],
               mode.revertVgaIndex[0], mode.revertVgaWant[0], mode.revertVgaGot[0]);
    }

    /* ---- a frozen clock: every wait must still end ----------------------- */
    {
        static osrdn_mode_state mode;
        int entered, cyc;

        seed(&boots[1]);
        modeInit(&mode);
        simCopy(before, mmio, sizeof mmio);
        simStickyAtomic = 1;
        simFrozenClock = 1;

        /* the entry first, with the clock already stopped: its own waits must
           end.  The trigger is turned on only afterwards, so the snapshot holds
           the register as the card really had it -- the reference driver also
           saves whatever it reads (legacy_crtc.c 541). */
        entered = osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        simTrigForever = 1;
        cyc = entered ? osrdn_mode_cycle(&mode, SIM_MMIO_BASE, SIM_FB_BASE) : 0;
        /* Reaching this line at all is the check: with a stopped clock the only
           thing that can end these waits is the turn bound. */
        simFrozenClock = 0;
        simStickyAtomic = 0;
        simTrigForever = 0;
        simTrigReads = 0;
        simTrigLeft = 0;
        osrdn_mode_revert(&mode, SIM_MMIO_BASE);
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL frozen: after revert %s %08lx, was %08lx\n",
                       osrdnSnapMmio[k].name, mmio[osrdnSnapMmio[k].offset / 4],
                       before[osrdnSnapMmio[k].offset / 4]);
                bad++;
                break;
            }
        printf("  %-4s a stopped clock: every wait still ends (enter=%d cycle=%d) and the "
               "revert still returns the boot state\n", bad ? "FAIL" : "ok", entered, cyc);
    }

    /* ---- a kernel revert arriving DURING the cycle's re-entry ------------ */
    {
        static osrdn_mode_state mode;
        int cyc;

        seed(&boots[1]);
        simCopy(before, mmio, sizeof mmio);
        simCopy(beforePll, pll, sizeof pll);
        vgaSave(&beforeVga);
        modeInit(&mode);
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        /* fire once the cycle's revert half has cleared modeWritten and the
           re-entry has set it again -- i.e. inside the re-entry, after the
           only place the cycle used to look at kernelRevertSeen */
        simHookMode = &mode;
        simHookPhase = 1;
        cyc = osrdn_mode_cycle(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (simHookMode != 0) {
            printf("  FAIL shutdown race: the hook never fired\n");
            bad++;
            simHookMode = 0;
            simHookPhase = 0;
        }
        if (cyc || mode.modeWritten || mode.inSequence ||
            mode.cycleWhy != MODE_WHY_KERNEL_CAME) {
            printf("  FAIL shutdown race: live=%d written=%d held=%d why=%d\n",
                   cyc, mode.modeWritten, mode.inSequence, mode.cycleWhy);
            bad++;
        }
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL shutdown race: %s %08lx, the console had %08lx\n",
                       osrdnSnapMmio[k].name, mmio[osrdnSnapMmio[k].offset / 4],
                       before[osrdnSnapMmio[k].offset / 4]);
                bad++;
                break;
            }
        vgaSave(&afterVga);
        for (k = 0; k < OSRDN_SNAP_CRTC; k++)
            if (afterVga.crtc[k] != beforeVga.crtc[k]) {
                printf("  FAIL shutdown race: CRTC[%d] not the console's\n", k);
                bad++;
                break;
            }
        printf("  %-4s a kernel revert during the re-entry leaves the card as the console had it\n",
               bad ? "FAIL" : "ok");
    }

    /* ---- a kernel revert arriving while a cycle holds the card ----------- */
    {
        static osrdn_mode_state mode;

        seed(&boots[1]);
        modeInit(&mode);
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        simCopy(before, mmio, sizeof mmio);

        mode.inSequence = 1;                    /* a cycle is between revert and re-entry */
        osrdn_mode_revert(&mode, SIM_MMIO_BASE);
        if (!mode.kernelRevertSeen) {
            printf("  FAIL claim: a kernel revert under a held claim was not recorded\n");
            bad++;
        }
        for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
            if (mmio[osrdnSnapMmio[k].offset / 4] != before[osrdnSnapMmio[k].offset / 4]) {
                printf("  FAIL claim: it wrote %s underneath the holder\n", osrdnSnapMmio[k].name);
                bad++;
                break;
            }
        mode.inSequence = 0;
        printf("  %-4s a kernel revert under a held claim writes nothing and is recorded\n",
               bad ? "FAIL" : "ok");
    }

    /* The snapshot only READS the palette: no data write, nothing changed, and
       what it read is what the card holds.  Entry 0 is made non-zero so a
       stray write of 0 cannot hide.  (Kept from the R3b-0 measurement, whose
       result fixed the read model above -- docs/R3_MULTIMODE_PLAN.md 21-7, 22-5 V8.) */
    {
        static osrdn_snap    ps;
        static unsigned long palBefore[OSRDN_SNAP_PALETTE];
        int                  pbad = 0;

        seed(&boots[0]);
        palette[0] = 0x2abfeaa8UL;
        simCopy(palBefore, palette, sizeof palette);
        simPalDataWrites = 0;
        if (!osrdn_snap_take(SIM_MMIO_BASE, &ps)) {
            printf("  FAIL palette: the snapshot refused (why %d)\n", ps.why);
            pbad++;
        } else {
            if (simPalDataWrites != 0) {
                printf("  FAIL palette: the snapshot wrote palette data %lu times\n", simPalDataWrites);
                pbad++;
            }
            for (k = 0; k < OSRDN_SNAP_PALETTE; k++)
                if (palette[k] != palBefore[k] || ps.palette[k] != palBefore[k]) {
                    printf("  FAIL palette: entry %d is %08lx, was %08lx, read %08lx\n",
                           k, palette[k], palBefore[k], ps.palette[k]);
                    pbad++;
                    break;
                }
        }
        bad += pbad;
        printf("  %-4s the snapshot reads the palette without writing it, and reads it right\n",
               pbad ? "FAIL" : "ok");
    }

    /* ---- R4: the engine wrapper (docs/R4_ENGINE_PLAN.md 13 #8) -------------- */
    {
        static osrdn_mode_state   mode;
        static osrdn_engine_state eng, engCopy;
        int           ebad = 0, rc;
        unsigned long s0, l0;

        seed(&boots[1]);
        modeInit(&mode);
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        simEngMode = &mode;
        simEngRevert = simEngXfer = 0;

        simEngCalls = 0;
        s0 = sleepCalls;
        rc = osrdn_mode_engine(&mode, SIM_MMIO_BASE, &eng, ENG_OP_RECORD, 0, &engCopy);
        if (rc != ENG_RC_RAN || simEngCalls != 1 || mode.inSequence || mode.noSleep ||
            !mode.modeWritten || sleepCalls != s0) {
            printf("  FAIL engine wrapper: plain run rc=%d calls=%d held=%d noSleep=%d written=%d slept=%lu\n",
                   rc, simEngCalls, mode.inSequence, mode.noSleep, mode.modeWritten, sleepCalls - s0);
            ebad++;
        }

        l0 = mode.lutApplied;
        simEngXfer = 1;
        s0 = sleepCalls;
        rc = osrdn_mode_engine(&mode, SIM_MMIO_BASE, &eng, ENG_OP_FILL, 0, &engCopy);
        simEngXfer = 0;
        if (rc != ENG_RC_RAN || mode.lutApplied == l0 || mode.lutPending || mode.inSequence ||
            sleepCalls != s0) {
            printf("  FAIL engine wrapper: a table arriving meanwhile was not applied at release "
                   "(applied %lu->%lu pending=%d held=%d slept=%lu)\n",
                   l0, mode.lutApplied, mode.lutPending, mode.inSequence, sleepCalls - s0);
            ebad++;
        }

        simEngRevert = 1;
        s0 = sleepCalls;
        rc = osrdn_mode_engine(&mode, SIM_MMIO_BASE, &eng, ENG_OP_BLIT, 1, &engCopy);
        simEngRevert = 0;
        if (rc != ENG_RC_RAN || mode.modeWritten || mode.inSequence || sleepCalls != s0) {
            printf("  FAIL engine wrapper: a kernel revert meanwhile was %s (written=%d held=%d slept=%lu)\n",
                   mode.modeWritten ? "LOST" : "honoured", mode.modeWritten, mode.inSequence,
                   sleepCalls - s0);
            ebad++;
        }

        simEngCalls = 0;
        rc = osrdn_mode_engine(&mode, SIM_MMIO_BASE, &eng, ENG_OP_RECORD, 0, &engCopy);
        if (rc != ENG_RC_NOT_LIVE || simEngCalls != 0 || mode.inSequence) {
            printf("  FAIL engine wrapper: ran with no mode on the card (rc=%d calls=%d)\n", rc, simEngCalls);
            ebad++;
        }

        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        mode.inSequence = 1;                    /* someone else holds the card */
        simEngCalls = 0;
        rc = osrdn_mode_engine(&mode, SIM_MMIO_BASE, &eng, ENG_OP_RECORD, 0, &engCopy);
        mode.inSequence = 0;
        if (rc != ENG_RC_BUSY || simEngCalls != 0) {
            printf("  FAIL engine wrapper: ran under someone else's claim (rc=%d calls=%d)\n", rc, simEngCalls);
            ebad++;
        }
        simEngMode = 0;
        bad += ebad;
        printf("  %-4s engine wrapper: runs under the claim, never sleeps, honours a revert and a "
               "table that arrive meanwhile, refuses with no mode or a held claim\n", ebad ? "FAIL" : "ok");
    }

    /* ---- R5: the mode module's side of the CP (docs/R5_PLAN.md 7-2 B2 B3 B10) ---- */
    {
        static osrdn_mode_state   mode;
        static osrdn_cp_state     cp, cpCopy;
        static osrdn_engine_state eng, engCopy;
        int           cbad = 0, rc, live;
        unsigned long w0, s0;

        seed(&boots[1]);
        modeInit(&mode);
        mode.cp = &cp;
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        simCpMode = &mode;
        simCpRevert = 0;

        /* the CP holds the card: a cycle is refused BEFORE it reverts anything */
        simCpAllows = 0;
        simCpQuiesce = 0;
        w0 = (unsigned long)writeCount;
        live = osrdn_mode_cycle(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        if (live || mode.cycleWhy != MODE_WHY_CP || !mode.modeWritten || simCpQuiesce != 0 ||
            (unsigned long)writeCount != w0 || mode.inSequence) {
            printf("  FAIL R5: a cycle with the CP on was not refused before the revert "
                   "(live=%d why=%d written=%d quiesce=%d writes=%lu)\n", live, mode.cycleWhy,
                   mode.modeWritten, simCpQuiesce, (unsigned long)writeCount - w0);
            cbad++;
        }
        /* ... and so is an R4 engine operation */
        simEngCalls = 0;
        simEngMode = 0;
        rc = osrdn_mode_engine(&mode, SIM_MMIO_BASE, &eng, ENG_OP_FILL, 0, &engCopy);
        if (rc != ENG_RC_CP || simEngCalls != 0 || mode.inSequence) {
            printf("  FAIL R5: an engine operation ran while the CP holds the card (rc=%d calls=%d)\n",
                   rc, simEngCalls);
            cbad++;
        }
        simCpAllows = 1;

        /* a kernel revert while a CP operation holds the claim: owed at modeFinish,
           and the CP is stopped first */
        simCpRevert = 1;
        simCpQuiesce = 0;
        s0 = sleepCalls;
        rc = osrdn_mode_cp(&mode, SIM_MMIO_BASE, &cp, 0, CP_OP_RECORD, 0, 0, &cpCopy, 0);
        simCpRevert = 0;
        if (rc != CP_RC_RAN || mode.modeWritten || simCpQuiesce < 1 || mode.inSequence ||
            sleepCalls != s0) {
            printf("  FAIL R5: a revert owed during a CP operation did not stop the CP, or slept "
                   "(rc=%d written=%d quiesce=%d held=%d slept=%lu)\n", rc, mode.modeWritten, simCpQuiesce,
                   mode.inSequence, sleepCalls - s0);
            cbad++;
        }
        /* no mode on the card now: STOP still runs, SUBMIT does not */
        simCpRuns = 0;
        rc = osrdn_mode_cp(&mode, SIM_MMIO_BASE, &cp, 0, CP_OP_STOP, 0, 0, &cpCopy, 0);
        if (rc != CP_RC_RAN || simCpRuns != 1) {
            printf("  FAIL R5: STOP refused with no mode on the card (rc=%d runs=%d)\n", rc, simCpRuns);
            cbad++;
        }
        simCpRuns = 0;
        rc = osrdn_mode_cp(&mode, SIM_MMIO_BASE, &cp, 0, CP_OP_SUBMIT, 1, 16, &cpCopy, 0);
        if (rc != CP_RC_NOT_LIVE || simCpRuns != 0) {
            printf("  FAIL R5: SUBMIT ran with no mode on the card (rc=%d runs=%d)\n", rc, simCpRuns);
            cbad++;
        }
        /* a revert with no mode on the card still stops the CP */
        simCpQuiesce = 0;
        osrdn_mode_revert(&mode, SIM_MMIO_BASE);
        if (simCpQuiesce != 1) {
            printf("  FAIL R5: a revert with no mode on the card did not stop the CP (%d)\n", simCpQuiesce);
            cbad++;
        }
        /* someone else holds the claim */
        (void)osrdn_mode_enter(&mode, SIM_MMIO_BASE, SIM_FB_BASE);
        mode.inSequence = 1;
        simCpRuns = 0;
        rc = osrdn_mode_cp(&mode, SIM_MMIO_BASE, &cp, 0, CP_OP_STOP, 0, 0, &cpCopy, 0);
        mode.inSequence = 0;
        if (rc != CP_RC_BUSY || simCpRuns != 0) {
            printf("  FAIL R5: a CP operation ran under someone else's claim (rc=%d)\n", rc);
            cbad++;
        }
        simCpMode = 0;
        bad += cbad;
        printf("  %-4s R5: every revert stops the CP first, a cycle and an engine operation are refused "
               "while it holds the card, STOP runs without a mode\n", cbad ? "FAIL" : "ok");
    }

    /* 5. every write went to an offset in the tables, or to an index register */
    for (k = 0; k < writeCount; k++) {
        int j, okOffset = (writeTrace[k] == 0x0008 || writeTrace[k] == 0x000c ||
                           writeTrace[k] == 0x00b0 || writeTrace[k] == 0x00b8);
        for (j = 0; !okOffset && j < OSRDN_SNAP_MMIO_COUNT; j++)
            if ((unsigned int)writeTrace[k] == osrdnSnapMmio[j].offset)
                okOffset = 1;
        if (!okOffset) {
            printf("  FAIL a write went to offset %04x, which is not in the tables\n", writeTrace[k]);
            bad++;
            break;
        }
    }
    printf("%s\n", bad ? "simworld2b: FAIL" : "simworld2b: PASS");
    exit(bad ? 1 : 0);
}
