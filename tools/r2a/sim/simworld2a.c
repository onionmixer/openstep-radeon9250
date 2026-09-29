/*
 * simworld2a.c - a fake PCI bus, Radeon MMIO and PLL index/data pair for
 * running RDNR2aProbe.m on the Linux host as 32-bit code.  Built and driven by
 * tools/r2a/sim_r2a.py.  Derived from tools/r1/sim/simworld.c (the PCI side
 * and the kernel functions are the same; the MMIO side is new).
 *
 * The probe reaches MMIO only through RDNR2aMMIO.h.  This file implements
 * those three functions; the real RDNR2aMMIO.m is not linked.  The mapping
 * IOMapPhysicalIntoIOTask hands back is PROT_NONE: a probe that dereferenced
 * the base itself would fault, so every access must come through the helpers,
 * where the rules below are enforced.
 *
 * Scenario on stdin, one directive per line (R1's, plus):
 *   runid <decimal>
 *   cfg <bus> <dev> <fn> <reg hex> <value hex>
 *   mmio <off hex> <value hex>
 *   scan <vtotal> <refresh millihertz> | scan dead
 *   mapfail | unmapfail
 *   cfgflip <bus> <dev> <fn> <reg hex> <value hex> <n>
 *   clockindex <hex>                 CLOCK_CNTL_INDEX at the start
 *   pll <index hex> <value hex>      a PLL register
 *   bytelanes ignore                 an 8-bit store replaces the whole register
 *   bytelanes ignore-all             ... and a 32-bit store does nothing
 *   readback6                        index reads show bit 6 set
 *   disturb <group> <event> <hex>    another writer sets CLOCK_CNTL_INDEX to
 *                                    <hex> in group <group> (counted from 0 at
 *                                    each splhigh) at <event>: before (at the
 *                                    splhigh, ahead of the probe's first read),
 *                                    afterstore, afterdata, afterrestore
 *
 * Rules (a violation prints SIM-VIOLATION on stderr and exits 3):
 *   R1's PCI and mapping rules; and
 *   - a helper access with a base other than the live mapping, after unmap,
 *     at an offset >= 0x2000, or (32-bit) not a multiple of 4
 *   - an 8-bit store anywhere but offset 0x08, with bit 7 (write enable), or
 *     with bit 6 unless it restores the group's first read
 *   - a 32-bit store anywhere but offset 0x08, or of a value other than the
 *     group's first read of 0x08
 *   - any store while interrupts are not masked
 *   - a 32-bit store in a group where every index read so far showed what a
 *     clean store gives (no abort condition), or any store in a group whose
 *     first read had write enable set
 *   - a CLOCK_CNTL_DATA read without an index read since the last index store,
 *     with no index store in the group, or while the index is not what the
 *     group's last store would give on an undisturbed register
 *   - a group started after a busy or aborted group
 *   - IOSleep, IODelay or IOLog while masked; splx with a wrong level; exit
 *     while masked or mapped
 *
 * Target fidelity: the probe's sprintf drops the field width of an `l'
 * conversion, as the OPENSTEP kernel's does.
 *
 * What this cannot show: how RV280 latches PLL_WR_EN, whether it honours byte
 * lanes, what its reads change, and cc 2.7.2.1's code.
 */

typedef unsigned int size_t;
typedef long off_t;

int printf(const char *, ...);
int fprintf(void *, const char *, ...);
int vprintf(const char *, char *);
int vsprintf(char *, const char *, char *);
int fflush(void *);
extern void *stderr;
void exit(int);
char *fgets(char *, int, void *);
extern void *stdin;
int sscanf(const char *, const char *, ...);
int strncmp(const char *, const char *, size_t);
int strcmp(const char *, const char *);
void *mmap(void *, size_t, int, int, int, off_t);
int munmap(void *, size_t);

#define PROT_NONE   0
#define MAP_PRIVATE 2
#define MAP_ANONYMOUS 0x20
#define MAP_FAILED  ((void *)-1)

void radeonR2aEntry(int runId);

#define MAX_FN      32
#define MMIO_LEN    0x2000
#define REG_INDEX   0x0008
#define REG_DATA    0x000c
#define REG_VLINE   0x0210
#define REG_FRAME   0x0214
#define LIVE_GAPS   7
#define MAX_DISTURB 8

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

static struct fn fns[MAX_FN];
static int nfn;
static unsigned int latch;
static int latched;
static unsigned int regs[MMIO_LEN / 4];
static void *mapBase;
static int mapped, mapCount, mapFail, unmapFail;
static unsigned int mapPhys;
static int scanDead = 1;
static double vtotal = 525.0, refreshHz = 59.94;
static double nowUs;
static unsigned long long delayUs, sleepMs;
static int delayCalls;

static unsigned int clockIndex;
static unsigned int pll[64];
static int byteLanes;           /* 0 honoured, 1 ignored, 2 ignored and 32-bit ignored */
static int readback6;
static struct disturb disturbs[MAX_DISTURB];
static int ndisturb;

static int splDepth;
static int group = -1;
static int groupFirstRead;
static unsigned int groupP;
static int storedInGroup;
static int readbackSinceStore;
static int write8Count, write32Count, dataReads;
static unsigned int expectIndex;        /* what an undisturbed register reads now */
static int groupAnomaly;                /* an index read in this group differed from it */
static int stopped;                     /* a busy or aborted group has ended */

static void
violation(const char *what, unsigned int a, unsigned int b)
{
    fflush(0);
    fprintf(stderr, "SIM-VIOLATION %s %08x %08x\n", what, a, b);
    exit(3);
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

/* ---- the kernel functions the probe calls ------------------------------- */

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
    if (splDepth)
        violation("log-while-masked", group, 0);
    printf("Sep 15 10:00:00 sim mach: ");
    vprintf(format, (char *)(&format + 1));
}

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

int
splhigh(void)
{
    int old = splDepth;

    if (splDepth)
        violation("splhigh-nested", group, 0);
    if (stopped)
        violation("group-after-stop", group, 0);
    splDepth = 1;
    group++;
    groupFirstRead = 1;
    storedInGroup = 0;
    readbackSinceStore = 0;
    fireDisturb(0);
    return old + 100;           /* an opaque level the probe must hand back */
}

int
splx(int level)
{
    if (!splDepth || level != 100)
        violation("splx", level, splDepth);
    splDepth = 0;
    if (!groupFirstRead && ((groupP & 0x80) || write32Count))
        stopped = 1;
    return 0;
}

typedef unsigned short IOEISAPortAddress;

unsigned char inb(IOEISAPortAddress p) { violation("inb", p, 0); return 0; }
unsigned short inw(IOEISAPortAddress p) { violation("inw", p, 0); return 0; }
void outb(IOEISAPortAddress p, unsigned char d) { violation("outb", p, d); }
void outw(IOEISAPortAddress p, unsigned short d) { violation("outw", p, d); }

void
outl(IOEISAPortAddress port, unsigned long data)
{
    if (port != 0x0cf8)
        violation("outl-port", port, data);
    if (!(data & 0x80000000UL) || (data & 0x7f000000UL))
        violation("outl-latch", port, data);
    latch = data;
    latched = 1;
}

unsigned long
inl(IOEISAPortAddress port)
{
    struct fn *f;
    int bus, dev, fn, reg;

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

int
IOMapPhysicalIntoIOTask(unsigned phys, unsigned length, unsigned *virt)
{
    int i, ok = 0;

    mapCount++;
    if (mapCount > 1)
        violation("second-map", phys, length);
    if (length != MMIO_LEN)
        violation("map-length", phys, length);
    for (i = 0; i < nfn; i++) {
        unsigned int did = fns[i].cfg[0] >> 16;
        if ((fns[i].cfg[0] & 0xffff) == 0x1002 &&
            (did == 0x5960 || did == 0x5961 || did == 0x5962 || did == 0x5963 ||
             did == 0x5964 || did == 0x5965 || did == 0x5c61 || did == 0x5c63) &&
            ((fns[i].cfg[0x0c / 4] >> 16) & 0x7f) == 0 &&
            (fns[i].cfg[0x18 / 4] & 0xfffffff0U) == phys && phys != 0)
            ok = 1;
    }
    if (!ok)
        violation("map-not-a-bar2", phys, length);
    if (mapFail)
        return -1;
    /* no access at all: only the helpers below may touch MMIO */
    mapBase = mmap(0, MMIO_LEN, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (mapBase == MAP_FAILED)
        violation("host-mmap", 0, 0);
    updateScan();
    mapped = 1;
    mapPhys = phys;
    *virt = (unsigned)mapBase;
    return 0;
}

int
IOUnmapPhysicalFromIOTask(unsigned virt, unsigned length)
{
    if (!mapped || virt != (unsigned)mapBase || length != MMIO_LEN)
        violation("unmap", virt, length);
    mapped = 0;
    return unmapFail ? -1 : 0;
}

/* ---- the three MMIO helpers (RDNR2aMMIO.h) -------------------------------- */

static void
checkAccess(unsigned int base, unsigned int offset, int wide)
{
    if (!mapped || base != (unsigned)mapBase)
        violation("mmio-base", base, offset);
    if (offset >= MMIO_LEN)
        violation("mmio-offset", base, offset);
    if (wide && (offset & 3))
        violation("mmio-offset-align", base, offset);
}

unsigned long
rdnMmioRead32(unsigned int base, unsigned int offset)
{
    unsigned int v;

    checkAccess(base, offset, 1);
    if (offset == REG_INDEX) {
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

/* ---- scenario ------------------------------------------------------------- */

__attribute__((force_align_arg_pointer))
void
_start(void)
{
    char buf[256], word[32];
    int runid = -1, bus, dev, fn;
    unsigned int reg, val, vt, mhz, g;

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
        if (strncmp(buf, "mapfail", 7) == 0) { mapFail = 1; continue; }
        if (strncmp(buf, "unmapfail", 9) == 0) { unmapFail = 1; continue; }
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
        if (buf[0] == '#' || buf[0] == '\n')
            continue;
        violation("scenario-syntax", 0, 0);
    }
    if (runid < 0)
        violation("scenario-no-runid", 0, 0);
    radeonR2aEntry(runid);
    if (mapped)
        violation("left-mapped", mapPhys, 0);
    if (splDepth)
        violation("left-masked", group, 0);
    fflush(0);
    fprintf(stderr, "SIM-STATS maps=%d sleep_ms=%llu delay_us=%llu delay_calls=%d write8=%d write32=%d "
            "groups=%d data_reads=%d final_index=%08x\n",
            mapCount, sleepMs, delayUs, delayCalls, write8Count, write32Count, group + 1, dataReads, clockIndex);
    exit(0);
}
