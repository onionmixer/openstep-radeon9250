/*
 * rdnr2b0.m - ask OSRDNDisplay for its R2b-0 record (docs/R2B0_IMPL_PLAN.md 5).
 *
 * Build on the target:
 *   cc -O -Wall -o /tmp/rdnr2b0 rdnr2b0.m -lDriver
 *
 * Usage:
 *   rdnr2b0 <runid> <build hex8>            look, then record
 *   rdnr2b0 <runid> <build hex8> state      look only (no record): the driver
 *                                           logs one line, which proves this
 *                                           boot's syslog path before anything
 *                                           touches hardware
 *   rdnr2b0 <runid> <build hex8> engine record
 *   rdnr2b0 <runid> <build hex8> engine fill <colour hex8>
 *   rdnr2b0 <runid> <build hex8> engine blit <case 0-12>
 *                                           R4: one 2D engine operation
 *                                           (docs/R4_ENGINE_PLAN.md 12-3); the
 *                                           driver logs the result lines
 *
 * Steps, each ending the tool with its own exit code on failure:
 *   3  lookUpByDeviceName "Display0" fails (the bundle did not load or init
 *      failed) -- no enumeration fallback, so nothing else is ever asked
 *   4  getIntValues "IOGetDisplayInfo" with count 5 (the superclass answers
 *      only 5 or 7; getCharValues returns -711) is not 1024 x 768
 *   5  getIntValues "RDNR2b0State" with count 9 is not ours: build, key on,
 *      no latch, location 03:0b.0
 *   6  setIntValues "RDNR2b0Record" = {runid, 0x52324230} returned -729 (key)
 *   9  ... -725 (in progress or two records this boot)
 *  10  ... -728 (a record stopped; latched)
 *  11  ... -711 (the driver's override was not reached)
 *   7  ... any other failure
 *   8  the state after the record does not show one more record
 *
 * Every line starts "RDNR2B0 " so tools/r2b0/target-run-r2b0.sh can keep it.
 */

#import <driverkit/IODeviceMaster.h>
#import <driverkit/return.h>
#import <stdio.h>
#import <stdlib.h>
#import <string.h>

#define INFO_PARAM      "IOGetDisplayInfo"
#define INFO_COUNT      5
#define STATE_PARAM     "RDNR2b0State"
#define STATE_COUNT     9
#define RECORD_PARAM    "RDNR2b0Record"
#define RECORD_COUNT    2
#define RECORD_MAGIC    0x52324230U
#define CYCLE_PARAM     "RDNR2bCycle"
#define CYCLE_COUNT     1
#define CYCLE_MAGIC     0x52324358U     /* "R2CX", the driver's OSRDN_CYCLE_MAGIC */
#define ENGINE_PARAM    "RDNR4Engine"
#define ENGINE_COUNT    3
#define ENGINE_MAGIC    0x52344530U     /* "R4E0", the driver's ENG_MAGIC */
/* The geometries the driver can publish (R3b-2: the one it does publish is
 * chosen from "Display Mode" at boot, and whether that choice is Configure's
 * is judged on the host against the instance table, docs/R3_MULTIMODE_PLAN.md
 * 21-2 D5a).  This table is held equal to the generated header's resolution
 * table by tools/r2b/check_tool_mode.py: the tool is built on the target
 * without that header on its include path. */
#define WANT_GEOMETRIES 5
static const unsigned wantGeometry[WANT_GEOMETRIES][2] = {
    {  640,  480 },
    {  800,  600 },
    { 1024,  768 },
    { 1280, 1024 },
    { 1600, 1200 }
};
#define WANT_LOCATION   0x358U          /* bus 3 << 8 | dev 0x0b << 3 | fn 0 */

static int
knownGeometry(unsigned width, unsigned height)
{
    int k;

    for (k = 0; k < WANT_GEOMETRIES; k++)
        if (wantGeometry[k][0] == width && wantGeometry[k][1] == height)
            return 1;
    return 0;
}

static void
printState(const char *when, const unsigned *w)
{
    printf("RDNR2B0 state when=%s nonce=%08x build=%08x enter=%u revert=%u records=%u lastrunid=%u "
           "lastresult=%u lastlines=%u flags=%08x key=%u latched=%u busy=%u cmode=%u loc=%03x\n",
           when, w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7], w[8],
           w[8] & 1U, (w[8] >> 1) & 1U, (w[8] >> 2) & 1U, (w[8] >> 8) & 0xffU, (w[8] >> 16) & 0xffffU);
}

static int
readState(IODeviceMaster *master, IOObjectNumber obj, unsigned *w)
{
    unsigned count = STATE_COUNT;
    IOReturn r;

    r = [master getIntValues:w forParameter:STATE_PARAM objectNumber:obj count:&count];
    printf("RDNR2B0 step=state r=%d count=%u\n", (int)r, count);
    if (r != IO_R_SUCCESS)
        return 0;
    return count == STATE_COUNT;
}

int
main(int argc, char **argv)
{
    IODeviceMaster *master;
    IOObjectNumber obj = 0;
    IOString kind;
    IOReturn r;
    unsigned info[INFO_COUNT];
    unsigned before[STATE_COUNT], after[STATE_COUNT];
    unsigned request[RECORD_COUNT];
    unsigned count;
    unsigned long runid, build;
    char *end;
    int stateOnly, cycleOnly, engineOp;
    unsigned long engineArg;

    if (argc < 3 || argc > 6) {
        printf("RDNR2B0 usage: rdnr2b0 <runid> <build hex8> [state|cycle|engine <op> [arg]]\n");
        return 2;
    }
    stateOnly = 0;
    cycleOnly = 0;
    engineOp = 0;
    engineArg = 0;
    if (argc >= 5 && strcmp(argv[3], "engine") == 0) {
        /* 1 record, 2 fill <colour hex>, 3 blit <case>: the driver's ENG_OP_*.
           Whole words only; an argument must be digits (no sign, not empty). */
        if (argc == 6 && (argv[5][0] == '\0' || argv[5][0] == '-' || argv[5][0] == '+'))
            engineOp = 0;
        else if (strcmp(argv[4], "record") == 0 && argc == 5)
            engineOp = 1;
        else if (strcmp(argv[4], "fill") == 0 && argc == 6) {
            engineOp = 2;
            engineArg = strtoul(argv[5], &end, 16);
            if (*end != '\0' || engineArg == 0x5a5a5a5aUL)   /* the marker: could not fail */
                engineOp = 0;
        } else if (strcmp(argv[4], "blit") == 0 && argc == 6) {
            engineOp = 3;
            engineArg = strtoul(argv[5], &end, 10);
            if (*end != '\0' || engineArg > 12UL)
                engineOp = 0;
        }
        if (engineOp == 0) {
            printf("RDNR2B0 usage: rdnr2b0 <runid> <build hex8> engine record|fill <hex8>|blit <0-12>\n");
            return 2;
        }
    } else if (argc >= 5) {
        /* five or six words that are not an engine request: refuse, rather
           than fall through to the record */
        printf("RDNR2B0 usage: rdnr2b0 <runid> <build hex8> [state|cycle|engine <op> [arg]]\n");
        return 2;
    } else if (argc == 4) {
        if (argv[3][0] == 's' && argv[3][1] == 't' && argv[3][2] == 'a')
            stateOnly = 1;
        else if (argv[3][0] == 'c' && argv[3][1] == 'y' && argv[3][2] == 'c')
            cycleOnly = 1;
        else {
            printf("RDNR2B0 usage: rdnr2b0 <runid> <build hex8> [state|cycle]\n");
            return 2;
        }
    }
    runid = strtoul(argv[1], &end, 10);
    if (*end != '\0' || runid == 0) {
        printf("RDNR2B0 bad runid %s\n", argv[1]);
        return 2;
    }
    build = strtoul(argv[2], &end, 16);
    if (*end != '\0') {
        printf("RDNR2B0 bad build %s\n", argv[2]);
        return 2;
    }
    printf("RDNR2B0 begin runid=%lu build=%08lx\n", runid, build);

    master = [IODeviceMaster new];
    if (master == nil) {
        printf("RDNR2B0 exit=3 why=no-device-master\n");
        return 3;
    }
    r = [master lookUpByDeviceName:"Display0" objectNumber:&obj deviceKind:&kind];
    printf("RDNR2B0 step=lookup r=%d object=%u kind=%s\n", (int)r, (unsigned)obj,
           r == IO_R_SUCCESS ? kind : "-");
    if (r != IO_R_SUCCESS) {
        printf("RDNR2B0 exit=3 why=no-display0\n");
        return 3;
    }

    count = INFO_COUNT;
    r = [master getIntValues:info forParameter:INFO_PARAM objectNumber:obj count:&count];
    printf("RDNR2B0 step=info r=%d count=%u width=%u height=%u refresh=%u bpp=%u colorspace=%u\n",
           (int)r, count, info[0], info[1], info[2], info[3], info[4]);
    if (r != IO_R_SUCCESS || count != INFO_COUNT ||
        !knownGeometry(info[0], info[1])) {
        printf("RDNR2B0 exit=4 why=display-info\n");
        return 4;
    }

    if (!readState(master, obj, before)) {
        printf("RDNR2B0 exit=5 why=state-unreadable\n");
        return 5;
    }
    printState("before", before);
    if (before[1] != (unsigned)build || (before[8] & 1U) == 0U || (before[8] & 2U) != 0U ||
        ((before[8] >> 16) & 0xffffU) != WANT_LOCATION) {
        printf("RDNR2B0 exit=5 why=state-not-ours\n");
        return 5;
    }

    if (stateOnly) {
        printf("RDNR2B0 exit=0 state-only\n");
        return 0;
    }

    if (engineOp != 0) {
        unsigned engreq[ENGINE_COUNT];

        engreq[0] = ENGINE_MAGIC;
        engreq[1] = (unsigned)engineOp;
        engreq[2] = (unsigned)engineArg;
        r = [master setIntValues:engreq forParameter:ENGINE_PARAM objectNumber:obj
                           count:ENGINE_COUNT];
        printf("RDNR2B0 step=engine op=%d arg=%08lx r=%d\n", engineOp, engineArg, (int)r);
        if (r != IO_R_SUCCESS) {
            printf("RDNR2B0 exit=7 why=engine r=%d\n", (int)r);
            return 7;
        }
        printf("RDNR2B0 exit=0 engine\n");
        return 0;
    }

    if (cycleOnly) {
        /* R2c: ask the driver to revert, read the whole snapshot back and come
         * back to the mode, so the revert can be judged without a shutdown
         * (docs/R2C_REVERT_PLAN.md).  The driver refuses a second one. */
        unsigned cycreq[CYCLE_COUNT];

        cycreq[0] = CYCLE_MAGIC;
        r = [master setIntValues:cycreq forParameter:CYCLE_PARAM objectNumber:obj
                           count:CYCLE_COUNT];
        printf("RDNR2B0 step=cycle r=%d\n", (int)r);
        if (!readState(master, obj, after))
            printf("RDNR2B0 step=cycle state-unreadable\n");
        else
            printState("after-cycle", after);
        if (r != IO_R_SUCCESS) {
            printf("RDNR2B0 exit=7 why=cycle r=%d\n", (int)r);
            return 7;
        }
        printf("RDNR2B0 exit=0 cycle\n");
        return 0;
    }

    request[0] = (unsigned)runid;
    request[1] = RECORD_MAGIC;
    r = [master setIntValues:request forParameter:RECORD_PARAM objectNumber:obj count:RECORD_COUNT];
    printf("RDNR2B0 step=record r=%d\n", (int)r);
    if (r == -729) {
        printf("RDNR2B0 exit=6 why=key-no\n");
        return 6;
    }
    if (r == -725) {
        printf("RDNR2B0 exit=9 why=busy-or-limit\n");
        return 9;
    }
    if (r == -728) {
        printf("RDNR2B0 exit=10 why=latched\n");
        return 10;
    }
    if (r == IO_R_UNSUPPORTED) {
        printf("RDNR2B0 exit=11 why=override-not-reached\n");
        return 11;
    }
    if (r != IO_R_SUCCESS) {
        printf("RDNR2B0 exit=7 why=record-failed\n");
        return 7;
    }

    if (!readState(master, obj, after)) {
        printf("RDNR2B0 exit=8 why=state-unreadable-after\n");
        return 8;
    }
    printState("after", after);
    if (after[4] != before[4] + 1U || after[5] != (unsigned)runid || after[0] != before[0]) {
        printf("RDNR2B0 exit=8 why=state-after\n");
        return 8;
    }
    printf("RDNR2B0 exit=0 lines=%u result=%u\n", after[7], after[6]);
    return 0;
}
