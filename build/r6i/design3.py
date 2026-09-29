#!/usr/bin/env python3
"""R6i design 3: does a Gouraud triangle with W != 1 separate affine from perspective colour?"""
import importlib.util, os, math
from fractions import Fraction as Fr
def load(n):
    sp=importlib.util.spec_from_file_location(n, os.path.join('tools/r6',n+'.py'))
    m=importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
to_=load('tex_oracle'); go=to_.go
V8=[(0x4187ced9,0x40e2b021,0x731f8aee),(0x40622d0e,0x416ac49c,0x3586fd7a),(0x4012c083,0x41d43333,0x44c49710)]
import struct
def f(b): return struct.unpack('<f', struct.pack('<I', b))[0]
GE=[(f(v[0]), f(v[1])) for v in V8]
COL=[v[2] for v in V8]
W=(Fr(1), Fr(1,8), Fr(1,2))
P=[(go.pos(x,'t16'), go.pos(y,'t16')) for x,y in GE]
(x0,y0),(x1,y1),(x2,y2)=P
A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
diff=[]; n=0
for x,y in go.covered(GE):
    sx,sy=Fr(x)+Fr(1,2), Fr(y)+Fr(1,2)
    b1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A
    b2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
    l=(1-b1-b2, b1, b2); n+=1
    q=[l[i]*W[i] for i in range(3)]; sq=sum(q); pw=[v/sq for v in q]
    d=0
    for lane in range(4):
        vals=[(COL[i]>>(8*lane))&0xff for i in range(3)]
        a=sum(l[i]*vals[i] for i in range(3)); p=sum(pw[i]*vals[i] for i in range(3))
        d=max(d, abs(a-p))
    diff.append(d)
print("PE (V8 geometry, W=(1,1/8,1/2)): covered", n)
for thr in (0.5,1,2,4,8,16):
    print(f"  pixels with max-lane |affine-perspective| >= {thr}: {sum(1 for d in diff if d>=thr)}")
print("  max", float(max(diff)))
