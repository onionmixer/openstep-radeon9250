#!/usr/bin/env python3
"""R6i-2 design 1: a triangle whose spans are powers of two, so the setup's gradient division is
exact, and an ST sweep fine enough to land BETWEEN the weight-quantum steps.

Prints, for each candidate (quantum, rounding), the bytes the sweep would give, and whether the
candidates are told apart."""
import math, sys
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe

TRI = [(4.0, 4.0), (20.0, 4.0), (4.0, 20.0)]     # 16-pixel spans: Ds/16 is exact in binary
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
                dx=(P[j][0]-P[i][0])*sgn; dy=(P[j][1]-P[i][1])*sgn
                e=dx*(sy-P[i][1])-dy*(sx-P[i][0])
                tl=(dy==0 and dx>0) or dy<0
                if e<0 or (e==0 and not tl): ins=False; break
            if ins: out.append((x,y))
    return out
COV=covered()
print('triangle (4,4)(20,4)(4,20): %d covered pixels' % len(COV))

def bary(x,y,off=Fr(1,2)):
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
    sx,sy=Fr(x)+off,Fr(y)+off
    b1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A
    b2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
    return (1-b1-b2,b1,b2)

def sweep(u0, dudx, vfix, w=8, h=8):
    """ST triple for: u = u0 + dudx*(x-4), v = vfix (both in texel units) -> s,t in [0,1]"""
    s0 = Fr(u0, w); s1 = Fr(u0 + 16*dudx, w); s2 = Fr(u0, w)
    t0 = t1 = t2 = Fr(vfix, h)
    return (s0,s1,s2),(t0,t1,t2)

def predict(st, tt, q, mode, fin='round255', w=8, h=8):
    out={}
    for (x,y) in COV:
        l=bary(x,y)
        s=sum(l[i]*st[i] for i in range(3))*w - Fr(1,2)
        t=sum(l[i]*tt[i] for i in range(3))*h - Fr(1,2)
        i0,j0=math.floor(s),math.floor(t); fu,fv=s-i0,t-j0
        acc=0
        for du,wu in ((0,1-fu),(1,fu)):
            for dv,wv in ((0,1-fv),(1,fv)):
                R = 255*((i0+du)&1)                    # pattern 2: R = 255 when u is odd
                acc += pe.quantise(wu*wv,q,mode)*R
        out[(x,y)] = min(255, math.floor(acc+Fr(1,2)) if fin=='round255' else math.floor(acc))
    return out

CAND=[(q,m) for q in (None,16,32,64,128,256,512) for m in ('floor','round','even') if not (q is None and m!='floor')]
for name,(u0,dudx,vfix) in (('LQ',(Fr(1)+Fr(1,1024), Fr(1,512), Fr(3,2))),
                            ('LV',(Fr(1)+Fr(1,1024), Fr(1,512), Fr(2))),
                            ('LW',(Fr(1)+Fr(1,1024), Fr(1,512), Fr(7,4)))):
    st,tt=sweep(u0,dudx,vfix)
    maps={c:predict(st,tt,*c) for c in CAND}
    # how many candidate pairs are told apart, and by how many pixels at least?
    worst=None
    for a in range(len(CAND)):
        for b in range(a+1,len(CAND)):
            d=sum(1 for p in COV if maps[CAND[a]][p]!=maps[CAND[b]][p])
            if worst is None or d<worst[0]: worst=(d,CAND[a],CAND[b])
    lv=sorted(set(maps[(64,'round')][p] for p in COV))
    print('%s: u0=%s dudx=%s v=%s  levels(64,round)=%s  closest pair %s' % (name,u0,dudx,vfix,lv[:8],worst))
