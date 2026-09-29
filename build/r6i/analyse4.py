"""R6i: the R byte depends on BOTH fractions -> the four bilinear weights are quantised one by one.
Search: quantum, its rounding, and how the weighted sum becomes a byte."""
import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
obs=pickle.load(open('build/r6i/observed_ff78c18a.pkl','rb'))

def Q(x, q, mode):
    if q is None: return x
    z = x*q
    k = math.floor(z) if mode=='floor' else math.floor(z+Fr(1,2)) if mode=='round' else round(z)
    return Fr(k, q)

FINAL = {
 'floor255': lambda W: min(255, math.floor(W*255)),
 'round255': lambda W: min(255, math.floor(W*255+Fr(1,2))),
 'floor256': lambda W: min(255, math.floor(W*256)),
 'mul257>>8': lambda W: min(255, math.floor(W*257*255/256)),
}
cases=['LF','LD','LA','LC']
data={}
for case in cases:
    w,h,_,pat=pe.tex_of(case); st,tt=pe.st_of(case)
    OFF=Fr(1,2)
    s=pe.coord(case,st,'A',OFF); t=pe.coord(case,tt,'A',OFF)
    rows=[]
    for p,v in obs[case].items():
        u=s[p]*w-Fr(1,2); vv=t[p]*h-Fr(1,2)
        i,j=math.floor(u),math.floor(vv); fu,fv=u-i,vv-j
        rows.append((i,j,fu,fv,v))
    data[case]=(w,h,pat,rows)

def texel(pat,u,v):
    return pe.texel(pat,u,v)

def predict(case, q, mode, fin):
    w,h,pat,rows=data[case]
    cl = pe.clamp_of(case)
    out=[]
    for i,j,fu,fv,got in rows:
        ws=[(0,0,(1-fu)*(1-fv)),(1,0,fu*(1-fv)),(0,1,(1-fu)*fv),(1,1,fu*fv)]
        word=0
        for lane in range(4):
            acc=0
            for du,dv,wt in ws:
                uu = max(0,min(w-1,i+du)) if cl=='clamp' else (i+du)%w
                vv2= max(0,min(h-1,j+dv)) if cl=='clamp' else (j+dv)%h
                acc += Q(wt,q,mode) * ((texel(pat,uu,vv2)>>(8*lane))&0xff)
            word |= FINAL[fin](acc/255 if False else acc/Fr(255)) << (8*lane)
        out.append((word,got))
    return out

best=[]
for q in (None,16,32,64,128,256):
    for mode in ('floor','round','even'):
        if q is None and mode!='floor': continue
        for fin in FINAL:
            bad=0; mx=0; tot=0
            for case in cases:
                for pr,got in predict(case,q,mode,fin):
                    for l in range(4):
                        d=abs(((pr>>(8*l))&0xff)-((got>>(8*l))&0xff))
                        mx=max(mx,d); tot+=d
                    bad += pr!=got
            best.append((mx,bad,round(tot/4416,2),q,mode,fin))
best.sort(key=lambda t:(t[0], t[1], t[3] or 0, t[4], t[5]))
print('max  bad  meanLSB  quantum mode final')
for b in best[:10]: print(b)
