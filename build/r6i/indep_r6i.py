"""R6i independent recount: its own parser, coverage, interpolation and texel addressing.

  python3 build/r6i/indep_r6i.py <boot nonce> [model]

Nothing here imports the oracles or the judge: the geometry, the ST triples, the W triples, the
texel patterns and the addressing are written out again from docs/R6I_PLAN.md 2-2, so that a shared
mistake cannot pass both.  It prints, per nearest-filtered case, how many covered pixels disagree
with the model (default the one the judge named).
"""
import math
import re
import sys
from fractions import Fraction as Fr

NONCE = sys.argv[1]
MODEL = sys.argv[2] if len(sys.argv) > 2 else 'Pq'

TRI = [(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)]     # T1z
W1 = (Fr(1), Fr(1), Fr(1))
WB = (Fr(1), Fr(1, 8), Fr(1, 2))
WC = (Fr(1), Fr(1, 4), Fr(1, 4))
WF = (Fr(1), Fr(8), Fr(2))
XA = ((Fr(0), Fr(1), Fr(0)), (Fr(0), Fr(0), Fr(1)))
# name: (w, h, pattern, clamp, ST, W, perspective?, VTE W0_FMT?)
CASES = {
    'PA': (8, 8, 0, 'clamp', XA, W1, True, False),
    'PB': (8, 8, 0, 'clamp', XA, WB, True, False),
    'PC': (8, 8, 0, 'clamp', XA, WC, True, False),
    'PD': (8, 8, 0, 'clamp', XA, WB, False, False),
    'PF': (8, 8, 0, 'clamp', XA, WF, True, True),
    'PH': (8, 8, 0, 'clamp', XA, W1, False, False),
    'LB': (2, 2, 1, 'clamp', XA, W1, False, False),
    'LE': (8, 8, 2, 'clamp', ((Fr(1, 8), Fr(2, 8), Fr(1, 8)), (Fr(1, 8), Fr(1, 8), Fr(2, 8))), W1, False, False),
    'LN': (2, 8, 0, 'clamp', XA, W1, False, False),
}
NUM = {'PA': 109, 'PB': 110, 'PC': 111, 'PD': 112, 'PF': 113, 'PH': 114, 'PE': 115, 'LA': 116,
       'LB': 117, 'LC': 118, 'LD': 119, 'LE': 120, 'LF': 121, 'PL': 122, 'PZ': 123, 'LN': 124}


def texel(pat, u, v):
    if pat == 0:
        return 0xff000000 | ((u * 32) << 16) | ((v * 32) << 8) | 0x55
    if pat == 1:
        return 0xff000000 | ((255 * (u & 1)) << 16) | ((255 * (v & 1)) << 8) | (255 * (u & 1) * (v & 1))
    return 0xff000000 | ((255 * (u & 1)) << 16) | ((255 * (v & 1)) << 8) | 0x55


def t16(v):                                       # the vertex, truncated to 1/16 (R6d)
    return Fr(math.floor(v * 16), 16)


P = [(t16(x), t16(y)) for x, y in TRI]


def covered():
    """the R6d rule: sample at pixel + 1/2, top-left edges included, winding-blind"""
    (x0, y0), (x1, y1), (x2, y2) = P
    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    sgn = 1 if area > 0 else -1
    out = []
    for y in range(32):
        for x in range(32):
            sx, sy = Fr(2 * x + 1, 2), Fr(2 * y + 1, 2)
            inside = True
            for i in range(3):
                j = (i + 1) % 3
                dx = (P[j][0] - P[i][0]) * sgn
                dy = (P[j][1] - P[i][1]) * sgn
                e = dx * (sy - P[i][1]) - dy * (sx - P[i][0])
                top_left = (dy == 0 and dx > 0) or dy < 0
                if e < 0 or (e == 0 and not top_left):
                    inside = False
                    break
            if inside:
                out.append((x, y))
    return out


COV = covered()


def weights(x, y, W, persp, off=Fr(1, 2)):   # measured: the ST is sampled at the pixel centre
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    sx, sy = Fr(x) + off, Fr(y) + off
    b1 = ((sx - x0) * (y2 - y0) - (x2 - x0) * (sy - y0)) / A
    b2 = ((x1 - x0) * (sy - y0) - (sx - x0) * (y1 - y0)) / A
    l = (1 - b1 - b2, b1, b2)
    if not persp:
        return l
    q = [W[i] if MODEL == 'Pq' else 1 / W[i] for i in range(3)]
    n = [l[i] * q[i] for i in range(3)]
    s = sum(n)
    return tuple(v / s for v in n)


def read_planes():
    planes, cur = {}, None
    for ln in open('build/r6/boot-%s.full.log' % NONCE, errors='replace'):
        m = re.search(r'plh boot=%s zc=\d+ case=(\d+) lane=(\d+) chunk=\d+' % NONCE, ln)
        if m:
            cur = (int(m.group(1)), int(m.group(2)))
            continue
        m = re.search(r'pl(\d) (\d+) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
        if m and cur:
            planes.setdefault(cur, {})[int(m.group(2))] = [int(w, 16) for w in m.group(3).split()]
    return planes


PL = read_planes()
total = bad = 0
for name, (w, h, pat, mode, (st, tt), W, persp, w0fmt) in sorted(CASES.items()):
    c = NUM[name]
    if (c, 0) not in PL:
        print('%-3s no planes' % name)
        continue
    lane = {}
    for l in range(4):
        ws = PL[(c, l)]
        lane[l] = [x for k in range(32) for x in ws[k]]
    n = 0
    Weff = tuple(1 / v for v in W) if w0fmt else W      # measured: VTX_W0_FMT makes the
                                                       # hardware take the reciprocal first
    for (x, y) in COV:
        lw = weights(x, y, Weff, persp)
        s = sum(lw[i] * st[i] for i in range(3)) * w
        t = sum(lw[i] * tt[i] for i in range(3)) * h
        fu, fv = s - math.floor(s), t - math.floor(t)
        if min(fu, 1 - fu) <= Fr(1, 1024) or min(fv, 1 - fv) <= Fr(1, 1024):
            continue                              # risky: a tap index could move
        u, v = math.floor(s), math.floor(t)
        u = max(0, min(w - 1, u)) if mode == 'clamp' else u % w
        v = max(0, min(h - 1, v)) if mode == 'clamp' else v % h
        i = y * 32 + x
        got = sum(((lane[l][i // 4] >> (8 * (i % 4))) & 0xff) << (8 * l) for l in range(4))
        want = texel(pat, u, v)
        total += 1
        n += got != want
    bad += n
    print('%-3s safe pixels checked, %d differ' % (name, n))
print('indep_r6i (%s): %d pixels, %d mismatches' % (MODEL, total, bad))
