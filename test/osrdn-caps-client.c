/*
 * osrdn-caps-client.c - M1a: what CAPS actually returns, with no verdict in the
 * way (docs/M1A_PLAN.md 5).
 *
 * Build on the target:
 *   cc -O -Wall -I<reloc dir> -o osrdncaps osrdn-caps-client.c
 *
 * Deliberately separate from the probe, and deliberately dumber: it opens the
 * node, sends CAPS, and prints every word it got, whatever they are.  When the
 * probe says something surprising, the question is always "is the probe wrong
 * or is the driver saying that?" -- and a tool that shares the probe's code
 * cannot answer it.  So this shares none.
 *
 * No -lDriver, for the same reason the probe has none.
 *
 * Every line starts "RDNCAPS ".
 */

#include "osrdn_r7b.h"

int printf(const char *, ...);
extern int open(const char *, int, ...);
extern int ioctl(int, int, char *);
extern int close(int);

#define NODE        "/dev/rdnvram0"
#define NODE_RDWR   2                   /* bsd/sys/fcntl.h 36: O_RDWR is 002 */

int
main(int argc, char **argv)
{
    osrdn_r7b_caps c;
    unsigned long *w = (unsigned long *)&c;
    const char *runid;
    unsigned i, n;
    int fd, rc;

    if (argc != 2) {
        printf("RDNCAPS usage: osrdncaps <runid>\n");
        return 2;
    }
    runid = argv[1];

    n = (unsigned)(sizeof c / sizeof(unsigned long));
    for (i = 0; i < n; i++)
        w[i] = 0UL;

    if ((fd = open(NODE, NODE_RDWR)) < 0) {
        printf("RDNCAPS run=%s step=open failed\n", runid);
        return 3;
    }
    rc = ioctl(fd, (int)OSRDN_R7B_IOC_CAPS, (char *)&c);
    (void)close(fd);
    if (rc != 0) {
        printf("RDNCAPS run=%s step=ioctl failed cmd=%08lx\n",
               runid, (unsigned long)OSRDN_R7B_IOC_CAPS);
        return 4;
    }

    /* the fields by name, then the same words raw: if a field is ever added on
       one side only, the raw row is what shows it */
    printf("RDNCAPS run=%s magic=%08lx version=%lu window=%08lx bytes=%lu max=%lu "
           "build=%08lx ready=%lu cprunning=%lu winstart=%08lx\n",
           runid, c.magic, c.version, c.window, c.bytes, c.maxWords,
           c.build, c.ready, c.cpRunning, c.winStart);
    printf("RDNCAPS run=%s words=%u", runid, n);
    for (i = 0; i < n; i++)
        printf(" %08lx", w[i]);
    printf("\n");
    printf("RDNCAPS run=%s expect magic=%08lx version=%lu\n",
           runid, (unsigned long)OSRDN_R7B_MAGIC, (unsigned long)OSRDN_R7B_VERSION);
    return 0;
}
