/*
 * osrdn-mesa-replay.c - M3e: send ONE captured batch again, alone, R times
 * (docs/M3E_PLAN.md 1).
 *
 * The culled teapot latched the CP on the same 108-word submission two boots
 * running, and the stream itself looks ordinary.  This asks the card the one
 * question the teapot cannot: does THAT stream latch a CP that has done nothing
 * else?
 *
 * The vertex words are not in this file.  The host cuts them out of the
 * teapot's `RDNTEAPOT step=failed-w` lines (words 48..107, twelve five-word
 * vertices) into a file of hex words.  The state is the one those words were
 * sent with, read off the captured prologue (docs/M3E_PLAN.md 1): smooth,
 * no blend, no texture, depth tested, colour at 0, pitch 64, 64 x 64.  They go
 * through the library's own builder, so the stream is laid out by the same
 * code the teapot used -- which this program proves before it is trusted: on a
 * latched CP the first flush is refused and the library keeps what it built.
 *
 *   rdnreplay <words file> <repeat>
 *
 * Links libGL_radeon.a only for the triangle unit and the probe; no GL context.
 * Every line starts "RDNREPLAY ".
 */

#include <stdio.h>
#include <stdlib.h>

#include "OSRDNMesaTri.h"

#define TRIS    4
#define VW      5                       /* words a vertex: x, y, z, w, colour */
#define WORDS   (TRIS * 3 * VW)

static void
sayFailed(void)
{
    const osrdn_tri_failed *f = OSRDNMesaTriFailed();
    unsigned long i;

    if (f->n == 0UL)
        return;
    printf("RDNREPLAY step=failed n=%lu failures=%lu reason=%s tris=%lu vw=%lu "
           "batch=%lu seed=%lu why=%lu at=%lu word=%lu status=%lu\n",
           f->n, f->failures, OSRDNMesaTriWhyName((int)f->reason), f->tris,
           f->vw, f->batch, f->seed, f->why, f->at, f->word, f->status);
    for (i = 0UL; i < f->n; i++) {
        if (i % 8UL == 0UL)
            printf("RDNREPLAY step=failed-w at=%lu", i);
        printf(" %lx", f->w[i]);   /* no width: the target cc ignores it */
        if (i % 8UL == 7UL || i + 1UL == f->n)
            printf("\n");
    }
}

int
main(int argc, char **argv)
{
    static unsigned long v[WORDS];
    FILE *fp;
    char *end;
    long rep;
    int k, t, why = 0;
    unsigned long got;

    if (argc != 3) {
        printf("RDNREPLAY usage: rdnreplay <words file> <repeat>\n");
        return 2;
    }
    rep = strtol(argv[2], &end, 10);
    if (*end != '\0' || rep < 1L || rep > 100000L) {
        printf("RDNREPLAY usage: repeat is 1 .. 100000\n");
        return 2;
    }
    if ((fp = fopen(argv[1], "r")) == 0) {
        printf("RDNREPLAY FAIL cannot open %s\n", argv[1]);
        return 2;
    }
    for (k = 0; k < WORDS; k++)
        if (fscanf(fp, "%lx", &v[k]) != 1) {
            printf("RDNREPLAY FAIL %s has %d words, want %d\n", argv[1], k, WORDS);
            return 2;
        }
    if (fscanf(fp, "%lx", &got) == 1) {
        printf("RDNREPLAY FAIL %s has more than %d words\n", argv[1], WORDS);
        return 2;
    }
    fclose(fp);
    printf("RDNREPLAY step=begin repeat=%ld words=%d first=%lx last=%lx\n",
           rep, WORDS, v[0], v[WORDS - 1]);

    for (k = 0; k < (int)rep; k++) {
        for (t = 0; t < TRIS; t++)
            if (osrdn_tri_batch_add(0UL, 64, 64, 64, &v[t * 3 * VW],
                                    1, 0, 0, 1, &why) == 0UL) {
                printf("RDNREPLAY step=add-refused round=%d tri=%d why=%s\n",
                       k, t, OSRDNMesaTriWhyName(why));
                sayFailed();
                return 1;
            }
        got = osrdn_tri_batch_flush(&why);
        if (got != (unsigned long)TRIS) {
            printf("RDNREPLAY step=flush-refused round=%d got=%lu why=%s\n",
                   k, got, OSRDNMesaTriWhyName(why));
            sayFailed();
            return 1;
        }
    }
    printf("RDNREPLAY step=end rounds=%ld all-drawn=1\n", rep);
    return 0;
}
