/*
 * RDNR1Probe.m - R1 interrogation of a PCI Radeon 9250 (RV280).
 *
 * Plan: docs/R1_INTERROGATION_PLAN.md.  Log grammar: tools/r1/parse_r1.py.
 *
 * What this file does, and all it does:
 *
 *   A  PCI configuration reads through mechanism #1.  Each read writes the
 *      host bridge's global address latch at 0xCF8 and reads 0xCFC.  No
 *      configuration register of any device is written.
 *   B  One 0x2000-byte mapping of the Radeon's BAR2, reads of named MMIO
 *      registers, unmap.  No MMIO register is written.
 *
 * It writes no PCI configuration register (no BAR sizing), no MMIO register,
 * no index register (so no PLL, VGA or attribute register is read), maps no
 * video memory and no ROM.  tools/r1/hostcheck.sh checks the object for this.
 *
 * It is a bare loadable: not an IODevice, no Auto Detect, loaded with
 * CALL/WIRE/START and never ADVERTISEd, run once, unloaded.
 *
 * Written for this project; the Matrox probe was read for the build layout
 * only (its load command runs a stage that reprograms the display).
 */

#import <driverkit/generalFuncs.h>
#import <driverkit/kernelDriver.h>
#import <driverkit/i386/ioPorts.h>
#import <stdio.h>          /* sprintf: as NeXT's QVision example driver does */

/* Every hex field is printed with %x on an (unsigned int), never with a
 * field width together with the long modifier: the kernel sprintf ignores
 * that width (target, 2026-09-15: an 8-wide long hex conversion printed
 * `303').  On i386 unsigned int and unsigned long are both 32 bits.
 * tools/r1/hostcheck.sh rejects a width with the long modifier here. */
#define U(x)                ((unsigned int)(x))

#define R1_VERSION          1

/* Provenance (PLAN section 4): tools/r1/target-build.sh passes the stamp
 * tools/r1/pack_probe.py computed (the first 32 bits of the packed tree's
 * SHA-256) as -DR1_BUILD=0x<8 hex digits>.
 * An integer, so make on the target carries it without nested quoting.
 * 0 means unstamped, and the host parser refuses such a log. */
#ifndef R1_BUILD
#define R1_BUILD            0x00000000
#endif

#define PCI_CFG_ADDR        0x0CF8
#define PCI_CFG_DATA        0x0CFC
#define PCI_MAX_BUS         8
#define PCI_MAX_DEVICE      32
#define PCI_MAX_FUNCTION    8

#define ATI_VENDOR          0x1002

#define BAR2_REG            0x18        /* radeonfbreg.h RADEON_MAPREG_MMIO */
#define MMIO_MAP_LENGTH     0x2000      /* plan section 3: max offset 0x0e40 */

#define LIVE_SAMPLES        8
#define LIVE_GAP_US         2000
#define FRAME_GAP_MS        60
#define LINE_PACE_MS        20

#define REG_CRTC_VLINE      0x0210
#define REG_CRTC_FRAME      0x0214
#define VLINE_MASK          (0x7ffUL << 16)     /* radeonfbreg.h:574 */

#define MAX_BRIDGES         16

/* Offsets: ANALYSIS.md section 12 (generated from three headers) and the
 * REGS table in tools/r1/parse_r1.py, whose self-test checks them. */
typedef struct {
    const char     *name;
    unsigned int    offset;
} r1_reg;

static const r1_reg r1Regs[] = {
    { "CLOCK_CNTL_INDEX",     0x0008 },
    { "BUS_CNTL",             0x0030 },
    { "GEN_INT_CNTL",         0x0040 },
    { "GEN_INT_STATUS",       0x0044 },
    { "CRTC_GEN_CNTL",        0x0050 },
    { "CRTC_EXT_CNTL",        0x0054 },
    { "DAC_CNTL",             0x0058 },
    { "DAC_CNTL2",            0x007c },
    { "CONFIG_MEMSIZE",       0x00f8 },
    { "CONFIG_APER_0_BASE",   0x0100 },
    { "CONFIG_APER_SIZE",     0x0108 },
    { "HOST_PATH_CNTL",       0x0130 },
    { "MC_FB_LOCATION",       0x0148 },
    { "MC_AGP_LOCATION",      0x014c },
    { "MEM_SDRAM_MODE_REG",   0x0158 },
    { "AIC_CNTL",             0x01d0 },
    { "CRTC_H_TOTAL_DISP",    0x0200 },
    { "CRTC_H_SYNC_STRT_WID", 0x0204 },
    { "CRTC_V_TOTAL_DISP",    0x0208 },
    { "CRTC_V_SYNC_STRT_WID", 0x020c },
    { "CRTC_OFFSET",          0x0224 },
    { "CRTC_PITCH",           0x022c },
    { "DISPLAY_BASE_ADDR",    0x023c },
    { "CRTC_MORE_CNTL",       0x027c },
    { "FP_GEN_CNTL",          0x0284 },
    { "GRPH_BUFFER_CNTL",     0x02f0 },
    { "CRTC2_GEN_CNTL",       0x03f8 },
    { "CP_RB_CNTL",           0x0704 },
    { "CP_RB_RPTR",           0x0710 },
    { "CP_RB_WPTR",           0x0714 },
    { "CP_CSQ_CNTL",          0x0740 },
    { "SURFACE_CNTL",         0x0b00 },
    { "DAC_MACRO_CNTL",       0x0d04 },
    { "DISP_OUTPUT_CNTL",     0x0d64 },
    { "RBBM_STATUS",          0x0e40 }
};
#define R1_REG_COUNT ((int)(sizeof(r1Regs) / sizeof(r1Regs[0])))

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
} r1_bridge;

static int          r1RunId;
static int          r1Seq;
static r1_bridge    r1Bridges[MAX_BRIDGES];
static int          r1BridgeCount;
static int          r1BridgeOverflow;   /* a bridge was not recorded */

/* ---- output ------------------------------------------------------------ */

/*
 * Every line: "RDN-R1 <runid> <kind> ... seq=<n>".  The caller supplies the
 * middle as one pre-formatted string, so the sequence number cannot be
 * forgotten on any line.  Paced so syslog does not see a burst.
 */
static void
r1Line(const char *body)
{
    IOLog("RDN-R1 %d %s seq=%d\n", r1RunId, body, r1Seq);
    r1Seq++;
    IOSleep(LINE_PACE_MS);
}

/* ---- A: PCI configuration reads ----------------------------------------- */

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
    char line[160];

    *cardCount = 0;
    r1BridgeCount = 0;
    r1BridgeOverflow = 0;
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
                    if (r1BridgeCount < MAX_BRIDGES) {
                        r1_bridge *b = &r1Bridges[r1BridgeCount++];
                        b->bus = bus;
                        b->device = device;
                        b->function = function;
                        b->busNumbers = pciRead(bus, device, function, 0x18);
                        b->memWindow = pciRead(bus, device, function, 0x20);
                        b->prefWindow = pciRead(bus, device, function, 0x24);
                        b->prefBaseUpper = pciRead(bus, device, function, 0x28);
                        b->prefLimitUpper = pciRead(bus, device, function, 0x2c);
                        sprintf(line, "bridge dev=%02x:%02x.%x bus=%08x win1c=%08x win20=%08x win24=%08x win28=%08x win2c=%08x",
                                bus, device, function, U(b->busNumbers),
                                U(pciRead(bus, device, function, 0x1c)),
                                U(b->memWindow), U(b->prefWindow),
                                U(b->prefBaseUpper), U(b->prefLimitUpper));
                        r1Line(line);
                    } else if (!r1BridgeOverflow) {
                        r1BridgeOverflow = 1;
                        r1Line("stop reason=too-many-bridges");
                    }
                }
                if ((idWord & 0xffffUL) != ATI_VENDOR)
                    continue;
                subsys = pciRead(bus, device, function, 0x2c);
                sprintf(line, "pci dev=%02x:%02x.%x vid=%04x did=%04x rev=%02x class=%06x subsys=%04x:%04x",
                        bus, device, function, U(idWord & 0xffffUL), U((idWord >> 16) & 0xffffUL),
                        U(classRev & 0xffUL), U(classRev >> 8),
                        U(subsys & 0xffffUL), U((subsys >> 16) & 0xffffUL));
                r1Line(line);
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
        /* bytes in configuration-space order: each long is little-endian */
        sprintf(line, "cfg dev=%02x:%02x.%x off=%02x bytes=%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x",
                bus, device, function, off,
                U(w[0] & 0xff), U((w[0] >> 8) & 0xff), U((w[0] >> 16) & 0xff), U((w[0] >> 24) & 0xff),
                U(w[1] & 0xff), U((w[1] >> 8) & 0xff), U((w[1] >> 16) & 0xff), U((w[1] >> 24) & 0xff),
                U(w[2] & 0xff), U((w[2] >> 8) & 0xff), U((w[2] >> 16) & 0xff), U((w[2] >> 24) & 0xff),
                U(w[3] & 0xff), U((w[3] >> 8) & 0xff), U((w[3] >> 16) & 0xff), U((w[3] >> 24) & 0xff));
        r1Line(line);
    }
}

/* A prefetchable window may be 64-bit (type bits 3-0 = 1, upper halves at
 * 0x28/0x2c: NetBSD pcireg.h:1409-1412).  Only a window wholly below 4 GiB
 * -- type 0, or type 1 with both upper halves zero -- is used; anything else
 * is treated as not containing the BAR. */
static int
prefWindowUsable(const r1_bridge *b)
{
    unsigned long type = b->prefWindow & 0xfUL;

    if (type == 0UL)
        return 1;
    return type == 1UL && b->prefBaseUpper == 0UL && b->prefLimitUpper == 0UL;
}

/* Is [start, start+length) inside a window of every bridge on the path to
 * the card's bus?  A bridge is on the path if the card's bus lies within
 * its secondary..subordinate range. */
static int
pathWindowsContain(int cardBus, unsigned long start, unsigned long length)
{
    int i, secondary, subordinate, onPath;

    /* an unrecorded bridge may be on the path: the check would be unsound */
    if (r1BridgeOverflow)
        return 0;
    onPath = 0;
    for (i = 0; i < r1BridgeCount; i++) {
        secondary = (int)((r1Bridges[i].busNumbers >> 8) & 0xffUL);
        subordinate = (int)((r1Bridges[i].busNumbers >> 16) & 0xffUL);
        if (cardBus < secondary || cardBus > subordinate)
            continue;
        onPath++;
        if (!windowContains(r1Bridges[i].memWindow, start, length) &&
            !(prefWindowUsable(&r1Bridges[i]) &&
              windowContains(r1Bridges[i].prefWindow, start, length)))
            return 0;
    }
    /* a card on bus 0 has no bridge above it; one on a higher bus must */
    return cardBus == 0 || onPath > 0;
}

/* The unlocked 0xCF8/0xCFC pairs could be interleaved with another config
 * user.  Everything the map decision rests on is read a second time; any
 * difference refuses the map. */
static int
bridgesStable(void)
{
    int i;
    r1_bridge *b;

    for (i = 0; i < r1BridgeCount; i++) {
        b = &r1Bridges[i];
        if (pciRead(b->bus, b->device, b->function, 0x18) != b->busNumbers ||
            pciRead(b->bus, b->device, b->function, 0x20) != b->memWindow ||
            pciRead(b->bus, b->device, b->function, 0x24) != b->prefWindow ||
            pciRead(b->bus, b->device, b->function, 0x28) != b->prefBaseUpper ||
            pciRead(b->bus, b->device, b->function, 0x2c) != b->prefLimitUpper)
            return 0;
    }
    return 1;
}

/* ---- B: MMIO reads -------------------------------------------------------- */

static unsigned long
mmioRead(vm_address_t base, unsigned int offset)
{
    return *(volatile unsigned long *)(base + offset);
}

static void
unmapMmio(vm_address_t base)
{
    if (IOUnmapPhysicalFromIOTask(base, MMIO_MAP_LENGTH) != IO_R_SUCCESS)
        r1Line("stop reason=unmap-failed");
}

static void
probeMmio(int bus, int device, int function)
{
    unsigned long bar, command, header, start;
    const char *type;
    int cmdMem, hdrType, wrap, inWindow, stable, ok, i, moving;
    vm_address_t base = 0;
    IOReturn r;
    unsigned long frameBefore, frameAfter, v;
    unsigned long liveFrame[LIVE_SAMPLES], liveVline[LIVE_SAMPLES];
    char line[160];

    bar = pciRead(bus, device, function, BAR2_REG);
    command = pciRead(bus, device, function, 0x04) & 0xffffUL;
    header = pciRead(bus, device, function, 0x0c);
    /* offset 0x18 is BAR2 only in a type-0 header (pcireg.h:430) */
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
    /* the mapping must not wrap past 4 GiB, whatever bus the card is on */
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
        r1Line(line);
        return;
    }
    r = IOMapPhysicalIntoIOTask((unsigned)start, MMIO_MAP_LENGTH, &base);
    if (r != IO_R_SUCCESS || base == 0) {
        sprintf(line, "mmio bar2=%08x type=%s hdr=%02x cmdmem=%d wrap=%d inwindow=%d stable=%d map=fail",
                U(bar), type, hdrType, cmdMem, wrap, inWindow, stable);
        r1Line(line);
        r1Line("stop reason=map-failed");
        return;
    }
    sprintf(line, "mmio bar2=%08x type=%s hdr=%02x cmdmem=%d wrap=%d inwindow=%d stable=%d map=ok",
            U(bar), type, hdrType, cmdMem, wrap, inWindow, stable);
    r1Line(line);

    /* Liveness: the gate is VLINE taking two or more values (plan 4-B).
     * All samples first, then the lines: r1Line sleeps LINE_PACE_MS, which
     * would stretch the 2 ms gaps to 22 ms and the window the plan's
     * arithmetic assumes (7 gaps, 14 ms). */
    for (i = 0; i < LIVE_SAMPLES; i++) {
        liveFrame[i] = mmioRead(base, REG_CRTC_FRAME);
        liveVline[i] = mmioRead(base, REG_CRTC_VLINE);
        if (i + 1 < LIVE_SAMPLES)
            IODelay(LIVE_GAP_US);
    }
    moving = 0;
    for (i = 0; i < LIVE_SAMPLES; i++) {
        sprintf(line, "live i=%d frame=%08x vline=%08x", i, U(liveFrame[i]), U(liveVline[i]));
        r1Line(line);
        if (((liveVline[i] ^ liveVline[0]) & VLINE_MASK) != 0UL)
            moving = 1;
    }
    /* A static VLINE means the mapping may not decode (cached, or the wrong
     * address): read nothing more through it (plan 4-B step 1). */
    if (!moving) {
        r1Line("stop reason=vline-static");
        unmapMmio(base);
        return;
    }

    /* FRAME over 60 ms: recorded, not a gate.  No line in between, so the
     * pacing sleep does not stretch the interval. */
    frameBefore = mmioRead(base, REG_CRTC_FRAME);
    IOSleep(FRAME_GAP_MS);
    frameAfter = mmioRead(base, REG_CRTC_FRAME);
    sprintf(line, "frame60 before=%08x after=%08x", U(frameBefore), U(frameAfter));
    r1Line(line);

    for (i = 0; i < R1_REG_COUNT; i++) {
        v = mmioRead(base, r1Regs[i].offset);
        sprintf(line, "reg name=%s off=%04x val=%08x", r1Regs[i].name, r1Regs[i].offset, U(v));
        r1Line(line);
    }

    unmapMmio(base);
}

/* ---- entry ---------------------------------------------------------------- */

void
radeonR1Entry(int runId)
{
    int bus = 0, device = 0, function = 0, count;
    char line[80];

    r1RunId = runId;
    r1Seq = 0;
    sprintf(line, "begin version=%d build=%08x", R1_VERSION, U(R1_BUILD));
    r1Line(line);

    scanPci(&bus, &device, &function, &count);
    if (count == 1) {
        dumpConfig(bus, device, function);
        probeMmio(bus, device, function);
    } else {
        sprintf(line, "stop reason=rv280-count-%d", count);
        r1Line(line);
    }

    /* the end line counts itself */
    sprintf(line, "end lines=%d", r1Seq + 1);
    r1Line(line);
}
