/*
 * OSRDNMesaTex.c - see OSRDNMesaTex.h.  Plain C89, no libc and no Mesa headers.
 *
 * It maps nothing: the one window OSRDNMesaSurface.c mapped is the one the
 * texels go into, and this unit asks for its base.  Keeping the mapping count
 * at one is an invariant the build gate reads, and a second mmap here would
 * have quietly broken it.
 */

#include "OSRDNMesaTex.h"
#include "OSRDNMesaTri.h"        /* G5-2: osrdn_tri_retire_if_inflight */
#include "OSRDNMesaSurface.h"
#include "OSRDNMesaTriTable.h"
#include "OSRDNMesaTime.h"          /* G5-0: the frame-budget instrument */

extern char *getenv(const char *);

static osrdn_tex_counts texCounts;
static unsigned long texImage[OSRDN_TEX_W * OSRDN_TEX_H];

/*
 * G5-1a (docs/G5_1A_TEX_READBACK_PLAN.md 1): after a level is written, how much
 * of it is read back.  M1g read EVERY word back and compared -- 16,384 uncached
 * PCI reads for a 128 x 128 level, 11 ms, a tenth to a quarter of a GLQuake
 * frame (G5-0 8-3) -- and in every GLQuake run it refused nothing.  By default
 * four words are read: the first and last of the first row and of the last
 * row, which is what a lost write, an aliased first or last row, or a wrong
 * shift would show.  RDNMesaTexVerify in the environment brings the whole loop
 * back, for diagnosis: a bad word in the middle of a level, or an alias in the
 * middle, is what only the whole loop sees.  Neither loop proves the ADDRESS is
 * right (both read where they wrote); the picture does.
 */
static int texVerifyAll = -1;

static int
texVerify(void)
{
    if (texVerifyAll < 0)
        texVerifyAll = (getenv("RDNMesaTexVerify") != 0) ? 1 : 0;
    return texVerifyAll;
}

const unsigned long *
OSRDNMesaTexImage(void)
{
    return texImage;
}

const osrdn_tex_counts *
OSRDNMesaTexCounts(void)
{
    return &texCounts;
}

const char *
OSRDNMesaTexWhyName(int why)
{
    static const char *names[OSRDN_TEX_REASONS] = {
        "-", "NO_WINDOW", "ARGS", "READBACK"
    };

    if (why < 0 || why >= OSRDN_TEX_REASONS)
        return "?";
    return names[why];
}

int
osrdn_tex_upload_at(const unsigned char *px, int comps, int w, int h, unsigned long byteOff,
                    int rs, int gs, int bs, int as, int *why)
{
    if (w < OSRDN_TEX_MIN_DIM) {
        texCounts.refused[OSRDN_TEX_ARGS]++;
        if (why != 0)
            *why = OSRDN_TEX_ARGS;
        return 0;
    }
    return osrdn_tex_upload_level(px, comps, w, h, byteOff, (unsigned long)w * 4UL, rs, gs, bs, as, why);
}

static int osrdnTexUploadLevelBody(const unsigned char *px, int comps, int w, int h, unsigned long byteOff,
                                   unsigned long rowBytes, int rs, int gs, int bs, int as, int *why);

/* G5-0: the leaf of every upload (osrdn_tex_upload_at comes through here), timed as one
   interval with the bytes it moved; the argument checks are inside so a refusal is
   counted at its true cost */
int
osrdn_tex_upload_level(const unsigned char *px, int comps, int w, int h, unsigned long byteOff,
                       unsigned long rowBytes, int rs, int gs, int bs, int as, int *why)
{
    osrdn_time_stamp t;
    int timed = osrdn_time_on();
    int ok;

    if (timed)
        osrdn_time_now(&t);
    ok = osrdnTexUploadLevelBody(px, comps, w, h, byteOff, rowBytes, rs, gs, bs, as, why);
    if (timed) {
        osrdn_time_add(OSRDN_TIME_UPLOAD, &t);
        if (ok && w > 0 && h > 0)
            osrdn_time_count(OSRDN_TIME_UPLOAD, (unsigned long)w * (unsigned long)h * 4UL);
    }
    return ok;
}

static int
osrdnTexUploadLevelBody(const unsigned char *px, int comps, int w, int h, unsigned long byteOff,
                        unsigned long rowBytes, int rs, int gs, int bs, int as, int *why)
{
    unsigned long winBytes = 0UL;
    unsigned long *win = (unsigned long *)osrdn_surf_window(&winBytes);
    unsigned long stride, need, row, col, at, word;
    const unsigned char *p;
    int bad = 0;

    /* G5-2 (docs/G5_2_ASYNC_SUBMIT_PLAN.md 2-4): an accepted batch may still be reading these texels */
    (void)osrdn_tri_retire_if_inflight();
    if (why != 0)
        *why = OSRDN_TEX_OK;
    if (px == 0 || (comps != 3 && comps != 4) || w < 1 || w > OSRDN_TEX_MAX_DIM ||
        h < 1 || h > OSRDN_TEX_MAX_DIM || (byteOff & 31UL) != 0UL ||
        (rowBytes & 31UL) != 0UL || rowBytes < (unsigned long)w * 4UL) {
        texCounts.refused[OSRDN_TEX_ARGS]++;
        if (why != 0)
            *why = OSRDN_TEX_ARGS;
        return 0;
    }
    stride = rowBytes;
    need = byteOff + (unsigned long)h * stride;
    if (win == 0 || need < byteOff || winBytes < need) {
        texCounts.refused[OSRDN_TEX_NO_WINDOW]++;
        if (why != 0)
            *why = OSRDN_TEX_NO_WINDOW;
        return 0;
    }
    p = px;
    for (row = 0UL; row < (unsigned long)h; row++) {
        at = (byteOff + row * stride) / 4UL;
        for (col = 0UL; col < (unsigned long)w; col++) {
            word = ((unsigned long)p[0] << rs) | ((unsigned long)p[1] << gs) | ((unsigned long)p[2] << bs) |
                   ((unsigned long)(comps == 4 ? p[3] : 0xff) << as);
            win[at + col] = word;
            p += comps;
        }
    }
    if (texVerify()) {
        p = px;
        for (row = 0UL; row < (unsigned long)h; row++) {
            at = (byteOff + row * stride) / 4UL;
            for (col = 0UL; col < (unsigned long)w; col++) {
                word = ((unsigned long)p[0] << rs) | ((unsigned long)p[1] << gs) | ((unsigned long)p[2] << bs) |
                       ((unsigned long)(comps == 4 ? p[3] : 0xff) << as);
                if (win[at + col] != word)
                    bad++;
                p += comps;
            }
        }
        texCounts.verifyWords += (unsigned long)w * (unsigned long)h;
    } else {
        /* the four corners, each once: a 1 x N or N x 1 level has two, 1 x 1 has one */
        unsigned long rows[2], cols[2], nr, nc, i, j;

        rows[0] = 0UL;  nr = 1UL;
        cols[0] = 0UL;  nc = 1UL;
        if (h > 1) { rows[1] = (unsigned long)h - 1UL; nr = 2UL; }
        if (w > 1) { cols[1] = (unsigned long)w - 1UL; nc = 2UL; }
        for (i = 0UL; i < nr; i++)
            for (j = 0UL; j < nc; j++) {
                p = px + (rows[i] * (unsigned long)w + cols[j]) * (unsigned long)comps;
                word = ((unsigned long)p[0] << rs) | ((unsigned long)p[1] << gs) | ((unsigned long)p[2] << bs) |
                       ((unsigned long)(comps == 4 ? p[3] : 0xff) << as);
                at = (byteOff + rows[i] * stride) / 4UL;
                if (win[at + cols[j]] != word)
                    bad++;
                texCounts.verifyWords++;
            }
    }
    texCounts.readBad += (unsigned long)bad;
    if (bad != 0) {
        texCounts.refused[OSRDN_TEX_READBACK]++;
        if (why != 0)
            *why = OSRDN_TEX_READBACK;
        return 0;
    }
    texCounts.uploads++;
    texCounts.texels += (unsigned long)w * (unsigned long)h;
    return 1;
}

int
osrdn_tex_upload(const unsigned long *argb, int w, int h, int *why)
{
    unsigned long winBytes = 0UL;
    unsigned long *win = (unsigned long *)osrdn_surf_window(&winBytes);
    unsigned long need;
    unsigned long row, col, at;
    int bad = 0;

    (void)osrdn_tri_retire_if_inflight();     /* G5-2: as the level upload */

    if (argb == 0 || w != OSRDN_TEX_W || h != OSRDN_TEX_H) {
        /* One size this rung, and it is the one R6h measured with.  A different
           size would need its own TXFORMAT log2 fields, which are in the
           generated prologue and not a run-time choice. */
        texCounts.refused[OSRDN_TEX_ARGS]++;
        if (why != 0)
            *why = OSRDN_TEX_ARGS;
        return 0;
    }
    need = OSRDN_TEX_BYTE_OFF + (unsigned long)h * (unsigned long)OSRDN_TEX_STRIDE;
    if (win == 0 || winBytes < need) {
        texCounts.refused[OSRDN_TEX_NO_WINDOW]++;
        if (why != 0)
            *why = OSRDN_TEX_NO_WINDOW;
        return 0;
    }

    /*
     * Row-major, at the HARDWARE's stride -- see the header.  The caller's rows
     * are w words apart; ours are OSRDN_TEX_STRIDE bytes apart, and for this
     * size those differ only when w * 4 < 32.
     */
    for (row = 0UL; row < (unsigned long)h; row++) {
        at = (OSRDN_TEX_BYTE_OFF + row * (unsigned long)OSRDN_TEX_STRIDE) / 4UL;
        for (col = 0UL; col < (unsigned long)w; col++) {
            win[at + col] = argb[row * (unsigned long)w + col];
            texImage[row * (unsigned long)w + col] =
                argb[row * (unsigned long)w + col];
        }
    }

    /*
     * And read it back, the way the driver does for its own prefill.  Writing
     * into video memory and assuming it arrived is how a texture rung reports a
     * sampling bug that is really an upload bug.
     */
    for (row = 0UL; row < (unsigned long)h; row++) {
        at = (OSRDN_TEX_BYTE_OFF + row * (unsigned long)OSRDN_TEX_STRIDE) / 4UL;
        for (col = 0UL; col < (unsigned long)w; col++)
            if (win[at + col] != argb[row * (unsigned long)w + col])
                bad++;
    }
    texCounts.readBad += (unsigned long)bad;
    if (bad != 0) {
        texCounts.refused[OSRDN_TEX_READBACK]++;
        if (why != 0)
            *why = OSRDN_TEX_READBACK;
        return 0;
    }

    texCounts.uploads++;
    texCounts.texels += (unsigned long)w * (unsigned long)h;
    texCounts.lastWord = argb[0];
    if (why != 0)
        *why = OSRDN_TEX_OK;
    return 1;
}
