#!/usr/bin/env python3
"""sim_present.py -- the present rows coalesced into one blit, run on the host.

G5-1b (docs/G5_1B_PRESENT_ONE_BLIT_PLAN.md 2).  mesa/OSRDNMesaPresent.c is
linked against a fake device (every PRESENT ioctl is recorded, and answered OK
or refused as the test says) and a fake surface (width, height, flipped flag).
The driver replays what SDL does -- a frame of H row calls, source row k to
destination dstY0 + H - 1 - k -- and python checks:

  1. surface not flipped (no present mode drawing): H ioctls, one row each,
     exactly as before G5-1b;
  2. surface flipped: ONE ioctl for the frame -- rows 0..H-1 to dstY0..dstY0+H-1 --
     and the other H-1 row calls answered OK without an ioctl (covered);
  3. a second frame does the same (the cover is per frame, not once);
  4. a partial rectangle (srcY > 0 first, or narrower than the surface) in
     flipped mode: one ioctl per row, source row H-1-srcY;
  5. the whole-surface blit refused by the kernel: the frame falls back to rows
     with the mapped source, and no row is silently dropped;
  6. mutations: no coalescing (H ioctls), the source row not mapped in the
     fallback (row H-1-srcY becomes srcY), the cover not checked against dstY.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.normpath(os.path.join(HERE, '..', '..'))
MESA = os.path.join(PROJ, 'mesa')
DRV = os.path.join(PROJ, 'OSRDNDisplay', 'OSRDNDisplay_reloc.tproj')
SRC = os.path.join(MESA, 'OSRDNMesaPresent.c')

DRIVER = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include "OSRDNMesaPresent.h"
#include "OSRDNMesaSurface.h"
#include "osrdn_r7b.h"
static osrdn_surf_counts sc;
static int flipped, refuseFull;
static const void *cur = (const void *)0x1234;
const osrdn_surf_counts *OSRDNMesaSurfaceCounts(void) { return &sc; }
int osrdn_surf_flipped(void) { return flipped; }
int osrdn_surf_bound_to(const void *ctx) { return ctx == cur; }
unsigned long osrdn_surf_stride(void) { return sc.width; }
void *OSMesaGetCurrentContext(void) { return (void *)cur; }
void osrdn_tri_hold_set(int on) { (void)on; }
int osrdn_tri_device_open(void) { return 3; }
void osrdn_tri_device_close(int fd) { (void)fd; }
/* ---- G5-1c: the application and its window server, faked ----
   haveAppKit: whether the dynamic linker finds NSApp & co (0 = a program without AppKit);
   the app has three windows: [menu 256x128 invisible] [ours, number 4, frame (W+2)x(H+24)] [icon 64x64];
   serverX/serverY: where the server has our frame right now (PostScript coords, y up). */
static int haveAppKit = 1;
static float serverX = 199.0F, serverY = 100.0F, serverW = 10.0F, serverH = 30.0F;
static int fakeApp = 1, fakeArr = 2, fakeWin[3] = {11, 12, 13};
static void *fake_NSApp = (void *)1;
void *fake_sel(const char *n) { return (void *)n; }
void *fake_send(void *self, void *sel, ...)
{
    const char *s = (const char *)sel;
    if (self == (void *)1 && !strcmp(s, "windows")) return (void *)2;
    if (self == (void *)2 && !strcmp(s, "count")) return (void *)3;
    if (self == (void *)2 && !strcmp(s, "objectAtIndex:")) { va_list ap; int i; va_start(ap, sel); i = va_arg(ap, int); va_end(ap); return (void *)(long)fakeWin[i]; }
    if (!strcmp(s, "isVisible")) return (void *)(long)(self == (void *)12 || self == (void *)13);
    if (!strcmp(s, "windowNumber")) return (void *)(long)(self == (void *)11 ? 2 : self == (void *)12 ? 4 : 7);
    return 0;
}
void fake_bounds(int num, float *x, float *y, float *w, float *h)
{
    if (num == 2) { *x = 0; *y = 0; *w = 256; *h = 128; }
    else if (num == 4) { *x = serverX; *y = serverY; *w = serverW; *h = serverH; }
    else if (num == 7) { *x = 192; *y = 0; *w = 64; *h = 64; }
    else { *w = 0; *h = 0; }
}
int NSIsSymbolNameDefined(const char *n) { return haveAppKit; }
void *NSLookupAndBindSymbol(const char *n) { return (void *)n; }
void *NSAddressOfSymbol(void *s)
{
    const char *n = (const char *)s;
    if (!strcmp(n, "_NSApp")) return &fake_NSApp;
    if (!strcmp(n, "_objc_msgSend")) return (void *)fake_send;
    if (!strcmp(n, "_sel_getUid")) return (void *)fake_sel;
    if (!strcmp(n, "_PScurrentwindowbounds")) return (void *)fake_bounds;
    return 0;
}
int ioctl(int fd, int cmd, char *p)
{
    osrdn_r7b_present *b = (osrdn_r7b_present *)p;
    (void)fd; (void)cmd;
    if (refuseFull && b->h > 1UL) { b->status = 22UL; b->verdict = OSRDN_PRESENT_E_DST; printf("IOCTL refused h=%lu\n", b->h); return 0; }
    b->status = 0UL; b->verdict = OSRDN_PRESENT_OK;
    printf("IOCTL src=%lu,%lu %lux%lu dst=%lu,%lu\n", b->srcX, b->srcY, b->w, b->h, b->dstX, b->dstY);
    return 0;
}
static void frame(const char *tag, unsigned long srcX, unsigned long srcY0, unsigned long w, unsigned long h, long dstX, long dstY0)
{
    unsigned long k, verdict; int ok = 0, bad = 0;
    for (k = 0; k < h; k++) {
        if (OSRDNMesaBufferPresentRect(srcX, srcY0 + k, w, 1UL, dstX, dstY0 + (long)(h - 1 - k), &verdict) == 0) ok++;
        else { bad++; break; }             /* as SDL: the frame stops at its first refusal */
    }
    printf("FRAME %s ok=%d bad=%d\n", tag, ok, bad);
}
int main(int argc, char **argv)
{
    const osrdn_present_counts *c;
    unsigned long verdict = 0;
    sc.width = 8; sc.height = 6;
    if (argc > 1 && argv[1][0] == 'c') goto partc;
    haveAppKit = 0;                                 /* run "b": a program without AppKit -- the G5-1b scenarios as they were */
    OSRDNMesaBufferPresentMode(1);
    flipped = 0;
    frame("plain", 0, 0, 8, 6, 10, 20);
    flipped = 1;
    frame("flipped1", 0, 0, 8, 6, 10, 20);          /* the first flipped frame: rows (nothing known yet) */
    frame("flipped2", 0, 0, 8, 6, 10, 20);          /* whole: the last frame was whole, here */
    frame("flipped3", 0, 0, 8, 6, 10, 20);          /* and again */
    frame("shifted", 0, 1, 8, 5, 10, 21);           /* right after a whole frame, one row off its cover: never covered, rows */
    frame("partial", 2, 1, 4, 3, 12, 22);           /* a clipped window: rows, mapped */
    frame("flipped4", 0, 0, 8, 6, 10, 20);          /* after a partial frame: rows again */
    frame("flipped5", 0, 0, 8, 6, 10, 20);          /* whole again */
    { unsigned long k, v; for (k = 0; k < 6; k++) OSRDNMesaBufferPresentRect(0, k, 8, 1, 10, 25, &v); printf("FRAME flat ok=6 bad=0\n"); }
    frame("afterflat", 0, 0, 8, 6, 10, 20);         /* rows */
    frame("clipped", 0, 0, 8, 4, 10, 40);           /* clipped at the bottom (4 rows, bottom at screen row 43): rows */
    frame("moved", 0, 0, 8, 6, 30, 50);             /* the first frame at a new place: rows */
    frame("moved2", 0, 0, 8, 6, 30, 50);            /* the second: whole */
    refuseFull = 1;
    frame("refused", 0, 0, 8, 6, 30, 50);           /* whole refused by the kernel: rows, none dropped */
    refuseFull = 0;
    c = OSRDNMesaPresentCounts();
    printf("COUNTS rects=%lu ok=%lu coalesced=%lu covered=%lu rowFallback=%lu\n", c->rects, c->ok, c->coalesced, c->covered, c->rowFallback);
    return 0;
partc:
    /* ---- run "c": an AppKit application; a drag.  The surface is drawn flipped (present mode). ---- */
    haveAppKit = 1;
    flipped = 1;
    OSRDNMesaBufferPresentMode(1);
    frame("s0", 0, 0, 8, 6, 10, 20);                /* rows (first of the run) */
    frame("s1", 0, 0, 8, 6, 10, 20);                /* whole is possible, but the pair is not steady twice yet: refused (unsettled) */
    frame("s2", 0, 0, 8, 6, 10, 20);                /* rows again (the last frame was not whole) */
    frame("s3", 0, 0, 8, 6, 10, 20);                /* whole; steady twice -> calibrated (SDL 10,20 <-> server 199,100), blit */
    serverX = 299.0F; serverY = 50.0F;              /* the user drags: right 100, down 50 (PostScript y falls) */
    frame("drag1", 0, 0, 8, 6, 10, 20);             /* moving: refused, nothing stamped */
    frame("drag2", 0, 0, 8, 6, 10, 20);             /* rows: the last frame was not whole */
    frame("drag3", 0, 0, 8, 6, 10, 20);             /* still, calibrated, SDL stale: blit SHIFTED at 110,70 */
    serverX = 250.0F; serverY = 75.0F;              /* SDL catches up mid-drag while the server is still moving */
    frame("caught", 0, 0, 8, 6, 110, 70);           /* new SDL origin: rows (run broken) */
    frame("mid", 0, 0, 8, 6, 110, 70);              /* whole possible; server moved since drag3: moving, refused */
    serverX = 299.0F; serverY = 50.0F;              /* the server settles */
    frame("settle", 0, 0, 8, 6, 110, 70);           /* rows (last not whole) */
    frame("settle2", 0, 0, 8, 6, 110, 70);          /* whole possible; server moved since mid: refused */
    frame("settle3", 0, 0, 8, 6, 110, 70);          /* rows */
    frame("settle4", 0, 0, 8, 6, 110, 70);          /* whole possible, steady twice, SDL same twice: calibrated 110,70 <-> 299,50, blit */
    frame("settle5", 0, 0, 8, 6, 110, 70);          /* whole, shift 0 */
    serverW = 500.0F;                               /* a different-sized window has our number now: lost */
    frame("lost", 0, 0, 8, 6, 110, 70);             /* refused E_BUSY, nothing stamped */
    serverW = 10.0F;
    frame("back", 0, 0, 8, 6, 110, 70);             /* rows */
    frame("back2", 0, 0, 8, 6, 110, 70);            /* whole possible; found again, steady, SDL same: calibrated, blit */
    serverY = 900.0F;                               /* dragged far up */
    frame("offtop", 0, 0, 8, 6, 110, 70);           /* moving: refused */
    frame("offtop2", 0, 0, 8, 6, 110, 70);          /* rows */
    frame("offtop3", 0, 0, 8, 6, 110, 70);          /* whole possible, still, shift (0,-850): off the top -> E_DST, nothing */
    c = OSRDNMesaPresentCounts();
    printf("COUNTS rects=%lu ok=%lu coalesced=%lu covered=%lu rowFallback=%lu finds=%lu lost=%lu cal=%lu shifted=%lu busy=%lu dst=%lu moving=%lu unsettled=%lu\n",
           c->rects, c->ok, c->coalesced, c->covered, c->rowFallback, c->windowFinds, c->windowLost, c->calibrations, c->shifted,
           c->refused[OSRDN_PRESENT_E_BUSY], c->refused[OSRDN_PRESENT_E_DST], c->moving, c->unsettled);
    (void)verdict;
    return 0;
}
"""

MUTATIONS = [
    ('no coalescing: the first row is just a row',
     "            if (whole) {", "            if (0) {"),
    ('the fallback row is not mapped to H-1-srcY',
     "        return presentBlit(srcX, H - 1UL - srcY, w, 1UL, (unsigned long) sx, (unsigned long) sy, outVerdict);",
     "        return presentBlit(srcX, srcY, w, 1UL, (unsigned long) sx, (unsigned long) sy, outVerdict);"),
    ('a covered row is not checked against its destination',
     "                (unsigned long) sy - presentCover.dstY == H - 1UL - srcY) {",
     "                1) {"),
    ('G5-1c: the shift is not applied to y',
     "        presentShiftY = -(long)(b.y - presentCal.by);", "        presentShiftY = 0L;"),
    ('G5-1c: the y sign is wrong (PostScript y grows upward)',
     "        presentShiftY = -(long)(b.y - presentCal.by);", "        presentShiftY = (long)(b.y - presentCal.by);"),
    ('G5-1c: calibrated at first sight, not at a steady moment',
     "    if (presentCal.steady >= 2UL && sdlSame) {", "    if (1) {"),
    ('G5-1c: a moving window is stamped anyway',
     "    if (moving) {\n        presentCal.steady = 0;", "    if (0) {\n        presentCal.steady = 0;"),
    ('G5-1c: a window of another size is taken for ours',
     "    if (!ok || b->w - (float) W < 0.0F || b->w - (float) W > 16.0F ||\n        b->h - (float) H < 0.0F || b->h - (float) H > 48.0F) {",
     "    if (!ok) {"),
    ('a frame is blitted whole without the last frame having been whole (a clipped window is drawn too high)',
     "                         presentRun.rows == H && presentRun.firstDstY == (unsigned long) dstY &&",
     "                         presentRun.firstDstY == (unsigned long) dstY &&"),
    ('the run does not follow the destination (a row off still counts as the run)',
     "                presentRun.firstDstY >= srcY && (unsigned long) dstY == presentRun.firstDstY - srcY)",
     "                1)"),
    ('the cover survives into the next frame',
     "            presentCover.valid = 0;\n            presentShiftX = 0L;", "            presentShiftX = 0L;"),
]


def build(src_text, tmp):
    src = os.path.join(tmp, 'OSRDNMesaPresent.c')
    drv = os.path.join(tmp, 'drv.c')
    exe = os.path.join(tmp, 'drv')
    open(src, 'w').write(src_text)
    open(drv, 'w').write(DRIVER)
    r = subprocess.run(['gcc', '-O1', '-w', '-I', MESA, '-I', DRV, '-o', exe, drv, src,
                        os.path.join(MESA, 'OSRDNMesaTime.c'), os.path.join(MESA, 'OSRDNMesaWindow.c')],
                       capture_output=True, text=True)
    return (exe, '') if r.returncode == 0 else (None, r.stderr)


def parse(out):
    """{name: (ioctl lines, FRAME line)} in order, and the COUNTS line"""
    seq, cur = [], []
    for l in out.split('\n'):
        if l.startswith('IOCTL'):
            cur.append(l)
        elif l.startswith('FRAME'):
            seq.append((l.split()[1], cur, l))
            cur = []
    return dict((name, (calls, line)) for name, calls, line in seq)


def rows_of(calls):
    return [tuple(int(x) for x in re.match(r'IOCTL src=(\d+),(\d+) (\d+)x(\d+) dst=(\d+),(\d+)', c).groups()) for c in calls if 'refused' not in c]


def mapped_rows(srcX, srcY0, w, h, dstX, dstY0):
    return [(srcX, 5 - (srcY0 + k), w, 1, dstX, dstY0 + h - 1 - k) for k in range(h)]


def judge_b(out):
    """run b: no AppKit, the G5-1b scenarios"""
    p = []
    by = parse(out)
    # 1. plain: 6 one-row ioctls, source row k to dst 20 + 5 - k
    calls, line = by.get('plain', ([], ''))
    if rows_of(calls) != [(0, k, 8, 1, 10, 25 - k) for k in range(6)] or 'ok=6 bad=0' not in line:
        p.append('plain: %s %s' % (rows_of(calls), line))
    def rows_at(name, srcX, srcY0, w, h, dstX, dstY0):
        calls, line = by.get(name, ([], ''))
        if rows_of(calls) != mapped_rows(srcX, srcY0, w, h, dstX, dstY0) or ('ok=%d bad=0' % h) not in line:
            p.append('%s: %s %s' % (name, rows_of(calls), line))
    def whole_at(name, x, y):
        calls, line = by.get(name, ([], ''))
        if rows_of(calls) != [(0, 0, 8, 6, x, y)] or 'ok=6 bad=0' not in line:
            p.append('%s: %s %s (want one blit at %d,%d)' % (name, rows_of(calls), line, x, y))
    rows_at('flipped1', 0, 0, 8, 6, 10, 20)       # the first flipped frame goes row by row, mapped
    whole_at('flipped2', 10, 20); whole_at('flipped3', 10, 20)
    rows_at('shifted', 0, 1, 8, 5, 10, 21)        # one row off flipped3's cover: never covered
    rows_at('partial', 2, 1, 4, 3, 12, 22)        # a clipped window: rows, mapped
    rows_at('flipped4', 0, 0, 8, 6, 10, 20)       # after a partial frame: rows again
    whole_at('flipped5', 10, 20)
    rows_at('afterflat', 0, 0, 8, 6, 10, 20)      # six rows at one destination are not SDL's walk
    rows_at('clipped', 0, 0, 8, 4, 10, 40)        # bottom clip: a whole blit from 38 would be WRONG
    rows_at('moved', 0, 0, 8, 6, 30, 50)          # the first frame at the new place is rows
    whole_at('moved2', 30, 50)
    calls, line = by.get('refused', ([], ''))     # the whole blit refused by the kernel: mapped rows, none dropped
    if not calls or 'refused' not in calls[0] or rows_of(calls) != mapped_rows(0, 0, 8, 6, 30, 50) or 'ok=6 bad=0' not in line:
        p.append('refused: %s %s' % (calls[:2], line))
    m = re.search(r'COUNTS rects=(\d+) ok=(\d+) coalesced=(\d+) covered=(\d+) rowFallback=(\d+)$', out, re.M)
    if not m:
        p.append('no COUNTS line')
    else:
        got = tuple(int(x) for x in m.groups())[2:]
        # coalesced: flipped2 flipped3 flipped5 moved2 and flat's first call; covered 5 x 4 (flat covers
        # nothing); rows: flipped1 6 + shifted 5 + partial 3 + flipped4 6 + flat 5 + afterflat 6 +
        # clipped 4 + moved 6 + refused 6
        if got != (5, 20, 47):
            p.append('counts coalesced/covered/rows = %s, want (5, 20, 47)' % (got,))
    return p


def judge_c(out):
    """run c: an AppKit application, a drag (docs/G5_1C_PRESENT_SERVER_POSITION_PLAN.md 2)"""
    p = []
    by = parse(out)
    def whole_at(name, x, y):
        calls, line = by.get(name, ([], ''))
        if rows_of(calls) != [(0, 0, 8, 6, x, y)] or 'ok=6 bad=0' not in line:
            p.append('%s: %s %s (want one blit at %d,%d)' % (name, rows_of(calls), line, x, y))
    def rows_at(name, x, y, n=6):
        calls, line = by.get(name, ([], ''))
        if rows_of(calls) != mapped_rows(0, 0, 8, n, x, y) or ('ok=%d bad=0' % n) not in line:
            p.append('%s: %s %s (want %d mapped rows at %d,%d)' % (name, rows_of(calls), line, n, x, y))
    def refused(name):
        calls, line = by.get(name, ([], ''))
        if calls or 'ok=0 bad=1' not in line:
            p.append('%s: %s %s (want nothing stamped, the first row refused)' % (name, rows_of(calls), line))
    rows_at('s0', 10, 20); refused('s1'); rows_at('s2', 10, 20); whole_at('s3', 10, 20)
    refused('drag1'); rows_at('drag2', 10, 20)
    # the drag: server +100, -50 (PostScript) while SDL still says 10,20 -> 110,70 (python: 10+(299-199), 20-(50-100))
    whole_at('drag3', 110, 70)
    rows_at('caught', 110, 70); refused('mid')
    rows_at('settle', 110, 70); refused('settle2'); rows_at('settle3', 110, 70)
    whole_at('settle4', 110, 70); whole_at('settle5', 110, 70)
    refused('lost'); rows_at('back', 110, 70); whole_at('back2', 110, 70)
    refused('offtop'); rows_at('offtop2', 110, 70); refused('offtop3')
    m = re.search(r'COUNTS rects=(\d+) ok=(\d+) coalesced=(\d+) covered=(\d+) rowFallback=(\d+) finds=(\d+) lost=(\d+) cal=(\d+) shifted=(\d+) busy=(\d+) dst=(\d+) moving=(\d+) unsettled=(\d+)', out)
    if not m:
        p.append('no COUNTS line')
    else:
        got = tuple(int(x) for x in m.groups())[2:]
        # coalesced: s3 drag3 settle4 settle5 back2 = 5, covered 5 each = 25; rows: s0 s2 drag2 caught settle
        # settle3 back offtop2 = 8 x 6 = 48; finds: s1 (the first query) and back2 (after lost); lost 1;
        # calibrations: s3, settle4 (SDL caught up consistently), back2; shifted: drag3 and offtop3 (its
        # shift (0,-850) is computed, then the destination is off the screen); busy: s1 unsettled + drag1 mid
        # settle2 offtop moving + lost = 6; dst: offtop3; moving 4; unsettled 1
        want = (5, 25, 48, 2, 1, 3, 2, 6, 1, 4, 1)
        if got != want:
            p.append('counts coalesced/covered/rows/finds/lost/cal/shifted/busy/dst/moving/unsettled = %s, want %s' % (got, want))
    return p


def run(exe, mode):
    return subprocess.run([exe, mode], capture_output=True, text=True).stdout


def main():
    src = open(SRC).read()
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        exe, e = build(src, tmp)
        if exe is None:
            print('sim_present: FAIL (the unit does not build on the host)\n' + e)
            return 1
        for mode, judge, name in (('b', judge_b, 'no AppKit: plain rows, one blit a frame, partial rows mapped, a refused blit falls back'),
                                  ('c', judge_c, 'an AppKit application: the frame follows the server, nothing is stamped while the window moves')):
            p = judge(run(exe, mode))
            if p:
                bad += 1
                print('  FAIL %s: %s' % (name, '; '.join(p)))
            else:
                print('  ok   ' + name)
        for name, a, b in MUTATIONS:
            if src.count(a) != 1:
                print('  FAIL mutation %-48s anchor found %d times' % (name, src.count(a)))
                bad += 1
                continue
            with tempfile.TemporaryDirectory() as t2:
                exe2, e2 = build(src.replace(a, b), t2)
                if exe2 is None:
                    print('  ok   mutation %-48s does not build' % name)
                    continue
                caught = bool(judge_b(run(exe2, 'b'))) or bool(judge_c(run(exe2, 'c')))
                print('  %s mutation %-48s %s' % ('ok  ' if caught else 'FAIL', name, 'caught' if caught else 'NOT caught'))
                bad += 0 if caught else 1
    print('sim_present: %s' % ('PASS' if bad == 0 else 'FAIL (%d)' % bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
