"""R6k independent recount: own parser, own coverage, own rectangles, own rule.

  python3 build/r6k/indep_r6k.py <boot nonce> [layout] [end] [polarity] [combine] [wx] [wy] [sign]

Nothing here imports the oracles: the geometry, the rectangles, the enable bits and the reading are
written out again from docs/R6K_PLAN.md, so that one mistake cannot pass both.  The defaults are the
plain reading (x in the low half, the bottom-right included, EXCLUSIVE=0 keeps the inside, the
enabled rectangles intersected); pass others to check a different name.
"""
import math
import re
import sys
from fractions import Fraction as Fr

N = sys.argv[1]
LAYOUT = sys.argv[2] if len(sys.argv) > 2 else 'x_low'
END = sys.argv[3] if len(sys.argv) > 3 else 'br_incl'
POL = sys.argv[4] if len(sys.argv) > 4 else 'keep'
COMB = sys.argv[5] if len(sys.argv) > 5 else 'and'
WX = int(sys.argv[6]) if len(sys.argv) > 6 else 16        # bits the x half really uses
WY = int(sys.argv[7]) if len(sys.argv) > 7 else 16
SIGN = sys.argv[8] if len(sys.argv) > 8 else 'unsigned'

MAPW = 32
RECT = {'R0': ((6, 3), (20, 13)), 'R1': ((10, 8), (26, 24)), 'R2': ((2, 18), (14, 29)),
        'inv': ((20, 13), (6, 3)), 'all': ((0, 0), (63, 63)),
        'bias': ((1446, 1443), (1460, 1453)), 'hx': ((2054, 3), (2068, 13)),
        'hy': ((6, 2051), (20, 2061)), 'neg': ((2032, 2032), (20, 13))}
# case number: (box side, clip, RE_CNTL, [(rectangle, exclusive)])
CASES = {
    146: (32.0, (0, 0, 64, 64), 2, []),
    147: (32.0, (0, 0, 64, 64), 2, [('R0', 0)]),
    148: (32.0, (0, 0, 64, 64), 2, [('R0', 1)]),
    149: (32.0, (0, 0, 64, 64), 2, [('R0', 0), ('R1', 0)]),
    150: (32.0, (0, 0, 64, 64), 2, [('R0', 0), ('R1', 1)]),
    151: (32.0, (0, 0, 64, 64), 2, [('R2', 0)]),
    152: (32.0, (0, 0, 64, 64), 2, [('inv', 0)]),
    153: (40.0, (0, 0, 32, 32), 2, [('all', 0)]),
    154: (32.0, (0, 0, 64, 64), 2, [('R0', 0)]),
    155: (32.0, (0, 0, 64, 64), 2, [('bias', 0)]),
    156: (32.0, (0, 0, 64, 64), 2, [('hx', 0)]),
    157: (32.0, (20, 13, 7, 4), 2, []),
    158: (32.0, (0, 0, 64, 64), 0, [('R0', 0)]),
    159: (32.0, (0, 0, 64, 64), 2, [('hy', 0)]),
    160: (32.0, (0, 0, 64, 64), 2, [('neg', 0)]),
}
NAME = dict((146 + k, 'AS%d' % k) for k in range(15))


def covered(side):
    """the map pixels the two triangles (0,0)(s,0)(0,s) and (s,0)(s,s)(0,s) cover, by the measured
    rule: vertices truncated to 1/16, the sample at pixel + 1/2, top-left edges included"""
    out = set()
    for pts in ([(0.0, 0.0), (side, 0.0), (0.0, side)], [(side, 0.0), (side, side), (0.0, side)]):
        P = [(Fr(math.floor(x * 16), 16), Fr(math.floor(y * 16), 16)) for x, y in pts]
        (x0, y0), (x1, y1), (x2, y2) = P
        A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        sgn = 1 if A > 0 else -1
        for y in range(MAPW):
            for x in range(MAPW):
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
                    out.add((x, y))
    return out


def half(v, w):
    """what the hardware sees in one half word: the low w bits, signed if SIGN says so"""
    v &= (1 << w) - 1
    if SIGN == 'signed' and (v >> (w - 1)):
        v -= 1 << w
    return v


def inside(p, rect):
    (ax, ay), (bx, by) = RECT[rect]
    if LAYOUT == 'y_low':
        ax, ay, bx, by = ay, ax, by, bx
    ax, bx, ay, by = half(ax, WX), half(bx, WX), half(ay, WY), half(by, WY)
    hi = 0 if END == 'br_incl' else -1
    return ax <= p[0] <= bx + hi and ay <= p[1] <= by + hi


def want(case):
    side, (cx1, cy1, cx2, cy2), recntl, slots = CASES[case]
    lo = (cx1, cy1) if recntl & 2 else (0, 0)
    out = set()
    for p in covered(side):
        if not (lo[0] <= p[0] <= cx2 - 1 and lo[1] <= p[1] <= cy2 - 1):
            continue
        keeps = []
        for rect, exc in slots:
            ins = inside(p, rect)
            keeps.append(ins if (POL == 'keep') != bool(exc) else not ins)
        if not keeps or (all(keeps) if COMB == 'and' else any(keeps)):
            out.add(p)
    return out


# the coverage map is logged BEFORE its case names itself and the digest after it
cov, dig, case, pend = {}, {}, None, {}
for ln in open('build/r6/boot-%s.full.log' % N, errors='replace'):
    m = re.search(r'RDN-R6 cov(\d) ((?:[0-9a-f]{8} ?){8})\s*$', ln)
    if m:
        pend[int(m.group(1))] = [int(x, 16) for x in m.group(2).split()]
        continue
    m = re.search(r'RDN-R6 zclear case=(\d+) stage=3', ln)
    if m:
        case = int(m.group(1))
        if pend:
            cov[case] = pend
            pend = {}
        continue
    m = re.search(r'RDN-R6 zc1 xor=\w+ wsum=\w+ changed=(\d+) ', ln)
    if m and case and case not in dig:
        dig[case] = int(m.group(1))

total = bad = 0
for c in sorted(CASES):
    if c not in cov or sorted(cov[c]) != list(range(8)):
        print('%-4s no coverage map' % NAME[c])
        continue
    words = [w for k in range(8) for w in cov[c][k]]
    got = set((i % 32, i // 32) for i in range(1024) if (words[i >> 4] >> (2 * (i & 15))) & 3)
    w = want(c)
    d = len(got ^ w)
    total += len(w)
    bad += d
    print('%-4s %4d pixels wanted, %4d seen, %3d differ, colour words changed %s' %
          (NAME[c], len(w), len(got), d, dig.get(c)))
    if dig.get(c) is not None and dig[c] != len(got):
        print('     a write outside the map: %d words changed, the map has %d' % (dig[c], len(got)))
print('indep_r6k (%s, %s, %s, %s): %d pixels, %d mismatches' % (LAYOUT, END, POL, COMB, total, bad))
