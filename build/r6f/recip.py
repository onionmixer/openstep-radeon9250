import sys
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
go=do.go
FEAS = {
 'I3_24': ((-236103.72340, -236103.71795), (414158.96875, 414158.98148)),
 'I4_24': ((449011.59184, 449011.59429), (143695.94690, 143695.95062)),
 'I6_24': ((-403555.67925, -403555.67273), (-726094.47500, -726094.46667)),
 'I7_24': ((49504.34884, 49504.37500), (-441623.50575, -441623.48649)),
 'I1_24': ((349525.30769, 349525.33333), (-0.00781, 0.00781)),
}
for name, ((xa,xb),(ya,yb)) in FEAS.items():
    pts, zs = do.triangles(name)[0]
    P=[(go.pos(x,'t16'),go.pos(y,'t16')) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0); S=1<<24
    Z=[Fr(v)*S for v in zs]
    nx=(Z[1]-Z[0])*(y2-y0)-(Z[2]-Z[0])*(y1-y0)
    ny=(Z[2]-Z[0])*(x1-x0)-(Z[1]-Z[0])*(x2-x0)
    inv = 1/A
    ix = (Fr(xa)/nx, Fr(xb)/nx) if nx > 0 else (Fr(xb)/nx, Fr(xa)/nx)
    iy = (Fr(ya)/ny, Fr(yb)/ny) if ny > 0 else (Fr(yb)/ny, Fr(ya)/ny)
    lo, hi = max(ix[0], iy[0]), min(ix[1], iy[1])
    print('%-7s 1/A = %.10e   inv from gx [%.6e, %.6e]  from gy [%.6e, %.6e]  overlap %s' %
          (name, float(inv), float(ix[0]), float(ix[1]), float(iy[0]), float(iy[1]), 'YES' if lo <= hi else 'no'))
    if lo <= hi:
        mid=(lo+hi)/2
        print('        one shared inv possible: [%.9e, %.9e], relative to 1/A %+.2e .. %+.2e' %
              (float(lo), float(hi), float(lo/inv-1), float(hi/inv-1)))
