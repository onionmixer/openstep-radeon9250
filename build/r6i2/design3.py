#!/usr/bin/env python3
"""R6i-2 design 3: the v-sweep twin (Q3) and the perspective case (Q4), on the 16x16 triangle."""
import math, sys
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
exec(open("build/r6i2/design1.py").read().split("def sweep(")[0].replace("print(","#print(",1))
COV=covered()
W_B=(Fr(1),Fr(1,8),Fr(1,2))

def maps(st, tt, W=None, w=8, h=8, off=Fr(1,2)):
    out={}
    for (x,y) in COV:
        l=bary(x,y,off)
        if W is not None:
            q=[l[i]*W[i] for i in range(3)]; sq=sum(q); l=[v/sq for v in q]
        s=sum(l[i]*st[i] for i in range(3))*w - Fr(1,2)
        t=sum(l[i]*tt[i] for i in range(3))*h - Fr(1,2)
        out[(x,y)]=(math.floor(s), s-math.floor(s), math.floor(t), t-math.floor(t))
    return out

# Q3: u fixed with fu = 0 (u = 2 exactly -> s = 5/16), v sweeps 1 texel in y and 1/16 in x
Q3_s=(Fr(5,16),)*3
Q3_t=(Fr(3,16), Fr(3,16)+Fr(1,128), Fr(3,16)+Fr(1,8))
m=maps(Q3_s,Q3_t)
print('Q3: fu %s (taps i %s), fv in [%s, %s] taps j %s, risky %d' % (
    sorted(set(f[1] for f in m.values())), sorted(set(f[0] for f in m.values())),
    min(f[3] for f in m.values()), max(f[3] for f in m.values()),
    sorted(set(f[2] for f in m.values())), sum(1 for f in m.values() if min(f[3],1-f[3])<=Fr(1,1024))))
# Q4: Q1's ST with W = (1, 1/8, 1/2) and perspective on
Q1_s=(Fr(1,8), Fr(1,4), Fr(17,128)); Q1_t=(Fr(3,16),)*3
m4=maps(Q1_s,Q1_t,W=W_B)
fu=[f[1] for f in m4.values()]
print('Q4 (perspective): fu in [%s, %s] taps i %s j %s risky %d, distinct fu %d' % (
    min(fu), max(fu), sorted(set(f[0] for f in m4.values())), sorted(set(f[2] for f in m4.values())),
    sum(1 for f in fu if min(f,1-f)<=Fr(1,1024)), len(set(fu))))
# does Q4 separate the affine reading from the perspective one?
m4a=maps(Q1_s,Q1_t)
d=sum(1 for p in COV if abs(float(m4[p][1]+m4[p][0]) - float(m4a[p][1]+m4a[p][0]))>1/256)
print('   Q4: %d of %d pixels differ from the affine reading by more than 1/256 texel' % (d, len(COV)))
