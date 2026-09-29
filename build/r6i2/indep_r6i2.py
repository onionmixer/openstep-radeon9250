"""R6i-2 independent recount: its own parser, coverage, ST interpolation and filter arithmetic.

  python3 build/r6i2/indep_r6i2.py <boot nonce>

The rule under test (measured on ff6dab1c):
  the ST is sampled at pixel + 1/2, the texel coordinate is s*w - 1/2,
  each axis' fraction is truncated to k/64,
  each 1-D mix is (a*(64-k) + b*k + r) >> 6 with r = 48 horizontally and r = 32 vertically,
  and with PP_CNTL.FILTER_ROUND_MODE set the horizontal r is 0.
"""
import math, re, sys
from fractions import Fraction as Fr

N = sys.argv[1]
TRI = [(4.0, 4.0), (20.0, 4.0), (4.0, 20.0)]
SH = Fr(1, 512 * 8)
CASES = {                     # name: (case number, s triple, t triple, pattern, r_horizontal)
    'Q1': (126, (Fr(1, 8) + SH, Fr(1, 4) + SH, Fr(17, 128) + SH), (Fr(3, 16),) * 3, 2, 48),
    'Q2': (127, (Fr(1, 8) + SH, Fr(1, 4) + SH, Fr(17, 128) + SH), (Fr(1, 4),) * 3, 2, 48),
    'Q3': (128, (Fr(5, 16),) * 3, (Fr(3, 16) + SH, Fr(3, 16) + Fr(1, 128) + SH, Fr(3, 16) + Fr(1, 8) + SH), 2, 48),
    'Q5': (130, (Fr(1, 8) + SH, Fr(1, 4) + SH, Fr(17, 128) + SH), (Fr(3, 16),) * 3, 2, 0),
}
RV = 32                       # the vertical constant


def texel(pat, u, v):
    return 0xff000000 | ((255 * (u & 1)) << 16) | ((255 * (v & 1)) << 8) | 0x55


def t16(v):
    return Fr(math.floor(v * 16), 16)


P = [(t16(x), t16(y)) for x, y in TRI]


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
                tl = (dy == 0 and dx > 0) or dy < 0
                if e < 0 or (e == 0 and not tl):
                    ins = False
                    break
            if ins:
                out.append((x, y))
    return out


COV = covered()


def interp(vals, x, y):
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    sx, sy = Fr(2 * x + 1, 2), Fr(2 * y + 1, 2)
    b1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
    b2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
    return (1 - b1 - b2) * vals[0] + b1 * vals[1] + b2 * vals[2]


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
for name, (num, st, tt, pat, rh) in sorted(CASES.items()):
    lane = {}
    for l in range(4):
        ws = planes[(num, l)]
        lane[l] = [x for k in range(32) for x in ws[k]]
    n = 0
    for (x, y) in COV:
        u = interp(st, x, y) * 8 - Fr(1, 2)
        v = interp(tt, x, y) * 8 - Fr(1, 2)
        i0, j0 = math.floor(u), math.floor(v)
        ku, kv = math.floor((u - i0) * 64), math.floor((v - j0) * 64)
        word = 0
        for l in range(4):
            def t(du, dv):
                return (texel(pat, (i0 + du) & 7, (j0 + dv) & 7) >> (8 * l)) & 0xff
            row0 = (t(0, 0) * (64 - ku) + t(1, 0) * ku + rh) >> 6
            row1 = (t(0, 1) * (64 - ku) + t(1, 1) * ku + rh) >> 6
            val = (row0 * (64 - kv) + row1 * kv + RV) >> 6
            word |= max(0, min(255, val)) << (8 * l)
        i = y * 32 + x
        got = sum(((lane[l][i // 4] >> (8 * (i % 4))) & 0xff) << (8 * l) for l in range(4))
        total += 1
        n += got != word
    bad += n
    print('%-3s %d pixels, %d differ' % (name, len(COV), n))
print('indep_r6i2: %d pixels, %d mismatches' % (total, bad))
