#!/usr/bin/env python3
"""G4-1b judge: the GHOST_TEXBIG scenes, accelerated against stock (docs/G4_GLQUAKE_PLAN.md 8-1).

  judge_texbig.py <dir with tb.*.ppm and tk.*.ppm> <probe log>

A hardware scene passes when every pixel that differs from stock by more than 32 in some
channel matches one of stock's eight neighbours within 32 (a sample-position difference of
at most one pixel: Matrox 4CA's allowance), a software scene when it is identical, and the
counters must say every triangle of a hardware scene reached the card.  The gradient
textures (R = column, G = row) also give the texel-per-pixel slope of each picture, which
must agree to 0.5 % -- a w = 1 vertex made it 1 % off and 2 texels ahead mid-quad.
"""
import re
import sys
import warnings

warnings.simplefilter('ignore')
from PIL import Image
import numpy as np

HARD = ['t64', 't256rgb', 't512', 'multi', 'sub', 'lm', 'redef', 'del']
SOFT = ['big', 'lum']
TRIS = {'t64': 2, 't256rgb': 2, 't512': 2, 'multi': 3, 'sub': 2, 'lm': 4, 'redef': 2, 'del': 2}
BG = (15, 20, 35)
# NEAREST gradient scenes: the texel-per-pixel slope must agree to 0.5 % (a w = 1 vertex made it
# 0.8 % off and 2 texels ahead mid-quad).  The LINEAR scene is judged by its mean texel OFFSET
# instead: R6i measured the card's bilinear at a = -1/2 texel and Mesa's software path differs
# from it by a constant texel or so, which a linear fit through the ramp's two ends misreads as a
# slope.
SLOPE = {'sub': (255 / 127, (340, 460)), 'redef': (255 / 63, None), 'del': (255 / 31, None)}
OFFSET = {'t256rgb': 1.0}


def load(p):
    return np.asarray(Image.open(p).convert('RGB')).astype(int)


def unexplained(a, s):
    d = np.abs(a - s).max(axis=2) > 32
    big = int(d.sum())
    ok = np.zeros_like(d)
    H, W = d.shape
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            sh = np.roll(np.roll(s, dy, axis=0), dx, axis=1)
            ok |= np.abs(a - sh).max(axis=2) <= 32
    return big, int((d & ~ok).sum())


def slope(img, y, per, exclude):
    xs, vs = [], []
    for x in range(258, 542):
        if exclude and exclude[0] <= x < exclude[1]:
            continue
        if tuple(img[y, x]) == BG:
            continue
        xs.append(x)
        vs.append(img[y, x][0] / per)
    return np.polyfit(xs, vs, 1)[0]


def main(d, log):
    fails = []
    for case in HARD + SOFT:
        try:
            a, s = load('%s/tb.%s.ppm' % (d, case)), load('%s/tk.%s.ppm' % (d, case))
        except IOError:
            fails.append('%s: picture missing' % case)
            continue
        diff = int((a != s).any(axis=2).sum())
        big, unx = unexplained(a, s)
        line = '  %-8s differing %6d  >32 %5d  not any stock neighbour %5d' % (case, diff, big, unx)
        if case in SOFT:
            if diff:
                fails.append('%s: a software scene differs from stock (%d px)' % (case, diff))
        elif unx:
            fails.append('%s: %d px match no stock neighbour' % (case, unx))
        if case in SLOPE:
            per, exc = SLOPE[case]
            sa, ss = slope(a, 520, per, exc), slope(s, 520, per, exc)
            line += '  texel/px %.4f vs %.4f (%.2f %%)' % (sa, ss, 100 * (sa / ss - 1))
            if abs(sa / ss - 1) > 0.005:
                fails.append('%s: the texel slope is %.2f %% off stock' % (case, 100 * (sa / ss - 1)))
        if case in OFFSET:
            per = OFFSET[case]
            row = [(a[520, x][0] - s[520, x][0]) / per for x in range(262, 538) if tuple(s[520, x]) != BG]
            off = sum(row) / len(row)
            line += '  mean texel offset %.2f' % off
            if abs(off) > 2.0:
                fails.append('%s: the card samples %.2f texels from stock (more than a bilinear convention)' % (case, off))
        print(line)
    text = open(log).read()
    m = re.search(r'GHOST texbig written; drawn=(\d+) delegated=(\d+) codeGap=(\d+) texAbsent=(\d+) texUploads=(\d+) texUploadBad=(\d+)', text)
    if not m:
        fails.append('the probe summary line is missing from the log')
    else:
        drawn, deleg, gap, absent, ups, bad = map(int, m.groups())
        want = sum(TRIS.values())
        print('  counters: drawn %d (want %d) delegated %d codeGap %d texAbsent %d uploads %d bad %d' % (drawn, want, deleg, gap, absent, ups, bad))
        if drawn != want:
            fails.append('drawn %d, want %d (every hardware-scene triangle on the card)' % (drawn, want))
        if deleg or gap or absent or bad:
            fails.append('delegated/codeGap/texAbsent/texUploadBad must all be 0')
    for f in fails:
        print('  FAIL ' + f)
    print('judge_texbig: %s' % ('PASS' if not fails else 'FAIL (%d)' % len(fails)))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
