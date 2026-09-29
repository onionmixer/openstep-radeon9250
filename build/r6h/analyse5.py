import pickle, sys
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import tex_oracle as te
obs=pickle.load(open('build/r6h/observed_ff9bdf88.pkl','rb'))
go=te.go
P=[(go.pos(x,'t16'), go.pos(y,'t16')) for x,y in te.GEOM]
(x0,y0),(x1,y1),(x2,y2)=P
A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
def interp_at(vals, o=Fr(0)):
    out={}
    for x,y in go.covered(te.GEOM):
        sx,sy=Fr(x)+o, Fr(y)+o
        w1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A; w2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
        out[(x,y)]=(1-w1-w2)*Fr(vals[0])+w1*Fr(vals[1])+w2*Fr(vals[2])
    return out
c='XF'; w,h,stride=te.tex_of(c); cs,ct=te.st_of(c)
s,t=interp_at(cs), interp_at(ct)
words=te.texture_words(c)
print('XF: 4x4 stored with %d-byte rows at 0x20000' % stride)
for assumed in (16, 32, 64):
    bad=sum(1 for p,val in obs[c].items()
            if words[(te._index(t[p]*h,h,'clamp')*assumed)//4 + te._index(s[p]*w,w,'clamp')] != val)
    print('   the sampler assuming a %2d-byte row stride: %3d misses of 276' % (assumed, bad))
# what texels does it actually return, as (u, v) pairs, against the predicted index?
def uv_of(x): return ((x>>16)&0xff)//32, ((x>>8)&0xff)//32
from collections import Counter
pairs=Counter()
for p,val in obs[c].items():
    pu=te._index(s[p]*w,w,'clamp'); pv=te._index(t[p]*h,h,'clamp')
    pairs[((pu,pv), uv_of(val))]+=1
print('   predicted (u,v) -> observed (u,v):')
for k,v in sorted(pairs.items())[:12]: print('     ', k, v)
