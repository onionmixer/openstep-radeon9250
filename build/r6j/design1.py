#!/usr/bin/env python3
"""R6j design 1: two draws -- a Gouraud destination, then a flat source with blending.
Which factor pairs pin the blend arithmetic, and how many distinct products do we get?"""
import math, sys
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
go = pe.go
GEOM = pe.GEOM_Q                       # the R6i-2 16x16 triangle
# a Gouraud destination: vertex colours (r, g, b, a) chosen to sweep every channel
DST_V = ((0x10, 0x20, 0xf0, 0x40), (0xe0, 0x90, 0x30, 0xc0), (0x70, 0xf0, 0x80, 0x20))
SRC = (0xc1, 0x2a, 0x9b, 0x37)         # the flat source colour (r, g, b, a)

def rule_b(vals):
    """R6e rule B on this triangle: bytes in covered() order"""
    P=[(go.pos(x,'t16'), go.pos(y,'t16')) for x,y in GEOM]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
    L=min(range(3), key=lambda i:(P[i][0],P[i][1]))
    out=[]
    for x,y in go.covered(GEOM):
        sx,sy=Fr(2*x+1,2),Fr(2*y+1,2)
        w1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A
        w2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
        w=[1-w1-w2,w1,w2]
        for i in range(3):
            if i!=L: w[i]=Fr(round(w[i]*256),256)
        w[L]=1-sum(w[i] for i in range(3) if i!=L)
        out.append(max(0,min(255,math.floor(sum(wi*Fr(ci) for wi,ci in zip(w,vals))))))
    return out
dst=[rule_b([DST_V[v][c] for v in range(3)]) for c in range(4)]   # per channel
print('destination: %d pixels; distinct per channel %s' % (len(dst[0]), [len(set(d)) for d in dst]))
FACTORS={'ZERO':lambda s,d,c: 0, 'ONE':lambda s,d,c: 255,
         'SRC_COLOR':lambda s,d,c: s[c], 'ONE_MINUS_SRC_COLOR':lambda s,d,c: 255-s[c],
         'DST_COLOR':lambda s,d,c: d[c], 'ONE_MINUS_DST_COLOR':lambda s,d,c: 255-d[c],
         'SRC_ALPHA':lambda s,d,c: s[3], 'ONE_MINUS_SRC_ALPHA':lambda s,d,c: 255-s[3],
         'DST_ALPHA':lambda s,d,c: d[3], 'ONE_MINUS_DST_ALPHA':lambda s,d,c: 255-d[3]}
PAIRS=[('ONE','ZERO'),('ZERO','ONE'),('ONE','ONE'),('SRC_ALPHA','ONE_MINUS_SRC_ALPHA'),
       ('DST_COLOR','ZERO'),('SRC_ALPHA','ONE'),('ONE_MINUS_DST_ALPHA','DST_ALPHA')]
# candidate arithmetics: result = clamp((src*Fs + dst*Fd + r) >> 8) with the factor scaled how?
def predict(fs,fd,r,scale,pix,c):
    s=SRC; d=[dst[k][pix] for k in range(4)]
    a=FACTORS[fs](s,d,c); b=FACTORS[fd](s,d,c)
    if scale=='plus1':                 # 255 -> 256 (a 9-bit one)
        a = a+1 if a==255 else a; b = b+1 if b==255 else b
    return min(255, (s[c]*a + d[c]*b + r) >> 8)
print('factor pair             distinct results   r=0 vs r=128 differ   r=0 vs r=255 differ')
for fs,fd in PAIRS:
    res={r:[predict(fs,fd,r,'none',p,c) for p in range(len(dst[0])) for c in range(4)] for r in (0,128,255)}
    d128=sum(1 for a,b in zip(res[0],res[128]) if a!=b)
    d255=sum(1 for a,b in zip(res[0],res[255]) if a!=b)
    print('%-22s %4d               %4d                 %4d' % ('%s,%s'%(fs,fd), len(set(res[0])), d128, d255))
