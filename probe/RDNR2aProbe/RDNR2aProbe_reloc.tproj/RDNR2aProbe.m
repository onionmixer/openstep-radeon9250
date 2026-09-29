/*
 * RDNR2aProbe.m - R2a MMIO and PLL snapshot of a PCI Radeon 9250 (RV280).
 *
 * Plan: docs/R1C_R2A_IMPL_PLAN.md section 2 (and docs/R2_FIRST_LIGHT_PLAN.md
 * section 3, R2a).  Log grammar: tools/r2a/parse_r2a.py.
 *
 * What this file does, and all it does:
 *
 *   A  PCI configuration reads through mechanism #1 (R1's code): a write of
 *      the host bridge's address latch at 0xCF8, a read of 0xCFC.  No
 *      configuration register of any device is written.
 *   B  One 0x2000-byte mapping of BAR2 after R1's checks, the liveness
 *      samples, reads of 50 named MMIO registers.
 *   P  Ten PLL register reads.  Each is one group with interrupts masked
 *      (splhigh): read CLOCK_CNTL_INDEX (P); if its write-enable bit is set,
 *      stop without writing; store the six-bit index in the low byte only;
 *      re-read (C) and require bits 8-31 unchanged and the low byte equal to
 *      the index; read CLOCK_CNTL_DATA; re-read the index (D) and require
 *      D = C; store P's low byte back; re-read (E) and require E = P.  Any
 *      failed requirement writes P back as a full 32-bit value -- the value
 *      read inside the same masked group, never an older one -- and ends the
 *      probe.  That 32-bit write exists only on that path.
 *
 * No PLL data register is written, no register other than CLOCK_CNTL_INDEX
 * is written, no index other than the PLL index is touched (no VGA, no
 * attribute, no palette).  All MMIO goes through RDNR2aMMIO.h; this file has
 * no pointer store at all.  tools/r2a/hostcheck.sh checks the source and the
 * object, tools/r2a/check_reloc.py the target-built helpers.
 *
 * It is a bare loadable: not an IODevice, no Auto Detect, loaded with
 * CALL/WIRE/START and never ADVERTISEd, run once, unloaded.
 */

#import <driverkit/generalFuncs.h>
#import <driverkit/kernelDriver.h>
#import <driverkit/i386/ioPorts.h>
#import <kernserv/machine/spl.h>    /* splhigh/splx, as EMU10K1Driver.m does */
#import <stdio.h>                   /* sprintf */
#import "RDNR2aMMIO.h"

/* Every hex field is printed with %x on an (unsigned int), never with a
 * field width together with the long modifier: the kernel sprintf ignores
 * that width (target, 2026-09-15).  tools/r2a/hostcheck.sh rejects it. */
#define U(x)                ((unsigned int)(x))

#define R2A_VERSION         1

/* Provenance: tools/r2a/target-build.sh passes -DR2A_BUILD=0x<stamp>.
 * 0 means unstamped, and the host parser refuses such a log. */
#ifndef R2A_BUILD
#define R2A_BUILD           0x00000000
#endif

#define PCI_CFG_ADDR        0x0CF8
#define PCI_CFG_DATA        0x0CFC
#define PCI_MAX_BUS         8
#define PCI_MAX_DEVICE      32
#define PCI_MAX_FUNCTION    8

#define ATI_VENDOR          0x1002

#define BAR2_REG            0x18        /* radeonfbreg.h RADEON_MAPREG_MMIO */
#define MMIO_MAP_LENGTH     0x2000      /* largest offset read: RBBM_STATUS 0x0e40 */

#define LIVE_SAMPLES        8
#define LIVE_GAP_US         2000
#define FRAME_GAP_MS        60
#define LINE_PACE_MS        20

#define REG_CLOCK_CNTL_INDEX 0x0008     /* radeonfbreg.h:330, radeon_reg.h:289 */
#define REG_CLOCK_CNTL_DATA  0x000c     /* radeonfbreg.h:329, radeon_reg.h:288 */
#define PLL_WR_EN           0x80UL      /* radeonfbreg.h RADEON_PLL_WR_EN (1 << 7) */
#define PLL_INDEX_MASK      0x3f        /* the index field: radeonfb.c:1578 idx & 0x3f */
#define LOW_BYTE            0xffUL

#define REG_CRTC_VLINE      0x0210
#define REG_CRTC_FRAME      0x0214
#define VLINE_MASK          (0x7ffUL << 16)     /* radeonfbreg.h:574 */

#define MAX_BRIDGES         16

/* the reason a PLL group stopped */
#define WHY_NONE            0
#define WHY_BUSY            1
#define WHY_UPPER           2
#define WHY_LOW             3
#define WHY_AFTER_DATA      4
#define WHY_RESTORE         5

typedef struct {
    const char     *name;
    unsigned int    offset;
} r2a_reg;

/* R1's 35 registers, then 15 more (docs/R1C_R2A_IMPL_PLAN.md section 2-3).
 * Offsets agree in the NetBSD and xf86 headers (tools/oracle/regtable.py);
 * tools/r2a/parse_r2a.py REGS must equal this table. */
static const r2a_reg r2aRegs[] = {
    { "CLOCK_CNTL_INDEX",      0x0008 },
    { "BUS_CNTL",              0x0030 },
    { "GEN_INT_CNTL",          0x0040 },
    { "GEN_INT_STATUS",        0x0044 },
    { "CRTC_GEN_CNTL",         0x0050 },
    { "CRTC_EXT_CNTL",         0x0054 },
    { "DAC_CNTL",              0x0058 },
    { "DAC_CNTL2",             0x007c },
    { "CONFIG_MEMSIZE",        0x00f8 },
    { "CONFIG_APER_0_BASE",    0x0100 },
    { "CONFIG_APER_SIZE",      0x0108 },
    { "HOST_PATH_CNTL",        0x0130 },
    { "MC_FB_LOCATION",        0x0148 },
    { "MC_AGP_LOCATION",       0x014c },
    { "MEM_SDRAM_MODE_REG",    0x0158 },
    { "AIC_CNTL",              0x01d0 },
    { "CRTC_H_TOTAL_DISP",     0x0200 },
    { "CRTC_H_SYNC_STRT_WID",  0x0204 },
    { "CRTC_V_TOTAL_DISP",     0x0208 },
    { "CRTC_V_SYNC_STRT_WID",  0x020c },
    { "CRTC_OFFSET",           0x0224 },
    { "CRTC_PITCH",            0x022c },
    { "DISPLAY_BASE_ADDR",     0x023c },
    { "CRTC_MORE_CNTL",        0x027c },
    { "FP_GEN_CNTL",           0x0284 },
    { "GRPH_BUFFER_CNTL",      0x02f0 },
    { "CRTC2_GEN_CNTL",        0x03f8 },
    { "CP_RB_CNTL",            0x0704 },
    { "CP_RB_RPTR",            0x0710 },
    { "CP_RB_WPTR",            0x0714 },
    { "CP_CSQ_CNTL",           0x0740 },
    { "SURFACE_CNTL",          0x0b00 },
    { "DAC_MACRO_CNTL",        0x0d04 },
    { "DISP_OUTPUT_CNTL",      0x0d64 },
    { "RBBM_STATUS",           0x0e40 },
    { "CRTC_OFFSET_CNTL",      0x0228 },
    { "DISP_MERGE_CNTL",       0x0d60 },
    { "TV_DAC_CNTL",           0x088c },
    { "DISP_HW_DEBUG",         0x0d14 },
    { "OVR_CLR",               0x0230 },
    { "OVR_WID_LEFT_RIGHT",    0x0234 },
    { "OVR_WID_TOP_BOTTOM",    0x0238 },
    { "OV0_SCALE_CNTL",        0x0420 },
    { "SUBPIC_CNTL",           0x0540 },
    { "VIPH_CONTROL",          0x0c40 },
    { "I2C_CNTL_1",            0x0094 },
    { "CAP0_TRIG_CNTL",        0x0950 },
    { "CAP1_TRIG_CNTL",        0x09c0 },
    { "MEM_CNTL",              0x0140 },
    { "MEM_TIMING_CNTL",       0x0144 }
};
#define R2A_REG_COUNT ((int)(sizeof(r2aRegs) / sizeof(r2aRegs[0])))

/* PLL indices (docs/R1C_R2A_IMPL_PLAN.md section 2-4); tools/r2a/parse_r2a.py
 * PLL must equal this table.  Every index has bits 6-7 clear. */
static const r2a_reg r2aPll[] = {
    { "PPLL_CNTL",             0x02 },
    { "PPLL_REF_DIV",          0x03 },
    { "PPLL_DIV_0",            0x04 },
    { "PPLL_DIV_3",            0x07 },
    { "VCLK_ECP_CNTL",         0x08 },
    { "HTOTAL_CNTL",           0x09 },
    { "X_MPLL_REF_FB_DIV",     0x0a },
    { "SCLK_CNTL",             0x0d },
    { "MCLK_CNTL",             0x12 },
    { "PIXCLKS_CNTL",          0x2d }
};
#define R2A_PLL_COUNT ((int)(sizeof(r2aPll) / sizeof(r2aPll[0])))

static const unsigned int rv280Ids[] = {
    0x5960, 0x5961, 0x5962, 0x5963, 0x5964, 0x5965, 0x5c61, 0x5c63
};
#define RV280_ID_COUNT ((int)(sizeof(rv280Ids) / sizeof(rv280Ids[0])))

typedef struct {
    int             bus, device, function;
    unsigned long   busNumbers;     /* config 0x18 */
    unsigned long   memWindow;      /* config 0x20: base/limit */
    unsigned long   prefWindow;     /* config 0x24: base/limit, type in bits 3-0 */
    unsigned long   prefBaseUpper;  /* config 0x28 */
    unsigned long   prefLimitUpper; /* config 0x2c */
} r2a_bridge;

/* one PLL group's readings */
typedef struct {
    unsigned long   p, c, v, d, e, a;
} r2a_pllread;

static int          r2aRunId;
static int          r2aSeq;
static r2a_bridge   r2aBridges[MAX_BRIDGES];
static int          r2aBridgeCount;
static int          r2aBridgeOverflow;
static r2a_pllread  r2aPllRead[R2A_PLL_COUNT];

/* ---- output ------------------------------------------------------------ */

/* Every line: "RDN-R2A <runid> <kind> ... seq=<n>", paced. */
static void
r2aLine(const char *body)
{
    IOLog("RDN-R2A %d %s seq=%d\n", r2aRunId, body, r2aSeq);
    r2aSeq++;
    IOSleep(LINE_PACE_MS);
}

/* ---- A: PCI configuration reads (as R1) ---------------------------------- */

static unsigned long
pciRead(int bus, int device, int function, int reg)
{
    unsigned long address;

    address = 0x80000000UL
        | ((unsigned long)(bus & 0xff) << 16)
        | ((unsigned long)(device & 0x1f) << 11)
        | ((unsigned long)(function & 0x07) << 8)
        | ((unsigned long)(reg & 0xfc));
    outl((IOEISAPortAddress)PCI_CFG_ADDR, address);
    return inl((IOEISAPortAddress)PCI_CFG_DATA);
}

static int
isRV280(unsigned int device)
{
    int i;

    for (i = 0; i < RV280_ID_COUNT; i++)
        if (rv280Ids[i] == device)
            return 1;
    return 0;
}

/* A memory window from a type-1 header word: base in the low 16 bits,
 * limit in the high 16 bits, each the top 12 bits of a 32-bit address. */
static int
windowContains(unsigned long word, unsigned long start, unsigned long length)
{
    unsigned long base;
    unsigned long limit;

    base = (word & 0xfff0UL) << 16;
    limit = (((word >> 16) & 0xfff0UL) << 16) | 0xfffffUL;
    if (base > limit)
        return 0;
    if (start < base)
        return 0;
    if (length == 0 || start + (length - 1) < start)
        return 0;
    return start + (length - 1) <= limit;
}

static void
scanPci(int *cardBus, int *cardDevice, int *cardFunction, int *cardCount)
{
    int bus, device, function, functions;
    unsigned long idWord, header, classRev, subsys;
    char line[180];

    *cardCount = 0;
    r2aBridgeCount = 0;
    r2aBridgeOverflow = 0;
    for (bus = 0; bus < PCI_MAX_BUS; bus++) {
        for (device = 0; device < PCI_MAX_DEVICE; device++) {
            idWord = pciRead(bus, device, 0, 0x00);
            if ((idWord & 0xffffUL) == 0xffffUL || idWord == 0UL)
                continue;
            header = pciRead(bus, device, 0, 0x0c);
            functions = ((header >> 16) & 0x80UL) ? PCI_MAX_FUNCTION : 1;
            for (function = 0; function < functions; function++) {
                idWord = pciRead(bus, device, function, 0x00);
                if ((idWord & 0xffffUL) == 0xffffUL || idWord == 0UL)
                    continue;
                classRev = pciRead(bus, device, function, 0x08);
                if ((classRev >> 8) == 0x060400UL || (classRev >> 16) == 0x0604UL) {
                    if (r2aBridgeCount < MAX_BRIDGES) {
                        r2a_bridge *b = &r2aBridges[r2aBridgeCount++];
                        b->bus = bus;
                        b->device = device;
                        b->function = function;
                        b->busNumbers = pciRead(bus, device, function, 0x18);
                        b->memWindow = pciRead(bus, device, function, 0x20);
                        b->prefWindow = pciRead(bus, device, function, 0x24);
                        b->prefBaseUpper = pciRead(bus, device, function, 0x28);
                        b->prefLimitUpper = pciRead(bus, device, function, 0x2c);
                        /* ctl3c: config 0x3c, bridge control in the upper 16
                         * bits, VGA forwarding = bit 19 (pcireg.h:1420-1425) */
                        sprintf(line, "bridge dev=%02x:%02x.%x bus=%08x win1c=%08x win20=%08x win24=%08x win28=%08x win2c=%08x ctl3c=%08x",
                                bus, device, function, U(b->busNumbers),
                                U(pciRead(bus, device, function, 0x1c)),
                                U(b->memWindow), U(b->prefWindow),
                                U(b->prefBaseUpper), U(b->prefLimitUpper),
                                U(pciRead(bus, device, function, 0x3c)));
                        r2aLine(line);
                    } else if (!r2aBridgeOverflow) {
                        r2aBridgeOverflow = 1;
                        r2aLine("stop reason=too-many-bridges");
                    }
                }
                if ((idWord & 0xffffUL) != ATI_VENDOR)
                    continue;
                subsys = pciRead(bus, device, function, 0x2c);
                sprintf(line, "pci dev=%02x:%02x.%x vid=%04x did=%04x rev=%02x class=%06x subsys=%04x:%04x",
                        bus, device, function, U(idWord & 0xffffUL), U((idWord >> 16) & 0xffffUL),
                        U(classRev & 0xffUL), U(classRev >> 8),
                        U(subsys & 0xffffUL), U((subsys >> 16) & 0xffffUL));
                r2aLine(line);
                if (isRV280((unsigned int)((idWord >> 16) & 0xffffUL))) {
                    if (*cardCount == 0) {
                        *cardBus = bus;
                        *cardDevice = device;
                        *cardFunction = function;
                    }
                    (*cardCount)++;
                }
            }
        }
    }
}

static void
dumpConfig(int bus, int device, int function)
{
    int off, k;
    unsigned long w[4];
    char line[160];

    for (off = 0; off < 0x40; off += 0x10) {
        for (k = 0; k < 4; k++)
            w[k] = pciRead(bus, device, function, off + 4 * k);
        sprintf(line, "cfg dev=%02x:%02x.%x off=%02x bytes=%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x",
                bus, device, function, off,
                U(w[0] & 0xff), U((w[0] >> 8) & 0xff), U((w[0] >> 16) & 0xff), U((w[0] >> 24) & 0xff),
                U(w[1] & 0xff), U((w[1] >> 8) & 0xff), U((w[1] >> 16) & 0xff), U((w[1] >> 24) & 0xff),
                U(w[2] & 0xff), U((w[2] >> 8) & 0xff), U((w[2] >> 16) & 0xff), U((w[2] >> 24) & 0xff),
                U(w[3] & 0xff), U((w[3] >> 8) & 0xff), U((w[3] >> 16) & 0xff), U((w[3] >> 24) & 0xff));
        r2aLine(line);
    }
}

/* A prefetchable window may be 64-bit (pcireg.h:1409-1412); only a window
 * wholly below 4 GiB is used. */
static int
prefWindowUsable(const r2a_bridge *b)
{
    unsigned long type = b->prefWindow & 0xfUL;

    if (type == 0UL)
        return 1;
    return type == 1UL && b->prefBaseUpper == 0UL && b->prefLimitUpper == 0UL;
}

static int
pathWindowsContain(int cardBus, unsigned long start, unsigned long length)
{
    int i, secondary, subordinate, onPath;

    if (r2aBridgeOverflow)
        return 0;
    onPath = 0;
    for (i = 0; i < r2aBridgeCount; i++) {
        secondary = (int)((r2aBridges[i].busNumbers >> 8) & 0xffUL);
        subordinate = (int)((r2aBridges[i].busNumbers >> 16) & 0xffUL);
        if (cardBus < secondary || cardBus > subordinate)
            continue;
        onPath++;
        if (!windowContains(r2aBridges[i].memWindow, start, length) &&
            !(prefWindowUsable(&r2aBridges[i]) &&
              windowContains(r2aBridges[i].prefWindow, start, length)))
            return 0;
    }
    return cardBus == 0 || onPath > 0;
}

static int
bridgesStable(void)
{
    int i;
    r2a_bridge *b;

    for (i = 0; i < r2aBridgeCount; i++) {
        b = &r2aBridges[i];
        if (pciRead(b->bus, b->device, b->function, 0x18) != b->busNumbers ||
            pciRead(b->bus, b->device, b->function, 0x20) != b->memWindow ||
            pciRead(b->bus, b->device, b->function, 0x24) != b->prefWindow ||
            pciRead(b->bus, b->device, b->function, 0x28) != b->prefBaseUpper ||
            pciRead(b->bus, b->device, b->function, 0x2c) != b->prefLimitUpper)
            return 0;
    }
    return 1;
}

/* ---- P: PLL groups ------------------------------------------------------- */

/*
 * One PLL register, with interrupts masked for the whole group.  Returns
 * WHY_NONE, or the reason it stopped.  No sleep, no log, no call other than
 * the MMIO helpers happens between splhigh and splx.  The two comparisons of
 * each check are separate if statements (cc 2.7.2.1 has miscompiled a
 * combined boolean of two comparisons at -O; that was long long, but it costs
 * nothing to avoid the form here).
 */
static int
pllGroup(vm_address_t base, int k)
{
    int s;
    int why;
    unsigned long p, c, v, d, e, a;
    unsigned long index;

    index = (unsigned long)r2aPll[k].offset & PLL_INDEX_MASK;
    c = 0;
    v = 0;
    d = 0;
    e = 0;
    a = 0;
    why = WHY_NONE;

    s = splhigh();
    p = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
    if (p & PLL_WR_EN) {
        why = WHY_BUSY;
    } else {
        rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));
        c = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
        if ((c & ~LOW_BYTE) != (p & ~LOW_BYTE))
            why = WHY_UPPER;
        if (why == WHY_NONE) {
            if ((c & LOW_BYTE) != index)
                why = WHY_LOW;
        }
        if (why == WHY_NONE) {
            v = rdnMmioRead32(base, REG_CLOCK_CNTL_DATA);
            d = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
            if (d != c)
                why = WHY_AFTER_DATA;
        }
        if (why == WHY_NONE) {
            rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(p & LOW_BYTE));
            e = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
            if (e != p)
                why = WHY_RESTORE;
        }
        if (why != WHY_NONE) {
            /* the one 32-bit store: P, read inside this masked group */
            rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, p);
            a = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
        }
    }
    splx(s);

    r2aPllRead[k].p = p;
    r2aPllRead[k].c = c;
    r2aPllRead[k].v = v;
    r2aPllRead[k].d = d;
    r2aPllRead[k].e = e;
    r2aPllRead[k].a = a;
    return why;
}

static const char *
whyName(int why)
{
    if (why == WHY_UPPER)
        return "upper";
    if (why == WHY_LOW)
        return "low";
    if (why == WHY_AFTER_DATA)
        return "after-data";
    if (why == WHY_RESTORE)
        return "restore";
    return "busy";
}

/* Returns 1 if all groups completed. */
static int
pllSnapshot(vm_address_t base)
{
    int k, done, why;
    char line[180];

    done = 0;
    why = WHY_NONE;
    for (k = 0; k < R2A_PLL_COUNT; k++) {
        why = pllGroup(base, k);
        if (why != WHY_NONE)
            break;
        done++;
    }

    /* the lines, after every hardware access */
    sprintf(line, "pllstart p0=%08x", U(r2aPllRead[0].p));
    r2aLine(line);
    for (k = 0; k < done; k++) {
        sprintf(line, "pll k=%d idx=%02x name=%s p=%08x c=%08x val=%08x d=%08x e=%08x",
                k, U(r2aPll[k].offset), r2aPll[k].name, U(r2aPllRead[k].p), U(r2aPllRead[k].c),
                U(r2aPllRead[k].v), U(r2aPllRead[k].d), U(r2aPllRead[k].e));
        r2aLine(line);
    }
    if (why == WHY_BUSY) {
        sprintf(line, "pllbusy k=%d p=%08x", done, U(r2aPllRead[done].p));
        r2aLine(line);
        r2aLine("stop reason=pll-index-busy");
    } else if (why != WHY_NONE) {
        sprintf(line, "pllabort k=%d why=%s p=%08x c=%08x d=%08x e=%08x a=%08x",
                done, whyName(why), U(r2aPllRead[done].p), U(r2aPllRead[done].c),
                U(r2aPllRead[done].d), U(r2aPllRead[done].e), U(r2aPllRead[done].a));
        r2aLine(line);
        r2aLine("stop reason=pll-index-disturbed");
    }
    sprintf(line, "pllend groups=%d", done);
    r2aLine(line);
    return done == R2A_PLL_COUNT;
}

/* ---- B: MMIO -------------------------------------------------------------- */

static void
unmapMmio(vm_address_t base)
{
    if (IOUnmapPhysicalFromIOTask(base, MMIO_MAP_LENGTH) != IO_R_SUCCESS)
        r2aLine("stop reason=unmap-failed");
}

static void
probeMmio(int bus, int device, int function)
{
    unsigned long bar, command, header, start;
    const char *type;
    int cmdMem, hdrType, wrap, inWindow, stable, ok, i, moving;
    vm_address_t base = 0;
    IOReturn r;
    unsigned long frameBefore, frameAfter;
    unsigned long liveFrame[LIVE_SAMPLES], liveVline[LIVE_SAMPLES];
    unsigned long regVal[R2A_REG_COUNT];
    char line[180];

    bar = pciRead(bus, device, function, BAR2_REG);
    command = pciRead(bus, device, function, 0x04) & 0xffffUL;
    header = pciRead(bus, device, function, 0x0c);
    hdrType = (int)((header >> 16) & 0x7fUL);
    start = bar & 0xfffffff0UL;
    if (bar & 1UL)
        type = "io";
    else if (((bar >> 1) & 3UL) == 0UL)
        type = "mem32";
    else if (((bar >> 1) & 3UL) == 2UL)
        type = "mem64";
    else
        type = "reserved";
    cmdMem = (int)((command >> 1) & 1UL);
    wrap = (start + (MMIO_MAP_LENGTH - 1UL) < start);
    inWindow = !wrap && pathWindowsContain(bus, start, MMIO_MAP_LENGTH);
    stable = pciRead(bus, device, function, BAR2_REG) == bar &&
             (pciRead(bus, device, function, 0x04) & 0xffffUL) == command &&
             pciRead(bus, device, function, 0x0c) == header &&
             bridgesStable();
    ok = (type[0] == 'm' && type[3] == '3' && start != 0UL && hdrType == 0 &&
          cmdMem && !wrap && inWindow && stable);

    if (!ok) {
        sprintf(line, "mmio bar2=%08x type=%s hdr=%02x cmdmem=%d wrap=%d inwindow=%d stable=%d map=skipped",
                U(bar), type, hdrType, cmdMem, wrap, inWindow, stable);
        r2aLine(line);
        return;
    }
    r = IOMapPhysicalIntoIOTask((unsigned)start, MMIO_MAP_LENGTH, &base);
    if (r != IO_R_SUCCESS || base == 0) {
        sprintf(line, "mmio bar2=%08x type=%s hdr=%02x cmdmem=%d wrap=%d inwindow=%d stable=%d map=fail",
                U(bar), type, hdrType, cmdMem, wrap, inWindow, stable);
        r2aLine(line);
        r2aLine("stop reason=map-failed");
        return;
    }
    sprintf(line, "mmio bar2=%08x type=%s hdr=%02x cmdmem=%d wrap=%d inwindow=%d stable=%d map=ok",
            U(bar), type, hdrType, cmdMem, wrap, inWindow, stable);
    r2aLine(line);

    /* liveness (as R1): all samples first, then the lines */
    for (i = 0; i < LIVE_SAMPLES; i++) {
        liveFrame[i] = rdnMmioRead32(base, REG_CRTC_FRAME);
        liveVline[i] = rdnMmioRead32(base, REG_CRTC_VLINE);
        if (i + 1 < LIVE_SAMPLES)
            IODelay(LIVE_GAP_US);
    }
    moving = 0;
    for (i = 0; i < LIVE_SAMPLES; i++) {
        sprintf(line, "live i=%d frame=%08x vline=%08x", i, U(liveFrame[i]), U(liveVline[i]));
        r2aLine(line);
        if (((liveVline[i] ^ liveVline[0]) & VLINE_MASK) != 0UL)
            moving = 1;
    }
    /* a static VLINE: the mapping may not decode -- no register read, and
     * above all no index store */
    if (!moving) {
        r2aLine("stop reason=vline-static");
        unmapMmio(base);
        return;
    }

    frameBefore = rdnMmioRead32(base, REG_CRTC_FRAME);
    IOSleep(FRAME_GAP_MS);
    frameAfter = rdnMmioRead32(base, REG_CRTC_FRAME);
    sprintf(line, "frame60 before=%08x after=%08x", U(frameBefore), U(frameAfter));
    r2aLine(line);

    /* registers: all reads first, then the lines (the PLL groups follow
     * the same rule) */
    for (i = 0; i < R2A_REG_COUNT; i++)
        regVal[i] = rdnMmioRead32(base, r2aRegs[i].offset);
    for (i = 0; i < R2A_REG_COUNT; i++) {
        sprintf(line, "reg name=%s off=%04x val=%08x", r2aRegs[i].name, r2aRegs[i].offset, U(regVal[i]));
        r2aLine(line);
    }

    (void)pllSnapshot(base);
    unmapMmio(base);
}

/* ---- entry ---------------------------------------------------------------- */

void
radeonR2aEntry(int runId)
{
    int bus = 0, device = 0, function = 0, count;
    char line[80];

    r2aRunId = runId;
    r2aSeq = 0;
    sprintf(line, "begin version=%d build=%08x", R2A_VERSION, U(R2A_BUILD));
    r2aLine(line);

    scanPci(&bus, &device, &function, &count);
    if (count == 1) {
        dumpConfig(bus, device, function);
        probeMmio(bus, device, function);
    } else {
        sprintf(line, "stop reason=rv280-count-%d", count);
        r2aLine(line);
    }

    /* the end line counts itself */
    sprintf(line, "end lines=%d", r2aSeq + 1);
    r2aLine(line);
}
