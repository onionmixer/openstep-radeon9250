/*
 * OSRDNMesaReadPix.c - G5-4 (docs/G5_4_READPIX_AND_CLEANUP_PLAN.md 1).  See the header.
 *
 * GL row sy lives in surface row height - 1 - sy: the triangle hook draws window y at
 * H - y (OSRDNMesaHook.c, flipH) and the mirror copies app row r from surface row H - 1 - r.
 * The clipping is read_fast_rgba_pixels' (readpix.c), bounds inclusive; the destination
 * layout is the GL pack rule _mesa_image_address uses (image.c): a row is comps x rowLength
 * bytes, rounded up to the alignment, and SkipRows / SkipPixels move the start.  SkipImages
 * is refused by the caller (it would move the start too).
 */
#include "OSRDNMesaReadPix.h"

int
osrdn_readpix_flipped(const osrdn_readpix_src *s, long x, long y, long w, long h, int comps,
                      const osrdn_readpix_pack *pk, unsigned char *dest)
{
    long rowLength, skipPixels, skipRows, readW, readH, stride, row, col;
    const unsigned long *src;
    unsigned char *d;
    unsigned long word;

    if (s == 0 || pk == 0 || dest == 0 || s->surf == 0 || (comps != 3 && comps != 4))
        return 0;
    if (pk->alignment != 1 && pk->alignment != 2 && pk->alignment != 4 && pk->alignment != 8)
        return 0;
    if (w < 0 || h < 0 || pk->rowLength < 0 || pk->skipPixels < 0 || pk->skipRows < 0)
        return 0;
    rowLength = (pk->rowLength > 0) ? pk->rowLength : w;
    stride = rowLength * (long) comps;
    if (pk->alignment > 1 && stride % (long) pk->alignment != 0)
        stride += (long) pk->alignment - stride % (long) pk->alignment;
    skipPixels = pk->skipPixels;
    skipRows = pk->skipRows;
    readW = w;
    readH = h;
    /* horizontal clipping, as read_fast_rgba_pixels */
    if (x < s->xmin) {
        skipPixels += s->xmin - x;
        readW -= s->xmin - x;
        x = s->xmin;
    }
    if (x + readW > s->xmax)
        readW -= x + readW - s->xmax - 1;
    if (readW <= 0)
        return 1;
    /* vertical */
    if (y < s->ymin) {
        skipRows += s->ymin - y;
        readH -= s->ymin - y;
        y = s->ymin;
    }
    if (y + readH > s->ymax)
        readH -= y + readH - s->ymax - 1;
    if (readH <= 0)
        return 1;
    /* bounds wider than the surface are not ours to guess -- refused BEFORE anything is written */
    if (x < 0 || y < 0 || x + readW > s->width || (unsigned long) (x + readW) > s->rowPixels ||
        y + readH > s->height)
        return 0;
    for (row = 0; row < readH; row++) {
        src = s->surf + (unsigned long) (s->height - 1L - (y + row)) * s->rowPixels + (unsigned long) x;
        d = dest + (skipRows + row) * stride + skipPixels * (long) comps;
        for (col = 0; col < readW; col++) {
            word = src[col];
            d[0] = (unsigned char) ((word >> s->rs) & 0xffUL);
            d[1] = (unsigned char) ((word >> s->gs) & 0xffUL);
            d[2] = (unsigned char) ((word >> s->bs) & 0xffUL);
            if (comps == 4)
                d[3] = (unsigned char) ((word >> s->as) & 0xffUL);
            d += comps;
        }
    }
    return 1;
}
