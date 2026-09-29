/*
 * osrdn_pll.m - R2a's PLL groups for the R2b-0 record (plain C, no class).
 *
 * Plan: docs/R2B0_IMPL_PLAN.md section 4-2.  pllGroup and the body of
 * pllSnapshot are R2a's (RDNR2aProbe.m), which ran PASS on the card
 * (docs/R2A_RESULT.md).  tools/r2b0/check_drift_src.py compares the two
 * functions with R2a's and allows only the hunks in
 * tools/r2b0/drift-src-allow.txt.
 *
 * Each PLL register is one group with interrupts masked (splhigh): read
 * CLOCK_CNTL_INDEX (P); if its write-enable bit is set, stop without
 * writing; store the six-bit index in the low byte only; re-read (C) and
 * require bits 8-31 unchanged and the low byte equal to the index; read
 * CLOCK_CNTL_DATA; re-read the index (D) and require D = C; store P's low
 * byte back; re-read (E) and require E = P.  Any failed requirement writes P
 * back as a full 32-bit value -- the value read inside the same masked group
 * -- and ends the snapshot.  No PLL data register is written.
 */

#import <driverkit/generalFuncs.h>
#import <kernserv/machine/spl.h>    /* splhigh/splx, as EMU10K1Driver.m does */
#import <stdio.h>                   /* sprintf */
#import "RDNR2aMMIO.h"
#import "osrdn_pll.h"

#define U(x)                ((unsigned int)(x))

#define REG_CLOCK_CNTL_INDEX 0x0008     /* radeonfbreg.h:330, radeon_reg.h:289 */
#define REG_CLOCK_CNTL_DATA  0x000c     /* radeonfbreg.h:329, radeon_reg.h:288 */
#define PLL_WR_EN           0x80UL      /* radeonfbreg.h RADEON_PLL_WR_EN (1 << 7) */
#define PLL_INDEX_MASK      0x3f        /* the index field: radeonfb.c:1578 idx & 0x3f */
#define LOW_BYTE            0xffUL

/* R2a's ten indices, then PPLL_DIV_1 and PPLL_DIV_2 (radeon_reg.h
 * RADEON_PPLL_DIV_1/2, xf86 reads the live slot PPLL_DIV_0 + PLL_DIV_SEL,
 * radeon_driver.c 1076 and 1079).  tools/r2b0/parse_r2b0.py PLL must equal
 * this table.  Every index has bits 6-7 clear. */
const r2a_reg r2aPll[R2A_PLL_COUNT] = {
    { "PPLL_CNTL",             0x02 },
    { "PPLL_REF_DIV",          0x03 },
    { "PPLL_DIV_0",            0x04 },
    { "PPLL_DIV_3",            0x07 },
    { "VCLK_ECP_CNTL",         0x08 },
    { "HTOTAL_CNTL",           0x09 },
    { "X_MPLL_REF_FB_DIV",     0x0a },
    { "SCLK_CNTL",             0x0d },
    { "MCLK_CNTL",             0x12 },
    { "PIXCLKS_CNTL",          0x2d },
    { "PPLL_DIV_1",            0x05 },
    { "PPLL_DIV_2",            0x06 }
};

r2a_pllread  r2aPllRead[R2A_PLL_COUNT];

/*
 * One PLL register, with interrupts masked for the whole group.  Returns
 * WHY_NONE, or the reason it stopped.  No sleep, no log, no call other than
 * the MMIO helpers happens between splhigh and splx.  The two comparisons of
 * each check are separate if statements (cc 2.7.2.1 has miscompiled a
 * combined boolean of two comparisons at -O; that was long long, but it costs
 * nothing to avoid the form here).
 */
static int
pllGroup(vm_address_t base, int k)
{
    int s;
    int why;
    unsigned long p, c, v, d, e, a;
    unsigned long index;

    index = (unsigned long)r2aPll[k].offset & PLL_INDEX_MASK;
    c = 0;
    v = 0;
    d = 0;
    e = 0;
    a = 0;
    why = WHY_NONE;

    s = splhigh();
    p = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
    if (p & PLL_WR_EN) {
        why = WHY_BUSY;
    } else {
        rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));
        c = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
        if ((c & ~LOW_BYTE) != (p & ~LOW_BYTE))
            why = WHY_UPPER;
        if (why == WHY_NONE) {
            if ((c & LOW_BYTE) != index)
                why = WHY_LOW;
        }
        if (why == WHY_NONE) {
            v = rdnMmioRead32(base, REG_CLOCK_CNTL_DATA);
            d = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
            if (d != c)
                why = WHY_AFTER_DATA;
        }
        if (why == WHY_NONE) {
            rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(p & LOW_BYTE));
            e = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
            if (e != p)
                why = WHY_RESTORE;
        }
        if (why != WHY_NONE) {
            /* the one 32-bit store: P, read inside this masked group */
            rdnMmioWrite32(base, REG_CLOCK_CNTL_INDEX, p);
            a = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
        }
    }
    splx(s);

    r2aPllRead[k].p = p;
    r2aPllRead[k].c = c;
    r2aPllRead[k].v = v;
    r2aPllRead[k].d = d;
    r2aPllRead[k].e = e;
    r2aPllRead[k].a = a;
    return why;
}

static const char *
whyName(int why)
{
    if (why == WHY_UPPER)
        return "upper";
    if (why == WHY_LOW)
        return "low";
    if (why == WHY_AFTER_DATA)
        return "after-data";
    if (why == WHY_RESTORE)
        return "restore";
    return "busy";
}

/* Returns 1 if all groups completed. */
int
osrdn_pll_snapshot(vm_address_t base, int *doneOut, int *whyOut)
{
    int k, done, why;
    char line[180];

    done = 0;
    why = WHY_NONE;
    for (k = 0; k < R2A_PLL_COUNT; k++) {
        why = pllGroup(base, k);
        if (why != WHY_NONE)
            break;
        done++;
    }

    /* the lines, after every hardware access */
    sprintf(line, "pllstart p0=%08x", U(r2aPllRead[0].p));
    osrdn_line(line);
    for (k = 0; k < done; k++) {
        sprintf(line, "pll k=%d idx=%02x name=%s p=%08x c=%08x val=%08x d=%08x e=%08x",
                k, U(r2aPll[k].offset), r2aPll[k].name, U(r2aPllRead[k].p), U(r2aPllRead[k].c),
                U(r2aPllRead[k].v), U(r2aPllRead[k].d), U(r2aPllRead[k].e));
        osrdn_line(line);
    }
    if (why == WHY_BUSY) {
        sprintf(line, "pllbusy k=%d p=%08x", done, U(r2aPllRead[done].p));
        osrdn_line(line);
        osrdn_line("stop reason=pll-index-busy");
    } else if (why != WHY_NONE) {
        sprintf(line, "pllabort k=%d why=%s p=%08x c=%08x d=%08x e=%08x a=%08x",
                done, whyName(why), U(r2aPllRead[done].p), U(r2aPllRead[done].c),
                U(r2aPllRead[done].d), U(r2aPllRead[done].e), U(r2aPllRead[done].a));
        osrdn_line(line);
        osrdn_line("stop reason=pll-index-disturbed");
    }
    sprintf(line, "pllend groups=%d", done);
    osrdn_line(line);
    *doneOut = done;
    *whyOut = why;
    return done == R2A_PLL_COUNT;
}
