/*
 * OSRDNMesaPresent.c - the SDL2 present contract over the driver's PRESENT
 * ioctl (G3, docs/G3_PRESENT_PLAN.md 2-2).
 *
 * WHAT A ROW COSTS IS THE POINT.  SDL stamps a frame a row at a time, in
 * reverse (SDL_openstepvideo.m 2560-2598), so this is called 600 times for an
 * 800x600 window.  Each call is one ioctl; the device is opened once when
 * present mode goes on and held until it goes off (the driver logs every open
 * and admits one holder), and the triangle path shares that descriptor.
 *
 * THE CURRENT CONTEXT MUST OWN THE SURFACE.  The Matrox library answers for
 * "the" surface; here a second, software context asking these questions gets
 * "no surface" rather than the first context's picture (codex, 2026-09-26).
 */
#include "OSRDNMesaPresent.h"
#include "OSRDNMesaSurface.h"
#include "OSRDNMesaTri.h"
#include "osrdn_r7b.h"
#include "OSRDNMesaTime.h"          /* G5-0: the frame-budget instrument */
#include "OSRDNMesaWindow.h"        /* G5-1c: where the server draws our window */

extern int ioctl(int, int, char *);
extern void *OSMesaGetCurrentContext(void);     /* osmesa.c 705; the owner key (1994) */

static osrdn_present_counts presentCounts;
static void presentFrameReset(void);            /* G5-1b/1c: defined with the frame state below */
static int presentOn;                           /* PresentMode(1) in force */
static const void *presentOwner;                /* the context that turned it on */

static int
presentOwned(void)
{
    const void *ctx = OSMesaGetCurrentContext();

    if (ctx == 0 || !osrdn_surf_bound_to(ctx)) {
        presentCounts.notOwner++;
        return 0;
    }
    return 1;
}

int
osrdn_present_active(void)
{
    if (!presentOn)
        return 0;
    /* the owner may have let the surface go since: then nothing is stood down */
    return osrdn_surf_bound_to(presentOwner) ? 1 : 0;
}

unsigned long
OSRDNMesaBufferOrigin(void)
{
    return presentOwned() ? 1UL : 0UL;
}

void
OSRDNMesaBufferPresentMode(int on)
{
    if (on) {
        if (!presentOwned())
            return;
        if (!presentOn) {
            presentCounts.modeOn++;
            presentOn = 1;
            presentOwner = OSMesaGetCurrentContext();
            osrdn_tri_hold_set(1);              /* one open for the whole run of rows */
            presentFrameReset();                /* G5-1b/1c: nothing known about this run of frames */
        }
        return;
    }
    if (presentOn) {
        presentCounts.modeOff++;
        presentOn = 0;
        presentOwner = 0;
        osrdn_tri_hold_set(0);
    }
}

static int presentBlit(unsigned long srcX, unsigned long srcY, unsigned long w, unsigned long h,
                       unsigned long dstX, unsigned long dstY, unsigned long *outVerdict);

/* G5-1b: the whole-surface blit a frame's first row call turned into, so the
   rows that follow can be answered without an ioctl */
static struct {
    int valid;
    unsigned long dstX, dstY, w, h;
} presentCover;

/*
 * G5-1b: the rows of the frame in progress.  A frame's first row says where the
 * BOTTOM of the window is, not how tall the stamp is: SDL clips a window that
 * hangs off the bottom of the screen to ph < H rows, and the first row then
 * lands at the screen's last row exactly as an unclipped window ending there
 * would.  So a frame is blitted whole only when the PREVIOUS frame was seen to
 * be whole -- H consecutive rows, same first destination, same x and width --
 * and the first frame after a move, a resize or a clip goes row by row (one
 * frame at the old cost, always the right picture).
 */
static struct {
    unsigned long rows;         /* consecutive rows seen since the frame's first */
    unsigned long firstDstY;    /* where its first row landed */
    unsigned long dstX, w;
} presentRun;

/*
 * G5-1c (docs/G5_1C_PRESENT_SERVER_POSITION_PLAN.md 1-1): SDL's destination lags a
 * server-side drag, so the frame is put where the SERVER says the window is.
 * At a steady moment -- two whole frames in a row with the same SDL origin and
 * the same server frame -- the pair is recorded; from then on each whole frame
 * is shifted by the server frame's movement since (x plus, y minus: PostScript
 * y grows upward).  A new SDL origin (SDL caught up with a move) drops the
 * calibration and waits for the next steady moment.  presentShift is the
 * frame's shift, applied to every row of the frame.
 */
static struct {
    int valid;                      /* calibrated */
    int number;                     /* our window, 0 = not found yet */
    unsigned long sdlX, sdlTop;     /* SDL's origin at calibration */
    float bx, by, bw, bh;           /* the server frame then */
    /* the steady-state watch */
    int seen;                       /* a server frame has been seen */
    unsigned long steady;           /* queries in a row with the same server frame (capped at 2) */
    float lastBx, lastBy;
    int sdlSeen;                    /* an SDL origin has been seen */
    unsigned long lastSdlX, lastSdlTop;
} presentCal;
static long presentShiftX, presentShiftY;

static void
presentFrameReset(void)
{
    presentRun.rows = 0UL;
    presentCover.valid = 0;
    /* the calibration and the moving watch survive a mode toggle: SDL turns the
       stamp off and on around every refused frame, and a drag refuses many */
}

/* the server frame of our window, timed; 0 when there is no query or it failed */
static int
presentServerFrame(unsigned long W, unsigned long H, osrdn_window_bounds *b)
{
    osrdn_time_stamp t;
    int timed = osrdn_time_on();
    int ok;

    if (!osrdn_window_ready())
        return 0;
    if (timed)
        osrdn_time_now(&t);
    ok = (presentCal.number != 0) ? osrdn_window_bounds_of(presentCal.number, b) : 0;
    if (!ok || b->w - (float) W < 0.0F || b->w - (float) W > 16.0F ||
        b->h - (float) H < 0.0F || b->h - (float) H > 48.0F) {
        /* not ours any more (or not yet): find it again */
        ok = osrdn_window_find(W, H, b);
        presentCal.number = ok ? b->number : 0;
        if (ok)
            presentCounts.windowFinds++;
    }
    if (timed)
        osrdn_time_add(OSRDN_TIME_QUERY, &t);
    return ok;
}

/*
 * A whole frame's first row: decide this frame's shift.  Returns 0 to refuse
 * the frame (E_BUSY): the window is MOVING -- its server frame differs from
 * the last query's -- or it could not be found.  A refused frame goes to the
 * screen through AppKit (SDL releases the stamp for that frame), which is the
 * one path that cannot leave a ghost, so nothing is stamped while the user
 * drags; the stamps resume when the frame has stood still for two queries.
 * (glwin stands down while `moving` too, openstep-mga-glwin.m 548-580.)
 */
static int
presentShiftFor(unsigned long W, unsigned long H, unsigned long sdlX, unsigned long sdlTop)
{
    osrdn_window_bounds b;
    int moving, sdlSame;

    presentShiftX = 0L;
    presentShiftY = 0L;
    if (!osrdn_window_ready())
        return 1;                           /* no query here: SDL's destination as it is */
    if (!presentServerFrame(W, H, &b)) {
        presentCal.valid = 0;
        presentCal.seen = 0;
        presentCounts.windowLost++;
        return 0;
    }
    moving = presentCal.seen && (b.x != presentCal.lastBx || b.y != presentCal.lastBy);
    presentCal.seen = 1;
    presentCal.lastBx = b.x;
    presentCal.lastBy = b.y;
    if (moving) {
        presentCal.steady = 0;
        presentCounts.moving++;
        return 0;
    }
    if (presentCal.steady < 2UL)
        presentCal.steady++;
    sdlSame = presentCal.sdlSeen && sdlX == presentCal.lastSdlX && sdlTop == presentCal.lastSdlTop;
    presentCal.sdlSeen = 1;
    presentCal.lastSdlX = sdlX;
    presentCal.lastSdlTop = sdlTop;
    if (presentCal.valid && sdlX == presentCal.sdlX && sdlTop == presentCal.sdlTop) {
        /* SDL still says where it said at calibration: follow the server from there */
        presentShiftX = (long)(b.x - presentCal.bx);
        presentShiftY = -(long)(b.y - presentCal.by);
        if (presentShiftX != 0L || presentShiftY != 0L)
            presentCounts.shifted++;
        return 1;
    }
    if (presentCal.valid && (long) sdlX == (long) presentCal.sdlX + (long)(b.x - presentCal.bx) &&
        (long) sdlTop == (long) presentCal.sdlTop - (long)(b.y - presentCal.by)) {
        /* SDL caught up, and agrees with the server: the pair moves as one */
        presentCal.sdlX = sdlX;
        presentCal.sdlTop = sdlTop;
        presentCal.bx = b.x;
        presentCal.by = b.y;
        presentCounts.calibrations++;
        return 1;
    }
    /* not calibrated, or SDL says something the server does not: the pair is
       taken only once the window has stood still for two queries and SDL's
       origin has been the same for two frames -- and until then the frame is
       refused, because SDL's origin alone may be the vacated place */
    presentCal.valid = 0;
    if (presentCal.steady >= 2UL && sdlSame) {
        presentCal.valid = 1;
        presentCal.sdlX = sdlX;
        presentCal.sdlTop = sdlTop;
        presentCal.bx = b.x;
        presentCal.by = b.y;
        presentCal.bw = b.w;
        presentCal.bh = b.h;
        presentCounts.calibrations++;
        return 1;
    }
    presentCounts.unsettled++;
    return 0;
}

int
OSRDNMesaBufferPresentRect(unsigned long srcX, unsigned long srcY,
                           unsigned long w, unsigned long h,
                           long dstX, long dstY, unsigned long *outVerdict)
{
    if (outVerdict != 0)
        *outVerdict = OSRDN_PRESENT_E_MODE;
    if (dstX < 0 || dstY < 0 || !presentOwned())
        return -1;
    /*
     * G5-1b (docs/G5_1B_PRESENT_ONE_BLIT_PLAN.md 1): THE SURFACE IS TOP-DOWN when
     * the hook drew it in present mode, so surface row s is screen row s and the
     * frame can go in one blit.  SDL still asks a row at a time, bottom row
     * first (its row k is source row k to destination dstY0 + H - 1 - k): the
     * first call of a frame -- source row 0, a full-width row, landing at least
     * H - 1 rows down the screen -- becomes the blit of rows 0..H-1 to
     * dstY - (H - 1) .. dstY, and every later row that this blit already put on
     * the screen is answered from the record.  Any other call in flipped mode
     * (a partial rectangle, or a first row the kernel refused) blits its one
     * row from H - 1 - srcY, which is where that row's pixels are now.
     */
    if (osrdn_surf_flipped() && h == 1UL) {
        const osrdn_surf_counts *sc = OSRDNMesaSurfaceCounts();
        unsigned long H = sc->height, W = sc->width;
        long sx, sy;

        if (srcY >= H)
            return -1;
        if (srcY == 0UL) {
            /* a frame's first row: whole only if the last frame was whole, here */
            int whole = (H > 1UL && srcX == 0UL && w == W && (unsigned long) dstY >= H - 1UL &&
                         presentRun.rows == H && presentRun.firstDstY == (unsigned long) dstY &&
                         presentRun.dstX == (unsigned long) dstX && presentRun.w == w);

            presentRun.rows = 1UL;
            presentRun.firstDstY = (unsigned long) dstY;
            presentRun.dstX = (unsigned long) dstX;
            presentRun.w = w;
            presentCover.valid = 0;
            presentShiftX = 0L;
            presentShiftY = 0L;
            if (whole) {
                unsigned long top = (unsigned long) dstY - (H - 1UL);

                /* G5-1c: where the server has the window now */
                if (!presentShiftFor(W, H, (unsigned long) dstX, top)) {
                    presentCounts.refused[OSRDN_PRESENT_E_BUSY]++;
                    if (outVerdict != 0)
                        *outVerdict = OSRDN_PRESENT_E_BUSY;
                    return -1;
                }
                sx = dstX + presentShiftX;
                sy = (long) top + presentShiftY;
                if (sx >= 0L && sy >= 0L) {
                    int rc = presentBlit(0UL, 0UL, W, H, (unsigned long) sx, (unsigned long) sy, outVerdict);

                    if (rc == 0) {
                        presentCover.valid = 1;
                        presentCover.dstX = (unsigned long) sx;
                        presentCover.dstY = (unsigned long) sy;
                        presentCover.w = W;
                        presentCover.h = H;
                        presentCounts.coalesced++;
                        return 0;
                    }
                }
                /* refused, or shifted off the screen: the rows go one by one below */
            }
        } else {
            /* the run continues only as SDL walks it: the next source row, one
               destination row up, same x and width */
            if (presentRun.rows == srcY && (unsigned long) dstX == presentRun.dstX && w == presentRun.w &&
                presentRun.firstDstY >= srcY && (unsigned long) dstY == presentRun.firstDstY - srcY)
                presentRun.rows++;
            else
                presentRun.rows = 0UL;
            sx = dstX + presentShiftX;
            sy = dstY + presentShiftY;
            if (presentCover.valid && srcX == 0UL && w == presentCover.w && sx >= 0L && sy >= 0L &&
                (unsigned long) sx == presentCover.dstX &&
                (unsigned long) sy >= presentCover.dstY &&
                (unsigned long) sy - presentCover.dstY == H - 1UL - srcY) {
                presentCounts.covered++;
                presentCounts.ok++;
                if (outVerdict != 0)
                    *outVerdict = OSRDN_PRESENT_OK;
                return 0;
            }
        }
        sx = dstX + presentShiftX;
        sy = dstY + presentShiftY;
        if (sx < 0L || sy < 0L) {
            presentCounts.refused[OSRDN_PRESENT_E_DST]++;
            if (outVerdict != 0)
                *outVerdict = OSRDN_PRESENT_E_DST;
            return -1;
        }
        presentCounts.rowFallback++;
        return presentBlit(srcX, H - 1UL - srcY, w, 1UL, (unsigned long) sx, (unsigned long) sy, outVerdict);
    }
    return presentBlit(srcX, srcY, w, h, (unsigned long) dstX, (unsigned long) dstY, outVerdict);
}

static int
presentBlit(unsigned long srcX, unsigned long srcY, unsigned long w, unsigned long h,
            unsigned long dstX, unsigned long dstY, unsigned long *outVerdict)
{
    osrdn_r7b_present b;
    int fd, rc;

    b.magic = OSRDN_PRESENT_MAGIC;
    b.version = OSRDN_PRESENT_VERSION;
    b.srcOrg = 0UL;                             /* the colour surface: window offset 0 */
    b.srcStride = osrdn_surf_stride();
    b.srcX = srcX;
    b.srcY = srcY;
    b.w = w;
    b.h = h;
    b.dstX = dstX;
    b.dstY = dstY;
    b.status = 0UL;
    b.verdict = 0UL;
    if ((fd = osrdn_tri_device_open()) < 0) {
        presentCounts.noDevice++;
        return -1;
    }
    {
        osrdn_time_stamp t;
        int timed = osrdn_time_on();            /* G5-0: one row's ioctl, and the frame boundary */

        if (timed)
            osrdn_time_now(&t);
        rc = ioctl(fd, (int)OSRDN_R7B_IOC_PRESENT, (char *)&b);
        if (timed) {
            osrdn_time_add(OSRDN_TIME_PRESENT, &t);
            osrdn_time_count(OSRDN_TIME_PRESENT, h);
            osrdn_time_frame_present(b.dstY);
        }
    }
    osrdn_tri_device_close(fd);
    presentCounts.rects++;
    if (rc != 0) {
        presentCounts.ioctlFailed++;
        return -1;
    }
    presentCounts.lastVerdict = b.verdict;
    if (outVerdict != 0)
        *outVerdict = b.verdict;
    if (b.status == 0UL) {
        presentCounts.ok++;
        return 0;
    }
    if (b.verdict < (unsigned long)OSRDN_PRESENT_VERDICT_COUNT)
        presentCounts.refused[b.verdict]++;
    return -1;
}

const osrdn_present_counts *
OSRDNMesaPresentCounts(void)
{
    return &presentCounts;
}

const char *
OSRDNMesaPresentVerdictName(unsigned long verdict)
{
    static const char *const names[OSRDN_PRESENT_VERDICT_COUNT] = {
        "OK", "MAGIC", "SRC", "DST", "GEOM", "BUSY", "LATCH", "MODE"
    };

    return (verdict < (unsigned long)OSRDN_PRESENT_VERDICT_COUNT) ? names[verdict] : "?";
}
