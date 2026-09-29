/*
 * OSRDNMesaTexArena.c - see OSRDNMesaTexArena.h.  Plain C89, no libc, no Mesa headers.
 */
#include "OSRDNMesaTexArena.h"

typedef struct {
    unsigned long origin;
    unsigned long bytes;
} osrdnTexBlock;

static osrdnTexBlock blocks[OSRDN_TEXARENA_BLOCKS];
static unsigned long blockCount;
static unsigned long arenaOrigin, arenaBytes, arenaEpoch;
static int arenaLive;

static void
arenaClear(void)
{
    unsigned long i;

    for (i = 0UL; i < (unsigned long)OSRDN_TEXARENA_BLOCKS; i++) {
        blocks[i].origin = 0UL;
        blocks[i].bytes = 0UL;
    }
    blockCount = 0UL;
}

void
osrdn_texarena_set(unsigned long origin, unsigned long bytes, unsigned long epoch)
{
    if (arenaLive && origin == arenaOrigin && bytes == arenaBytes && epoch == arenaEpoch)
        return;                         /* the same arena: keep what it holds */
    arenaClear();
    arenaOrigin = origin;
    arenaBytes = bytes;
    arenaEpoch = epoch;
    arenaLive = (bytes != 0UL);
}

void
osrdn_texarena_drop(void)
{
    arenaClear();
    arenaOrigin = arenaBytes = arenaEpoch = 0UL;
    arenaLive = 0;
}

unsigned long
osrdn_texarena_epoch(void)
{
    return arenaEpoch;
}

int
osrdn_texarena_alloc(unsigned long bytes, unsigned long epoch, unsigned long *origin)
{
    unsigned long want, at, i;

    if (origin != 0)
        *origin = 0UL;
    if (!arenaLive || origin == 0 || bytes == 0UL || epoch != arenaEpoch)
        return 0;
    if (blockCount >= (unsigned long)OSRDN_TEXARENA_BLOCKS)
        return 0;
    want = (bytes + OSRDN_TEXARENA_ALIGN - 1UL) & ~(OSRDN_TEXARENA_ALIGN - 1UL);
    if (want < bytes)                   /* wrapped */
        return 0;
    /* first fit over the sorted blocks: the gap before block i, else after the last */
    at = arenaOrigin;
    for (i = 0UL; i < blockCount; i++) {
        if (blocks[i].origin >= at && blocks[i].origin - at >= want)
            break;
        if (blocks[i].origin + blocks[i].bytes > at)
            at = blocks[i].origin + blocks[i].bytes;
    }
    if (at < arenaOrigin || at - arenaOrigin > arenaBytes)
        return 0;
    if (arenaBytes - (at - arenaOrigin) < want)
        return 0;
    for (i = blockCount; i > 0UL; i--) {    /* keep them sorted */
        if (blocks[i - 1UL].origin < at)
            break;
        blocks[i] = blocks[i - 1UL];
    }
    blocks[i].origin = at;
    blocks[i].bytes = want;
    blockCount++;
    *origin = at;
    return 1;
}

int
osrdn_texarena_free(unsigned long origin, unsigned long epoch)
{
    unsigned long i;

    if (!arenaLive || epoch != arenaEpoch)
        return 0;
    for (i = 0UL; i < blockCount; i++)
        if (blocks[i].origin == origin) {
            for (; i + 1UL < blockCount; i++)
                blocks[i] = blocks[i + 1UL];
            blockCount--;
            blocks[blockCount].origin = 0UL;
            blocks[blockCount].bytes = 0UL;
            return 1;
        }
    return 0;                           /* not ours, or freed already */
}

void
osrdn_texarena_stat(unsigned long *count, unsigned long *used, unsigned long *bytes)
{
    unsigned long i, n = 0UL;

    for (i = 0UL; i < blockCount; i++)
        n += blocks[i].bytes;
    if (count != 0) *count = blockCount;
    if (used != 0)  *used = n;
    if (bytes != 0) *bytes = arenaLive ? arenaBytes : 0UL;
}

static int
texarenaLog2(unsigned long v, unsigned long *out)
{
    unsigned long n = 0UL;

    if (v == 0UL || (v & (v - 1UL)) != 0UL)
        return 0;                       /* not a power of two */
    while (v > 1UL) {
        v >>= 1;
        n++;
    }
    *out = n;
    return 1;
}

int
osrdn_texarena_chain(unsigned long w, unsigned long h, unsigned long levels,
                     unsigned long *offs, unsigned long *bytes)
{
    unsigned long lw, lh, i, cw, ch, row, total = 0UL;

    if (offs == 0 || bytes == 0 || !texarenaLog2(w, &lw) || !texarenaLog2(h, &lh))
        return 0;
    if (lw > 11UL || lh > 11UL || levels == 0UL || levels > (unsigned long)OSRDN_TEXARENA_MAX_LEVELS)
        return 0;
    if (levels > (lw > lh ? lw : lh) + 1UL)
        return 0;                       /* more levels than the base can halve into */
    for (i = 0UL; i < levels; i++) {
        cw = (lw > i) ? (1UL << (lw - i)) : 1UL;
        ch = (lh > i) ? (1UL << (lh - i)) : 1UL;
        row = (cw * 4UL + 31UL) & ~31UL;
        total = (total + 31UL) & ~31UL;
        offs[i] = total;
        total += row * ch;
    }
    *bytes = total;
    return 1;
}
