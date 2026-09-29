"""R6i-2: try the classic lerp form v = a + ((b - a)*k + r) >> 6 (arithmetic shift = floor) for each
stage, and the symmetric form, to see which one names both stages with one constant."""
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
FORMS={
 'sym':  lambda a,b,k,r: (a*(64-k) + b*k + r) >> 6,
 'lerp': lambda a,b,k,r: a + (((b-a)*k + r) >> 6),
 'lerp255': lambda a,b,k,r: a + (((b-a)*k*255 + r*255) // (64*255)),
}
def fit(case, axis, form):
    w,h,_,pat=pe.tex_of(case); best=[]
    for r in range(64):
        bad=0
        for i0,fu,j0,fv,got in DATA[case]:
            f = fu if axis=='u' else fv
            k = math.floor(f*64)
            word=0
            for lane in range(4):
                t=lambda du,dv: (pe.texel(pat,(i0+du)&7,(j0+dv)&7)>>(8*lane))&0xff
                a,b = (t(0,0), t(1,0)) if axis=='u' else (t(0,0), t(0,1))
                v=FORMS[form](a,b,k,r)
                word |= min(255,max(0,v)) << (8*lane)
            bad += word!=got
        best.append((bad,r))
    best.sort()
    return best[:3]
for form in FORMS:
    print('== %s' % form)
    print('   Q1 u (bit clear):', fit('Q1','u',form))
    print('   Q5 u (bit set)  :', fit('Q5','u',form))
    print('   Q3 v (bit clear):', fit('Q3','v',form))
