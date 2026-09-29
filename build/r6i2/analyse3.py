"""R6i-2: with the weight quantised to k/64 per axis, what turns (a=0, b=255, k) into the byte?
Family: byte = (255*k + r) >> 6 for r = 0..63, and the same with the vertical mix."""
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
DATA={c:rows(c) for c in ('Q1','Q2','Q3','Q5')}
def fit(cases, r, q=64):
    bad=0; mx=0
    for c in cases:
        w,h,_,pat=pe.tex_of(c)
        for i0,fu,j0,fv,got in DATA[c]:
            ku=math.floor(fu*q); kv=math.floor(fv*q)
            word=0
            for lane in range(4):
                t=lambda du,dv: (pe.texel(pat,(i0+du)&7,(j0+dv)&7)>>(8*lane))&0xff
                # two 1-D mixes, each rounded the same way, then the vertical one
                row0=( (t(0,0)*(q-ku) + t(1,0)*ku) + r ) >> 6
                row1=( (t(0,1)*(q-ku) + t(1,1)*ku) + r ) >> 6
                v=( (row0*(q-kv) + row1*kv) + r ) >> 6
                word |= min(255,max(0,v)) << (8*lane)
            bad += word!=got
            for lane in range(4):
                mx=max(mx, abs(((word>>(8*lane))&0xff)-((got>>(8*lane))&0xff)))
    return mx, bad
for grp,cases in (('default',('Q1','Q2','Q3')), ('bitset',('Q5',))):
    res=[(fit(cases,r), r) for r in range(64)]
    res.sort()
    print('%s: best (max, off), r: %s' % (grp, res[:4]))
