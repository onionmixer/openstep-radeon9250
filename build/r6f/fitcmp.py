import pickle, sys
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
go=do.go
FEAS = {  # from build/r6f/fitplane.py
 'I1_24': ((349525.30769, 349525.33333), (-0.00781, 0.00781)),
 'I3_24': ((-236103.72340, -236103.71795), (414158.96875, 414158.98148)),
 'I4_24': ((449011.59184, 449011.59429), (143695.94690, 143695.95062)),
 'I6_24': ((-403555.67925, -403555.67273), (-726094.47500, -726094.46667)),
 'I7_24': ((49504.34884, 49504.37500), (-441623.50575, -441623.48649)),
}
def grads(name, p):
    pts, zs = do.triangles(name)[0]
    P=[(go.pos(x,p),go.pos(y,p)) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0); S=1<<do.fmt_bits(name)
    Z=[Fr(v)*S for v in zs]
    gx=((Z[1]-Z[0])*(y2-y0)-(Z[2]-Z[0])*(y1-y0))/A
    gy=((Z[2]-Z[0])*(x1-x0)-(Z[1]-Z[0])*(x2-x0))/A
    return float(gx), float(gy)
for name, ((xa, xb), (ya, yb)) in FEAS.items():
    for p in ('t16', 'exact'):
        gx, gy = grads(name, p)
        print('%-7s %-5s gx %14.5f %s   gy %14.5f %s' % (name, p, gx, 'IN ' if xa <= gx <= xb else 'out',
                                                          gy, 'IN ' if ya <= gy <= yb else 'out'))
