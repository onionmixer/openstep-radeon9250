import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import tex_oracle as te
obs=pickle.load(open('build/r6h/observed_ff9bdf88.pkl','rb'))
def uv_of(w): return ((w>>16)&0xff)//32, ((w>>8)&0xff)//32
n='XA'; w,h,_=te.tex_of(n); st,tt=te.st_of(n)
s,t=te.interp(st), te.interp(tt)
du=[]; dv=[]
for p,val in obs[n].items():
    u,v=uv_of(val)
    du.append(u - math.floor(s[p]*w)); dv.append(v - math.floor(t[p]*h))
from collections import Counter
print('XA: u - floor(s*8):', dict(Counter(du)), ' v - floor(t*8):', dict(Counter(dv)))
# where does the difference happen -- by the fractional part?
fr=Counter()
for p,val in obs[n].items():
    u,_=uv_of(val); f=s[p]*w - math.floor(s[p]*w)
    fr[(round(float(f),2), u - math.floor(s[p]*w))]+=1
print('by fractional part of s*8:', sorted(fr.items())[:10])
# try the rule u = floor(s*w + 1/2) and others on every case
for rule in [(0,'clamp'),(Fr(1,2),'clamp'),(Fr(-1,2),'clamp')]:
    tot=0
    for c in te.ORDER:
        ww,hh,_=te.tex_of(c); cs,ct=te.st_of(c); ss,tv=te.interp(cs),te.interp(ct)
        for p,val in obs[c].items():
            u,v=uv_of(val)
            mode='clamp' if te.case_rule_of(c)=='clamp' else 'wrap'
            pu=te._index(ss[p]*ww+rule[0], ww, mode); pv=te._index(tv[p]*hh+rule[0], hh, mode)
            tot += (u,v)!=(pu,pv)
    print('rule', rule, 'mismatching pixels over all cases:', tot)
