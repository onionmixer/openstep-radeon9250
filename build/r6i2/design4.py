#!/usr/bin/env python3
"""R6i-2 design 4: does Q2 (fv = 1/2) separate "each of the four weights is quantised" from
"each axis is quantised, then multiplied"?  And how many candidate pairs stay indistinguishable?"""
import math, sys, itertools
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
exec(open("build/r6i2/design1.py").read().split("def sweep(")[0].replace("print(","#print(",1))
COV=covered()
# u0 is shifted by 1/512 of a texel so that the pixel-centre fractions are EVEN multiples of
# 1/512: only then can a sample land exactly on the half of a 1/64 or 1/128 cell, which is what
# tells "round half up" from "round half to even" apart (design4 checks it)
SH=Fr(1,512*8)
CASES={
 'Q1': ((Fr(1,8)+SH, Fr(1,4)+SH, Fr(17,128)+SH), (Fr(3,16),)*3),
 'Q2': ((Fr(1,8)+SH, Fr(1,4)+SH, Fr(17,128)+SH), (Fr(1,4),)*3),
 'Q3': ((Fr(5,16),)*3, (Fr(3,16)+SH, Fr(3,16)+Fr(1,128)+SH, Fr(3,16)+Fr(1,8)+SH)),
}
def pixels(case, q, mode, where, fin, w=8, h=8):
    st,tt=CASES[case]; out={}
    for (x,y) in COV:
        l=bary(x,y)
        s=sum(l[i]*st[i] for i in range(3))*w - Fr(1,2)
        t=sum(l[i]*tt[i] for i in range(3))*h - Fr(1,2)
        i0,j0=math.floor(s),math.floor(t); fu,fv=s-i0,t-j0
        if where=='axis':
            fu2,fv2=pe.quantise(fu,q,mode),pe.quantise(fv,q,mode)
            ws=[(0,0,(1-fu2)*(1-fv2)),(1,0,fu2*(1-fv2)),(0,1,(1-fu2)*fv2),(1,1,fu2*fv2)]
        else:
            ws=[(0,0,pe.quantise((1-fu)*(1-fv),q,mode)),(1,0,pe.quantise(fu*(1-fv),q,mode)),
                (0,1,pe.quantise((1-fu)*fv,q,mode)),(1,1,pe.quantise(fu*fv,q,mode))]
        accR=sum(wt*(255*((i0+du)&1)) for du,dv,wt in ws)
        accG=sum(wt*(255*((j0+dv)&1)) for du,dv,wt in ws)
        f=(lambda v: min(255, math.floor(v+Fr(1,2)))) if fin=='round' else (lambda v: min(255, math.floor(v)))
        out[(x,y)]=(f(accR), f(accG))
    return out
CAND=[(q,m,wh,f) for q in (None,16,32,64,128,256) for m in ('floor','round','even')
      for wh in ('product','axis') for f in ('floor','round') if not (q is None and (m!='floor' or wh!='product'))]
print('candidates', len(CAND))
maps={}
for c in CAND:
    maps[c]={case:pixels(case,*c) for case in CASES}
same=0; worst=None
for a,b in itertools.combinations(CAND,2):
    d=sum(1 for case in CASES for p in COV if maps[a][case][p]!=maps[b][case][p])
    if d==0: same+=1
    if worst is None or (d>0 and d<worst[0]): worst=(d,a,b)
print('indistinguishable pairs: %d of %d' % (same, len(CAND)*(len(CAND)-1)//2))
print('closest distinguishable pair: %s' % (worst,))
for c in ((64,'round','product','round'), (64,'round','axis','round')):
    d=sum(1 for case in CASES for p in COV if maps[c][case][p]!=maps[(64,'round','product','round')][case][p])
    print('   %s vs product: %d pixels differ' % (str(c), d))

# which candidates collapse into one class?
cls={}
for c in CAND:
    key=tuple(tuple(maps[c][case][p] for p in COV) for case in CASES)
    cls.setdefault(key,[]).append(c)
print('equivalence classes: %d (of %d candidates)' % (len(cls), len(CAND)))
for k,v in cls.items():
    if len(v)>1: print('   same picture: %s' % (v,))

print('--- margins that matter (product, final round)')
for q in (16,32,64,128,256):
    a=(q,'round','product','round'); b=(q,'even','product','round'); c=(q,'floor','product','round')
    d_re=sum(1 for case in CASES for p in COV if maps[a][case][p]!=maps[b][case][p])
    d_rf=sum(1 for case in CASES for p in COV if maps[a][case][p]!=maps[c][case][p])
    d_ax=sum(1 for case in CASES for p in COV if maps[a][case][p]!=maps[(q,'round','axis','round')][case][p])
    d_ex=sum(1 for case in CASES for p in COV if maps[a][case][p]!=maps[(None,'floor','product','round')][case][p])
    print('  q=1/%-3d  round vs even %3d   round vs floor %3d   product vs axis %3d   vs exact %3d' %
          (q, d_re, d_rf, d_ax, d_ex))
