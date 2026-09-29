import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import tex_oracle as te
from collections import Counter
obs=pickle.load(open('build/r6h/observed_ff9bdf88.pkl','rb'))
def uv_of(w): return ((w>>16)&0xff)//32, ((w>>8)&0xff)//32
for c in te.ORDER:
    w,h,stride=te.tex_of(c); cs,ct=te.st_of(c); s,t=te.interp(cs),te.interp(ct)
    mode = 'clamp' if te.case_rule_of(c)=='clamp' else 'wrap'
    du=Counter(); dv=Counter(); bad=0
    for p,val in obs[c].items():
        u,v=uv_of(val)
        pu=te._index(s[p]*w, w, mode); pv=te._index(t[p]*h, h, mode)
        du[u-pu]+=1; dv[v-pv]+=1
        bad += (u,v)!=(pu,pv)
    print('%-3s (%dx%d stride %2d %s) mismatches %3d   du %s  dv %s' % (c,w,h,stride,mode,bad,dict(du),dict(dv)))
