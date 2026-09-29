"""R6j independent recount: own parser, coverage, Gouraud rule B, factors and blend arithmetic.

  python3 build/r6j/indep_r6j.py <boot nonce> [fmap] [r]

Nothing here imports the oracles: the geometry, the destination colours, the source colour, the
factor table and the arithmetic are written out again from docs/R6J_PLAN.md, so that one mistake
cannot pass both.  Defaults to the plain reading (factor as-is, no rounding constant); pass the
values the judge named to check them.
"""
import math
import re
import sys
from fractions import Fraction as Fr

N = sys.argv[1]
FMAP = sys.argv[2] if len(sys.argv) > 2 else 'id'
RCON = int(sys.argv[3]) if len(sys.argv) > 3 else 0

TRI = [(4.0, 4.0), (20.0, 4.0), (4.0, 20.0)]
DST_V = ((0x10, 0x20, 0xf0, 0x40), (0xe0, 0x90, 0x30, 0xc0), (0x70, 0xf0, 0x80, 0x20))   # r g b a
SRC = (0xc1, 0x2a, 0x9b, 0x37)
CASES = {                      # name: (case number, source factor, destination factor, combine)
    'J1': (136, 'ONE', 'ZERO', 'ADD'), 'J2': (137, 'ZERO', 'ONE', 'ADD'),
    'J3': (138, 'ONE', 'ONE', 'ADD'), 'J4': (139, 'SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD'),
    'J5': (140, 'DST_COLOR', 'ZERO', 'ADD'), 'J6': (141, 'SRC_ALPHA', 'ONE', 'ADD'),
    'J7': (142, 'SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD'), 'J8': (143, 'ONE', 'ONE', 'SUB'),
    'J9': (144, 'SRC_ALPHA', 'ONE_MINUS_SRC_ALPHA', 'ADD'), 'J0': (145, None, None, None),
}
P = [(Fr(math.floor(x * 16), 16), Fr(math.floor(y * 16), 16)) for x, y in TRI]


def covered():
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    sgn = 1 if A > 0 else -1
    out = []
    for y in range(32):
        for x in range(32):
            sx, sy = Fr(2 * x + 1, 2), Fr(2 * y + 1, 2)
            ins = True
            for i in range(3):
                j = (i + 1) % 3
                dx, dy = (P[j][0] - P[i][0]) * sgn, (P[j][1] - P[i][1]) * sgn
                e = dx * (sy - P[i][1]) - dy * (sx - P[i][0])
                if e < 0 or (e == 0 and not ((dy == 0 and dx > 0) or dy < 0)):
                    ins = False
                    break
            if ins:
                out.append((x, y))
    return out


COV = covered()


def rule_b(vals):
    """R6e rule B: the two weights other than the leftmost vertex's rounded to 1/256 (half to even),
    the leftmost taking the rest, the weighted sum floored"""
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    L = min(range(3), key=lambda i: (P[i][0], P[i][1]))
    out = {}
    for x, y in COV:
        sx, sy = Fr(2 * x + 1, 2), Fr(2 * y + 1, 2)
        w1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
        w2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
        w = [1 - w1 - w2, w1, w2]
        for i in range(3):
            if i != L:
                w[i] = Fr(round(w[i] * 256), 256)
        w[L] = 1 - sum(w[i] for i in range(3) if i != L)
        out[(x, y)] = max(0, min(255, math.floor(sum(wi * Fr(ci) for wi, ci in zip(w, vals)))))
    return out


DST = dict((p, tuple(rule_b([DST_V[v][c] for v in range(3)])[p] for c in range(4))) for p in COV)


def factor(name, s, d, lane):
    if name == 'ZERO':
        return 0
    if name == 'ONE':
        return 255
    if name == 'SRC_COLOR':
        return s[lane]
    if name == 'DST_COLOR':
        return d[lane]
    if name == 'SRC_ALPHA':
        return s[3]
    if name == 'ONE_MINUS_SRC_ALPHA':
        return 255 - s[3]
    if name == 'DST_ALPHA':
        return d[3]
    return 255 - d[3]


def fmap(x):
    if FMAP == 'sat256':
        return 256 if x == 255 else x
    if FMAP == 'expand':
        return x + (x >> 7)
    if FMAP == 'plus1':                          # the measured reading: 0x37 multiplies as 0x38
        return x + 1
    return x


planes, cur = {}, None
for ln in open('build/r6/boot-%s.full.log' % N, errors='replace'):
    m = re.search(r'plh boot=%s zc=\d+ case=(\d+) lane=(\d+) chunk=\d+' % N, ln)
    if m:
        cur = (int(m.group(1)), int(m.group(2)))
        continue
    m = re.search(r'pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m and cur:
        planes.setdefault(cur, {})[int(m.group(2))] = [int(w, 16) for w in m.group(3).split()]

total = bad = 0
for name, (num, fs, fd, comb) in sorted(CASES.items()):
    if (num, 0) not in planes:
        print('%-3s no planes' % name)
        continue
    lane = {}
    for l in range(4):
        ws = planes[(num, l)]
        lane[l] = [x for k in range(32) for x in ws[k]]
    n = 0
    for (x, y) in COV:
        d = DST[(x, y)]
        dl = (d[2], d[1], d[0], d[3])            # the framebuffer word's lanes: b, g, r, a
        sl = (SRC[2], SRC[1], SRC[0], SRC[3])
        word = 0
        for l in range(4):
            if fs is None:
                v = sl[l]
            else:
                t = (sl[l] * fmap(factor(fs, sl, dl, l)) + RCON) >> 8
                u = (dl[l] * fmap(factor(fd, sl, dl, l)) + RCON) >> 8
                v = max(0, min(255, t + u if comb == 'ADD' else t - u))
            word |= v << (8 * l)
        i = y * 32 + x
        got = sum(((lane[l][i // 4] >> (8 * (i % 4))) & 0xff) << (8 * l) for l in range(4))
        total += 1
        n += got != word
    bad += n
    print('%-3s %d pixels, %d differ' % (name, len(COV), n))
print('indep_r6j (%s, r=%d): %d pixels, %d mismatches' % (FMAP, RCON, total, bad))
