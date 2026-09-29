/*
 * osrdn-mesa-probe-test.c - M1a gates C, D, E and F on the real machine
 * (docs/M1A_PLAN.md 6).
 *
 * Build on the target:
 *   cc -O -Wall -I<mesa dir> -I<reloc dir> -o osrdnprobe \
 *      osrdn-mesa-probe-test.c OSRDNMesaProbe.c
 *
 * No -lDriver.  That is not an omission: libGL cannot carry Objective-C, so a
 * probe that needed IODeviceMaster would be a probe libGL could not call, and
 * this test is what proves the built object has no such need.
 *
 * Usage:
 *   osrdnprobe <runid> [revoke]
 *     revoke   run, then revoke, then run again -- gate E
 *
 * Gate D is run by setting RDNMesaAccelOff in the environment before this.
 * Gate F is run by asking before the CP has been started.
 *
 * Every line starts "RDNPROBE ".
 */

#include "OSRDNMesaProbe.h"

int printf(const char *, ...);

int
main(int argc, char **argv)
{
    const OSRDNMesaProbeCaps *c;
    const char *runid;
    int first, second, third;
    int doRevoke = 0;

    if (argc < 2 || argc > 3) {
        printf("RDNPROBE usage: osrdnprobe <runid> [revoke]\n");
        return 2;
    }
    runid = argv[1];
    if (argc == 3) {
        /* no strcmp: this unit declares its own libc and needs none */
        if (argv[2][0] == 'r')
            doRevoke = 1;
        else {
            printf("RDNPROBE usage: osrdnprobe <runid> [revoke]\n");
            return 2;
        }
    }

    /* gate C, first half: what this machine says */
    first = OSRDNMesaProbeRun();
    printf("RDNPROBE run=%s step=first verdict=%d name=%s\n",
           runid, first, OSRDNMesaProbeName(first));

    /* gate C, second half: the same answer, from the same process */
    second = OSRDNMesaProbeRun();
    printf("RDNPROBE run=%s step=second verdict=%d name=%s same=%d\n",
           runid, second, OSRDNMesaProbeName(second), first == second);

    /* what CAPS said, separately -- zeroed unless the verdict is HARDWARE */
    c = OSRDNMesaProbeGetCaps();
    printf("RDNPROBE run=%s step=caps window=%08lx bytes=%lu max=%lu build=%08lx "
           "winstart=%08lx\n",
           runid, c->window, c->bytes, c->maxWords, c->build, c->winStart);

    if (doRevoke) {
        /* gate E: one-way.  Whatever the machine says now, it says REVOKED. */
        OSRDNMesaProbeRevoke();
        third = OSRDNMesaProbeRun();
        printf("RDNPROBE run=%s step=revoked verdict=%d name=%s back=%d\n",
               runid, third, OSRDNMesaProbeName(third), third == first);
        c = OSRDNMesaProbeGetCaps();
        printf("RDNPROBE run=%s step=revoked-caps window=%08lx build=%08lx\n",
               runid, c->window, c->build);
    }
    printf("RDNPROBE run=%s step=done\n", runid);
    return 0;
}
