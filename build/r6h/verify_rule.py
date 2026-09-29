# the measured rule, checked on every case and every covered pixel
import pickle, sys
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import tex_oracle as te
obs=pickle.load(open('build/r6h/observed_ff9bdf88.pkl','rb'))
go=te.go
P=[(go.pos(x,'t16'), go.pos(y,'t16')) for x,y in te.GEOM]
(x0,y0),(x1,y1),(x2,y2)=P
A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
def interp_at(vals, o):
    out={}
    for x,y in go.covered(te.GEOM):
        sx,sy=Fr(x)+o, Fr(y)+o
        w1=((sx-x0)*(y2-y0)-(x2-x0)*(sy-y0))/A; w2=((x1-x0)*(sy-y0)-(sx-x0)*(y1-y0))/A
        out[(x,y)]=(1-w1-w2)*Fr(vals[0])+w1*Fr(vals[1])+w2*Fr(vals[2])
    return out
tot=0
for o in (Fr(0), Fr(1,4)):
    bad=0
    for c in te.ORDER:
        w,h,_=te.tex_of(c); cs,ct=te.st_of(c)
        s,t=interp_at(cs,o), interp_at(ct,o)
        mode='clamp' if te.case_rule_of(c)=='clamp' else 'wrap'
        row=max(w*4, 32)//4                       # the measured row stride
        words=te.texture_words(c)
        for p,val in obs[c].items():
            u=te._index(s[p]*w,w,mode); v=te._index(t[p]*h,h,mode)
            if words[v*row+u] != val: bad+=1
    print('sample at pixel + %-4s, texel = floor(coord*size), row stride = max(w*4, 32): %d misses of %d'
          % (o, bad, sum(len(obs[c]) for c in te.ORDER)))
    tot+=bad
# and the value identity
same=sum(1 for c in te.ORDER for v in obs[c].values() if (v>>24)==0xff and (v&0xff)==0x55)
print('every pixel carries a texel word (alpha ff, low byte 55):', same, 'of', sum(len(obs[c]) for c in te.ORDER))
print('VERIFIED' if tot==0 else 'NOT VERIFIED')
