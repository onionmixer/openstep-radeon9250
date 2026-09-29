"""R6i-2: fit the weight arithmetic on the dyadic sweep -- quantum, its rounding, and how the
weighted sum of 0 and 255 becomes a byte (floor / round / ceil / 256-scale)."""
import pickle, sys, math, itertools
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
obs=pickle.load(open('build/r6i2/observed_ff6dab1c.pkl','rb'))
def Q(x,q,mode):
    if q is None: return x
    z=x*q
    k=math.floor(z) if mode=='floor' else math.floor(z+Fr(1,2)) if mode=='round' else round(z)
    return Fr(k,q)
FIN={'floor255': lambda w: min(255, math.floor(w*255)),
     'round255': lambda w: min(255, math.floor(w*255+Fr(1,2))),
     'ceil255':  lambda w: min(255, -math.floor(-w*255)),
     'floor256': lambda w: min(255, math.floor(w*256)),
     'round256': lambda w: min(255, math.floor(w*256+Fr(1,2)))}
def rows(case):
    w,h,_,_=pe.tex_of(case); st,tt=pe.st_of(case)
    s=pe.coord(case,st,'A',pe.MEASURED_OFF); t=pe.coord(case,tt,'A',pe.MEASURED_OFF)
    out=[]
    for p,v in obs[case].items():
        u=s[p]*w-Fr(1,2); vv=t[p]*h-Fr(1,2)
        i0,j0=math.floor(u),math.floor(vv)
        out.append((i0,u-i0,j0,vv-j0,v))
    return out
DATA={c:rows(c) for c in ('Q1','Q2','Q3','Q5')}
def predict(case,q,mode,where,fin):
    w,h,_,pat=pe.tex_of(case); out=[]
    for i0,fu,j0,fv,got in DATA[case]:
        if where=='axis':
            qu,qv=Q(fu,q,mode),Q(fv,q,mode)
            ws=[(0,0,(1-qu)*(1-qv)),(1,0,qu*(1-qv)),(0,1,(1-qu)*qv),(1,1,qu*qv)]
        else:
            ws=[(0,0,Q((1-fu)*(1-fv),q,mode)),(1,0,Q(fu*(1-fv),q,mode)),
                (0,1,Q((1-fu)*fv,q,mode)),(1,1,Q(fu*fv,q,mode))]
        word=0
        for lane in range(4):
            acc=sum(wt*((pe.texel(pat, (i0+du)&7, (j0+dv)&7)>>(8*lane))&0xff) for du,dv,wt in ws)
            word |= FIN[fin](acc/Fr(255)) << (8*lane)
        out.append((word,got))
    return out
best=[]
for q in (32,64,128,256,None):
    for mode in ('floor','round','even'):
        if q is None and mode!='floor': continue
        for where in ('axis','product'):
            for fin in FIN:
                for grp,cases in (('default',('Q1','Q2','Q3')), ('bitset',('Q5',))):
                    bad=mx=0
                    for c in cases:
                        for pr,got in predict(c,q,mode,where,fin):
                            for l in range(4):
                                d=abs(((pr>>(8*l))&0xff)-((got>>(8*l))&0xff)); mx=max(mx,d)
                            bad += pr!=got
                    best.append((grp,mx,bad,q,mode,where,fin))
for grp in ('default','bitset'):
    rows_=[b for b in best if b[0]==grp]
    rows_.sort(key=lambda t:(t[1],t[2]))
    print('== %s' % grp)
    for r in rows_[:5]: print('   max %3d  pixels off %3d   q=%s %s %s %s' % r[1:])
