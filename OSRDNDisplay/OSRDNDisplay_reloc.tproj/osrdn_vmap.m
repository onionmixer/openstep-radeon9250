/*
 * osrdn_vmap.m - see osrdn_vmap.h.  Plain C89; no hardware, no log, and
 * osrdn_vmap_pfn and osrdn_vmap_fix call nothing (tools/r4/check_r4_src.py).
 */

#import "osrdn_vmap.h"

osrdn_vmap osrdn_vmap_window = { 0, 0UL, 0UL, 0UL, 0UL, 0UL, 0, 0UL, 0UL, 0UL };

#define VMAP_INT_MAX    0x7FFFFFFFUL

int
osrdn_vmap_fix(osrdn_vmap *v, unsigned long start, unsigned long end,
               unsigned long bar0, unsigned long page)
{
    unsigned long shift;

    if (v->fixed)
        return OSRDN_VMAP_AGAIN;
    if (page == 0UL || (page & (page - 1UL)) != 0UL)
        return OSRDN_VMAP_PAGE;
    if ((start & (page - 1UL)) != 0UL || (end & (page - 1UL)) != 0UL ||
        (bar0 & (page - 1UL)) != 0UL)
        return OSRDN_VMAP_ALIGN;
    if (start >= end || end - start < page)
        return OSRDN_VMAP_EMPTY;
    if (bar0 > 0xFFFFFFFFUL - end)
        return OSRDN_VMAP_WRAP;
    if (end > VMAP_INT_MAX - 2UL * page)
        return OSRDN_VMAP_RANGE;
    for (shift = 0UL; (1UL << shift) != page; shift++)
        ;                                   /* page is a power of two: ends */
    if (((bar0 + end - page) >> shift) > VMAP_INT_MAX)
        return OSRDN_VMAP_PFN;
    v->start = start;
    v->end = end;
    v->bar0 = bar0;
    v->page = page;
    v->shift = shift;
    v->fixed = 1;                           /* last: the others are set */
    return OSRDN_VMAP_OK;
}

int
osrdn_vmap_fix_batch(osrdn_vmap *v, unsigned long phys, unsigned long bytes)
{
    if (v->bfixed)
        return OSRDN_VMAP_BAGAIN;
    if (!v->fixed)
        return OSRDN_VMAP_BFIRST;           /* page and shift come from the other window */
    if (bytes != v->page)
        return OSRDN_VMAP_BSIZE;            /* one page: d_mmap answers in pages */
    if ((phys & (v->page - 1UL)) != 0UL)
        return OSRDN_VMAP_BALIGN;
    if (phys > 0xFFFFFFFFUL - bytes)
        return OSRDN_VMAP_BWRAP;
    /* clear of the VRAM window AND of the two pages past it that the self-test
       walks expecting -1, so the two windows cannot be confused for each other */
    if (OSRDN_VMAP_BATCH_BASE <= v->end + 2UL * v->page)
        return OSRDN_VMAP_BLOW;
    if (OSRDN_VMAP_BATCH_BASE > VMAP_INT_MAX - bytes)
        return OSRDN_VMAP_BRANGE;
    if ((phys >> v->shift) > VMAP_INT_MAX)
        return OSRDN_VMAP_BPFN;
    v->bbase = OSRDN_VMAP_BATCH_BASE;
    v->bphys = phys;
    v->bbytes = bytes;
    v->bfixed = 1;                          /* last: the others are set */
    return OSRDN_VMAP_OK;
}

int
osrdn_vmap_pfn(const osrdn_vmap *v, int dev, int offset, int prot)
{
    unsigned long off, phys, rel;

    if (!v->fixed)
        return -1;
    if ((dev & 0xFF) != 0)
        return -1;
    if (offset < 0)
        return -1;
    if (prot != OSRDN_VMAP_PROT_RW)                 /* no EXEC, no read-only */
        return -1;
    off = (unsigned long)offset;
    /* R7b: the batch window, which BLOW proved sits past the other one.  The
       bound is asked of the WHOLE PAGE, not of the offset -- the kernel maps a
       whole page for every offset it accepts (Matrox 3-35, R7_PLAN 10-5 E). */
    if (v->bfixed && off >= v->bbase) {
        rel = off - v->bbase;
        if (v->bbytes < v->page || rel > v->bbytes - v->page)
            return -1;
        if (v->bphys > 0xFFFFFFFFUL - rel)
            return -1;
        phys = v->bphys + rel;
        /* this also settles rel: BALIGN proved bphys page aligned, so an offset
           that does not start a page cannot produce a page-aligned phys */
        if ((phys & (v->page - 1UL)) != 0UL)
            return -1;
        if ((phys >> v->shift) > VMAP_INT_MAX)
            return -1;
        return (int)(phys >> v->shift);
    }
    /* written so no expression can overflow */
    if (v->end < v->page || v->start > v->end - v->page)
        return -1;
    if (off < v->start || off > v->end - v->page)
        return -1;
    if (v->bar0 > 0xFFFFFFFFUL - off)
        return -1;
    phys = v->bar0 + off;
    if ((phys & (v->page - 1UL)) != 0UL)
        return -1;
    if ((phys >> v->shift) > VMAP_INT_MAX)
        return -1;
    return (int)(phys >> v->shift);
}

/* one case: ask twice, the answers must agree and be what was wanted */
static unsigned long
vmapAsk(const osrdn_vmap *v, int dev, int offset, int prot, int want)
{
    int a, b;

    a = osrdn_vmap_pfn(v, dev, offset, prot);
    b = osrdn_vmap_pfn(v, dev, offset, prot);
    return (a != b || a != want) ? 1UL : 0UL;
}

unsigned long
osrdn_vmap_selftest(const osrdn_vmap *v, unsigned long *cases, unsigned long *allowed)
{
    unsigned long bad = 0UL, n = 0UL, ok = 0UL;
    unsigned long first, off, stop, k;
    int s, e, p, rw, got, got2;

    *cases = 0UL;
    *allowed = 0UL;
    if (!v->fixed)
        return 1UL;
    s = (int)v->start;
    e = (int)v->end;
    p = (int)v->page;
    rw = OSRDN_VMAP_PROT_RW;
    /* the first PFN by division, the rest by counting: not the function's
       own formula (plan 11-1) */
    first = (v->bar0 + v->start) / v->page;

    /* the fixed list (plan 3-3) */
    bad += vmapAsk(v, 0, s, rw, (int)first);                        n++;
    bad += vmapAsk(v, 0, s + p, rw, (int)(first + 1UL));            n++;
    bad += vmapAsk(v, 0, e - p, rw, (int)(first + (v->end - v->start) / v->page - 1UL)); n++;
    bad += vmapAsk(v, 0, e, rw, -1);                                n++;
    bad += vmapAsk(v, 0, e + p, rw, -1);                            n++;
    if (v->start >= v->page) {
        bad += vmapAsk(v, 0, s - p, rw, -1);                        n++;
    }
    if (v->start != 0UL) {
        bad += vmapAsk(v, 0, 0, rw, -1);                            n++;
    }
    bad += vmapAsk(v, 0, s + 4, rw, -1);                            n++;
    bad += vmapAsk(v, 0, (int)(VMAP_INT_MAX - v->page + 1UL), rw, -1); n++;
    bad += vmapAsk(v, 0, -2147483647 - 1, rw, -1);                  n++;
    bad += vmapAsk(v, 1, s, rw, -1);                                n++;   /* minor 1 */
    bad += vmapAsk(v, 0xFF, s, rw, -1);                             n++;
    bad += vmapAsk(v, 0x100, s, rw, (int)first);                    n++;   /* major 1 minor 0 */
    bad += vmapAsk(v, (int)(short)0x9100, s, rw, (int)first);       n++;   /* sign-extended rdev */
    bad += vmapAsk(v, 0, s, 1, -1);                                 n++;   /* read only */
    bad += vmapAsk(v, 0, s, 7, -1);                                 n++;   /* with exec */
    bad += vmapAsk(v, 0, s, 0, -1);                                 n++;
    bad += vmapAsk(v, 0, s, 3 | 8, -1);                             n++;

    /* R7b: the batch window, when there is one.  Its PFN by division, the
       refusals around it by the same rules the other window gets. */
    if (v->bfixed) {
        int b = (int)v->bbase;

        bad += vmapAsk(v, 0, b, rw, (int)(v->bphys / v->page));     n++;
        bad += vmapAsk(v, 0, b + p, rw, -1);                        n++;   /* past the page */
        bad += vmapAsk(v, 0, b - p, rw, -1);                        n++;   /* the gap below */
        bad += vmapAsk(v, 0, b + 4, rw, -1);                        n++;   /* not a page start */
        bad += vmapAsk(v, 1, b, rw, -1);                            n++;   /* minor 1 */
        bad += vmapAsk(v, 0, b, 1, -1);                             n++;   /* read only */
        bad += vmapAsk(v, 0, b, 7, -1);                             n++;   /* with exec */
    } else {
        bad += vmapAsk(v, 0, (int)OSRDN_VMAP_BATCH_BASE, rw, -1);   n++;
    }

    /* every page from 0 to end + 2 pages (fix proved it fits an int) */
    stop = v->end + 2UL * v->page;
    k = 0UL;
    for (off = 0UL; off <= stop; off += v->page) {
        got = osrdn_vmap_pfn(v, 0, (int)off, rw);
        got2 = osrdn_vmap_pfn(v, 0, (int)off, rw);
        n++;
        if (got != got2) {
            bad++;
            continue;
        }
        if (off >= v->start && off < v->end) {
            if (got != (int)(first + k))
                bad++;
            k++;
        } else if (got != -1) {
            bad++;
        }
        if (got != -1)
            ok++;
    }
    if (ok != (v->end - v->start) / v->page)
        bad++;
    *cases = n;
    *allowed = ok;
    return bad;
}
