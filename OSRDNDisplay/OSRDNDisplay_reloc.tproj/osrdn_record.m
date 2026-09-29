/*
 * osrdn_record.m - the R2b-0 record for a PCI Radeon 9250 (RV280).  Plain C.
 *
 * Plan: docs/R2B0_IMPL_PLAN.md sections 2 and 4.  Log grammar:
 * tools/r2b0/parse_r2b0.py.
 *
 * What this file does to hardware, and all it does:
 *
 *   A  PCI configuration reads through mechanism #1 (R1's code): a write of
 *      the host bridge's address latch at 0xCF8, a read of 0xCFC.  No
 *      configuration register of any device is written.  At probe one pair,
 *      at init the R2a checks without a line, at record R2a's scan with its
 *      lines.
 *   B  Reads of the MMIO map the class made at init (never a map or unmap
 *      here): liveness, the time windows, 50 registers.
 *   P  Twelve PLL groups, R2a's (osrdn_pll.m): the one-byte index store and
 *      its restore; a 32-bit store of the value read in the same masked
 *      group on the abort path only.
 *   V  Standard VGA: index port reads and stores of SEQ, CRTC and GR (each
 *      original index put back), attribute index stores of i | 0x20 for
 *      0x10..0x14 and of the original index, all under one splhigh; no data
 *      port is ever written.
 *
 * Rules the host checks hold this file to (tools/r2b0/check_r2b0_src.py):
 * ports only through osrdn_port.h, MMIO only through RDNR2aMMIO.h, no
 * IOGetTimestamp/IOLog/IOSleep/IODelay between splhigh and splx, no 64-bit
 * division, every hex field printed as %x of an (unsigned int).
 *
 * The request (osrdn_record_request) refuses without touching hardware
 * unless: the arguments are right, the instance table said Yes, and a
 * masked test-and-set finds no record in progress, fewer than two this
 * boot, and no latch.  A record that stops (VLINE static, PLL busy or
 * disturbed, PCI changed) sets the latch: no later record touches hardware
 * this boot (PLAN.md prohibition 8).
 */

#import <driverkit/generalFuncs.h>
#import <kernserv/machine/spl.h>    /* splhigh/splx */
#import <stdio.h>                   /* sprintf */
#import "RDNR2aMMIO.h"
#import "osrdn_port.h"
#import "osrdn_pll.h"
#import "osrdn_record.h"
#import "osrdn_expect.h"

#define U(x)                ((unsigned int)(x))

#define R2B0_VERSION        2

#define PCI_CFG_ADDR        0x0CF8
#define PCI_CFG_DATA        0x0CFC
#define PCI_MAX_BUS         8
#define PCI_MAX_DEVICE      32
#define PCI_MAX_FUNCTION    8

#define ATI_VENDOR          0x1002
#define RV280_ID_WORD       0x59601002UL        /* Auto Detect IDs, device << 16 | vendor */

#define BAR0_REG            0x10
#define BAR2_REG            0x18        /* radeonfbreg.h RADEON_MAPREG_MMIO */

#define LIVE_SAMPLES        8
#define LIVE_GAP_US         2000
#define FRAME_GAP_MS        60
#define SECOND_GAP_MS       1000
#define LINE_PACE_MS        20

#define REG_CLOCK_CNTL_INDEX 0x0008
#define REG_CRTC_VLINE      0x0210
#define REG_CRTC_FRAME      0x0214
#define VLINE_MASK          (0x7ffUL << 16)     /* radeonfbreg.h:574 */

#define MAX_BRIDGES         16
#define BRIDGE_CTL_VGA      0x00080000UL        /* config 0x3c bit 19, pcireg.h 1425 */

/* standard VGA ports */
#define VGA_ATTR_INDEX      0x3c0
#define VGA_ATTR_READ       0x3c1
#define VGA_SEQ_INDEX       0x3c4
#define VGA_SEQ_DATA        0x3c5
#define VGA_MISC_READ       0x3cc
#define VGA_GR_INDEX        0x3ce
#define VGA_GR_DATA         0x3cf
#define VGA_CRTC_COLOR      0x3d4
#define VGA_CRTC_MONO       0x3b4
#define VGA_STATUS_OFFSET   6                   /* 0x3da / 0x3ba */
#define VGA_PAS             0x20
#define VGA_SEQ_COUNT       5
#define VGA_CRTC_COUNT      25
#define VGA_GR_COUNT        9
#define VGA_ATTR_FIRST      0x10
#define VGA_ATTR_COUNT      5

/* gate conditions (radeon_reg.h line numbers in docs/R2B0_IMPL_PLAN.md 4-4) */
#define PLL_DIV_SEL_MASK    0x00000300UL
#define CRTC2_EN            0x02000000UL
#define FP_FPON             0x00000001UL
#define CSQ_MODE_SHIFT      28
#define RBBM_ACTIVE         0x80000000UL
#define PPLL_REF_DIV_MASK   0x3ffUL
#define PPLL_CNTL_MUST_0    0x00070003UL
#define VCLK_SRC_SEL_MASK   0x3UL
#define GATE_COUNT          32

#define ELAPSED_UNMEASURED  0xfffffffeUL
#define ELAPSED_SATURATED   0xffffffffUL

/* the kernel's console mode, written by _kminit only (1 text, 2 graphic) */
extern int basicConsoleMode;

typedef struct {
    const char     *name;
    unsigned int    offset;
} osrdn_reg;

/* R2a's 50 registers, in R2a's order; tools/r2b0/parse_r2b0.py REGS must
 * equal this table. */
static const osrdn_reg osrdnRegs[] = {
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
#define OSRDN_REG_COUNT ((int)(sizeof(osrdnRegs) / sizeof(osrdnRegs[0])))

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
    unsigned long   control;        /* config 0x3c */
} osrdn_bridge;

/* R2a's BAR2 decision, and BAR0's */
typedef struct {
    unsigned long   bar, start;
    const char     *type;
    int             hdrType, cmdMem, wrap, inWindow, stable, ok;
} osrdn_barcheck;

typedef struct {
    unsigned char   misc;
    int             decoded;
    unsigned int    crtcBase;
    unsigned char   seqIndex, crtcIndex, grIndex, attrIndex;
    unsigned char   seq[VGA_SEQ_COUNT];
    unsigned char   crtc[VGA_CRTC_COUNT];
    unsigned char   gr[VGA_GR_COUNT];
    unsigned char   attr[VGA_ATTR_COUNT];
} osrdn_vga;

static unsigned int  osrdnRunId;
static int           osrdnSeq;
static osrdn_bridge  osrdnBridges[MAX_BRIDGES];
static int           osrdnBridgeCount;
static int           osrdnBridgeOverflow;
static unsigned long osrdnRegVal[OSRDN_REG_COUNT];

/* ---- output ------------------------------------------------------------ */

/* Every record line: "RDN-R2B0 <runid> <kind> ... seq=<n>", paced. */
void
osrdn_line(const char *body)
{
    IOLog("RDN-R2B0 %u %s seq=%d\n", osrdnRunId, body, osrdnSeq);
    osrdnSeq++;
    IOSleep(LINE_PACE_MS);
}

static void
hexBytes(char *text, const unsigned char *b, int n)
{
    int i;

    for (i = 0; i < n; i++)
        sprintf(text + 2 * i, "%02x", U(b[i]));
    text[2 * n] = '\0';
}

int
osrdn_name_is(const char *name, const char *want)
{
    int i;

    if (name == 0)
        return 0;
    for (i = 0; want[i] != '\0'; i++)
        if (name[i] != want[i])
            return 0;
    return name[i] == '\0';
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
    osrdn_outl((IOEISAPortAddress)PCI_CFG_ADDR, address);
    return osrdn_inl((IOEISAPortAddress)PCI_CFG_DATA);
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

/* R2a's scan.  With log 0 it writes no line (init, before nxlogd). */
static void
scanPci(int log, int *cardBus, int *cardDevice, int *cardFunction, int *cardCount)
{
    int bus, device, function, functions;
    unsigned long idWord, header, classRev, subsys;
    char line[180];

    *cardCount = 0;
    osrdnBridgeCount = 0;
    osrdnBridgeOverflow = 0;
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
                    if (osrdnBridgeCount < MAX_BRIDGES) {
                        osrdn_bridge *b = &osrdnBridges[osrdnBridgeCount++];
                        b->bus = bus;
                        b->device = device;
                        b->function = function;
                        b->busNumbers = pciRead(bus, device, function, 0x18);
                        b->memWindow = pciRead(bus, device, function, 0x20);
                        b->prefWindow = pciRead(bus, device, function, 0x24);
                        b->prefBaseUpper = pciRead(bus, device, function, 0x28);
                        b->prefLimitUpper = pciRead(bus, device, function, 0x2c);
                        b->control = pciRead(bus, device, function, 0x3c);
                        if (log) {
                            sprintf(line, "bridge dev=%02x:%02x.%x bus=%08x win1c=%08x win20=%08x win24=%08x win28=%08x win2c=%08x ctl3c=%08x",
                                    bus, device, function, U(b->busNumbers),
                                    U(pciRead(bus, device, function, 0x1c)),
                                    U(b->memWindow), U(b->prefWindow),
                                    U(b->prefBaseUpper), U(b->prefLimitUpper),
                                    U(b->control));
                            osrdn_line(line);
                        }
                    } else if (!osrdnBridgeOverflow) {
                        osrdnBridgeOverflow = 1;
                        if (log)
                            osrdn_line("stop reason=too-many-bridges");
                    }
                }
                if ((idWord & 0xffffUL) != ATI_VENDOR)
                    continue;
                if (log) {
                    subsys = pciRead(bus, device, function, 0x2c);
                    sprintf(line, "pci dev=%02x:%02x.%x vid=%04x did=%04x rev=%02x class=%06x subsys=%04x:%04x",
                            bus, device, function, U(idWord & 0xffffUL), U((idWord >> 16) & 0xffffUL),
                            U(classRev & 0xffUL), U(classRev >> 8),
                            U(subsys & 0xffffUL), U((subsys >> 16) & 0xffffUL));
                    osrdn_line(line);
                }
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
        osrdn_line(line);
    }
}

/* A prefetchable window may be 64-bit (pcireg.h:1409-1412); only a window
 * wholly below 4 GiB is used. */
static int
prefWindowUsable(const osrdn_bridge *b)
{
    unsigned long type = b->prefWindow & 0xfUL;

    if (type == 0UL)
        return 1;
    return type == 1UL && b->prefBaseUpper == 0UL && b->prefLimitUpper == 0UL;
}

static int
onPath(const osrdn_bridge *b, int cardBus)
{
    int secondary = (int)((b->busNumbers >> 8) & 0xffUL);
    int subordinate = (int)((b->busNumbers >> 16) & 0xffUL);

    if (cardBus < secondary)
        return 0;
    return cardBus <= subordinate;
}

static int
pathWindowsContain(int cardBus, unsigned long start, unsigned long length)
{
    int i, count;

    if (osrdnBridgeOverflow)
        return 0;
    count = 0;
    for (i = 0; i < osrdnBridgeCount; i++) {
        if (!onPath(&osrdnBridges[i], cardBus))
            continue;
        count++;
        if (!windowContains(osrdnBridges[i].memWindow, start, length) &&
            !(prefWindowUsable(&osrdnBridges[i]) &&
              windowContains(osrdnBridges[i].prefWindow, start, length)))
            return 0;
    }
    return cardBus == 0 || count > 0;
}

static int
bridgesStable(void)
{
    int i;
    osrdn_bridge *b;

    for (i = 0; i < osrdnBridgeCount; i++) {
        b = &osrdnBridges[i];
        if (pciRead(b->bus, b->device, b->function, 0x18) != b->busNumbers ||
            pciRead(b->bus, b->device, b->function, 0x20) != b->memWindow ||
            pciRead(b->bus, b->device, b->function, 0x24) != b->prefWindow ||
            pciRead(b->bus, b->device, b->function, 0x28) != b->prefBaseUpper ||
            pciRead(b->bus, b->device, b->function, 0x2c) != b->prefLimitUpper)
            return 0;
    }
    return 1;
}

/* R2a's checks of one memory BAR for a mapping of length bytes. */
static void
checkBar(int bus, int device, int function, int reg, unsigned long length, osrdn_barcheck *c)
{
    unsigned long command, header;

    c->bar = pciRead(bus, device, function, reg);
    command = pciRead(bus, device, function, 0x04) & 0xffffUL;
    header = pciRead(bus, device, function, 0x0c);
    c->hdrType = (int)((header >> 16) & 0x7fUL);
    c->start = c->bar & 0xfffffff0UL;
    if (c->bar & 1UL)
        c->type = "io";
    else if (((c->bar >> 1) & 3UL) == 0UL)
        c->type = "mem32";
    else if (((c->bar >> 1) & 3UL) == 2UL)
        c->type = "mem64";
    else
        c->type = "reserved";
    c->cmdMem = (int)((command >> 1) & 1UL);
    c->wrap = (c->start + (length - 1UL) < c->start);
    c->inWindow = !c->wrap && pathWindowsContain(bus, c->start, length);
    c->stable = pciRead(bus, device, function, reg) == c->bar &&
                (pciRead(bus, device, function, 0x04) & 0xffffUL) == command &&
                pciRead(bus, device, function, 0x0c) == header &&
                bridgesStable();
    c->ok = (c->type[0] == 'm' && c->type[3] == '3' && c->start != 0UL && c->hdrType == 0 &&
             c->cmdMem && !c->wrap && c->inWindow && c->stable);
}

/* ---- probe and init ------------------------------------------------------- */

int
osrdn_probe_accept(int rc, int bus, int dev, int fn)
{
    unsigned long idWord = 0xffffffffUL;
    int accept = 0;

    if (rc == 0) {
        idWord = pciRead(bus, dev, fn, 0x00);
        if (idWord == RV280_ID_WORD)
            accept = 1;
    }
    IOLog("RDN-R2B0 probe rc=%d loc=%02x:%02x.%x id=%08x %s\n",
          rc, U(bus & 0xff), U(dev & 0xff), U(fn & 0xff), U(idWord), accept ? "accept" : "decline");
    return accept;
}

/* One display owner per boot.
 *
 * driverLoader opens Instance0.table, Instance1.table, ... and probes each one
 * (the machine's own binary, build/r2b0/driverLoader.bin: the loop at
 * 0x37d4-0x380f; and at 0x3bf4-0x3c54 a MISSING instance 0 falls back to the
 * bundle's Default.table and still configures a device), so a bundle left with
 * a surplus instance table binds this one card twice.  Two instances would
 * interleave osrdnRunId and osrdnSeq above and the parser could not reassemble
 * the run.  That loop is serial, so a plain flag is enough -- no spl is taken
 * here.  The claim is released when the superclass probe fails, so a later
 * instance can still become the owner.
 */
static int osrdnProbeHeld;

int
osrdn_probe_claim(void)
{
    int held = osrdnProbeHeld;

    if (!held)
        osrdnProbeHeld = 1;
    IOLog("RDN-R2B0 claim held=%d result=%s\n", held, held ? "refuse" : "claim");
    return held ? 0 : 1;
}

void
osrdn_probe_release(void)
{
    osrdnProbeHeld = 0;
    IOLog("RDN-R2B0 claim held=0 result=release\n");
}

void
osrdn_init_start(osrdn_state *st, unsigned long build, int bus, int dev, int fn)
{
    ns_time_t t;

    /* every field, by name (no library call) */
    IOGetTimestamp(&t);
    st->nonce = (unsigned long)t;
    st->build = build;
    st->enterCount = 0;
    st->revertCount = 0;
    st->bus = bus;
    st->dev = dev;
    st->fn = fn;
    st->initOk = 0;
    st->initWhy = "not-checked";
    st->bar0 = 0;
    st->bar2 = 0;
    st->mmioBase = 0;
    st->recordEnabled = 0;
    st->cmode = basicConsoleMode;
    st->inProgress = 0;
    st->latched = 0;
    st->bootRecords = 0;
    st->lastRunid = 0;
    st->lastResult = OSRDN_RESULT_NONE;
    st->lastLines = 0;
}

/* Config reads only; no line and no sleep (it runs before nxlogd). */
int
osrdn_init_precheck(osrdn_state *st)
{
    int bus = 0, device = 0, function = 0, count;
    osrdn_barcheck c0, c2;

    scanPci(0, &bus, &device, &function, &count);
    if (count != 1) {
        st->initWhy = "rv280-count";
        return 0;
    }
    if (bus != st->bus || device != st->dev || function != st->fn) {
        st->initWhy = "location";
        return 0;
    }
    checkBar(bus, device, function, BAR2_REG, OSRDN_MMIO_LENGTH, &c2);
    if (!c2.ok) {
        st->initWhy = "bar2";
        return 0;
    }
    checkBar(bus, device, function, BAR0_REG, OSRDN_FB_LENGTH, &c0);
    if (!c0.ok) {
        st->initWhy = "bar0";
        return 0;
    }
    st->bar0 = c0.start;
    st->bar2 = c2.start;
    st->initOk = 1;
    st->initWhy = "ok";
    return 1;
}

int
osrdn_fb_reach_ok(const osrdn_state *st, unsigned long length)
{
    if (!st->initOk || length == 0UL)
        return 0;
    if (st->bar0 + (length - 1UL) < st->bar0)
        return 0;                       /* wraps */
    return pathWindowsContain(st->bus, st->bar0, length);
}

void
osrdn_init_line(const osrdn_state *st)
{
    IOLog("RDN-R2B0 init boot=%08x build=%08x loc=%02x:%02x.%x key=%s cmode=%d bar0=%08x bar2=%08x %s%s\n",
          U(st->nonce), U(st->build), U(st->bus & 0xff), U(st->dev & 0xff), U(st->fn & 0xff),
          st->recordEnabled ? "yes" : "no", st->cmode, U(st->bar0), U(st->bar2),
          (st->initOk && st->mmioBase != 0) ? "ok" : "abort=", (st->initOk && st->mmioBase != 0) ? "" : st->initWhy);
}

/* ---- time ------------------------------------------------------------------ */

/*
 * Elapsed microseconds between two IOGetTimestamp readings, as the AC97
 * driver's ich_elapsedUs: never a 64-bit division (the kernel has no
 * __udivdi3), and a clock that went back or did not move is "unmeasured",
 * not zero.  The two comparisons are separate statements (cc 2.7.2.1 has
 * miscompiled a combined boolean of two long long comparisons at -O).
 */
static unsigned long
elapsedUs(ns_time_t t0, ns_time_t t1)
{
    ns_time_t d;

    if (t1 <= t0)
        return ELAPSED_UNMEASURED;
    d = t1 - t0;
    if (d > 0xffffffffULL)
        return ELAPSED_SATURATED;
    return (unsigned long)((unsigned int)d / 1000U);
}

static void
elapsedText(char *text, unsigned long us)
{
    if (us == ELAPSED_UNMEASURED)
        sprintf(text, "unm");
    else if (us == ELAPSED_SATURATED)
        sprintf(text, "sat");
    else
        sprintf(text, "%u", U(us));
}

/* ---- V: standard VGA --------------------------------------------------------- */

/* All of it under one splhigh: the kernel console's timer writes GR and SEQ
 * index 2 without a lock (docs/R2B0_IMPL_PLAN.md S30).  No line, no sleep, no
 * clock read inside. */
static void
vgaSnapshot(osrdn_vga *v)
{
    int s, i;
    unsigned int crtcBase, statusPort;

    v->misc = 0;
    v->decoded = 0;
    v->crtcBase = 0;
    v->seqIndex = 0;
    v->crtcIndex = 0;
    v->grIndex = 0;
    v->attrIndex = 0;
    for (i = 0; i < VGA_SEQ_COUNT; i++)
        v->seq[i] = 0;
    for (i = 0; i < VGA_CRTC_COUNT; i++)
        v->crtc[i] = 0;
    for (i = 0; i < VGA_GR_COUNT; i++)
        v->gr[i] = 0;
    for (i = 0; i < VGA_ATTR_COUNT; i++)
        v->attr[i] = 0;

    s = splhigh();
    v->misc = osrdn_inb((IOEISAPortAddress)VGA_MISC_READ);
    v->decoded = (v->misc != 0xff);
    v->crtcBase = 0;
    if (v->decoded) {
        crtcBase = (v->misc & 1) ? VGA_CRTC_COLOR : VGA_CRTC_MONO;
        statusPort = crtcBase + VGA_STATUS_OFFSET;
        v->crtcBase = crtcBase;

        v->seqIndex = osrdn_inb((IOEISAPortAddress)VGA_SEQ_INDEX);
        for (i = 0; i < VGA_SEQ_COUNT; i++) {
            osrdn_outb((IOEISAPortAddress)VGA_SEQ_INDEX, (unsigned char)i);
            v->seq[i] = osrdn_inb((IOEISAPortAddress)VGA_SEQ_DATA);
        }
        osrdn_outb((IOEISAPortAddress)VGA_SEQ_INDEX, v->seqIndex);

        v->crtcIndex = osrdn_inb((IOEISAPortAddress)crtcBase);
        for (i = 0; i < VGA_CRTC_COUNT; i++) {
            osrdn_outb((IOEISAPortAddress)crtcBase, (unsigned char)i);
            v->crtc[i] = osrdn_inb((IOEISAPortAddress)(crtcBase + 1));
        }
        osrdn_outb((IOEISAPortAddress)crtcBase, v->crtcIndex);

        v->grIndex = osrdn_inb((IOEISAPortAddress)VGA_GR_INDEX);
        for (i = 0; i < VGA_GR_COUNT; i++) {
            osrdn_outb((IOEISAPortAddress)VGA_GR_INDEX, (unsigned char)i);
            v->gr[i] = osrdn_inb((IOEISAPortAddress)VGA_GR_DATA);
        }
        osrdn_outb((IOEISAPortAddress)VGA_GR_INDEX, v->grIndex);

        /* attribute controller: reset the flip-flop before every index store */
        (void)osrdn_inb((IOEISAPortAddress)statusPort);
        v->attrIndex = osrdn_inb((IOEISAPortAddress)VGA_ATTR_INDEX);
        for (i = 0; i < VGA_ATTR_COUNT; i++) {
            (void)osrdn_inb((IOEISAPortAddress)statusPort);
            osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, (unsigned char)((VGA_ATTR_FIRST + i) | VGA_PAS));
            v->attr[i] = osrdn_inb((IOEISAPortAddress)VGA_ATTR_READ);
        }
        (void)osrdn_inb((IOEISAPortAddress)statusPort);
        osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, v->attrIndex);
        (void)osrdn_inb((IOEISAPortAddress)statusPort);
    }
    splx(s);
}

static void
vgaLines(const osrdn_vga *v)
{
    char line[200];
    char seq[2 * VGA_SEQ_COUNT + 1], crtc[2 * VGA_CRTC_COUNT + 1];
    char gr[2 * VGA_GR_COUNT + 1], attr[2 * VGA_ATTR_COUNT + 1];

    hexBytes(seq, v->seq, VGA_SEQ_COUNT);
    hexBytes(crtc, v->crtc, VGA_CRTC_COUNT);
    hexBytes(gr, v->gr, VGA_GR_COUNT);
    hexBytes(attr, v->attr, VGA_ATTR_COUNT);
    sprintf(line, "vga part=1 misc=%02x dec=%d base=%03x sqi=%02x sq=%s crtci=%02x crtc=%s",
            U(v->misc), v->decoded, U(v->crtcBase), U(v->seqIndex), seq, U(v->crtcIndex), crtc);
    osrdn_line(line);
    sprintf(line, "vga part=2 gri=%02x gr=%s attri=%02x attr=%s",
            U(v->grIndex), gr, U(v->attrIndex), attr);
    osrdn_line(line);
}

/* ---- gates -------------------------------------------------------------------- */

static unsigned long
regValue(unsigned int offset)
{
    int i;

    for (i = 0; i < OSRDN_REG_COUNT; i++)
        if (osrdnRegs[i].offset == offset)
            return osrdnRegVal[i];
    return 0xffffffffUL;
}

/* pass: 1, 0, or -1 for "not evaluated" */
static void
gateLine(int step, const char *name, unsigned long val, unsigned long want, int pass, int *refused)
{
    char line[120];

    sprintf(line, "gate step=%d name=%s val=%08x want=%08x pass=%s",
            step, name, U(val), U(want), pass > 0 ? "1" : (pass == 0 ? "0" : "na"));
    osrdn_line(line);
    if (pass != 1)
        (*refused)++;
}

static int
gateEqual(int step, const char *name, unsigned long val, unsigned long want, int *refused)
{
    gateLine(step, name, val, want, val == want, refused);
    return val == want;
}

/* Returns the number of gates that did not pass. */
static int
gateEvaluate(const osrdn_state *st, int cardBus, int pllComplete, unsigned long p0, unsigned long indexEnd)
{
    int refused = 0;
    int i, count;
    unsigned long v, all;
    char line[80];

    /* step 0 */
    gateEqual(0, "aper0", regValue(0x0100), st->bar0, &refused);
    v = regValue(0x0108);
    gateLine(0, "apersize", v, OSRDN_FB_LENGTH, v >= OSRDN_FB_LENGTH, &refused);
    v = regValue(0x00f8);
    gateLine(0, "memsize", v, OSRDN_FB_LENGTH, v >= OSRDN_FB_LENGTH, &refused);
    gateEqual(0, "displaybase", regValue(0x023c), (regValue(0x0148) & 0xffffUL) << 16, &refused);
    for (i = 0; i < OSRDN_EXPECT_R1_COUNT; i++)
        gateEqual(0, osrdnExpectR1[i].gate, regValue(osrdnExpectR1[i].offset), osrdnExpectR1[i].want, &refused);
    gateEqual(0, "divsel", regValue(REG_CLOCK_CNTL_INDEX) & PLL_DIV_SEL_MASK, PLL_DIV_SEL_MASK, &refused);
    gateEqual(0, "crtc2", regValue(0x03f8) & CRTC2_EN, 0, &refused);
    gateEqual(0, "fpon", regValue(0x0284) & FP_FPON, 0, &refused);
    gateEqual(0, "cpmode", regValue(0x0740) >> CSQ_MODE_SHIFT, 0, &refused);
    gateEqual(0, "rbbm", regValue(0x0e40) & RBBM_ACTIVE, 0, &refused);
    for (i = 0; i < OSRDN_EXPECT_R2A_COUNT; i++)
        gateEqual(0, osrdnExpectR2a[i].gate, regValue(osrdnExpectR2a[i].offset), osrdnExpectR2a[i].want, &refused);
    all = 0xffffffffUL;
    count = 0;
    for (i = 0; i < osrdnBridgeCount; i++) {
        if (!onPath(&osrdnBridges[i], cardBus))
            continue;
        count++;
        all &= osrdnBridges[i].control;
    }
    if (count == 0)
        all = 0;
    gateLine(0, "bridgevga", all & BRIDGE_CTL_VGA, BRIDGE_CTL_VGA, (all & BRIDGE_CTL_VGA) != 0UL, &refused);

    /* step 1 */
    if (pllComplete) {
        v = r2aPllRead[1].v & PPLL_REF_DIV_MASK;
        gateLine(1, "refdiv", v, 6, v == 6UL || v == 12UL, &refused);
        gateEqual(1, "ppllcntl", r2aPllRead[0].v & PPLL_CNTL_MUST_0, 0, &refused);
        gateEqual(1, "vclksrc", r2aPllRead[4].v & VCLK_SRC_SEL_MASK, VCLK_SRC_SEL_MASK, &refused);
        gateEqual(1, "indexend", indexEnd, p0, &refused);
    } else {
        gateLine(1, "refdiv", 0, 6, -1, &refused);
        gateLine(1, "ppllcntl", 0, 0, -1, &refused);
        gateLine(1, "vclksrc", 0, VCLK_SRC_SEL_MASK, -1, &refused);
        gateLine(1, "indexend", 0, p0, -1, &refused);
    }
    sprintf(line, "verdict gates=%d refused=%d result=%s", GATE_COUNT, refused, refused ? "refuse" : "enter");
    osrdn_line(line);
    return refused;
}

/* ---- the record ------------------------------------------------------------------ */

static unsigned long
recordRun(osrdn_state *st)
{
    int bus = 0, device = 0, function = 0, count, i, moving, pllComplete, done, why;
    vm_address_t base = st->mmioBase;
    osrdn_barcheck c2;
    unsigned long liveFrame[LIVE_SAMPLES], liveVline[LIVE_SAMPLES];
    unsigned long delayUs[LIVE_SAMPLES - 1];
    unsigned long frameBefore, frameAfter, secondBefore, secondAfter, us60, us1000, p0, indexEnd;
    ns_time_t ta, tb;
    osrdn_vga vga;
    char line[200], d[LIVE_SAMPLES - 1][12], s60[12], s1000[12];

    sprintf(line, "begin version=%d boot=%08x build=%08x enter=%u revert=%u cmode=%d loc=%02x:%02x.%x key=%s",
            R2B0_VERSION, U(st->nonce), U(st->build), U(st->enterCount), U(st->revertCount), st->cmode,
            U(st->bus & 0xff), U(st->dev & 0xff), U(st->fn & 0xff), st->recordEnabled ? "yes" : "no");
    osrdn_line(line);

    /* PCI, as R2a, and the card must be the one init mapped */
    scanPci(1, &bus, &device, &function, &count);
    if (count != 1) {
        sprintf(line, "stop reason=rv280-count-%d", count);
        osrdn_line(line);
        return OSRDN_RESULT_STOP;
    }
    dumpConfig(bus, device, function);
    checkBar(bus, device, function, BAR2_REG, OSRDN_MMIO_LENGTH, &c2);
    sprintf(line, "mmio bar2=%08x type=%s hdr=%02x cmdmem=%d wrap=%d inwindow=%d stable=%d map=%s",
            U(c2.bar), c2.type, c2.hdrType, c2.cmdMem, c2.wrap, c2.inWindow, c2.stable,
            c2.ok ? "ok" : "skipped");
    osrdn_line(line);
    if (bus != st->bus || device != st->dev || function != st->fn) {
        osrdn_line("stop reason=pci-location");
        return OSRDN_RESULT_STOP;
    }
    if (!c2.ok) {
        osrdn_line("stop reason=pci-bar2-check");
        return OSRDN_RESULT_STOP;
    }
    if (c2.start != st->bar2) {
        osrdn_line("stop reason=pci-bar2-changed");
        return OSRDN_RESULT_STOP;
    }

    /* liveness (as R1): all samples first, then the lines; the clock around
     * each gap */
    for (i = 0; i < LIVE_SAMPLES; i++) {
        liveFrame[i] = rdnMmioRead32(base, REG_CRTC_FRAME);
        liveVline[i] = rdnMmioRead32(base, REG_CRTC_VLINE);
        if (i + 1 < LIVE_SAMPLES) {
            IOGetTimestamp(&ta);
            IODelay(LIVE_GAP_US);
            IOGetTimestamp(&tb);
            delayUs[i] = elapsedUs(ta, tb);
        }
    }
    moving = 0;
    for (i = 0; i < LIVE_SAMPLES; i++) {
        sprintf(line, "live i=%d frame=%08x vline=%08x", i, U(liveFrame[i]), U(liveVline[i]));
        osrdn_line(line);
        if (((liveVline[i] ^ liveVline[0]) & VLINE_MASK) != 0UL)
            moving = 1;
    }
    /* a static VLINE: the mapping may not decode -- no register read, and
     * above all no index store */
    if (!moving) {
        osrdn_line("stop reason=vline-static");
        return OSRDN_RESULT_STOP;
    }

    frameBefore = rdnMmioRead32(base, REG_CRTC_FRAME);
    IOGetTimestamp(&ta);
    IOSleep(FRAME_GAP_MS);
    IOGetTimestamp(&tb);
    frameAfter = rdnMmioRead32(base, REG_CRTC_FRAME);
    us60 = elapsedUs(ta, tb);
    sprintf(line, "frame60 before=%08x after=%08x", U(frameBefore), U(frameAfter));
    osrdn_line(line);

    secondBefore = rdnMmioRead32(base, REG_CRTC_FRAME);
    IOGetTimestamp(&ta);
    IOSleep(SECOND_GAP_MS);
    IOGetTimestamp(&tb);
    secondAfter = rdnMmioRead32(base, REG_CRTC_FRAME);
    us1000 = elapsedUs(ta, tb);
    for (i = 0; i < LIVE_SAMPLES - 1; i++)
        elapsedText(d[i], delayUs[i]);
    elapsedText(s60, us60);
    elapsedText(s1000, us1000);
    sprintf(line, "time d0=%s d1=%s d2=%s d3=%s d4=%s d5=%s d6=%s s60=%s f60=%u s1000=%s f1000=%u",
            d[0], d[1], d[2], d[3], d[4], d[5], d[6], s60, U(frameAfter - frameBefore),
            s1000, U(secondAfter - secondBefore));
    osrdn_line(line);

    /* registers: all reads first, then the lines */
    for (i = 0; i < OSRDN_REG_COUNT; i++)
        osrdnRegVal[i] = rdnMmioRead32(base, osrdnRegs[i].offset);
    for (i = 0; i < OSRDN_REG_COUNT; i++) {
        sprintf(line, "reg name=%s off=%04x val=%08x", osrdnRegs[i].name, osrdnRegs[i].offset, U(osrdnRegVal[i]));
        osrdn_line(line);
    }

    /* PLL groups; a busy or disturbed index ends the hardware part here */
    pllComplete = osrdn_pll_snapshot(base, &done, &why);
    p0 = r2aPllRead[0].p;
    indexEnd = 0;
    if (pllComplete) {
        indexEnd = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
        sprintf(line, "idxend val=%08x", U(indexEnd));
        osrdn_line(line);
        vgaSnapshot(&vga);
        vgaLines(&vga);
    }

    if (gateEvaluate(st, bus, pllComplete, p0, indexEnd) != 0 || !pllComplete)
        return pllComplete ? OSRDN_RESULT_REFUSE : OSRDN_RESULT_STOP;
    return OSRDN_RESULT_ENTER;
}

IOReturn
osrdn_record_request(osrdn_state *st, const unsigned *params, unsigned count)
{
    int s;
    IOReturn verdict;
    unsigned long result;

    if (params == 0 || count != OSRDN_RECORD_COUNT)
        return OSRDN_R_INVALID;
    if ((unsigned long)params[1] != OSRDN_MAGIC)
        return OSRDN_R_INVALID;
    if (params[0] == 0 || (unsigned long)params[0] == st->lastRunid)
        return OSRDN_R_INVALID;
    if (!st->recordEnabled) {
        IOLog("RDN-R2B0 refused boot=%08x runid=%u rc=%d key=no\n", U(st->nonce), params[0], OSRDN_R_KEY_NO);
        return OSRDN_R_KEY_NO;
    }

    /* the test-and-set: compares and stores only */
    s = splhigh();
    if (st->latched) {
        verdict = OSRDN_R_LATCHED;
    } else if (!st->initOk) {
        verdict = OSRDN_R_LATCHED;
    } else if (st->mmioBase == 0) {
        verdict = OSRDN_R_LATCHED;
    } else if (st->inProgress) {
        verdict = OSRDN_R_BUSY;
    } else if (st->bootRecords >= 2) {
        verdict = OSRDN_R_BUSY;
    } else {
        st->inProgress = 1;
        st->bootRecords++;
        verdict = 0;
    }
    splx(s);

    if (verdict != 0) {
        IOLog("RDN-R2B0 refused boot=%08x runid=%u rc=%d\n", U(st->nonce), params[0], verdict);
        return verdict;
    }

    st->lastRunid = (unsigned long)params[0];
    osrdnRunId = params[0];
    osrdnSeq = 0;
    result = recordRun(st);
    if (result == OSRDN_RESULT_STOP)
        st->latched = 1;
    /* the end line counts itself */
    {
        char line[40];
        sprintf(line, "end lines=%d", osrdnSeq + 1);
        osrdn_line(line);
    }
    st->lastResult = result;
    st->lastLines = (unsigned long)osrdnSeq;
    st->inProgress = 0;
    return 0;
}

void
osrdn_state_words(const osrdn_state *st, unsigned *words)
{
    words[0] = U(st->nonce);
    words[1] = U(st->build);
    words[2] = U(st->enterCount);
    words[3] = U(st->revertCount);
    words[4] = U(st->bootRecords);
    words[5] = U(st->lastRunid);
    words[6] = U(st->lastResult);
    words[7] = U(st->lastLines);
    words[8] = U((st->recordEnabled ? 1U : 0U)
               | (st->latched ? 2U : 0U)
               | (st->inProgress ? 4U : 0U)
               | ((unsigned)(st->cmode & 0xff) << 8)
               | ((unsigned)(st->bus & 0xff) << 24)
               | ((unsigned)(st->dev & 0x1f) << 19)
               | ((unsigned)(st->fn & 0x7) << 16));
}
