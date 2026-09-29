/*
 * OSRDNMesaDepth.c - see OSRDNMesaDepth.h.  Plain C89, no libc, no Mesa headers.
 *
 * It maps nothing: the one window OSRDNMesaSurface.c mapped is the one the
 * depth buffer lives in, and this unit asks for its base.  Keeping the mapping
 * count at one is an invariant the build gate reads.
 */

#include "OSRDNMesaDepth.h"
#include "OSRDNMesaSurface.h"
#include "OSRDNMesaTriTable.h"
#include "OSRDNMesaTri.h"        /* G3b: the device, held or opened */
#include "osrdn_r7b.h"          /* G3b: the clear block */
#include "OSRDNMesaTime.h"      /* G5-0: the frame-budget instrument */
extern int ioctl(int, int, char *);

static osrdn_depth_counts depthCounts;

const osrdn_depth_counts *
OSRDNMesaDepthCounts(void)
{
    return &depthCounts;
}

const char *
OSRDNMesaDepthWhyName(int why)
{
    static const char *names[OSRDN_DEPTH_REASONS] = {
        "-", "NO_WINDOW", "ARGS", "READBACK"
    };

    if (why < 0 || why >= OSRDN_DEPTH_REASONS)
        return "?";
    return names[why];
}

long
osrdn_depth_at(int x, int y)
{
    if (x < 0 || y < 0 || x >= OSRDN_TRI_DEPTH_W || y >= OSRDN_TRI_DEPTH_H)
        return -1L;
    return (long)osrdnDepthAt[y * OSRDN_TRI_DEPTH_W + x];
}

long
osrdn_depth_get(int x, int y)
{
    unsigned long winBytes = 0UL;
    unsigned char *win = (unsigned char *)osrdn_surf_window(&winBytes);
    unsigned long a;

    if (x < 0 || y < 0 || x >= OSRDN_TRI_DEPTH_W || y >= OSRDN_TRI_DEPTH_H)
        return -1L;
    (void)osrdn_tri_retire_if_inflight();     /* G5-2: the depth the card has finished writing */
    if (win == 0 ||
        winBytes < OSRDN_TRI_DEPTH_BYTE_OFF + (unsigned long)OSRDN_TRI_DEPTH_BYTES)
        return -1L;
    a = OSRDN_TRI_DEPTH_BYTE_OFF +
        (unsigned long)osrdnDepthAt[y * OSRDN_TRI_DEPTH_W + x];
    return (long)((unsigned long)win[a] | ((unsigned long)win[a + 1] << 8));
}


/*
 * G3b (docs/G3B_CLEAR_PLAN.md 2-3): THE CARD CLEARS.  This used to write the
 * depth buffer through the mapped window from the CPU -- 243k uncached words
 * for 800x600, about 250 ms a frame (boot 4) -- and read it back.  The
 * reference clears with the engine (radeon_cp_dispatch_clear), and the kernel
 * now builds that clear itself (CP_OP_CLEAR); the window offsets and pitches
 * here are the layout's, the same the prologue hands the triangles.
 */
static unsigned long
depthFloatBits(unsigned long value16)       /* value / 65536 as IEEE single: the vertex z the card floors back to value */
{
    union { float f; unsigned long u; } x;

    x.f = (float)value16 / 65536.0f;
    return x.u;
}

int
osrdn_card_clear(unsigned long flags, unsigned long colour, unsigned long depth16,
                 int width, int height, int *why)
{
    osrdn_r7b_clear b;
    int fd, rc;

    if (why != 0)
        *why = OSRDN_DEPTH_OK;
    if (depth16 > 0xffffUL || width <= 0 || height <= 0 ||
        width > OSRDN_TRI_SURF_MAX_W || height > OSRDN_TRI_SURF_MAX_H ||
        flags == 0UL || (flags & ~(OSRDN_CLEAR_COLOUR | OSRDN_CLEAR_DEPTH)) != 0UL) {
        depthCounts.refused[OSRDN_DEPTH_ARGS]++;
        if (why != 0)
            *why = OSRDN_DEPTH_ARGS;
        return 0;
    }
    if (osrdn_surf_stride() == 0UL) {
        depthCounts.refused[OSRDN_DEPTH_NO_WINDOW]++;
        if (why != 0)
            *why = OSRDN_DEPTH_NO_WINDOW;
        return 0;
    }
    b.magic = OSRDN_CLEAR_MAGIC;
    b.version = OSRDN_CLEAR_VERSION;
    b.flags = flags;
    b.colourOff = 0UL;                          /* the colour surface: window offset 0 */
    b.colourPitch = osrdn_surf_stride();
    b.colourValue = colour;
    b.depthOff = OSRDN_TRI_DEPTH_BYTE_OFF;
    b.depthPitch = ((unsigned long)width + 31UL) & ~31UL;
    b.depthZ = depthFloatBits(depth16);
    b.w = (unsigned long)width;
    b.h = (unsigned long)height;
    b.status = 0UL;
    b.verdict = 0UL;
    if ((fd = osrdn_tri_device_open()) < 0) {
        depthCounts.refused[OSRDN_DEPTH_CARD]++;
        if (why != 0)
            *why = OSRDN_DEPTH_CARD;
        return 0;
    }
    {
        osrdn_time_stamp t;
        int timed = osrdn_time_on();            /* G5-0: the ioctl alone; one clear a frame */

        if (timed)
            osrdn_time_now(&t);
        rc = ioctl(fd, (int)OSRDN_R7B_IOC_CLEAR, (char *)&b);
        if (timed) {
            osrdn_time_add(OSRDN_TIME_CLEAR, &t);
            osrdn_time_frame_clear();
        }
    }
    osrdn_tri_device_close(fd);
    depthCounts.lastVerdict = (rc == 0) ? b.verdict : ~0UL;
    if (rc != 0 || b.status != 0UL) {
        depthCounts.refused[OSRDN_DEPTH_CARD]++;
        if (why != 0)
            *why = OSRDN_DEPTH_CARD;
        return 0;
    }
    if (flags & OSRDN_CLEAR_DEPTH) {
        depthCounts.clears++;
        depthCounts.pixels += (unsigned long)width * (unsigned long)height;
        depthCounts.lastValue = depth16;
    }
    if (flags & OSRDN_CLEAR_COLOUR)
        depthCounts.colourClears++;
    return 1;
}

int
osrdn_depth_clear(unsigned long value, int width, int height, int *why)
{
    return osrdn_card_clear(OSRDN_CLEAR_DEPTH, 0UL, value, width, height, why);
}

int
osrdn_colour_clear(unsigned long colour, int width, int height, int *why)
{
    return osrdn_card_clear(OSRDN_CLEAR_COLOUR, colour, 0UL, width, height, why);
}
