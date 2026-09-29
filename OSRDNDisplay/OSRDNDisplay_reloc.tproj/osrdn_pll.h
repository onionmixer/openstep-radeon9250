/*
 * osrdn_pll.h - R2a's PLL groups, carried over for the R2b-0 record.
 *
 * Plan: docs/R2B0_IMPL_PLAN.md section 4-2.  osrdn_pll.m holds R2a's
 * pllGroup and pllSnapshot (probe/RDNR2aProbe/RDNR2aProbe_reloc.tproj/
 * RDNR2aProbe.m) with only the reviewed differences
 * (tools/r2b0/drift-src-allow.txt): the table has 12 indices, the line
 * function is osrdn_line, and the snapshot hands back how it ended.
 */

#import <driverkit/kernelDriver.h>      /* vm_address_t */

#define R2A_PLL_COUNT       12

/* the reason a PLL group stopped (as R2a) */
#define WHY_NONE            0
#define WHY_BUSY            1
#define WHY_UPPER           2
#define WHY_LOW             3
#define WHY_AFTER_DATA      4
#define WHY_RESTORE         5

typedef struct {
    const char     *name;
    unsigned int    offset;
} r2a_reg;

/* one PLL group's readings */
typedef struct {
    unsigned long   p, c, v, d, e, a;
} r2a_pllread;

extern const r2a_reg r2aPll[R2A_PLL_COUNT];
extern r2a_pllread r2aPllRead[R2A_PLL_COUNT];

/* Returns 1 if all groups completed; *doneOut the groups completed, *whyOut
 * how the first incomplete one stopped (WHY_NONE if none). */
int osrdn_pll_snapshot(vm_address_t base, int *doneOut, int *whyOut);

/* the record's line writer (osrdn_record.m) */
void osrdn_line(const char *body);
