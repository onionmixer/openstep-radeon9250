/*
 * rdnr4map.m - R4c: map the offscreen window through OSRDNDisplay's character
 * device and check what the plan says it must show (docs/R4C_VMAP_PLAN.md
 * 11-4, gates 11-5).
 *
 * Build on the target (with r4map_want.c beside it):
 *   cc -O -Wall -o rdnr4map rdnr4map.m -lDriver
 *
 * Usage, as root (the nodes are 0600 root):
 *   rdnr4map <runid> <build hex8>
 *
 * Steps, each ending the tool with its own exit code:
 *   3  Display0 not found           4  RDNR2b0State not this build
 *   5  RDNR4Vmap not registered     6  the major is 0 or its two sources differ
 *   7  /dev has another node with this major, or a path that is not a char device
 *   8  mknod / open failed          9  minor 1 opened (it must be ENXIO)
 *  10  a boundary mapping that must be refused was ACCEPTED -- the tool stops at
 *      once and never touches it
 *  11  a boundary mapping that must be accepted was refused
 *  12  the block could not be mapped
 *  13  S1 already holds this run's words (use a new runid)
 *  14  the round trip through the mapping is wrong
 *  15  the mode claim was held (IO_R_BUSY): not a failure, run again
 *  16  an engine operation failed or was refused
 *  17  the block after UBLIT or FILL is wrong (aliasing then UNDECIDED)
 *  18  the aliasing pages could not be mapped
 *  19  aliasing seen, or a page did not read back
 *  20  a page could not be put back
 *  21  the engine has no alias (its key is off or its gate refused at boot)
 * Both nodes are unlinked on every exit after they were made.
 *
 * Rules that shape the code:
 *   - this is the 4.2BSD mmap: the address must be the caller's already, the
 *     call returns 0 on success, MAP_SHARED only, no munmap (plan 1 F2);
 *   - no mapping is longer than 32 pages (every mapping costs the kernel 48 bytes
 *     a page, allocated unchecked, plan 1 F4);
 *   - no word at or above ceiling - 64 MiB is touched before the aliasing step,
 *     which is last (the first CPU access near 124 MiB, plan 10-1 E4);
 *   - after a write loop, one locked exchange (xchg with memory) drains any
 *     write-combining buffer before the kernel is asked to look (plan 10-2 B11).
 *
 * Every line starts "RDNR4M ".
 */

#import <driverkit/IODeviceMaster.h>
#import <driverkit/IODevice.h>
#import <driverkit/return.h>
#import <stdio.h>
#import <stdlib.h>
#import <string.h>
#import <libc.h>
#import <errno.h>
#import <sys/types.h>
#import <sys/stat.h>
#import <sys/dir.h>
#import <sys/time.h>
#import <sys/mman.h>
#import <fcntl.h>
#import <mach/mach.h>

#import "r4map_want.c"

extern caddr_t mmap(caddr_t, int, int, int, int, off_t);     /* not declared by this libc */

#define STATE_PARAM     "RDNR2b0State"
#define STATE_COUNT     9
#define VMAP_PARAM      "RDNR4Vmap"
#define VMAP_COUNT      7
#define VMAP_MAGIC      0x52344D30U     /* "R4M0", the driver's OSRDN_VMAP_MAGIC */
#define VMAP_ON         1
#define ENGINE_PARAM    "RDNR4Engine"
#define ENGINE_COUNT    3
#define ENGINE_MAGIC    0x52344530U     /* "R4E0", the driver's ENG_MAGIC */
#define OP_FILL         2               /* ENG_OP_FILL */
#define OP_UBLIT        4               /* ENG_OP_UBLIT */
#define NODE0           "/dev/rdnvram0"
#define NODE1           "/dev/rdnvram1"
#define MAX_PAGES       32UL
#define ALIAS_STRIDE    0x4000000UL     /* 64 MiB */
#define PROT_RW         (PROT_READ | PROT_WRITE)
#define IS_CHR(m)       (((m) & S_IFMT) == S_IFCHR)   /* S_ISCHR is POSIX-only in these headers */

static int nodesMade = 0;

static int
finish(int code)
{
    if (nodesMade) {
        (void)unlink(NODE0);
        (void)unlink(NODE1);
    }
    printf("RDNR4M exit=%d\n", code);
    return code;
}

/* one locked exchange: drains write-combining buffers (xchg with memory is locked) */
static void
drain(void)
{
    static volatile unsigned long w;
    unsigned long v = 1UL;

    __asm__ __volatile__("xchgl %0, %1" : "=r"(v), "=m"(w) : "0"(v), "m"(w));
}

static unsigned long
elapsedUs(struct timeval *t0, struct timeval *t1)
{
    return (unsigned long)((t1->tv_sec - t0->tv_sec) * 1000000L + (t1->tv_usec - t0->tv_usec));
}

/* vm_allocate the place, map over it; the address on success, 0 on refusal */
static volatile unsigned long *
mapAt(int fd, unsigned long off, unsigned long pages, unsigned long page, int prot, int *err)
{
    vm_address_t addr = 0;

    *err = 0;
    if (pages == 0UL || pages > MAX_PAGES)
        return 0;
    if (vm_allocate(task_self(), &addr, (vm_size_t)(pages * page), TRUE) != KERN_SUCCESS) {
        *err = -1;
        return 0;
    }
    if ((int)mmap((caddr_t)addr, (int)(pages * page), prot, MAP_SHARED, fd, (off_t)off) == -1) {
        *err = errno;
        return 0;
    }
    return (volatile unsigned long *)addr;
}

static IOReturn
engine(IODeviceMaster *master, IOObjectNumber obj, unsigned op, unsigned long arg)
{
    unsigned req[ENGINE_COUNT];
    IOReturn r;

    req[0] = ENGINE_MAGIC;
    req[1] = op;
    req[2] = (unsigned)arg;
    r = [master setIntValues:req forParameter:ENGINE_PARAM objectNumber:obj count:ENGINE_COUNT];
    printf("RDNR4M engine op=%u arg=%08lx r=%d\n", op, arg, (int)r);
    if (r != IO_R_SUCCESS && r != IO_R_BUSY && op == OP_UBLIT)
        printf("RDNR4M hint: the kernel line says why; why=17 is a reused seed -- the seed carries only the "
               "run id's low byte, so a run id equal to an earlier one of this boot modulo 256 is refused\n");
    return r;
}

/* read the whole block and sort it; the counts go on one line */
static unsigned long
judgeBlock(const char *what, volatile unsigned long *b, int op, unsigned long arg, unsigned long seedOld)
{
    unsigned long off, got, want, src, n[4];
    long first = -1;
    int c, spot;

    n[0] = n[1] = n[2] = n[3] = 0UL;
    for (off = 0UL; off < R4M_BLOCK; off += 4UL) {
        got = b[off / 4UL];
        if (op == OP_UBLIT) {
            want = r4mWantUblit(arg, off);
            spot = r4mUblitSpot(off, &src);
        } else {
            want = r4mWantFill(arg, off);
            spot = r4mFillSpot(off);
        }
        c = r4mClass(got, want, r4mUser(seedOld, off), spot);
        n[c]++;
        if (c != R4M_OK && first < 0)
            first = (long)off;
    }
    printf("RDNR4M %s ok=%lu stale=%lu mark=%lu other=%lu first=%ld\n", what, n[R4M_OK], n[R4M_STALE],
           n[R4M_MARKED], n[R4M_OTHER], first);
    return n[R4M_STALE] + n[R4M_MARKED] + n[R4M_OTHER];
}

/* the ten boundary cases (plan 4 step 4); the order and the wants are held to
   the plan's list by tools/r4/check_tool_r4map.py */
struct bound {
    const char      *what;
    int             base;           /* 0 = start, 1 = end, 2 = zero, 3 = negative */
    long            delta;          /* bytes added to the base */
    unsigned long   pages;
    int             prot;
    int             want;           /* 1 accepted, 0 refused */
};

static const struct bound bounds[] = {
    { "start",          0, 0L,      1UL, PROT_RW,                1 },
    { "last",           1, -1L,     1UL, PROT_RW,                1 },
    { "last+next",      1, -1L,     2UL, PROT_RW,                0 },
    { "end",            1, 0L,      1UL, PROT_RW,                0 },
    { "before",         0, -1L,     1UL, PROT_RW,                0 },
    { "zero",           2, 0L,      1UL, PROT_RW,                0 },
    { "unaligned",      0, 4L,      1UL, PROT_RW,                0 },
    { "readonly",       0, 0L,      1UL, PROT_READ,              0 },
    { "exec",           0, 0L,      1UL, PROT_RW | PROT_EXEC,    0 },
    { "negative",       3, 0L,      1UL, PROT_RW,                0 }
};
#define NBOUNDS (sizeof bounds / sizeof bounds[0])

int
main(int argc, char **argv)
{
    IODeviceMaster *master;
    IOObjectNumber obj = 0;
    IOString kind;
    IOReturn r;
    unsigned state[STATE_COUNT], vm[VMAP_COUNT], cmajor = 0;
    unsigned count, k;
    unsigned long runid, build, start, end, page, off, seedA, seedB, colour, hi, lo, i, bad;
    unsigned long saveLo[2048], saveHi[2048];
    char *endp;
    int fd, err;
    DIR *d;
    struct direct *de;
    struct stat st;
    char path[64];
    volatile unsigned long *m, *blk, *pl, *ph;
    struct timeval t0, t1, t2;

    setbuf(stdout, (char *)0);          /* unbuffered: survive a fault */
    if (argc != 3) {
        printf("RDNR4M usage: rdnr4map <runid> <build hex8>\n");
        return 2;
    }
    runid = strtoul(argv[1], &endp, 10);
    if (*endp != '\0' || runid == 0UL) {
        printf("RDNR4M bad runid %s\n", argv[1]);
        return 2;
    }
    build = strtoul(argv[2], &endp, 16);
    if (*endp != '\0') {
        printf("RDNR4M bad build %s\n", argv[2]);
        return 2;
    }
    seedA = 0xC3000000UL | ((runid & 0xffUL) << 16);
    seedB = 0x3C000000UL | ((runid & 0xffUL) << 16);
    colour = 0x96000000UL | (runid & 0xffffffUL);
    printf("RDNR4M begin runid=%lu build=%08lx seedA=%08lx seedB=%08lx colour=%08lx\n",
           runid, build, seedA, seedB, colour);

    /* 1. the device, as the driver reports it */
    master = [IODeviceMaster new];
    r = (master == nil) ? IO_R_NO_DEVICE
                        : [master lookUpByDeviceName:"Display0" objectNumber:&obj deviceKind:&kind];
    if (r != IO_R_SUCCESS) {
        printf("RDNR4M step=lookup r=%d\n", (int)r);
        return finish(3);
    }
    count = STATE_COUNT;
    r = [master getIntValues:state forParameter:STATE_PARAM objectNumber:obj count:&count];
    printf("RDNR4M step=state r=%d build=%08x flags=%08x\n", (int)r, state[1], state[8]);
    if (r != IO_R_SUCCESS || count != STATE_COUNT || state[1] != (unsigned)build)
        return finish(4);
    count = VMAP_COUNT;
    r = [master getIntValues:vm forParameter:VMAP_PARAM objectNumber:obj count:&count];
    printf("RDNR4M step=vmap r=%d magic=%08x state=%u start=%08x end=%08x page=%u major=%d engine=%08x\n",
           (int)r, vm[0], vm[1], vm[2], vm[3], vm[4], (int)vm[5], vm[6]);
    if (r != IO_R_SUCCESS || count != VMAP_COUNT || vm[0] != VMAP_MAGIC || vm[1] != VMAP_ON)
        return finish(5);
    start = vm[2];
    end = vm[3];
    page = vm[4];
    if (vm[6] == 0U) {
        printf("RDNR4M step=vmap the engine has no alias: UBLIT and FILL cannot run (see the RDN-R4 alias line)\n");
        return finish(21);
    }
    if (page == 0UL || (page & (page - 1UL)) != 0UL || start >= end || vm[6] != vm[2]) {
        printf("RDNR4M step=vmap the window is not usable, or the engine block is not at its start\n");
        return finish(5);
    }
    count = 1;
    r = [master getIntValues:&cmajor forParameter:IO_CHARACTER_MAJOR objectNumber:obj count:&count];
    printf("RDNR4M step=major r=%d major=%u driver=%d\n", (int)r, cmajor, (int)vm[5]);
    if (r != IO_R_SUCCESS || count != 1 || cmajor == 0U || cmajor != vm[5])
        return finish(6);

    /* 2. no other node may reach this major; our two paths are char devices or absent */
    d = opendir("/dev");
    if (d == 0) {
        printf("RDNR4M step=devscan cannot read /dev errno=%d\n", errno);
        return finish(7);
    }
    bad = 0UL;
    while ((de = readdir(d)) != 0) {
        if (strlen(de->d_name) > sizeof path - 6)
            continue;
        sprintf(path, "/dev/%s", de->d_name);
        if (stat(path, &st) != 0 || !IS_CHR(st.st_mode) || (unsigned)major(st.st_rdev) != cmajor)
            continue;
        printf("RDNR4M devscan node=%s dev=%04x\n", path, (unsigned)st.st_rdev & 0xffffU);
        if (strcmp(path, NODE0) != 0 && strcmp(path, NODE1) != 0)
            bad++;
    }
    closedir(d);
    if (bad != 0UL)
        return finish(7);
    if ((stat(NODE0, &st) == 0 && !IS_CHR(st.st_mode)) || (stat(NODE1, &st) == 0 && !IS_CHR(st.st_mode))) {
        printf("RDNR4M devscan a node path is not a character device\n");
        return finish(7);
    }
    (void)unlink(NODE0);
    (void)unlink(NODE1);
    nodesMade = 1;
    if (mknod(NODE0, S_IFCHR | 0600, (int)((cmajor << 8) | 0U)) != 0 ||
        mknod(NODE1, S_IFCHR | 0600, (int)((cmajor << 8) | 1U)) != 0) {
        printf("RDNR4M step=mknod errno=%d\n", errno);
        return finish(8);
    }
    fd = open(NODE1, O_RDWR);
    err = errno;
    printf("RDNR4M step=minor1 fd=%d errno=%d\n", fd, fd < 0 ? err : 0);
    if (fd >= 0 || err != ENXIO) {
        if (fd >= 0)
            close(fd);
        return finish(9);
    }
    fd = open(NODE0, O_RDWR);
    if (fd < 0) {
        printf("RDNR4M step=open errno=%d\n", errno);
        return finish(8);
    }

    /* 3-4. the boundaries; an accepted mapping is never dereferenced here */
    for (k = 0; k < NBOUNDS; k++) {
        const struct bound *b = &bounds[k];
        unsigned long o;

        if (b->base == 0)
            o = start + (unsigned long)(b->delta < 0 ? -(long)page : b->delta);
        else if (b->base == 1)
            o = (b->delta < 0) ? end - page : end;
        else if (b->base == 2)
            o = 0UL;
        else
            o = 0x80000000UL;
        m = mapAt(fd, o, b->pages, page, b->prot, &err);
        printf("RDNR4M bound k=%u what=%s off=%08lx pages=%lu prot=%d want=%s got=%s errno=%d\n", k, b->what, o,
               b->pages, b->prot, b->want ? "ok" : "refused", m != 0 ? "ok" : "refused", err);
        if (m != 0 && !b->want)
            return finish(10);          /* never touch it */
        if (m == 0 && b->want)
            return finish(11);
    }

    /* 5. the block, and freshness: S1 must not hold this run's words already */
    blk = mapAt(fd, start, R4M_BLOCK / page, page, PROT_RW, &err);
    printf("RDNR4M step=block off=%08lx pages=%lu got=%s errno=%d\n", start, R4M_BLOCK / page,
           blk != 0 ? "ok" : "refused", err);
    if (blk == 0)
        return finish(12);
    bad = 0UL;
    for (off = R4M_S1_OFF; off < R4M_S1_OFF + R4M_S1_PITCH * R4M_S1_H; off += 4UL)
        if (blk[off / 4UL] == r4mUser(seedA, off))
            bad++;
    printf("RDNR4M step=fresh already=%lu\n", bad);
    if (bad != 0UL)
        return finish(13);

    /* 6. the round trip, timed (for the record only: a read-back cannot tell
       write-combining from uncached, plan 11-5) */
    gettimeofday(&t0, 0);
    for (off = 0UL; off < R4M_BLOCK; off += 4UL)
        blk[off / 4UL] = r4mUser(seedA, off);
    drain();
    gettimeofday(&t1, 0);
    bad = 0UL;
    for (off = 0UL; off < R4M_BLOCK; off += 4UL)
        if (blk[off / 4UL] != r4mUser(seedA, off))
            bad++;
    gettimeofday(&t2, 0);
    printf("RDNR4M self bad=%lu write_us=%lu read_us=%lu bytes=%lu\n", bad, elapsedUs(&t0, &t1),
           elapsedUs(&t1, &t2), R4M_BLOCK);
    if (bad != 0UL)
        return finish(14);

    /* 7. UBLIT: the kernel checks the whole block holds the user's words, the
       engine copies S1 to S2; then this reads the block back */
    r = engine(master, obj, OP_UBLIT, seedA);
    if (r == IO_R_BUSY)
        return finish(15);
    if (r != IO_R_SUCCESS)
        return finish(16);
    bad = judgeBlock("ublit", blk, OP_UBLIT, seedA, seedA);

    /* 8. FILL, after the user wrote and read the whole block again */
    for (off = 0UL; off < R4M_BLOCK; off += 4UL)
        blk[off / 4UL] = r4mUser(seedB, off);
    drain();
    for (off = 0UL, i = 0UL; off < R4M_BLOCK; off += 4UL)
        i += (blk[off / 4UL] != r4mUser(seedB, off));
    printf("RDNR4M warm bad=%lu\n", i);
    r = engine(master, obj, OP_FILL, colour);
    if (r == IO_R_BUSY)
        return finish(15);
    if (r != IO_R_SUCCESS)
        return finish(16);
    bad += judgeBlock("fill", blk, OP_FILL, colour, seedB) + i;
    if (bad != 0UL) {
        printf("RDNR4M alias UNDECIDED (the block did not read back as it must)\n");
        return finish(17);
    }

    /* 9. aliasing, last: lo = hi - 64 MiB; save, write lo, write hi, read lo,
       read hi, put both back, read both */
    hi = end - page;
    lo = hi - ALIAS_STRIDE;
    if (lo < start + R4M_BLOCK || page / 4UL > 2048UL) {
        printf("RDNR4M alias the low page is not in the window above the block\n");
        return finish(18);
    }
    pl = mapAt(fd, lo, 1UL, page, PROT_RW, &err);
    ph = (pl != 0) ? mapAt(fd, hi, 1UL, page, PROT_RW, &err) : 0;
    printf("RDNR4M step=aliasmap lo=%08lx hi=%08lx got=%s errno=%d\n", lo, hi, ph != 0 ? "ok" : "refused", err);
    if (pl == 0 || ph == 0)
        return finish(18);
    for (i = 0UL; i < page / 4UL; i++) {
        saveLo[i] = pl[i];
        saveHi[i] = ph[i];
    }
    for (i = 0UL; i < page / 4UL; i++)
        pl[i] = 0xA1000000UL | (runid & 0xffUL) << 16 | i;
    drain();
    for (i = 0UL; i < page / 4UL; i++)
        ph[i] = 0xB2000000UL | (runid & 0xffUL) << 16 | i;
    drain();
    bad = 0UL;
    for (i = 0UL; i < page / 4UL; i++)
        bad += (pl[i] != (0xA1000000UL | (runid & 0xffUL) << 16 | i));
    for (i = 0UL, k = 0; i < page / 4UL; i++)
        k += (ph[i] != (0xB2000000UL | (runid & 0xffUL) << 16 | i));
    printf("RDNR4M alias lo_changed=%lu hi_wrong=%u stride=%08lx\n", bad, k, ALIAS_STRIDE);
    for (i = 0UL; i < page / 4UL; i++)
        pl[i] = saveLo[i];
    drain();
    for (i = 0UL; i < page / 4UL; i++)
        ph[i] = saveHi[i];
    drain();
    for (i = 0UL, off = 0UL; i < page / 4UL; i++)
        off += (pl[i] != saveLo[i]) + (ph[i] != saveHi[i]);
    printf("RDNR4M restore bad=%lu\n", off);
    if (bad != 0UL || k != 0U)
        return finish(19);
    if (off != 0UL)
        return finish(20);
    close(fd);
    printf("RDNR4M done runid=%lu\n", runid);
    return finish(0);
}
