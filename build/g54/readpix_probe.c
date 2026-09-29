/*
 * readpix_probe.c - G5-4 5-1 on the machine (docs/G5_4_READPIX_AND_CLEANUP_PLAN.md 1-3): glReadPixels
 * from the TOP-DOWN surface.  OSMesa, offscreen: present mode on (the flag the hook flips by; no
 * screen is touched), the lower half drawn red and the upper half blue by the card, then
 *   1. orientation: GL row 0 (the bottom) must be red, the top row blue;
 *   2. bytes: every pixel of glReadPixels(GL_RGBA) must equal the surface word at memory row H-1-y;
 *   3. GL_RGB with alignment 4 and a 3-pixel-wider row length, the same pixels.
 *   readpix_probe <w> <h>      prints "READPIX ..." lines and "READPIX PASS" / "READPIX FAIL"
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <GL/osmesa.h>
#include <GL/gl.h>
#include "OSRDNMesaHook.h"
#include "OSRDNMesaPresent.h"
#include "OSRDNMesaSurface.h"

static void quad(float y0, float y1, float r, float g, float b)
{
    glColor3f(r, g, b);
    glBegin(GL_TRIANGLES);
    glVertex2f(-1.0F, y0); glVertex2f(1.0F, y0); glVertex2f(1.0F, y1);
    glVertex2f(-1.0F, y0); glVertex2f(1.0F, y1); glVertex2f(-1.0F, y1);
    glEnd();
}

int main(int argc, char **argv)
{
    int w = argc > 1 ? atoi(argv[1]) : 64, h = argc > 2 ? atoi(argv[2]) : 48;
    OSMesaContext ctx;
    unsigned char *app, *rgba, *rgb;
    const unsigned long *surf;
    unsigned long stride;
    int rs, gs, bs, as, x, y, bad = 0, badRgb = 0, rowRgb;
    const osrdn_hook_counts *hc;

    ctx = OSMesaCreateContext(OSMESA_RGBA, NULL);
    app = (unsigned char *) calloc((size_t) (w * h * 4), 1);
    rgba = (unsigned char *) calloc((size_t) (w * h * 4), 1);
    rowRgb = ((w + 3) * 3 + 3) & ~3;
    rgb = (unsigned char *) calloc((size_t) (rowRgb * h + 16), 1);
    if (!ctx || !app || !rgba || !rgb || !OSMesaMakeCurrent(ctx, app, GL_UNSIGNED_BYTE, w, h)) {
        printf("READPIX setup failed\nREADPIX FAIL\n");
        return 2;
    }
    OSRDNMesaBufferPresentMode(1);
    glViewport(0, 0, w, h);
    glDisable(GL_DEPTH_TEST);
    glClearColor(0.0F, 1.0F, 0.0F, 1.0F);
    glClear(GL_COLOR_BUFFER_BIT);
    quad(-1.0F, 0.0F, 1.0F, 0.0F, 0.0F);        /* lower half red */
    quad(0.0F, 1.0F, 0.0F, 0.0F, 1.0F);         /* upper half blue */
    glFinish();
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    glPixelStorei(GL_PACK_ALIGNMENT, 4);
    glPixelStorei(GL_PACK_ROW_LENGTH, w + 3);
    glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE, rgb);
    glPixelStorei(GL_PACK_ROW_LENGTH, 0);
    surf = osrdn_surf_base();
    stride = osrdn_surf_stride();
    osrdn_surf_shifts(&rs, &gs, &bs, &as);
    hc = OSRDNMesaHookCounts();
    printf("READPIX w=%d h=%d flipped=%d present=%d stride=%lu shifts=%d,%d,%d,%d readpix_flipped=%lu declined=%lu\n",
           w, h, osrdn_surf_flipped(), osrdn_present_active(), stride, rs, gs, bs, as,
           hc->readpixFlipped, hc->readpixFlipDeclined);
    printf("READPIX bottom-left %02x%02x%02x top-left %02x%02x%02x\n",
           rgba[0], rgba[1], rgba[2], rgba[(h - 1) * w * 4], rgba[(h - 1) * w * 4 + 1], rgba[(h - 1) * w * 4 + 2]);
    if (surf == 0) {
        printf("READPIX no surface\nREADPIX FAIL\n");
        return 1;
    }
    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++) {
            unsigned long v = surf[(unsigned long) (h - 1 - y) * stride + (unsigned long) x];
            const unsigned char *p = rgba + (y * w + x) * 4, *q = rgb + y * rowRgb + x * 3;
            if (p[0] != ((v >> rs) & 255) || p[1] != ((v >> gs) & 255) || p[2] != ((v >> bs) & 255) ||
                p[3] != ((v >> as) & 255))
                bad++;
            if (q[0] != p[0] || q[1] != p[1] || q[2] != p[2])
                badRgb++;
        }
    printf("READPIX rgba_mismatch=%d rgb_mismatch=%d\n", bad, badRgb);
    if (bad == 0 && badRgb == 0 && rgba[0] > 200 && rgba[2] < 50 &&
        rgba[(h - 1) * w * 4 + 2] > 200 && rgba[(h - 1) * w * 4] < 50 && hc->readpixFlipped == 2UL &&
        hc->readpixFlipDeclined == 0UL && osrdn_surf_flipped())
        printf("READPIX PASS\n");
    else
        printf("READPIX FAIL\n");
    OSRDNMesaBufferPresentMode(0);
    OSMesaDestroyContext(ctx);
    return 0;
}
