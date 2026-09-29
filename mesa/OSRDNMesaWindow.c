/*
 * OSRDNMesaWindow.c - G5-1c: the server's own account of where our window is.
 * See the header.  No libc headers, as the rest of the library.
 */
#include "OSRDNMesaWindow.h"

/* the dynamic linker's symbol lookup (mach-o/dyld.h 102-108): "defined" answers
   without binding, so a missing AppKit is an ordinary no, not an abort */
extern int NSIsSymbolNameDefined(const char *);
extern void *NSLookupAndBindSymbol(const char *);
extern void *NSAddressOfSymbol(void *);

typedef void *(*osrdnObjcSend)(void *self, void *sel, ...);       /* objc_msgSend */
typedef void *(*osrdnObjcSel)(const char *name);                  /* sel_getUid */
typedef void (*osrdnPsWindowBounds)(int num, float *x, float *y, float *w, float *h);   /* psopsNeXT.h 128 */

static osrdn_window_counts winCounts;
static int winReady = -1;
static void **winNSApp;                 /* the global `id NSApp` */
static osrdnObjcSend winSend;
static osrdnObjcSel winSel;
static osrdnPsWindowBounds winBounds;

static void *
winBind(const char *name)
{
    if (!NSIsSymbolNameDefined(name))
        return 0;
    return NSAddressOfSymbol(NSLookupAndBindSymbol(name));
}

int
osrdn_window_ready(void)
{
    if (winReady < 0) {
        winNSApp  = (void **)             winBind("_NSApp");
        winSend   = (osrdnObjcSend)       winBind("_objc_msgSend");
        winSel    = (osrdnObjcSel)        winBind("_sel_getUid");
        winBounds = (osrdnPsWindowBounds) winBind("_PScurrentwindowbounds");
        winReady = (winNSApp != 0 && winSend != 0 && winSel != 0 && winBounds != 0) ? 1 : 0;
        if (winReady)
            winCounts.binds++;
        else
            winCounts.noSymbols++;
    }
    return winReady;
}

int
osrdn_window_bounds_of(int number, osrdn_window_bounds *out)
{
    float x = 0.0F, y = 0.0F, w = 0.0F, h = 0.0F;

    if (!osrdn_window_ready() || number <= 0) {
        winCounts.queryFailed++;
        return 0;
    }
    winCounts.queries++;
    (*winBounds)(number, &x, &y, &w, &h);
    if (w <= 0.0F || h <= 0.0F) {
        winCounts.queryFailed++;
        return 0;
    }
    out->number = number;
    out->x = x;
    out->y = y;
    out->w = w;
    out->h = h;
    return 1;
}

#define OSRDN_WINDOW_LIST_MAX   32

int
osrdn_window_find(unsigned long contentW, unsigned long contentH, osrdn_window_bounds *out)
{
    void *app, *windows, *win;
    int count, k, found = 0;
    osrdn_window_bounds b;

    if (!osrdn_window_ready() || *winNSApp == 0) {
        winCounts.findFailed++;
        return 0;
    }
    app = *winNSApp;
    windows = (*winSend)(app, (*winSel)("windows"));                  /* an NSArray of the app's windows */
    if (windows == 0) {
        winCounts.findFailed++;
        return 0;
    }
    count = (int)(long)(*winSend)(windows, (*winSel)("count"));
    if (count > OSRDN_WINDOW_LIST_MAX)
        count = OSRDN_WINDOW_LIST_MAX;
    for (k = 0; k < count; k++) {
        int number, visible;
        float dw, dh;

        win = (*winSend)(windows, (*winSel)("objectAtIndex:"), k);
        if (win == 0)
            continue;
        visible = (int)(long)(*winSend)(win, (*winSel)("isVisible"));
        if (!visible)
            continue;
        number = (int)(long)(*winSend)(win, (*winSel)("windowNumber"));
        if (!osrdn_window_bounds_of(number, &b))
            continue;
        dw = b.w - (float) contentW;
        dh = b.h - (float) contentH;
        /* a title bar and borders, and nothing else: the icon tile, the menu
           and any panel are far from the surface's size */
        if (dw >= 0.0F && dw <= 16.0F && dh >= 0.0F && dh <= 48.0F) {
            if (found) {                    /* two candidates: refuse to guess */
                winCounts.findFailed++;
                return 0;
            }
            *out = b;
            found = 1;
        }
    }
    if (found)
        winCounts.finds++;
    else
        winCounts.findFailed++;
    return found;
}

const osrdn_window_counts *
OSRDNMesaWindowCounts(void)
{
    return &winCounts;
}
