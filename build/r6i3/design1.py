#!/usr/bin/env python3
"""R6i-3 design 1: which k values does a sweep reach, and which r constants can it separate?

byte = (a*(64-k) + b*k + r) >> 6 with a, b in {0, 255}: two r values are told apart by a k only if
the shift crosses.  Q5 (the bit-set case) left r in {0, 8, 16, 24, 32} open -- find a sweep that
separates them, and check the transposed pattern tells "per axis" from "per channel"."""
import math, sys
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe

def ks(case):
    return sorted(set(math.floor(fu * 64) for p, i0, fu, j0, fv in pe.taps(case)))

for c in ('Q1', 'Q5', 'Q2'):
    k = ks(c)
    print('%s: %d distinct ku, missing %d of 0..63: %s' % (c, len(k), 64 - len(k), [x for x in range(64) if x not in k][:12]))

def seps(kset, rs=(0, 8, 16, 24, 32, 40, 48, 56)):
    """{(r, r'): how many k values give a different byte}"""
    out = {}
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            d = 0
            for k in kset:
                for a, b in ((0, 255), (255, 0)):
                    if ((a * (64 - k) + b * k + rs[i]) >> 6) != ((a * (64 - k) + b * k + rs[j]) >> 6):
                        d += 1
                        break
            out[(rs[i], rs[j])] = d
    return out

s = seps(ks('Q5'))
print('Q5 separations (pairs that stay together):', sorted([p for p, d in s.items() if d == 0]))
print('Q5 smallest non-zero separation:', min(d for d in s.values() if d))
full = seps(list(range(64)))
print('a sweep reaching all 64 k values: pairs that stay together: %s, smallest %d' %
      (sorted([p for p, d in full.items() if d == 0]), min(d for d in full.values() if d)))
