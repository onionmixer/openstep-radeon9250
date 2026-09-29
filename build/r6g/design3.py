# R6g two-draw cases: predictions and the power of each test
import sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
go=do.go; zo=do.zo
T=do.GEOM['T1z']; pix=sorted(go.covered(T)); n=len(pix)
def zi(v): return math.floor(Fr(v)*65536)
def interp(zs):
    P=[(go.pos(x,'t16'),go.pos(y,'t16')) for x,y in T]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0); z=[Fr(v) for v in zs]
    out={}
    for x,y in pix:
        sx,sy=Fr(2*x+1,2),Fr(2*y+1,2)
        w1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A; w2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
        out[(x,y)]=(1-w1-w2)*z[0]+w1*z[1]+w2*z[2]
    return out
# H1: draw1 ALWAYS z=0.25 -> stored 16384 everywhere; draw2 LESS z=0.75 must fail everywhere
d1, d2 = zi(0.25), zi(0.75)
print('H1 draw1 %d draw2 %d -> draw2 passes %d of %d (want 0)' % (d1, d2, sum(1 for p in pix if d2 < d1), n))
pat = do.pattern_block()
stale = sum(1 for x, y in pix if d2 < do.read_depth(pat, x, y, 16))
print('H1 power: if the test read the ZPREP pattern instead, %d of %d pixels would pass' % (stale, n))
# H2: prefill 0.75, draw1 z=0.25 LESS write off, draw2 z=0.5 LESS
s, a, b = zi(0.75), zi(0.25), zi(0.5)
print('H2 prefill %d; draw1 passes %s (no write); draw2 vs prefill passes %d of %d (want %d); if draw1 had written, %d'
      % (s, a < s, sum(1 for p in pix if b < s), n, n, sum(1 for p in pix if b < a)))
# H3: z = 0.5 + 2^-17 both draws; EQUAL on the second
zf = 0.5 + 2.0**-17
print('H3 stored %d, integer compare -> EQUAL passes %d of %d; unfloored compare -> %d'
      % (zi(zf), n, n, 0))
# H4: draw1 ALWAYS (0.25,0.75,0.25); draw2 LESS (0.75,0.25,0.75)
i1, i2 = interp((0.25, 0.75, 0.25)), interp((0.75, 0.25, 0.75))
v1 = {p: math.floor(i1[p]*65536) for p in pix}; v2 = {p: math.floor(i2[p]*65536) for p in pix}
win = [p for p in pix if v2[p] < v1[p]]
near = [p for p in pix if abs(v2[p]-v1[p]) <= 2]
print('H4 draw2 passes %d of %d; pixels within 2 LSB of the crossing: %d %s' % (len(win), n, len(near), sorted(near)[:4]))
print('H4 depth after: draw2 value where it passes, draw1 value elsewhere; ranges %d..%d / %d..%d'
      % (min(v1.values()), max(v1.values()), min(v2.values()), max(v2.values())))
