/*
 * OSRDNMesaProbe.c - see OSRDNMesaProbe.h.  Plain C89, no driverkit, no
 * Objective-C, no libGL dependency of its own.
 *
 * Order of the questions matters and is the order of docs/M1A_PLAN.md 3: the
 * cheapest and most final first, so that a machine without this card spends one
 * stat and answers.  REVOKED is asked before anything, because it outranks a
 * later success by construction.
 */

#include "OSRDNMesaProbe.h"
#include "osrdn_r7b.h"

/*
 * No libc headers, deliberately: this unit is built for the target by cc and for
 * the host simulator by gcc, and the two must compile the SAME text.  What it
 * needs from libc is four calls, declared here.  (osrdn_vmap.m keeps the same
 * rule for the same reason.)
 */
extern char *getenv(const char *);
extern int open(const char *, int, ...);
extern int ioctl(int, int, char *);
extern int close(int);

#define NODE            "/dev/rdnvram0"
/* bsd/sys/fcntl.h 36: O_RDWR is 002.  tools/mesa/check_probe.py reads that
   header and fails if it ever stops being 2, so this is pinned, not guessed. */
#define NODE_RDWR       2

/* zeroing without <string.h>: the blocks are arrays of unsigned long */
static void probeZero(unsigned long *p, int n)
{
    int i;

    for (i = 0; i < n; i++)
        p[i] = 0UL;
}

static int  probeVerdict = -1;          /* -1 = not asked yet */
static int  probeRevoked;
static OSRDNMesaProbeCaps probeCaps;

/* ---- the seam, and the real calls behind it ------------------------------ */

static int realOpen(const char *path)
{
    return open(path, NODE_RDWR);
}

static int realIoctl(int fd, int cmd, char *blk)
{
    return ioctl(fd, cmd, blk);
}

static void realClose(int fd)
{
    (void)close(fd);
}

static const char *realGetenv(const char *name)
{
    return (const char *)getenv(name);
}

#ifdef OSRDN_PROBE_TESTABLE
static const OSRDNMesaProbeOps *probeOps;

void OSRDNMesaProbeSetOps(const OSRDNMesaProbeOps *ops)
{
    probeOps = ops;
}

void OSRDNMesaProbeForget(void)
{
    /* the whole initial state, revocation included: revocation is ONE-WAY in the
       shipped build, so a simulator that could not clear it here would be unable
       to test anything after it had tested that.  This function exists only in a
       build that defines OSRDN_PROBE_TESTABLE. */
    probeRevoked = 0;
    probeVerdict = -1;
    probeZero((unsigned long *)&probeCaps,
              (int)(sizeof probeCaps / sizeof(unsigned long)));
}

#define P_OPEN(p)           (probeOps ? probeOps->openNode(p) : realOpen(p))
#define P_IOCTL(f, c, b)    (probeOps ? probeOps->ioctlNode(f, c, b) : realIoctl(f, c, b))
#define P_CLOSE(f)          (probeOps ? probeOps->closeNode(f) : realClose(f))
#define P_GETENV(n)         (probeOps ? probeOps->getenvName(n) : realGetenv(n))
#else
#define P_OPEN(p)           realOpen(p)
#define P_IOCTL(f, c, b)    realIoctl(f, c, b)
#define P_CLOSE(f)          realClose(f)
#define P_GETENV(n)         realGetenv(n)
#endif

/* ---- the decision -------------------------------------------------------- */

/*
 * One pass over the questions.  It returns a verdict and NEVER an error: every
 * way out of here is one of the nine.  The caller caches it.
 */
static int probeAsk(OSRDNMesaProbeCaps *caps)
{
    osrdn_r7b_caps blk;
    int fd, rc;

    /* The switch first among the "no" answers: a user who turned it off does
       not want us touching the node at all.  It can only subtract -- there is
       no value here that turns acceleration ON, which is why the test is
       "present" and not a comparison. */
    if (P_GETENV(OSRDN_PROBE_ENV) != 0)
        return OSRDN_PROBE_DISABLED;

    /* An absent node and a refused open are the same verdict, so there is no
       stat: it would be a second call that cannot change the answer. */
    if ((fd = P_OPEN(NODE)) < 0)
        return OSRDN_PROBE_NO_DEVICE;

    probeZero((unsigned long *)&blk, (int)(sizeof blk / sizeof(unsigned long)));
    rc = P_IOCTL(fd, (int)OSRDN_R7B_IOC_CAPS, (char *)&blk);
    P_CLOSE(fd);
    if (rc != 0) {
        /* Identity comes from the ioctl ITSELF.  Another driver's node may sit
           at a plausible name and a plausible major and still not be ours; what
           settles it is that it does not answer this command. */
        return OSRDN_PROBE_NOT_OURS;
    }
    if (blk.magic != OSRDN_R7B_MAGIC)
        return OSRDN_PROBE_MAGIC;
    /* EXACTLY the version: it names a shared-memory layout, so older and newer
       are both wrong, and neither is more wrong than the other. */
    if (blk.version != OSRDN_R7B_VERSION)
        return OSRDN_PROBE_VERSION;
    if (blk.ready != 1UL)
        return OSRDN_PROBE_NOT_READY;
    if (blk.cpRunning != 1UL)
        return OSRDN_PROBE_NOT_RUNNING;

    caps->window = blk.window;
    caps->bytes = blk.bytes;
    caps->maxWords = blk.maxWords;
    caps->build = blk.build;
    caps->winStart = blk.winStart;
    return OSRDN_PROBE_HARDWARE;
}

int OSRDNMesaProbeRun(void)
{
    OSRDNMesaProbeCaps caps;

    /* One-way, and asked before anything else: a later success must not undo a
       revocation, because whatever caused it would happen again. */
    if (probeRevoked)
        return OSRDN_PROBE_REVOKED;
    if (probeVerdict >= 0)
        return probeVerdict;

    probeZero((unsigned long *)&caps, (int)(sizeof caps / sizeof(unsigned long)));
    probeVerdict = probeAsk(&caps);
    if (probeVerdict == OSRDN_PROBE_HARDWARE) {
        /* field by field, not `probeCaps = caps`: a struct assignment makes the
           compiler emit a call to memcpy, and memcpy in this object's undefined
           symbols would weaken the one gate that proves these hooks cannot draw
           (docs/M1B_PLAN.md 6-B3 -- a hook could memcpy into a caller's buffer). */
        probeCaps.window = caps.window;
        probeCaps.bytes = caps.bytes;
        probeCaps.maxWords = caps.maxWords;
        probeCaps.build = caps.build;
        probeCaps.winStart = caps.winStart;
    }
    return probeVerdict;
}

void OSRDNMesaProbeRevoke(void)
{
    /* The flag is the ONLY thing carrying this.  Writing REVOKED into the cached
       verdict as well would make the flag redundant -- and a check that cannot be
       made to fail is not a check: removing it would go unnoticed, and the next
       person to add a re-probe path would silently lose the revocation. */
    probeRevoked = 1;
    probeZero((unsigned long *)&probeCaps,
              (int)(sizeof probeCaps / sizeof(unsigned long)));
}

const char *OSRDNMesaProbeName(int verdict)
{
    static const char *names[OSRDN_PROBE_VERDICTS] = {
        "HARDWARE", "NO_DEVICE", "NOT_OURS", "MAGIC", "VERSION",
        "NOT_READY", "NOT_RUNNING", "DISABLED", "REVOKED"
    };

    if (verdict < 0 || verdict >= OSRDN_PROBE_VERDICTS)
        return "?";
    return names[verdict];
}

const OSRDNMesaProbeCaps *OSRDNMesaProbeGetCaps(void)
{
    return &probeCaps;
}
