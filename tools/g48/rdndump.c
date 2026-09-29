/*
 * rdndump.c - G4-10 diagnosis: copy the client window's COLOUR surface (offset 0) and DEPTH surface
 * (offset OSRDN_TRI_DEPTH_BYTE_OFF) out of VRAM into two files, the way the library maps the window
 * (mesa/OSRDNMesaSurface.c surfMap: open, CAPS, vm_allocate, mmap at caps.winStart).  Read only.
 *   cc -O -Wall -o rdndump rdndump.c
 *   rdndump <colour file> <depth file> [width height]        (default 640 480; colour 4 B/px, depth 2 B/px)
 *   rdndump fill <hex colour> [width height [hex depth]]     G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 6):
 *       WRITES the colour surface with one word and the depth surface with one halfword (default
 *       0xffff, far -- a GEQUAL stream wants 0 instead), so two
 *       replays that start from the same window can be compared -- the only mode that writes.
 * Exit: 0 ok, 2 usage/file, 3 open, 4 CAPS, 5 map.  Every line starts "RDNDUMP ".
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/types.h>
#include <mach/mach.h>
#include "../../OSRDNDisplay/OSRDNDisplay_reloc.tproj/osrdn_r7b.h"

extern char *mmap(char *, int, int, int, int, long);
extern int open(const char *, int, ...);
extern int ioctl(int, int, char *);
extern int close(int);

#define NODE            "/dev/rdnvram0"
#define NODE_RDWR       2
#define PROT_RW         3
#define MAP_SHARED_     1
#define DEPTH_BYTE_OFF  0x00500000UL            /* OSRDNMesaTriTable.h OSRDN_TRI_DEPTH_BYTE_OFF */
#define PAGE            8192UL

int
main(int argc, char **argv)
{
    osrdn_r7b_caps caps;
    char *addr = 0;
    unsigned long w = 640UL, h = 480UL, cbytes, dbytes, bytes;
    int fd, fill = 0;
    unsigned long fillWord = 0UL, fillDepth = 0xffffUL, i;
    FILE *f;

    if (argc < 3) {
        printf("RDNDUMP usage: rdndump <colour file> <depth file> [width height]\n");
        return 2;
    }
    if (strcmp(argv[1], "fill") == 0) {
        fill = 1;
        fillWord = strtoul(argv[2], 0, 16);
        if (argc >= 6)
            fillDepth = strtoul(argv[5], 0, 16) & 0xffffUL;
    }
    if (argc >= 5) {
        w = strtoul(argv[3], 0, 10);
        h = strtoul(argv[4], 0, 10);
    }
    cbytes = w * h * 4UL;
    dbytes = w * h * 2UL;
    bytes = ((DEPTH_BYTE_OFF + dbytes) + PAGE - 1UL) & ~(PAGE - 1UL);
    if ((fd = open(NODE, NODE_RDWR)) < 0) {
        printf("RDNDUMP open errno=%d\n", errno);
        return 3;
    }
    memset((char *)&caps, 0, sizeof caps);
    if (ioctl(fd, (int)OSRDN_R7B_IOC_CAPS, (char *)&caps) != 0 || caps.magic != OSRDN_R7B_MAGIC || caps.winStart == 0UL) {
        printf("RDNDUMP caps errno=%d magic=%08lx winstart=%08lx\n", errno, caps.magic, caps.winStart);
        (void)close(fd);
        return 4;
    }
    if (vm_allocate(task_self(), (vm_address_t *)&addr, (vm_size_t)bytes, TRUE) != KERN_SUCCESS ||
        mmap(addr, (int)bytes, PROT_RW, MAP_SHARED_, fd, (long)caps.winStart) == (char *)-1) {
        printf("RDNDUMP map errno=%d bytes=%lu\n", errno, bytes);
        (void)close(fd);
        return 5;
    }
    printf("RDNDUMP winstart=%08lx build=%08lx bytes=%lu colour=%lu depth@%08lx=%lu\n",
           caps.winStart, caps.build, bytes, cbytes, DEPTH_BYTE_OFF, dbytes);
    if (fill) {
        volatile unsigned long *cw = (volatile unsigned long *)addr;
        volatile unsigned short *dw = (volatile unsigned short *)(addr + DEPTH_BYTE_OFF);

        for (i = 0UL; i < w * h; i++) {
            cw[i] = fillWord;
            dw[i] = (unsigned short) fillDepth;
        }
        (void)close(fd);
        printf("RDNDUMP filled colour=%08lx depth=%04lx pixels=%lu\n", fillWord, fillDepth, w * h);
        return 0;
    }
    if ((f = fopen(argv[1], "w")) == 0 || fwrite(addr, 1, (int)cbytes, f) != (int)cbytes) {
        printf("RDNDUMP colour write failed errno=%d\n", errno);
        return 2;
    }
    (void)fclose(f);
    if ((f = fopen(argv[2], "w")) == 0 || fwrite(addr + DEPTH_BYTE_OFF, 1, (int)dbytes, f) != (int)dbytes) {
        printf("RDNDUMP depth write failed errno=%d\n", errno);
        return 2;
    }
    (void)fclose(f);
    (void)close(fd);
    printf("RDNDUMP done\n");
    return 0;
}
