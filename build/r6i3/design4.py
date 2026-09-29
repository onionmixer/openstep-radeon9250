#!/usr/bin/env python3
"""R6i-3 design 4: the exact ST triples for S1..S5, and a check that every value is exact in float32
and that the sweeps stay inside one texel with an even tap."""
import math, struct, sys
from fractions import Fraction as Fr
exec(open("build/r6i3/design2.py").read().split("SH=Fr(1,512)")[0])
SH = Fr(1, 512)
def f32(x): return Fr(struct.unpack('<f', struct.pack('<f', float(x)))[0])
def st_u(U0, V0, w=8, h=8):
    u0 = U0 + Fr(1, 2); v0 = V0 + Fr(1, 2)
    return (Fr(u0, w), Fr(u0 + Fr(15, 16), w), Fr(u0 + Fr(1, 16), w)), (Fr(v0, h),) * 3
def st_v(U0, V0, w=8, h=8):
    u0 = U0 + Fr(1, 2); v0 = V0 + Fr(1, 2)
    return (Fr(u0, w),) * 3, (Fr(v0, h), Fr(v0 + Fr(1, 16), h), Fr(v0 + Fr(15, 16), h))
CASES = {
    'S1': st_u(Fr(0) + SH, Fr(1)),
    'S2': st_v(Fr(2), Fr(0) + SH),
    'S3': st_u(Fr(2) + SH, Fr(1)),
    'S4': st_v(Fr(2), Fr(2) + SH),
    'S5': st_u(Fr(2) + SH, Fr(1)),
}
for n, (st, tt) in sorted(CASES.items()):
    exact = all(f32(v) == v for v in st + tt)
    pr = []
    for (x, y) in COV:
        u = interp(st, x, y) * 8 - Fr(1, 2); v = interp(tt, x, y) * 8 - Fr(1, 2)
        i0, j0 = math.floor(u), math.floor(v)
        pr.append((i0, math.floor((u - i0) * 64), j0, math.floor((v - j0) * 64), u - i0, v - j0))
    i0s = sorted(set(p[0] for p in pr)); j0s = sorted(set(p[2] for p in pr))
    print('%s: s=%s t=%s' % (n, [str(x) for x in st], [str(x) for x in tt]))
    print('    float32 exact %s, taps i %s j %s, distinct ku %d kv %d, fu==0 on %d, fv==0 on %d' %
          (exact, i0s, j0s, len(set(p[1] for p in pr)), len(set(p[3] for p in pr)),
           sum(1 for p in pr if p[4] == 0), sum(1 for p in pr if p[5] == 0)))
