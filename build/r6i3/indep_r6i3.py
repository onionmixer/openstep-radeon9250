"""R6i-3 independent recount: own parser, coverage, ST interpolation, pattern and filter.

  python3 build/r6i3/indep_r6i3.py <boot nonce>

The rule under test: ST at pixel + 1/2, u = s*w - 1/2, each axis truncated to k/64, and each 1-D mix
(a*(64-k) + b*k + r) >> 6 with r = 48 across and 32 down -- and r = 16 for BOTH when PP_CNTL bit 10
(FILTER_ROUND_MODE) is set.  The constant follows the AXIS, not the colour channel.
"""
import math, re, sys
from fractions import Fraction as Fr
N = sys.argv[1]
TRI = [(4.0, 4.0), (20.0, 4.0), (4.0, 20.0)]
CASES = {                 # name: (case, s triple, t triple, pattern, r across, r down)
    'N1': (131, (Fr(257, 4096), Fr(737, 4096), Fr(289, 4096)), (Fr(3, 16),) * 3, 3, 48, 32),
    'N2': (132, (Fr(5, 16),) * 3, (Fr(257, 4096), Fr(289, 4096), Fr(737, 4096)), 3, 48, 32),
    'N3': (133, (Fr(1281, 4096), Fr(1761, 4096), Fr(1313, 4096)), (Fr(3, 16),) * 3, 2, 16, 16),
    'N4': (134, (Fr(5, 16),) * 3, (Fr(1281, 4096), Fr(1313, 4096), Fr(1761, 4096)), 2, 16, 16),
    'N5': (135, (Fr(1281, 4096), Fr(1761, 4096), Fr(1313, 4096)), (Fr(3, 16),) * 3, 2, 48, 32),
}


def texel(pat, u, v):
    if pat == 3:
        return 0xff000000 | ((255 * (v & 1)) << 16) | ((255 * (u & 1)) << 8) | 0x55
    return 0xff000000 | ((255 * (u & 1)) << 16) | ((255 * (v & 1)) << 8) | 0x55


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


def interp(v, x, y):
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    sx, sy = Fr(2 * x + 1, 2), Fr(2 * y + 1, 2)
    b1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
    b2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
    return (1 - b1 - b2) * v[0] + b1 * v[1] + b2 * v[2]


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
for name, (num, st, tt, pat, rh, rv) in sorted(CASES.items()):
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
            word |= max(0, min(255, (row0 * (64 - kv) + row1 * kv + rv) >> 6)) << (8 * l)
        i = y * 32 + x
        got = sum(((lane[l][i // 4] >> (8 * (i % 4))) & 0xff) << (8 * l) for l in range(4))
        total += 1
        n += got != word
    bad += n
    print('%-3s %d pixels, %d differ' % (name, len(COV), n))
print('indep_r6i3: %d pixels, %d mismatches' % (total, bad))
