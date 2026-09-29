import sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
go=do.go
FEAS = {
 'I1_24': ((349525.30769, 349525.33333), (-0.00781, 0.00781)),
 'I3_24': ((-236103.72340, -236103.71795), (414158.96875, 414158.98148)),
 'I4_24': ((449011.59184, 449011.59429), (143695.94690, 143695.95062)),
 'I6_24': ((-403555.67925, -403555.67273), (-726094.47500, -726094.46667)),
 'I7_24': ((49504.34884, 49504.37500), (-441623.50575, -441623.48649)),
}
def grads(name):
    pts, zs = do.triangles(name)[0]
    P=[(go.pos(x,'t16'),go.pos(y,'t16')) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0); S=1<<do.fmt_bits(name)
    Z=[Fr(v)*S for v in zs]
    gx=((Z[1]-Z[0])*(y2-y0)-(Z[2]-Z[0])*(y1-y0))/A
    gy=((Z[2]-Z[0])*(x1-x0)-(Z[1]-Z[0])*(x2-x0))/A
    return gx, gy, A, Z, P
for name, ((xa,xb),(ya,yb)) in FEAS.items():
    gx, gy, A, Z, P = grads(name)
    for lab, g, lo, hi in (('gx', gx, xa, xb), ('gy', gy, ya, yb)):
        best=None
        for k in range(0, 13):
            d=1<<k
            lo_k, hi_k = math.ceil(Fr(lo)*d), math.floor(Fr(hi)*d)
            if lo_k <= hi_k:
                best=(k, Fr(lo_k, d)); break
        e=Fr(g).limit_denominator(10**9)
        print('%-7s %s exact %16.6f  simplest dyadic in range 1/2^%d = %16.6f  (exact - that = %+0.6f, x2^%d = %+0.3f)'
              % (name, lab, float(g), best[0], float(best[1]), float(Fr(g)-best[1]), best[0], float((Fr(g)-best[1])*(1<<best[0]))))
