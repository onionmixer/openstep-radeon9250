import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import tex_oracle as te
exec(open('build/r6h/analyse3.py').read().split('OFFS=')[0].split("obs=")[0])
obs=pickle.load(open('build/r6h/observed_ff9bdf88.pkl','rb'))
go=te.go
def uv_of(w): return ((w>>16)&0xff)//32, ((w>>8)&0xff)//32
P=[(go.pos(x,'t16'), go.pos(y,'t16')) for x,y in te.GEOM]
(x0,y0),(x1,y1),(x2,y2)=P
A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
def interp_at(vals, ox, oy):
    out={}
    for x,y in go.covered(te.GEOM):
        sx,sy=Fr(x)+ox, Fr(y)+oy
        w1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A; w2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
        out[(x,y)]=(1-w1-w2)*Fr(vals[0])+w1*Fr(vals[1])+w2*Fr(vals[2])
    return out
def misses(ox, oy, cases=('XA','XB','XC','XD','XG'), stride_from_width=True):
    tot=0
    for c in cases:
        w,h,stride=te.tex_of(c); cs,ct=te.st_of(c)
        s,t=interp_at(cs,ox,oy), interp_at(ct,ox,oy)
        mode='clamp' if te.case_rule_of(c)=='clamp' else 'wrap'
        words=te.texture_words(c); row=(w*4 if stride_from_width else stride)//4
        for p,val in obs[c].items():
            u=te._index(s[p]*w,w,mode); v=te._index(t[p]*h,h,mode)
            if words[v*row+u] != val: tot+=1
    return tot
print('fine scan of the sample offset (same in x and y):')
for o in (Fr(-1,2),Fr(-1,4),Fr(-1,8),Fr(0),Fr(1,8),Fr(3,16),Fr(1,4),Fr(5,16),Fr(3,8),Fr(7,16),Fr(1,2)):
    print('   x+%-5s: %4d misses' % (o, misses(o,o)))
print('XE with the width stride:', misses(Fr(0),Fr(0),('XE',), True), ' with its 64-byte stride:', misses(Fr(0),Fr(0),('XE',), False))
print('XF with the width stride:', misses(Fr(0),Fr(0),('XF',), True), ' with its 16-byte stride:', misses(Fr(0),Fr(0),('XF',), False))
