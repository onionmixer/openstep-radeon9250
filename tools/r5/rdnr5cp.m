/*
 * rdnr5cp.m - ask OSRDNDisplay for one R5 CP operation (docs/R5_PLAN.md 8, 9-2).
 *
 * Build on the target:
 *   cc -O -Wall -o rdnr5cp rdnr5cp.m -lDriver
 *
 * Usage, one operation per run, in the plan's order (9-2), stopping at the first
 * anomaly:
 *   rdnr5cp <runid> <build hex8> record|load|map|reset|start|negctl|stop
 *   rdnr5cp <runid> <build hex8> submit <len>     len: 16..4080, a multiple of 16
 *   rdnr5cp <runid> <build hex8> inject <len>     R5d: a SUBMIT, then the driver latches
 *                                                 (docs/R5D_PLAN.md 7; needs "RDN CP Inject")
 *   rdnr5cp <runid> <build hex8> tdump            M1x: the accumulated stage times, then zeroed
 *   rdnr5cp <runid> <build hex8> rec3d|zprep      R6a: read the 3D registers / fill the block
 *   rdnr5cp <runid> <build hex8> zclear <case>    R6a/R6b/R6c: case 1 A 2 B 3 C 4 D 5 E, colour 6 F 7 G 8 H, triangles 9-25, Gouraud 26-49, 50-59 (docs/R6E_PLAN.md 18),
 *                                                 depth 60-81 (docs/R6F_PLAN.md 3-1), the depth test 82-101 (docs/R6G_PLAN.md 2-2), the first texture 102-108 (docs/R6H_PLAN.md 2-2), perspective and bilinear 109-124 (docs/R6I_PLAN.md 2-2), the bilinear weight arithmetic 125-130 (docs/R6I2_PLAN.md 2-2), axis or channel 131-135 (docs/R6I3_PLAN.md 2-2), the blend unit 136-145 (docs/R6J_PLAN.md 2-2), the auxiliary scissor 146-160 (docs/R6K_PLAN.md 4), batching 161-165 (docs/R6L_PLAN.md 4), buffer reuse 166-170 (docs/R6M_PLAN.md 4), the client's own stream 171 (docs/R7_PLAN.md 4)
 *                                                 (docs/R6_PLAN.md 7; needs "RDN 3D Test")
 *
 * The evidence is in the kernel's RDN-R5 lines (tools/r5/check_cp.py judges
 * them); this tool only asks and reports the return code.  SUBMIT and NEGCTL
 * take their seed from the run id -- a new run id per call keeps the kernel's
 * "not the last seed" rule satisfied, and the judge recomputes the markers from
 * the seed the kernel logs.
 *
 * Exit codes:
 *   0  the operation ran (IO_R_SUCCESS)     2  usage
 *   3  Display0 not found                   4  RDNR2b0State is not this build
 *   5  the mode claim was held (IO_R_BUSY): not a failure, run again with a new run id
 *   6  refused, timed out or latched: read the kernel lines, and after a latch
 *      call nothing more -- no cycle, the operator reboots (plan 7-2 B14).  The one
 *      exception is the latch INJECT sets on purpose ("injected=1" in the io line):
 *      docs/R5D_PLAN.md 7 then lists what is called after it
 *
 * Every line starts "RDNR5 ".
 */

#import <driverkit/IODeviceMaster.h>
#import <driverkit/return.h>
#import <stdio.h>
#import <stdlib.h>
#import <string.h>

#define STATE_PARAM     "RDNR2b0State"
#define STATE_COUNT     9
#define CP_PARAM        "RDNR5Cp"
#define CP_COUNT        4
#define CP_MAGIC        0x52354330U     /* "R5C0", the driver's CP_MAGIC */

static const char *const opNames[] = {
    "", "record", "load", "map", "reset", "start", "submit", "negctl", "stop", "inject",
    "rec3d", "zprep", "zclear", "plane", "quiet", "tdump", "nowb", "spin", "time", "loud",
    "present", "clear", "asubmit", "retire"
};
#define OP_QUIET        14
#define OP_TDUMP        15      /* M1x: read the accumulated stage times, zero them */
#define OP_NOWB         16      /* M2a: len != 0 skips the WBINVD in the submission path */
#define OP_SPIN         17      /* M2b: len = extra cpCond polls before each IODelay */
#define OP_TIME         18      /* M2c: len != 0 lets the stage instrument run */
#define OP_LOUD         19      /* M2g: len = submissions to log; 0 = quiet now */
#define OP_SUBMIT       6
#define OP_NEGCTL       7
#define OP_INJECT       9
#define OP_ZCLEAR       12
#define OP_PLANE        13      /* R6e: len = lane*4 + chunk, 0 .. 15 (docs/R6E_PLAN.md 13) */
/* M1n: the loop is `k < OP_COUNT`, so this is the number of ENTRIES, not the
   last index.  It was 14 with 14 entries ("" .. "plane"); adding "quiet" made
   15, "tdump" 16, "nowb" 17, "spin" 18, "time" 19 and "loud" 20.  Leaving it behind would make
   the new name one the tool never matched -- a usage error, silently. */
#define OP_COUNT        24      /* G3: "present" 21, G3b: "clear" 22, G5-2: "asubmit" 23, "retire" 24 */

typedef char opNamesFull[(sizeof(opNames) / sizeof(opNames[0]) == OP_COUNT) ? 1 : -1];

int
main(int argc, char **argv)
{
    IODeviceMaster *master;
    IOObjectNumber obj = 0;
    IOString kind;
    IOReturn r;
    unsigned state[STATE_COUNT], req[CP_COUNT];
    unsigned long runid, build, len = 0, seed = 0;
    unsigned count;
    char *end;
    int op = 0, k;

    setbuf(stdout, (char *)0);
    if (argc < 4 || argc > 5) {
        printf("RDNR5 usage: rdnr5cp <runid> <build hex8> record|load|map|reset|start|negctl|stop|rec3d|zprep|tdump|submit <len>|inject <len>|zclear <case>|plane <lane*4+chunk>|quiet <lease>|nowb <0|1>|spin <0..64>|time <0|1>\n");
        return 2;
    }
    runid = strtoul(argv[1], &end, 10);
    if (*end != '\0' || runid == 0UL) {
        printf("RDNR5 bad runid %s\n", argv[1]);
        return 2;
    }
    build = strtoul(argv[2], &end, 16);
    if (*end != '\0') {
        printf("RDNR5 bad build %s\n", argv[2]);
        return 2;
    }
    for (k = 1; k < OP_COUNT; k++)
        if (strcmp(argv[3], opNames[k]) == 0)
            op = k;
    if (op == 0 || (op == OP_SUBMIT || op == OP_INJECT || op == OP_ZCLEAR ||
                    op == OP_PLANE || op == OP_QUIET || op == OP_NOWB ||
                    op == OP_SPIN || op == OP_TIME || op == OP_LOUD) != (argc == 5)) {
        printf("RDNR5 usage: an operation name, and a length (submit, inject), a case (zclear), lane*4+chunk (plane), a lease (quiet, loud) or 0|1 (nowb) only\n");
        return 2;
    }
    if (op == OP_ZCLEAR) {
        len = strtoul(argv[4], &end, 10);
        if (*end != '\0' || len < 1UL || len > 171UL) {  /* 171 = CP_R6_CASES in osrdn_cp.h */
            printf("RDNR5 bad case %s (1 .. 171)\n", argv[4]);
            return 2;
        }
    } else if (op == OP_PLANE) {
        len = strtoul(argv[4], &end, 10);
        if (*end != '\0' || len > 15UL) {
            printf("RDNR5 bad plane chunk %s (0 .. 15)\n", argv[4]);
            return 2;
        }
    } else if (op == OP_LOUD) {
        /* M2g: the lease, in submissions.  0 goes quiet now. */
        len = strtoul(argv[4], &end, 10);
        if (*end != '\0' || len > 100000UL) {
            printf("RDNR5 bad loud lease %s (0 .. 100000 submissions)\n", argv[4]);
            return 2;
        }
    } else if (op == OP_QUIET) {
        /* M1n: the lease, in submissions.  M2g: silence is the default now, so
           any N only cancels a loud lease -- 0 no longer brings the log back. */
        len = strtoul(argv[4], &end, 10);
        if (*end != '\0' || len > 100000UL) {
            printf("RDNR5 bad quiet lease %s (0 .. 100000 submissions)\n", argv[4]);
            return 2;
        }
    } else if (op == OP_NOWB) {
        /* M2a: 0 or 1 and nothing else.  A typo must not read as "on". */
        len = strtoul(argv[4], &end, 10);
        if (*end != '\0' || len > 1UL) {
            printf("RDNR5 bad nowb %s (0 or 1)\n", argv[4]);
            return 2;
        }
    } else if (op == OP_TIME) {
        /* M2c: 0 or 1 and nothing else. */
        len = strtoul(argv[4], &end, 10);
        if (*end != '\0' || len > 1UL) {
            printf("RDNR5 bad time %s (0 or 1)\n", argv[4]);
            return 2;
        }
    } else if (op == OP_SPIN) {
        /* M2b: 0 .. CP_SPIN_MAX.  The driver refuses more; this says so sooner. */
        len = strtoul(argv[4], &end, 10);
        if (*end != '\0' || len > 64UL) {
            printf("RDNR5 bad spin %s (0 .. 64)\n", argv[4]);
            return 2;
        }
    } else if (op == OP_SUBMIT || op == OP_INJECT) {
        len = strtoul(argv[4], &end, 10);
        if (*end != '\0' || len < 16UL || len > 4080UL || (len & 15UL) != 0UL) {
            printf("RDNR5 bad length %s (16..4080, a multiple of 16)\n", argv[4]);
            return 2;
        }
    }
    if (op == OP_SUBMIT || op == OP_NEGCTL || op == OP_INJECT || op == OP_ZCLEAR) {
        seed = (runid * 2654435761UL) ^ 0x5eed0000UL;
        if (seed == 0UL)
            seed = 1UL;
    }
    printf("RDNR5 begin runid=%lu build=%08lx op=%s seed=%08lx len=%lu\n", runid, build, opNames[op], seed, len);

    master = [IODeviceMaster new];
    r = (master == nil) ? IO_R_NO_DEVICE
                        : [master lookUpByDeviceName:"Display0" objectNumber:&obj deviceKind:&kind];
    if (r != IO_R_SUCCESS) {
        printf("RDNR5 exit=3 lookup r=%d\n", (int)r);
        return 3;
    }
    count = STATE_COUNT;
    r = [master getIntValues:state forParameter:STATE_PARAM objectNumber:obj count:&count];
    if (r != IO_R_SUCCESS || count != STATE_COUNT || state[1] != (unsigned)build) {
        printf("RDNR5 exit=4 state r=%d build=%08x\n", (int)r, state[1]);
        return 4;
    }
    req[0] = CP_MAGIC;
    req[1] = (unsigned)op;
    req[2] = (unsigned)seed;
    req[3] = (unsigned)len;
    r = [master setIntValues:req forParameter:CP_PARAM objectNumber:obj count:CP_COUNT];
    printf("RDNR5 result op=%s r=%d\n", opNames[op], (int)r);
    if (r == IO_R_SUCCESS) {
        printf("RDNR5 exit=0\n");
        return 0;
    }
    if (r == IO_R_BUSY) {
        printf("RDNR5 exit=5 the mode claim was held: run again with a new run id\n");
        return 5;
    }
    printf("RDNR5 exit=6 see the kernel's RDN-R5 lines; after a latch call nothing more and do not cycle\n");
    return 6;
}
