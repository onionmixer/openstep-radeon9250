#!/usr/bin/env python3
"""R6i-3 design 2: a sweep that stays inside ONE texel with an EVEN tap index, so every k appears
with a = 0, b = 255 -- that is the branch where the rounding constant shows."""
import math, sys
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
exec(open("build/r6i2/design1.py").read().split("def sweep(")[0].replace("print(","#print(",1)) if False else None
# the R6i-2 geometry and interpolation, written out again here
TRI=[(4.0,4.0),(20.0,4.0),(4.0,20.0)]
def t16(v): return Fr(math.floor(v*16),16)
P=[(t16(x),t16(y)) for x,y in TRI]
def covered():
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0); sgn=1 if A>0 else -1
    out=[]
    for y in range(32):
        for x in range(32):
            sx,sy=Fr(2*x+1,2),Fr(2*y+1,2); ins=True
            for i in range(3):
                j=(i+1)%3
                dx,dy=(P[j][0]-P[i][0])*sgn,(P[j][1]-P[i][1])*sgn
                e=dx*(sy-P[i][1])-dy*(sx-P[i][0])
                tl=(dy==0 and dx>0) or dy<0
                if e<0 or (e==0 and not tl): ins=False; break
            if ins: out.append((x,y))
    return out
COV=covered()
def interp(vals,x,y):
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
    sx,sy=Fr(2*x+1,2),Fr(2*y+1,2)
    b1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A
    b2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
    return (1-b1-b2)*vals[0]+b1*vals[1]+b2*vals[2]

SH=Fr(1,512)          # 1/512 texel
def sweep_st(U0, span_x, span_y, V0, w=8, h=8):
    """U0, V0 are TEXEL coordinates (u = s*w - 1/2), so s*w = U0 + 1/2"""
    u0=U0+Fr(1,2); v0=V0+Fr(1,2)
    s=(Fr(u0,w), Fr(u0+span_x,w), Fr(u0+span_y,w))
    t=(Fr(v0,h),)*3
    return s,t

def profile(st, tt, w=8, h=8):
    out=[]
    for (x,y) in COV:
        u=interp(st,x,y)*w-Fr(1,2); v=interp(tt,x,y)*h-Fr(1,2)
        i0,j0=math.floor(u),math.floor(v)
        out.append((i0, math.floor((u-i0)*64), j0, math.floor((v-j0)*64)))
    return out

def separates(prof, rs=(0,8,16,24,32,40,48,56)):
    worst=None
    for i in range(len(rs)):
        for j in range(i+1,len(rs)):
            d=0
            for i0,ku,j0,kv in prof:
                a,b=(0,255) if i0%2==0 else (255,0)
                if ((a*(64-ku)+b*ku+rs[i])>>6) != ((a*(64-ku)+b*ku+rs[j])>>6): d+=1
            if worst is None or d<worst[0]: worst=(d,rs[i],rs[j])
    return worst

for name,U0,V0 in (('S3 (even tap, one texel)', Fr(2)+SH, Fr(1)),
                   ('S3-odd (odd tap)',        Fr(3)+SH, Fr(1)),
                   ('Q1 (for comparison)',     Fr(1,2)+SH, Fr(1))):
    st,tt=sweep_st(U0, Fr(15,16), Fr(1,16), V0)
    pr=profile(st,tt)
    ev=[p for p in pr if p[0]%2==0]
    print('%-26s taps i %s, even-tap pixels %3d, distinct ku %2d, worst r pair (separating pixels, r, r\') %s' %
          (name, sorted(set(p[0] for p in pr)), len(ev), len(set(p[1] for p in pr)), separates(pr)))

print('--- S3: how finely can it pin r? (all 64 values)')
st,tt=sweep_st(Fr(2)+SH, Fr(15,16), Fr(1,16), Fr(1))
pr=profile(st,tt)
bad=[]
for r in range(64):
    for r2 in range(r+1,64):
        d=sum(1 for i0,ku,j0,kv in pr
              if ((0*(64-ku)+255*ku+r)>>6) != ((0*(64-ku)+255*ku+r2)>>6))
        if d==0: bad.append((r,r2))
print('   r pairs S3 cannot separate: %d %s' % (len(bad), bad[:10]))
adj=[(r, sum(1 for i0,ku,j0,kv in pr if ((255*ku+r)>>6)!=((255*ku+r+1)>>6))) for r in range(63)]
print('   adjacent-r separation: min %d, zero at %s' % (min(a[1] for a in adj), [a[0] for a in adj if a[1]==0][:10]))
# and the same sweep run vertically (for the bit-set vertical constant)
print('--- S4 (vertical twin): swap the roles')
st2=(Fr(Fr(2)+SH+Fr(1,2),8),)*3
tt2=(Fr(Fr(1)+Fr(1,2),8), Fr(Fr(1)+Fr(1,2)+Fr(1,16),8), Fr(Fr(1)+Fr(1,2)+Fr(15,16),8))
pr2=profile(st2,tt2)
print('   taps j %s, distinct kv %d, fu %s' % (sorted(set(p[2] for p in pr2)), len(set(p[3] for p in pr2)),
                                               sorted(set(p[1] for p in pr2))[:4]))
