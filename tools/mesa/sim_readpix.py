#!/usr/bin/env python3
"""sim_readpix.py -- G5-4 (docs/G5_4_READPIX_AND_CLEANUP_PLAN.md 1-3): glReadPixels from the
top-down (present mode) surface, run on the host against a python oracle.

The oracle is the GL picture P (row 0 at the BOTTOM, as GL and OSMesa count) read the way Mesa's
read_fast_rgba_pixels clips (bounds inclusive) and _mesa_image_address lays out (row = comps x
rowLength rounded up to the alignment, SkipRows / SkipPixels).  The unit gets the surface the
library really holds: memory row r = P[H-1-r].  Every case compares the WHOLE destination buffer,
guard bytes on both sides included, so a write outside the rectangle is caught as well as a wrong
byte inside it.  Cases: alignment 1/2/4/8, rowLength 0 / w / w+3, skips, rectangles inside, across
each edge and wholly outside, RGB and RGBA, three shift orders.  Mutations must each be caught.
"""
import os
import random
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.normpath(os.path.join(HERE, '..', '..'))
MESA = os.path.join(PROJ, 'mesa')
SRC = os.path.join(MESA, 'OSRDNMesaReadPix.c')
W, H, ROWPIX = 37, 23, 40          # a row holds more words than the width, as a real surface may
GUARD = 64
SHIFTS = [(0, 8, 16, 24), (16, 8, 0, 24), (8, 16, 24, 0)]


def word(gx, gy):
    return (0x9e3779b1 * (gx + 1) ^ 0x85ebca77 * (gy + 7) ^ (gx * gy)) & 0xffffffff


def cases():
    rnd = random.Random(20260929)
    out = []
    for comps in (3, 4):
        for al in (1, 2, 4, 8):
            for rl in ('0', 'w', 'w+3'):
                for _ in range(6):
                    w, h = rnd.randint(1, 17), rnd.randint(1, 9)
                    x, y = rnd.randint(-6, W + 2), rnd.randint(-5, H + 2)
                    sp, sr = rnd.choice((0, 0, 2)), rnd.choice((0, 0, 1))
                    rowlen = 0 if rl == '0' else (w if rl == 'w' else w + 3)
                    out.append((comps, al, rowlen, sp, sr, x, y, w, h, rnd.randrange(3)))
    out.append((3, 4, 0, 0, 0, 0, 0, W, H, 0))            # the whole buffer, as screenshot reads it
    out.append((4, 1, 0, 0, 0, W - 1, H - 1, 1, 1, 0))    # the last pixel
    return out


def expect(c):
    comps, al, rowlen, sp, sr, x, y, w, h, sh = c
    rs, gs, bs, as_ = SHIFTS[sh]
    rl = rowlen if rowlen > 0 else w
    stride = rl * comps
    if al > 1 and stride % al:
        stride += al - stride % al
    size = GUARD * 2 + (sr + h) * stride + (sp + w) * comps + 16
    buf = bytearray([0xab]) * size
    xmin, xmax, ymin, ymax = 0, W - 1, 0, H - 1
    skipP, skipR, rw, rh = sp, sr, w, h
    if x < xmin:
        skipP += xmin - x; rw -= xmin - x; x = xmin
    if x + rw > xmax:
        rw -= x + rw - xmax - 1
    if rw <= 0:
        return buf, 1
    if y < ymin:
        skipR += ymin - y; rh -= ymin - y; y = ymin
    if y + rh > ymax:
        rh -= y + rh - ymax - 1
    if rh <= 0:
        return buf, 1
    for r in range(rh):
        for k in range(rw):
            v = word(x + k, y + r)
            o = GUARD + (skipR + r) * stride + (skipP + k) * comps
            buf[o:o + 3] = bytes(((v >> rs) & 255, (v >> gs) & 255, (v >> bs) & 255))
            if comps == 4:
                buf[o + 3] = (v >> as_) & 255
    return buf, 1


def driver(cs):
    rows = ',\n'.join('{%d,%d,%d,%d,%d,%d,%d,%d,%d,%d}' % c for c in cs)
    shifts = ','.join('{%d,%d,%d,%d}' % s for s in SHIFTS)
    sizes = ','.join(str(len(expect(c)[0])) for c in cs)
    return r'''
#include <stdio.h>
#include <stdlib.h>
#include "OSRDNMesaReadPix.h"
static const long C[][10] = { %s };
static const int SH[][4] = { %s };
static const long SZ[] = { %s };
static unsigned long wordOf(long gx, long gy)
{ return (0x9e3779b1UL * (unsigned long)(gx + 1) ^ 0x85ebca77UL * (unsigned long)(gy + 7) ^ (unsigned long)(gx * gy)) & 0xffffffffUL; }
int main(void)
{
    static unsigned long surf[%d * %d];
    long r, k, i, n = (long)(sizeof C / sizeof C[0]);
    for (r = 0; r < %d; r++)            /* memory row r holds GL row H-1-r */
        for (k = 0; k < %d; k++)
            surf[r * %d + k] = (k < %d) ? wordOf(k, %d - 1 - r) : 0xdeadbeefUL;
    for (i = 0; i < n; i++) {
        osrdn_readpix_src s; osrdn_readpix_pack p; unsigned char *b; int ok;
        s.surf = surf; s.rowPixels = %d; s.width = %d; s.height = %d;
        s.rs = SH[C[i][9]][0]; s.gs = SH[C[i][9]][1]; s.bs = SH[C[i][9]][2]; s.as = SH[C[i][9]][3];
        s.xmin = 0; s.xmax = %d - 1; s.ymin = 0; s.ymax = %d - 1;
        p.alignment = (int)C[i][1]; p.rowLength = C[i][2]; p.skipPixels = C[i][3]; p.skipRows = C[i][4];
        b = (unsigned char *)malloc((size_t)SZ[i]);
        for (k = 0; k < SZ[i]; k++) b[k] = 0xab;
        ok = osrdn_readpix_flipped(&s, C[i][5], C[i][6], C[i][7], C[i][8], (int)C[i][0], &p, b + %d);
        printf("CASE %%ld ok=%%d ", i, ok);
        for (k = 0; k < SZ[i]; k++) printf("%%02x", b[k]);
        printf("\n");
        free(b);
    }
    return 0;
}
''' % (rows, shifts, sizes, H, ROWPIX, H, ROWPIX, ROWPIX, W, H, ROWPIX, W, H, W, H, GUARD)


MUTATIONS = [
    ('the rows are not flipped',
     'src = s->surf + (unsigned long) (s->height - 1L - (y + row)) * s->rowPixels', 'src = s->surf + (unsigned long) (y + row) * s->rowPixels'),
    ('the alignment is ignored',
     '    if (pk->alignment > 1 && stride % (long) pk->alignment != 0)\n', '    if (0)\n'),
    ('the bounds are exclusive',
     '        readW -= x + readW - s->xmax - 1;', '        readW -= x + readW - s->xmax;'),
    ('the alpha comes from the blue lane',
     '((word >> s->as) & 0xffUL)', '((word >> s->bs) & 0xffUL)'),
    ('skipRows is ignored',
     'd = dest + (skipRows + row) * stride', 'd = dest + row * stride'),
    ('a clipped column is not skipped',
     '        skipPixels += s->xmin - x;\n', ''),
]


def run(src_text, cs, tmp):
    open(os.path.join(tmp, 'OSRDNMesaReadPix.c'), 'w').write(src_text)
    open(os.path.join(tmp, 'drv.c'), 'w').write(driver(cs))
    exe = os.path.join(tmp, 'drv')
    r = subprocess.run(['gcc', '-O1', '-w', '-I', MESA, '-o', exe, os.path.join(tmp, 'drv.c'),
                        os.path.join(tmp, 'OSRDNMesaReadPix.c')], capture_output=True, text=True)
    if r.returncode:
        return None, r.stderr
    return subprocess.run([exe], capture_output=True, text=True).stdout, ''


def judge(out, cs):
    bad = []
    got = dict((int(m.group(1)), (int(m.group(2)), bytes.fromhex(m.group(3))))
               for m in re.finditer(r'CASE (\d+) ok=(\d) ([0-9a-f]*)', out))
    for i, c in enumerate(cs):
        want, wok = expect(c)
        if i not in got:
            bad.append('case %d: no line' % i); continue
        ok, b = got[i]
        if ok != wok or b != bytes(want):
            first = next((k for k in range(min(len(b), len(want))) if b[k] != want[k]), None)
            bad.append('case %d %s: ok=%d, first differing byte %s' % (i, c, ok, first))
    return bad


def main():
    cs = cases()
    src = open(SRC).read()
    fails = 0
    with tempfile.TemporaryDirectory() as t:
        out, e = run(src, cs, t)
        if out is None:
            print('sim_readpix: FAIL (does not build)\n' + e); return 1
        p = judge(out, cs)
        inside = sum(1 for c in cs if 0 <= c[5] and c[5] + c[7] <= W and 0 <= c[6] and c[6] + c[8] <= H)
        print('  %s %d cases (%d wholly inside, the rest across an edge or outside), every byte and guard byte%s'
              % ('ok  ' if not p else 'FAIL', len(cs), inside, '' if not p else ': ' + '; '.join(p[:3])))
        fails += bool(p)
    for label, a, b in MUTATIONS:
        if src.count(a) != 1:
            print('  FAIL mutation %-36s anchor found %d times' % (label, src.count(a))); fails += 1; continue
        with tempfile.TemporaryDirectory() as t:
            out, e = run(src.replace(a, b), cs, t)
            caught = out is None or bool(judge(out, cs))
        print('  %s mutation %-36s %s' % ('ok  ' if caught else 'FAIL', label, 'caught' if caught else 'NOT caught'))
        fails += 0 if caught else 1
    print('sim_readpix: %s' % ('PASS' if not fails else 'FAIL (%d)' % fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
