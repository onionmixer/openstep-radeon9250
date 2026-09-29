#!/usr/bin/env python3
"""R6i design 5 (after codex): PZ -- is depth perspective-corrected?  PL -- perspective with a
linear filter: separation and whether every pixel still magnifies."""
import importlib.util, os, math, struct
from fractions import Fraction as Fr
def load(n):
    sp=importlib.util.spec_from_file_location(n, os.path.join('tools/r6',n+'.py'))
    m=importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
to_=load('tex_oracle'); go=to_.go; GEOM=to_.GEOM
W=(Fr(1),Fr(1,8),Fr(1,2))
P=[(go.pos(x,'t16'), go.pos(y,'t16')) for x,y in GEOM]
(x0,y0),(x1,y1),(x2,y2)=P
A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
def lam(x,y,off=Fr(1,2)):
    sx,sy=Fr(x)+off, Fr(y)+off
    w1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A
    w2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
    return (1-w1-w2,w1,w2)
def persp(l, vals):
    q=[l[i]*W[i] for i in range(3)]; s=sum(q)
    return sum(q[i]*Fr(vals[i]) for i in range(3))/s
def aff(l, vals):
    return sum(l[i]*Fr(vals[i]) for i in range(3))

# ---- PZ: a varying-z triangle (R6f I1-style z per vertex), 24-bit depth
Z=(Fr(1,4), Fr(3,4), Fr(1,2))
d=[]
for x,y in go.covered(GEOM):
    l=lam(x,y)
    za=math.floor(aff(l,Z)*(1<<24)); zp=math.floor(persp(l,Z)*(1<<24))
    d.append(abs(za-zp))
print(f"PZ: covered={len(d)} pixels differing >=1 LSB(24bit): {sum(1 for v in d if v>=1)}, >=256: {sum(1 for v in d if v>=256)}, max={max(d)} ({max(d)/(1<<24):.4f} of full)")

# ---- PL: perspective with the LD texture/ST, linear filter
ST=(Fr(1,8),Fr(2,8),Fr(1,8)); TT=(Fr(1,8),Fr(1,8),Fr(2,8))
rows=[]; grad=[]
pix=sorted(go.covered(GEOM))
val={}
for x,y in pix:
    l=lam(x,y,Fr(0))
    ua=aff(l,ST)*8; up=persp(l,ST)*8
    va=aff(l,TT)*8; vp=persp(l,TT)*8
    # R channel of pat2 under exact bilinear with a=0: 255*(frac if floor even else 1-frac)
    def rch(u):
        i=math.floor(u); f=u-i
        return 255*(f if i%2==0 else 1-f)
    val[(x,y)]=(rch(ua), rch(up), ua, up)
diff=[abs(val[p][0]-val[p][1]) for p in pix]
print(f"PL: covered={len(pix)} pixels with |affine-perspective| R >= 8 LSB: {sum(1 for v in diff if v>=8)}, max {float(max(diff)):.1f}")
# gradient check: magnification everywhere?
mx=0
for x,y in pix:
    if (x+1,y) in val: mx=max(mx, abs(val[(x+1,y)][3]-val[(x,y)][3]))
    if (x,y+1) in val: mx=max(mx, abs(val[(x,y+1)][3]-val[(x,y)][3]))
print(f"PL: largest perspective du per pixel step = {float(mx):.4f} texel  (magnifies if < 1)")
