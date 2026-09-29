#!/usr/bin/env python3
"""R6l design 1 (docs/R6L_PLAN.md 3-4): the grids, the submission sizes, and where the ring wraps.

Everything here is computed, not assumed: the triangles are laid out and checked against the
measured coverage rule (no overlap inside a packet, all inside the map), the submission lengths
follow osrdn_cp.m's own count, and the ring arithmetic follows cpR6Submit word for word.
"""
import sys

sys.path.insert(0, 'tools/r6')
import gouraud_oracle as go                      # noqa: E402  (the measured coverage rule)

MAPW = 32
RING, MASK = 4096, 0xfff


def grid(cell, nx, ny, per=1):
    """per=1: one right triangle in each cell; per=2: the cell's two halves, which tile it"""
    out = []
    for j in range(ny):
        for i in range(nx):
            x, y = float(i * cell), float(j * cell)
            a, b = x + cell, y + cell
            out.append([(x, y), (a, y), (x, b)])
            if per == 2:
                out.append([(a, y), (a, b), (x, b)])
    return out


def cover(tris):
    """{(x, y)} the union, and the number of pixels two triangles of the set share"""
    seen, dup = set(), 0
    for t in tris:
        for p in go.covered(t):
            if p in seen:
                dup += 1
            seen.add(p)
    return seen, dup


def submission(nvert, extra=0):
    """osrdn_cp.m: state 26 + blend stage 8 + clip 4 + header and VF 2 + vertices + tail 10"""
    return 26 + 8 + 4 + 2 + 5 * nvert + 10 + extra


def ring(p, n):
    """cpR6Submit: round to 16, pad to the end if it would not fit, return (pad, len, new wptr)"""
    length = (n + 15) & ~15
    pad = RING - p if length > RING - p else 0
    return pad, length, (p + pad + length) & MASK


G40, G80 = grid(4, 8, 5), grid(4, 8, 5, per=2)
for name, tris in (('G40', G40), ('G80', G80)):
    px, dup = cover(tris)
    # what must hold: every covered pixel is in the map, and every vertex is inside the buffer
    inmap = all(0 <= x < MAPW and 0 <= y < MAPW for x, y in px)
    inbuf = all(0 <= x <= 64 and 0 <= y <= 64 for t in tris for x, y in t)
    print('%-4s %3d triangles, %4d vertices, %4d pixels, %d shared, pixels in the map %s, vertices in the buffer %s' %
          (name, len(tris), 3 * len(tris), len(px), dup, inmap, inbuf))
    print('     submission %4d words -> ring %4d' % (submission(3 * len(tris)),
                                                     ring(0, submission(3 * len(tris)))[1]))

# ---- the boot's sequence: F, then BA BB BA BB BA BC BD BF
# BC: the same triangle shifted one pixel right each time -- every packet has its own left strip
# and they all share the right part, so the picture says which packet wrote last
STAIR = [[(float(4 + k), 4.0), (24.0, 4.0), (float(4 + k), 24.0)] for k in range(8)]
SEQ = [('F', submission(3)), ('BA', submission(120)), ('BB', submission(240)),
       ('BA', submission(120)), ('BB', submission(240)), ('BA', submission(120)),
       ('BC', submission(24, extra=8 * 2)), ('BD', submission(24, extra=8 * 2 + 2)),
       ('BF', submission(3))]
p, wraps = 0, []
print('--- the ring through the boot')
for name, n in SEQ:
    pad, length, q = ring(p, n)
    if q < p:
        wraps.append(name)
    print('  %-3s %4d words, pad %4d, wptr %4d -> %4d%s' % (name, n, pad, p, q, '   WRAP' if q < p else ''))
    p = q
print('wraps at: %s' % (wraps or 'NEVER -- the sequence must be longer'))

px, dup = cover(STAIR)
print('--- BC: %d triangles, %d pixels in the union' % (len(STAIR), len(px)))
# what the picture must be: the LAST triangle that covers a pixel decides its colour
winner = {}
for k, t in enumerate(STAIR):
    for q in go.covered(t):
        winner[q] = k
from collections import Counter
c = Counter(winner.values())
print('    pixels whose last writer is packet k: %s' % sorted(c.items()))
clip = (12, 12)
after = {}
for k, t in enumerate(STAIR):
    for q in go.covered(t):
        if k >= 4 and (q[0] < clip[0] or q[1] < clip[1]):
            continue                                  # BD: the scissor moves before packet 5
        after[q] = k
print('    BD differs from BC on %d pixels' % sum(1 for q in set(winner) | set(after)
                                                  if winner.get(q) != after.get(q)))
