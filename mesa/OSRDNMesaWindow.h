/*
 * OSRDNMesaWindow.h - G5-1c: where the window server is drawing THIS application's
 * window, right now (docs/G5_1C_PRESENT_SERVER_POSITION_PLAN.md 1-1).
 *
 * WHY.  The present stamps pixels the window server does not know about.  SDL
 * gives the destination from its own cached window position, and that cache
 * lags a server-side drag: the stamps of those frames land on the vacated
 * screen area and stay there as a ghost (nobody repaints what nobody drew).
 * The Matrox glwin demo cured the same trail by asking the server itself,
 * with PScurrentwindowbounds of ITS OWN window (openstep-mga-glwin.m 486-496).
 *
 * HOW, WITHOUT LINKING ANYTHING.  Every symbol is looked up at run time
 * (NSIsSymbolNameDefined / NSLookupAndBindSymbol, mach-o/dyld.h 102-108): a
 * program without AppKit -- the offscreen probes -- gets "no window" and
 * presents as before.  _dyld_lookup_and_bind is NOT used: it kills the
 * process on a missing symbol (build/g51c/dyt.c).
 *
 * WHICH WINDOW.  Not the front window (PSfrontwindow returns server-global
 * numbers, a menu or a panel can be in front, and PScurrentwindowbounds wants
 * the application's LOCAL number: build/g51c/winprobe.m saw front=39 for our
 * window 4, and the context's screen list 180 179 raise rangecheck when asked
 * for bounds).  The application's own list is the answer: NSApp -> windows ->
 * windowNumber for each, through objc_msgSend bound at run time -- winprobe
 * listed [2 menu 256x128] [3 193x208] [4 vis 642x504 = ours] [7 icon 64x64]
 * ... with no exception.  Ours is the visible one whose frame is the surface
 * plus a title bar and borders.
 *
 * COORDINATES.  The bounds are the window FRAME in PostScript screen space
 * (origin bottom-left, y up): a 640 x 480 content at (200,200) is the frame
 * (199,199) 642 x 504.  Only DIFFERENCES of bounds are used, so no offset,
 * screen height or title height is needed.
 */
#ifndef OSRDN_MESA_WINDOW_H
#define OSRDN_MESA_WINDOW_H

typedef struct {
    int   number;                   /* the application's window number, 0 = none found */
    float x, y, w, h;               /* its frame, PostScript screen space */
} osrdn_window_bounds;

typedef struct {
    unsigned long binds;            /* the symbols were looked up and found */
    unsigned long noSymbols;        /* looked up and not found (no AppKit here) */
    unsigned long finds;            /* our window identified from the application's list */
    unsigned long findFailed;       /* the list had no single visible window of the expected size */
    unsigned long queries;          /* bounds asked */
    unsigned long queryFailed;
} osrdn_window_counts;

/* 1 when AppKit, the ObjC runtime and the DPS operator are in this process (decided once) */
int osrdn_window_ready(void);
/* the visible window of this application whose frame is contentW x contentH plus a
   title bar and borders (frame w - contentW in [0, 16], frame h - contentH in [0, 48]);
   0 when there is none or more than one */
int osrdn_window_find(unsigned long contentW, unsigned long contentH, osrdn_window_bounds *out);
/* the current frame of the application's window `number`; 0 on failure */
int osrdn_window_bounds_of(int number, osrdn_window_bounds *out);
const osrdn_window_counts *OSRDNMesaWindowCounts(void);

#endif
