#!/usr/bin/env python3
"""R6i design 1: which W triples separate affine / perspective(q=W0) / perspective(q=1/W0)?"""
import importlib.util, os, math, itertools
from fractions import Fraction as Fr
HERE='tools/r6'
def load(n):
    sp=importlib.util.spec_from_file_location(n, os.path.join(HERE,n+'.py'))
    m=importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m
to_=load('tex_oracle')
go=to_.go
GEOM=to_.GEOM
DELTA=Fr(1,1024)

def bary(off):
    P=[(go.pos(x,'t16'), go.pos(y,'t16')) for x,y in GEOM]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
    out={}
    for x,y in go.covered(GEOM):
        sx,sy=Fr(x)+off, Fr(y)+off
        w1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A
        w2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
        out[(x,y)]=(1-w1-w2,w1,w2)
    return out

B={o:bary(o) for o in (Fr(0),Fr(1,2))}

def coord(model, vals, W, off):
    """interpolated s at each pixel under a model"""
    r={}
    for p,l in B[off].items():
        if model=='A':
            r[p]=sum(l[i]*Fr(vals[i]) for i in range(3))
        else:
            q=[Fr(W[i]) if model=='Pq' else 1/Fr(W[i]) for i in range(3)]
            num=sum(l[i]*Fr(vals[i])*q[i] for i in range(3))
            den=sum(l[i]*q[i] for i in range(3))
            r[p]=num/den
    return r

def texels(model,W,off,st,tt,w=8,h=8):
    s=coord(model,st,W,off); t=coord(model,tt,W,off)
    out={}
    for p in s:
        fs,ft=s[p]*w, t[p]*h
        safe = min(fs-math.floor(fs), math.floor(fs)+1-fs)>DELTA and min(ft-math.floor(ft), math.floor(ft)+1-ft)>DELTA
        u=max(0,min(w-1,math.floor(fs))); v=max(0,min(h-1,math.floor(ft)))
        out[p]=((u,v),safe)
    return out

ST=((0,1,0),(0,0,1))
cands=[(1,Fr(1,2),Fr(1,4)),(1,Fr(1,4),Fr(1,4)),(1,Fr(1,4),1),(1,Fr(1,2),1),(1,Fr(1,8),Fr(1,2)),(Fr(1,4),1,Fr(1,2))]
models=[(m,o) for m in ('A','Pq','Pw') for o in (Fr(0),Fr(1,2))]
print("cand: allsafe  pairwise-min-separation over model pairs (safe in both)")
for W in cands:
    maps={k:texels(k[0],W,k[1],*ST) for k in models}
    ps=list(maps[models[0]].keys())
    allsafe=[p for p in ps if all(maps[k][p][1] for k in models)]
    mind=None; worst=None
    for a,b in itertools.combinations(models,2):
        both=[p for p in ps if maps[a][p][1] and maps[b][p][1]]
        d=sum(1 for p in both if maps[a][p][0]!=maps[b][p][0])
        if mind is None or d<mind: mind, worst=d,(a,b)
        
    print(f"W={tuple(str(x) for x in W)}: n={len(ps)} allsafe={len(allsafe)} min-sep={mind} at {worst[0]} vs {worst[1]}")
