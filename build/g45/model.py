#!/usr/bin/env python3
"""G4-5 probe numbers (docs/G4_5_MIP_PLAN.md 3): scene D's texcoord spans and expected G, the
square layouts of scenes C/D/E/F.  Every constant the probe and the judge use comes from here;
the probe's C values are printed by --c and checked against this table by the judge."""
import math, sys

TEX = 128            # base level side
LEVELS = 8           # 128 .. 1

def level_g(i):
    return 32 * i    # scene D: level i's G (flat), R = 100, B = 0

def scene_d():
    """16 px squares, lambda = 1 + k/8: span s = 2^lambda / 8 so texels/pixel = 128 s / 16 = 2^lambda"""
    rows = []
    for k in range(9):
        lam = 1 + k / 8
        s = 2 ** lam / 8
        lo = math.floor(lam)
        f = lam - lo
        g = (1 - f) * level_g(lo) + f * level_g(min(lo + 1, LEVELS - 1))
        rows.append(dict(k=k, lam=lam, span=s, level=lo, f=f, g=g, x=40 + k * 40, y=100, n=16))
    return rows

def squares_ac():
    """scenes A/C: square i at lambda i -- 128..8 px with texcoords 0..1, then 8 px with 0..2/4/8"""
    out = []
    for sq in range(8):
        n = (TEX >> sq) if sq < 5 else 8
        t = 1.0 if sq < 5 else float(1 << (sq - 4))
        x = 50 + (sq if sq < 5 else sq - 5) * 150
        y = 100 if sq < 5 else 400
        out.append(dict(sq=sq, n=n, t=t, x=x, y=y, level=sq))
    return out

def scene_e():
    """three rows: before, after TexSubImage2D(level 2), after TexImage2D(level 2); each row a
    lambda 0 square (128 px, 0..1) and a lambda 2 square (32 px, 0..1)"""
    rows = []
    for r in range(3):
        rows.append(dict(row=r, x0=50, x2=250, y=50 + r * 180, n0=128, n2=32))
    return rows

if __name__ == '__main__':
    for r in scene_d():
        print('D k=%d lambda=%.3f span=%.9f level=%d f=%.3f G=%.1f at %d,%d' % (r['k'], r['lam'], r['span'], r['level'], r['f'], r['g'], r['x'], r['y']))
    # the squares must not overlap and must fit 800 x 600
    boxes = [(r['x'], r['y'], r['n']) for r in scene_d()]
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            (x1, y1, n1), (x2, y2, n2) = boxes[a], boxes[b]
            assert x1 + n1 <= x2 or x2 + n2 <= x1 or y1 + n1 <= y2 or y2 + n2 <= y1, (a, b)
    assert all(x + n <= 800 and y + n <= 600 for x, y, n in boxes)
    for s in squares_ac():
        print('AC sq=%d n=%d t=%g at %d,%d' % (s['sq'], s['n'], s['t'], s['x'], s['y']))
    for e in scene_e():
        print('E row=%d x0=%d x2=%d y=%d' % (e['row'], e['x0'], e['x2'], e['y']))
        assert e['y'] + 128 <= 600
    print('model ok')
