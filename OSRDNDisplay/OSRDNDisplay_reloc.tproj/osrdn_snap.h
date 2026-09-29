/*
 * osrdn_snap.h - the R2b snapshot: everything the first mode set disturbs,
 * read before any write and written back by the revert.
 *
 * docs/R2B_IMPL_PLAN.md 12-12 is the canonical list and this file must match
 * it.  The rule is one sentence: THE SET THIS FILE CAN WRITE IS THE SET IT
 * SNAPSHOTS.  Every mode write in the driver goes through osrdn_mmio_put or
 * osrdn_pll_put, which take an index into these tables and nothing else, so
 * "which registers does the entry write" is answerable by reading the tables.
 *
 * Nothing here logs: the kernel VGA console drives the same I/O ports this
 * file reads, so a log line between the VGA snapshot and the end of the
 * revert would invalidate the snapshot (docs/R2B_IMPL_PLAN.md 12-9).
 */

#import <driverkit/kernelDriver.h>      /* vm_address_t */

/* ---- MMIO, in the order of the table in osrdn_snap.m ---------------------- */
#define SNAP_CLOCK_CNTL_INDEX   0
#define SNAP_CRTC_GEN_CNTL      1
#define SNAP_CRTC_EXT_CNTL      2
#define SNAP_DAC_CNTL           3
#define SNAP_CRTC_H_TOTAL_DISP  4
#define SNAP_CRTC_H_SYNC        5
#define SNAP_CRTC_V_TOTAL_DISP  6
#define SNAP_CRTC_V_SYNC        7
#define SNAP_CRTC_OFFSET        8
#define SNAP_CRTC_OFFSET_CNTL   9
#define SNAP_CRTC_PITCH         10
#define SNAP_GRPH_BUFFER_CNTL   11
#define SNAP_DISP_MERGE_CNTL    12
#define OSRDN_SNAP_MMIO_COUNT   13

/* ---- PLL, one byte index each -------------------------------------------- */
#define SNAP_PPLL_CNTL          0
#define SNAP_PPLL_REF_DIV       1
#define SNAP_PPLL_DIV_3         2
#define SNAP_VCLK_ECP_CNTL      3
#define SNAP_HTOTAL_CNTL        4
#define OSRDN_SNAP_PLL_COUNT    5

/* ---- standard VGA, read through the I/O ports ---------------------------- */
#define OSRDN_SNAP_SEQ          5       /* SEQ 0..4 */
#define OSRDN_SNAP_CRTC         25      /* CRTC 0..0x18 */
#define OSRDN_SNAP_GR           9       /* GR 0..8 */
#define OSRDN_SNAP_ATTR         21      /* ATTR 0..0x14, the whole set */
#define OSRDN_SNAP_PALETTE      256

/* why a snapshot is not valid */
#define SNAP_WHY_NONE           0
#define SNAP_WHY_PLL_BUSY       1       /* CLOCK_CNTL_INDEX had PLL_WR_EN set */
#define SNAP_WHY_PLL_INDEX      2       /* the index did not come back */
#define SNAP_WHY_NO_BASE        3
#define SNAP_WHY_VGA_DECODE     4       /* MISC read 0xff: the legacy VGA ports are not
                                           decoded (bridge forwarding off or no VGA core).
                                           Everything else would read 0xff too, and the
                                           text-console gate would be fooled by it -- R2b-0's
                                           record used the same test (osrdn_record.m 659). */

/* ---- read-only registers: never snapshot, never written -------------------
 * The entry's step-0 conditions (docs/R2_CLOSEOUT.md 11).  Their own table and
 * their own accessor, and no write accessor takes an index into it, so adding a
 * condition here cannot widen what the driver writes or what the revert has to
 * put back. */
#define PEEK_CRTC2_GEN_CNTL     0
#define PEEK_FP_GEN_CNTL        1
#define PEEK_CP_CSQ_CNTL        2
#define PEEK_RBBM_STATUS        3
#define PEEK_AIC_CNTL           4
#define PEEK_GEN_INT_CNTL       5
#define PEEK_OV0_SCALE_CNTL     6
#define PEEK_I2C_CNTL_1         7
#define PEEK_VIPH_CONTROL       8
#define PEEK_DISP_OUTPUT_CNTL   9
#define PEEK_DAC_CNTL2          10
#define PEEK_SURFACE_CNTL       11
#define PEEK_HOST_PATH_CNTL     12
#define PEEK_CONFIG_APER_0_BASE 13
#define PEEK_CONFIG_APER_SIZE   14
#define PEEK_CONFIG_MEMSIZE     15
#define PEEK_DISPLAY_BASE_ADDR  16
#define PEEK_MC_FB_LOCATION     17
#define OSRDN_PEEK_COUNT        18

/* ---- read-only PLL registers (R4, docs/R4_ENGINE_PLAN.md 13 #1) ----------
 * Clock state the engine RECORD reads and nothing writes.  A table of their
 * own, like osrdnPeek: putting them in osrdnSnapPll would make the snapshot,
 * the revert and the R2c read-back compare clock registers that may move on
 * their own under dynamic clocking. */
#define PLLPEEK_SCLK_CNTL       0
#define PLLPEEK_SCLK_MORE_CNTL  1
#define PLLPEEK_CLK_PWRMGT_CNTL 2
#define OSRDN_PLL_PEEK_COUNT    3

typedef struct {
    int             valid;
    int             why;
    unsigned long   mmio[OSRDN_SNAP_MMIO_COUNT];
    unsigned long   pll[OSRDN_SNAP_PLL_COUNT];
    unsigned long   palette[OSRDN_SNAP_PALETTE];
    unsigned char   vgaMisc;
    unsigned char   vgaSeq[OSRDN_SNAP_SEQ];
    unsigned char   vgaCrtc[OSRDN_SNAP_CRTC];
    unsigned char   vgaGr[OSRDN_SNAP_GR];
    unsigned char   vgaAttr[OSRDN_SNAP_ATTR];
    unsigned char   vgaAttrPas;     /* the attribute index byte as the console left it, palette
                                       address source bit included.  Kept because the read of
                                       ATTR 0x00-0x0F is only valid with that bit CLEAR, so the
                                       snapshot has to turn it off and put it back, and a later
                                       reader must be able to see what it was. */
    unsigned int    crtcPort;           /* 0x3d4 or 0x3b4, from MISC bit 0 */
    int             vgaTaken;           /* 0 when the VGA set was not read */
} osrdn_snap;

/* the tables, so a checker and the simulator can read them */
typedef struct {
    const char     *name;
    unsigned int    offset;             /* MMIO offset, or the PLL byte index */
} osrdn_snap_reg;

extern const osrdn_snap_reg osrdnSnapMmio[OSRDN_SNAP_MMIO_COUNT];
extern const osrdn_snap_reg osrdnSnapPll[OSRDN_SNAP_PLL_COUNT];
extern const osrdn_snap_reg osrdnPeek[OSRDN_PEEK_COUNT];
extern const osrdn_snap_reg osrdnPllPeek[OSRDN_PLL_PEEK_COUNT];

/* read everything; 1 on success, 0 with s->why set */
int osrdn_snap_take(vm_address_t base, osrdn_snap *snap);

/* the ONLY way this driver writes a mode register: an index into the tables */
void osrdn_mmio_put(vm_address_t base, int which, unsigned long value);
unsigned long osrdn_mmio_get(vm_address_t base, int which);
/* read one of the read-only step-0 registers; 0xffffffff for a bad index */
unsigned long osrdn_peek(vm_address_t base, int which);
void osrdn_pll_put(vm_address_t base, int which, unsigned long value);
unsigned long osrdn_pll_get(vm_address_t base, int which);
/* read one of the read-only PLL registers and put the index byte back as it
   was; 0xffffffff for a bad index, or without touching anything if the index
   byte had PLL_WR_EN set (the snapshot refuses the same state) */
unsigned long osrdn_pll_peek(vm_address_t base, int which);

/* palette and VGA ports */
void osrdn_palette_put(vm_address_t base, int first, int count, const unsigned long *values);
/* read palette entries the way the snapshot does: the entry number as the
   whole index word (this card reads by the low byte, docs/R3_MULTIMODE_PLAN.md 21-7) */
void osrdn_palette_get(vm_address_t base, int first, int count, unsigned long *values);
void osrdn_vga_put(const osrdn_snap *snap);
