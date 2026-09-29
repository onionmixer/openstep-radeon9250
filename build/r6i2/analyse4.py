"""R6i-2: Q1 (fv = 0) isolates the horizontal mix, Q3 (fu = 0) the vertical one.  Fit each stage:
byte = (a*(q-k) + b*k + r) >> log2(q) with k = floor(q*f) (or rounded), over q and r."""
import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import persp_oracle as pe
obs=pickle.load(open('build/r6i2/observed_ff6dab1c.pkl','rb'))
def rows(case):
    w,h,_,_=pe.tex_of(case); st,tt=pe.st_of(case)
    s=pe.coord(case,st,'A',pe.MEASURED_OFF); t=pe.coord(case,tt,'A',pe.MEASURED_OFF)
    out=[]
    for p,v in obs[case].items():
        u=s[p]*w-Fr(1,2); vv=t[p]*h-Fr(1,2)
        i0,j0=math.floor(u),math.floor(vv)
        out.append((i0,u-i0,j0,vv-j0,v))
    return out
DATA={c:rows(c) for c in ('Q1','Q3','Q5')}
def stage_fit(case, axis):
    best=[]
    w,h,_,pat=pe.tex_of(case)
    for q in (32,64,128,256):
        sh=q.bit_length()-1
        for mode in ('floor','round'):
            for r in range(q):
                bad=0; mx=0
                for i0,fu,j0,fv,got in DATA[case]:
                    f = fu if axis=='u' else fv
                    k = math.floor(f*q) if mode=='floor' else math.floor(f*q+Fr(1,2))
                    word=0
                    for lane in range(4):
                        t=lambda du,dv: (pe.texel(pat,(i0+du)&7,(j0+dv)&7)>>(8*lane))&0xff
                        a,b = (t(0,0), t(1,0)) if axis=='u' else (t(0,0), t(0,1))
                        v=(a*(q-k) + b*k + r) >> sh
                        word |= min(255,max(0,v)) << (8*lane)
                    bad += word!=got
                    for lane in range(4):
                        mx=max(mx, abs(((word>>(8*lane))&0xff)-((got>>(8*lane))&0xff)))
                best.append((mx,bad,q,mode,r))
    best.sort()
    return best[:4]
print('Q1 horizontal (bit clear):', stage_fit('Q1','u'))
print('Q5 horizontal (bit set)  :', stage_fit('Q5','u'))
print('Q3 vertical   (bit clear):', stage_fit('Q3','v'))
