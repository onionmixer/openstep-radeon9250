# fit the sample position (and the offset) that explains every case
import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import tex_oracle as te
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
OFFS=[Fr(0), Fr(1,4), Fr(1,2), Fr(3,4), Fr(1)]
best=[]
for ox in OFFS:
    for oy in OFFS:
        for a in (0, Fr(-1,2), Fr(1,2)):
            tot=0; per={}
            for c in ('XA','XB','XC','XD','XG'):      # the 8x8 cases with a known stride
                w,h,_=te.tex_of(c); cs,ct=te.st_of(c)
                s,t=interp_at(cs,ox,oy), interp_at(ct,ox,oy)
                mode='clamp' if te.case_rule_of(c)=='clamp' else 'wrap'
                bad=0
                for p,val in obs[c].items():
                    u,v=uv_of(val)
                    if (te._index(s[p]*w+a,w,mode), te._index(t[p]*h+a,h,mode)) != (u,v): bad+=1
                per[c]=bad; tot+=bad
            best.append((tot, ox, oy, a, per))
best.sort()
for t in best[:5]: print('misses %4d  sample (x+%s, y+%s)  offset %-5s  %s' % (t[0], t[1], t[2], t[3], t[4]))
