#!/usr/bin/env python3
"""R6i design 2: the bilinear cases -- separation of the texel-space offset a, and how finely the
fine-sweep case (LD) samples the weight curve."""
import importlib.util, os, math, itertools
from fractions import Fraction as Fr
def load(n):
    sp=importlib.util.spec_from_file_location(n, os.path.join('tools/r6',n+'.py'))
    m=importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
to_=load('tex_oracle'); go=to_.go; GEOM=to_.GEOM

def interp(vals, off):
    return to_.interp(tuple(vals), off)

def tex1(u,v):   # corner-distinct 2x2 (texpat 1)
    return dict(A=255, R=255*(u&1), G=255*(v&1), B=255*((u&1)&(v&1)))
def tex2(u,v):   # alternating (texpat 2)
    return dict(A=255, R=255*(u&1), G=255*(v&1), B=0x55)

def bilin(case, pat, w, h, st, tt, a, o, clamp):
    """exact bilinear: value per channel at each covered pixel"""
    s=interp(st,o); t=interp(tt,o); out={}
    def idx(i,n):
        if clamp=='clamp': return max(0,min(n-1,i))
        return i%n
    for p in s:
        uf=s[p]*w+a-Fr(1,2) if False else s[p]*w+a
        vf=t[p]*h+a
        i0=math.floor(uf); j0=math.floor(vf); fu=uf-i0; fv=vf-j0
        acc={}
        for ch in ('A','R','G','B'):
            v00=pat(idx(i0,w),idx(j0,h))[ch]; v10=pat(idx(i0+1,w),idx(j0,h))[ch]
            v01=pat(idx(i0,w),idx(j0+1,h))[ch]; v11=pat(idx(i0+1,w),idx(j0+1,h))[ch]
            acc[ch]=(1-fu)*(1-fv)*v00+fu*(1-fv)*v10+(1-fu)*fv*v01+fu*fv*v11
        out[p]=(acc, min(fu,1-fu), min(fv,1-fv))
    return out

O=Fr(0)
cases={
 'LA': (tex1,2,2,(0,1,0),(0,0,1),'clamp'),
 'LC': (tex1,2,2,(0,1,0),(0,0,1),'wrap'),
 'LD': (tex2,8,8,(Fr(1,8),Fr(2,8),Fr(1,8)),(Fr(1,8),Fr(1,8),Fr(2,8)),'clamp'),
}
for name,(pat,w,h,st,tt,cl) in cases.items():
    m0=bilin(name,pat,w,h,st,tt,Fr(0),O,cl)
    mh=bilin(name,pat,w,h,st,tt,Fr(-1,2),O,cl)
    diffs=[]
    for p in m0:
        d=max(abs(m0[p][0][c]-mh[p][0][c]) for c in 'ARGB')
        diffs.append(d)
    big=sum(1 for d in diffs if d>=8)
    print(f"{name}: n={len(m0)} pixels where |a=0 - a=-1/2| >= 8 LSB: {big}, max diff {float(max(diffs)):.1f}")
    # how many distinct horizontal fractions does the case sample?
    fu=sorted(set(float(m0[p][1]) for p in m0))
    print(f"    distinct min(fu,1-fu) values (a=0): {len(fu)}  smallest gap {min(b-a for a,b in zip(fu,fu[1:])) if len(fu)>1 else 0:.4f}")
