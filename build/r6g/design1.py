# R6g design: a constant-z triangle over a prefilled depth ramp -- how many pixels fall on each side
import sys
sys.path.insert(0, 'tools/r6'); import depth_oracle as do
go = do.go
T = do.GEOM['T1z']                      # (4,4) (28,4) (4,28): 276 pixels
pix = sorted(go.covered(T))
Zc16, B16 = 32768, 1024                 # z = 0.5 -> floor(0.5 * 65536); ramp 1024 a pixel in x
A16 = Zc16 - 16 * B16
def stored(x, y, A=A16, B=B16, C=0): return A + B * x + C * y
less = [p for p in pix if Zc16 < stored(*p)]      # the new value is LESS than the stored one
eq   = [p for p in pix if Zc16 == stored(*p)]
gt   = [p for p in pix if Zc16 > stored(*p)]
print('pixels', len(pix), 'new<stored', len(less), 'equal', len(eq), 'new>stored', len(gt))
print('equal column x =', sorted(set(x for x, y in eq)), 'rows', len(eq))
print('stored range', min(stored(*p) for p in pix), max(stored(*p) for p in pix), '(16-bit top 65535)')
Zc24, B24 = 1 << 23, 1 << 18
A24 = Zc24 - 16 * B24
print('24-bit stored range', A24 + B24 * 4, A24 + B24 * 27, 'Zc', Zc24)
# the interpolated case: z from 0.25 to 0.75 in x (I1's z) against a constant prefill at the middle
import math
from fractions import Fraction as Fr
pts, zs = do.triangles('I1_16')[0]
P = [(go.pos(x, 't16'), go.pos(y, 't16')) for x, y in pts]
(x0, y0), (x1, y1), (x2, y2) = P
Aa = (x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
def zat(x, y):
    sx, sy = Fr(2*x+1, 2), Fr(2*y+1, 2)
    w1 = ((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/Aa; w2 = ((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/Aa
    return (1-w1-w2)*Fr(zs[0]) + w1*Fr(zs[1]) + w2*Fr(zs[2])
drawn = {p: math.floor(zat(*p) * 65536) for p in pix}
S = 32768                                # a constant prefill
near = [p for p in pix if abs(drawn[p] - S) <= 2]
print('interpolated case: drawn range', min(drawn.values()), max(drawn.values()), 'within 2 LSB of the prefill:', len(near), sorted(near)[:6])
