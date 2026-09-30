/*
 * rdnhsync.m - move OSRDNDisplay's picture sideways, live, to calibrate
 * "RDN HSync Adjust" against a capture (docs/REL3_DISPLAY_FIX_PLAN.md 3-2 5-6).
 *
 * Build on the target:
 *   cc -O -Wall -o rdnhsync rdnhsync.m -lDriver
 *
 * Usage:
 *   rdnhsync <pixels>       -16..48; the sync starts that many pixels later
 *                           than the table's, so the picture moves LEFT as the
 *                           number grows.  It lasts until the next boot, which
 *                           reads "RDN HSync Adjust" (or the default, 7).
 *
 * The driver logs "RDN-REL3 hsync-set ... rc= word= got=" for every call.
 * Exit codes: 0 set; 2 usage; 3 no Display0; 4 the driver refused (IO_R_*
 * printed: -702 busy, -710 not live or read back wrong, -706 bad value,
 * -729/-711 the opt-in key is off).
 */

#import <driverkit/IODeviceMaster.h>
#import <driverkit/return.h>
#import <stdio.h>
#import <stdlib.h>

#define HSYNC_PARAM     "RDNRel3HSync"
#define HSYNC_MAGIC     0x48535943U     /* "HSYC", the driver's OSRDN_HSYNC_MAGIC */
#define HSYNC_MIN       (-16)
#define HSYNC_MAX       48

int
main(int argc, char **argv)
{
    IODeviceMaster *master;
    IOObjectNumber  obj;
    IOString        kind;
    IOReturn        r;
    unsigned        req[2];
    long            v;
    char           *end;

    if (argc != 2) {
        printf("usage: rdnhsync <pixels -16..48>\n");
        return 2;
    }
    v = strtol(argv[1], &end, 10);
    if (*end != '\0' || end == argv[1] || v < HSYNC_MIN || v > HSYNC_MAX) {
        printf("RDNHSYNC bad value %s (want -16..48)\n", argv[1]);
        return 2;
    }
    master = [IODeviceMaster new];
    if (master == nil) {
        printf("RDNHSYNC exit=3 why=no-device-master\n");
        return 3;
    }
    r = [master lookUpByDeviceName:"Display0" objectNumber:&obj deviceKind:&kind];
    if (r != IO_R_SUCCESS) {
        printf("RDNHSYNC exit=3 why=no-display0 r=%d\n", (int)r);
        return 3;
    }
    req[0] = HSYNC_MAGIC;
    req[1] = (unsigned)(int)v;
    r = [master setIntValues:req forParameter:HSYNC_PARAM objectNumber:obj count:2];
    printf("RDNHSYNC adj=%ld r=%d\n", v, (int)r);
    return (r == IO_R_SUCCESS) ? 0 : 4;
}
