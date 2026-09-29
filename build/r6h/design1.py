# R6h design: which texel each pixel samples, and how many pixels sit at a texel boundary
import sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
go=do.go; T=do.GEOM['T1z']; pix=sorted(go.covered(T))
P=[(go.pos(x,'t16'), go.pos(y,'t16')) for x,y in T]
(x0,y0),(x1,y1),(x2,y2)=P
A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
def interp(vals):
    out={}
    for x,y in pix:
        sx,sy=Fr(2*x+1,2),Fr(2*y+1,2)
        w1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A; w2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
        out[(x,y)]=(1-w1-w2)*Fr(vals[0])+w1*Fr(vals[1])+w2*Fr(vals[2])
    return out
def texel(v, w, off, mode):
    t = math.floor(v*w + off)
    if mode=='clamp': return max(0, min(w-1, t))
    return t % w
CASES = {  # name: (w, h, s triple, t triple, mode)
 'XA': (8,8,(0,1,0),(0,0,1),'clamp'),
 'XB': (8,8,(Fr(1,16),Fr(17,16),Fr(1,16)),(Fr(1,16),Fr(1,16),Fr(17,16)),'clamp'),
 'XC': (8,8,(0,2,0),(0,0,2),'wrap'),
 'XD': (8,8,(Fr(-1,4),Fr(5,4),Fr(-1,4)),(Fr(-1,4),Fr(-1,4),Fr(5,4)),'clamp'),
 'XE': (8,8,(0,1,0),(0,0,1),'clamp'),
 'XF': (4,4,(0,1,0),(0,0,1),'clamp'),
 'XG': (8,8,(0,1,0),(Fr(1,2),)*3,'wrap'),
}
print('%-4s %-22s %s' % ('case','texels used','risky pixels per offset rule'))
for n,(w,h,st,tt,mode) in CASES.items():
    s=interp(st); t=interp(tt)
    for off,lab in ((0,'a=0'),(Fr(-1,2),'a=-1/2'),(Fr(1,2),'a=+1/2')):
        used=set((texel(s[p],w,off,mode), texel(t[p],h,off,mode)) for p in pix)
        # a pixel is risky when s*w + off is within 1/64 of an integer (the interpolation may move it)
        risky=sum(1 for p in pix if min(abs(s[p]*w+off - round(s[p]*w+off)), abs(t[p]*h+off - round(t[p]*h+off))) < Fr(1,64))
        if lab=='a=0': print('%-4s %-22s' % (n, '%d of %d' % (len(used), w*h)), end=' ')
        print('%s: risky %3d' % (lab, risky), end='  ')
    print()
