/*
 * simworld.c - a fake PCI bus and Radeon MMIO for running RDNR1Probe.m on
 * the Linux host as 32-bit code.  Built and driven by tools/r1/sim_r1.py.
 *
 * The 32-bit host libc is installed without headers or crt files, so this
 * file declares what it uses and supplies _start itself.
 *
 * Scenario on stdin, one directive per line:
 *   runid <decimal>
 *   cfg <bus> <dev> <fn> <reg hex> <value hex>   32-bit word; a function
 *                                                 exists once any word is set
 *   mmio <off hex> <value hex>                    32-bit register word
 *   scan <vtotal> <refresh millihertz>            VLINE and FRAME advance with
 *                                                 simulated time
 *   scan dead                                     VLINE and FRAME never change
 *   mapfail                                       IOMapPhysicalIntoIOTask fails
 *   unmapfail                                     IOUnmapPhysicalFromIOTask fails
 *   cfgflip <bus> <dev> <fn> <reg hex> <value hex> <n>  after n reads of
 *                                                 that word it reads as value
 *                                                 (another config user racing)
 *
 * Simulated time advances only in IOSleep and IODelay.
 *
 * What the fake world enforces (a violation prints SIM-VIOLATION on stderr
 * and the process exits 3, so a probe that breaks a rule cannot produce a
 * log at all):
 *   - no outb/outw/inb/inw; outl only to 0xCF8 with bit 31 set and bits
 *     24-30 clear; inl only from 0xCFC and only after such a latch
 *   - configuration reads only at offsets below 0x40
 *   - at most one mapping, exactly 0x2000 bytes at the BAR2 base of an ATI
 *     RV280 function with a type-0 header,
 *     unmapped with the same address and length before exit
 *   - the probe's view of MMIO is a read-only mapping: a write faults
 *   - the liveness window is IODelay-only: no IOSleep between the first and
 *     the last of the LIVE_GAPS delays (plan R1 4-B: 7 gaps of 2 ms = 14 ms)
 *
 * Target fidelity: the probe's sprintf is this file's, not glibc's.  The
 * OPENSTEP kernel sprintf ignores the field width of a conversion that has
 * the `l' modifier (measured 2026-09-15: `%08lx' printed `303', `%04x'
 * printed `0008'), so the width and zero flag are dropped from those
 * conversions before glibc formats the string.
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
void *mmap(void *, size_t, int, int, int, off_t);
int memfd_create(const char *, unsigned int);
int ftruncate(int, off_t);

#define PROT_READ   1
#define PROT_WRITE  2
#define MAP_SHARED  1
#define MAP_FAILED  ((void *)-1)

void radeonR1Entry(int runId);

#define MAX_FN      32
#define MMIO_LEN    0x2000
#define REG_VLINE   0x0210
#define REG_FRAME   0x0214
#define LIVE_GAPS   7

struct fn {
    int bus, dev, fn;
    unsigned int cfg[64];   /* words at 0x00..0xfc */
    int flipReg;            /* -1, or the word index that flips */
    unsigned int flipVal;
    int flipReads;
    int flipAfter;
};

static struct fn fns[MAX_FN];
static int nfn;
static unsigned int latch;
static int latched;
static unsigned int *mmioRW;
static void *mmioRO;
static int mapped, mapCount, mapFail, unmapFail;
static unsigned int mapPhys;
static int scanDead = 1;
static double vtotal = 525.0, refreshHz = 59.94;
static double nowUs;
static unsigned long long delayUs, sleepMs;
static int delayCalls;

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

    if (!mmioRW || scanDead)
        return;
    frames = nowUs * refreshHz / 1e6;
    line = (frames - (double)(unsigned int)frames) * vtotal;
    mmioRW[REG_VLINE / 4] = ((unsigned int)line & 0x7ff) << 16;
    mmioRW[REG_FRAME / 4] = (unsigned int)frames;
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
    /* i386 cdecl: the variable arguments follow the format on the stack */
    printf("Sep 15 10:00:00 sim mach: ");
    vprintf(format, (char *)(&format + 1));
}

void
IOSleep(unsigned ms)
{
    if (delayCalls > 0 && delayCalls < LIVE_GAPS)
        violation("sleep-inside-live-window", delayCalls, ms);
    sleepMs += ms;
    nowUs += ms * 1000.0;
    updateScan();
}

void
IODelay(unsigned us)
{
    delayCalls++;
    delayUs += us;
    nowUs += us;
    updateScan();
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
    int i, fd, ok = 0;

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
    fd = memfd_create("mmio", 0);
    if (fd < 0 || ftruncate(fd, MMIO_LEN) != 0)
        violation("host-memfd", 0, 0);
    mmioRO = mmap(0, MMIO_LEN, PROT_READ, MAP_SHARED, fd, 0);
    if (mmioRO == MAP_FAILED)
        violation("host-mmap", 0, 0);
    /* the RW view was filled from the scenario before the probe ran */
    {
        unsigned int *rw = mmap(0, MMIO_LEN, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
        if ((void *)rw == MAP_FAILED)
            violation("host-mmap", 1, 0);
        for (i = 0; i < MMIO_LEN / 4; i++)
            rw[i] = mmioRW[i];
        mmioRW = rw;
    }
    updateScan();
    mapped = 1;
    mapPhys = phys;
    *virt = (unsigned)mmioRO;
    return 0;
}

int
IOUnmapPhysicalFromIOTask(unsigned virt, unsigned length)
{
    if (!mapped || virt != (unsigned)mmioRO || length != MMIO_LEN)
        violation("unmap", virt, length);
    mapped = 0;
    return unmapFail ? -1 : 0;
}

/* ---- scenario ------------------------------------------------------------- */

static unsigned int stage[MMIO_LEN / 4];

__attribute__((force_align_arg_pointer))
void
_start(void)
{
    char buf[256];
    int runid = -1, bus, dev, fn;
    unsigned int reg, val, vt, mhz;

    mmioRW = stage;
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
            stage[reg / 4] = val;
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
        if (buf[0] == '#' || buf[0] == '\n')
            continue;
        violation("scenario-syntax", 0, 0);
    }
    if (runid < 0)
        violation("scenario-no-runid", 0, 0);
    radeonR1Entry(runid);
    if (mapped)
        violation("left-mapped", mapPhys, 0);
    fflush(0);
    fprintf(stderr, "SIM-STATS maps=%d sleep_ms=%llu delay_us=%llu delay_calls=%d\n", mapCount, sleepMs, delayUs, delayCalls);
    exit(0);
}
