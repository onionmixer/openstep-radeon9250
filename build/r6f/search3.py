# R6f-2: the gradients held as a FLOAT (mantissa mb bits, rounding m), exact accumulation from a reference
import pickle, sys, math
from fractions import Fraction as Fr
sys.path.insert(0,'tools/r6'); import depth_oracle as do
obs = pickle.load(open('build/r6f/observed_e4d44687.pkl','rb')); go=do.go
def fq(v, mb, m):
    if v == 0: return Fr(0)
    s = -1 if v < 0 else 1; a = abs(Fr(v))
    e = 0
    while Fr(2)**e > a: e -= 1
    while Fr(2)**(e+1) <= a: e += 1
    sc = Fr(2)**(mb - e)
    t = a * sc
    k = math.floor(t) if m in ('floor','tz') else math.floor(t + Fr(1,2)) if m == 'up' else round(t)
    return s * Fr(k) / sc                      # tz == floor of the magnitude (toward zero)
def setup(name):
    pts, zs = do.triangles(name)[0]
    P=[(go.pos(x,'t16'),go.pos(y,'t16')) for x,y in pts]
    (x0,y0),(x1,y1),(x2,y2)=P
    A=(x1-x0)*(y2-y0)-(x2-x0)*(y1-y0)
    bits = do.fmt_bits(name); S = 1 << bits
    Z=[Fr(v)*S for v in zs]
    gx=((Z[1]-Z[0])*(y2-y0)-(Z[2]-Z[0])*(y1-y0))/A
    gy=((Z[2]-Z[0])*(x1-x0)-(Z[1]-Z[0])*(x2-x0))/A
    return P, Z, gx, gy, sorted(go.covered(pts)), S-1
def predict(name, mb, m, ref, zm):
    P, Z, gx, gy, pix, top = setup(name)
    qx, qy = fq(gx, mb, m), fq(gy, mb, m)
    r = {'v0':0,'left':min(range(3),key=lambda i:(P[i][0],P[i][1])),'top':min(range(3),key=lambda i:(P[i][1],P[i][0]))}[ref]
    zr = Z[r] if zm=='exact' else fq(Z[r], mb, m)
    xr, yr = P[r]
    return [max(0,min(top,math.floor(zr + qx*(Fr(2*x+1,2)-xr) + qy*(Fr(2*y+1,2)-yr)))) for x,y in pix], pix
CASES=[n+b for n in do.IORDER for b in ('_24','_16')]
res=[]
for mb in range(12, 25):
    for m in ('floor','tz','up','even'):
        for ref in ('v0','left','top'):
            for zm in ('exact','q'):
                tot=0; per={}
                for name in CASES:
                    got,pix=predict(name,mb,m,ref,zm)
                    d=sum(1 for a,p in zip(got,pix) if a!=obs[name][p]); per[name]=d; tot+=d
                res.append((tot,mb,m,ref,zm,per))
res.sort()
for t in res[:6]: print('misses %5d  mb=%-2d %-5s ref=%-4s zref=%-5s  %s' % (t[0],t[1],t[2],t[3],t[4], [ (k,v) for k,v in t[5].items() if v][:5]))
