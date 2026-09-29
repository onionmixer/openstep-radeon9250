/*
 * osrdn_snap.m - read the state the first mode set disturbs, and write it back.
 *
 * docs/R2B_IMPL_PLAN.md 12-12.  Plain C89 (a .m file so the NeXT headers are
 * imported the one way this project imports them).  No logging, no floating
 * point, no 64-bit division.
 *
 * The PLL write protocol is the one xf86 uses (RADEONOUTPLL): write the index
 * byte with PLL_WR_EN set, store 32 bits to CLOCK_CNTL_DATA.  This file then
 * writes the index byte back WITHOUT PLL_WR_EN, which xf86 does not do -- it
 * relies on the next read to clear it.  We clear it because this driver's own
 * PLL read path refuses while PLL_WR_EN is set (osrdn_pll.m), so leaving it
 * set would make the entry's read-back gate fail (docs/R2B_IMPL_PLAN.md 12-3).
 *
 * Two registers are written that are not in the snapshot tables:
 * CLOCK_CNTL_INDEX (in the MMIO table anyway) and PALETTE_INDEX.  Both are
 * index registers -- a pointer the next access overwrites, not state the
 * console depends on.  Everything else this file writes is in the tables.
 *
 * The palette is read by writing the entry number as the whole index word,
 * i.e. into the low byte.  xf86 reads with the number in bits 16-23 instead
 * (radeon_macros.h INPAL_START).  This card was measured to take the READ
 * index from the low byte: boot e6ea2e88 read the palette both ways -- the
 * low-byte read gave the console's four-level grey ramp, the bits-16-23 read
 * gave entry 0 256 times (docs/R3_MULTIMODE_PLAN.md 21-7).
 */

#import "osrdn_snap.h"
#import <kernserv/machine/spl.h>    /* splhigh/splx around the attribute file */
#import "osrdn_port.h"
#import "RDNR2aMMIO.h"

#define REG_CLOCK_CNTL_INDEX    0x0008
#define REG_CLOCK_CNTL_DATA     0x000c
#define REG_PALETTE_INDEX       0x00b0
#define REG_PALETTE_30_DATA     0x00b8

#define PLL_WR_EN               0x80UL
#define PLL_INDEX_MASK          0x3f
#define LOW_BYTE                0xffUL

#define VGA_ATTR_INDEX          0x3c0
#define VGA_ATTR_READ           0x3c1
#define VGA_SEQ_INDEX           0x3c4
#define VGA_SEQ_DATA            0x3c5
#define VGA_MISC_READ           0x3cc
#define VGA_MISC_WRITE          0x3c2
#define VGA_GR_INDEX            0x3ce
#define VGA_GR_DATA             0x3cf
#define VGA_CRTC_COLOR          0x3d4
#define VGA_CRTC_MONO           0x3b4
#define VGA_STATUS_OFFSET       6
#define VGA_PAS                 0x20

const osrdn_snap_reg osrdnSnapMmio[OSRDN_SNAP_MMIO_COUNT] = {
    { "CLOCK_CNTL_INDEX",      0x0008 },
    { "CRTC_GEN_CNTL",         0x0050 },
    { "CRTC_EXT_CNTL",         0x0054 },
    { "DAC_CNTL",              0x0058 },
    { "CRTC_H_TOTAL_DISP",     0x0200 },
    { "CRTC_H_SYNC_STRT_WID",  0x0204 },
    { "CRTC_V_TOTAL_DISP",     0x0208 },
    { "CRTC_V_SYNC_STRT_WID",  0x020c },
    { "CRTC_OFFSET",           0x0224 },
    { "CRTC_OFFSET_CNTL",      0x0228 },
    { "CRTC_PITCH",            0x022c },
    { "GRPH_BUFFER_CNTL",      0x02f0 },
    { "DISP_MERGE_CNTL",       0x0d60 }
};

const osrdn_snap_reg osrdnSnapPll[OSRDN_SNAP_PLL_COUNT] = {
    { "PPLL_CNTL",             0x02 },
    { "PPLL_REF_DIV",          0x03 },
    { "PPLL_DIV_3",            0x07 },
    { "VCLK_ECP_CNTL",         0x08 },
    { "HTOTAL_CNTL",           0x09 }
};

/* PLL byte indexes from ref/upstream/unpacked/xf86-video-ati-6.14.6/src/radeon_reg.h
   (RADEON_SCLK_CNTL 0x0d, RADEON_SCLK_MORE_CNTL 0x35, RADEON_CLK_PWRMGT_CNTL 0x14);
   read only, docs/R4_ENGINE_PLAN.md 12-3 */
const osrdn_snap_reg osrdnPllPeek[OSRDN_PLL_PEEK_COUNT] = {
    { "SCLK_CNTL",             0x0d },
    { "SCLK_MORE_CNTL",        0x35 },
    { "CLK_PWRMGT_CNTL",       0x14 }
};

/* offsets from ref/upstream/unpacked/xf86-video-ati-6.14.6/src/radeon_reg.h;
   docs/R2_CLOSEOUT.md 7 and 10 give the line of each and the value both
   measured boots had */
const osrdn_snap_reg osrdnPeek[OSRDN_PEEK_COUNT] = {
    { "CRTC2_GEN_CNTL",        0x03f8 },
    { "FP_GEN_CNTL",           0x0284 },
    { "CP_CSQ_CNTL",           0x0740 },
    { "RBBM_STATUS",           0x0e40 },
    { "AIC_CNTL",              0x01d0 },
    { "GEN_INT_CNTL",          0x0040 },
    { "OV0_SCALE_CNTL",        0x0420 },
    { "I2C_CNTL_1",            0x0094 },
    { "VIPH_CONTROL",          0x0c40 },
    { "DISP_OUTPUT_CNTL",      0x0d64 },
    { "DAC_CNTL2",             0x007c },
    { "SURFACE_CNTL",          0x0b00 },
    { "HOST_PATH_CNTL",        0x0130 },
    { "CONFIG_APER_0_BASE",    0x0100 },
    { "CONFIG_APER_SIZE",      0x0108 },
    { "CONFIG_MEMSIZE",        0x00f8 },
    { "DISPLAY_BASE_ADDR",     0x023c },
    { "MC_FB_LOCATION",        0x0148 }
};

unsigned long
osrdn_peek(vm_address_t base, int which)
{
    if (which < 0 || which >= OSRDN_PEEK_COUNT)
        return 0xffffffffUL;
    return rdnMmioRead32(base, osrdnPeek[which].offset);
}

/* ---- one accessor each, so the write set is the table ---------------------- */

unsigned long
osrdn_mmio_get(vm_address_t base, int which)
{
    if (which < 0 || which >= OSRDN_SNAP_MMIO_COUNT)
        return 0xffffffffUL;
    return rdnMmioRead32(base, osrdnSnapMmio[which].offset);
}

void
osrdn_mmio_put(vm_address_t base, int which, unsigned long value)
{
    if (which < 0 || which >= OSRDN_SNAP_MMIO_COUNT)
        return;
    rdnMmioWrite32(base, osrdnSnapMmio[which].offset, value);
}

unsigned long
osrdn_pll_get(vm_address_t base, int which)
{
    unsigned long index;

    if (which < 0 || which >= OSRDN_SNAP_PLL_COUNT)
        return 0xffffffffUL;
    index = (unsigned long)osrdnSnapPll[which].offset & PLL_INDEX_MASK;
    rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));
    return rdnMmioRead32(base, REG_CLOCK_CNTL_DATA);
}

unsigned long
osrdn_pll_peek(vm_address_t base, int which)
{
    unsigned long saved, value;

    if (which < 0 || which >= OSRDN_PLL_PEEK_COUNT)
        return 0xffffffffUL;
    saved = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
    if (saved & PLL_WR_EN)
        return 0xffffffffUL;
    rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX,
                  (unsigned char)(osrdnPllPeek[which].offset & PLL_INDEX_MASK));
    value = rdnMmioRead32(base, REG_CLOCK_CNTL_DATA);
    rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(saved & 0xffUL));
    return value;
}

void
osrdn_pll_put(vm_address_t base, int which, unsigned long value)
{
    unsigned long index;

    if (which < 0 || which >= OSRDN_SNAP_PLL_COUNT)
        return;
    index = (unsigned long)osrdnSnapPll[which].offset & PLL_INDEX_MASK;
    rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index | PLL_WR_EN));
    rdnMmioWrite32(base, REG_CLOCK_CNTL_DATA, value);
    rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX, (unsigned char)(index & PLL_INDEX_MASK));
}

/* ---- the snapshot --------------------------------------------------------- */

static void
vgaTake(osrdn_snap *snap)
{
    unsigned int    crtcPort;
    unsigned int    statusPort;
    int             s;
    int             k;
    unsigned char   pas;

    snap->vgaMisc = osrdn_inb((IOEISAPortAddress)VGA_MISC_READ);
    if (snap->vgaMisc == 0xff)
        return;                 /* not decoded: the caller refuses (SNAP_WHY_VGA_DECODE) */
    crtcPort = (snap->vgaMisc & 0x01) ? VGA_CRTC_COLOR : VGA_CRTC_MONO;
    snap->crtcPort = crtcPort;
    statusPort = crtcPort + VGA_STATUS_OFFSET;

    for (k = 0; k < OSRDN_SNAP_SEQ; k++) {
        osrdn_outb((IOEISAPortAddress)VGA_SEQ_INDEX, (unsigned char)k);
        snap->vgaSeq[k] = osrdn_inb((IOEISAPortAddress)VGA_SEQ_DATA);
    }
    for (k = 0; k < OSRDN_SNAP_CRTC; k++) {
        osrdn_outb((IOEISAPortAddress)crtcPort, (unsigned char)k);
        snap->vgaCrtc[k] = osrdn_inb((IOEISAPortAddress)(crtcPort + 1));
    }
    for (k = 0; k < OSRDN_SNAP_GR; k++) {
        osrdn_outb((IOEISAPortAddress)VGA_GR_INDEX, (unsigned char)k);
        snap->vgaGr[k] = osrdn_inb((IOEISAPortAddress)VGA_GR_DATA);
    }
    /* The attribute controller.
     *
     * ATTR 0x00-0x0F are the sixteen internal palette entries, and the palette
     * address source bit (index bit 5) decides who owns them: with PAS = 0 the
     * CPU can read and write them and the display shows the overscan colour;
     * with PAS = 1 the video stream is using them, CPU writes are inhibited
     * and READS ARE INVALID (ref/G400SPEC_Jun1999.txt 12087, where the bit is
     * marked "VGA.", i.e. the standard one; that implementation returns all
     * ones).  0x10-0x14 are not palette entries and are not gated -- this
     * machine read them with PAS set (R2b-0 record, attri=20 attr=0100030000).
     *
     * This loop used to OR the console's PAS into every index, so the sixteen
     * palette entries were read while they were not readable, and the revert
     * then wrote those values back.  The first whole-snapshot read-back on the
     * machine is what showed it: seven bytes that did not come back, every
     * named one inside 0x00-0x0F (2026-09-16, docs/R2C_REVERT_PLAN.md 16).
     *
     * The bit goes back before this returns, and the whole transaction is one
     * splhigh section: while PAS is clear the screen is the overscan colour,
     * and being interrupted in the middle could leave it there.  Nothing here
     * waits, so this raises no clock-reading question.
     */
    s = splhigh();
    osrdn_inb((IOEISAPortAddress)statusPort);
    pas = osrdn_inb((IOEISAPortAddress)VGA_ATTR_INDEX);
    osrdn_inb((IOEISAPortAddress)statusPort);
    osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, 0x00);        /* PAS off to read */
    for (k = 0; k < OSRDN_SNAP_ATTR; k++) {
        osrdn_inb((IOEISAPortAddress)statusPort);
        osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, (unsigned char)k);
        snap->vgaAttr[k] = osrdn_inb((IOEISAPortAddress)VGA_ATTR_READ);
    }
    osrdn_inb((IOEISAPortAddress)statusPort);
    osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, pas);
    splx(s);
    snap->vgaAttrPas = pas;
    snap->vgaTaken = 1;
}

int
osrdn_snap_take(vm_address_t base, osrdn_snap *snap)
{
    int             k;
    unsigned long   p;

    for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
        snap->mmio[k] = 0;
    for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
        snap->pll[k] = 0;
    for (k = 0; k < OSRDN_SNAP_PALETTE; k++)
        snap->palette[k] = 0;
    snap->valid = 0;
    snap->why = SNAP_WHY_NONE;
    snap->vgaTaken = 0;
    snap->crtcPort = 0;

    if (base == 0) {
        snap->why = SNAP_WHY_NO_BASE;
        return 0;
    }

    /* the PLL index must be idle before any index byte is written */
    p = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
    if (p & PLL_WR_EN) {
        snap->why = SNAP_WHY_PLL_BUSY;
        return 0;
    }

    for (k = 0; k < OSRDN_SNAP_MMIO_COUNT; k++)
        snap->mmio[k] = rdnMmioRead32(base, osrdnSnapMmio[k].offset);
    for (k = 0; k < OSRDN_SNAP_PLL_COUNT; k++)
        snap->pll[k] = osrdn_pll_get(base, k);

    /* put the PLL index back the way the boot left it */
    rdnMmioWrite8(base, REG_CLOCK_CNTL_INDEX,
                  (unsigned char)(snap->mmio[SNAP_CLOCK_CNTL_INDEX] & LOW_BYTE));
    p = rdnMmioRead32(base, REG_CLOCK_CNTL_INDEX);
    if ((p & LOW_BYTE) != (snap->mmio[SNAP_CLOCK_CNTL_INDEX] & LOW_BYTE)) {
        snap->why = SNAP_WHY_PLL_INDEX;
        return 0;
    }

    for (k = 0; k < OSRDN_SNAP_PALETTE; k++) {
        rdnMmioWrite32(base, REG_PALETTE_INDEX, (unsigned long)k);
        snap->palette[k] = rdnMmioRead32(base, REG_PALETTE_30_DATA);
    }

    vgaTake(snap);
    if (!snap->vgaTaken) {
        snap->why = SNAP_WHY_VGA_DECODE;
        return 0;
    }
    snap->valid = 1;
    return 1;
}

/* ---- writing back --------------------------------------------------------- */

void
osrdn_palette_put(vm_address_t base, int first, int count, const unsigned long *values)
{
    int k;

    for (k = 0; k < count; k++) {
        rdnMmioWrite32(base, REG_PALETTE_INDEX, (unsigned long)(first + k));
        rdnMmioWrite32(base, REG_PALETTE_30_DATA, values[k]);
    }
}

void
osrdn_palette_get(vm_address_t base, int first, int count, unsigned long *values)
{
    int k;

    for (k = 0; k < count; k++) {
        rdnMmioWrite32(base, REG_PALETTE_INDEX, (unsigned long)(first + k));
        values[k] = rdnMmioRead32(base, REG_PALETTE_30_DATA);
    }
}

void
osrdn_vga_put(const osrdn_snap *snap)
{
    unsigned int    crtcPort;
    unsigned int    statusPort;
    int             k;

    if (!snap->vgaTaken)
        return;
    crtcPort = snap->crtcPort;
    statusPort = crtcPort + VGA_STATUS_OFFSET;

    /* sequencer reset and screen off while the rest goes back */
    osrdn_outb((IOEISAPortAddress)VGA_SEQ_INDEX, 0x00);
    osrdn_outb((IOEISAPortAddress)VGA_SEQ_DATA, 0x01);
    osrdn_outb((IOEISAPortAddress)VGA_SEQ_INDEX, 0x01);
    osrdn_outb((IOEISAPortAddress)VGA_SEQ_DATA, (unsigned char)(snap->vgaSeq[1] | 0x20));

    osrdn_outb((IOEISAPortAddress)VGA_MISC_WRITE, snap->vgaMisc);
    for (k = 2; k < OSRDN_SNAP_SEQ; k++) {
        osrdn_outb((IOEISAPortAddress)VGA_SEQ_INDEX, (unsigned char)k);
        osrdn_outb((IOEISAPortAddress)VGA_SEQ_DATA, snap->vgaSeq[k]);
    }

    /* CR11 bit 7 protects CR0-CR7 */
    osrdn_outb((IOEISAPortAddress)crtcPort, 0x11);
    osrdn_outb((IOEISAPortAddress)(crtcPort + 1), (unsigned char)(snap->vgaCrtc[0x11] & 0x7f));
    for (k = 0; k < OSRDN_SNAP_CRTC; k++) {
        osrdn_outb((IOEISAPortAddress)crtcPort, (unsigned char)k);
        osrdn_outb((IOEISAPortAddress)(crtcPort + 1), snap->vgaCrtc[k]);
    }

    for (k = 0; k < OSRDN_SNAP_GR; k++) {
        osrdn_outb((IOEISAPortAddress)VGA_GR_INDEX, (unsigned char)k);
        osrdn_outb((IOEISAPortAddress)VGA_GR_DATA, snap->vgaGr[k]);
    }

    osrdn_inb((IOEISAPortAddress)statusPort);
    for (k = 0; k < OSRDN_SNAP_ATTR; k++) {
        osrdn_inb((IOEISAPortAddress)statusPort);
        osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, (unsigned char)k);
        osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, snap->vgaAttr[k]);
    }

    /* sequencer 1 as it was, then SEQ0 from the snapshot with both reset bits
       released.  Not a bare 0x03: that would throw away whatever else the
       console had in SEQ0.  Not the raw snapshot either: if it somehow held a
       reset bit clear, the sequencer would stay in reset and the screen would
       be black.  (The simulator caught the bare-0x03 version.) */
    osrdn_outb((IOEISAPortAddress)VGA_SEQ_INDEX, 0x01);
    osrdn_outb((IOEISAPortAddress)VGA_SEQ_DATA, snap->vgaSeq[1]);
    osrdn_outb((IOEISAPortAddress)VGA_SEQ_INDEX, 0x00);
    osrdn_outb((IOEISAPortAddress)VGA_SEQ_DATA, (unsigned char)(snap->vgaSeq[0] | 0x03));
    osrdn_inb((IOEISAPortAddress)statusPort);
    osrdn_outb((IOEISAPortAddress)VGA_ATTR_INDEX, VGA_PAS);
}
