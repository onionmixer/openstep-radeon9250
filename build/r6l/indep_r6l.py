"""R6l independent recount: own parser, own triangles, own coverage, own ordering rule.

  python3 build/r6l/indep_r6l.py <boot nonce>

Nothing here imports the oracles: the grids, the staircase, the clip change and the rule that the
last packet to cover a pixel owns it are written out again from docs/R6L_PLAN.md, so that one
mistake cannot pass both.  It also re-derives the ring arithmetic and says where the wrap fell.
"""
import math
import re
import sys
from fractions import Fraction as Fr

N = sys.argv[1]
MAPW = 32
RING = 4096
CLIP0 = (0, 0, 64, 64)
CLIP_BD = (12, 12, 32, 32)
CODE_A, CODE_B = 1, 2


def cell_tris(cell, nx, ny, per):
    out = []
    for j in range(ny):
        for i in range(nx):
            x, y = float(i * cell), float(j * cell)
            a, b = x + cell, y + cell
            out.append([(x, y), (a, y), (x, b)])
            if per == 2:
                out.append([(a, y), (a, b), (x, b)])
    return out


G40 = cell_tris(4, 8, 5, 1)
G80 = cell_tris(4, 8, 5, 2)
STAIR = [[(float(4 + k), 4.0), (24.0, 4.0), (float(4 + k), 24.0)] for k in range(8)]
T1 = [[(4.0, 4.0), (28.0, 4.0), (4.0, 28.0)]]
# case number: [(triangles, colour code, new clip or None)] -- one entry per packet
CASES = {
    161: [(G40, CODE_A, None)],
    162: [(G80, CODE_A, None)],
    163: [([STAIR[k]], CODE_A if k % 2 == 0 else CODE_B, None) for k in range(8)],
    164: [([STAIR[k]], CODE_A if k % 2 == 0 else CODE_B, CLIP_BD if k == 4 else None) for k in range(8)],
    165: [(T1, CODE_A, None)],
}
NAME = {161: 'BA', 162: 'BB', 163: 'BC', 164: 'BD', 165: 'BF'}


def covered(tri):
    """the measured rule: vertices truncated to 1/16, the sample at pixel + 1/2, top-left edges in"""
    P = [(Fr(math.floor(x * 16), 16), Fr(math.floor(y * 16), 16)) for x, y in tri]
    (x0, y0), (x1, y1), (x2, y2) = P
    A = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if A == 0:
        return []
    sgn = 1 if A > 0 else -1
    out = []
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
                out.append((x, y))
    return out


def want(case):
    """{(x, y): code} -- the packets in order, the last one to cover a pixel owns it"""
    out, clip = {}, CLIP0
    for tris, code, newclip in CASES[case]:
        if newclip is not None:
            clip = newclip
        x1, y1, x2, y2 = clip
        for t in tris:
            for (x, y) in covered(t):
                if x1 <= x <= x2 - 1 and y1 <= y <= y2 - 1:
                    out[(x, y)] = code
    return out


# ---- the log, one operation at a time (the driver logs its coverage map before the case line and
# the digest after it, so grouping by operation is the only order-proof way to read it)
text = open('build/r6/boot-%s.full.log' % N, errors='replace').read()
wptr, order = [], []
for chunk in text.split('RDN-R5 begin ')[1:]:
    chunk = chunk[:chunk.index('RDN-R5 begin ')] if 'RDN-R5 begin ' in chunk else chunk
    m = re.search(r'wptr=(\d+)', chunk)
    if m:
        wptr.append(int(m.group(1)))
    m = re.search(r'RDN-R6 zclear case=(\d+) stage=3', chunk)
    if not m or int(m.group(1)) not in CASES:
        continue
    words = {}
    for cm in re.finditer(r'RDN-R6 cov(\d) ((?:[0-9a-f]{8} ?){8})', chunk):
        words[int(cm.group(1))] = [int(x, 16) for x in cm.group(2).split()]
    order.append((int(m.group(1)), words))

total = bad = 0
seen = {}
for run, (c, words) in enumerate(order):
    if sorted(words) != list(range(8)):
        print('%-3s run %d: coverage map lines %s' % (NAME[c], run, sorted(words)))
        continue
    w = [x for k in range(8) for x in words[k]]
    got = {}
    for i in range(1024):
        code = (w[i >> 4] >> (2 * (i & 15))) & 3
        if code:
            got[(i % 32, i // 32)] = code
    exp = want(c)
    d = sum(1 for q in set(got) | set(exp) if got.get(q) != exp.get(q))
    total += len(exp)
    bad += d
    same = '' if c not in seen else ('  same as run %d: %s' % (seen[c], 'yes' if got == seen[(c, 'px')] else 'NO'))
    if c not in seen:
        seen[c], seen[(c, 'px')] = run, got
    print('%-3s run %d: %4d pixels wanted, %4d seen, %3d differ%s' % (NAME[c], run, len(exp), len(got), d, same))
drops = [(a, b) for a, b in zip(wptr, wptr[1:]) if b < a]
print('the ring wrapped %d time(s): %s' % (len(drops), ' '.join('%d>%d' % d for d in drops) or 'never'))
print('indep_r6l: %d pixels over %d runs, %d mismatches' % (total, len(order), bad))
