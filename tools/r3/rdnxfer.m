/*
 * rdnxfer -- send a 256-entry transfer table to Display0 the way the window
 * server does (docs/G2_LUT_PLAN.md 3): IOSetTransferTable through the
 * device master.  The driver's superclass checks the count for the depth and
 * calls setTransferTable:count:, which puts the table on the hardware LUT
 * (or defers it while another sequence holds the card; the RDN-R3 xfer line
 * in /usr/adm/messages says which: result=1 applied, 3 deferred).
 *
 *   rdnxfer <file>      file: 256 lines, one hex word each, packed RRGGBBAA
 *
 * Exit: 0 sent (r printed), 2 bad file, 3 no Display0, 5 the driver refused.
 * Build on the target:  cc -O -Wall -o rdnxfer rdnxfer.m -lDriver
 */
#import <driverkit/IODeviceMaster.h>
#import <driverkit/return.h>
#import <driverkit/displayDefs.h>
#import <stdio.h>
#import <stdlib.h>
#import <string.h>

#define XFER_COUNT 256

int
main(int argc, char **argv)
{
    static unsigned int table[XFER_COUNT];
    IODeviceMaster *master;
    IOObjectNumber  obj = 0;
    IOString        kind;
    IOReturn        r;
    FILE           *f;
    char            line[64];
    char           *end;
    unsigned long   sum = 0, v;
    int             n = 0;

    if (argc != 2) {
        printf("RDNXFER usage: rdnxfer <file>\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == 0) {
        printf("RDNXFER exit=2 why=open %s\n", argv[1]);
        return 2;
    }
    while (n < XFER_COUNT && fgets(line, sizeof line, f) != 0) {
        if (line[0] == '#' || line[0] == '\n')
            continue;
        v = strtoul(line, &end, 16);
        if (end == line) {
            printf("RDNXFER exit=2 why=bad-word line=%d\n", n + 1);
            fclose(f);
            return 2;
        }
        table[n++] = (unsigned int)v;
        sum += v;
    }
    fclose(f);
    if (n != XFER_COUNT) {
        printf("RDNXFER exit=2 why=count %d\n", n);
        return 2;
    }
    printf("RDNXFER begin count=%d sum=%08lx first=%08x last=%08x\n",
           n, sum & 0xffffffffUL, table[0], table[XFER_COUNT - 1]);

    master = [IODeviceMaster new];
    if (master == nil) {
        printf("RDNXFER exit=3 why=no-device-master\n");
        return 3;
    }
    r = [master lookUpByDeviceName:"Display0" objectNumber:&obj deviceKind:&kind];
    printf("RDNXFER step=lookup r=%d object=%u kind=%s\n", (int)r, (unsigned)obj,
           r == IO_R_SUCCESS ? kind : "-");
    if (r != IO_R_SUCCESS) {
        printf("RDNXFER exit=3 why=no-display0\n");
        return 3;
    }
    r = [master setIntValues:table forParameter:IO_SET_TRANSFER_TABLE objectNumber:obj
                count:XFER_COUNT];
    printf("RDNXFER step=set r=%d\n", (int)r);
    if (r != IO_R_SUCCESS) {
        printf("RDNXFER exit=5 why=refused r=%d\n", (int)r);
        return 5;
    }
    printf("RDNXFER exit=0 sent=%d\n", n);
    return 0;
}
