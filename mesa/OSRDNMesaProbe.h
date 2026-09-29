/*
 * OSRDNMesaProbe.h - M1a: does this process get hardware acceleration, and if
 * not, why (docs/M1A_PLAN.md).
 *
 * This is the GATE, and it exists before any Mesa hook does.  Filling the hooks
 * first would leave the revert path untested, and the revert path is the one
 * MOST users run -- a machine without this card, a boot without the key, a
 * build that does not match.  (openstep-matrox-remade/docs/M1_3_GATING_PLAN.md
 * 18-23, which says exactly that after having lived it.)
 *
 * Plain C on purpose: libGL cannot carry Objective-C, so nothing here may reach
 * for IODeviceMaster or driverkit.  Everything it needs, the character device
 * already offers (R7b, docs/R7_PLAN.md 10).
 *
 * The contract, in one line: THE PROBE ALWAYS ANSWERS.  A failure is a verdict,
 * not an error -- a caller that gets an error cannot choose a fallback.
 */

#ifndef OSRDN_MESA_PROBE_H
#define OSRDN_MESA_PROBE_H

/*
 * Nine verdicts, and EIGHT OF THEM MEAN SOFTWARE.  Only OSRDN_PROBE_HARDWARE
 * accelerates; every other value is a reason to leave Mesa's software
 * rasteriser alone.  That ratio is the point of the rung: the interesting path
 * is the one that declines.
 */
#define OSRDN_PROBE_HARDWARE    0       /* every check passed */
#define OSRDN_PROBE_NO_DEVICE   1       /* no node, or open() refused */
#define OSRDN_PROBE_NOT_OURS    2       /* it answers, but not this driver */
#define OSRDN_PROBE_MAGIC       3       /* CAPS came back with another magic */
#define OSRDN_PROBE_VERSION     4       /* not the version we compiled against */
#define OSRDN_PROBE_NOT_READY   5       /* no batch page or no batch window */
#define OSRDN_PROBE_NOT_RUNNING 6       /* the CP is not running */
#define OSRDN_PROBE_DISABLED    7       /* the environment switch turned it off */
#define OSRDN_PROBE_REVOKED     8       /* something went wrong; we gave it up */
#define OSRDN_PROBE_VERDICTS    9

/* The switch.  It can only SUBTRACT: any value at all turns acceleration off,
   and no value can turn it on, because a switch that could would turn it on
   where there is no hardware. */
#define OSRDN_PROBE_ENV         "RDNMesaAccelOff"

/*
 * The verdict for this process.  The FIRST call decides it and every later call
 * repeats that answer -- if it could change, one frame could be drawn half by
 * each layer.  Never returns anything outside 0 .. OSRDN_PROBE_VERDICTS-1.
 */
int OSRDNMesaProbeRun(void);

/*
 * Give the acceleration up, for good.  One-way: after this the verdict is
 * REVOKED and a later success cannot bring it back, because whatever went wrong
 * would simply happen again.
 */
void OSRDNMesaProbeRevoke(void);

/* The name of a verdict, for a log line.  Never null. */
const char *OSRDNMesaProbeName(int verdict);

/*
 * What CAPS said, for the run that produced the verdict: zeroed unless the
 * verdict is HARDWARE.  A caller needs the window and the stride from here
 * rather than asking again -- asking again is a second answer.
 */
typedef struct {
    unsigned long window;       /* the mmap offset of the batch window */
    unsigned long bytes;        /* its length */
    unsigned long maxWords;     /* the most one submission may carry */
    unsigned long build;        /* which driver answered */
    unsigned long winStart;     /* the offscreen window's card address */
} OSRDNMesaProbeCaps;

const OSRDNMesaProbeCaps *OSRDNMesaProbeGetCaps(void);

/*
 * The seam the host simulator drives (docs/M1A_PLAN.md 6-A).  A build that does
 * not define OSRDN_PROBE_TESTABLE uses the real calls and this declaration is
 * not compiled, so the shipped library has no seam to reach.
 */
#ifdef OSRDN_PROBE_TESTABLE
typedef struct {
    int (*openNode)(const char *path);          /* fd, or -1 with errno set */
    int (*ioctlNode)(int fd, int cmd, char *blk);   /* 0, or -1 with errno set */
    void (*closeNode)(int fd);
    const char *(*getenvName)(const char *name);
} OSRDNMesaProbeOps;

void OSRDNMesaProbeSetOps(const OSRDNMesaProbeOps *ops);    /* null = the real ones */
void OSRDNMesaProbeForget(void);                            /* drop the cached verdict */
#endif

#endif /* OSRDN_MESA_PROBE_H */
