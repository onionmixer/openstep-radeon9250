/*
 * simworld2b0.c - a fake PCI bus, Radeon MMIO, PLL index/data pair, standard
 * VGA ports, kernel clock and spl for running OSRDNDisplay's record code
 * (osrdn_record.m, osrdn_pll.m) on the Linux host as 32-bit code.  Built and
 * driven by tools/r2b0/sim_r2b0.py.  Derived from tools/r2a/sim/simworld2a.c:
 * the PCI side, the MMIO helpers and the PLL rules are R2a's; the ports go
 * through osrdn_port.h, and the record's own calls replace the probe entry.
 *
 * This file stands in for osrdn_port.m and RDNR2aMMIO.m (neither is linked)
 * and for the class: _start probes, inits, maps the MMIO aperture itself
 * (PROT_NONE, so only the helpers can reach it) and makes the requests.
 *
 * Scenario on stdin (R2a's directives, plus):
 *   probe <rc> <bus> <dev> <fn>      what getPCIdevice: returns (default: rc 0
 *                                    and the first RV280 in the cfg directives)
 *   key no                           the instance table does not say Yes
 *   cmode <n>                        the kernel's basicConsoleMode (default 1)
 *   vga console                      the state _VGASetGraphicsMode leaves (S17)
 *   vgamisc <hex> | vga undecoded    MISC; or every VGA port reads ff
 *   vgabyte <seq|crtc|gr|attr> <i> <hex>
 *   request <runid> [<magic hex> <count>]   a setIntValues "RDNR2b0Record";
 *                                    without any, one request of runid
 *   reenter <n>                      at the n-th IOSleep of the first request,
 *                                    make a second request from inside it
 *   clockback <n> <ns>               the n-th IOGetTimestamp reads ns earlier
 *
 * Rules (a violation prints SIM-VIOLATION on stderr and exits 3):
 *   R2a's PCI, MMIO and PLL group rules; and
 *   - any hardware access after a "stop reason=" line in the same request,
 *     or in any later request (the latch)
 *   - any hardware access by a request that returned non-zero, or by a
 *     request made from inside another (reentry)
 *   - IOGetTimestamp, IOLog, IOSleep or IODelay while masked
 *   - a VGA port access while not masked; a masked section that touches both
 *     MMIO and VGA ports; PCI configuration access while masked
 *   - a VGA port read outside 0x3cc 0x3c4 0x3c5 0x3ce 0x3cf crtc crtc+1
 *     crtc+6 0x3c0 0x3c1, or of the base MISC does not select
 *   - a write to any data port; an index store other than 0..4 (SEQ), 0..0x18
 *     (CRTC), 0..8 (GR) or the index found at the start of the section; an
 *     attribute store while the flip-flop is in the data state, or of a value
 *     other than 0x30..0x34 or the original index; a 0x3c1 read of an index
 *     below 0x10 or without PAS
 *   - a VGA section that ends with an index not restored or the flip-flop in
 *     the data state
 *   - IOMapPhysicalIntoIOTask / IOUnmapPhysicalFromIOTask called at all
 *   - IODelay count inside a record's liveness window reset per record
 *
 * Target fidelity: the record's sprintf drops the field width of an `l'
 * conversion, as the OPENSTEP kernel's does.
 *
 * What this cannot show: the card, the kernel's real spl and clock, and cc
 * 2.7.2.1's code (the reloc gate covers the port and MMIO helpers).
 */

typedef unsigned int size_t;
typedef long off_t;

int printf(const char *, ...);
int fprintf(void *, const char *, ...);
int vsprintf(char *, const char *, char *);
int fflush(void *);
extern void *stderr;
void exit(int);
char *fgets(char *, int, void *);
extern void *stdin;
int sscanf(const char *, const char *, ...);
int strncmp(const char *, const char *, size_t);
int strcmp(const char *, const char *);
char *strstr(const char *, const char *);
void *mmap(void *, size_t, int, int, int, off_t);

#define PROT_NONE   0
#define MAP_PRIVATE 2
#define MAP_ANONYMOUS 0x20
#define MAP_FAILED  ((void *)-1)

#include <driverkit/generalFuncs.h>
#include "osrdn_port.h"
#include "osrdn_record.h"

#define MAX_FN      40
#define MMIO_LEN    0x2000
#define REG_INDEX   0x0008
#define REG_DATA    0x000c
#define REG_VLINE   0x0210
#define REG_FRAME   0x0214
#define LIVE_GAPS   7
#define MAX_DISTURB 8
#define MAX_REQ     8

struct fn {
    int bus, dev, fn;
    unsigned int cfg[64];
    int flipReg;
    unsigned int flipVal;
    int flipReads;
    int flipAfter;
};

struct disturb {
    int group;
    int event;          /* 0 before, 1 afterstore, 2 afterdata, 3 afterrestore */
    unsigned int value;
};

struct req {
    unsigned int runid, magic, count;
};

static struct fn fns[MAX_FN];
static int nfn;
static unsigned int latch;
static int latched;
static unsigned int regs[MMIO_LEN / 4];
static void *mapBase;
static int mapped;
static int scanDead = 1;
static double vtotal = 525.0, refreshHz = 59.94;
static double nowUs;
static unsigned long long delayUs, sleepMs;
static int delayCalls;

static unsigned int clockIndex;
static unsigned int pll[64];
static int byteLanes;
static int readback6;
static struct disturb disturbs[MAX_DISTURB];
static int ndisturb;

static int splDepth;
static int sectionKind;                 /* 0 nothing yet, 1 MMIO, 2 VGA */
static int group = -1;
static int groupFirstRead;
static unsigned int groupP;
static int storedInGroup;
static int readbackSinceStore;
static int write8Count, write32Count, dataReads;
static unsigned int expectIndex;
static int groupAnomaly;
static int stopped;                     /* a busy or aborted PLL group has ended */

/* the record as a whole */
static long hwAccess;
static int stopSeen;                    /* a stop line in this request */
static int latchWorld;                  /* a stop line in an earlier request */
static int stampCalls, clockBackCall = -1;
static unsigned long long clockBackNs;
static int sleepCalls, reenterAt = -1, reentered;
static int nested;

/* VGA */
static int vgaDecoded = 1;
static unsigned char vMisc = 0xe3;
static unsigned char vSeq[5], vCrtc[25], vGr[9], vAttr[21];
static unsigned char vSeqIdx, vCrtcIdx, vGrIdx, vAttrIdx;
static int vFlipData;
static unsigned char oSeqIdx, oCrtcIdx, oGrIdx, oAttrIdx;
static int vgaOut, vgaIn;

int basicConsoleMode = 1;

static osrdn_state st;

static void
violation(const char *what, unsigned int a, unsigned int b)
{
    fflush(0);
    fprintf(stderr, "SIM-VIOLATION %s %08x %08x\n", what, a, b);
    exit(3);
}

static void
touch(const char *what, unsigned int a)
{
    hwAccess++;
    if (stopSeen)
        violation("hardware-after-stop", a, 0);
    if (latchWorld)
        violation("hardware-after-latch", a, 0);
    if (nested)
        violation("reentered-request-touched-hardware", a, 0);
    (void)what;
}

static struct fn *
findFn(int bus, int dev, int f, int create)
{
    int i;

    for (i = 0; i < nfn; i++)
        if (fns[i].bus == bus && fns[i].dev == dev && fns[i].fn == f)
            return &fns[i];
    if (!create)
        return 0;
    if (nfn == MAX_FN)
        violation("too-many-functions", 0, 0);
    fns[nfn].bus = bus;
    fns[nfn].dev = dev;
    fns[nfn].fn = f;
    fns[nfn].flipReg = -1;
    return &fns[nfn++];
}

static void
updateScan(void)
{
    double frames, line;

    if (scanDead)
        return;
    frames = nowUs * refreshHz / 1e6;
    line = (frames - (double)(unsigned int)frames) * vtotal;
    regs[REG_VLINE / 4] = ((unsigned int)line & 0x7ff) << 16;
    regs[REG_FRAME / 4] = (unsigned int)frames;
}

static void
fireDisturb(int event)
{
    int i;

    for (i = 0; i < ndisturb; i++)
        if (disturbs[i].group == group && disturbs[i].event == event)
            clockIndex = disturbs[i].value;
}

/* ---- the kernel functions the record calls ------------------------------- */

int
sprintf(char *out, const char *format, ...)
{
    char fmt[512];
    const char *p = format;
    char *q = fmt;

    while (*p && q < fmt + sizeof fmt - 8) {
        if (*p != '%') {
            *q++ = *p++;
            continue;
        }
        {
            const char *spec = p++;
            const char *flags, *width, *len;
            int haveL = 0;

            if (*p == '%') {
                *q++ = '%';
                *q++ = *p++;
                continue;
            }
            flags = p;
            while (*p == '-' || *p == '0' || *p == '+' || *p == ' ' || *p == '#')
                p++;
            width = p;
            while (*p >= '0' && *p <= '9')
                p++;
            len = p;
            while (*p == 'l' || *p == 'h') {
                if (*p == 'l')
                    haveL = 1;
                p++;
            }
            *q++ = '%';
            if (!haveL) {
                const char *c;
                for (c = spec + 1; c < len; c++)
                    *q++ = *c;
            } else {
                const char *c;
                for (c = flags; c < width; c++)
                    if (*c != '0')
                        *q++ = *c;
            }
            {
                const char *c;
                for (c = len; c < p; c++)
                    *q++ = *c;
            }
            if (*p)
                *q++ = *p++;
        }
    }
    *q = 0;
    return vsprintf(out, fmt, (char *)(&format + 1));
}

void
IOLog(const char *format, ...)
{
    char buf[1024];

    if (splDepth)
        violation("log-while-masked", group, 0);
    vsprintf(buf, format, (char *)(&format + 1));
    printf("Sep 16 10:00:00 sim mach: %s", buf);
    if (strstr(buf, " stop reason="))
        stopSeen = 1;
    if (strstr(buf, " begin version="))
        delayCalls = 0;
}

static void
makeReentrantRequest(void);

void
IOSleep(unsigned ms)
{
    if (splDepth)
        violation("sleep-while-masked", group, ms);
    if (delayCalls > 0 && delayCalls < LIVE_GAPS)
        violation("sleep-inside-live-window", delayCalls, ms);
    sleepMs += ms;
    nowUs += ms * 1000.0;
    updateScan();
    sleepCalls++;
    if (sleepCalls == reenterAt && !reentered) {
        reentered = 1;
        makeReentrantRequest();
    }
}

void
IODelay(unsigned us)
{
    if (splDepth)
        violation("delay-while-masked", group, us);
    delayCalls++;
    delayUs += us;
    nowUs += us;
    updateScan();
}

void
IOGetTimestamp(ns_time_t *nsp)
{
    unsigned long long ns;

    if (splDepth)
        violation("timestamp-while-masked", group, 0);
    ns = (unsigned long long)(nowUs * 1000.0) + 5000000000ULL;
    if (stampCalls == clockBackCall)
        ns -= clockBackNs;
    stampCalls++;
    *nsp = ns;
}

int
splhigh(void)
{
    int old = splDepth;

    if (splDepth)
        violation("splhigh-nested", group, 0);
    splDepth = 1;
    sectionKind = 0;
    groupFirstRead = 1;
    storedInGroup = 0;
    readbackSinceStore = 0;
    return old + 100;           /* an opaque level the code must hand back */
}

int
splx(int level)
{
    if (!splDepth || level != 100)
        violation("splx", level, splDepth);
    if (sectionKind == 1 && !groupFirstRead && ((groupP & 0x80) || write32Count))
        stopped = 1;
    if (sectionKind == 2 && vgaDecoded) {
        if (vSeqIdx != oSeqIdx || vCrtcIdx != oCrtcIdx || vGrIdx != oGrIdx || vAttrIdx != oAttrIdx)
            violation("vga-index-not-restored", (unsigned)vSeqIdx << 24 | vCrtcIdx << 16 | vGrIdx << 8 | vAttrIdx,
                      (unsigned)oSeqIdx << 24 | oCrtcIdx << 16 | oGrIdx << 8 | oAttrIdx);
        if (vFlipData)
            violation("flipflop-data-state", vAttrIdx, 0);
    }
    splDepth = 0;
    return 0;
}

/* ---- PCI configuration (osrdn_outl / osrdn_inl) ---------------------------- */

void
osrdn_outl(IOEISAPortAddress port, unsigned long data)
{
    touch("outl", port);
    if (splDepth)
        violation("cfg-while-masked", port, data);
    if (port != 0x0cf8)
        violation("outl-port", port, data);
    if (!(data & 0x80000000UL) || (data & 0x7f000000UL))
        violation("outl-latch", port, data);
    latch = data;
    latched = 1;
}

unsigned long
osrdn_inl(IOEISAPortAddress port)
{
    struct fn *f;
    int bus, dev, fn, reg;

    touch("inl", port);
    if (splDepth)
        violation("cfg-while-masked", port, 0);
    if (port != 0x0cfc)
        violation("inl-port", port, 0);
    if (!latched)
        violation("inl-unlatched", port, 0);
    bus = (latch >> 16) & 0xff;
    dev = (latch >> 11) & 0x1f;
    fn = (latch >> 8) & 0x7;
    reg = latch & 0xfc;
    if (reg >= 0x40)
        violation("cfg-offset", latch, 0);
    f = findFn(bus, dev, fn, 0);
    if (!f)
        return 0xffffffffUL;
    if (f->flipReg == reg / 4 && f->flipReads++ >= f->flipAfter)
        return f->flipVal;
    return f->cfg[reg / 4];
}

/* ---- standard VGA (osrdn_inb / osrdn_outb) ------------------------------------ */

static unsigned int
crtcBase(void)
{
    return (vMisc & 1) ? 0x3d4 : 0x3b4;
}

static void
vgaSection(IOEISAPortAddress port)
{
    if (!splDepth)
        violation("vga-unmasked", port, 0);
    if (sectionKind == 1)
        violation("mixed-section", port, 0);
    if (stopped)
        violation("group-after-stop", port, 0);
    if (sectionKind == 0) {
        sectionKind = 2;
        oSeqIdx = vSeqIdx;
        oCrtcIdx = vCrtcIdx;
        oGrIdx = vGrIdx;
        oAttrIdx = vAttrIdx;
    }
}

unsigned char
osrdn_inb(IOEISAPortAddress port)
{
    unsigned int base = crtcBase();
    unsigned int other = base == 0x3d4 ? 0x3b4 : 0x3d4;

    touch("inb", port);
    vgaSection(port);
    vgaIn++;
    if (port == other || port == other + 1 || port == other + 6)
        violation("vga-wrong-base", port, vMisc);
    if (!vgaDecoded)
        return 0xff;
    if (port == 0x3cc)
        return vMisc;
    if (port == 0x3c4)
        return vSeqIdx;
    if (port == 0x3c5)
        return vSeqIdx < 5 ? vSeq[vSeqIdx] : 0;
    if (port == 0x3ce)
        return vGrIdx;
    if (port == 0x3cf)
        return vGrIdx < 9 ? vGr[vGrIdx] : 0;
    if (port == base)
        return vCrtcIdx;
    if (port == base + 1)
        return vCrtcIdx < 25 ? vCrtc[vCrtcIdx] : 0;
    if (port == base + 6) {
        vFlipData = 0;
        return 0;
    }
    if (port == 0x3c0)
        return vAttrIdx;
    if (port == 0x3c1) {
        if ((vAttrIdx & 0x1f) < 0x10)
            violation("attr-palette-read", vAttrIdx, 0);
        if (!(vAttrIdx & 0x20))
            violation("attr-read-without-pas", vAttrIdx, 0);
        return (vAttrIdx & 0x1f) < 21 ? vAttr[vAttrIdx & 0x1f] : 0;
    }
    violation("port-read-not-allowed", port, 0);
    return 0;
}

void
osrdn_outb(IOEISAPortAddress port, unsigned char data)
{
    unsigned int base = crtcBase();

    touch("outb", port);
    vgaSection(port);
    vgaOut++;
    if (!vgaDecoded)
        violation("store-to-undecoded", port, data);
    if (port == 0x3c4) {
        if (data >= 5 && data != oSeqIdx)
            violation("seq-index-value", port, data);
        vSeqIdx = data;
        return;
    }
    if (port == 0x3ce) {
        if (data >= 9 && data != oGrIdx)
            violation("gr-index-value", port, data);
        vGrIdx = data;
        return;
    }
    if (port == base) {
        if (data >= 25 && data != oCrtcIdx)
            violation("crtc-index-value", port, data);
        vCrtcIdx = data;
        return;
    }
    if (port == 0x3c0) {
        if (vFlipData)
            violation("attr-data-write", port, data);
        if (!(data >= 0x30 && data <= 0x34) && data != oAttrIdx)
            violation("attr-index-value", port, data);
        vAttrIdx = data;
        vFlipData = 1;
        return;
    }
    violation("vga-data-write", port, data);
}

/* ---- mapping is the class's, never the record's ------------------------------- */

int
IOMapPhysicalIntoIOTask(unsigned phys, unsigned length, unsigned *virt)
{
    violation("map-in-record", phys, length);
    (void)virt;
    return -1;
}

int
IOUnmapPhysicalFromIOTask(unsigned virt, unsigned length)
{
    violation("unmap-in-record", virt, length);
    return -1;
}

/* ---- the three MMIO helpers (RDNR2aMMIO.h) -------------------------------- */

static void
checkAccess(unsigned int base, unsigned int offset, int wide)
{
    touch("mmio", offset);
    if (!mapped || base != (unsigned)mapBase)
        violation("mmio-base", base, offset);
    if (offset >= MMIO_LEN)
        violation("mmio-offset", base, offset);
    if (wide && (offset & 3))
        violation("mmio-offset-align", base, offset);
    if (splDepth) {
        if (sectionKind == 2)
            violation("mixed-section", offset, 0);
        if (sectionKind == 0) {
            sectionKind = 1;
            group++;
            fireDisturb(0);
        }
    }
}

unsigned long
rdnMmioRead32(unsigned int base, unsigned int offset)
{
    unsigned int v;

    checkAccess(base, offset, 1);
    if (offset == REG_INDEX) {
        if (splDepth && stopped)
            violation("group-after-stop", group, 0);
        v = clockIndex;
        if (readback6)
            v |= 0x40;
        if (splDepth && groupFirstRead) {
            groupP = v;
            expectIndex = v;
            groupAnomaly = 0;
            groupFirstRead = 0;
        } else if (splDepth && v != expectIndex) {
            groupAnomaly = 1;
        }
        readbackSinceStore = 1;
        return v;
    }
    if (offset == REG_DATA) {
        if (!storedInGroup)
            violation("data-without-index", group, clockIndex);
        if (!readbackSinceStore)
            violation("data-before-check", group, clockIndex);
        if (groupAnomaly || (clockIndex | (readback6 ? 0x40U : 0U)) != expectIndex)
            violation("data-from-wrong-index", clockIndex, expectIndex);
        dataReads++;
        v = pll[clockIndex & 0x3f];
        fireDisturb(2);
        return v;
    }
    updateScan();
    return regs[offset / 4];
}

void
rdnMmioWrite8(unsigned int base, unsigned int offset, unsigned char value)
{
    checkAccess(base, offset, 0);
    if (offset != REG_INDEX)
        violation("write8-offset", offset, value);
    if (!splDepth)
        violation("index-store-unmasked", offset, value);
    if (stopped)
        violation("group-after-stop", group, value);
    if (value & 0x80)
        violation("write8-wr-en", offset, value);
    if ((value & 0x40) && value != (groupP & 0xff))
        violation("write8-bit6", value, groupP);
    if (groupFirstRead || (groupP & 0x80))
        violation("store-while-busy", value, groupP);
    write8Count++;
    expectIndex = (groupP & ~0xffU) | value;
    if (byteLanes)
        clockIndex = value;
    else
        clockIndex = (clockIndex & ~0xffU) | value;
    if (!storedInGroup) {
        storedInGroup = 1;
        readbackSinceStore = 0;
        fireDisturb(1);
    } else {
        readbackSinceStore = 0;
        fireDisturb(3);
    }
}

void
rdnMmioWrite32(unsigned int base, unsigned int offset, unsigned long value)
{
    checkAccess(base, offset, 1);
    if (offset != REG_INDEX)
        violation("write32-offset", offset, value);
    if (!splDepth)
        violation("write32-unmasked", offset, value);
    if (value != groupP)
        violation("write32-value", value, groupP);
    if (!groupAnomaly)
        violation("write32-no-abort", value, groupP);
    write32Count++;
    if (byteLanes != 2)
        clockIndex = value;
}

/* ---- requests ------------------------------------------------------------------ */

static IOReturn
request(unsigned int runid, unsigned int magic, unsigned int count)
{
    unsigned params[2];
    long before = hwAccess;
    IOReturn rc;
    unsigned w[OSRDN_STATE_COUNT];

    params[0] = runid;
    params[1] = magic;
    stopSeen = 0;
    rc = osrdn_record_request(&st, params, count);
    printf("SIM-REQ runid=%u rc=%d hw=%ld\n", runid, (int)rc, hwAccess - before);
    if (rc != 0 && hwAccess != before)
        violation("refused-request-touched-hardware", runid, (unsigned)(hwAccess - before));
    osrdn_state_words(&st, w);
    if (w[8] & 4U)
        violation("in-progress-left", runid, w[8]);
    if (stopSeen)
        latchWorld = 1;
    stopSeen = 0;
    return rc;
}

static void
makeReentrantRequest(void)
{
    unsigned params[2];
    long before = hwAccess;
    IOReturn rc;

    params[0] = 999001;
    params[1] = OSRDN_MAGIC;
    nested = 1;
    rc = osrdn_record_request(&st, params, 2);
    nested = 0;
    printf("SIM-REENTER rc=%d hw=%ld\n", (int)rc, hwAccess - before);
    if (rc != OSRDN_R_BUSY)
        violation("reentry-not-refused", (unsigned)rc, 0);
}

/* ---- scenario ------------------------------------------------------------- */

static void
vgaConsole(void)
{
    static const unsigned char seq[5] = { 0x03, 0x01, 0x0f, 0x00, 0x06 };
    static const unsigned char crtc[25] = {
        0x5f, 0x4f, 0x50, 0x82, 0x54, 0x80, 0x0b, 0x3e, 0x00, 0x40, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x59, 0xea, 0x8c, 0xdf, 0x28, 0x00, 0xe7, 0x04, 0xe3, 0xff };
    static const unsigned char attr[21] = {
        0x00, 0x01, 0x02, 0x03, 0x00, 0x01, 0x02, 0x03, 0x00, 0x01, 0x02, 0x03,
        0x00, 0x01, 0x02, 0x03, 0x01, 0x00, 0x03, 0x00, 0x00 };
    static const unsigned char gr[9] = { 0x00, 0x0f, 0x00, 0x00, 0x00, 0x00, 0x05, 0x0f, 0xff };
    int i;

    vMisc = 0xe3;
    for (i = 0; i < 5; i++) vSeq[i] = seq[i];
    for (i = 0; i < 25; i++) vCrtc[i] = crtc[i];
    for (i = 0; i < 21; i++) vAttr[i] = attr[i];
    for (i = 0; i < 9; i++) vGr[i] = gr[i];
    /* _VGASetGraphicsMode's last stores: GR index 8, CRTC 0x18, SEQ 1,
     * attribute 0x20 with the flip-flop left in the data state */
    vSeqIdx = 1;
    vCrtcIdx = 0x18;
    vGrIdx = 8;
    vAttrIdx = 0x20;
    vFlipData = 1;
}

__attribute__((force_align_arg_pointer))
void
_start(void)
{
    char buf[256], word[32];
    int runid = -1, bus, dev, fn, i;
    int probeRc = 0, probeBus = -1, probeDev = -1, probeFn = -1, keyYes = 1;
    unsigned int reg, val, vt, mhz, g, a, b;
    struct req reqs[MAX_REQ];
    int nreq = 0;
    unsigned w[OSRDN_STATE_COUNT];

    vgaConsole();
    while (fgets(buf, sizeof buf, stdin)) {
        if (sscanf(buf, "runid %d", &runid) == 1)
            continue;
        if (sscanf(buf, "cfg %d %d %d %x %x", &bus, &dev, &fn, &reg, &val) == 5) {
            if (reg >= 0x100 || (reg & 3))
                violation("scenario-cfg", reg, val);
            findFn(bus, dev, fn, 1)->cfg[reg / 4] = val;
            continue;
        }
        if (sscanf(buf, "mmio %x %x", &reg, &val) == 2) {
            if (reg >= MMIO_LEN || (reg & 3))
                violation("scenario-mmio", reg, val);
            regs[reg / 4] = val;
            continue;
        }
        if (sscanf(buf, "scan %u %u", &vt, &mhz) == 2) {
            scanDead = 0;
            vtotal = vt;
            refreshHz = mhz / 1000.0;
            continue;
        }
        if (strncmp(buf, "scan dead", 9) == 0) { scanDead = 1; continue; }
        if (sscanf(buf, "cfgflip %d %d %d %x %x %u", &bus, &dev, &fn, &reg, &val, &vt) == 6) {
            struct fn *f = findFn(bus, dev, fn, 0);
            if (!f || reg >= 0x100 || (reg & 3))
                violation("scenario-cfgflip", reg, val);
            f->flipReg = reg / 4;
            f->flipVal = val;
            f->flipAfter = (int)vt;
            continue;
        }
        if (sscanf(buf, "clockindex %x", &val) == 1) { clockIndex = val; continue; }
        if (sscanf(buf, "pll %x %x", &reg, &val) == 2) {
            if (reg >= 64)
                violation("scenario-pll", reg, val);
            pll[reg] = val;
            continue;
        }
        if (strncmp(buf, "bytelanes ignore-all", 20) == 0) { byteLanes = 2; continue; }
        if (strncmp(buf, "bytelanes ignore", 16) == 0) { byteLanes = 1; continue; }
        if (strncmp(buf, "readback6", 9) == 0) { readback6 = 1; continue; }
        if (sscanf(buf, "disturb %u %31s %x", &g, word, &val) == 3) {
            int ev = -1;
            if (strcmp(word, "before") == 0) ev = 0;
            if (strcmp(word, "afterstore") == 0) ev = 1;
            if (strcmp(word, "afterdata") == 0) ev = 2;
            if (strcmp(word, "afterrestore") == 0) ev = 3;
            if (ev < 0 || ndisturb == MAX_DISTURB)
                violation("scenario-disturb", g, val);
            disturbs[ndisturb].group = (int)g;
            disturbs[ndisturb].event = ev;
            disturbs[ndisturb].value = val;
            ndisturb++;
            continue;
        }
        if (sscanf(buf, "probe %d %d %d %d", &probeRc, &probeBus, &probeDev, &probeFn) == 4)
            continue;
        if (strncmp(buf, "key no", 6) == 0) { keyYes = 0; continue; }
        if (sscanf(buf, "cmode %d", &basicConsoleMode) == 1)
            continue;
        if (strncmp(buf, "vga console", 11) == 0) { vgaConsole(); continue; }
        if (strncmp(buf, "vga undecoded", 13) == 0) { vgaDecoded = 0; continue; }
        if (sscanf(buf, "vgamisc %x", &val) == 1) { vMisc = (unsigned char)val; continue; }
        if (sscanf(buf, "vgabyte %31s %u %x", word, &a, &val) == 3) {
            if (strcmp(word, "seq") == 0 && a < 5) vSeq[a] = (unsigned char)val;
            else if (strcmp(word, "crtc") == 0 && a < 25) vCrtc[a] = (unsigned char)val;
            else if (strcmp(word, "gr") == 0 && a < 9) vGr[a] = (unsigned char)val;
            else if (strcmp(word, "attr") == 0 && a < 21) vAttr[a] = (unsigned char)val;
            else violation("scenario-vgabyte", a, val);
            continue;
        }
        if (sscanf(buf, "request %u %x %u", &a, &b, &val) == 3) {
            if (nreq == MAX_REQ)
                violation("scenario-request", a, 0);
            reqs[nreq].runid = a;
            reqs[nreq].magic = b;
            reqs[nreq].count = val;
            nreq++;
            continue;
        }
        if (sscanf(buf, "request %u", &a) == 1) {
            if (nreq == MAX_REQ)
                violation("scenario-request", a, 0);
            reqs[nreq].runid = a;
            reqs[nreq].magic = (unsigned)OSRDN_MAGIC;
            reqs[nreq].count = 2;
            nreq++;
            continue;
        }
        if (sscanf(buf, "reenter %d", &reenterAt) == 1)
            continue;
        if (sscanf(buf, "clockback %d %u", &clockBackCall, &val) == 2) {
            clockBackNs = (unsigned long long)val * 1000ULL;
            continue;
        }
        if (buf[0] == '#' || buf[0] == '\n')
            continue;
        violation("scenario-syntax", 0, 0);
    }
    if (runid < 0)
        violation("scenario-no-runid", 0, 0);
    if (probeBus < 0) {
        for (i = 0; i < nfn; i++) {
            unsigned int id = fns[i].cfg[0];
            if ((id & 0xffff) == 0x1002 && (id >> 16) == 0x5960) {
                probeBus = fns[i].bus;
                probeDev = fns[i].dev;
                probeFn = fns[i].fn;
                break;
            }
        }
        if (probeBus < 0) {
            probeRc = -704;
            probeBus = probeDev = probeFn = 0xff;
        }
    }

    /* +probe:, then init as the class does it */
    printf("SIM-PROBE accept=%d\n", osrdn_probe_accept(probeRc, probeBus, probeDev, probeFn));
    /* the one-owner latch, exercised here because the class itself is not in
       this world (docs/R2B0_IMPL_PLAN.md 15-2 D): claim, refuse a second
       claim, release, claim again.  Leaves the latch free. */
    {
        int claim1 = osrdn_probe_claim();
        int claim2 = osrdn_probe_claim();
        int claim3;
        osrdn_probe_release();
        claim3 = osrdn_probe_claim();
        printf("SIM-LATCH first=%d second=%d after_release=%d\n", claim1, claim2, claim3);
        osrdn_probe_release();
    }
    osrdn_init_start(&st, 0x1234abcdUL, probeBus, probeDev, probeFn);
    st.recordEnabled = keyYes;
    if (probeRc == 0 && osrdn_init_precheck(&st)) {
        mapBase = mmap(0, MMIO_LEN, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (mapBase == MAP_FAILED)
            violation("host-mmap", 0, 0);
        mapped = 1;
        st.mmioBase = (unsigned)mapBase;
        updateScan();
    } else if (probeRc != 0) {
        st.initWhy = "no-location";
    }
    osrdn_init_line(&st);
    printf("SIM-INIT ok=%d mapped=%d\n", st.initOk, mapped);
    if (!mapped) {
        fflush(0);
        fprintf(stderr, "SIM-STATS hw=%ld sleep_ms=%llu delay_us=%llu delay_calls=%d write8=%d write32=%d "
                "groups=%d data_reads=%d final_index=%08x vga_out=%d vga_in=%d stamps=%d\n",
                hwAccess, sleepMs, delayUs, delayCalls, write8Count, write32Count, group + 1, dataReads,
                clockIndex, vgaOut, vgaIn, stampCalls);
        exit(0);
    }

    /* the window server has entered once */
    st.enterCount = 1;
    st.revertCount = 1;
    /* the class logs this on the State read the run script makes before the
     * record; the parser wants it ahead of the begin line */
    osrdn_state_words(&st, w);
    printf("Sep 16 10:00:00 sim mach: RDN-R2B0 state boot=%08x build=%08x records=%u last=%u flags=%08x "
           "cmode=%d loc=%02x:%02x.%x\n",
           w[0], w[1], w[4], w[5], w[8], st.cmode, st.bus & 0xff, st.dev & 0xff, st.fn & 0xff);
    if (nreq == 0) {
        reqs[0].runid = (unsigned)runid;
        reqs[0].magic = (unsigned)OSRDN_MAGIC;
        reqs[0].count = 2;
        nreq = 1;
    }
    for (i = 0; i < nreq; i++)
        (void)request(reqs[i].runid, reqs[i].magic, reqs[i].count);
    if (reenterAt >= 0 && !reentered)
        violation("reentry-never-made", (unsigned)reenterAt, (unsigned)sleepCalls);
    if (splDepth)
        violation("left-masked", group, 0);
    osrdn_state_words(&st, w);
    printf("RDNR2B0 state when=after nonce=%08x build=%08x enter=%u revert=%u records=%u lastrunid=%u "
           "lastresult=%u lastlines=%u flags=%08x key=%u latched=%u busy=%u cmode=%u loc=%03x\n",
           w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7], w[8],
           w[8] & 1U, (w[8] >> 1) & 1U, (w[8] >> 2) & 1U, (w[8] >> 8) & 0xffU, (w[8] >> 16) & 0xffffU);
    fflush(0);
    fprintf(stderr, "SIM-STATS hw=%ld sleep_ms=%llu delay_us=%llu delay_calls=%d write8=%d write32=%d "
            "groups=%d data_reads=%d final_index=%08x vga_out=%d vga_in=%d stamps=%d\n",
            hwAccess, sleepMs, delayUs, delayCalls, write8Count, write32Count, group + 1, dataReads,
            clockIndex, vgaOut, vgaIn, stampCalls);
    exit(0);
}
