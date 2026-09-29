#!/usr/bin/env python3
"""R6i-2 design 2: u = u0 + x/16 + y/256 on a 16x16 triangle -- the setup's divisions are by 16
(exact in binary) and the 120 pixels land on 120 different points of the 1/256 grid."""
import math, sys
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
exec(open("build/r6i2/design1.py").read().split("def sweep(")[0].replace("print(","#print(",1))
COV=covered()

def st_of(u0, dudx, dudy, vfix, w=8, h=8):
    s=(Fr(u0,w), Fr(u0+16*dudx,w), Fr(u0+16*dudy,w))
    t=(Fr(vfix,h),)*3
    return s,t

def fracs(st,tt,w=8,h=8):
    out={}
    for (x,y) in COV:
        l=bary(x,y)
        s=sum(l[i]*st[i] for i in range(3))*w - Fr(1,2)
        t=sum(l[i]*tt[i] for i in range(3))*h - Fr(1,2)
        i0,j0=math.floor(s),math.floor(t)
        out[(x,y)]=(i0,s-i0,j0,t-j0)
    return out

def byte_of(fu,fv,i0,q,mode):
    acc=0
    for du,wu in ((0,1-fu),(1,fu)):
        for dv,wv in ((0,1-fv),(1,fv)):
            acc += pe.quantise(wu*wv,q,mode)*(255*((i0+du)&1))
    return min(255, math.floor(acc+Fr(1,2)))

CAND=[(q,m) for q in (None,16,32,64,128,256) for m in ('floor','round','even') if not (q is None and m!='floor')]
for name,(u0,dudx,dudy,vfix) in (
        ('Q1',(Fr(1), Fr(1,16), Fr(1,256), Fr(3,2))),       # fv = 0 exactly: R = 255*Q(fu)
        ('Q2',(Fr(1), Fr(1,16), Fr(1,256), Fr(2))),         # fv = 1/2
        ('Q3',(Fr(3,2), Fr(1,256), Fr(1,16), Fr(3,2)))):    # the axes swapped (v sweeps)
    st,tt=st_of(u0,dudx,dudy,vfix)
    fr=fracs(st,tt)
    print('%s: s=%s t=%s' % (name,[str(x) for x in st],[str(x) for x in tt]))
    print('   distinct fu: %d   distinct fv: %d' % (len(set(f[1] for f in fr.values())), len(set(f[3] for f in fr.values()))))
    maps={c:{p:byte_of(f[1],f[3],f[0],*c) for p,f in fr.items()} for c in CAND}
    worst=None
    for a in range(len(CAND)):
        for b in range(a+1,len(CAND)):
            d=sum(1 for p in COV if maps[CAND[a]][p]!=maps[CAND[b]][p])
            if worst is None or d<worst[0]: worst=(d,CAND[a],CAND[b])
    print('   closest candidate pair: %s pixels apart %s vs %s' % worst)
    for c in ((None,'floor'),(64,'floor'),(64,'round'),(64,'even'),(32,'floor'),(128,'round')):
        lv=sorted(set(maps[c].values()))
        print('     %-14s %2d levels %s' % (str(c), len(lv), lv[:8]))

print('--- tap ranges and risky pixels')
for name,(u0,dudx,dudy,vfix) in (('Q1',(Fr(1), Fr(1,16), Fr(1,256), Fr(3,2))),
                                 ('Q2',(Fr(1), Fr(1,16), Fr(1,256), Fr(2))),
                                 ('Q3',(Fr(3,2), Fr(1,256), Fr(1,16), Fr(3,2)))):
    st,tt=st_of(u0,dudx,dudy,vfix); fr=fracs(st,tt)
    fus=[f[1] for f in fr.values()]; i0s=set(f[0] for f in fr.values()); j0s=set(f[2] for f in fr.values())
    risky=sum(1 for f in fus if min(f,1-f)<=Fr(1,1024))
    print('%s: fu in [%s, %s]  taps i %s j %s  risky %d  fv %s' %
          (name, min(fus), max(fus), sorted(i0s), sorted(j0s), risky, sorted(set(f[3] for f in fr.values()))))
