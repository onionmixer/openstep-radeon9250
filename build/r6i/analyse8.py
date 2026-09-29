"""R6i: PE -- how are the perspective weights rounded before the colour is mixed?"""
import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe, gouraud_oracle as go
obs=pickle.load(open('build/r6i/observed_ff78c18a.pkl','rb'))
pts=pe.GEOM_V8
P=[(go.pos(x,'t16'), go.pos(y,'t16')) for x,y in pts]
L=min(range(3), key=lambda i:(P[i][0],P[i][1]))
W=pe.w_of('PE')
lam=pe.bary('PE', Fr(1,2))
def variants(p):
    l=lam[p]
    q=[l[i]*W[i] for i in range(3)]; sq=sum(q); pw=[v/sq for v in q]
    out={}
    out['exact']=pw
    for mode in ('round','even'):
        w=list(pw)
        for i in range(3):
            if i!=L:
                z=w[i]*256
                w[i]=Fr(math.floor(z+Fr(1,2)) if mode=='round' else round(z),256)
        w[L]=1-sum(w[i] for i in range(3) if i!=L)
        out['ruleB-'+mode]=w
    for mode in ('round','even'):               # all three weights rounded, then renormalised by the leftmost
        w=[Fr(math.floor(v*256+Fr(1,2)) if mode=='round' else round(v*256),256) for v in pw]
        out['all3-'+mode]=w
    # the affine weights rounded first, then perspective-corrected
    w=list(l)
    for i in range(3):
        if i!=L:
            w[i]=Fr(round(w[i]*256),256)
    w[L]=1-sum(w[i] for i in range(3) if i!=L)
    q2=[w[i]*W[i] for i in range(3)]; s2=sum(q2)
    out['affine-then-persp']=[v/s2 for v in q2]
    return out
names=None
bad={}
for p,v in obs['PE'].items():
    vs=variants(p)
    names=list(vs)
    k=list(go.covered(pts)).index(p)
    for nm,w in vs.items():
        for lane in range(4):
            vals=go.lane_triple('V8','BGRA'[lane])
            want=max(0,min(255,math.floor(sum(wi*Fr(ci) for wi,ci in zip(w,vals)))))
            got=(v>>(8*lane))&0xff
            if want!=got: bad[nm]=bad.get(nm,0)+1
print('bytes total', 4*len(obs['PE']))
for nm in names: print('  %-20s %d bytes differ' % (nm, bad.get(nm,0)))
