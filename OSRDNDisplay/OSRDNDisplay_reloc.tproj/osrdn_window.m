/*
 * osrdn_window.m - see osrdn_window.h.  Plain C89; no hardware, no log.
 */

#import "osrdn_window.h"

static int
pageOk(unsigned long pageBytes)
{
    return pageBytes != 0UL && (pageBytes & (pageBytes - 1UL)) == 0UL;
}

unsigned long
osrdn_window_start(unsigned long width, unsigned long height,
                   unsigned long bytesPerPixel, unsigned long pageBytes)
{
    unsigned long row, visible, guard, start;

    if (!pageOk(pageBytes) || width == 0UL || height == 0UL || bytesPerPixel == 0UL)
        return 0UL;
    if (width > 0xFFFFFFFFUL / bytesPerPixel)
        return 0UL;
    row = width * bytesPerPixel;
    if (height > 0xFFFFFFFFUL / row || OSRDN_WIN_GUARD_ROWS > 0xFFFFFFFFUL / row)
        return 0UL;
    visible = row * height;
    guard = row * OSRDN_WIN_GUARD_ROWS;
    if (visible > 0xFFFFFFFFUL - guard)
        return 0UL;
    start = visible + guard;
    if (start > 0xFFFFFFFFUL - (pageBytes - 1UL))
        return 0UL;
    return (start + pageBytes - 1UL) & ~(pageBytes - 1UL);
}

unsigned long
osrdn_window_ceiling(unsigned long vramBytes, unsigned long pageBytes)
{
    if (!pageOk(pageBytes) || vramBytes <= OSRDN_WIN_TOP_MARGIN)
        return 0UL;
    return (vramBytes - OSRDN_WIN_TOP_MARGIN) & ~(pageBytes - 1UL);
}
