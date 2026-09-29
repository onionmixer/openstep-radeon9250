import sys, numpy as np
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
go=do.go; F=np.float32
FEAS = {
 'I1_24': ((349525.30769, 349525.33333), (-0.00781, 0.00781)),
 'I3_24': ((-236103.72340, -236103.71795), (414158.96875, 414158.98148)),
 'I4_24': ((449011.59184, 449011.59429), (143695.94690, 143695.95062)),
 'I6_24': ((-403555.67925, -403555.67273), (-726094.47500, -726094.46667)),
 'I7_24': ((49504.34884, 49504.37500), (-441623.50575, -441623.48649)),
}
def variants(name):
    pts, zs = do.triangles(name)[0]
    P=[(float(go.pos(x,'t16')), float(go.pos(y,'t16'))) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=[(F(a),F(b)) for a,b in P]
    out={}
    for scale, lab in ((F(1<<24),'z*2^24'), (F(1),'z in [0,1]')):
        z=[F(v)*scale for v in zs]
        ax,ay,bx,by=x1-x0,y1-y0,x2-x0,y2-y0
        d1,d2=z[1]-z[0],z[2]-z[0]
        A=F(ax*by-bx*ay)
        nx=F(d1*by-d2*ay); ny=F(d2*ax-d1*bx)
        gx=F(nx/A); gy=F(ny/A)
        inv=F(F(1.0)/A); gx2=F(nx*inv); gy2=F(ny*inv)
        m = F(1<<24) if lab=='z in [0,1]' else F(1)
        out['%s div' % lab]=(float(F(gx*m)), float(F(gy*m)))
        out['%s recip' % lab]=(float(F(gx2*m)), float(F(gy2*m)))
    return out
for name, ((xa,xb),(ya,yb)) in FEAS.items():
    for lab,(gx,gy) in variants(name).items():
        print('%-7s %-16s gx %15.5f %s  gy %15.5f %s' % (name, lab, gx, 'IN ' if xa<=gx<=xb else '   ', gy, 'IN ' if ya<=gy<=yb else '   '))
